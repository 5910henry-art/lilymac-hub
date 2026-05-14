
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

from config2 import (
    DATABASE_URL,
    DB_SCHEMA,
    UTC,
    KENYA,
    MAX_CONCURRENT,
    BASE_URL,
    HEADERS,
    COMPETITION_MAP,
    PREDICTORS_DIR,
)

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
            "Postgres driver not available. Install psycopg3 or psycopg2."
        ) from exc

# -------------------------
# Local configuration / defaults
# -------------------------
LOG_FILE = os.environ.get("API_LOG_FILE", "api.json.log")
BANK_ROLL = float(os.environ.get("BANK_ROLL", "1000"))
MAX_LIMIT = int(os.environ.get("MAX_LIMIT", "80000"))
DEFAULT_LIMIT = 15
CACHE_TTL = {"/matches": 30}
DEFAULT_RATE = {"calls": 30, "per_seconds": 60}
UPCOMING_STATUSES = ["SCHEDULED", "TIMED", "NS"]
EAT = ZoneInfo("Africa/Nairobi")
EAT = KENYA

# -------------------------
# App
# -------------------------
app = Flask("lilymac_predictions_hub")
CORS(app)
app.config["COMPRESS_LEVEL"] = 6
app.config["COMPRESS_MIN_SIZE"] = 500
Compress(app)
@app.after_request
def apply_global_json_fix(response):
    try:
        if response.is_json:
            data = response.get_json()
            fixed = normalize_dates(data)
            response.set_data(json.dumps(fixed))
    except Exception:
        pass
    return response
# -------------------------
# Logging
# -------------------------
logger = logging.getLogger("lilymac_api")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
console_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
ch.setFormatter(console_fmt)
fh = logging.FileHandler(LOG_FILE)
fh.setLevel(logging.INFO)
fh.setFormatter(console_fmt)
if not logger.handlers:
    logger.addHandler(ch)
    logger.addHandler(fh)
else:
    logger.handlers = [ch, fh]


def log_json(level: str, **kwargs):
    payload = {
        "ts": datetime.now(UTC).astimezone(KENYA).isoformat(),
        **kwargs,
    }
    message = json.dumps(payload, default=str)
    if level == "error":
        logger.error(message)
    elif level == "warning":
        logger.warning(message)
    else:
        logger.info(message)


def normalize_dates(obj):
    """
    Recursively convert ALL datetime objects into ISO strings.
    Also normalizes utcDate/utcdate fields.
    """
    if isinstance(obj, dict):
        new_obj = {}

        for k, v in obj.items():
            key = "utcDate" if k.lower() == "utcdate" else k

            if isinstance(v, datetime):
                try:
                    dt_utc = _parse_match_datetime(v)
                    new_obj[key] = dt_utc.isoformat() if dt_utc else None

                    # auto-add localDate if it's utcDate
                    if key == "utcDate" and dt_utc:
                        new_obj["localDate"] = dt_utc.astimezone(KENYA).isoformat()

                except Exception:
                    new_obj[key] = None

            elif isinstance(v, (dict, list)):
                new_obj[key] = normalize_dates(v)

            else:
                # try parsing string dates too
                if isinstance(v, str) and ("gmt" in v.lower() or "t" in v):
                    try:
                        dt = _parse_match_datetime(v)
                        new_obj[key] = dt.isoformat()
                        if key == "utcDate":
                            new_obj["localDate"] = dt.astimezone(KENYA).isoformat()
                    except Exception:
                        new_obj[key] = v
                else:
                    new_obj[key] = v

        return new_obj

    elif isinstance(obj, list):
        return [normalize_dates(item) for item in obj]

    return obj

def _parse_match_datetime(raw):
    if raw is None:
        return None

    if isinstance(raw, datetime):
        dt = raw
    else:
        text = str(raw).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            dt = parsedate_to_datetime(text)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)

# -------------------------
# DB bridge (Postgres-safe, sync)
# -------------------------
_db_lock = threading.RLock()
_named_param_pattern = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")


