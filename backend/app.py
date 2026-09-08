import os
import json
import time
import asyncio
import logging
import threading
import inspect
import re

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from functools import wraps

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_compress import Compress
from flask_socketio import SocketIO, emit

from config2 import (
    DATABASE_URL,
    DB_CONNECT_URL,
    DB_SCHEMA,
    UTC,
    KENYA,
    MAX_CONCURRENT,
    BASE_URL,
    HEADERS,
    COMPETITION_MAP,
    PREDICTORS_DIR,
)


# =========================================================
# POSTGRES DRIVER
# =========================================================

try:
    import psycopg
    from psycopg.rows import dict_row

    _PSYCOPG3 = True

except Exception:
    _PSYCOPG3 = False

    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

    except Exception as exc:
        raise RuntimeError(
            "Postgres driver not available. "
            "Install psycopg3 or psycopg2."
        ) from exc


# =========================================================
# CONFIGURATION
# =========================================================

LOG_FILE = os.environ.get(
    "API_LOG_FILE",
    "api.json.log"
)

BANK_ROLL = float(
    os.environ.get("BANK_ROLL", "1000")
)

MAX_LIMIT = int(
    os.environ.get("MAX_LIMIT", "80000")
)

DEFAULT_LIMIT = 15

CACHE_TTL = {
    "/matches": 30,
}

DEFAULT_RATE = {
    "calls": 30,
    "per_seconds": 60,
}

UPCOMING_STATUSES = [
    "SCHEDULED",
    "TIMED",
    "NS",
]

# Kenya / East Africa Time
EAT = KENYA


# =========================================================
# FLASK APP
# =========================================================

app = Flask("lilymac_predictions_hub")

CORS(app)

app.config["COMPRESS_LEVEL"] = 6
app.config["COMPRESS_MIN_SIZE"] = 500

Compress(app)

# =========================================================
# SOCKET.IO
# =========================================================

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    ping_interval=25,
    ping_timeout=60,
)


# =========================================================
# DATE NORMALIZATION
# =========================================================

def _parse_match_datetime(raw):
    """
    Convert datetime/date strings into UTC-aware datetime.
    Naive datetimes are treated as UTC.
    """

    if raw is None:
        return None

    if isinstance(raw, datetime):
        dt = raw

    else:
        text = str(raw).strip()

        try:
            dt = datetime.fromisoformat(
                text.replace("Z", "+00:00")
            )

        except Exception:
            try:
                dt = parsedate_to_datetime(text)
            except Exception:
                return None

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt.astimezone(timezone.utc)


def normalize_dates(obj):
    """
    Recursively convert datetime objects to ISO strings.

    Also normalizes:
        utcdate
        utcDate

    and automatically adds:
        localDate

    for UTC match dates.
    """

    if isinstance(obj, dict):

        new_obj = {}

        for key, value in obj.items():

            normalized_key = (
                "utcDate"
                if key.lower() == "utcdate"
                else key
            )

            if isinstance(value, datetime):

                try:
                    dt_utc = _parse_match_datetime(value)

                    if dt_utc:

                        new_obj[normalized_key] = (
                            dt_utc.isoformat()
                        )

                        if normalized_key == "utcDate":
                            new_obj["localDate"] = (
                                dt_utc
                                .astimezone(KENYA)
                                .isoformat()
                            )

                    else:
                        new_obj[normalized_key] = None

                except Exception:
                    new_obj[normalized_key] = None

            elif isinstance(value, (dict, list)):

                new_obj[normalized_key] = (
                    normalize_dates(value)
                )

            else:

                # Only attempt string parsing for values
                # that look like dates.
                if (
                    isinstance(value, str)
                    and (
                        "gmt" in value.lower()
                        or "t" in value.lower()
                        or value.endswith("Z")
                    )
                ):

                    try:
                        dt = _parse_match_datetime(value)

                        if dt:

                            new_obj[normalized_key] = (
                                dt.isoformat()
                            )

                            if normalized_key == "utcDate":
                                new_obj["localDate"] = (
                                    dt
                                    .astimezone(KENYA)
                                    .isoformat()
                                )

                        else:
                            new_obj[normalized_key] = value

                    except Exception:
                        new_obj[normalized_key] = value

                else:
                    new_obj[normalized_key] = value

        return new_obj

    if isinstance(obj, list):
        return [
            normalize_dates(item)
            for item in obj
        ]

    return obj


@app.after_request
def apply_global_json_fix(response):
    """
    Normalize datetime values in JSON responses.
    """

    try:

        if response.is_json:

            data = response.get_json()

            fixed = normalize_dates(data)

            response.set_data(
                json.dumps(
                    fixed,
                    default=str
                )
            )

            response.headers["Content-Type"] = (
                "application/json"
            )

    except Exception:
        pass

    return response


# =========================================================
# LOGGING
# =========================================================

logger = logging.getLogger(
    "lilymac_api"
)

logger.setLevel(logging.INFO)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

console_fmt = logging.Formatter(
    "%(asctime)s %(levelname)s %(message)s"
)

ch.setFormatter(console_fmt)

fh = logging.FileHandler(LOG_FILE)
fh.setLevel(logging.INFO)
fh.setFormatter(console_fmt)

if not logger.handlers:

    logger.addHandler(ch)
    logger.addHandler(fh)

else:

    logger.handlers = [
        ch,
        fh
    ]


def log_json(level: str, **kwargs):

    payload = {
        "ts": (
            datetime.now(UTC)
            .astimezone(KENYA)
            .isoformat()
        ),
        **kwargs,
    }

    message = json.dumps(
        payload,
        default=str
    )

    if level == "error":
        logger.error(message)

    elif level == "warning":
        logger.warning(message)

    else:
        logger.info(message)


# =========================================================
# DATABASE
# =========================================================

_db_lock = threading.RLock()

_named_param_pattern = re.compile(
    r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)"
)


def _connect_db():
    """
    Open a PostgreSQL connection using henry_schema.
    """

    if _PSYCOPG3:

        return psycopg.connect(
            DB_CONNECT_URL,
            row_factory=dict_row,
            options=(
                "-c search_path=henry_schema,public"
            ),
        )

    return psycopg2.connect(
        DB_CONNECT_URL,
        options=(
            "-c search_path=henry_schema,public"
        ),
    )


def _run_sync_or_async(callable_or_coro):
    """
    Execute sync result or awaitable safely.
    """

    if inspect.isawaitable(
        callable_or_coro
    ):

        try:
            loop = asyncio.get_running_loop()

        except RuntimeError:
            loop = None

        if loop and loop.is_running():

            result_box = {}
            error_box = {}

            def _runner():

                try:
                    result_box["value"] = (
                        asyncio.run(
                            callable_or_coro
                        )
                    )

                except Exception as exc:
                    error_box["error"] = exc

            thread = threading.Thread(
                target=_runner,
                daemon=True,
            )

            thread.start()
            thread.join()

            if error_box.get("error"):
                raise error_box["error"]

            return result_box.get("value")

        return asyncio.run(
            callable_or_coro
        )

    return callable_or_coro


def _normalize_sql_params(sql: str, params):

    if params is None:
        params = ()

    if isinstance(params, (list, tuple)):

        return sql, tuple(params)

    if not isinstance(params, dict):

        return sql, (params,)

    ordered_keys = []

    def repl(match):

        key = match.group(1)

        ordered_keys.append(key)

        return "%s"

    normalized_sql = (
        _named_param_pattern.sub(
            repl,
            sql
        )
    )

    try:

        normalized_params = tuple(
            params[key]
            for key in ordered_keys
        )

    except KeyError as exc:

        raise KeyError(
            f"Missing SQL parameter: "
            f"{exc.args[0]}"
        ) from exc

    return (
        normalized_sql,
        normalized_params
    )


def _fetchall_dicts(cur):

    rows = (
        cur.fetchall()
        if cur.description
        else []
    )

    return [
        dict(row)
        for row in rows
    ]


def _call_db(
    fn,
    sql: str,
    params=()
):

    normalized_sql, normalized_params = (
        _normalize_sql_params(
            sql,
            params
        )
    )

    try:

        with _db_lock:

            conn = _connect_db()

            try:

                if _PSYCOPG3:

                    with conn.cursor() as cur:

                        result = fn(
                            cur,
                            normalized_sql,
                            normalized_params,
                        )

                        conn.commit()

                        return _run_sync_or_async(
                            result
                        )

                else:

                    with conn.cursor(
                        cursor_factory=RealDictCursor
                    ) as cur:

                        result = fn(
                            cur,
                            normalized_sql,
                            normalized_params,
                        )

                        conn.commit()

                        return _run_sync_or_async(
                            result
                        )

            finally:

                conn.close()

    except Exception as exc:

        log_json(
            "error",
            event="db_call_failed",
            sql=normalized_sql[:180],
            error=str(exc),
        )

        raise


def _query_fn(
    cur,
    sql,
    params
):

    cur.execute(
        sql,
        params
    )

    return _fetchall_dicts(cur)


