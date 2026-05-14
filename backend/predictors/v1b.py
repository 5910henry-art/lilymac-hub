#!/usr/bin/env python3
"""
v1b_fully_timeaware_h2h_poisson.py

Fully strict time-aware football predictor
Supports injected DB connection from run.py
"""

from datetime import datetime, timezone
from math import exp, factorial, log2
import traceback
import aiosqlite
from config import DB_FILE

UTC = timezone.utc

# ---------------- CONFIG ----------------
FORM_N = 8
H2H_N = 10
DECAY_DAYS = 365
HOME_ADV = 0.15
DRAW_BASE = 0.22
MAX_GOALS = 5
POISSON_BLEND = 0.3
MIN_CONFIDENCE = 0.55
HOME_ADV_MULTIPLIER = 1.08
DRAW_BOOST_UNIT = 0.03
DRAW_CAP = 0.12

# ---------------- UTILS ----------------
def parse_date(d):
    return datetime.fromisoformat(d.replace("Z", "+00:00")).replace(tzinfo=UTC)

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
        (match_id,)
    ) as cur:
        return await cur.fetchone()

async def fetch_h2h(conn, home_id, away_id, match_date, match_id):
    q = """
    SELECT utcDate, home_team_id, away_team_id, home_score, away_score
    FROM matches
    WHERE utcDate < ?
      AND id != ?
      AND ((home_team_id=? AND away_team_id=?) OR (home_team_id=? AND away_team_id=?))
      AND status='FINISHED'
    ORDER BY utcDate DESC
    LIMIT ?
    """
    async with conn.execute(q, (
        match_date.isoformat(), match_id,
        home_id, away_id, away_id, home_id, H2H_N
    )) as cur:
        return await cur.fetchall()

async def fetch_team_form(conn, team_id, match_date, match_id):
    q = """
    SELECT utcDate, home_team_id, away_team_id, home_score, away_score
    FROM matches
    WHERE utcDate < ?
      AND id != ?
      AND (home_team_id=? OR away_team_id=?)
      AND status='FINISHED'
    ORDER BY utcDate DESC
    LIMIT ?
    """
    async with conn.execute(q, (
        match_date.isoformat(), match_id,
        team_id, team_id, FORM_N
    )) as cur:
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

# ---------------- CALCULATIONS ----------------
def calc_form(matches, team_id, ref_date):
    pts, wsum, used = 0.0, 0.0, 0
    for m in matches:
        if m[3] is None or m[4] is None:
            continue
        used += 1
        mdate = parse_date(m[0])
        w = decay_weight(mdate, ref_date)
        home, away = m[1], m[2]
        hg, ag = m[3], m[4]
        gd = (hg - ag) if team_id == home else (ag - hg)
        p = 1.0 if gd > 0 else 0.5 if gd == 0 else 0.0
        pts += p * w
        wsum += w
    return pts / wsum if wsum else 0.5, used

def calculate_attack_defense(matches, team_id, league_home_avg, league_away_avg, ref_date):
    scored, conceded, wsum, used = 0.0, 0.0, 0.0, 0
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
        wsum += w

    if wsum == 0:
        return 1.0, 1.0, used

    attack = (scored / wsum) / league_home_avg if league_home_avg else 1.0
    defense = (conceded / wsum) / league_away_avg if league_away_avg else 1.0
    return attack, defense, used

def build_poisson_probs(lh, la):
    probs = {}
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            probs[(h, a)] = poisson_pmf(h, lh) * poisson_pmf(a, la)

    total = sum(probs.values()) or 1.0
    for k in probs:
        probs[k] /= total

    home = sum(p for (h, a), p in probs.items() if h > a)
    draw = sum(p for (h, a), p in probs.items() if h == a)
    away = sum(p for (h, a), p in probs.items() if h < a)
    exp_home = sum(h * p for (h, a), p in probs.items())
    exp_away = sum(a * p for (h, a), p in probs.items())

    return {
        "home": home,
        "draw": draw,
        "away": away,
        "expected_goals": {"home": exp_home, "away": exp_away}
    }

# ---------------- CORE ----------------
async def _predict_core(conn, match_id, home_id=None, away_id=None):
    row = await fetch_match_info(conn, match_id)
    if not row:
        return None

    match_date = parse_date(row[0])
    home_id = home_id or row[1]
    away_id = away_id or row[2]

    league_home_avg, league_away_avg = await fetch_league_averages(conn, match_date)

    h2h_matches = await fetch_h2h(conn, home_id, away_id, match_date, match_id)
    h2h_home, h2h_used_home = calc_form(h2h_matches, home_id, match_date)
    h2h_away, h2h_used_away = calc_form(h2h_matches, away_id, match_date)

    home_form_matches = await fetch_team_form(conn, home_id, match_date, match_id)
    away_form_matches = await fetch_team_form(conn, away_id, match_date, match_id)

    home_form, home_form_used = calc_form(home_form_matches, home_id, match_date)
    away_form, away_form_used = calc_form(away_form_matches, away_id, match_date)

    home_attack, home_defense, _ = calculate_attack_defense(
        home_form_matches, home_id, league_home_avg, league_away_avg, match_date
    )
    away_attack, away_defense, _ = calculate_attack_defense(
        away_form_matches, away_id, league_home_avg, league_away_avg, match_date
    )

    hp = 0.45 * home_form + 0.35 * h2h_home + HOME_ADV
    ap = 0.45 * away_form + 0.35 * h2h_away

    lh = max(0.4, hp * home_attack / away_defense * HOME_ADV_MULTIPLIER)
    la = max(0.4, ap * away_attack / home_defense)

    poisson_p = build_poisson_probs(lh, la)

    p_home = (1 - POISSON_BLEND) * hp + POISSON_BLEND * poisson_p["home"]
    p_draw = (1 - POISSON_BLEND) * DRAW_BASE + POISSON_BLEND * poisson_p["draw"]
    p_away = (1 - POISSON_BLEND) * ap + POISSON_BLEND * poisson_p["away"]

    s = p_home + p_draw + p_away
    p_home /= s; p_draw /= s; p_away /= s

    label = max(
        {"Home Win": p_home, "Draw": p_draw, "Away Win": p_away},
        key=lambda k: {"Home Win": p_home, "Draw": p_draw, "Away Win": p_away}[k]
    )

    return {
        "prediction": label,
        "probabilities": {
            "home_win": round(p_home, 3),
            "draw": round(p_draw, 3),
            "away_win": round(p_away, 3),
        },
        "expected_goals": {
            "home": round(poisson_p["expected_goals"]["home"], 2),
            "away": round(poisson_p["expected_goals"]["away"], 2),
        },
        "confidence": confidence(p_home, p_draw, p_away),
        "model": "v1b_fully_timeaware",
        "generated_at": datetime.now(UTC).isoformat()
    }

# ---------------- PUBLIC ENTRY ----------------
async def predict(match_id, home_id=None, away_id=None, conn=None):
    try:
        if conn:
            return await _predict_core(conn, match_id, home_id, away_id)

        async with aiosqlite.connect(DB_FILE) as local_conn:
            return await _predict_core(local_conn, match_id, home_id, away_id)

    except Exception:
        traceback.print_exc()
        return None


async def predict_home_away(match_id, home_id=None, away_id=None, **kwargs):
    return await predict(match_id, home_id, away_id, conn=kwargs.get("conn"))
