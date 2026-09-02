#!/usr/bin/env python3
"""
V4B_POSTGRES — Time-safe football prediction model

Features
--------
- PostgreSQL + asyncpg
- No future-data leakage
- Time-aware league averages
- Time-decayed team form
- Attack / defense strength normalized against league averages
- Draw-aware H2H
- Proper historical ELO using opponent ratings
- Time-safe ELO cutoff
- Home advantage
- True Poisson goal generation
- Monte Carlo simulation
- Exact Poisson outcome probabilities
- Most-probable scoreline
- Stable entropy-based confidence
- Lightweight TTL caches
- Safe date parsing
- Compatible with existing predict() / predict_home_away() wrappers

Expected matches columns
------------------------
id
utcdate
home_team_id
away_team_id
home_score
away_score
status

The database is PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import exp, factorial, log2
from typing import Optional, Tuple, List, Dict, Any
import asyncio
import random
import time
import traceback

import asyncpg

from config2 import DATABASE_URL


# ============================================================
# TIME
# ============================================================

UTC = timezone.utc


# ============================================================
# MODEL CONFIG
# ============================================================

# Historical H2H matches to consider
H2H_N = 8

# Recent matches used for form
FORM_MATCHES = 15

# Maximum age of form/H2H influence
DECAY_DAYS = 365.0

# Maximum goals represented in exact Poisson matrix
MAX_GOALS = 8

# Home advantage multiplier
HOME_ADV = 1.10

# Never allow expected goals to collapse completely
MIN_LAMBDA = 0.20

# Maximum reasonable lambda
MAX_LAMBDA = 5.00

# Form influence
FORM_LAMBDA_WEIGHT = 0.15

# H2H influence
H2H_LAMBDA_WEIGHT = 0.12

# ELO influence
ELO_LAMBDA_WEIGHT = 0.12

# ELO parameters
ELO_INITIAL = 1500.0
ELO_K = 20.0

# Home advantage used inside ELO
ELO_HOME_ADV = 60.0

# Monte Carlo simulations
MONTE_CARLO_SIMS = 5000

# Confidence floor
MIN_CONFIDENCE = 0.0

# Confidence ceiling
MAX_CONFIDENCE = 0.95

# Cache lifetime
CACHE_TTL_SECONDS = 30.0

# Cache size limits
MAX_CACHE_ITEMS = 5000


# ============================================================
# CACHE STRUCTURES
# ============================================================

_recent_cache: Dict[
    Tuple[int, str],
    Tuple[float, List[asyncpg.Record]]
] = {}

_h2h_cache: Dict[
    Tuple[int, int, str],
    Tuple[float, Tuple[float, float]]
] = {}

_league_cache: Dict[
    str,
    Tuple[float, Tuple[float, float]]
] = {}

_elo_cache: Dict[
    str,
    Tuple[float, Dict[int, float]]
] = {}


# ============================================================
# GENERAL HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_date(value: Any) -> datetime:
    """
    Safely convert PostgreSQL datetime/string into UTC datetime.
    """
    try:
        if isinstance(value, datetime):
            dt = value

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)

            return dt.astimezone(UTC)

        if value is None:
            return utc_now()

        text = str(value).strip()

        if not text:
            return utc_now()

        dt = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)

        return dt.astimezone(UTC)

    except Exception:
        return utc_now()


def cache_valid(timestamp: float) -> bool:
    return (time.monotonic() - timestamp) < CACHE_TTL_SECONDS


def trim_cache(cache: Dict, max_items: int = MAX_CACHE_ITEMS):
    """
    Prevent unlimited memory growth.
    """
    try:
        while len(cache) > max_items:
            first_key = next(iter(cache))
            del cache[first_key]
    except Exception:
        pass


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


# ============================================================
# DECAY
# ============================================================

def decay_weight(
    match_date: datetime,
    ref_date: datetime
) -> float:
    """
    Exponential time decay.

    Recent matches receive more weight.
    Future matches receive zero influence.
    """
    match_date = parse_date(match_date)
    ref_date = parse_date(ref_date)

    seconds = (ref_date - match_date).total_seconds()

    if seconds <= 0:
        return 1.0

    days = seconds / 86400.0

    return exp(-days / DECAY_DAYS)


# ============================================================
# POISSON
# ============================================================

def poisson_pmf(k: int, lam: float) -> float:
    """
    Exact Poisson probability.
    """
    if k < 0:
        return 0.0

    lam = max(0.0, float(lam))

    try:
        return (lam ** k) * exp(-lam) / factorial(k)
    except Exception:
        return 0.0


def poisson_distribution(
    lam: float,
    max_goals: int = MAX_GOALS
) -> List[float]:
    """
    Generate normalized Poisson probabilities.
    """
    lam = clamp(
        safe_float(lam, MIN_LAMBDA),
        0.0,
        MAX_LAMBDA
    )

    probs = [
        poisson_pmf(k, lam)
        for k in range(max_goals + 1)
    ]

    total = sum(probs)

    if total <= 0:
        return [1.0] + [0.0] * max_goals

    return [p / total for p in probs]


def poisson_sample(
    lam: float,
    rng: random.Random
) -> int:
    """
    Knuth Poisson sampler.

    Does not require NumPy.
    """
    lam = clamp(
        safe_float(lam, MIN_LAMBDA),
        0.0,
        MAX_LAMBDA
    )

    if lam <= 0:
        return 0

    # Knuth's algorithm
    limit = exp(-lam)

    k = 0
    probability = 1.0

    while probability > limit:
        k += 1
        probability *= rng.random()

        # Safety against pathological loops
        if k > 30:
            return 30

    return k - 1


# ============================================================
# PROBABILITY / CONFIDENCE
# ============================================================

def normalize_three(
    home: float,
    draw: float,
    away: float
) -> Tuple[float, float, float]:

    values = [
        max(0.0, home),
        max(0.0, draw),
        max(0.0, away),
    ]

    total = sum(values)

    if total <= 0:
        return 1 / 3, 1 / 3, 1 / 3

    return (
        values[0] / total,
        values[1] / total,
        values[2] / total,
    )


def confidence(
    home_prob: float,
    draw_prob: float,
    away_prob: float
) -> float:
    """
    Entropy-based confidence.

    Unlike V4A, this does NOT artificially report 55%
    confidence for an almost perfectly balanced prediction.
    """
    h, d, a = normalize_three(
        home_prob,
        draw_prob,
        away_prob
    )

    entropy = 0.0

    for p in (h, d, a):
        if p > 0:
            entropy -= p * log2(p)

    max_entropy = log2(3)

    if max_entropy <= 0:
        return 0.0

    raw = 1.0 - (entropy / max_entropy)

    return round(
        clamp(
            raw,
            MIN_CONFIDENCE,
            MAX_CONFIDENCE
        ),
        3
    )


# ============================================================
# DATABASE
# ============================================================

async def fetch_match(
    conn: asyncpg.Connection,
    match_id: int
):
    """
    Fetch target match.
    """
    return await conn.fetchrow(
        """
        SELECT
            id,
            utcdate AS match_date,
            home_team_id,
            away_team_id
        FROM matches
        WHERE id = $1
        LIMIT 1
        """,
        match_id
    )


# ============================================================
# LEAGUE AVERAGES
# ============================================================

async def fetch_league_avgs(
    conn: asyncpg.Connection,
    ref_date: datetime
) -> Tuple[float, float]:

    ref_date = parse_date(ref_date)

    cache_key = ref_date.isoformat()

    cached = _league_cache.get(cache_key)

    if cached:
        timestamp, value = cached

        if cache_valid(timestamp):
            return value

    row = await conn.fetchrow(
        """
        SELECT
            AVG(home_score) AS home_avg,
            AVG(away_score) AS away_avg
        FROM matches
        WHERE utcdate < $1
          AND status = 'FINISHED'
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
        """,
        ref_date
    )

    if (
        row
        and row["home_avg"] is not None
        and row["away_avg"] is not None
    ):
        home_avg = safe_float(row["home_avg"], 1.40)
        away_avg = safe_float(row["away_avg"], 1.10)
    else:
        home_avg = 1.40
        away_avg = 1.10

    home_avg = clamp(home_avg, 0.50, 3.50)
    away_avg = clamp(away_avg, 0.50, 3.50)

    result = (
        home_avg,
        away_avg
    )

    _league_cache[cache_key] = (
        time.monotonic(),
        result
    )

    trim_cache(_league_cache)

    return result


# ============================================================
# RECENT FORM
# ============================================================

async def fetch_recent(
    conn: asyncpg.Connection,
    team_id: int,
    ref_date: datetime
) -> List[asyncpg.Record]:

    ref_date = parse_date(ref_date)

    key = (
        int(team_id),
        ref_date.isoformat()
    )

    cached = _recent_cache.get(key)

    if cached:
        timestamp, value = cached

        if cache_valid(timestamp):
            return value

    rows = await conn.fetch(
        f"""
        SELECT
            utcdate AS match_date,
            home_team_id,
            away_team_id,
            home_score,
            away_score
        FROM matches
        WHERE utcdate < $1
          AND status = 'FINISHED'
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
          AND (
              home_team_id = $2
              OR away_team_id = $2
          )
        ORDER BY utcdate DESC
        LIMIT {FORM_MATCHES}
        """,
        ref_date,
        team_id
    )

    _recent_cache[key] = (
        time.monotonic(),
        rows
    )

    trim_cache(_recent_cache)

    return rows


def attack_defense(
    matches: List[asyncpg.Record],
    team_id: int,
    ref_date: datetime
) -> Tuple[float, float]:

    scored = 0.0
    conceded = 0.0
    weighted_points = 0.0

    for match in matches:

        if (
            match["home_score"] is None
            or match["away_score"] is None
        ):
            continue

        match_date = parse_date(
            match["match_date"]
        )

        weight = decay_weight(
            match_date,
            ref_date
        )

        if team_id == match["home_team_id"]:
            scored_goals = safe_float(
                match["home_score"]
            )
            conceded_goals = safe_float(
                match["away_score"]
            )
        else:
            scored_goals = safe_float(
                match["away_score"]
            )
            conceded_goals = safe_float(
                match["home_score"]
            )

        scored += scored_goals * weight
        conceded += conceded_goals * weight
        weighted_points += weight

    if weighted_points <= 0:
        return 1.0, 1.0

    return (
        scored / weighted_points,
        conceded / weighted_points
    )


def form_strength(
    matches: List[asyncpg.Record],
    team_id: int,
    ref_date: datetime
) -> float:
    """
    Calculate a modest form multiplier.

    Positive form > 1
    Negative form < 1
    Neutral form = 1
    """
    weighted_points = 0.0
    weight_total = 0.0

    for match in matches:

        if (
            match["home_score"] is None
            or match["away_score"] is None
        ):
            continue

        match_date = parse_date(
            match["match_date"]
        )

        weight = decay_weight(
            match_date,
            ref_date
        )

        if team_id == match["home_team_id"]:
            gf = safe_float(match["home_score"])
            ga = safe_float(match["away_score"])
        else:
            gf = safe_float(match["away_score"])
            ga = safe_float(match["home_score"])

        if gf > ga:
            points = 3.0
        elif gf == ga:
            points = 1.0
        else:
            points = 0.0

        weighted_points += points * weight
        weight_total += 3.0 * weight

    if weight_total <= 0:
        return 1.0

    form_ratio = weighted_points / weight_total

    # Convert 0..1 into a restrained multiplier.
    multiplier = 1.0 + (
        (form_ratio - 0.5)
        * FORM_LAMBDA_WEIGHT
    )

    return clamp(
        multiplier,
        1.0 - FORM_LAMBDA_WEIGHT,
        1.0 + FORM_LAMBDA_WEIGHT
    )


# ============================================================
# H2H
# ============================================================

async def h2h_modifier(
    conn: asyncpg.Connection,
    home_id: int,
    away_id: int,
    ref_date: datetime
) -> Tuple[float, float]:

    ref_date = parse_date(ref_date)

    key = (
        int(home_id),
        int(away_id),
        ref_date.isoformat()
    )

    cached = _h2h_cache.get(key)

    if cached:
        timestamp, value = cached

        if cache_valid(timestamp):
            return value

    rows = await conn.fetch(
        f"""
        SELECT
            home_team_id,
            away_team_id,
            home_score,
            away_score,
            utcdate AS match_date
        FROM matches
        WHERE utcdate < $1
          AND status = 'FINISHED'
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
          AND (
              (
                  home_team_id = $2
                  AND away_team_id = $3
              )
              OR
              (
                  home_team_id = $3
                  AND away_team_id = $2
              )
          )
        ORDER BY utcdate DESC
        LIMIT {H2H_N}
        """,
        ref_date,
        home_id,
        away_id
    )

    if not rows:
        result = (1.0, 1.0)

        _h2h_cache[key] = (
            time.monotonic(),
            result
        )

        return result

    home_score = 0.0
    draw_score = 0.0
    away_score = 0.0
    total_weight = 0.0

    for match in rows:

        weight = decay_weight(
            parse_date(match["match_date"]),
            ref_date
        )

        actual_home_goals = safe_float(
            match["home_score"]
        )

        actual_away_goals = safe_float(
            match["away_score"]
        )

        # Convert historical fixture into perspective
        # of today's home and away teams.
        if match["home_team_id"] == home_id:
            perspective_home = actual_home_goals
            perspective_away = actual_away_goals
        else:
            perspective_home = actual_away_goals
            perspective_away = actual_home_goals

        if perspective_home > perspective_away:
            home_score += weight
        elif perspective_home < perspective_away:
            away_score += weight
        else:
            draw_score += weight

        total_weight += weight

    if total_weight <= 0:
        result = (1.0, 1.0)
    else:
        home_ratio = home_score / total_weight
        away_ratio = away_score / total_weight

        # Only apply the directional H2H edge.
        # Draws intentionally reduce the strength of the edge.
        home_modifier = (
            1.0
            + H2H_LAMBDA_WEIGHT
            * (home_ratio - away_ratio)
        )

        away_modifier = (
            1.0
            + H2H_LAMBDA_WEIGHT
            * (away_ratio - home_ratio)
        )

        result = (
            clamp(
                home_modifier,
                1.0 - H2H_LAMBDA_WEIGHT,
                1.0 + H2H_LAMBDA_WEIGHT
            ),
            clamp(
                away_modifier,
                1.0 - H2H_LAMBDA_WEIGHT,
                1.0 + H2H_LAMBDA_WEIGHT
            )
        )

    _h2h_cache[key] = (
        time.monotonic(),
        result
    )

    trim_cache(_h2h_cache)

    return result


# ============================================================
# ELO
# ============================================================

def elo_expected(
    team_elo: float,
    opponent_elo: float
) -> float:
    """
    Expected score using standard ELO formula.
    """
    return 1.0 / (
        1.0
        + 10.0 ** (
            (opponent_elo - team_elo) / 400.0
        )
    )


def elo_update(
    home_elo: float,
    away_elo: float,
    home_score: int,
    away_score: int
) -> Tuple[float, float]:

    # Home advantage is applied to expected probability,
    # not stored permanently inside the team's rating.
    expected_home = elo_expected(
        home_elo + ELO_HOME_ADV,
        away_elo
    )

    expected_away = 1.0 - expected_home

    if home_score > away_score:
        actual_home = 1.0
        actual_away = 0.0

    elif home_score < away_score:
        actual_home = 0.0
        actual_away = 1.0

    else:
        actual_home = 0.5
        actual_away = 0.5

    # Small goal-margin adjustment.
    goal_difference = abs(
        int(home_score) - int(away_score)
    )

    if goal_difference <= 1:
        margin_multiplier = 1.0
    elif goal_difference == 2:
        margin_multiplier = 1.15
    elif goal_difference == 3:
        margin_multiplier = 1.25
    else:
        margin_multiplier = 1.35

    change = (
        ELO_K
        * margin_multiplier
    )

    new_home = (
        home_elo
        + change * (
            actual_home - expected_home
        )
    )

    new_away = (
        away_elo
        + change * (
            actual_away - expected_away
        )
    )

    return new_home, new_away


async def compute_all_elo(
    conn: asyncpg.Connection,
    ref_date: datetime
) -> Dict[int, float]:
    """
    Compute ELO for every team using ONLY matches before ref_date.

    This fixes the major V4A problem where the opponent was reset
    to 1500 after every match.

    It also prevents future matches from influencing predictions.
    """

    ref_date = parse_date(ref_date)

    cache_key = ref_date.isoformat()

    cached = _elo_cache.get(cache_key)

    if cached:
        timestamp, value = cached

        if cache_valid(timestamp):
            return value

    rows = await conn.fetch(
        """
        SELECT
            home_team_id,
            away_team_id,
            home_score,
            away_score,
            utcdate AS match_date
        FROM matches
        WHERE utcdate < $1
          AND status = 'FINISHED'
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
          AND home_team_id IS NOT NULL
          AND away_team_id IS NOT NULL
        ORDER BY utcdate ASC
        """,
        ref_date
    )

    ratings: Dict[int, float] = {}

    for match in rows:

        home_id = match["home_team_id"]
        away_id = match["away_team_id"]

        if home_id not in ratings:
            ratings[home_id] = ELO_INITIAL

        if away_id not in ratings:
            ratings[away_id] = ELO_INITIAL

        old_home = ratings[home_id]
        old_away = ratings[away_id]

        new_home, new_away = elo_update(
            old_home,
            old_away,
            int(match["home_score"]),
            int(match["away_score"])
        )

        ratings[home_id] = new_home
        ratings[away_id] = new_away

    _elo_cache[cache_key] = (
        time.monotonic(),
        ratings
    )

    trim_cache(_elo_cache)

    return ratings


async def compute_elo(
    conn: asyncpg.Connection,
    team_id: int,
    ref_date: datetime
) -> float:

    ratings = await compute_all_elo(
        conn,
        ref_date
    )

    return ratings.get(
        team_id,
        ELO_INITIAL
    )


# ============================================================
# ELO LAMBDA ADJUSTMENT
# ============================================================

def elo_lambda_modifier(
    home_elo: float,
    away_elo: float
) -> Tuple[float, float]:

    elo_difference = (
        home_elo
        - away_elo
    ) / 400.0

    # Keep the adjustment deliberately small.
    adjustment = (
        elo_difference
        * ELO_LAMBDA_WEIGHT
    )

    home_modifier = 1.0 + adjustment
    away_modifier = 1.0 - adjustment

    return (
        clamp(
            home_modifier,
            0.85,
            1.15
        ),
        clamp(
            away_modifier,
            0.85,
            1.15
        )
    )


# ============================================================
# EXACT POISSON OUTCOME
# ============================================================

def poisson_match_probabilities(
    lambda_home: float,
    lambda_away: float
) -> Tuple[
    float,
    float,
    float,
    float,
    float,
    Tuple[int, int]
]:

    home_probs = poisson_distribution(
        lambda_home,
        MAX_GOALS
    )

    away_probs = poisson_distribution(
        lambda_away,
        MAX_GOALS
    )

    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    best_probability = -1.0
    best_score = (0, 0)

    for home_goals in range(MAX_GOALS + 1):

        for away_goals in range(MAX_GOALS + 1):

            probability = (
                home_probs[home_goals]
                * away_probs[away_goals]
            )

            if home_goals > away_goals:
                home_win += probability

            elif home_goals < away_goals:
                away_win += probability

            else:
                draw += probability

            if probability > best_probability:
                best_probability = probability
                best_score = (
                    home_goals,
                    away_goals
                )

    home_win, draw, away_win = normalize_three(
        home_win,
        draw,
        away_win
    )

    expected_home = (
        sum(
            goals * probability
            for goals, probability
            in enumerate(home_probs)
        )
    )

    expected_away = (
        sum(
            goals * probability
            for goals, probability
            in enumerate(away_probs)
        )
    )

    return (
        home_win,
        draw,
        away_win,
        expected_home,
        expected_away,
        best_score
    )


# ============================================================
# MONTE CARLO
# ============================================================

def monte_carlo_simulation(
    lambda_home: float,
    lambda_away: float,
    match_id: int,
    home_elo: float,
    away_elo: float,
    sims: int = MONTE_CARLO_SIMS
) -> Tuple[
    float,
    float,
    float,
    float,
    float
]:
    """
    True Poisson Monte Carlo.

    A deterministic seed is used so the same match does not
    randomly change prediction every time the scheduler runs.
    """

    lambda_home = clamp(
        lambda_home,
        MIN_LAMBDA,
        MAX_LAMBDA
    )

    lambda_away = clamp(
        lambda_away,
        MIN_LAMBDA,
        MAX_LAMBDA
    )

    elo_home_modifier, elo_away_modifier = (
        elo_lambda_modifier(
            home_elo,
            away_elo
        )
    )

    adjusted_home = clamp(
        lambda_home * elo_home_modifier,
        MIN_LAMBDA,
        MAX_LAMBDA
    )

    adjusted_away = clamp(
        lambda_away * elo_away_modifier,
        MIN_LAMBDA,
        MAX_LAMBDA
    )

    # Stable seed.
    seed = (
        int(match_id) * 1000003
        + int(round(home_elo))
        * 97
        + int(round(away_elo))
        * 193
    )

    rng = random.Random(seed)

    home_wins = 0
    draws = 0
    away_wins = 0

    total_home_goals = 0
    total_away_goals = 0

    sims = max(1000, int(sims))

    for _ in range(sims):

        home_goals = poisson_sample(
            adjusted_home,
            rng
        )

        away_goals = poisson_sample(
            adjusted_away,
            rng
        )

        total_home_goals += home_goals
        total_away_goals += away_goals

        if home_goals > away_goals:
            home_wins += 1

        elif home_goals < away_goals:
            away_wins += 1

        else:
            draws += 1

    return (
        home_wins / sims,
        draws / sims,
        away_wins / sims,
        total_home_goals / sims,
        total_away_goals / sims,
    )


# ============================================================
# PREDICTION
# ============================================================

async def predict(
    conn: asyncpg.Connection,
    match_id: int,
    home_id: Optional[int] = None,
    away_id: Optional[int] = None,
    **kwargs
) -> Optional[Dict[str, Any]]:

    try:

        print(
            f"🔹 V4B predicting match {match_id}"
        )

        # ----------------------------------------------------
        # TARGET MATCH
        # ----------------------------------------------------

        row = await fetch_match(
            conn,
            match_id
        )

        if not row:
            print(
                f"⚠️ V4B match {match_id} not found"
            )
            return None

        ref_date = parse_date(
            row["match_date"]
        )

        home_id = (
            home_id
            if home_id is not None
            else row["home_team_id"]
        )

        away_id = (
            away_id
            if away_id is not None
            else row["away_team_id"]
        )

        if home_id is None or away_id is None:
            print(
                f"⚠️ V4B missing team IDs for {match_id}"
            )
            return None

        # ----------------------------------------------------
        # LEAGUE BASELINE
        # ----------------------------------------------------

        league_home_avg, league_away_avg = (
            await fetch_league_avgs(
                conn,
                ref_date
            )
        )

        # ----------------------------------------------------
        # RECENT FORM
        # ----------------------------------------------------

        home_recent = await fetch_recent(
            conn,
            home_id,
            ref_date
        )

        away_recent = await fetch_recent(
            conn,
            away_id,
            ref_date
        )

        home_scored, home_conceded = (
            attack_defense(
                home_recent,
                home_id,
                ref_date
            )
        )

        away_scored, away_conceded = (
            attack_defense(
                away_recent,
                away_id,
                ref_date
            )
        )

        home_form_modifier = form_strength(
            home_recent,
            home_id,
            ref_date
        )

        away_form_modifier = form_strength(
            away_recent,
            away_id,
            ref_date
        )

        # ----------------------------------------------------
        # ATTACK / DEFENSE NORMALIZATION
        # ----------------------------------------------------

        # Avoid division by zero.
        league_home_avg = max(
            league_home_avg,
            0.50
        )

        league_away_avg = max(
            league_away_avg,
            0.50
        )

        home_attack_strength = (
            home_scored
            / league_home_avg
        )

        home_defense_strength = (
            home_conceded
            / league_away_avg
        )

        away_attack_strength = (
            away_scored
            / league_away_avg
        )

        away_defense_strength = (
            away_conceded
            / league_home_avg
        )

        # ----------------------------------------------------
        # BASE LAMBDAS
        # ----------------------------------------------------

        lambda_home = (
            league_home_avg
            * home_attack_strength
            * away_defense_strength
            * HOME_ADV
        )

        lambda_away = (
            league_away_avg
            * away_attack_strength
            * home_defense_strength
        )

        # ----------------------------------------------------
        # FORM
        # ----------------------------------------------------

        lambda_home *= (
            1.0
            + (
                home_form_modifier - 1.0
            )
        )

        lambda_away *= (
            1.0
            + (
                away_form_modifier - 1.0
            )
        )

        # ----------------------------------------------------
        # H2H
        # ----------------------------------------------------

        h2h_home_modifier, h2h_away_modifier = (
            await h2h_modifier(
                conn,
                home_id,
                away_id,
                ref_date
            )
        )

        lambda_home *= h2h_home_modifier
        lambda_away *= h2h_away_modifier

        # ----------------------------------------------------
        # ELO
        # ----------------------------------------------------

        home_elo = await compute_elo(
            conn,
            home_id,
            ref_date
        )

        away_elo = await compute_elo(
            conn,
            away_id,
            ref_date
        )

        elo_home_modifier, elo_away_modifier = (
            elo_lambda_modifier(
                home_elo,
                away_elo
            )
        )

        # Apply ELO once to the lambda.
        lambda_home *= (
            1.0
            + (
                elo_home_modifier - 1.0
            ) * ELO_LAMBDA_WEIGHT
        )

        lambda_away *= (
            1.0
            + (
                elo_away_modifier - 1.0
            ) * ELO_LAMBDA_WEIGHT
        )

        # ----------------------------------------------------
        # SAFETY CLAMP
        # ----------------------------------------------------

        lambda_home = clamp(
            lambda_home,
            MIN_LAMBDA,
            MAX_LAMBDA
        )

        lambda_away = clamp(
            lambda_away,
            MIN_LAMBDA,
            MAX_LAMBDA
        )

        # ----------------------------------------------------
        # EXACT POISSON
        # ----------------------------------------------------

        (
            poisson_home,
            poisson_draw,
            poisson_away,
            poisson_expected_home,
            poisson_expected_away,
            most_probable_score
        ) = poisson_match_probabilities(
            lambda_home,
            lambda_away
        )

        # ----------------------------------------------------
        # MONTE CARLO
        # ----------------------------------------------------

        (
            mc_home,
            mc_draw,
            mc_away,
            mc_expected_home,
            mc_expected_away
        ) = monte_carlo_simulation(
            lambda_home,
            lambda_away,
            match_id,
            home_elo,
            away_elo
        )

        # ----------------------------------------------------
        # COMBINE EXACT + MONTE CARLO
        # ----------------------------------------------------

        # Exact Poisson is more stable.
        # Monte Carlo gives a secondary simulation estimate.
        home_probability = (
            poisson_home * 0.70
            + mc_home * 0.30
        )

        draw_probability = (
            poisson_draw * 0.70
            + mc_draw * 0.30
        )

        away_probability = (
            poisson_away * 0.70
            + mc_away * 0.30
        )

        (
            home_probability,
            draw_probability,
            away_probability
        ) = normalize_three(
            home_probability,
            draw_probability,
            away_probability
        )

        # ----------------------------------------------------
        # LABEL
        # ----------------------------------------------------

        if (
            home_probability >= draw_probability
            and home_probability >= away_probability
        ):
            prediction_label = "Home Win"

        elif (
            away_probability >= home_probability
            and away_probability >= draw_probability
        ):
            prediction_label = "Away Win"

        else:
            prediction_label = "Draw"

        # ----------------------------------------------------
        # SCORE
        # ----------------------------------------------------

        predicted_home_goals = most_probable_score[0]
        predicted_away_goals = most_probable_score[1]

        predicted_score = (
            f"{predicted_home_goals}"
            f"-"
            f"{predicted_away_goals}"
        )

        # ----------------------------------------------------
        # EXPECTED GOALS
        # ----------------------------------------------------

        expected_home = (
            poisson_expected_home * 0.70
            + mc_expected_home * 0.30
        )

        expected_away = (
            poisson_expected_away * 0.70
            + mc_expected_away * 0.30
        )

        # ----------------------------------------------------
        # CONFIDENCE
        # ----------------------------------------------------

        model_confidence = confidence(
            home_probability,
            draw_probability,
            away_probability
        )

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        result = {
            "prediction": prediction_label,

            "predicted_score": predicted_score,

            "probabilities": {
                "home_win": round(
                    home_probability,
                    3
                ),
                "draw": round(
                    draw_probability,
                    3
                ),
                "away_win": round(
                    away_probability,
                    3
                ),
            },

            "expected_goals": {
                "home": round(
                    expected_home,
                    2
                ),
                "away": round(
                    expected_away,
                    2
                ),
            },

            "confidence": model_confidence,

            "model_version": (
                "V4B_POSTGRES_TIME_SAFE_"
                "POISSON_MC_ELO"
            ),

            "generated_at": utc_now().isoformat(),

            # Useful diagnostics
            "model_data": {
                "match_date": ref_date.isoformat(),

                "home_team_id": home_id,
                "away_team_id": away_id,

                "home_elo": round(
                    home_elo,
                    2
                ),

                "away_elo": round(
                    away_elo,
                    2
                ),

                "league_avg_goals": {
                    "home": round(
                        league_home_avg,
                        3
                    ),
                    "away": round(
                        league_away_avg,
                        3
                    ),
                },

                "lambdas": {
                    "home": round(
                        lambda_home,
                        3
                    ),
                    "away": round(
                        lambda_away,
                        3
                    ),
                },

                "form_modifiers": {
                    "home": round(
                        home_form_modifier,
                        4
                    ),
                    "away": round(
                        away_form_modifier,
                        4
                    ),
                },

                "h2h_modifiers": {
                    "home": round(
                        h2h_home_modifier,
                        4
                    ),
                    "away": round(
                        h2h_away_modifier,
                        4
                    ),
                },

                "monte_carlo": {
                    "simulations": MONTE_CARLO_SIMS,
                    "home_win": round(
                        mc_home,
                        3
                    ),
                    "draw": round(
                        mc_draw,
                        3
                    ),
                    "away_win": round(
                        mc_away,
                        3
                    ),
                },
            },
        }

        print(
            f"✅ V4B {match_id}: "
            f"{prediction_label} "
            f"{predicted_score} "
            f"(confidence={model_confidence})"
        )

        return result

    except Exception as exc:

        print(
            f"❌ V4B prediction failed "
            f"for match {match_id}: {exc}"
        )

        traceback.print_exc()

        return None


# ============================================================
# EXISTING WRAPPER
# ============================================================

async def predict_home_away(
    conn: asyncpg.Connection,
    match_id: int,
    home_id: Optional[int] = None,
    away_id: Optional[int] = None,
    **kwargs
):
    """
    Compatibility wrapper.

    Existing prediction code can continue calling:

        predict_home_away(conn, match_id, home_id, away_id)
    """

    return await predict(
        conn,
        match_id,
        home_id,
        away_id,
        **kwargs
    )


# ============================================================
# CACHE CONTROL
# ============================================================

def clear_caches():
    """
    Clear all in-process model caches.

    Useful after a large batch of new FINISHED matches has
    been inserted into PostgreSQL.
    """

    _recent_cache.clear()
    _h2h_cache.clear()
    _league_cache.clear()
    _elo_cache.clear()

    print("🧹 V4B caches cleared")


# ============================================================
# DATABASE CONNECTION HELPER
# ============================================================

async def create_connection():
    """
    Create a PostgreSQL connection using DATABASE_URL.
    """
    return await asyncpg.connect(
        DATABASE_URL
    )


# ============================================================
# TEST
# ============================================================

async def main_test():

    conn = None

    try:

        print(
            "🔌 Connecting to PostgreSQL..."
        )

        conn = await create_connection()

        print(
            "✅ PostgreSQL connection established"
        )

        # Change this to an existing match ID
        test_match_id = 1

        result = await predict(
            conn,
            match_id=test_match_id
        )

        print()
        print(
            "========== V4B RESULT =========="
        )
        print(result)
        print(
            "================================"
        )

    except Exception:

        traceback.print_exc()

    finally:

        if conn is not None:
            await conn.close()

            print(
                "🔌 PostgreSQL connection closed"
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main_test()
    )