def _execute_fn(
    cur,
    sql,
    params
):

    cur.execute(
        sql,
        params
    )

    if cur.description:
        return _fetchall_dicts(cur)

    return cur.rowcount


def db_query_list(
    sql: str,
    params=()
):

    try:

        rows = _call_db(
            _query_fn,
            sql,
            params
        )

        return rows or []

    except Exception as exc:

        log_json(
            "error",
            event="db_query_failed",
            sql=sql[:180],
            error=str(exc),
        )

        return []


def db_query_single(
    sql: str,
    params=()
):

    rows = db_query_list(
        sql,
        params
    )

    return (
        rows[0]
        if rows
        else None
    )


def db_execute(
    sql: str,
    params=()
):

    try:

        return _call_db(
            _execute_fn,
            sql,
            params
        )

    except Exception as exc:

        log_json(
            "error",
            event="db_execute_failed",
            sql=sql[:180],
            error=str(exc),
        )

        raise


def query(
    sql,
    params=(),
    single=False
):

    if single:
        return db_query_single(
            sql,
            params
        )

    return db_query_list(
        sql,
        params
    )


def execute(
    sql,
    params=()
):

    return db_execute(
        sql,
        params
    )


async def fetch_rows(
    sql,
    params=()
):

    return db_query_list(
        sql,
        params
    )


# =========================================================
# CACHE
# =========================================================

_cache = {}

_cache_lock = threading.Lock()

CACHE_MAX_ITEMS = 5000


def cache_response(ttl: int):

    def decorator(fn):

        @wraps(fn)
        def wrapper(
            *args,
            **kwargs
        ):

            key = (
                f"{request.path}:"
                f"{tuple(sorted(request.args.items()))}"
            )

            now_ts = time.time()

            with _cache_lock:

                entry = _cache.get(key)

                if (
                    entry
                    and entry["expire"] > now_ts
                ):

                    return entry["value"]

            response = fn(
                *args,
                **kwargs
            )

            with _cache_lock:

                expired_keys = [
                    key
                    for key, value
                    in _cache.items()
                    if value.get(
                        "expire",
                        0
                    ) <= now_ts
                ]

                for key in expired_keys:
                    _cache.pop(
                        key,
                        None
                    )

                if len(_cache) >= CACHE_MAX_ITEMS:

                    items_sorted = sorted(
                        _cache.items(),
                        key=lambda item:
                            item[1].get(
                                "expire",
                                0
                            ),
                    )

                    to_remove = max(
                        1,
                        CACHE_MAX_ITEMS // 10
                    )

                    for key, _ in items_sorted[
                        :to_remove
                    ]:

                        _cache.pop(
                            key,
                            None
                        )

                _cache[key] = {
                    "value": response,
                    "expire": now_ts + ttl,
                }

            return response

        return wrapper

    return decorator


# =========================================================
# RATE LIMITER
# =========================================================

_rate_store = defaultdict(list)

_rate_lock = threading.Lock()


def get_client_ip():

    forwarded = request.headers.get(
        "X-Forwarded-For"
    )

    if forwarded:
        return (
            forwarded
            .split(",")[0]
            .strip()
        )

    return (
        request.remote_addr
        or "unknown"
    )


def rate_limit(
    calls=None,
    per_seconds=None
):

    calls = (
        calls
        or DEFAULT_RATE["calls"]
    )

    per_seconds = (
        per_seconds
        or DEFAULT_RATE["per_seconds"]
    )

    def decorator(fn):

        @wraps(fn)
        def wrapper(
            *args,
            **kwargs
        ):

            ip = get_client_ip()

            key = (
                f"{fn.__name__}:{ip}"
            )

            now = time.time()

            window = (
                now - per_seconds
            )

            with _rate_lock:

                timestamps = (
                    _rate_store[key]
                )

                timestamps[:] = [
                    t
                    for t in timestamps
                    if t > window
                ]

                if len(timestamps) >= calls:

                    return jsonify({
                        "error":
                            "rate limit exceeded",
                        "limit":
                            calls,
                        "window_seconds":
                            per_seconds,
                    }), 429

                timestamps.append(now)

            return fn(
                *args,
                **kwargs
            )

        return wrapper

    return decorator


# =========================================================
# PREDICTION HELPERS
# =========================================================

ALLOWED_LABELS = {
    "Home Win",
    "Away Win",
    "Draw",
}


def now_kenya_iso():

    return (
        datetime.now(UTC)
        .astimezone(KENYA)
        .isoformat()
    )


def cap_limit(
    val,
    default=DEFAULT_LIMIT,
    max_limit=MAX_LIMIT
):

    try:

        val = int(val)

        if val <= 0:
            return default

        return min(
            val,
            max_limit
        )

    except Exception:

        return default


def parse_prediction_json(
    pred_json_text
):

    if not pred_json_text:
        return None

    if isinstance(
        pred_json_text,
        dict
    ):
        return pred_json_text

    try:

        return json.loads(
            pred_json_text
        )

    except Exception:

        return None


def normalize_label(
    label: str
):

    if not label:
        return None

    return (
        label
        .strip()
        .lower()
        .replace(" ", "_")
    )


def extract_best_prediction_from_pj(
    pj
):

    if not pj or not isinstance(
        pj,
        dict
    ):

        return None, 0.0

    home = (
        pj.get("home_win")
        or pj.get("home")
        or pj.get("homeProbability")
        or pj.get("p_home")
    )

    draw = (
        pj.get("draw")
        or pj.get("p_draw")
    )

    away = (
        pj.get("away_win")
        or pj.get("away")
        or pj.get("awayProbability")
        or pj.get("p_away")
    )

    if any(
        isinstance(
            value,
            (int, float)
        )
        for value in (
            home,
            draw,
            away,
        )
    ):

        home_v = (
            float(home)
            if isinstance(
                home,
                (int, float)
            )
            else 0.0
        )

        draw_v = (
            float(draw)
            if isinstance(
                draw,
                (int, float)
            )
            else 0.0
        )

        away_v = (
            float(away)
            if isinstance(
                away,
                (int, float)
            )
            else 0.0
        )

        return max(
            [
                ("Home Win", home_v),
                ("Draw", draw_v),
                ("Away Win", away_v),
            ],
            key=lambda item: item[1],
        )

    probs = (
        pj.get("probabilities")
        or pj.get("probs")
        or pj.get("probability")
        or pj.get("probabilities_map")
    )

    if isinstance(
        probs,
        dict
    ) and probs:

        def get_prob(key):

            return (
                probs.get(key)
                or probs.get(key.lower())
                or probs.get(key.upper())
                or 0.0
            )

        candidates = [
            (
                "Home Win",
                get_prob("Home Win")
            ),
            (
                "Draw",
                get_prob("Draw")
            ),
            (
                "Away Win",
                get_prob("Away Win")
            ),
            (
                "Home Win",
                get_prob("home_win")
            ),
            (
                "Draw",
                get_prob("draw")
            ),
            (
                "Away Win",
                get_prob("away_win")
            ),
        ]

        label, prob = max(
            candidates,
            key=lambda item:
                item[1] or 0.0
        )

        try:
            prob = float(prob)
        except Exception:
            prob = 0.0

        return label, prob

    pred = (
        pj.get("prediction")
        or pj.get("pred")
        or pj.get("label")
    )

    prob = (
        pj.get("confidence")
        or pj.get("prob")
        or pj.get("score")
    )

    if pred:

        mapping = {
            "h": "Home Win",
            "1": "Home Win",
            "home": "Home Win",
            "home_win": "Home Win",

            "d": "Draw",
            "draw": "Draw",

            "a": "Away Win",
            "2": "Away Win",
            "away": "Away Win",
            "away_win": "Away Win",
        }

        pred_label = mapping.get(
            str(pred)
            .strip()
            .lower(),
            str(pred)
        )

        try:

            prob_f = (
                float(prob)
                if prob is not None
                else 0.0
            )

        except Exception:

            prob_f = 0.0

        return (
            pred_label,
            prob_f
        )

    return None, 0.0


def result_from_score(
    home,
    away
):

    if home is None or away is None:
        return None

    if home > away:
        return "Home Win"

    if away > home:
        return "Away Win"

    return "Draw"


def calculate_kelly(
    prob,
    odds
):

    if odds <= 1 or prob <= 0:
        return 0

    try:

        return max(
            (
                odds * prob - 1
            ) / (
                odds - 1
            ),
            0
        )

    except Exception:

        return 0


# =========================================================
# ROOT / HEALTH
# =========================================================

@app.route("/")
def root():

    return jsonify({
        "status": "ok",
        "service":
            "Lilymac Prediction Hub API",
        "timestamp":
            now_kenya_iso(),
    })


@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "service":
            "prediction_api",
        "time":
            now_kenya_iso(),
    })


# =========================================================
# DATABASE DEBUG
# =========================================================