def _connect_db():
    """
    Open a fresh Postgres connection for each operation.
    This avoids shared-connection concurrency errors in Flask.
    """
    if _PSYCOPG3:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def _run_sync_or_async(callable_or_coro):
    """Run a sync result directly or execute an awaitable safely."""
    if inspect.isawaitable(callable_or_coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Keep asyncio support for the rare case it is needed,
            # but do not reuse the current running loop.
            result_box = {}
            error_box = {}

            def _runner():
                try:
                    result_box["value"] = asyncio.run(callable_or_coro)
                except Exception as exc:
                    error_box["error"] = exc

            t = threading.Thread(target=_runner, daemon=True)
            t.start()
            t.join()
            if error_box.get("error"):
                raise error_box["error"]
            return result_box.get("value")

        return asyncio.run(callable_or_coro)
    return callable_or_coro


def _normalize_sql_params(sql: str, params):
    """
    Convert :named placeholders to positional %s placeholders and a tuple
    so the app works cleanly with Postgres drivers.
    """
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

    normalized_sql = _named_param_pattern.sub(repl, sql)

    try:
        normalized_params = tuple(params[key] for key in ordered_keys)
    except KeyError as exc:
        raise KeyError(f"Missing SQL parameter: {exc.args[0]}") from exc

    return normalized_sql, normalized_params


def _fetchall_dicts(cur):
    rows = cur.fetchall() if cur.description else []
    return [dict(r) for r in rows]


def _call_db(fn, sql: str, params=()):
    normalized_sql, normalized_params = _normalize_sql_params(sql, params)
    try:
        with _db_lock:
            conn = _connect_db()
            try:
                if _PSYCOPG3:
                    with conn.cursor() as cur:
                        result = fn(cur, normalized_sql, normalized_params)
                        conn.commit()
                        return _run_sync_or_async(result)
                else:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        result = fn(cur, normalized_sql, normalized_params)
                        conn.commit()
                        return _run_sync_or_async(result)
            finally:
                conn.close()
    except Exception as e:
        log_json("error", event="db_call_failed", sql=normalized_sql[:180], error=str(e))
        raise


def _query_fn(cur, sql, params):
    cur.execute(sql, params)
    return _fetchall_dicts(cur)


def _execute_fn(cur, sql, params):
    cur.execute(sql, params)
    if cur.description:
        return _fetchall_dicts(cur)
    return cur.rowcount


def db_query_list(sql: str, params=()):
    try:
        rows = _call_db(_query_fn, sql, params)
        return rows or []
    except Exception as e:
        log_json("error", event="db_query_failed", sql=sql[:180], error=str(e))
        return []


def db_query_single(sql: str, params=()):
    rows = db_query_list(sql, params)
    return rows[0] if rows else None


def db_execute(sql: str, params=()):
    try:
        return _call_db(_execute_fn, sql, params)
    except Exception as e:
        log_json("error", event="db_execute_failed", sql=sql[:180], error=str(e))
        raise


def query(sql, params=(), single=False):
    return db_query_single(sql, params) if single else db_query_list(sql, params)


def execute(sql, params=()):
    return db_execute(sql, params)


async def fetch_rows(sql, params=()):
    return db_query_list(sql, params)


# -------------------------
# Cache
# -------------------------
_cache = {}
_cache_lock = threading.Lock()
CACHE_MAX_ITEMS = 5000


def cache_response(ttl: int):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{request.path}:{tuple(sorted(request.args.items()))}"
            now_ts = time.time()

            with _cache_lock:
                entry = _cache.get(key)
                if entry and entry["expire"] > now_ts:
                    return entry["value"]

            resp = fn(*args, **kwargs)

            with _cache_lock:
                expired_keys = [k for k, v in _cache.items() if v.get("expire", 0) <= now_ts]
                for k in expired_keys:
                    _cache.pop(k, None)

                if len(_cache) >= CACHE_MAX_ITEMS:
                    items_sorted = sorted(_cache.items(), key=lambda kv: kv[1].get("expire", 0))
                    to_remove = max(1, CACHE_MAX_ITEMS // 10)
                    for k, _ in items_sorted[:to_remove]:
                        _cache.pop(k, None)

                _cache[key] = {"value": resp, "expire": now_ts + ttl}
            return resp

        return wrapper

    return decorator


# -------------------------
# Rate limiter
# -------------------------
_rate_store = defaultdict(list)
_rate_lock = threading.Lock()


def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def rate_limit(calls=None, per_seconds=None):
    calls = calls or DEFAULT_RATE["calls"]
    per_seconds = per_seconds or DEFAULT_RATE["per_seconds"]

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ip = get_client_ip()
            key = f"{fn.__name__}:{ip}"
            now = time.time()
            window = now - per_seconds

            with _rate_lock:
                timestamps = _rate_store[key]
                timestamps[:] = [t for t in timestamps if t > window]
                if len(timestamps) >= calls:
                    return jsonify({
                        "error": "rate limit exceeded",
                        "limit": calls,
                        "window_seconds": per_seconds,
                    }), 429
                timestamps.append(now)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# -------------------------
# Prediction helpers
# -------------------------
ALLOWED_LABELS = {"Home Win", "Away Win", "Draw"}


def now_kenya_iso():
    return datetime.now(UTC).astimezone(KENYA).isoformat()


def cap_limit(val, default=DEFAULT_LIMIT, max_limit=MAX_LIMIT):
    try:
        val = int(val)
        if val <= 0:
            return default
        return min(val, max_limit)
    except Exception:
        return default


def parse_prediction_json(pred_json_text):
    if not pred_json_text:
        return None
    if isinstance(pred_json_text, dict):
        return pred_json_text
    try:
        return json.loads(pred_json_text)
    except Exception:
        return None


def normalize_label(label: str):
    if not label:
        return None
    return label.strip().lower().replace(" ", "_")


def extract_best_prediction_from_pj(pj):
    if not pj or not isinstance(pj, dict):
        return None, 0.0

    home = pj.get("home_win") or pj.get("home") or pj.get("homeProbability") or pj.get("p_home")
    draw = pj.get("draw") or pj.get("p_draw")
    away = pj.get("away_win") or pj.get("away") or pj.get("awayProbability") or pj.get("p_away")

    if any(isinstance(x, (int, float)) for x in (home, draw, away)):
        home_v = float(home) if isinstance(home, (int, float)) else 0.0
        draw_v = float(draw) if isinstance(draw, (int, float)) else 0.0
        away_v = float(away) if isinstance(away, (int, float)) else 0.0
        best_label, best_prob = max(
            [("Home Win", home_v), ("Draw", draw_v), ("Away Win", away_v)],
            key=lambda x: x[1],
        )
        return best_label, best_prob

    probs = pj.get("probabilities") or pj.get("probs") or pj.get("probability") or pj.get("probabilities_map")
    if isinstance(probs, dict) and probs:
        def get_prob(key):
            return probs.get(key) or probs.get(key.lower()) or probs.get(key.upper()) or 0.0

        candidates = [
            ("Home Win", get_prob("Home Win")),
            ("Draw", get_prob("Draw")),
            ("Away Win", get_prob("Away Win")),
            ("Home Win", get_prob("home_win")),
            ("Draw", get_prob("draw")),
            ("Away Win", get_prob("away_win")),
        ]
        label, prob = max(candidates, key=lambda x: x[1] or 0.0)
        try:
            prob = float(prob)
        except Exception:
            prob = 0.0
        return label, prob

    pred = pj.get("prediction") or pj.get("pred") or pj.get("label")
    prob = pj.get("confidence") or pj.get("prob") or pj.get("score")
    if pred:
        mapping = {
            "h": "Home Win", "1": "Home Win", "home": "Home Win", "home_win": "Home Win",
            "d": "Draw", "draw": "Draw",
            "a": "Away Win", "2": "Away Win", "away": "Away Win", "away_win": "Away Win",
        }
        pred_label = mapping.get(str(pred).strip().lower(), str(pred))
        try:
            prob_f = float(prob) if prob is not None else 0.0
        except Exception:
            prob_f = 0.0
        return pred_label, prob_f

    return None, 0.0


def result_from_score(h, a):
    if h is None or a is None:
        return None
    if h > a:
        return "Home Win"
    if a > h:
        return "Away Win"
    return "Draw"


def calculate_kelly(prob, odds):
    if odds <= 1 or prob <= 0:
        return 0
    try:
        return max((odds * prob - 1) / (odds - 1), 0)
    except Exception:
        return 0


# -------------------------
# Routes
# -------------------------
@app.route("/")
def root():
    return jsonify({"status": "ok", "service": "Lilymac Prediction Hub API", "timestamp": now_kenya_iso()})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "prediction_api", "time": now_kenya_iso()})


