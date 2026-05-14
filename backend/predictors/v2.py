#!/usr/bin/env python3
"""
V5_TIMEAWARE_STRICT_ATTACK_DEFENSE_POSTGRES
- Strict H2H + home/away form
- Attack/defense Poisson model
- Postgres-compatible (asyncpg)
- Async, shared PostgreSQL connection
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from math import exp, factorial, log2
from typing import Optional, Any, Dict, Tuple, List

import asyncpg

from config2 import DATABASE_URL

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
logger = logging.getLogger("v5_postgres_strict")
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [v5_postgres_strict] %(message)s"))
    logger.addHandler(ch)
logger.setLevel(logging.INFO)

# ---------------- SMALL CACHES ----------------
_recent_cache: Dict[Tuple[int, str], List[asyncpg.Record]] = {}
_h2h_cache: Dict[Tuple[int, int, str, int], List[asyncpg.Record]] = {}

# ---------------- UTILS ----------------
def now_iso() -> str:
    return datetime.now(UTC).isoformat()

def parse_date(d: Any) -> datetime:
    try:
        if isinstance(d, datetime):
            return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)
        return datetime.fromisoformat(str(d).replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return datetime.now(UTC)

def decay_weight(match_date: datetime, ref_date: datetime) -> float:
    days = max(0, (ref_date - match_date).days)
    return exp(-days / 450)  # slower decay

def confidence(h: float, d: float, a: float) -> float:
    entropy = -sum(p * log2(p) for p in (h, d, a) if p > 0)
    return round(min(0.95, max(MIN_CONFIDENCE, 1 - entropy / 1.58)), 2)

def poisson_pmf(k: int, lam: float) -> float:
    try:
        return (lam ** k) * exp(-lam) / factorial(k)
    except Exception:
        return 0.0

def build_poisson_matrix(lambda_home: float, lambda_away: float):
    probs = {}
    for h in range(POISSON_MAX_GOALS + 1):
        for a in range(POISSON_MAX_GOALS + 1):
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

# ---------------- DB QUERIES ----------------
async def get_match_utc(conn: asyncpg.Connection, match_id: int):
    row = await conn.fetchrow(
        """
        SELECT utcdate, home_team_id, away_team_id
        FROM matches
        WHERE id = $1
        LIMIT 1
        """,
        match_id,
    )
    if row:
        return parse_date(row["utcdate"]), row["home_team_id"], row["away_team_id"]
    return None, None, None

async def fetch_recent_matches(
    conn: asyncpg.Connection,
    team_id: int,
    match_date: datetime,
    match_id: int,
):
    key = (team_id, match_date.isoformat())
    if key in _recent_cache:
        return _recent_cache[key]

    rows = await conn.fetch(
        """
        SELECT utcdate, home_team_id, away_team_id, home_score, away_score
        FROM matches
        WHERE utcdate < $1
          AND id != $2
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
          AND (home_team_id = $3 OR away_team_id = $3)
        ORDER BY utcdate DESC
        LIMIT $4
        """,
        match_date,
        match_id,
        team_id,
        FORM_N,
    )

    _recent_cache[key] = rows
    return rows

# ---------------- H2H & FORM ----------------
async def compute_h2h(
    conn: asyncpg.Connection,
    home_id: int,
    away_id: int,
    match_utc: datetime,
    match_id: int,
):
    key = (home_id, away_id, match_utc.isoformat(), match_id)
    if key in _h2h_cache:
        rows = _h2h_cache[key]
    else:
        rows = await conn.fetch(
            """
            SELECT home_team_id, away_team_id, home_score, away_score, utcdate
            FROM matches
            WHERE ((home_team_id = $1 AND away_team_id = $2)
                OR (home_team_id = $2 AND away_team_id = $1))
              AND utcdate < $3
              AND id != $4
              AND status = 'FINISHED'
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
            ORDER BY utcdate DESC
            LIMIT $5
            """,
            home_id,
            away_id,
            match_utc,
            match_id,
            H2H_N,
        )
        _h2h_cache[key] = rows

    if not rows:
        return {"home": 0.33, "draw": 0.34, "away": 0.33, "matches": 0}

    wh = wd = wa = total = 0.0
    for i, r in enumerate(rows):
        hs, as_ = r["home_score"], r["away_score"]
        if hs is None or as_ is None:
            continue

        w = DECAY ** i
        if r["home_team_id"] == home_id:
            w *= HOME_ADVANTAGE

        total += w
        if hs == as_:
            wd += w
        elif (r["home_team_id"] == home_id and hs > as_) or (r["away_team_id"] == home_id and as_ > hs):
            wh += w
        else:
            wa += w

    total = total or 1.0
    return {"home": wh / total, "draw": wd / total, "away": wa / total, "matches": len(rows)}

async def compute_form(conn: asyncpg.Connection, team_id: int, match_utc: datetime, match_id: int):
    recent = await fetch_recent_matches(conn, team_id, match_utc, match_id)

    scored = conceded = points = 0.0
    used = 0

    for r in recent:
        hs, as_ = r["home_score"], r["away_score"]
        if hs is None or as_ is None:
            continue

        if r["home_team_id"] == team_id:
            s, c = hs, as_
        else:
            s, c = as_, hs

        scored += s
        conceded += c
        points += 3 if s > c else 1 if s == c else 0
        used += 1

    if used == 0:
        return {
            "momentum": 0.0,
            "avg_scored": 1.1,
            "avg_conceded": 1.1,
            "form_strength": 0.5,
        }

    return {
        "momentum": (scored - conceded) / used,
        "avg_scored": scored / used,
        "avg_conceded": conceded / used,
        "form_strength": points / (3 * used),
    }

# ---------------- PREDICT ----------------
async def predict(
    conn: asyncpg.Connection,
    match_id: int,
    home_id: Optional[int] = None,
    away_id: Optional[int] = None,
):
    try:
        match_utc, db_home_id, db_away_id = await get_match_utc(conn, match_id)
        if not match_utc:
            return None

        home_id = home_id or db_home_id
        away_id = away_id or db_away_id
        if not home_id or not away_id:
            return None

        # H2H
        h2h = await compute_h2h(conn, home_id, away_id, match_utc, match_id)

        # Home/Away form
        home_form = await compute_form(conn, home_id, match_utc, match_id)
        away_form = await compute_form(conn, away_id, match_utc, match_id)

        # Combine H2H + Form
        hp, dp, ap = h2h["home"], h2h["draw"], h2h["away"]
        form_diff = home_form["momentum"] - away_form["momentum"]
        hp += ALPHA_FORM * form_diff
        ap -= ALPHA_FORM * form_diff

        # Attack/Defense expected goals
        lambda_home = max(MIN_LAMBDA, home_form["avg_scored"] * away_form["avg_conceded"] * HOME_ADVANTAGE)
        lambda_away = max(MIN_LAMBDA, away_form["avg_scored"] * home_form["avg_conceded"])

        # Poisson
        p_home, p_draw, p_away, exp_home, exp_away = build_poisson_matrix(lambda_home, lambda_away)

        # Blend with H2H/Form
        w_poisson = 0.25 if h2h["matches"] == 0 else min(0.35, 3 / (h2h["matches"] or 1))
        hp = (1 - w_poisson) * hp + w_poisson * p_home
        dp = (1 - w_poisson) * dp + w_poisson * p_draw
        ap = (1 - w_poisson) * ap + w_poisson * p_away

        # Add draw base
        dp = (1 - POISSON_BLEND) * DRAW_BASE + POISSON_BLEND * dp

        # Normalize
        s = hp + dp + ap or 1.0
        hp, dp, ap = hp / s, dp / s, ap / s

        label = "Home Win" if hp > max(dp, ap) else "Away Win" if ap > max(hp, dp) else "Draw"

        return {
            "prediction": label,
            "probabilities": {
                "home_win": round(hp, 3),
                "draw": round(dp, 3),
                "away_win": round(ap, 3),
            },
            "expected_goals": {
                "home": round(exp_home, 2),
                "away": round(exp_away, 2),
            },
            "confidence": confidence(hp, dp, ap),
            "matches_used": h2h["matches"],
            "model_version": "V5_TIMEAWARE_STRICT_ATTACK_DEFENSE_POSTGRES",
            "generated_at": now_iso(),
        }

    except Exception:
        logger.exception("Prediction failed for match_id=%s home=%s away=%s", match_id, home_id, away_id)
        traceback.print_exc()
        return None

# ---------------- LEGACY WRAPPER ----------------
async def predict_home_away(conn, match_id, home_id=None, away_id=None, **kwargs):
    return await predict(conn, match_id, home_id, away_id)

# ---------------- TEST ----------------
async def main_test():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in config2.py")

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        result = await predict(conn, match_id=1)
        print(result)
    finally:
        await conn.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main_test())