@app.route(
    "/debug/db",
    methods=["GET"]
)
def debug_db():

    conn = None

    try:

        conn = _connect_db()

        if _PSYCOPG3:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        current_database(),
                        current_schema()
                """)

                db, schema = (
                    cur.fetchone()
                )

                cur.execute(
                    "SHOW search_path"
                )

                search_path = (
                    cur.fetchone()[0]
                )

                cur.execute("""
                    SELECT COUNT(*)
                    FROM matches
                """)

                matches = (
                    cur.fetchone()[0]
                )

                cur.execute("""
                    SELECT COUNT(*)
                    FROM matches
                    WHERE status IN (
                        'SCHEDULED',
                        'TIMED'
                    )
                """)

                upcoming = (
                    cur.fetchone()[0]
                )

        else:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        current_database(),
                        current_schema()
                """)

                db, schema = (
                    cur.fetchone()
                )

                cur.execute(
                    "SHOW search_path"
                )

                search_path = (
                    cur.fetchone()[0]
                )

                cur.execute("""
                    SELECT COUNT(*)
                    FROM matches
                """)

                matches = (
                    cur.fetchone()[0]
                )

                cur.execute("""
                    SELECT COUNT(*)
                    FROM matches
                    WHERE status IN (
                        'SCHEDULED',
                        'TIMED'
                    )
                """)

                upcoming = (
                    cur.fetchone()[0]
                )

        return jsonify({
            "database": db,
            "schema": schema,
            "search_path": search_path,
            "matches": matches,
            "upcoming": upcoming,
        })

    except Exception as exc:

        return jsonify({
            "error": str(exc)
        }), 500

    finally:

        if conn:
            conn.close()


# =========================================================
# OPTIMIZED DASHBOARD
# =========================================================

@app.route(
    "/dashboard",
    methods=["GET"]
)
def dashboard():

    prediction_filter = (
        request.args.get(
            "prediction"
        )
    )

    threshold_filter = (
        request.args.get(
            "threshold"
        )
    )

    page = max(
        request.args.get(
            "page",
            1,
            type=int
        ),
        1
    )

    limit = cap_limit(
        request.args.get(
            "limit",
            100
        ),
        default=100,
        max_limit=1000,
    )

    offset = (
        page - 1
    ) * limit

    # -----------------------------------------------------
    # ALL DASHBOARD STATISTICS IN ONE SQL QUERY
    # -----------------------------------------------------

    summary_sql = """
        SELECT

            COUNT(*) FILTER (
                WHERE status = 'FINISHED'
                  AND prediction = 'HOME'
            ) AS home_count,

            COUNT(*) FILTER (
                WHERE status = 'FINISHED'
                  AND prediction = 'AWAY'
            ) AS away_count,

            COUNT(*) FILTER (
                WHERE status = 'FINISHED'
                  AND prediction = 'DRAW'
            ) AS draw_count,

            COUNT(*) FILTER (
                WHERE status = 'FINISHED'
                  AND prediction = 'HOME'
                  AND LOWER(result) = 'won'
            ) AS home_wins,

            COUNT(*) FILTER (
                WHERE status = 'FINISHED'
                  AND prediction = 'AWAY'
                  AND LOWER(result) = 'won'
            ) AS away_wins,

            COUNT(*) FILTER (
                WHERE status = 'FINISHED'
                  AND prediction = 'DRAW'
                  AND LOWER(result) = 'won'
            ) AS draw_wins,

            COUNT(*) FILTER (
                WHERE status = 'FINISHED'
                  AND prediction = 'YES'
            ) AS yes_count,

            COUNT(*) FILTER (
                WHERE status = 'FINISHED'
                  AND prediction = 'YES'
                  AND LOWER(result) = 'won'
            ) AS yes_wins,

            COUNT(*) FILTER (
                WHERE status = 'FINISHED'
                  AND prediction = 'OVER'
            ) AS over_count,

            COUNT(*) FILTER (
                WHERE status = 'FINISHED'
                  AND prediction = 'OVER'
                  AND LOWER(result) = 'won'
            ) AS over_wins,

            COUNT(*) FILTER (
                WHERE status = 'FINISHED'
                  AND LOWER(result)
                    IN ('won', 'lost')
            ) AS general_count,

            COUNT(*) FILTER (
                WHERE status = 'FINISHED'
                  AND LOWER(result) = 'won'
            ) AS general_wins

        FROM dashboard
    """

    summary = (
        db_query_single(
            summary_sql
        )
        or {}
    )

    def safe_int(value):
        try:
            return int(value or 0)
        except Exception:
            return 0

    def percentage(
        wins,
        total
    ):

        wins = float(
            wins or 0
        )

        total = float(
            total or 0
        )

        if total <= 0:
            return 0.0

        return round(
            wins / total * 100,
            2
        )

    home_count = safe_int(
        summary.get(
            "home_count"
        )
    )

    away_count = safe_int(
        summary.get(
            "away_count"
        )
    )

    draw_count = safe_int(
        summary.get(
            "draw_count"
        )
    )

    yes_count = safe_int(
        summary.get(
            "yes_count"
        )
    )

    over_count = safe_int(
        summary.get(
            "over_count"
        )
    )

    general_count = safe_int(
        summary.get(
            "general_count"
        )
    )

    match_outcome_counts = {
        "HOME": home_count,
        "AWAY": away_count,
        "DRAW": draw_count,
    }

    match_outcome_win_rate = {
        "HOME": percentage(
            summary.get("home_wins"),
            home_count,
        ),

        "AWAY": percentage(
            summary.get("away_wins"),
            away_count,
        ),

        "DRAW": percentage(
            summary.get("draw_wins"),
            draw_count,
        ),
    }

    # -----------------------------------------------------
    # FILTERS
    # -----------------------------------------------------

    conditions = []

    params = {}

    if prediction_filter:

        conditions.append(
            "UPPER(prediction) = "
            "UPPER(:prediction)"
        )

        params["prediction"] = (
            prediction_filter
        )

    if threshold_filter:

        conditions.append(
            "CAST(threshold AS TEXT) = "
            ":threshold"
        )

        params["threshold"] = (
            threshold_filter
        )

    where_sql = ""

    if conditions:

        where_sql = (
            "WHERE "
            + " AND ".join(
                conditions
            )
        )

    # -----------------------------------------------------
    # FILTERED COUNT
    # -----------------------------------------------------

    count_row = (
        db_query_single(
            f"""
                SELECT COUNT(*) AS count
                FROM dashboard
                {where_sql}
            """,
            params,
        )
        or {}
    )

    total_rows = safe_int(
        count_row.get("count")
    )

    # -----------------------------------------------------
    # PAGINATED DATA
    # -----------------------------------------------------

    rows_params = dict(params)

    rows_params["limit"] = limit
    rows_params["offset"] = offset

    rows = db_query_list(
        f"""
            SELECT *
            FROM dashboard
            {where_sql}
            ORDER BY
                match_time DESC NULLS LAST
            LIMIT :limit
            OFFSET :offset
        """,
        rows_params,
    )

    return jsonify({

        "status": "ok",

        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_rows,
            "pages": (
                (
                    total_rows
                    + limit
                    - 1
                ) // limit
                if limit
                else 0
            ),
        },

        "match_outcome_win_rate":
            match_outcome_win_rate,

        "match_outcome_counts":
            match_outcome_counts,

        "yes_win_rate":
            percentage(
                summary.get(
                    "yes_wins"
                ),
                yes_count,
            ),

        "yes_count":
            yes_count,

        "over_win_rate":
            percentage(
                summary.get(
                    "over_wins"
                ),
                over_count,
            ),

        "over_count":
            over_count,

        "general_win_rate":
            percentage(
                summary.get(
                    "general_wins"
                ),
                general_count,
            ),

        "general_count":
            general_count,

        "matches":
            rows,
    })


# =========================================================
# GROUPED PREDICTIONS
# =========================================================

