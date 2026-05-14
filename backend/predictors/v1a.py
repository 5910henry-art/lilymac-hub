#!/usr/bin/env python3
"""
v1a_fully_timeaware_attack_defense.py (UPDATED)

- Fully strict time-aware attack/defense Poisson model
- Excludes current and future matches
- Uses decay weighting
- Supports injected DB connection from runner (preferred)
- Falls back to its own connection if none provided
"""

from datetime import datetime, timezone
from math import exp, factorial, log2
import traceback
import aiosqlite
from config import DB_FILE

UTC = timezone.utc

# ---------------- CONFIG ----------------
FORM_MATCHES = 20
DECAY_DAYS = 365
MAX_GOALS = 6
MIN_LAMBDA = 0.25
HOME_ADV_MULTIPLIER = 1.08
MIN_CONFIDENCE = 0.52
DRAW_BASE = 0.22
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

# ---------------- DB QUERIES ----------------
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


async def fetch_league_averages(conn, match_date):
    q = """
    SELECT AVG(home_score), AVG(away_score)
    FROM matches
    WHERE utcDate < ?
      AND status='FINISHED'
    """
    async with conn.execute(q, (match_date.isoformat(),)) as cur:
        row = await cur.fetchone()
        if row and row[0] is not None and row[1] is not None:
            return row[0], row[1]
        return 1.4, 1.1

# ---------------- STRENGTH CALC ----------------
def calculate_attack_defense(matches, team_id, ref_date):
    scored = conceded = weight_sum = 0.0
    used = 0

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

# ---------------- CORE LOGIC ----------------
async def _predict_core(conn, match_id, home_id=None, away_id=None):
    row = await fetch_match_info(conn, match_id)
    if not row:
        return None

    match_date = parse_date(row[0])
    home_id = home_id or row[1]
    away_id = away_id or row[2]

    league_home_avg, league_away_avg = await fetch_league_averages(conn, match_date)

    home_matches = await fetch_recent_matches(conn, home_id, match_date, match_id)
    away_matches = await fetch_recent_matches(conn, away_id, match_date, match_id)

    home_scored, home_conceded, home_used = calculate_attack_defense(
        home_matches, home_id, match_date
    )
    away_scored, away_conceded, away_used = calculate_attack_defense(
        away_matches, away_id, match_date
    )

    home_attack = home_scored / league_home_avg if league_home_avg else 1.0
    home_defense = home_conceded / league_away_avg if league_away_avg else 1.0
    away_attack = away_scored / league_away_avg if league_away_avg else 1.0
    away_defense = away_conceded / league_home_avg if league_home_avg else 1.0

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

    # Blend structural draw bias slightly
    p_draw = (1 - POISSON_BLEND) * DRAW_BASE + POISSON_BLEND * p_draw

    s = p_home + p_draw + p_away
    p_home /= s
    p_draw /= s
    p_away /= s

    label = (
        "Home Win"
        if p_home > max(p_draw, p_away)
        else "Away Win"
        if p_away > max(p_home, p_draw)
        else "Draw"
    )

    return {
        "prediction": label,
        "probabilities": {
            "home_win": round(p_home, 3),
            "draw": round(p_draw, 3),
            "away_win": round(p_away, 3),
        },
        "expected_goals": {
            "home": round(exp_home, 2),
            "away": round(exp_away, 2),
        },
        "confidence": confidence(p_home, p_draw, p_away),
        "matches_used": {
            "home_recent": home_used,
            "away_recent": away_used,
        },
        "model": "v1a",
        "generated_at": datetime.now(UTC).isoformat(),
    }

# ---------------- PUBLIC ENTRY ----------------
async def predict(match_id, home_id=None, away_id=None, conn=None):
    try:
        if conn is not None:
            return await _predict_core(conn, match_id, home_id, away_id)

        async with aiosqlite.connect(DB_FILE) as fallback_conn:
            await fallback_conn.execute("PRAGMA journal_mode=WAL;")
            await fallback_conn.execute("PRAGMA synchronous=NORMAL;")
            await fallback_conn.execute("PRAGMA temp_store=MEMORY;")
            await fallback_conn.execute("PRAGMA foreign_keys=ON;")
            return await _predict_core(fallback_conn, match_id, home_id, away_id)

    except Exception:
        traceback.print_exc()
        return None


async def predict_home_away(match_id, home_id=None, away_id=None, conn=None, **kwargs):
    return await predict(match_id, home_id=home_id, away_id=away_id, conn=conn)
