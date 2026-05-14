import os
import json
import time
import asyncio
import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Optional

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_compress import Compress
import jwt
from werkzeug.security import check_password_hash


from config import (
    DB_FILE,
    query_db,
    execute_db,
    UTC,
    KENYA,
    MAX_CONCURRENT,
    BASE_URL,
    HEADERS,
    COMPETITION_MAP,
    PREDICTORS_DIR,
)

# -------------------------
LOG_FILE = os.environ.get("API_LOG_FILE", "api.json.log")
BANK_ROLL = float(os.environ.get("BANK_ROLL", "1000"))
MAX_LIMIT = int(os.environ.get("MAX_LIMIT", "80000"))
DEFAULT_LIMIT = 15
CACHE_TTL = { "/matches": 30}
DEFAULT_RATE = {"calls": 30, "per_seconds": 60}
UPCOMING_STATUSES = ["SCHEDULED", "TIMED", "NS"]

# EAT alias (East Africa Time) -> same as KENYA timezone object
EAT = KENYA

# -------------------------
# App
# -------------------------
app = Flask("lilymac_predictions_hub")
CORS(app)

# response compression
app.config["COMPRESS_LEVEL"] = 6
app.config["COMPRESS_MIN_SIZE"] = 500
Compress(app)

# -------------------------
# Logging (structured JSON)
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
    # avoid duplicate handlers in some reload scenarios
    logger.handlers = [ch, fh]


def log_json(level: str, **kwargs):
    """Structured logging helper used across the app."""
    payload = {
        "ts": datetime.now(UTC).astimezone(KENYA).isoformat(),
        **kwargs,
    }
    if level == "error":
        logger.error(json.dumps(payload, default=str))
    elif level == "warning":
        logger.warning(json.dumps(payload, default=str))
    else:
        logger.info(json.dumps(payload, default=str))

# -------------------------
# Async bridge for SQLite
# -------------------------