@app.route("/dashboard", methods=["GET"])
def dashboard():
    prediction_filter = request.args.get("prediction", type=str)
    threshold_filter = request.args.get("threshold", type=str)

    rows = db_query_list("SELECT * FROM dashboard")
    result = []
    for row in rows:
        if prediction_filter and row.get("prediction") and row["prediction"].upper() != prediction_filter.upper():
            continue
        if threshold_filter and str(row.get("threshold")) != threshold_filter:
            continue
        result.append(row)

    match_outcome_rows = db_query_list("""
        SELECT
            prediction,
            COUNT(*) as count,
            COALESCE(
                ROUND(
                    (SUM(CASE WHEN LOWER(result) = 'won' THEN 1 ELSE 0 END) * 100.0) /
                    NULLIF(COUNT(*), 0),
                    2
                ), 0
            ) AS win_rate_percentage
        FROM dashboard
        WHERE status = 'FINISHED' AND prediction IN ('HOME','AWAY','DRAW')
        GROUP BY prediction;
    """)
    match_outcome_rates = {row["prediction"]: row["win_rate_percentage"] for row in match_outcome_rows}
    match_outcome_counts = {row["prediction"]: row["count"] for row in match_outcome_rows}
    for key in ["HOME", "AWAY", "DRAW"]:
        match_outcome_rates.setdefault(key, 0.0)
        match_outcome_counts.setdefault(key, 0)

    yes_row = db_query_single("""
        SELECT
            COUNT(*) as count,
            COALESCE(
                ROUND(
                    (SUM(CASE WHEN LOWER(result)='won' THEN 1 ELSE 0 END) * 100.0) /
                    NULLIF(COUNT(*),0), 2
                ), 0
            ) as win_rate_percentage
        FROM dashboard
        WHERE status='FINISHED' AND prediction='YES';
    """)
    over_row = db_query_single("""
        SELECT
            COUNT(*) as count,
            COALESCE(
                ROUND(
                    (SUM(CASE WHEN LOWER(result)='won' THEN 1 ELSE 0 END) * 100.0) /
                    NULLIF(COUNT(*),0), 2
                ), 0
            ) as win_rate_percentage
        FROM dashboard
        WHERE status='FINISHED' AND prediction='OVER';
    """)
    general_row = db_query_single("""
        SELECT
            COUNT(*) as count,
            COALESCE(
                ROUND(
                    (SUM(CASE WHEN LOWER(result)='won' THEN 1 ELSE 0 END) * 100.0) /
                    NULLIF(COUNT(*),0), 2
                ), 0
            ) as win_rate_percentage
        FROM dashboard
        WHERE status='FINISHED' AND LOWER(result) IN ('won','lost');
    """)

    return jsonify({
        "match_outcome_win_rate": match_outcome_rates,
        "match_outcome_counts": match_outcome_counts,
        "yes_win_rate": (yes_row or {}).get("win_rate_percentage", 0.0),
        "yes_count": (yes_row or {}).get("count", 0),
        "over_win_rate": (over_row or {}).get("win_rate_percentage", 0.0),
        "over_count": (over_row or {}).get("count", 0),
        "general_win_rate": (general_row or {}).get("win_rate_percentage", 0.0),
        "general_count": (general_row or {}).get("count", 0),
        "matches": result,
    })


