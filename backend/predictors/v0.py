#!/usr/bin/env python3
"""
V2_COMBINED_TIMEAWARE_H2H_AD_POISSON_V0B_POSTGRES

- PostgreSQL/asyncpg version of v0b
- Keeps v0b logic:
  - form multiplier explicitly
  - H2H decays by match age
  - confidence considers lambda gap & sample size
  - dynamic MAX_GOALS based on expected goals
  - fully async, time-aware
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import exp, factorial, log2
from typing import Any, Dict, Optional, Tuple, List
import traceback

import asyncpg

from config2 import DATABASE_URL

UTC = timezone.utc

# ---------------- CONFIG ----------------
H2H_N = 8
FORM_MATCHES = 15
DECAY_DAYS = 365
MAX_GOALS_BASE = 6
HOME_ADV = 1.10
MIN_LAMBDA = 0.25
FORM_LAMBDA_WEIGHT = 0.15
H2H_LAMBDA_WEIGHT = 0.20
MIN_CONFIDENCE = 0.55

# ---------------- SMALL CACHES ----------------
_recent_cache: Dict[Tuple[int, str], List[asyncpg.Record]] = {}
_h2h_cache: Dict[Tuple[int, int, str], Tuple[float, float]] = {}


# ---------------- UTILS ----------------
def parse_date(d: Any) -> datetime:
    """
    Accepts datetime or ISO string and returns UTC datetime.
    Falls back to now if parsing fails.
    """
    try:
        if isinstance(d, datetime):
            return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)
        return datetime.fromisoformat(str(d).replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return datetime.now(UTC)


def decay_weight(match_date: datetime, ref_date: datetime) -> float:
    days = max(0, (ref_date - match_date).days)
    return exp(-days / DECAY_DAYS)


def poisson_pmf(k: int, lam: float) -> float:
    try:
        return (lam ** k) * exp(-lam) / factorial(k)
    except Exception:
        return 0.0


def confidence(
    ph: float,
    pd: float,
    pa: float,
    lh: Optional[float] = None,
    la: Optional[float] = None,
    n_home: Optional[int] = None,
    n_away: Optional[int] = None,
) -> float:
    """
    Entropy-based confidence + lambda gap + sample size penalty.
    """
    entropy = -sum(p * log2(p) for p in (ph, pd, pa) if p > 0)
    conf = 1 - entropy / 1.58

    if lh is not None and la is not None:
        gap = abs(lh - la)
        denom = max(lh, la, 1e-9)
        conf += 0.05 * min(gap / denom, 1.0)

    if n_home is not None and n_home < 3:
        conf -= 0.05
    if n_away is not None and n_away < 3:
        conf -= 0.05

    return round(max(MIN_CONFIDENCE, min(0.95, conf)), 2)


# ---------------- DB ----------------
async def fetch_match(conn: asyncpg.Connection, match_id: int):
    return await conn.fetchrow(
        """
        SELECT utcdate, home_team_id, away_team_id
        FROM matches
        WHERE id = $1
        LIMIT 1
        """,
        match_id,
    )


async def fetch_league_avgs(conn: asyncpg.Connection, ref_date: datetime) -> Tuple[float, float]:
    row = await conn.fetchrow(
        """
        SELECT AVG(home_score) AS h_avg,
               AVG(away_score) AS a_avg
        FROM matches
        WHERE utcdate < $1
          AND status = 'FINISHED'
        """,
        ref_date,
    )

    if row and row["h_avg"] is not None and row["a_avg"] is not None:
        return float(row["h_avg"]), float(row["a_avg"])
    return 1.4, 1.1


async def fetch_recent(
    conn: asyncpg.Connection,
    team_id: int,
    ref_date: datetime,
    limit: int = FORM_MATCHES,
):
    key = (team_id, ref_date.isoformat())
    if key in _recent_cache:
        return _recent_cache[key]

    rows = await conn.fetch(
        """
        SELECT utcdate, home_team_id, away_team_id, home_score, away_score
        FROM matches
        WHERE utcdate < $1
          AND status = 'FINISHED'
          AND (home_team_id = $2 OR away_team_id = $2)
        ORDER BY utcdate DESC
        LIMIT $3
        """,
        ref_date,
        team_id,
        limit,
    )

    _recent_cache[key] = rows
    return rows


# ---------------- FORM / STRENGTH ----------------
def attack_defense(matches, team_id: int, ref_date: datetime) -> Tuple[float, float]:
    scored = conceded = wsum = 0.0

    for m in matches:
        if m["home_score"] is None or m["away_score"] is None:
            continue

        try:
            w = decay_weight(parse_date(m["utcdate"]), ref_date)
        except Exception:
            w = 1.0

        if team_id == m["home_team_id"]:
            s, c = m["home_score"], m["away_score"]
        else:
            s, c = m["away_score"], m["home_score"]

        scored += s * w
        conceded += c * w
        wsum += w

    if wsum == 0:
        return 1.0, 1.0

    return scored / wsum, conceded / wsum


def form_multiplier(matches, team_id: int, ref_date: datetime) -> float:
    """
    Return lambda multiplier based on recent form (points).
    """
    if not matches:
        return 1.0

    points = 0.0
    for m in matches:
        if m["home_score"] is None or m["away_score"] is None:
            continue

        w = decay_weight(parse_date(m["utcdate"]), ref_date)

        if team_id == m["home_team_id"]:
            pts = 3 if m["home_score"] > m["away_score"] else 1 if m["home_score"] == m["away_score"] else 0
        else:
            pts = 3 if m["away_score"] > m["home_score"] else 1 if m["away_score"] == m["home_score"] else 0

        points += pts * w

    max_points = 3 * len(matches) if matches else 1
    return 1 + FORM_LAMBDA_WEIGHT * (points / max_points)


# ---------------- H2H ----------------
async def h2h_modifier(
    conn: asyncpg.Connection,
    home_id: int,
    away_id: int,
    ref_date: datetime,
) -> Tuple[float, float]:
    key = (home_id, away_id, ref_date.isoformat())
    if key in _h2h_cache:
        return _h2h_cache[key]

    rows = await conn.fetch(
        """
        SELECT home_team_id, away_team_id, home_score, away_score, utcdate
        FROM matches
        WHERE utcdate < $1
          AND status = 'FINISHED'
          AND (
                (home_team_id = $2 AND away_team_id = $3)
             OR (home_team_id = $3 AND away_team_id = $2)
          )
        ORDER BY utcdate DESC
        LIMIT $4
        """,
        ref_date,
        home_id,
        away_id,
        H2H_N,
    )

    if not rows:
        _h2h_cache[key] = (1.0, 1.0)
        return 1.0, 1.0

    home_bias = 0.0
    away_bias = 0.0

    for r in rows:
        if r["home_score"] is None or r["away_score"] is None:
            continue

        w = decay_weight(parse_date(r["utcdate"]), ref_date)

        if r["home_score"] > r["away_score"]:
            home_bias += w
        elif r["away_score"] > r["home_score"]:
            away_bias += w

    total = home_bias + away_bias or 1.0
    res = (
        1 + H2H_LAMBDA_WEIGHT * (home_bias / total),
        1 + H2H_LAMBDA_WEIGHT * (away_bias / total),
    )
    _h2h_cache[key] = res
    return res


# ---------------- POISSON ----------------
def poisson_matrix(lh: float, la: float) -> Tuple[float, float, float]:
    max_goals = max(MAX_GOALS_BASE, int(max(lh, la) + 1))
    probs: Dict[Tuple[int, int], float] = {}

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            probs[(h, a)] = poisson_pmf(h, lh) * poisson_pmf(a, la)

    s = sum(probs.values()) or 1.0
    for k in probs:
        probs[k] /= s

    ph = sum(p for (h, a), p in probs.items() if h > a)
    pd = sum(p for (h, a), p in probs.items() if h == a)
    pa = sum(p for (h, a), p in probs.items() if h < a)

    return ph, pd, pa


# ---------------- PREDICT ----------------
async def predict(
    conn: asyncpg.Connection,
    match_id: int,
    home_id: Optional[int] = None,
    away_id: Optional[int] = None,
    **kwargs,
) -> Optional[Dict[str, Any]]:
    try:
        row = await fetch_match(conn, match_id)
        if not row:
            return None

        ref_date = parse_date(row["utcdate"])
        home_id = home_id or row["home_team_id"]
        away_id = away_id or row["away_team_id"]

        if not home_id or not away_id:
            return None

        league_h, league_a = await fetch_league_avgs(conn, ref_date)

        home_recent = await fetch_recent(conn, home_id, ref_date)
        away_recent = await fetch_recent(conn, away_id, ref_date)

        h_att, h_def = attack_defense(home_recent, home_id, ref_date)
        a_att, a_def = attack_defense(away_recent, away_id, ref_date)

        # Base expected goals
        lh = max(MIN_LAMBDA, league_h * h_att * a_def * HOME_ADV)
        la = max(MIN_LAMBDA, league_a * a_att * h_def)

        # H2H modifier
        h2h_h, h2h_a = await h2h_modifier(conn, home_id, away_id, ref_date)
        lh *= h2h_h
        la *= h2h_a

        # Form multiplier
        lh *= form_multiplier(home_recent, home_id, ref_date)
        la *= form_multiplier(away_recent, away_id, ref_date)

        ph, pd, pa = poisson_matrix(lh, la)
        conf = confidence(ph, pd, pa, lh, la, len(home_recent), len(away_recent))

        if ph > max(pd, pa):
            label = "Home Win"
        elif pa > max(ph, pd):
            label = "Away Win"
        else:
            label = "Draw"

        return {
            "prediction": label,
            "probabilities": {
                "home_win": round(ph, 3),
                "draw": round(pd, 3),
                "away_win": round(pa, 3),
            },
            "expected_goals": {
                "home": round(lh, 2),
                "away": round(la, 2),
            },
            "confidence": conf,
            "model_version": "V2_COMBINED_TIMEAWARE_H2H_AD_POISSON_V0B_POSTGRES",
            "generated_at": datetime.now(UTC).isoformat(),
        }

    except Exception:
        traceback.print_exc()
        return None


# ---------------- WRAPPER ----------------
async def predict_home_away(
    conn: asyncpg.Connection,
    match_id: int,
    home_id: Optional[int] = None,
    away_id: Optional[int] = None,
    **kwargs,
):
    return await predict(conn, match_id, home_id, away_id, **kwargs)


# ---------------- CONNECTION HELPER ----------------
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
