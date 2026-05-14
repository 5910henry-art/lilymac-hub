#!/usr/bin/env python3
"""
v1b_postgres_timeaware_h2h_poisson.py

PostgreSQL version of v1b.
- Uses asyncpg + DATABASE_URL
- Keeps the same time-aware form + H2H + Poisson logic
- Supports injected DB connection from run.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import exp, factorial, log2
from typing import Optional, Dict, Any, Tuple, List
import traceback

import asyncpg
from config2 import DATABASE_URL

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

# ---------------- SMALL CACHES ----------------
_recent_cache: Dict[Tuple[int, str], List[asyncpg.Record]] = {}
_h2h_cache: Dict[Tuple[int, int, str, int], List[asyncpg.Record]] = {}


# ---------------- UTILS ----------------
def parse_date(d: Any) -> datetime:
    try:
        if isinstance(d, datetime):
            return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)
        return datetime.fromisoformat(str(d).replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return datetime.now(UTC)


def decay_weight(match_date: datetime, ref_date: datetime) -> float:
    days = max(0, (ref_date - match_date).days)
    return exp(-days / DECAY_DAYS)


def confidence(h: float, d: float, a: float) -> float:
    entropy = -sum(p * log2(p) for p in (h, d, a) if p > 0)
    return round(min(0.95, max(MIN_CONFIDENCE, 1 - entropy / 1.58)), 2)


def poisson_pmf(k: int, lam: float) -> float:
    try:
        return (lam ** k) * exp(-lam) / factorial(k)
    except Exception:
        return 0.0


# ---------------- DB QUERIES ----------------
async def fetch_match_info(conn: asyncpg.Connection, match_id: int):
    return await conn.fetchrow(
        """
        SELECT utcdate, home_team_id, away_team_id
        FROM matches
        WHERE id = $1
        LIMIT 1
        """,
        match_id,
    )


async def fetch_h2h(
    conn: asyncpg.Connection,
    home_id: int,
    away_id: int,
    match_date: datetime,
    match_id: int,
):
    key = (home_id, away_id, match_date.isoformat(), match_id)
    if key in _h2h_cache:
        return _h2h_cache[key]

    rows = await conn.fetch(
        """
        SELECT utcdate, home_team_id, away_team_id, home_score, away_score
        FROM matches
        WHERE utcdate < $1
          AND id != $2
          AND (
                (home_team_id = $3 AND away_team_id = $4)
             OR (home_team_id = $4 AND away_team_id = $3)
          )
          AND status = 'FINISHED'
        ORDER BY utcdate DESC
        LIMIT $5
        """,
        match_date,
        match_id,
        home_id,
        away_id,
        H2H_N,
    )

    _h2h_cache[key] = rows
    return rows


async def fetch_team_form(
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
          AND (home_team_id = $3 OR away_team_id = $3)
          AND status = 'FINISHED'
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


async def fetch_league_averages(conn: asyncpg.Connection, match_date: datetime):
    row = await conn.fetchrow(
        """
        SELECT AVG(home_score) AS home_avg,
               AVG(away_score) AS away_avg
        FROM matches
        WHERE utcdate < $1
          AND status = 'FINISHED'
        """,
        match_date,
    )
    if row and row["home_avg"] is not None and row["away_avg"] is not None:
        return float(row["home_avg"]), float(row["away_avg"])
    return 1.4, 1.1


# ---------------- CALCULATIONS ----------------
def calc_form(matches, team_id: int, ref_date: datetime):
    pts, wsum, used = 0.0, 0.0, 0

    for m in matches:
        if m["home_score"] is None or m["away_score"] is None:
            continue

        used += 1
        mdate = parse_date(m["utcdate"])
        w = decay_weight(mdate, ref_date)
        home, away = m["home_team_id"], m["away_team_id"]
        hg, ag = m["home_score"], m["away_score"]

        gd = (hg - ag) if team_id == home else (ag - hg)
        p = 1.0 if gd > 0 else 0.5 if gd == 0 else 0.0

        pts += p * w
        wsum += w

    return (pts / wsum if wsum else 0.5), used


def calculate_attack_defense(
    matches,
    team_id: int,
    league_home_avg: float,
    league_away_avg: float,
    ref_date: datetime,
):
    scored = conceded = wsum = 0.0
    used = 0

    for m in matches:
        if m["home_score"] is None or m["away_score"] is None:
            continue

        used += 1
        mdate = parse_date(m["utcdate"])
        w = decay_weight(mdate, ref_date)
        home, away = m["home_team_id"], m["away_team_id"]
        hg, ag = m["home_score"], m["away_score"]

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


def build_poisson_probs(lh: float, la: float):
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
        "expected_goals": {"home": exp_home, "away": exp_away},
    }


# ---------------- CORE ----------------
async def _predict_core(
    conn: asyncpg.Connection,
    match_id: int,
    home_id: Optional[int] = None,
    away_id: Optional[int] = None,
):
    row = await fetch_match_info(conn, match_id)
    if not row:
        return None

    match_date = parse_date(row["utcdate"])
    home_id = home_id or row["home_team_id"]
    away_id = away_id or row["away_team_id"]

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

    lh = max(0.4, hp * home_attack / max(away_defense, 1e-9) * HOME_ADV_MULTIPLIER)
    la = max(0.4, ap * away_attack / max(home_defense, 1e-9))

    poisson_p = build_poisson_probs(lh, la)

    p_home = (1 - POISSON_BLEND) * hp + POISSON_BLEND * poisson_p["home"]
    p_draw = (1 - POISSON_BLEND) * DRAW_BASE + POISSON_BLEND * poisson_p["draw"]
    p_away = (1 - POISSON_BLEND) * ap + POISSON_BLEND * poisson_p["away"]

    s = p_home + p_draw + p_away
    if s == 0:
        p_home, p_draw, p_away = 0.34, 0.33, 0.33
    else:
        p_home /= s
        p_draw /= s
        p_away /= s

    probs = {"Home Win": p_home, "Draw": p_draw, "Away Win": p_away}
    label = max(probs, key=probs.get)

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
        "model": "v1b_postgres_timeaware",
        "generated_at": datetime.now(UTC).isoformat(),
    }


# ---------------- PUBLIC ENTRY ----------------
async def predict(
    match_id: int,
    home_id: Optional[int] = None,
    away_id: Optional[int] = None,
    conn: Optional[asyncpg.Connection] = None,
):
    try:
        if conn is not None:
            return await _predict_core(conn, match_id, home_id, away_id)

        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set in config2.py")

        db = await asyncpg.connect(DATABASE_URL)
        try:
            return await _predict_core(db, match_id, home_id, away_id)
        finally:
            await db.close()

    except Exception:
        traceback.print_exc()
        return None


async def predict_home_away(
    match_id: int,
    home_id: Optional[int] = None,
    away_id: Optional[int] = None,
    **kwargs,
):
    return await predict(match_id, home_id, away_id, conn=kwargs.get("conn"))


# ---------------- TEST ----------------
async def main_test():
    result = await predict(match_id=1)
    print(result)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main_test())