@app.route("/predictions/match/grouped", methods=["GET"])
def grouped_predictions():
    home = request.args.get("home") or None
    away = request.args.get("away") or None
    match_id = request.args.get("match_id") or None

    now = datetime.now(UTC).isoformat()
    query_sql = """
        SELECT DISTINCT ON (m.id)
            m.id, m.home_team_name, m.away_team_name, m.utcdate AS "utcDate"
        FROM matches m
        INNER JOIN models mo ON m.id = mo.match_id
        WHERE m.utcDate > :now
    """
    params = {"now": now}
    if home:
        query_sql += " AND m.home_team_name ILIKE :home"
        params["home"] = f"%{home}%"
    if away:
        query_sql += " AND m.away_team_name ILIKE :away"
        params["away"] = f"%{away}%"
    if match_id:
        query_sql += " AND m.id = :match_id"
        params["match_id"] = match_id
    query_sql += " ORDER BY m.id, m.utcDate ASC"

    matches = db_query_list(query_sql, params)
    if not matches:
        return jsonify({"error": "No upcoming matches with predictions found"}), 404

    result = []
    for match in matches:
        mid = match["id"]
        rows = db_query_list(
            "SELECT model_version, prediction_json, confidence FROM models WHERE match_id = :match_id ORDER BY model_version",
            {"match_id": mid},
        )
        grouped = defaultdict(list)
        for r in rows:
            try:
                pred = json.loads(r.get("prediction_json") or "{}")
            except Exception:
                pred = {}
            label = pred.get("prediction", "Unknown")
            grouped[label].append({
                "model_version": r.get("model_version"),
                "probabilities": pred.get("probabilities", {}),
                "confidence": r.get("confidence"),
            })

        grouped_list = []
        for k, v in grouped.items():
            avg_conf = sum((m.get("confidence") or 0) for m in v) / len(v) if v else 0
            grouped_list.append({
                "prediction": k,
                "num_models": len(v),
                "avg_confidence": round(avg_conf, 3),
                "models": v,
            })

        grouped_list.sort(key=lambda x: (x["num_models"], x["avg_confidence"]), reverse=True)
        result.append({
            "match_id": match["id"],
            "home": match["home_team_name"],
            "away": match["away_team_name"],
            "utcDate": match["utcDate"],
            "grouped_predictions": grouped_list,
        })

    return jsonify(result)

@app.route("/bookmark/all", methods=["GET"])
def all_bookmarks():
    model_version = request.args.get("model_version")
    bookmarks = []
    eat_tz = ZoneInfo("Africa/Nairobi")

    sql = """
        SELECT
            b.*
        FROM bookmark b
        WHERE b.match_time > (NOW() AT TIME ZONE 'UTC')
    """
    params = {}

    if model_version:
        sql += """
            AND EXISTS (
                SELECT 1
                FROM models md
                WHERE md.match_id = b.match_id
                  AND md.model_version = :model_version
            )
        """
        params["model_version"] = model_version

    sql += """
        ORDER BY b.match_time ASC
    """

    rows = db_query_list(sql, params)

    for r in rows:
        bm = dict(r)

        mt = bm.get("match_time")
        dt = None
        if isinstance(mt, datetime):
            dt = mt if mt.tzinfo else mt.replace(tzinfo=timezone.utc)
        else:
            dt = _parse_match_datetime(mt)

        bm["match_time"] = dt.isoformat() if dt else None
        bm["localDate"] = dt.astimezone(eat_tz).isoformat() if dt else None

        for k in [
            "home_odds", "draw_odds", "away_odds",
            "over05", "under05", "over15", "under15",
            "over25", "under25", "over35", "under35",
            "gg_odds", "ng_odds", "p_home", "p_draw", "p_away"
        ]:
            if k in bm:
                try:
                    bm[k] = float(bm[k]) if bm[k] not in (None, "") else None
                except Exception:
                    bm[k] = None

        bookmarks.append(bm)

    return jsonify({
        "status": "ok",
        "count": len(bookmarks),
        "bookmarks": bookmarks
    })