@app.route(
    "/predictions/match/grouped",
    methods=["GET"]
)
def grouped_predictions():

    home = request.args.get(
        "home"
    ) or None

    away = request.args.get(
        "away"
    ) or None

    match_id = request.args.get(
        "match_id"
    ) or None

    limit = cap_limit(
        request.args.get(
            "limit",
            50
        ),
        default=50,
        max_limit=500,
    )

    now = (
        datetime.now(UTC)
        .isoformat()
    )

    query_sql = """
        SELECT
            m.id,
            m.home_team_name,
            m.away_team_name,
            m.utcdate AS "utcDate"
        FROM matches m

        WHERE m.utcdate > :now

          AND EXISTS (
              SELECT 1
              FROM models mo
              WHERE mo.match_id = m.id
          )
    """

    params = {
        "now": now
    }

    if home:

        query_sql += """
            AND m.home_team_name ILIKE :home
        """

        params["home"] = (
            f"%{home}%"
        )

    if away:

        query_sql += """
            AND m.away_team_name ILIKE :away
        """

        params["away"] = (
            f"%{away}%"
        )

    if match_id:

        query_sql += """
            AND m.id = :match_id
        """

        params["match_id"] = match_id

    query_sql += """
        ORDER BY m.utcdate ASC
        LIMIT :limit
    """

    params["limit"] = limit

    matches = db_query_list(
        query_sql,
        params
    )

    if not matches:

        return jsonify({
            "count": 0,
            "matches": [],
        })

    placeholders = []

    model_params = {}

    for index, match in enumerate(
        matches
    ):

        key = f"mid{index}"

        placeholders.append(
            f":{key}"
        )

        model_params[key] = (
            match["id"]
        )

    models_sql = f"""
        SELECT
            match_id,
            model_version,
            prediction_json,
            confidence
        FROM models
        WHERE match_id IN (
            {", ".join(placeholders)}
        )
        ORDER BY
            match_id,
            model_version
    """

    model_rows = db_query_list(
        models_sql,
        model_params
    )

    models_by_match = (
        defaultdict(list)
    )

    for row in model_rows:

        mid = row.get(
            "match_id"
        )

        pred = parse_prediction_json(
            row.get(
                "prediction_json"
            )
        ) or {}

        label = pred.get(
            "prediction",
            "Unknown"
        )

        models_by_match[mid].append({

            "model_version":
                row.get(
                    "model_version"
                ),

            "probabilities":
                pred.get(
                    "probabilities",
                    {}
                ),

            "confidence":
                row.get(
                    "confidence"
                ),

            "_prediction":
                label,
        })

    result = []

    for match in matches:

        mid = match["id"]

        grouped = (
            defaultdict(list)
        )

        for model in (
            models_by_match.get(
                mid,
                []
            )
        ):

            label = model.pop(
                "_prediction",
                "Unknown"
            )

            grouped[
                label
            ].append(model)

        grouped_list = []

        for label, model_list in (
            grouped.items()
        ):

            avg_conf = (

                sum(
                    (
                        m.get(
                            "confidence"
                        )
                        or 0
                    )
                    for m in model_list
                )
                / len(model_list)

                if model_list
                else 0
            )

            grouped_list.append({

                "prediction":
                    label,

                "num_models":
                    len(model_list),

                "avg_confidence":
                    round(
                        avg_conf,
                        3
                    ),

                "models":
                    model_list,
            })

        grouped_list.sort(
            key=lambda item: (
                item["num_models"],
                item["avg_confidence"],
            ),
            reverse=True,
        )

        result.append({

            "match_id":
                match["id"],

            "home":
                match[
                    "home_team_name"
                ],

            "away":
                match[
                    "away_team_name"
                ],

            "utcDate":
                match[
                    "utcDate"
                ],

            "grouped_predictions":
                grouped_list,
        })

    return jsonify({
        "count":
            len(result),

        "matches":
            result,
    })


# =========================================================
# BOOKMARKS
# =========================================================

@app.route(
    "/bookmark/all",
    methods=["GET"]
)
def all_bookmarks():

    model_version = (
        request.args.get(
            "model_version"
        )
    )

    sql = """
        SELECT
            b.*
        FROM bookmark b
        WHERE b.match_time >
              (NOW() AT TIME ZONE 'UTC')
    """

    params = {}

    if model_version:

        sql += """
            AND EXISTS (
                SELECT 1
                FROM models md
                WHERE md.match_id = b.match_id
                  AND md.model_version =
                      :model_version
            )
        """

        params[
            "model_version"
        ] = model_version

    sql += """
        ORDER BY b.match_time ASC
    """

    rows = db_query_list(
        sql,
        params
    )

    bookmarks = []

    numeric_fields = [
        "home_odds",
        "draw_odds",
        "away_odds",
        "over05",
        "under05",
        "over15",
        "under15",
        "over25",
        "under25",
        "over35",
        "under35",
        "gg_odds",
        "ng_odds",
        "p_home",
        "p_draw",
        "p_away",
    ]

    for row in rows:

        bookmark = dict(row)

        match_time = (
            bookmark.get(
                "match_time"
            )
        )

        dt = _parse_match_datetime(
            match_time
        )

        bookmark["match_time"] = (
            dt.isoformat()
            if dt
            else None
        )

        bookmark["localDate"] = (
            dt
            .astimezone(EAT)
            .isoformat()
            if dt
            else None
        )

        for field in numeric_fields:

            if field not in bookmark:
                continue

            try:

                bookmark[field] = (
                    float(
                        bookmark[field]
                    )
                    if bookmark[field]
                    not in (
                        None,
                        ""
                    )
                    else None
                )

            except Exception:

                bookmark[field] = None

        bookmarks.append(
            bookmark
        )

    return jsonify({
        "status": "ok",
        "count":
            len(bookmarks),
        "bookmarks":
            bookmarks,
    })


# =========================================================
# TEAM MATCH OVERVIEW
# =========================================================

@app.route(
    "/team-match-overview",
    methods=["GET"]
)
def team_match_overview():

    match_id = request.args.get(
        "match_id"
    )

    h2h_limit = cap_limit(
        request.args.get(
            "h2h_limit"
        ),
        default=5
    )

    model_version = request.args.get(
        "model_version"
    )

    if not match_id:

        return jsonify({
            "error":
                "match_id is required"
        }), 400

    try:

        match_id = int(
            match_id
        )

    except ValueError:

        return jsonify({
            "error":
                "match_id must be an integer"
        }), 400

    match_row = db_query_single(
        """
            SELECT
                home_team_id,
                away_team_id,
                home_team_name,
                away_team_name
            FROM matches
            WHERE id = :match_id
        """,
        {
            "match_id":
                match_id
        }
    )

    if not match_row:

        return jsonify({
            "error":
                "match_id not found"
        }), 404

    home_team_id = (
        match_row[
            "home_team_id"
        ]
    )

    away_team_id = (
        match_row[
            "away_team_id"
        ]
    )

    h2h_rows = db_query_list(
        """
            SELECT
                id AS match_id,
                home_team_id,
                away_team_id,
                home_team_name,
                away_team_name,
                home_score,
                away_score,
                utcDate AS date_played

            FROM matches

            WHERE (
                home_team_id = :home_id
                AND away_team_id = :away_id
            )

            OR (
                home_team_id = :away_id
                AND away_team_id = :home_id
            )

            ORDER BY utcDate DESC
            LIMIT :limit
        """,
        {
            "home_id":
                home_team_id,

            "away_id":
                away_team_id,

            "limit":
                h2h_limit,
        }
    )

    home_wins = 0
    away_wins = 0
    draws = 0

    home_goals = 0
    away_goals = 0

    home_form = []
    away_form = []

    for match in h2h_rows:

        home_score = match.get(
            "home_score"
        )

        away_score = match.get(
            "away_score"
        )

        if (
            home_score is None
            or away_score is None
        ):
            continue

        home_goals += home_score
        away_goals += away_score

        if home_score > away_score:

            if (
                match[
                    "home_team_id"
                ]
                == home_team_id
            ):

                home_wins += 1

                home_form.append("W")
                away_form.append("L")

            else:

                away_wins += 1

                home_form.append("L")
                away_form.append("W")

        elif away_score > home_score:

            if (
                match[
                    "away_team_id"
                ]
                == home_team_id
            ):

                home_wins += 1

                home_form.append("W")
                away_form.append("L")

            else:

                away_wins += 1

                home_form.append("L")
                away_form.append("W")

        else:

            draws += 1

            home_form.append("D")
            away_form.append("D")

    total = (
        home_wins
        + away_wins
        + draws
    )

    h2h_stats = {

        "total_matches":
            total,

        "home_wins":
            home_wins,

        "away_wins":
            away_wins,

        "draws":
            draws,

        "avg_home_goals":
            round(
                home_goals / total,
                2
            )
            if total
            else 0,

        "avg_away_goals":
            round(
                away_goals / total,
                2
            )
            if total
            else 0,

        "home_form":
            "".join(
                home_form
            ),

        "away_form":
            "".join(
                away_form
            ),

        "home_win_rate":
            round(
                home_wins
                / total
                * 100,
                2
            )
            if total
            else 0,

        "away_win_rate":
            round(
                away_wins
                / total
                * 100,
                2
            )
            if total
            else 0,

        "draw_rate":
            round(
                draws
                / total
                * 100,
                2
            )
            if total
            else 0,

        "prediction_suggestion":
            (
                f"Home: "
                f"{round(home_wins / total * 100, 2) if total else 0}%, "
                f"Draw: "
                f"{round(draws / total * 100, 2) if total else 0}%, "
                f"Away: "
                f"{round(away_wins / total * 100, 2) if total else 0}%"
            ),

        "matches":
            h2h_rows,
    }

    pred_params = {
        "home_id":
            home_team_id,

        "away_id":
            away_team_id,
    }

    pred_query = """
        SELECT
            p.id,
            p.match_id,
            p.prediction_json,
            p.confidence,
            p.generated_at,

            m.home_score,
            m.away_score,

            m.home_team_name,
            m.away_team_name

        FROM predictions p

        JOIN matches m
          ON p.match_id = m.id

        WHERE (
            m.home_team_id = :home_id
            AND m.away_team_id = :away_id
        )

        OR (
            m.home_team_id = :away_id
            AND m.away_team_id = :home_id
        )

        AND m.home_score IS NOT NULL
        AND m.away_score IS NOT NULL
    """

    if model_version:

        pred_query += """
            AND p.model_version =
                :model_version
        """

        pred_params[
            "model_version"
        ] = model_version

    pred_query += """
        ORDER BY
            p.generated_at DESC
        LIMIT 50
    """

    rows = db_query_list(
        pred_query,
        pred_params
    )

    past_predictions = []

    for row in rows:

        pj = (
            parse_prediction_json(
                row.get(
                    "prediction_json"
                )
            )
            or {}
        )

        pred_label, prob = (
            extract_best_prediction_from_pj(
                pj
            )
        )

        pred_norm = normalize_label(
            pred_label
        )

        actual = normalize_label(
            result_from_score(
                row.get(
                    "home_score"
                ),
                row.get(
                    "away_score"
                )
            )
        )

        past_predictions.append({

            "id":
                row.get("id"),

            "match_id":
                row.get("match_id"),

            "home_team":
                row.get(
                    "home_team_name"
                ),

            "away_team":
                row.get(
                    "away_team_name"
                ),

            "prediction":
                pred_label,

            "probabilities":
                pj.get(
                    "probabilities"
                )
                if isinstance(
                    pj,
                    dict
                )
                else None,

            "confidence":
                row.get(
                    "confidence"
                )
                or prob,

            "generated_at":
                row.get(
                    "generated_at"
                ),

            "correct":
                (
                    pred_norm
                    == actual
                ),
        })

    next_match = db_query_single(
        """
            SELECT
                id,
                home_team_name,
                away_team_name

            FROM matches

            WHERE (
                home_team_id = :home_id
                AND away_team_id = :away_id
            )

            OR (
                home_team_id = :away_id
                AND away_team_id = :home_id
            )

            AND (
                home_score IS NULL
                OR away_score IS NULL
            )

            ORDER BY utcDate ASC

            LIMIT 1
        """,
        {
            "home_id":
                home_team_id,

            "away_id":
                away_team_id,
        }
    )

    next_match_prediction = None

    if next_match:

        prediction_row = db_query_single(
            """
                SELECT
                    prediction_json,
                    confidence
                FROM predictions
                WHERE match_id = :match_id
                ORDER BY generated_at DESC
                LIMIT 1
            """,
            {
                "match_id":
                    next_match["id"]
            }
        )

        if prediction_row:

            pj = (
                parse_prediction_json(
                    prediction_row.get(
                        "prediction_json"
                    )
                )
                or {}
            )

            label, _ = (
                extract_best_prediction_from_pj(
                    pj
                )
            )

            next_match_prediction = {

                "match_id":
                    next_match["id"],

                "home_team":
                    next_match[
                        "home_team_name"
                    ],

                "away_team":
                    next_match[
                        "away_team_name"
                    ],

                "prediction":
                    label,

                "confidence":
                    prediction_row.get(
                        "confidence"
                    ),
            }

    return jsonify({
        "h2h_stats":
            h2h_stats,

        "past_predictions":
            past_predictions,

        "next_match_prediction":
            next_match_prediction,
    })


