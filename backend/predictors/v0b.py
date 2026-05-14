#!/usr/bin/env python3
"""
V2_COMBINED_TIMEAWARE_H2H_AD_POISSON_V0B

- Adds form multiplier explicitly
- H2H decays by match age
- Confidence considers lambda gap & sample size
- Dynamic MAX_GOALS based on expected goals
- Fully async, time-aware
"""

from datetime import datetime, timezone
from math import exp, factorial, log2
import traceback
import aiosqlite

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

# ---------------- UTILS ----------------
def parse_date(d):
    return datetime.fromisoformat(d.replace("Z", "+00:00")).astimezone(UTC)


def decay_weight(match_date, ref_date):
    days = (ref_date - match_date).days
    return exp(-days / DECAY_DAYS)


def poisson_pmf(k, lam):
    try:
        return (lam ** k) * exp(-lam) / factorial(k)
    except Exception:
        return 0.0


def confidence(ph, pd, pa, lh=None, la=None, n_home=None, n_away=None):
    """Entropy-based + lambda gap + sample size"""
    entropy = -sum(p * log2(p) for p in (ph, pd, pa) if p > 0)
    conf = 1 - entropy / 1.58

    # lambda gap adjustment
    if lh and la:
        gap = abs(lh - la)
        conf += 0.05 * min(gap / max(lh, la), 1.0)

    # sample size penalty
    if n_home is not None and n_home < 3:
        conf -= 0.05
    if n_away is not None and n_away < 3:
        conf -= 0.05

    return round(max(MIN_CONFIDENCE, min(0.95, conf)), 2)

# ---------------- DB ----------------
async def fetch_match(conn, match_id):
    async with conn.execute(
        "SELECT utcDate, home_team_id, away_team_id FROM matches WHERE id=?",
        (match_id,)
    ) as cur:
        return await cur.fetchone()


async def fetch_league_avgs(conn, ref_date):
    async with conn.execute(
        "SELECT AVG(home_score), AVG(away_score) FROM matches "
        "WHERE utcDate < ? AND status='FINISHED'",
        (ref_date.isoformat(),)
    ) as cur:
        row = await cur.fetchone()
        return row if row and row[0] else (1.4, 1.1)


async def fetch_recent(conn, team_id, ref_date, limit=FORM_MATCHES):
    q = """
    SELECT utcDate, home_team_id, away_team_id, home_score, away_score
    FROM matches
    WHERE utcDate < ?
      AND status='FINISHED'
      AND (home_team_id=? OR away_team_id=?)
    ORDER BY utcDate DESC
    LIMIT ?
    """
    async with conn.execute(q, (ref_date.isoformat(), team_id, team_id, limit)) as cur:
        return await cur.fetchall()


# ---------------- FORM / STRENGTH ----------------
def attack_defense(matches, team_id, ref_date):
    scored = conceded = wsum = 0.0
    for m in matches:
        if m[3] is None or m[4] is None:
            continue
        w = decay_weight(parse_date(m[0]), ref_date)
        if team_id == m[1]:
            s, c = m[3], m[4]
        else:
            s, c = m[4], m[3]
        scored += s * w
        conceded += c * w
        wsum += w
    if wsum == 0:
        return 1.0, 1.0
    return scored / wsum, conceded / wsum


def form_multiplier(matches, team_id, ref_date):
    """Return lambda multiplier based on recent form (points)"""
    points = 0.0
    for m in matches:
        if m[3] is None or m[4] is None:
            continue
        w = decay_weight(parse_date(m[0]), ref_date)
        if team_id == m[1]:
            pts = 3 if m[3] > m[4] else 1 if m[3] == m[4] else 0
        else:
            pts = 3 if m[4] > m[3] else 1 if m[4] == m[3] else 0
        points += pts * w
    max_points = 3 * len(matches) if matches else 1
    return 1 + FORM_LAMBDA_WEIGHT * (points / max_points)


# ---------------- H2H ----------------
async def h2h_modifier(conn, home_id, away_id, ref_date):
    q = """
    SELECT home_team_id, away_team_id, home_score, away_score, utcDate
    FROM matches
    WHERE utcDate < ?
      AND status='FINISHED'
      AND ((home_team_id=? AND away_team_id=?) OR (home_team_id=? AND away_team_id=?))
    ORDER BY utcDate DESC
    LIMIT ?
    """
    async with conn.execute(q, (ref_date.isoformat(), home_id, away_id, away_id, home_id, H2H_N)) as cur:
        rows = await cur.fetchall()

    if not rows:
        return 1.0, 1.0

    home_bias = away_bias = 0.0
    for r in rows:
        w = decay_weight(parse_date(r[4]), ref_date)
        if r[2] > r[3]:
            home_bias += w
        elif r[3] > r[2]:
            away_bias += w

    total = home_bias + away_bias or 1.0
    return (
        1 + H2H_LAMBDA_WEIGHT * (home_bias / total),
        1 + H2H_LAMBDA_WEIGHT * (away_bias / total)
    )


# ---------------- POISSON ----------------
def poisson_matrix(lh, la):
    max_goals = max(MAX_GOALS_BASE, int(max(lh, la) + 1))
    probs = {}
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
async def predict(conn, match_id, home_id=None, away_id=None, **kwargs):
    try:
        row = await fetch_match(conn, match_id)
        if not row:
            return None

        ref_date = parse_date(row[0])
        home_id = home_id or row[1]
        away_id = away_id or row[2]

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
                "away_win": round(pa, 3)
            },
            "expected_goals": {
                "home": round(lh, 2),
                "away": round(la, 2)
            },
            "confidence": conf,
            "model_version": "V2_COMBINED_TIMEAWARE_V0B",
            "generated_at": datetime.now(UTC).isoformat()
        }

    except Exception:
        traceback.print_exc()
        return None


# ---------------- WRAPPER ----------------
async def predict_home_away(conn, match_id, home_id=None, away_id=None, **kwargs):
    return await predict(conn, match_id, home_id, away_id, **kwargs)