@app.route("/team-match-overview", methods=["GET"])
def team_match_overview():
    match_id = request.args.get("match_id")
    h2h_limit = cap_limit(request.args.get("h2h_limit"), default=5)
    model_version = request.args.get("model_version")

    if not match_id:
        return jsonify({"error": "match_id is required"}), 400
    try:
        match_id = int(match_id)
    except ValueError:
        return jsonify({"error": "match_id must be an integer"}), 400

    match_row = db_query_single("""
        SELECT home_team_id, away_team_id, home_team_name, away_team_name
        FROM matches
        WHERE id = :match_id
    """, {"match_id": match_id})
    if not match_row:
        return jsonify({"error": "match_id not found"}), 404

    home_team_id = match_row["home_team_id"]
    away_team_id = match_row["away_team_id"]

    h2h_rows = db_query_list("""
        SELECT id AS match_id, home_team_id, away_team_id,
               home_team_name, away_team_name,
               home_score, away_score, utcDate AS date_played
        FROM matches
        WHERE ((home_team_id = :home_id AND away_team_id = :away_id)
            OR (home_team_id = :away_id AND away_team_id = :home_id))
        ORDER BY utcDate DESC
        LIMIT :limit
    """, {"home_id": home_team_id, "away_id": away_team_id, "limit": h2h_limit})

    h2h_matches = list(h2h_rows)
    home_wins = away_wins = draws = 0
    home_goals = away_goals = 0
    home_form = []
    away_form = []

    for m in h2h_matches:
        if m["home_score"] is None or m["away_score"] is None:
            continue
        h, a = m["home_score"], m["away_score"]
        home_goals += h
        away_goals += a
        if h > a:
            if m["home_team_id"] == home_team_id:
                home_wins += 1; home_form.append("W"); away_form.append("L")
            else:
                away_wins += 1; home_form.append("L"); away_form.append("W")
        elif a > h:
            if m["away_team_id"] == home_team_id:
                home_wins += 1; home_form.append("W"); away_form.append("L")
            else:
                away_wins += 1; home_form.append("L"); away_form.append("W")
        else:
            draws += 1; home_form.append("D"); away_form.append("D")

    total = home_wins + away_wins + draws
    h2h_stats = {
        "total_matches": total,
        "home_wins": home_wins,
        "away_wins": away_wins,
        "draws": draws,
        "avg_home_goals": round(home_goals / total, 2) if total else 0,
        "avg_away_goals": round(away_goals / total, 2) if total else 0,
        "home_form": "".join(home_form),
        "away_form": "".join(away_form),
        "home_win_rate": round(home_wins / total * 100, 2) if total else 0,
        "away_win_rate": round(away_wins / total * 100, 2) if total else 0,
        "draw_rate": round(draws / total * 100, 2) if total else 0,
        "prediction_suggestion": (
            f"Home: {round(home_wins / total * 100, 2) if total else 0}%, "
            f"Draw: {round(draws / total * 100, 2) if total else 0}%, "
            f"Away: {round(away_wins / total * 100, 2) if total else 0}%"
        ),
        "matches": h2h_matches,
    }

    pred_params = {"home_id": home_team_id, "away_id": away_team_id}
    pred_query = """
        SELECT p.id, p.match_id, p.prediction_json, p.confidence, p.generated_at,
               m.home_score, m.away_score,
               m.home_team_name, m.away_team_name
        FROM predictions p
        JOIN matches m ON p.match_id = m.id
        WHERE ((m.home_team_id = :home_id AND m.away_team_id = :away_id)
            OR (m.home_team_id = :away_id AND m.away_team_id = :home_id))
          AND m.home_score IS NOT NULL
          AND m.away_score IS NOT NULL
    """
    if model_version:
        pred_query += " AND p.model_version = :model_version"
        pred_params["model_version"] = model_version
    pred_query += " ORDER BY p.generated_at DESC LIMIT 50"

    rows = db_query_list(pred_query, pred_params)
    past_predictions = []
    for row in rows:
        pj = parse_prediction_json(row.get("prediction_json") or "{}")
        pred_label, prob = extract_best_prediction_from_pj(pj)
        pred_norm = normalize_label(pred_label)
        if row["home_score"] > row["away_score"]:
            actual = "home_win"
        elif row["away_score"] > row["home_score"]:
            actual = "away_win"
        else:
            actual = "draw"
        past_predictions.append({
            "id": row["id"],
            "match_id": row["match_id"],
            "home_team": row["home_team_name"],
            "away_team": row["away_team_name"],
            "prediction": pred_label,
            "probabilities": pj.get("probabilities") if isinstance(pj, dict) else None,
            "confidence": row.get("confidence") or prob,
            "generated_at": row.get("generated_at"),
            "correct": (pred_norm == actual),
        })

    next_match = db_query_single("""
        SELECT id, home_team_name, away_team_name
        FROM matches
        WHERE ((home_team_id = :home_id AND away_team_id = :away_id)
            OR (home_team_id = :away_id AND away_team_id = :home_id))
          AND (home_score IS NULL OR away_score IS NULL)
        ORDER BY utcDate ASC
        LIMIT 1
    """, {"home_id": home_team_id, "away_id": away_team_id})

    next_match_prediction = None
    if next_match:
        pr = db_query_single(
            "SELECT prediction_json, confidence FROM predictions WHERE match_id = :match_id ORDER BY generated_at DESC LIMIT 1",
            {"match_id": next_match["id"]},
        )
        if pr:
            pj = parse_prediction_json(pr.get("prediction_json") or "{}")
            label, _ = extract_best_prediction_from_pj(pj)
            next_match_prediction = {
                "match_id": next_match["id"],
                "home_team": next_match["home_team_name"],
                "away_team": next_match["away_team_name"],
                "prediction": label,
                "confidence": pr.get("confidence"),
            }

    return jsonify({"h2h_stats": h2h_stats, "past_predictions": past_predictions, "next_match_prediction": next_match_prediction})


@app.route("/api/finished-matches-with-predictions", methods=["GET"])
def finished_matches_with_predictions():
    try:
        months_back = int(request.args.get("months", 2))
        if months_back < 1:
            months_back = 1
        limit = request.args.get("limit")
        limit_clause = f"LIMIT {int(limit)}" if limit and int(limit) > 0 else ""

        now_kenya = datetime.now(UTC).astimezone(KENYA)
        first_day_this_month = now_kenya.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        year = first_day_this_month.year
        month = first_day_this_month.month - months_back
        while month < 1:
            month += 12
            year -= 1
        first_day_target = datetime(year, month, 1, tzinfo=KENYA)
        first_day_target_utc = first_day_target.astimezone(UTC).isoformat()

        query_sql = f"""
        SELECT m.*, p.model_version, p.prediction_json, p.confidence
        FROM matches m
        JOIN predictions p ON m.id = p.match_id
        WHERE m.home_score IS NOT NULL
          AND m.away_score IS NOT NULL
          AND m.utcDate >= :first_day_target_utc
        ORDER BY m.utcDate DESC
        {limit_clause}
        """
        rows = db_query_list(query_sql, {"first_day_target_utc": first_day_target_utc})
        results = []
        for row in rows:
            row_dict = dict(row)
            if row_dict.get("prediction_json"):
                try:
                    row_dict["prediction_json"] = json.loads(row_dict["prediction_json"])
                except Exception:
                    row_dict["prediction_json"] = {}
            results.append(row_dict)
        return jsonify({"count": len(results), "matches": results})
    except Exception as e:
        log_json("error", event="finished_matches_error", error=str(e))
        return jsonify({"error": "internal server error"}), 500


