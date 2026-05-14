#!/usr/bin/env python3
"""
V5_TIMEAWARE_STRICT_ATTACK_DEFENSE_SQL_CONN
- Strict H2H + home/away form
- Attack/defense Poisson model
- DB-compatible (no league_id needed)
- Async, shared aiosqlite.Connection
"""

import logging
import traceback
from datetime import datetime, timezone
from math import exp, factorial, log2
from typing import Optional, Any
import aiosqlite

# ---------------- CONFIG ----------------
H2H_N = 8
FORM_N = 5
DECAY = 0.9
HOME_ADVANTAGE = 1.18
ALPHA_FORM = 0.25
POISSON_MAX_GOALS = 5
MIN_LAMBDA = 0.25
DRAW_BASE = 0.24
POISSON_BLEND = 0.3
MIN_CONFIDENCE = 0.52

UTC = timezone.utc

# ---------------- LOGGING ----------------
logger = logging.getLogger("v5_sql_strict")
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [v5_sql_strict] %(message)s"))
    logger.addHandler(ch)
logger.setLevel(logging.INFO)

# ---------------- UTILS ----------------
def now_iso():
    return datetime.now(UTC).isoformat()

def parse_date(d):
    return datetime.fromisoformat(d.replace("Z", "+00:00")).replace(tzinfo=UTC)

def decay_weight(match_date, ref_date):
    days = (ref_date - match_date).days
    return exp(-days / 450)  # slower decay

def confidence(h, d, a):
    entropy = -sum(p*log2(p) for p in (h,d,a) if p>0)
    return round(min(0.95, max(MIN_CONFIDENCE, 1 - entropy/1.58)), 2)

def poisson_pmf(k, lam):
    try:
        return (lam ** k) * exp(-lam) / factorial(k)
    except Exception:
        return 0.0

def build_poisson_matrix(lambda_home, lambda_away):
    probs = {}
    for h in range(POISSON_MAX_GOALS+1):
        for a in range(POISSON_MAX_GOALS+1):
            probs[(h,a)] = poisson_pmf(h, lambda_home)*poisson_pmf(a, lambda_away)
    total = sum(probs.values()) or 1.0
    for k in probs:
        probs[k] /= total
    p_home = sum(p for (h,a),p in probs.items() if h>a)
    p_draw = sum(p for (h,a),p in probs.items() if h==a)
    p_away = sum(p for (h,a),p in probs.items() if h<a)
    exp_home = sum(h*p for (h,a),p in probs.items())
    exp_away = sum(a*p for (h,a),p in probs.items())
    return p_home, p_draw, p_away, exp_home, exp_away

# ---------------- DB QUERIES ----------------
async def get_match_utc(conn, match_id):
    async with conn.execute("SELECT utcDate, home_team_id, away_team_id FROM matches WHERE id=? LIMIT 1", (match_id,)) as cur:
        row = await cur.fetchone()
        if row:
            return parse_date(row[0]), row[1], row[2]
    return None, None, None

async def fetch_recent_matches(conn, team_id, match_date, match_id):
    q = """
        SELECT utcDate, home_team_id, away_team_id, home_score, away_score
        FROM matches
        WHERE utcDate < ?
          AND id != ?
          AND home_score IS NOT NULL
          AND (home_team_id=? OR away_team_id=?)
        ORDER BY utcDate DESC
        LIMIT ?
    """
    async with conn.execute(q, (match_date.isoformat(), match_id, team_id, team_id, FORM_N)) as cur:
        return await cur.fetchall()