def _run_sync(coro):
    """
    Safe async runner for Flask.
    Prevents 'event loop closed' errors under load.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
    else:
        return asyncio.run(coro)


def db_query_list(sql: str, params=()):
    try:
        return _run_sync(query_db(sql, params))
    except Exception as e:
        log_json("error", event="db_query_failed", sql=sql[:120], error=str(e))
        return []


def db_query_single(sql: str, params=()):
    rows = db_query_list(sql, params)
    return rows[0] if rows else None


def db_execute(sql: str, params=()):
    try:
        return _run_sync(execute_db(sql, params))
    except Exception as e:
        log_json("error", event="db_execute_failed", sql=sql[:120], error=str(e))
        raise


# legacy helpers
def query(sql, params=(), single=False):
    return db_query_single(sql, params) if single else db_query_list(sql, params)


def execute(sql, params=()):
    return db_execute(sql, params)


async def fetch_rows(sql, params=()):
    return await query_db(sql, params)


# -------------------------
# Improved Cache Engine
# -------------------------

_cache = {}
_cache_lock = threading.Lock()
CACHE_MAX_ITEMS = 5000  # bound the cache to avoid unbounded growth


def cache_response(ttl: int):
    """
    Lightweight in-memory cache.
    Faster key creation and safer expiration.
    """
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
                # cleanup expired items
                expired_keys = [k for k, v in _cache.items() if v.get("expire", 0) <= now_ts]
                for k in expired_keys:
                    _cache.pop(k, None)

                # enforce max size by removing oldest expiring entries (10% chunk)
                if len(_cache) >= CACHE_MAX_ITEMS:
                    # sort by expire (oldest first) and drop the oldest 10%
                    items_sorted = sorted(_cache.items(), key=lambda kv: kv[1].get("expire", 0))
                    to_remove = max(1, CACHE_MAX_ITEMS // 10)
                    for k, _ in items_sorted[:to_remove]:
                        _cache.pop(k, None)

                _cache[key] = {
                    "value": resp,
                    "expire": now_ts + ttl
                }

            return resp

        return wrapper
    return decorator


# -------------------------
# Improved Rate Limiter
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
                        "window_seconds": per_seconds
                    }), 429

                timestamps.append(now)

            return fn(*args, **kwargs)

        return wrapper

    return decorator
# -------------------------
# Prediction helpers & utilities
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
            key=lambda x: x[1]
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
            "H": "Home Win", "1": "Home Win", "home": "Home Win", "home_win": "Home Win",
            "D": "Draw", "draw": "Draw",
            "A": "Away Win", "2": "Away Win", "away": "Away Win", "away_win": "Away Win"
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

# Health endpoint (useful for gateways / load balancers)
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "prediction_api",
        "time": now_kenya_iso()
    })


# Dashboard
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
        if key not in match_outcome_rates:
            match_outcome_rates[key] = 0.0
            match_outcome_counts[key] = 0

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
    yes_rate = yes_row["win_rate_percentage"] if yes_row else 0.0
    yes_count = yes_row["count"] if yes_row else 0

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
    over_rate = over_row["win_rate_percentage"] if over_row else 0.0
    over_count = over_row["count"] if over_row else 0

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
    general_rate = general_row["win_rate_percentage"] if general_row else 0.0
    general_count = general_row["count"] if general_row else 0

    return jsonify({
        "match_outcome_win_rate": match_outcome_rates,
        "match_outcome_counts": match_outcome_counts,
        "yes_win_rate": yes_rate,
        "yes_count": yes_count,
        "over_win_rate": over_rate,
        "over_count": over_count,
        "general_win_rate": general_rate,
        "general_count": general_count,
        "matches": result
    })


# Grouped predictions
@app.route("/predictions/match/grouped", methods=["GET"])
def grouped_predictions():
    home = request.args.get("home") or None
    away = request.args.get("away") or None
    match_id = request.args.get("match_id") or None

    now = datetime.now(UTC).isoformat()
    query_sql = """
        SELECT m.id, m.home_team_name, m.away_team_name, m.utcDate
        FROM matches m
        INNER JOIN models mo ON m.id = mo.match_id
        WHERE m.utcDate > ?
    """
    params = [now]
    if home:
        query_sql += " AND m.home_team_name LIKE ?"
        params.append(f"%{home}%")
    if away:
        query_sql += " AND m.away_team_name LIKE ?"
        params.append(f"%{away}%")
    if match_id:
        query_sql += " AND m.id = ?"
        params.append(match_id)
    query_sql += " GROUP BY m.id ORDER BY m.utcDate ASC"

    matches = db_query_list(query_sql, tuple(params))
    if not matches:
        return jsonify({"error": "No upcoming matches with predictions found"}), 404

    result = []
    for match in matches:
        mid = match["id"]
        rows = db_query_list("SELECT model_version, prediction_json, confidence FROM models WHERE match_id = ? ORDER BY model_version", (mid,))
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
                "confidence": r.get("confidence")
            })

        grouped_list = []
        for k, v in grouped.items():
            avg_conf = sum((m.get("confidence") or 0) for m in v) / len(v) if v else 0
            grouped_list.append({
                "prediction": k,
                "num_models": len(v),
                "avg_confidence": round(avg_conf, 3),
                "models": v
            })

        grouped_list.sort(key=lambda x: (x["num_models"], x["avg_confidence"]), reverse=True)
        result.append({
            "match_id": match["id"],
            "home": match["home_team_name"],
            "away": match["away_team_name"],
            "utcDate": match["utcDate"],
            "grouped_predictions": grouped_list
        })

    return jsonify(result)


# Bookmark & Kelly staking
@app.route("/bookmark/all", methods=["GET"])
def all_bookmarks():
    model_version = request.args.get("model_version")
    bookmarks = []

    if model_version:
        rows = db_query_list("""
            SELECT
                b.match_id,
                b.league,
                b.home_team,
                b.away_team,
                b.home_odds,
                b.draw_odds,
                b.away_odds,
                m.prediction_json
            FROM bookmark b
            JOIN models m ON b.match_id = m.match_id
            WHERE m.model_version = ?
        """, (model_version,))
        for r in rows:
            bm = dict(r)
            for k in ["home_odds", "draw_odds", "away_odds"]:
                try:
                    bm[k] = float(bm[k])
                except Exception:
                    bm[k] = 0.0
            try:
                pred = json.loads(bm.get("prediction_json") or "{}")
            except Exception:
                pred = {}
            probs = pred.get("probabilities", {})
            prediction = pred.get("prediction")
            predicted_goals = pred.get("predicted_goals")
            EV_home = probs.get("home_win", 0) * bm["home_odds"] - 1
            EV_draw = probs.get("draw", 0) * bm["draw_odds"] - 1
            EV_away = probs.get("away_win", 0) * bm["away_odds"] - 1
            if prediction in ["Home", "Home Win"]:
                odds = bm["home_odds"]; prob = probs.get("home_win", 0); pred_EV = EV_home
            elif prediction in ["Away", "Away Win"]:
                odds = bm["away_odds"]; prob = probs.get("away_win", 0); pred_EV = EV_away
            else:
                odds = bm["draw_odds"]; prob = probs.get("draw", 0); pred_EV = EV_draw
            kelly = calculate_kelly(prob, odds)
            stake_amount = kelly * BANK_ROLL
            EVs = {"Home Win": round(EV_home, 6), "Draw": round(EV_draw, 6), "Away Win": round(EV_away, 6)}
            top_EV_Bet = max(EVs, key=EVs.get)
            bookmarks.append({
                "match_id": bm["match_id"],
                "league": bm["league"],
                "home_team": bm["home_team"],
                "away_team": bm["away_team"],
                "odds": {"home": bm["home_odds"], "draw": bm["draw_odds"], "away": bm["away_odds"]},
                "prediction": prediction,
                "prediction_prob": round(prob, 6),
                "prediction_EV": round(pred_EV, 6),
                "kelly": round(kelly, 6),
                "stake_amount": round(stake_amount, 2),
                "EVs": EVs,
                "top_EV_Bet": top_EV_Bet,
                "predicted_goals": predicted_goals
            })
    else:
        rows = db_query_list("SELECT * FROM bookmark")
        for r in rows:
            bm = dict(r)
            evs = {"Home": bm.get("EV_home", 0) or 0, "Draw": bm.get("EV_draw", 0) or 0, "Away": bm.get("EV_away", 0) or 0}
            bm["top_EV_Bet"] = max(evs, key=evs.get)
            bookmarks.append(bm)

    return jsonify({"status": "ok", "count": len(bookmarks), "bookmarks": bookmarks})


# team-match-overview
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
        WHERE id = ?
    """, (match_id,))
    if not match_row:
        return jsonify({"error": "match_id not found"}), 404

    home_team_id = match_row["home_team_id"]
    away_team_id = match_row["away_team_id"]

    h2h_rows = db_query_list("""
        SELECT id AS match_id, home_team_id, away_team_id,
               home_team_name, away_team_name,
               home_score, away_score, utcDate AS date_played
        FROM matches
        WHERE ((home_team_id = ? AND away_team_id = ?)
            OR (home_team_id = ? AND away_team_id = ?))
        ORDER BY utcDate DESC
        LIMIT ?
    """, (home_team_id, away_team_id, away_team_id, home_team_id, h2h_limit))

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
                home_wins += 1
                home_form.append("W"); away_form.append("L")
            else:
                away_wins += 1
                home_form.append("L"); away_form.append("W")
        elif a > h:
            if m["away_team_id"] == home_team_id:
                home_wins += 1
                home_form.append("W"); away_form.append("L")
            else:
                away_wins += 1
                home_form.append("L"); away_form.append("W")
        else:
            draws += 1
            home_form.append("D"); away_form.append("D")

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
        "prediction_suggestion":
            f"Home: {round(home_wins / total * 100, 2) if total else 0}%, "
            f"Draw: {round(draws / total * 100, 2) if total else 0}%, "
            f"Away: {round(away_wins / total * 100, 2) if total else 0}%",
        "matches": h2h_matches
    }

    pred_params = [home_team_id, away_team_id, away_team_id, home_team_id]
    pred_query = """
        SELECT p.id, p.match_id, p.prediction_json, p.confidence, p.generated_at,
               m.home_score, m.away_score,
               m.home_team_name, m.away_team_name
        FROM predictions p
        JOIN matches m ON p.match_id = m.id
        WHERE ((m.home_team_id = ? AND m.away_team_id = ?)
            OR (m.home_team_id = ? AND m.away_team_id = ?))
          AND m.home_score IS NOT NULL
          AND m.away_score IS NOT NULL
    """

    if model_version:
        pred_query += " AND p.model_version = ?"
        pred_params.append(model_version)

    pred_query += " ORDER BY p.generated_at DESC LIMIT 50"

    rows = db_query_list(pred_query, tuple(pred_params))
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
            "correct": (pred_norm == actual)
        })

    next_match = db_query_single("""
        SELECT id, home_team_name, away_team_name
        FROM matches
        WHERE ((home_team_id = ? AND away_team_id = ?)
            OR (home_team_id = ? AND away_team_id = ?))
          AND (home_score IS NULL OR away_score IS NULL)
        ORDER BY utcDate ASC
        LIMIT 1
    """, (home_team_id, away_team_id, away_team_id, home_team_id))

    next_match_prediction = None
    if next_match:
        pr = db_query_single("SELECT prediction_json, confidence FROM predictions WHERE match_id = ? ORDER BY generated_at DESC LIMIT 1", (next_match["id"],))
        if pr:
            pj = parse_prediction_json(pr.get("prediction_json") or "{}")
            label, _ = extract_best_prediction_from_pj(pj)
            next_match_prediction = {
                "match_id": next_match["id"],
                "home_team": next_match["home_team_name"],
                "away_team": next_match["away_team_name"],
                "prediction": label,
                "confidence": pr.get("confidence")
            }

    return jsonify({
        "h2h_stats": h2h_stats,
        "past_predictions": past_predictions,
        "next_match_prediction": next_match_prediction
    })