@app.route("/h2h", methods=["GET"])
def h2h_simple():
    home_team_id = request.args.get("home_team_id")
    away_team_id = request.args.get("away_team_id")
    limit = cap_limit(request.args.get("limit", 5), default=5)
    if not home_team_id or not away_team_id:
        return jsonify({"error": "home_team_id and away_team_id are required"}), 400
    try:
        home_team_id = int(home_team_id)
        away_team_id = int(away_team_id)
    except ValueError:
        return jsonify({"error": "team ids must be integers"}), 400

    rows = db_query_list("""
        SELECT id, home_team_id, away_team_id, match_id, home_score, away_score, date_played
        FROM h2h
        WHERE (home_team_id = :home_id AND away_team_id = :away_id)
           OR (home_team_id = :away_id AND away_team_id = :home_id)
        ORDER BY date_played DESC
        LIMIT :limit
    """, {"home_id": home_team_id, "away_id": away_team_id, "limit": limit})
    return jsonify({"count": len(rows), "matches": rows})


@app.route("/tips/value")
def tips_value():
    status_arg = request.args.get("status", "TIMED,SCHEDULED")
    statuses = [s.strip().upper() for s in status_arg.split(",") if s.strip()]
    try:
        placeholders = ",".join([f":s{i}" for i in range(len(statuses))])
        status_params = {f"s{i}": statuses[i] for i in range(len(statuses))}
        tips = db_query_list(f"""
            SELECT v.*,
                   m.utcDate, m.status,
                   m.home_team_id, m.away_team_id,
                   m.home_team_name, m.away_team_name
            FROM matches m
            INNER JOIN value v ON v.match_id = m.id
            WHERE m.status IN ({placeholders})
            ORDER BY m.utcDate ASC
        """, status_params)
        if not tips:
            return jsonify({"success": True, "count": 0, "tips": []})
        team_ids = {t["home_team_id"] for t in tips} | {t["away_team_id"] for t in tips}
        team_placeholders = ",".join([f":tid{i}" for i in range(len(team_ids))])
        team_params = {f"tid{i}": tid for i, tid in enumerate(team_ids)}
        logos_rows = db_query_list(f"SELECT id, crest FROM teams WHERE id IN ({team_placeholders})", team_params)
        logos = {r["id"]: r["crest"] for r in logos_rows}
        for t in tips:
            t["home_team_logo"] = logos.get(t["home_team_id"], "")
            t["away_team_logo"] = logos.get(t["away_team_id"], "")
            t["predicted_score"] = {
                "home": t.get("home_goals_pred"),
                "away": t.get("away_goals_pred"),
                "most_likely": t.get("most_likely_score"),
                "confidence": t.get("conf_score"),
            }
            t["btts"] = {"yes": bool(t.get("btts_yes")) if t.get("btts_yes") is not None else None, "confidence": t.get("conf_btts")}
            t["over_under"] = {
                "over_1_5": {"tip": bool(t.get("over_1_5")) if t.get("over_1_5") is not None else None, "confidence": t.get("conf_over_1_5")},
                "over_2_5": {"tip": bool(t.get("over_2_5")) if t.get("over_2_5") is not None else None, "confidence": t.get("conf_over_2_5")},
                "over_3_5": {"tip": bool(t.get("over_3_5")) if t.get("over_3_5") is not None else None, "confidence": t.get("conf_over_3_5")},
                "over_4_5": {"tip": bool(t.get("over_4_5")) if t.get("over_4_5") is not None else None, "confidence": t.get("conf_over_4_5")},
            }
        return jsonify({"success": True, "count": len(tips), "tips": tips})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/tips/daily", methods=["GET"])
def tips_daily():
    date = request.args.get("date") or datetime.now(KENYA).date().isoformat()

    query_sql = """
        SELECT
            p.id AS prediction_id,
            p.match_id,
            p.model_version,
            p.prediction_json,
            p.confidence,
            p.generated_at AS prediction_time,
            m.competition,
            m.matchday,
            m.utcdate,
            m.status,
            m.home_team_name,
            m.away_team_name,
            m.home_score,
            m.away_score
        FROM predictions p
        JOIN matches m ON p.match_id = m.id
        WHERE m.status IN ('SCHEDULED', 'TIMED', 'PENDING')
          AND DATE(m.utcdate AT TIME ZONE 'Africa/Nairobi') = :date
        ORDER BY p.confidence DESC, m.utcdate ASC
    """

    try:
        rows = db_query_list(query_sql, {"date": date})
        tips = []

        for r in rows:
            try:
                data = parse_prediction_json(r.get("prediction_json")) or {}
                prediction = data.get("prediction")
                probs = data.get("probabilities", {})
            except Exception:
                prediction, probs = None, {}

            tips.append({
                "prediction_id": r.get("prediction_id"),
                "match_id": r.get("match_id"),
                "model_version": r.get("model_version"),
                "confidence": r.get("confidence"),
                "prediction_time": r.get("prediction_time"),
                "prediction": prediction,
                "probabilities": probs,
                "competition": r.get("competition"),
                "matchday": r.get("matchday"),

                "utcdate": r.get("utcdate"),

                "status": r.get("status"),
                "home_team": {
                    "name": r.get("home_team_name"),
                    "score": r.get("home_score"),
                },
                "away_team": {
                    "name": r.get("away_team_name"),
                    "score": r.get("away_score"),
                },
                "venue": r.get("venue"),
            })

        return jsonify({
            "count": len(tips),
            "date": date,
            "tips": tips
        })

    except Exception as e:
        log_json("error", event="/tips/daily_error", error=str(e))
        return jsonify({"error": str(e)}), 500