# =========================================================
# FINISHED MATCHES WITH PREDICTIONS
# =========================================================

@app.route(
    "/api/finished-matches-with-predictions",
    methods=["GET"]
)
def finished_matches_with_predictions():

    try:

        months_back = int(
            request.args.get(
                "months",
                2
            )
        )

        if months_back < 1:
            months_back = 1

        limit_arg = request.args.get(
            "limit"
        )

        limit_clause = ""

        if limit_arg:

            try:

                parsed_limit = int(
                    limit_arg
                )

                if parsed_limit > 0:

                    parsed_limit = min(
                        parsed_limit,
                        MAX_LIMIT
                    )

                    limit_clause = (
                        f"LIMIT {parsed_limit}"
                    )

            except Exception:
                pass

        now_kenya = (
            datetime.now(UTC)
            .astimezone(KENYA)
        )

        first_day_this_month = (
            now_kenya.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        )

        year = (
            first_day_this_month.year
        )

        month = (
            first_day_this_month.month
            - months_back
        )

        while month < 1:

            month += 12
            year -= 1

        first_day_target = datetime(
            year,
            month,
            1,
            tzinfo=KENYA,
        )

        first_day_target_utc = (
            first_day_target
            .astimezone(UTC)
            .isoformat()
        )

        query_sql = f"""
            SELECT
                m.*,
                p.model_version,
                p.prediction_json,
                p.confidence

            FROM matches m

            JOIN predictions p
              ON m.id = p.match_id

            WHERE m.home_score IS NOT NULL
              AND m.away_score IS NOT NULL
              AND m.utcDate >=
                  :first_day_target_utc

            ORDER BY
                m.utcDate DESC

            {limit_clause}
        """

        rows = db_query_list(
            query_sql,
            {
                "first_day_target_utc":
                    first_day_target_utc
            }
        )

        results = []

        for row in rows:

            row_dict = dict(row)

            prediction_json = (
                row_dict.get(
                    "prediction_json"
                )
            )

            if prediction_json:

                try:

                    row_dict[
                        "prediction_json"
                    ] = json.loads(
                        prediction_json
                    )

                except Exception:

                    row_dict[
                        "prediction_json"
                    ] = {}

            results.append(
                row_dict
            )

        return jsonify({
            "count":
                len(results),

            "matches":
                results,
        })

    except Exception as exc:

        log_json(
            "error",
            event=
                "finished_matches_error",
            error=str(exc),
        )

        return jsonify({
            "error":
                "internal server error"
        }), 500


# =========================================================
# H2H
# =========================================================

@app.route(
    "/h2h",
    methods=["GET"]
)
def h2h_simple():

    home_team_id = request.args.get(
        "home_team_id"
    )

    away_team_id = request.args.get(
        "away_team_id"
    )

    limit = cap_limit(
        request.args.get(
            "limit",
            5
        ),
        default=5
    )

    if (
        not home_team_id
        or not away_team_id
    ):

        return jsonify({
            "error":
                "home_team_id and "
                "away_team_id are required"
        }), 400

    try:

        home_team_id = int(
            home_team_id
        )

        away_team_id = int(
            away_team_id
        )

    except ValueError:

        return jsonify({
            "error":
                "team ids must be integers"
        }), 400

    rows = db_query_list(
        """
            SELECT
                id,
                home_team_id,
                away_team_id,
                match_id,
                home_score,
                away_score,
                date_played

            FROM h2h

            WHERE (
                home_team_id = :home_id
                AND away_team_id = :away_id
            )

            OR (
                home_team_id = :away_id
                AND away_team_id = :home_id
            )

            ORDER BY date_played DESC

            LIMIT :limit
        """,
        {
            "home_id":
                home_team_id,

            "away_id":
                away_team_id,

            "limit":
                limit,
        }
    )

    return jsonify({
        "count":
            len(rows),

        "matches":
            rows,
    })


# =========================================================
# VALUE TIPS
# =========================================================

@app.route(
    "/tips/value"
)
def tips_value():

    status_arg = request.args.get(
        "status",
        "TIMED,SCHEDULED"
    )

    statuses = [
        status.strip().upper()
        for status in status_arg.split(",")
        if status.strip()
    ]

    if not statuses:

        return jsonify({
            "success": True,
            "count": 0,
            "tips": [],
        })

    try:

        placeholders = ",".join(
            f":s{i}"
            for i in range(
                len(statuses)
            )
        )

        status_params = {
            f"s{i}":
                statuses[i]
            for i in range(
                len(statuses)
            )
        }

        tips = db_query_list(
            f"""
                SELECT
                    v.*,

                    m.utcDate,
                    m.status,

                    m.home_team_id,
                    m.away_team_id,

                    m.home_team_name,
                    m.away_team_name

                FROM matches m

                INNER JOIN value v
                    ON v.match_id = m.id

                WHERE m.status IN (
                    {placeholders}
                )

                ORDER BY
                    m.utcDate ASC
            """,
            status_params
        )

        if not tips:

            return jsonify({
                "success":
                    True,
                "count":
                    0,
                "tips":
                    [],
            })

        team_ids = (
            {
                tip["home_team_id"]
                for tip in tips
            }
            |
            {
                tip["away_team_id"]
                for tip in tips
            }
        )

        team_placeholders = ",".join(
            f":tid{i}"
            for i in range(
                len(team_ids)
            )
        )

        team_params = {
            f"tid{i}":
                team_id
            for i, team_id
            in enumerate(team_ids)
        }

        logos_rows = db_query_list(
            f"""
                SELECT
                    id,
                    crest
                FROM teams
                WHERE id IN (
                    {team_placeholders}
                )
            """,
            team_params
        )

        logos = {
            row["id"]:
                row["crest"]
            for row in logos_rows
        }

        for tip in tips:

            tip["home_team_logo"] = (
                logos.get(
                    tip["home_team_id"],
                    ""
                )
            )

            tip["away_team_logo"] = (
                logos.get(
                    tip["away_team_id"],
                    ""
                )
            )

            tip["predicted_score"] = {

                "home":
                    tip.get(
                        "home_goals_pred"
                    ),

                "away":
                    tip.get(
                        "away_goals_pred"
                    ),

                "most_likely":
                    tip.get(
                        "most_likely_score"
                    ),

                "confidence":
                    tip.get(
                        "conf_score"
                    ),
            }

            tip["btts"] = {

                "yes":
                    (
                        bool(
                            tip.get(
                                "btts_yes"
                            )
                        )
                        if tip.get(
                            "btts_yes"
                        ) is not None
                        else None
                    ),

                "confidence":
                    tip.get(
                        "conf_btts"
                    ),
            }

            tip["over_under"] = {

                "over_1_5": {
                    "tip":
                        (
                            bool(
                                tip.get(
                                    "over_1_5"
                                )
                            )
                            if tip.get(
                                "over_1_5"
                            ) is not None
                            else None
                        ),

                    "confidence":
                        tip.get(
                            "conf_over_1_5"
                        ),
                },

                "over_2_5": {
                    "tip":
                        (
                            bool(
                                tip.get(
                                    "over_2_5"
                                )
                            )
                            if tip.get(
                                "over_2_5"
                            ) is not None
                            else None
                        ),

                    "confidence":
                        tip.get(
                            "conf_over_2_5"
                        ),
                },

                "over_3_5": {
                    "tip":
                        (
                            bool(
                                tip.get(
                                    "over_3_5"
                                )
                            )
                            if tip.get(
                                "over_3_5"
                            ) is not None
                            else None
                        ),

                    "confidence":
                        tip.get(
                            "conf_over_3_5"
                        ),
                },

                "over_4_5": {
                    "tip":
                        (
                            bool(
                                tip.get(
                                    "over_4_5"
                                )
                            )
                            if tip.get(
                                "over_4_5"
                            ) is not None
                            else None
                        ),

                    "confidence":
                        tip.get(
                            "conf_over_4_5"
                        ),
                },
            }

        return jsonify({
            "success":
                True,

            "count":
                len(tips),

            "tips":
                tips,
        })

    except Exception as exc:

        log_json(
            "error",
            event="tips_value_error",
            error=str(exc),
        )

        return jsonify({
            "success":
                False,

            "error":
                str(exc),
        }), 500


