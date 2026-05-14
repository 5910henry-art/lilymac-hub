#!/usr/bin/env python3
"""
V4A_POSTGRES — Fully time-aware H2H + Poisson + ELO/FORM predictor
- Uses asyncpg + DATABASE_URL (Postgres)
- H2H with decay + home advantage
- League-normalized attack/defense Poisson
- Form momentum as lambda modifier
- ELO weighting
- Fast exact Poisson grid instead of Monte Carlo
- Stable entropy-based confidence
- Safe date parsing and small caches
"""

from datetime import datetime, timezone
from math import exp, factorial, log2
import traceback
from typing import Optional, Tuple, List, Dict, Any

import asyncpg
from config2 import DATABASE_URL

UTC = timezone.utc

# ---------------- CONFIG ----------------
H2H_N = 8
FORM_MATCHES = 15
DECAY_DAYS = 365
MAX_GOALS = 6
HOME_ADV = 1.10
MIN_LAMBDA = 0.25
FORM_LAMBDA_WEIGHT = 0.15
H2H_LAMBDA_WEIGHT = 0.20
MIN_CONFIDENCE = 0.55
ELO_K = 20
ELO_LOOKBACK = 50

# ---------------- UTILS ----------------
def parse_date(d: str) -> datetime:
    try:
        return datetime.fromisoformat(d.replace("Z", "+00:00")).astimezone(UTC)
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

def confidence(h: float, d: float, a: float) -> float:
    entropy = -sum(p * log2(p) for p in (h, d, a) if p > 0)
    return round(min(0.95, max(MIN_CONFIDENCE, 1 - entropy / 1.58)), 3)

def fast_poisson_probs(lh: float, la: float):
    """
    Exact score-grid probability calculation up to MAX_GOALS.
    Much faster and more stable than Python Monte Carlo loops.
    """
    ph = pd = pa = 0.0
    exp_home = exp_away = 0.0

    for h in range(MAX_GOALS + 1):
        p_h = poisson_pmf(h, lh)
        for a in range(MAX_GOALS + 1):
            p = p_h * poisson_pmf(a, la)

            exp_home += h * p
            exp_away += a * p

            if h > a:
                ph += p
            elif h < a:
                pa += p
            else:
                pd += p

    total = ph + pd + pa
    if total > 0:
        ph /= total
        pd /= total
        pa /= total

    return ph, pd, pa, exp_home, exp_away

# ---------------- DB ----------------
async def fetch_match(conn: asyncpg.Connection, match_id: int):
    return await conn.fetchrow(
        "SELECT utcDate, home_team_id, away_team_id FROM matches WHERE id=$1 LIMIT 1",
        match_id,
    )

async def fetch_league_avgs(conn: asyncpg.Connection, ref_date: datetime) -> Tuple[float, float]:
    row = await conn.fetchrow(
        "SELECT AVG(home_score) AS h_avg, AVG(away_score) AS a_avg "
        "FROM matches WHERE utcDate < $1 AND status='FINISHED'",
        ref_date,
    )
    if row and row["h_avg"] is not None and row["a_avg"] is not None:
        return float(row["h_avg"]), float(row["a_avg"])
    return 1.4, 1.1

_recent_cache: Dict[Tuple[int, str], List[asyncpg.Record]] = {}
_h2h_cache: Dict[Tuple[int, int, str], Tuple[float, float]] = {}
_elo_cache: Dict[int, float] = {}

async def fetch_recent(conn: asyncpg.Connection, team_id: int, ref_date: datetime) -> List[asyncpg.Record]:
    key = (team_id, ref_date.isoformat())
    if key in _recent_cache:
        return _recent_cache[key]

    rows = await conn.fetch(
        f"""
        SELECT utcDate, home_team_id, away_team_id, home_score, away_score
        FROM matches
        WHERE utcDate < $1
          AND status='FINISHED'
          AND (home_team_id=$2 OR away_team_id=$2)
        ORDER BY utcDate DESC
        LIMIT {FORM_MATCHES}
        """,
        ref_date,
        team_id,
    )

    _recent_cache[key] = rows
    return rows