@app.get("/accumulator")
def accumulator_endpoint():
    by_market = request.args.get("by_market", default="false").lower() == "true"
    by_date = request.args.get("by_date", default="false").lower() == "true"
    folds = request.args.get("folds", default="false").lower() == "true"
    max_games = request.args.get("max_games", default=10, type=int)

    async def _fetch():
        query_sql = """
            SELECT a.*,
                   m.home_team_name AS home_team,
                   m.away_team_name AS away_team
            FROM accumulator a
            JOIN matches m ON m.id = a.match_id
            ORDER BY a.probability DESC
        """
        rows = await fetch_rows(query_sql)

        if folds:
            result = {"fold_1": defaultdict(list), "fold_2": defaultdict(list), "fold_3": defaultdict(list)}
            for row in rows:
                prob = row.get("probability") or 0
                fold_name = None
                if prob > 0.75:
                    fold_name = "fold_1"
                elif 0.60 < prob < 0.75:
                    fold_name = "fold_2"
                elif 0.54 < prob < 0.60:
                    fold_name = "fold_3"
                if fold_name is None:
                    continue
                key = "ALL"
                if by_date and by_market:
                    key = f"{(row.get('match_time') or '')[:10]}_{row.get('market')}"
                elif by_date:
                    key = (row.get('match_time') or '')[:10]
                elif by_market:
                    key = row.get("market")
                if len(result[fold_name][key]) < max_games:
                    result[fold_name][key].append({
                        "home_team": row.get("home_team"),
                        "away_team": row.get("away_team"),
                        "market": row.get("market"),
                        "selection": row.get("selection"),
                        "probability": row.get("probability"),
                        "match_time": row.get("match_time"),
                    })
            return result

        if not by_market and not by_date:
            return [{
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "market": row.get("market"),
                "selection": row.get("selection"),
                "probability": row.get("probability"),
                "match_time": row.get("match_time"),
            } for row in rows]

        if by_date and by_market:
            result = defaultdict(lambda: defaultdict(list))
            for row in rows:
                date = (row.get("match_time") or "")[:10]
                market = row.get("market")
                if len(result[date][market]) < max_games:
                    result[date][market].append({
                        "home_team": row.get("home_team"),
                        "away_team": row.get("away_team"),
                        "market": row.get("market"),
                        "selection": row.get("selection"),
                        "probability": row.get("probability"),
                        "match_time": row.get("match_time"),
                    })
            return result

        if by_date:
            result = defaultdict(list)
            for row in rows:
                date = (row.get("match_time") or "")[:10]
                if len(result[date]) < max_games:
                    result[date].append({
                        "home_team": row.get("home_team"),
                        "away_team": row.get("away_team"),
                        "market": row.get("market"),
                        "selection": row.get("selection"),
                        "probability": row.get("probability"),
                        "match_time": row.get("match_time"),
                    })
            return result

        if by_market:
            result = defaultdict(list)
            for row in rows:
                market = row.get("market")
                if len(result[market]) < max_games:
                    result[market].append({
                        "home_team": row.get("home_team"),
                        "away_team": row.get("away_team"),
                        "market": row.get("market"),
                        "selection": row.get("selection"),
                        "probability": row.get("probability"),
                        "match_time": row.get("match_time"),
                    })
            return result

    data = _run_sync_or_async(_fetch())
    return jsonify(data)


@app.route("/teams", methods=["GET"])
def teams():
    limit = cap_limit(request.args.get("limit", 50000))
    rows = db_query_list("""
        SELECT id, name, short_name, tla, crest, venue, founded
        FROM teams
        ORDER BY name
        LIMIT :limit
    """, {"limit": limit})
    comp_rows = db_query_list("""
        SELECT home_team_id AS team_id, competition
        FROM matches
        WHERE competition IS NOT NULL
        UNION
        SELECT away_team_id AS team_id, competition
        FROM matches
        WHERE competition IS NOT NULL
    """)
    comp_map = {}
    for r in comp_rows:
        comp_map.setdefault(r["team_id"], set()).add(r["competition"])
    teams_out = []
    for t in rows:
        t["competitions"] = sorted(list(comp_map.get(t["id"], [])))
        teams_out.append(t)
    return jsonify({"count": len(teams_out), "teams": teams_out})


@app.route("/matches", methods=["GET"])
@rate_limit(calls=60, per_seconds=60)
@cache_response(ttl=CACHE_TTL.get("/matches", 90))
def matches_list():
    limit = cap_limit(request.args.get("limit", MAX_LIMIT), default=DEFAULT_LIMIT, max_limit=MAX_LIMIT)
    rows = db_query_list("""
        SELECT id, home_team_name, away_team_name,utcdate as utcDate,status
        FROM matches
        ORDER BY utcdate DESC
        LIMIT :limit
    """, {"limit": limit})
    out = []
    for rec in rows:
        raw_dt = rec.get("utcDate")
        if raw_dt:
            try:
                dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
                rec["localDate"] = dt.astimezone(EAT).isoformat()
            except Exception:
                rec["localDate"] = raw_dt
        else:
            rec["localDate"] = None
        out.append(rec)
    return jsonify({"count": len(out), "matches": out})