# =========================================================
# DAILY TIPS
# =========================================================

@app.route(
    "/tips/daily",
    methods=["GET"]
)
def tips_daily():

    date = (
        request.args.get(
            "date"
        )
        or datetime.now(
            KENYA
        ).date().isoformat()
    )

    query_sql = """
        SELECT

            p.id AS prediction_id,
            p.match_id,
            p.model_version,
            p.prediction_json,
            p.confidence,

            p.generated_at
                AS prediction_time,

            m.competition,
            m.matchday,
            m.utcdate,
            m.status,

            m.home_team_name,
            m.away_team_name,

            m.home_score,
            m.away_score

        FROM predictions p

        JOIN matches m
          ON p.match_id = m.id

        WHERE m.status IN (
            'SCHEDULED',
            'TIMED',
            'PENDING'
        )

        AND DATE(
            m.utcdate
            AT TIME ZONE 'Africa/Nairobi'
        ) = :date

        ORDER BY
            p.confidence DESC,
            m.utcdate ASC
    """

    try:

        rows = db_query_list(
            query_sql,
            {
                "date":
                    date
            }
        )

        tips = []

        for row in rows:

            data = (
                parse_prediction_json(
                    row.get(
                        "prediction_json"
                    )
                )
                or {}
            )

            prediction = (
                data.get(
                    "prediction"
                )
            )

            probabilities = (
                data.get(
                    "probabilities",
                    {}
                )
            )

            tips.append({

                "prediction_id":
                    row.get(
                        "prediction_id"
                    ),

                "match_id":
                    row.get(
                        "match_id"
                    ),

                "model_version":
                    row.get(
                        "model_version"
                    ),

                "confidence":
                    row.get(
                        "confidence"
                    ),

                "prediction_time":
                    row.get(
                        "prediction_time"
                    ),

                "prediction":
                    prediction,

                "probabilities":
                    probabilities,

                "competition":
                    row.get(
                        "competition"
                    ),

                "matchday":
                    row.get(
                        "matchday"
                    ),

                "utcdate":
                    row.get(
                        "utcdate"
                    ),

                "status":
                    row.get(
                        "status"
                    ),

                "home_team": {

                    "name":
                        row.get(
                            "home_team_name"
                        ),

                    "score":
                        row.get(
                            "home_score"
                        ),
                },

                "away_team": {

                    "name":
                        row.get(
                            "away_team_name"
                        ),

                    "score":
                        row.get(
                            "away_score"
                        ),
                },

            })

        return jsonify({

            "count":
                len(tips),

            "date":
                date,

            "tips":
                tips,
        })

    except Exception as exc:

        log_json(
            "error",
            event="/tips/daily_error",
            error=str(exc),
        )

        return jsonify({
            "error":
                str(exc)
        }), 500


# =========================================================
# ACCUMULATOR
# =========================================================

@app.get("/accumulator")
def accumulator_endpoint():

    by_market = (
        request.args.get(
            "by_market",
            "false"
        ).lower()
        == "true"
    )

    by_date = (
        request.args.get(
            "by_date",
            "false"
        ).lower()
        == "true"
    )

    folds = (
        request.args.get(
            "folds",
            "false"
        ).lower()
        == "true"
    )

    max_games = request.args.get(
        "max_games",
        default=10,
        type=int
    )

    max_games = max(
        1,
        min(
            max_games,
            100
        )
    )

    async def _fetch():

        query_sql = """
            SELECT
                a.*,

                m.home_team_name
                    AS home_team,

                m.away_team_name
                    AS away_team

            FROM accumulator a

            JOIN matches m
              ON m.id = a.match_id

            ORDER BY
                a.probability DESC
        """

        rows = await fetch_rows(
            query_sql
        )

        def item(row):

            return {

                "home_team":
                    row.get(
                        "home_team"
                    ),

                "away_team":
                    row.get(
                        "away_team"
                    ),

                "market":
                    row.get(
                        "market"
                    ),

                "selection":
                    row.get(
                        "selection"
                    ),

                "probability":
                    row.get(
                        "probability"
                    ),

                "match_time":
                    row.get(
                        "match_time"
                    ),
            }

        if folds:

            result = {

                "fold_1":
                    defaultdict(list),

                "fold_2":
                    defaultdict(list),

                "fold_3":
                    defaultdict(list),
            }

            for row in rows:

                probability = (
                    row.get(
                        "probability"
                    )
                    or 0
                )

                fold_name = None

                if probability > 0.75:

                    fold_name = (
                        "fold_1"
                    )

                elif (
                    0.60
                    < probability
                    < 0.75
                ):

                    fold_name = (
                        "fold_2"
                    )

                elif (
                    0.54
                    < probability
                    < 0.60
                ):

                    fold_name = (
                        "fold_3"
                    )

                if fold_name is None:
                    continue

                if by_date and by_market:

                    key = (
                        f"{(
                            row.get(
                                'match_time'
                            )
                            or ''
                        )[:10]}"
                        f"_"
                        f"{row.get('market')}"
                    )

                elif by_date:

                    key = (
                        (
                            row.get(
                                "match_time"
                            )
                            or ""
                        )[:10]
                    )

                elif by_market:

                    key = row.get(
                        "market"
                    )

                else:

                    key = "ALL"

                if (
                    len(
                        result[
                            fold_name
                        ][key]
                    )
                    < max_games
                ):

                    result[
                        fold_name
                    ][key].append(
                        item(row)
                    )

            return result

        if not by_market and not by_date:

            return [
                item(row)
                for row in rows
            ]

        if by_date and by_market:

            result = (
                defaultdict(
                    lambda:
                        defaultdict(list)
                )
            )

            for row in rows:

                date_key = (
                    (
                        row.get(
                            "match_time"
                        )
                        or ""
                    )[:10]
                )

                market = row.get(
                    "market"
                )

                if (
                    len(
                        result[
                            date_key
                        ][market]
                    )
                    < max_games
                ):

                    result[
                        date_key
                    ][market].append(
                        item(row)
                    )

            return result

        if by_date:

            result = defaultdict(
                list
            )

            for row in rows:

                date_key = (
                    (
                        row.get(
                            "match_time"
                        )
                        or ""
                    )[:10]
                )

                if (
                    len(
                        result[
                            date_key
                        ]
                    )
                    < max_games
                ):

                    result[
                        date_key
                    ].append(
                        item(row)
                    )

            return result

        if by_market:

            result = defaultdict(
                list
            )

            for row in rows:

                market = row.get(
                    "market"
                )

                if (
                    len(
                        result[
                            market
                        ]
                    )
                    < max_games
                ):

                    result[
                        market
                    ].append(
                        item(row)
                    )

            return result

        return []

    data = _run_sync_or_async(
        _fetch()
    )

    return jsonify(data)


# =========================================================
# TEAMS
# =========================================================