async def h2h_modifier(conn: asyncpg.Connection, home_id: int, away_id: int, ref_date: datetime) -> Tuple[float, float]:
    key = (home_id, away_id, ref_date.isoformat())
    if key in _h2h_cache:
        return _h2h_cache[key]

    rows = await conn.fetch(
        f"""
        SELECT home_team_id, away_team_id, home_score, away_score, utcDate
        FROM matches
        WHERE utcDate < $1
          AND status='FINISHED'
          AND ((home_team_id=$2 AND away_team_id=$3) OR (home_team_id=$3 AND away_team_id=$2))
        ORDER BY utcDate DESC
        LIMIT {H2H_N}
        """,
        ref_date,
        home_id,
        away_id,
    )

    if not rows:
        _h2h_cache[key] = (1.0, 1.0)
        return 1.0, 1.0

    home_bias = away_bias = 0.0
    for i, r in enumerate(rows):
        try:
            w = 0.9 ** i
            if r["home_score"] is not None and r["away_score"] is not None:
                if r["home_score"] > r["away_score"]:
                    home_bias += w
                elif r["away_score"] > r["home_score"]:
                    away_bias += w
        except Exception:
            continue

    total = home_bias + away_bias or 1.0
    res = (
        1 + H2H_LAMBDA_WEIGHT * (home_bias / total),
        1 + H2H_LAMBDA_WEIGHT * (away_bias / total),
    )
    _h2h_cache[key] = res
    return res

# ---------------- FORM / STRENGTH ----------------
def attack_defense(matches: List[asyncpg.Record], team_id: int, ref_date: datetime) -> Tuple[float, float]:
    scored = conceded = wsum = 0.0

    for m in matches:
        if m["home_score"] is None or m["away_score"] is None:
            continue

        try:
            m_date = m["utcdate"]
            if isinstance(m_date, str):
                m_date = parse_date(m_date)
            w = decay_weight(m_date, ref_date)
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

# ---------------- ELO ----------------
def elo_update(home_elo: float, away_elo: float, home_score: int, away_score: int) -> Tuple[float, float]:
    expected_home = 1 / (1 + 10 ** ((away_elo - home_elo) / 400))
    expected_away = 1 - expected_home

    if home_score > away_score:
        score_home, score_away = 1, 0
    elif home_score < away_score:
        score_home, score_away = 0, 1
    else:
        score_home = score_away = 0.5

    home_elo += ELO_K * (score_home - expected_home)
    away_elo += ELO_K * (score_away - expected_away)
    return home_elo, away_elo

async def compute_elo(conn: asyncpg.Connection, team_id: int) -> float:
    if team_id in _elo_cache:
        return _elo_cache[team_id]

    elo = 1500.0

    rows = await conn.fetch(
        f"""
        SELECT home_team_id, away_team_id, home_score, away_score
        FROM matches
        WHERE status='FINISHED'
          AND (home_team_id=$1 OR away_team_id=$1)
        ORDER BY utcDate DESC
        LIMIT {ELO_LOOKBACK}
        """,
        team_id,
    )

    # reverse to simulate chronological progression
    rows = list(reversed(rows))

    for r in rows:
        h_id, a_id = r["home_team_id"], r["away_team_id"]
        h_s, a_s = r["home_score"], r["away_score"]

        if team_id == h_id:
            elo, _ = elo_update(elo, 1500.0, h_s, a_s)
        else:
            _, elo = elo_update(1500.0, elo, h_s, a_s)

    _elo_cache[team_id] = elo
    return elo

# ---------------- PREDICT ----------------
async def predict(
    conn: asyncpg.Connection,
    match_id: int,
    home_id: Optional[int] = None,
    away_id: Optional[int] = None,
    **kwargs
) -> Optional[Dict[str, Any]]:
    try:
        print(f"🔹 v4a predicting match {match_id}")

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

        lh = max(MIN_LAMBDA, league_h * h_att * a_def * HOME_ADV)
        la = max(MIN_LAMBDA, league_a * a_att * h_def)

        h2h_h, h2h_a = await h2h_modifier(conn, home_id, away_id, ref_date)
        lh *= h2h_h
        la *= h2h_a

        home_elo = await compute_elo(conn, home_id)
        away_elo = await compute_elo(conn, away_id)

        elo_diff = (home_elo - away_elo) / 400
        lh *= (1 + elo_diff)
        la *= (1 - elo_diff)

        ph, pd, pa, exp_home, exp_away = fast_poisson_probs(lh, la)
        conf = confidence(ph, pd, pa)

        label = "Home Win" if ph > max(pd, pa) else "Away Win" if pa > max(ph, pd) else "Draw"
        score_prediction = f"{round(exp_home)}-{round(exp_away)}"

        return {
            "prediction": label,
            "predicted_score": score_prediction,
            "probabilities": {
                "home_win": round(ph, 3),
                "draw": round(pd, 3),
                "away_win": round(pa, 3),
            },
            "expected_goals": {
                "home": round(exp_home, 2),
                "away": round(exp_away, 2),
            },
            "confidence": conf,
            "model_version": "V4A_POSTGRES_TIMEAWARE_POISSON_ELO",
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
    **kwargs
):
    return await predict(conn, match_id, home_id, away_id)

# ---------------- CONNECTION HELPER ----------------
async def main_test():
    conn = await asyncpg.connect(DATABASE_URL)
    result = await predict(conn, match_id=1)
    print(result)
    await conn.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main_test())