@app.route("/matches/recent", methods=["GET"])
def matches_recent():
    limit = cap_limit(request.args.get("limit", 300), default=300, max_limit=MAX_LIMIT)
    rows = db_query_list("""
        SELECT id, competition, matchday, utcDate, status,
               home_team_id, away_team_id, home_score, away_score,
               home_team_name, away_team_name, generated_at
        FROM matches WHERE status='FINISHED'
        ORDER BY utcDate DESC LIMIT :limit
    """, {"limit": limit})
    return jsonify({"count": len(rows), "matches": rows})



@app.route("/matches/upcoming", methods=["GET"])
def matches_upcoming():
    limit = cap_limit(
        request.args.get("limit", 1000),
        default=1000,
        max_limit=MAX_LIMIT
    )

    rows = db_query_list("""
        SELECT id, competition, matchday, utcDate, status,
               home_team_id, away_team_id, home_team_name, away_team_name, generated_at
        FROM matches
        WHERE status IN ('SCHEDULED','TIMED')
        ORDER BY utcDate ASC
        LIMIT :limit
    """, {"limit": limit})

    out = []

    for rec in rows:
        utc_raw = rec.get("utcDate") or rec.get("utcdate")

        dt_utc = None
        local_date = None
        timestamp = None

        try:
            dt_utc = _parse_match_datetime(utc_raw)
            if dt_utc is not None:
                dt_local = dt_utc.astimezone(EAT)
                local_date = dt_local.isoformat()
                timestamp = int(dt_utc.timestamp())
        except Exception:
            local_date = utc_raw
            timestamp = None

        rec["localDate"] = local_date
        rec["timestamp"] = timestamp
        out.append(rec)

    return jsonify({
        "success": True,
        "count": len(out),
        "matches": out
    })

@app.route("/predictions/latest", methods=["GET"])
def predictions_latest():
    limit = cap_limit(request.args.get("limit", 100), default=100, max_limit=MAX_LIMIT)
    now_iso = datetime.now(UTC).isoformat()
    sql = """
        SELECT p.match_id, p.model_version, p.prediction_json, p.generated_at,
               m.utcDate, m.status, m.home_team_name, m.away_team_name
        FROM predictions p
        LEFT JOIN matches m ON CAST(p.match_id AS TEXT) = CAST(m.id AS TEXT)
        WHERE m.status IN (:s1, :s2, :s3)
          AND m.utcDate >= :now
        ORDER BY m.utcDate ASC, p.generated_at DESC
        LIMIT :limit
    """
    rows = db_query_list(sql, {
        "s1": UPCOMING_STATUSES[0],
        "s2": UPCOMING_STATUSES[1],
        "s3": UPCOMING_STATUSES[2],
        "now": now_iso,
        "limit": limit,
    })
    out = []
    for row in rows:
        rec = dict(row)
        raw_json = rec.pop("prediction_json", None)
        rec["prediction"] = parse_prediction_json(raw_json) if raw_json else None
        out.append(rec)
    return jsonify({"count": len(out), "predictions": out})


@app.route("/predictions/<int:match_id>", methods=["GET"])
@cache_response(ttl=300)
def match_prediction(match_id):
    row = db_query_single(
        "SELECT prediction_json, confidence FROM predictions WHERE match_id = :match_id ORDER BY generated_at DESC LIMIT 1",
        {"match_id": match_id},
    )
    if not row:
        return jsonify({"error": "prediction not found"}), 404
    pj = parse_prediction_json(row.get("prediction_json"))
    return jsonify({"prediction": pj, "confidence": row.get("confidence")})


@app.route("/players", methods=["GET"])
def players():
    team_id = request.args.get("team_id")
    key_player = request.args.get("key_player")
    injured = request.args.get("injured")
    limit = cap_limit(request.args.get("limit", 10000), default=10000, max_limit=MAX_LIMIT)

    query_sql = """
    SELECT p.id, p.name, p.team_id, t.name AS team_name, p.position, p.rating,
           p.goals, p.assists, p.key_player, p.is_injured
    FROM players p
    LEFT JOIN teams t ON p.team_id = t.id
    """
    conditions = []
    params = {}

    if team_id:
        conditions.append("p.team_id = :team_id")
        params["team_id"] = team_id
    if key_player is not None:
        conditions.append("p.key_player = :key_player")
        params["key_player"] = int(key_player)
    if injured is not None:
        conditions.append("p.is_injured = :injured")
        params["injured"] = int(injured)

    if conditions:
        query_sql += " WHERE " + " AND ".join(conditions)
    query_sql += " LIMIT :limit"
    params["limit"] = limit

    rows = db_query_list(query_sql, params)
    return jsonify({"count": len(rows), "players": rows})


# -------------------------
# Error handlers
# -------------------------
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(e):
    log_json("error", event="internal_server_error", error=str(e))
    return jsonify({"error": "internal server error"}), 500


# -------------------------
# App runner
# -------------------------
if __name__ == "__main__":
    log_json("info", event="api_start", port=int(os.environ.get("PORT", 5003)), db=DATABASE_URL)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5003)), debug=(os.environ.get("FLASK_DEBUG", "0") == "1"))
