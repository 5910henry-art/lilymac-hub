#!/usr/bin/env python3
"""
v1f_DB_COMPATIBLE

- Strict time-aware Poisson predictor
- Compatible with current matches table (no league_id)
- Global draw base
- Recent form + Poisson blending
- Supports injected DB connection (run.py compatible)
"""

from datetime import datetime, timezone
from math import exp, factorial, log2
import traceback
import aiosqlite
from config import DB_FILE

UTC = timezone.utc

# ---------------- CONFIG ----------------
FORM_MATCHES = 30
DECAY_DAYS = 450
MAX_GOALS = 6
MIN_LAMBDA = 0.25
HOME_ADV_MULTIPLIER = 1.15
MIN_CONFIDENCE = 0.52
DRAW_BASE_DEFAULT = 0.24
POISSON_BLEND = 0.3

# ---------------- UTILS ----------------
def parse_date(d):
    return datetime.fromisoformat(d.replace("Z", "+00:00")).astimezone(UTC)

def decay_weight(match_date, ref_date):
    days = (ref_date - match_date).days
    return exp(-days / DECAY_DAYS)

def confidence(h, d, a):
    entropy = -sum(p * log2(p) for p in (h, d, a) if p > 0)
    return round(min(0.95, max(MIN_CONFIDENCE, 1 - entropy / 1.58)), 2)

def poisson_pmf(k, lam):
    try:
        return (lam ** k) * exp(-lam) / factorial(k)
    except Exception:
        return 0.0

# ---------------- DB ----------------
async def fetch_match_info(conn, match_id):
    async with conn.execute(
        "SELECT utcDate, home_team_id, away_team_id FROM matches WHERE id=?",
        (match_id,),
    ) as cur:
        return await cur.fetchone()

async def fetch_recent_matches(conn, team_id, match_date, match_id):
    q = """
    SELECT utcDate, home_team_id, away_team_id, home_score, away_score
    FROM matches
    WHERE utcDate < ?
      AND id != ?
      AND status='FINISHED'
      AND (home_team_id=? OR away_team_id=?)
    ORDER BY utcDate DESC
    LIMIT ?
    """
    async with conn.execute(
        q, (match_date.isoformat(), match_id, team_id, team_id, FORM_MATCHES)
    ) as cur:
        return await cur.fetchall()

async def fetch_global_draw_base(conn, match_date):
    q = """
    SELECT AVG(CASE WHEN home_score=away_score THEN 1 ELSE 0 END)
    FROM matches
    WHERE utcDate < ?
      AND status='FINISHED'
    """
    async with conn.execute(q, (match_date.isoformat(),)) as cur:
        row = await cur.fetchone()
        return row[0] if row and row[0] is not None else DRAW_BASE_DEFAULT

# ---------------- STRENGTH ----------------
def calculate_attack_defense(matches, team_id, ref_date):
    scored, conceded, weight_sum, used = 0.0, 0.0, 0.0, 0

    for m in matches:
        if m[3] is None or m[4] is None:
            continue

        used += 1
        mdate = parse_date(m[0])
        w = decay_weight(mdate, ref_date)

        home, away = m[1], m[2]
        hg, ag = m[3], m[4]

        if team_id == home:
            scored += hg * w
            conceded += ag * w
        else:
            scored += ag * w
            conceded += hg * w

        weight_sum += w

    if weight_sum == 0:
        return 1.0, 1.0, used

    return scored / weight_sum, conceded / weight_sum, used

# ---------------- POISSON ----------------
def build_poisson_matrix(lambda_home, lambda_away):
    probs = {}

    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            probs[(h, a)] = poisson_pmf(h, lambda_home) * poisson_pmf(a, lambda_away)

    total = sum(probs.values()) or 1.0
    for k in probs:
        probs[k] /= total

    p_home = sum(p for (h, a), p in probs.items() if h > a)
    p_draw = sum(p for (h, a), p in probs.items() if h == a)
    p_away = sum(p for (h, a), p in probs.items() if h < a)

    exp_home = sum(h * p for (h, a), p in probs.items())
    exp_away = sum(a * p for (h, a), p in probs.items())

    return p_home, p_draw, p_away, exp_home, exp_away

# ---------------- CORE ----------------
async def _predict_core(conn, match_id, home_id=None, away_id=None):
    row = await fetch_match_info(conn, match_id)
    if not row:
        return None

    match_date = parse_date(row[0])
    home_id = home_id or row[1]
    away_id = away_id or row[2]

    draw_base = await fetch_global_draw_base(conn, match_date)

    home_matches = await fetch_recent_matches(conn, home_id, match_date, match_id)
    away_matches = await fetch_recent_matches(conn, away_id, match_date, match_id)

    home_scored, home_conceded, home_used = calculate_attack_defense(
        home_matches, home_id, match_date
    )
    away_scored, away_conceded, away_used = calculate_attack_defense(
        away_matches, away_id, match_date
    )

    league_home_avg = max(home_scored, 1.0)
    league_away_avg = max(away_scored, 1.0)

    home_attack = home_scored / league_home_avg
    home_defense = home_conceded / league_away_avg
    away_attack = away_scored / league_away_avg
    away_defense = away_conceded / league_home_avg

    lambda_home = max(
        MIN_LAMBDA,
        league_home_avg * home_attack * away_defense * HOME_ADV_MULTIPLIER,
    )
    lambda_away = max(
        MIN_LAMBDA,
        league_away_avg * away_attack * home_defense,
    )

    p_home, p_draw, p_away, exp_home, exp_away = build_poisson_matrix(
        lambda_home, lambda_away
    )

    total_lambda = lambda_home + lambda_away + 1e-6
    lambda_home_prob = lambda_home / total_lambda
    lambda_away_prob = lambda_away / total_lambda

    p_home = (1 - POISSON_BLEND) * lambda_home_prob + POISSON_BLEND * p_home
    p_away = (1 - POISSON_BLEND) * lambda_away_prob + POISSON_BLEND * p_away
    p_draw = (1 - POISSON_BLEND) * draw_base + POISSON_BLEND * p_draw

    s = p_home + p_draw + p_away
    p_home, p_draw, p_away = p_home / s, p_draw / s, p_away / s

    label = max(
        [("Home Win", p_home), ("Draw", p_draw), ("Away Win", p_away)],
        key=lambda x: x[1],
    )[0]

    return {
        "prediction": label,
        "probabilities": {
            "home_win": round(p_home, 3),
            "draw": round(p_draw, 3),
            "away_win": round(p_away, 3),
        },
        "expected_goals": {"home": round(exp_home, 2), "away": round(exp_away, 2)},
        "confidence": confidence(p_home, p_draw, p_away),
        "matches_used": {
            "home_recent": home_used,
            "away_recent": away_used,
        },
        "model": "v1f_db_compatible",
        "generated_at": datetime.now(UTC).isoformat(),
    }

# ---------------- PUBLIC API ----------------
async def predict(match_id, home_id=None, away_id=None, conn=None):
    try:
        if conn:
            return await _predict_core(conn, match_id, home_id, away_id)

        async with aiosqlite.connect(DB_FILE) as new_conn:
            return await _predict_core(new_conn, match_id, home_id, away_id)

    except Exception:
        traceback.print_exc()
        return None

async def predict_home_away(match_id, home_id=None, away_id=None, **kwargs):
    return await predict(match_id, home_id, away_id, conn=kwargs.get("conn"))