# Finished matches with predictions (monthly)
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

        # compute target month/year
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
          AND m.utcDate >= ?
        ORDER BY m.utcDate DESC
        {limit_clause}
        """
        rows = db_query_list(query_sql, (first_day_target_utc,))
        results = []
        for row in rows:
            row_dict = dict(row)
            if "prediction_json" in row_dict and row_dict["prediction_json"]:
                try:
                    row_dict["prediction_json"] = json.loads(row_dict["prediction_json"])
                except Exception:
                    row_dict["prediction_json"] = {}
            results.append(row_dict)
        return jsonify({"count": len(results), "matches": results})
    except Exception as e:
        log_json("error", event="finished_matches_error", error=str(e))
        return jsonify({"error": "internal server error"}), 500


# H2H simple
@app.route("/h2h", methods=["GET"])
def h2h_simple():
    home_team_id = request.args.get("home_team_id")
    away_team_id = request.args.get("away_team_id")
    limit = cap_limit(request.args.get("limit", 5), default=5)
    if not home_team_id or not away_team_id:
        return jsonify({"error": "home_team_id and away_team_id are required"}), 400
    try:
        home_team_id = int(home_team_id); away_team_id = int(away_team_id)
    except ValueError:
        return jsonify({"error": "team ids must be integers"}), 400

    rows = db_query_list("""
        SELECT id, home_team_id, away_team_id, match_id, home_score, away_score, date_played
        FROM h2h
        WHERE (home_team_id = ? AND away_team_id = ?)
           OR (home_team_id = ? AND away_team_id = ?)
        ORDER BY date_played DESC
        LIMIT ?
    """, (home_team_id, away_team_id, away_team_id, home_team_id, limit))
    return jsonify({"count": len(rows), "matches": rows})


# Tips (value)
@app.route("/tips/value")
def tips_value():
    status_arg = request.args.get("status", "TIMED,SCHEDULED")
    statuses = [s.strip().upper() for s in status_arg.split(",") if s.strip()]
    try:
        placeholders = ",".join("?" * len(statuses))
        tips = db_query_list(f"""
            SELECT v.*,
                   m.utcDate, m.status,
                   m.home_team_id, m.away_team_id,
                   m.home_team_name, m.away_team_name
            FROM matches m
            INNER JOIN value v ON v.match_id = m.id
            WHERE m.status IN ({placeholders})
            ORDER BY m.utcDate ASC
        """, tuple(statuses))
        if not tips:
            return jsonify({"success": True, "count": 0, "tips": []})
        team_ids = {t["home_team_id"] for t in tips} | {t["away_team_id"] for t in tips}
        placeholders = ",".join("?" * len(team_ids))
        logos_rows = db_query_list(f"SELECT id, crest FROM teams WHERE id IN ({placeholders})", tuple(team_ids))
        logos = {r["id"]: r["crest"] for r in logos_rows}
        for t in tips:
            t["home_team_logo"] = logos.get(t["home_team_id"], "")
            t["away_team_logo"] = logos.get(t["away_team_id"], "")
            t["predicted_score"] = {"home": t.get("home_goals_pred"), "away": t.get("away_goals_pred"), "most_likely": t.get("most_likely_score"), "confidence": t.get("conf_score")}
            t["btts"] = {"yes": bool(t.get("btts_yes")) if t.get("btts_yes") is not None else None, "confidence": t.get("conf_btts")}
            t["over_under"] = {
                "over_1_5": {"tip": bool(t.get("over_1_5")) if t.get("over_1_5") is not None else None, "confidence": t.get("conf_over_1_5")},
                "over_2_5": {"tip": bool(t.get("over_2_5")) if t.get("over_2_5") is not None else None, "confidence": t.get("conf_over_2_5")},
                "over_3_5": {"tip": bool(t.get("over_3_5")) if t.get("over_3_5") is not None else None, "confidence": t.get("conf_over_3_5")},
                "over_4_5": {"tip": bool(t.get("over_4_5")) if t.get("over_4_5") is not None else None, "confidence": t.get("conf_over_4_5")}
            }
        return jsonify({"success": True, "count": len(tips), "tips": tips})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# Tips (daily)
@app.route("/tips/daily", methods=["GET"])
def tips_daily():
    date = request.args.get("date") or datetime.now(KENYA).date().isoformat()
    query = """
        SELECT
            p.id AS prediction_id,
            p.match_id,
            p.model_version,
            p.prediction_json,
            p.confidence,
            p.generated_at AS prediction_time,
            m.competition,
            m.matchday,
            COALESCE(m.localDate, m.utcDate) AS localDate,
            m.status,
            m.home_team_name,
            m.away_team_name,
            m.home_score,
            m.away_score,
            m.venue
        FROM predictions p
        JOIN matches m ON p.match_id = m.id
        WHERE DATE(COALESCE(m.localDate, m.utcDate)) = ?
        AND m.status IN ('SCHEDULED', 'TIMED', 'PENDING')
        ORDER BY p.confidence DESC, COALESCE(m.localDate, m.utcDate) ASC
    """
    try:
        rows = db_query_list(query, (date,))
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
                "localDate": r.get("localDate"),
                "status": r.get("status"),
                "home_team": {"name": r.get("home_team_name"), "score": r.get("home_score")},
                "away_team": {"name": r.get("away_team_name"), "score": r.get("away_score")},
                "venue": r.get("venue")
            })
        return jsonify({"count": len(tips), "date": date, "tips": tips})
    except Exception as e:
        log_json("error", event="/tips/daily_error", error=str(e))
        return jsonify({"error": str(e)}), 500

# Accumulator (async fetch)
@app.get("/accumulator")
def accumulator_endpoint():
    by_market = request.args.get("by_market", default="false").lower() == "true"
    by_date = request.args.get("by_date", default="false").lower() == "true"
    folds = request.args.get("folds", default="false").lower() == "true"
    max_games = request.args.get("max_games", default=10, type=int)

    async def _fetch():
        query = """
            SELECT a.*,
                   m.home_team_name AS home_team,
                   m.away_team_name AS away_team
            FROM accumulator a
            JOIN matches m ON m.id = a.match_id
            ORDER BY a.probability DESC
        """
        rows = await fetch_rows(query)

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
                    key = f"{row.get('match_time','')[:10]}_{row.get('market')}"
                elif by_date:
                    key = row.get('match_time','')[:10]
                elif by_market:
                    key = row.get('market')
                if len(result[fold_name][key]) < max_games:
                    result[fold_name][key].append({
                        "home_team": row.get("home_team"),
                        "away_team": row.get("away_team"),
                        "market": row.get("market"),
                        "selection": row.get("selection"),
                        "probability": row.get("probability"),
                        "match_time": row.get("match_time")
                    })
            return result
        else:
            if not by_market and not by_date:
                return [{
                    "home_team": row.get("home_team"),
                    "away_team": row.get("away_team"),
                    "market": row.get("market"),
                    "selection": row.get("selection"),
                    "probability": row.get("probability"),
                    "match_time": row.get("match_time")
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
                            "match_time": row.get("match_time")
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
                            "match_time": row.get("match_time")
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
                            "match_time": row.get("match_time")
                        })
                return result

    # use safe runner to avoid asyncio.run in running loop
    data = _run_sync(_fetch())
    return jsonify(data)


# Teams endpoint
@app.route("/teams", methods=["GET"])
def teams():
    limit = cap_limit(request.args.get("limit", 50000))
    rows = db_query_list("""
        SELECT id, name, short_name, tla, crest, venue, founded
        FROM teams
        ORDER BY name
        LIMIT ?
    """, (limit,))
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


# Matches list
@app.route("/matches", methods=["GET"])
@rate_limit(calls=60, per_seconds=60)
@cache_response(ttl=CACHE_TTL.get("/matches", 90))
def matches_list():
    limit = min(int(request.args.get("limit", MAX_LIMIT)), MAX_LIMIT)
    rows = db_query_list("""
        SELECT id, home_team_name, away_team_name, COALESCE(utcDate, localDate, '') as utcDate, status
        FROM matches
        ORDER BY utcDate DESC
        LIMIT ?
    """, (limit,))
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


# Matches recent (finished)
@app.route("/matches/recent", methods=["GET"])
def matches_recent():
    limit = cap_limit(request.args.get("limit", 300))
    rows = db_query_list("""
        SELECT id, competition, matchday, utcDate, status,
               home_team_id, away_team_id, home_score, away_score,
               home_team_name, away_team_name, generated_at
        FROM matches WHERE status='FINISHED'
        ORDER BY utcDate DESC LIMIT ?
    """, (limit,))
    return jsonify({"count": len(rows), "matches": rows})


# Matches upcoming
@app.route("/matches/upcoming", methods=["GET"])
def matches_upcoming():
    limit = cap_limit(request.args.get("limit", 1000))
    rows = db_query_list("""
        SELECT id, competition, matchday, utcDate, status,
               home_team_id, away_team_id, home_team_name, away_team_name, generated_at
        FROM matches WHERE status IN ('SCHEDULED','TIMED')
        ORDER BY utcDate ASC LIMIT ?
    """, (limit,))
    out = []
    for rec in rows:
        if rec.get("utcDate"):
            try:
                dt = datetime.fromisoformat(rec["utcDate"].replace("Z", "+00:00"))
                rec["localDate"] = dt.astimezone(EAT).isoformat()
            except Exception:
                rec["localDate"] = rec["utcDate"]
        out.append(rec)
    return jsonify({"count": len(out), "matches": out})

# Predictions latest
@app.route("/predictions/latest", methods=["GET"])
def predictions_latest():
    limit = cap_limit(request.args.get("limit", 100))
    sql = """
        SELECT p.match_id, p.model_version, p.prediction_json, p.generated_at,
               m.utcDate, m.status, m.home_team_name, m.away_team_name
        FROM predictions p
        LEFT JOIN matches m ON CAST(p.match_id AS TEXT) = CAST(m.id AS TEXT)
        WHERE m.status IN (?, ?, ?)
          AND m.utcDate >= datetime('now')
        ORDER BY datetime(m.utcDate) ASC, datetime(p.generated_at) DESC
        LIMIT ?
    """
    rows = db_query_list(sql, (*UPCOMING_STATUSES, limit))
    out = []
    for row in rows:
        rec = dict(row)
        raw_json = rec.pop("prediction_json", None)
        rec["prediction"] = parse_prediction_json(raw_json) if raw_json else None
        out.append(rec)
    return jsonify({"count": len(out), "predictions": out})


# Cached single match prediction endpoint
@app.route("/predictions/<int:match_id>", methods=["GET"])
@cache_response(ttl=300)
def match_prediction(match_id):
    row = db_query_single(
        "SELECT prediction_json, confidence FROM predictions WHERE match_id = ? ORDER BY generated_at DESC LIMIT 1",
        (match_id,)
    )
    if not row:
        return jsonify({"error": "prediction not found"}), 404

    pj = parse_prediction_json(row.get("prediction_json"))
    return jsonify({"prediction": pj, "confidence": row.get("confidence")})


# Players endpoint
@app.route("/players", methods=["GET"])
def players():
    team_id = request.args.get("team_id")
    key_player = request.args.get("key_player")
    injured = request.args.get("injured")
    limit = cap_limit(request.args.get("limit", 10000))

    query_sql = """
    SELECT p.id, p.name, p.team_id, t.name AS team_name, p.position, p.rating,
           p.goals, p.assists, p.key_player, p.is_injured
    FROM players p
    LEFT JOIN teams t ON p.team_id = t.id
    """
    conditions = []
    params = []

    if team_id:
        conditions.append("p.team_id = ?"); params.append(team_id)
    if key_player is not None:
        conditions.append("p.key_player = ?"); params.append(int(key_player))
    if injured is not None:
        conditions.append("p.is_injured = ?"); params.append(int(injured))

    if conditions:
        query_sql += " WHERE " + " AND ".join(conditions)
    query_sql += " LIMIT ?"
    params.append(limit)

    rows = db_query_list(query_sql, tuple(params))
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
    log_json("info", event="api_start", port=int(os.environ.get("PORT", 5003)), db=DB_FILE)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5003)), debug=(os.environ.get("FLASK_DEBUG", "0") == "1"))