# ---------------- H2H & FORM ----------------
async def compute_h2h(conn, home_id, away_id, match_utc, match_id):
    query = """
        SELECT home_team_id, away_team_id, home_score, away_score, match_id
        FROM h2h
        WHERE ((home_team_id=? AND away_team_id=?) OR (home_team_id=? AND away_team_id=?))
          AND datetime(date_played) < datetime(?)
          AND match_id != ?
        ORDER BY date_played DESC
        LIMIT ?
    """
    args = (home_id, away_id, away_id, home_id, match_utc.isoformat(), match_id, H2H_N)
    async with conn.execute(query, args) as cur:
        rows = await cur.fetchall()

    if not rows:
        return {"home":0.33, "draw":0.34, "away":0.33, "matches":0}

    wh = wd = wa = total = 0.0
    for i,r in enumerate(rows):
        hs, as_ = r[2], r[3]
        if hs is None or as_ is None:
            continue
        w = DECAY ** i
        if r[0]==home_id:
            w *= HOME_ADVANTAGE
        total += w
        if hs==as_:
            wd += w
        elif (r[0]==home_id and hs>as_) or (r[1]==home_id and as_>hs):
            wh += w
        else:
            wa += w
    return {"home": wh/total, "draw": wd/total, "away": wa/total, "matches": len(rows)}

async def compute_form(conn, team_id, match_utc, home=None):
    recent = await fetch_recent_matches(conn, team_id, match_utc, 0)
    scored = conceded = points = 0.0
    used = 0
    for r in recent:
        hs, as_ = r[3], r[4]
        if r[1]==team_id:
            s,c = hs, as_
        else:
            s,c = as_, hs
        scored += s; conceded += c
        points += 3 if s>c else 1 if s==c else 0
        used += 1
    if used==0:
        return {"momentum":0, "avg_scored":1.1, "avg_conceded":1.1, "form_strength":0.5}
    return {"momentum":(scored-conceded)/used, "avg_scored":scored/used, "avg_conceded":conceded/used, "form_strength":points/(3*used)}

# ---------------- PREDICT ----------------
async def predict(conn, match_id, home_id=None, away_id=None):
    try:
        match_utc, home_id, away_id = await get_match_utc(conn, match_id)
        if not match_utc:
            return None

        # H2H
        h2h = await compute_h2h(conn, home_id, away_id, match_utc, match_id)

        # Home/Away form
        home_form = await compute_form(conn, home_id, match_utc)
        away_form = await compute_form(conn, away_id, match_utc)

        # Combine H2H + Form
        hp, dp, ap = h2h["home"], h2h["draw"], h2h["away"]
        form_diff = home_form["momentum"] - away_form["momentum"]
        hp += ALPHA_FORM * form_diff
        ap -= ALPHA_FORM * form_diff

        # Attack/Defense expected goals
        lambda_home = max(MIN_LAMBDA, home_form["avg_scored"] * (away_form["avg_conceded"]) * HOME_ADVANTAGE)
        lambda_away = max(MIN_LAMBDA, away_form["avg_scored"] * (home_form["avg_conceded"]))

        # Poisson
        p_home, p_draw, p_away, exp_home, exp_away = build_poisson_matrix(lambda_home, lambda_away)

        # Blend with H2H/Form
        w_poisson = 0.25 if h2h["matches"]==0 else min(0.35, 3/(h2h["matches"] or 1))
        hp = (1-w_poisson)*hp + w_poisson*p_home
        dp = (1-w_poisson)*dp + w_poisson*p_draw
        ap = (1-w_poisson)*ap + w_poisson*p_away

        # Add DRAW_BASE
        dp = (1-POISSON_BLEND)*DRAW_BASE + POISSON_BLEND*dp

        # Normalize
        s = hp+dp+ap or 1.0
        hp, dp, ap = hp/s, dp/s, ap/s

        label = "Home Win" if hp>max(dp, ap) else "Away Win" if ap>max(hp, dp) else "Draw"

        return {
            "prediction": label,
            "probabilities": {"home_win": round(hp,3), "draw": round(dp,3), "away_win": round(ap,3)},
            "expected_goals": {"home": round(exp_home,2), "away": round(exp_away,2)},
            "confidence": confidence(hp, dp, ap),
            "matches_used": h2h["matches"],
            "model_version": "V5_TIMEAWARE_STRICT_ATTACK_DEFENSE_SQL_CONN",
            "generated_at": now_iso()
        }
    except Exception:
        logger.exception("Prediction failed for match_id=%s home=%s away=%s", match_id, home_id, away_id)
        traceback.print_exc()
        return None

# ---------------- LEGACY WRAPPER ----------------
async def predict_home_away(conn, match_id, home_id=None, away_id=None, **kwargs):
    return await predict(conn, match_id, home_id, away_id)