@app.route(
    "/teams",
    methods=["GET"]
)
def teams():

    limit = cap_limit(
        request.args.get(
            "limit",
            50000
        ),
        default=50000,
        max_limit=MAX_LIMIT,
    )

    rows = db_query_list(
        """
            SELECT
                id,
                name,
                short_name,
                tla,
                crest,
                venue,
                founded

            FROM teams

            ORDER BY name

            LIMIT :limit
        """,
        {
            "limit":
                limit
        }
    )

    comp_rows = db_query_list(
        """
            SELECT
                home_team_id AS team_id,
                competition

            FROM matches

            WHERE competition IS NOT NULL

            UNION

            SELECT
                away_team_id AS team_id,
                competition

            FROM matches

            WHERE competition IS NOT NULL
        """
    )

    comp_map = {}

    for row in comp_rows:

        comp_map.setdefault(
            row["team_id"],
            set()
        ).add(
            row["competition"]
        )

    teams_out = []

    for team in rows:

        team["competitions"] = sorted(
            list(
                comp_map.get(
                    team["id"],
                    set()
                )
            )
        )

        teams_out.append(
            team
        )

    return jsonify({
        "count":
            len(teams_out),

        "teams":
            teams_out,
    })


# =========================================================
# MATCHES
# =========================================================

@app.route(
    "/matches",
    methods=["GET"]
)
@rate_limit(
    calls=60,
    per_seconds=60
)
@cache_response(
    ttl=CACHE_TTL.get(
        "/matches",
        30
    )
)
def matches_list():

    limit = cap_limit(
        request.args.get(
            "limit",
            DEFAULT_LIMIT
        ),
        default=DEFAULT_LIMIT,
        max_limit=MAX_LIMIT,
    )

    rows = db_query_list(
        """
            SELECT
                id,
                home_team_name,
                away_team_name,
                utcdate AS utcDate,
                status

            FROM matches

            ORDER BY utcdate DESC

            LIMIT :limit
        """,
        {
            "limit":
                limit
        }
    )

    out = []

    for record in rows:

        dt = _parse_match_datetime(
            record.get(
                "utcDate"
            )
        )

        if dt:

            record["utcDate"] = (
                dt.isoformat()
            )

            record["localDate"] = (
                dt
                .astimezone(EAT)
                .isoformat()
            )

        else:

            record["localDate"] = None

        out.append(
            record
        )

    return jsonify({
        "count":
            len(out),

        "matches":
            out,
    })


# =========================================================
# RECENT MATCHES
# =========================================================

@app.route(
    "/matches/recent",
    methods=["GET"]
)
def matches_recent():

    limit = cap_limit(
        request.args.get(
            "limit",
            300
        ),
        default=300,
        max_limit=MAX_LIMIT,
    )

    rows = db_query_list(
        """
            SELECT
                id,
                competition,
                matchday,
                utcDate,
                status,

                home_team_id,
                away_team_id,

                home_score,
                away_score,

                home_team_name,
                away_team_name,

                generated_at

            FROM matches

            WHERE status =
                'FINISHED'

            ORDER BY
                utcDate DESC

            LIMIT :limit
        """,
        {
            "limit":
                limit
        }
    )

    return jsonify({
        "count":
            len(rows),

        "matches":
            rows,
    })


# =========================================================
# UPCOMING MATCHES
# =========================================================

@app.route(
    "/matches/upcoming",
    methods=["GET"]
)
def matches_upcoming():

    limit = cap_limit(
        request.args.get(
            "limit",
            1000
        ),
        default=1000,
        max_limit=MAX_LIMIT,
    )

    rows = db_query_list(
        """
            SELECT
                id,
                competition,
                matchday,
                utcDate,
                status,

                home_team_id,
                away_team_id,

                home_team_name,
                away_team_name,

                generated_at

            FROM matches

            WHERE status IN (
                'SCHEDULED',
                'TIMED',
                'NS'
            )

            ORDER BY
                utcDate ASC

            LIMIT :limit
        """,
        {
            "limit":
                limit
        }
    )

    out = []

    for record in rows:

        dt_utc = _parse_match_datetime(
            record.get(
                "utcDate"
            )
        )

        if dt_utc:

            dt_local = (
                dt_utc
                .astimezone(EAT)
            )

            record["utcDate"] = (
                dt_utc.isoformat()
            )

            record["localDate"] = (
                dt_local.isoformat()
            )

            record["timestamp"] = int(
                dt_utc.timestamp()
            )

        else:

            record["localDate"] = None
            record["timestamp"] = None

        out.append(
            record
        )

    return jsonify({

        "success":
            True,

        "count":
            len(out),

        "matches":
            out,
    })


# =========================================================
# LATEST PREDICTIONS
# =========================================================

@app.route(
    "/predictions/latest",
    methods=["GET"]
)
def predictions_latest():

    limit = cap_limit(
        request.args.get(
            "limit",
            100
        ),
        default=100,
        max_limit=MAX_LIMIT,
    )

    now_iso = (
        datetime.now(UTC)
        .isoformat()
    )

    rows = db_query_list(
        """
            SELECT
                p.match_id,
                p.model_version,
                p.prediction_json,
                p.generated_at,

                m.utcDate,
                m.status,

                m.home_team_name,
                m.away_team_name,

                m.competition

            FROM predictions p

            LEFT JOIN matches m
              ON p.match_id = m.id

            WHERE m.status IN (
                :s1,
                :s2,
                :s3
            )

            AND m.utcDate >= :now

            ORDER BY
                m.utcDate ASC,
                p.generated_at DESC

            LIMIT :limit
        """,
        {
            "s1":
                UPCOMING_STATUSES[0],

            "s2":
                UPCOMING_STATUSES[1],

            "s3":
                UPCOMING_STATUSES[2],

            "now":
                now_iso,

            "limit":
                limit,
        }
    )

    out = []

    for row in rows:

        record = dict(row)

        raw_json = record.pop(
            "prediction_json",
            None
        )

        record["prediction"] = (
            parse_prediction_json(
                raw_json
            )
            if raw_json
            else None
        )

        out.append(
            record
        )

    return jsonify({
        "count":
            len(out),

        "predictions":
            out,
    })


# =========================================================
# SINGLE MATCH PREDICTION
# =========================================================

@app.route(
    "/predictions/<int:match_id>",
    methods=["GET"]
)
@cache_response(
    ttl=300
)
def match_prediction(
    match_id
):

    row = db_query_single(
        """
            SELECT
                prediction_json,
                confidence

            FROM predictions

            WHERE match_id =
                :match_id

            ORDER BY
                generated_at DESC

            LIMIT 1
        """,
        {
            "match_id":
                match_id
        }
    )

    if not row:

        return jsonify({
            "error":
                "prediction not found"
        }), 404

    prediction_json = (
        parse_prediction_json(
            row.get(
                "prediction_json"
            )
        )
    )

    return jsonify({

        "prediction":
            prediction_json,

        "confidence":
            row.get(
                "confidence"
            ),
    })


# =========================================================
# PLAYERS
# =========================================================

@app.route(
    "/players",
    methods=["GET"]
)
def players():

    team_id = request.args.get(
        "team_id"
    )

    key_player = request.args.get(
        "key_player"
    )

    injured = request.args.get(
        "injured"
    )

    limit = cap_limit(
        request.args.get(
            "limit",
            10000
        ),
        default=10000,
        max_limit=MAX_LIMIT,
    )

    query_sql = """
        SELECT

            p.id,
            p.name,
            p.team_id,

            t.name AS team_name,

            p.position,
            p.rating,
            p.goals,
            p.assists,
            p.key_player,
            p.is_injured

        FROM players p

        LEFT JOIN teams t
          ON p.team_id = t.id
    """

    conditions = []

    params = {}

    if team_id:

        conditions.append(
            "p.team_id = :team_id"
        )

        params["team_id"] = (
            team_id
        )

    if key_player is not None:

        conditions.append(
            "p.key_player = :key_player"
        )

        params["key_player"] = int(
            key_player
        )

    if injured is not None:

        conditions.append(
            "p.is_injured = :injured"
        )

        params["injured"] = int(
            injured
        )

    if conditions:

        query_sql += (
            " WHERE "
            + " AND ".join(
                conditions
            )
        )

    query_sql += """
        ORDER BY p.name
        LIMIT :limit
    """

    params["limit"] = limit

    rows = db_query_list(
        query_sql,
        params
    )

    return jsonify({
        "count":
            len(rows),

        "players":
            rows,
    })


# =========================================================
# LIVE MATCHES
# =========================================================

@app.route(
    "/live",
    methods=["GET"]
)
@rate_limit(
    calls=120,
    per_seconds=60
)
def live_matches():

    """
    Return ONLY matches whose database status is:

        IN_PLAY
        PAUSED

    No status mapping is performed.
    Database status is preserved exactly.
    """

    try:

        # -------------------------------------------------
        # Get live matches ONLY
        # -------------------------------------------------

        rows = db_query_list(
            """
                SELECT
                    id,
                    home_team_name,
                    away_team_name,
                    status,
                    home_score,
                    away_score,
                    utcDate,
                    generated_at

                FROM matches

                WHERE UPPER(TRIM(status)) IN (
                    'IN_PLAY',
                    'PAUSED'
                )

                ORDER BY
                    CASE
                        WHEN UPPER(TRIM(status))
                            = 'IN_PLAY'
                        THEN 1

                        WHEN UPPER(TRIM(status))
                            = 'PAUSED'
                        THEN 2

                        ELSE 3
                    END,

                    utcDate ASC NULLS LAST,
                    id ASC

                LIMIT 200
            """
        )

        output = []

        for row in rows:

            # -------------------------------------------------
            # SECOND SAFETY FILTER
            # -------------------------------------------------

            raw_status = str(
                row.get("status") or ""
            ).strip().upper()

            if raw_status not in {
                "IN_PLAY",
                "PAUSED",
            }:
                continue

            # -------------------------------------------------
            # TIME
            # -------------------------------------------------

            # PostgreSQL returns the unquoted utcDate column
            # as lowercase "utcdate" through psycopg.
            utc_date = row.get(
                "utcdate"
            )

            if utc_date is None:
                utc_date = row.get(
                    "utcDate"
                )

            local_date = None

            if utc_date:

                try:

                    dt = _parse_match_datetime(
                        utc_date
                    )

                    if dt:

                        utc_date = (
                            dt.isoformat()
                        )

                        local_date = (
                            dt
                            .astimezone(EAT)
                            .isoformat()
                        )

                except Exception:

                    pass

            # -------------------------------------------------
            # MATCH OBJECT
            # -------------------------------------------------

            output.append({

                "match_id":
                    row.get("id"),

                "home_team":
                    row.get(
                        "home_team_name"
                    ),

                "away_team":
                    row.get(
                        "away_team_name"
                    ),

                "home_score":
                    row.get(
                        "home_score"
                    ),

                "away_score":
                    row.get(
                        "away_score"
                    ),

                # IMPORTANT:
                # Preserve exact database status.
                "status":
                    raw_status,

                "utcDate":
                    utc_date,

                "localDate":
                    local_date,

                "updated_at":
                    row.get(
                        "generated_at"
                    ),
            })

        # -------------------------------------------------
        # COUNTS
        # -------------------------------------------------

        in_play_count = sum(
            1
            for item in output
            if item["status"] == "IN_PLAY"
        )

        paused_count = sum(
            1
            for item in output
            if item["status"] == "PAUSED"
        )

        # -------------------------------------------------
        # RESPONSE
        # -------------------------------------------------

        return jsonify({

            "status":
                "ok",

            "server_time":
                now_kenya_iso(),

            "count":
                len(output),

            "counts": {

                "in_play":
                    in_play_count,

                "paused":
                    paused_count,
            },

            "matches":
                output,
        })

    except Exception as exc:

        log_json(
            "error",
            event=
                "live_matches_error",
            error=str(exc),
        )

        return jsonify({

            "status":
                "error",

            "error":
                str(exc),

        }), 500


# =========================================================
# SOCKET.IO LIVE MATCH STREAM
# =========================================================

LIVE_SOCKET_INTERVAL = float(
    os.environ.get(
        "LIVE_SOCKET_INTERVAL",
        "1.0"
    )
)

_live_socket_lock = threading.Lock()

_live_socket_snapshot = None


def build_live_snapshot():
    """
    Build the exact same live data used by /live.

    ONLY:
        IN_PLAY
        PAUSED

    are allowed through.

    No status mapping is performed.
    """

    try:

        rows = db_query_list(
            """
                SELECT
                    id,
                    home_team_name,
                    away_team_name,
                    status,
                    home_score,
                    away_score,
                    utcDate,
                    generated_at

                FROM matches

                WHERE UPPER(TRIM(status)) IN (
                    'IN_PLAY',
                    'PAUSED'
                )

                ORDER BY
                    CASE
                        WHEN UPPER(TRIM(status))
                            = 'IN_PLAY'
                        THEN 1

                        WHEN UPPER(TRIM(status))
                            = 'PAUSED'
                        THEN 2

                        ELSE 3
                    END,

                    utcDate ASC NULLS LAST,
                    id ASC

                LIMIT 200
            """
        )

        output = []

        for row in rows:

            raw_status = str(
                row.get("status") or ""
            ).strip().upper()

            # Strict safety filter.
            if raw_status not in {
                "IN_PLAY",
                "PAUSED",
            }:
                continue

            # PostgreSQL returns the unquoted utcDate
            # column as lowercase "utcdate" through psycopg.
            utc_date = row.get(
                "utcdate"
            )

            if utc_date is None:
                utc_date = row.get(
                    "utcDate"
                )

            local_date = None

            if utc_date:

                try:

                    dt = _parse_match_datetime(
                        utc_date
                    )

                    if dt:

                        utc_date = (
                            dt.isoformat()
                        )

                        local_date = (
                            dt
                            .astimezone(EAT)
                            .isoformat()
                        )

                except Exception:

                    pass

            output.append({

                "match_id":
                    row.get("id"),

                "home_team":
                    row.get(
                        "home_team_name"
                    ),

                "away_team":
                    row.get(
                        "away_team_name"
                    ),

                "home_score":
                    row.get(
                        "home_score"
                    ),

                "away_score":
                    row.get(
                        "away_score"
                    ),

                "status":
                    raw_status,

                "utcDate":
                    utc_date,

                "localDate":
                    local_date,

                "updated_at":
                    row.get(
                        "generated_at"
                    ),
            })

        in_play_count = sum(
            1
            for item in output
            if item["status"] == "IN_PLAY"
        )

        paused_count = sum(
            1
            for item in output
            if item["status"] == "PAUSED"
        )

        return {

            "status":
                "ok",

            "server_time":
                now_kenya_iso(),

            "count":
                len(output),

            "counts": {

                "in_play":
                    in_play_count,

                "paused":
                    paused_count,
            },

            "matches":
                output,
        }

    except Exception as exc:

        log_json(
            "error",
            event=
                "live_socket_snapshot_error",
            error=str(exc),
        )

        return None


@socketio.on("connect")
def live_socket_connect():

    log_json(
        "info",
        event="live_socket_client_connected",
    )

    snapshot = build_live_snapshot()

    if snapshot is not None:

        emit(
            "live_snapshot",
            snapshot
        )


@socketio.on("disconnect")
def live_socket_disconnect():

    log_json(
        "info",
        event="live_socket_client_disconnected",
    )


def _live_snapshot_signature(snapshot):
    """
    Create a stable representation of the actual live state.

    server_time and updated_at are intentionally excluded
    so clients only receive a new snapshot when match data
    actually changes.
    """

    if not snapshot:
        return None

    matches = []

    for match in snapshot.get(
        "matches",
        []
    ):

        matches.append((
            match.get("match_id"),
            match.get("home_team"),
            match.get("away_team"),
            match.get("home_score"),
            match.get("away_score"),
            match.get("status"),
            match.get("utcDate"),
        ))

    return tuple(matches)


def _live_socket_watcher():

    global _live_socket_snapshot

    log_json(
        "info",
        event=
            "live_socket_watcher_started",
        interval=
            LIVE_SOCKET_INTERVAL,
    )

    while True:

        try:

            snapshot = build_live_snapshot()

            if snapshot is not None:

                signature = (
                    _live_snapshot_signature(
                        snapshot
                    )
                )

                with _live_socket_lock:

                    previous_signature = (
                        _live_socket_snapshot
                    )

                    if (
                        previous_signature
                        != signature
                    ):

                        _live_socket_snapshot = (
                            signature
                        )

                        socketio.emit(
                            "live_snapshot",
                            snapshot
                        )

                        log_json(
                            "info",
                            event=
                                "live_socket_snapshot_emitted",
                            count=
                                snapshot.get(
                                    "count",
                                    0
                                ),
                        )

        except Exception as exc:

            log_json(
                "error",
                event=
                    "live_socket_watcher_error",
                error=str(exc),
            )

        time.sleep(
            LIVE_SOCKET_INTERVAL
        )


_live_socket_thread = None
_live_socket_thread_lock = threading.Lock()


def start_live_socket_watcher():

    global _live_socket_thread

    with _live_socket_thread_lock:

        if (
            _live_socket_thread
            and _live_socket_thread.is_alive()
        ):
            return

        _live_socket_thread = threading.Thread(
            target=_live_socket_watcher,
            name="live-socket-watcher",
            daemon=True,
        )

        _live_socket_thread.start()


# Start the watcher once when the application module
# is loaded.
start_live_socket_watcher()


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def not_found(error):

    return jsonify({
        "error":
            "endpoint not found"
    }), 404


@app.errorhandler(500)
def internal_error(error):

    log_json(
        "error",
        event=
            "internal_server_error",
        error=str(error),
    )

    return jsonify({
        "error":
            "internal server error"
    }), 500


# =========================================================
# APP RUNNER
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5003
        )
    )

    log_json(
        "info",
        event="api_start",
        port=port,
        db=DATABASE_URL,
    )

    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=(
            os.environ.get(
                "FLASK_DEBUG",
                "0"
            )
            == "1"
        ),
        allow_unsafe_werkzeug=True,
    )
