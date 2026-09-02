#!/usr/bin/env python3
"""
V4B_GOALS — V4B Companion Goals / Alternative Score Predictor

Purpose
-------
This predictor follows the same core methodology as V4B:

    - PostgreSQL / asyncpg
    - Time-aware historical data
    - Recent-form analysis
    - Decay-weighted form
    - League-normalized attack / defense
    - H2H modifier
    - ELO strength
    - Poisson goal model
    - Monte Carlo simulation
    - Entropy-based confidence

Unlike the normal V4B predictor, this file specializes in:

    - Primary score
    - Alternative score
    - BTTS probability
    - Over 1.5
    - Over 2.5
    - Over 3.5
    - Over 4.5
    - Scoreline probabilities

IMPORTANT
---------
BTTS and Over probabilities come directly from the same Monte Carlo
score distribution.

Example:

    Primary score:       1-1
    Alternative score:   2-1

    BTTS:                64%
    Over 1.5:            78%
    Over 2.5:            53%
    Over 3.5:            29%
    Over 4.5:            14%

The displayed alternative score is NOT used to calculate BTTS/Over.
Those markets are calculated from all simulations.

"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import exp, factorial, log2
from typing import Optional, Tuple, List, Dict, Any
import traceback
import random

import asyncpg

from config2 import DATABASE_URL


# ============================================================
# TIME
# ============================================================

UTC = timezone.utc


# ============================================================
# CONFIG
# ============================================================

# V4B-style historical windows
H2H_N = 8
FORM_MATCHES = 15
DECAY_DAYS = 365

# Goal model
MAX_GOALS = 7
MIN_LAMBDA = 0.25
MAX_LAMBDA = 5.00

# Home advantage
HOME_ADV = 1.10

# Model weighting
FORM_LAMBDA_WEIGHT = 0.15
H2H_LAMBDA_WEIGHT = 0.20

# ELO
ELO_K = 20
BASE_ELO = 1500

# Monte Carlo
MC_SIMS = 10000

# Markets
OVER_LINES = [
    1.5,
    2.5,
    3.5,
    4.5,
]

# Alternative score selection
MAX_ALTERNATIVE_GOALS = 6


# ============================================================
# CACHES
# ============================================================

_recent_cache: Dict[
    Tuple[int, str],
    List[asyncpg.Record]
] = {}

_h2h_cache: Dict[
    Tuple[int, int, str],
    Tuple[float, float]
] = {}

_elo_cache: Dict[
    int,
    float
] = {}

_league_avg_cache: Dict[
    str,
    Tuple[float, float]
] = {}


# ============================================================
# DATE
# ============================================================

def parse_date(
    value
) -> datetime:
    """
    Safely convert database / ISO timestamps to UTC.
    """

    try:

        if isinstance(
            value,
            datetime
        ):

            dt = value

        else:

            dt = datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00"
                )
            )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=UTC
            )

        return dt.astimezone(UTC)

    except Exception:

        return datetime.now(UTC)


def decay_weight(
    match_date: datetime,
    ref_date: datetime
) -> float:
    """
    Time decay.

    Recent matches receive greater weight.
    """

    days = max(
        0,
        (
            ref_date
            - match_date
        ).days
    )

    return exp(
        -days / DECAY_DAYS
    )


# ============================================================
# POISSON
# ============================================================

def poisson_pmf(
    k: int,
    lam: float
) -> float:

    try:

        return (
            (lam ** k)
            * exp(-lam)
            / factorial(k)
        )

    except Exception:

        return 0.0


# ============================================================
# CONFIDENCE
# ============================================================

def confidence(
    home_probability: float,
    draw_probability: float,
    away_probability: float
) -> float:
    """
    Entropy-based confidence.

    Low entropy = stronger prediction.

    Maximum practical entropy for 3 outcomes ≈ 1.585.
    """

    values = (
        home_probability,
        draw_probability,
        away_probability
    )

    entropy = -sum(
        p * log2(p)
        for p in values
        if p > 0
    )

    result = (
        1
        - entropy / 1.58
    )

    return round(
        min(
            0.95,
            max(
                0.55,
                result
            )
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

    return await conn.fetchrow(
        """
        SELECT
            utcdate,
            home_team_id,
            away_team_id
        FROM henry_schema.matches
        WHERE id=$1
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
    """
    Calculate historical league scoring averages before
    the target match.

    This follows the V4B/V4A league-normalized concept.
    """

    cache_key = (
        ref_date.strftime(
            "%Y-%m-%d"
        )
    )

    if cache_key in _league_avg_cache:

        return _league_avg_cache[
            cache_key
        ]

    row = await conn.fetchrow(
        """
        SELECT
            AVG(home_score) AS h_avg,
            AVG(away_score) AS a_avg
        FROM henry_schema.matches
        WHERE utcdate < $1
          AND status='FINISHED'
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
        """,
        ref_date
    )

    if (
        row
        and row["h_avg"] is not None
        and row["a_avg"] is not None
    ):

        result = (
            float(row["h_avg"]),
            float(row["a_avg"])
        )

    else:

        result = (
            1.40,
            1.10
        )

    _league_avg_cache[
        cache_key
    ] = result

    return result


# ============================================================
# RECENT FORM
# ============================================================

async def fetch_recent(
    conn: asyncpg.Connection,
    team_id: int,
    ref_date: datetime
) -> List[asyncpg.Record]:
    """
    Fetch the team's most recent completed matches before
    the target fixture.
    """

    key = (
        team_id,
        ref_date.isoformat()
    )

    if key in _recent_cache:

        return _recent_cache[key]

    rows = await conn.fetch(
        f"""
        SELECT
            utcdate,
            home_team_id,
            away_team_id,
            home_score,
            away_score
        FROM henry_schema.matches
        WHERE utcdate < $1
          AND status='FINISHED'
          AND (
              home_team_id=$2
              OR away_team_id=$2
          )
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
        ORDER BY utcdate DESC
        LIMIT {FORM_MATCHES}
        """,
        ref_date,
        team_id
    )

    _recent_cache[key] = rows

    return rows


# ============================================================
# ATTACK / DEFENSE
# ============================================================

def attack_defense(
    matches: List[asyncpg.Record],
    team_id: int,
    ref_date: datetime
) -> Tuple[float, float]:
    """
    Time-decayed attack and defense.

    Returns:

        attack = weighted goals scored
        defense = weighted goals conceded
    """

    scored = 0.0
    conceded = 0.0
    weight_sum = 0.0

    for match in matches:

        if (
            match["home_score"] is None
            or match["away_score"] is None
        ):
            continue

        match_date = parse_date(
            match["utcdate"]
        )

        weight = decay_weight(
            match_date,
            ref_date
        )

        if (
            team_id
            == match["home_team_id"]
        ):

            goals_for = float(
                match["home_score"]
            )

            goals_against = float(
                match["away_score"]
            )

        else:

            goals_for = float(
                match["away_score"]
            )

            goals_against = float(
                match["home_score"]
            )

        scored += (
            goals_for
            * weight
        )

        conceded += (
            goals_against
            * weight
        )

        weight_sum += weight

    if weight_sum <= 0:

        return (
            1.0,
            1.0
        )

    return (
        scored / weight_sum,
        conceded / weight_sum
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
    """
    H2H modifier.

    Recent H2H results receive greater weight.

    The modifier affects expected goals, not final market
    probabilities directly.
    """

    key = (
        home_id,
        away_id,
        ref_date.isoformat()
    )

    if key in _h2h_cache:

        return _h2h_cache[key]

    rows = await conn.fetch(
        f"""
        SELECT
            home_team_id,
            away_team_id,
            home_score,
            away_score,
            utcdate
        FROM henry_schema.matches
        WHERE utcdate < $1
          AND status='FINISHED'
          AND (
              (
                  home_team_id=$2
                  AND away_team_id=$3
              )
              OR
              (
                  home_team_id=$3
                  AND away_team_id=$2
              )
          )
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
        ORDER BY utcdate DESC
        LIMIT {H2H_N}
        """,
        ref_date,
        home_id,
        away_id
    )

    if not rows:

        result = (
            1.0,
            1.0
        )

        _h2h_cache[key] = result

        return result

    home_bias = 0.0
    away_bias = 0.0

    for index, row in enumerate(rows):

        weight = (
            0.9 ** index
        )

        home_score = row[
            "home_score"
        ]

        away_score = row[
            "away_score"
        ]

        if home_score > away_score:

            if row[
                "home_team_id"
            ] == home_id:

                home_bias += weight

            else:

                away_bias += weight

        elif away_score > home_score:

            if row[
                "away_team_id"
            ] == home_id:

                home_bias += weight

            else:

                away_bias += weight

    total = (
        home_bias
        + away_bias
    )

    if total <= 0:

        result = (
            1.0,
            1.0
        )

        _h2h_cache[key] = result

        return result

    home_modifier = (
        1
        + H2H_LAMBDA_WEIGHT
        * (
            home_bias
            / total
        )
    )

    away_modifier = (
        1
        + H2H_LAMBDA_WEIGHT
        * (
            away_bias
            / total
        )
    )

    result = (
        home_modifier,
        away_modifier
    )

    _h2h_cache[key] = result

    return result


# ============================================================
# ELO
# ============================================================

def elo_update(
    home_elo: float,
    away_elo: float,
    home_score: int,
    away_score: int
) -> Tuple[float, float]:

    expected_home = (
        1
        / (
            1
            + 10 ** (
                (
                    away_elo
                    - home_elo
                )
                / 400
            )
        )
    )

    expected_away = (
        1
        - expected_home
    )

    if home_score > away_score:

        actual_home = 1.0
        actual_away = 0.0

    elif home_score < away_score:

        actual_home = 0.0
        actual_away = 1.0

    else:

        actual_home = 0.5
        actual_away = 0.5

    home_elo += (
        ELO_K
        * (
            actual_home
            - expected_home
        )
    )

    away_elo += (
        ELO_K
        * (
            actual_away
            - expected_away
        )
    )

    return (
        home_elo,
        away_elo
    )


async def compute_elo(
    conn: asyncpg.Connection,
    team_id: int
) -> float:
    """
    Calculate team ELO from historical completed matches.

    NOTE:
    This preserves the V4B-style simple team ELO architecture.
    """

    if team_id in _elo_cache:

        return _elo_cache[
            team_id
        ]

    elo = float(
        BASE_ELO
    )

    rows = await conn.fetch(
        """
        SELECT
            home_team_id,
            away_team_id,
            home_score,
            away_score
        FROM henry_schema.matches
        WHERE status='FINISHED'
          AND (
              home_team_id=$1
              OR away_team_id=$1
          )
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
        ORDER BY utcdate ASC
        """,
        team_id
    )

    for row in rows:

        home_id = row[
            "home_team_id"
        ]

        away_id = row[
            "away_team_id"
        ]

        home_score = row[
            "home_score"
        ]

        away_score = row[
            "away_score"
        ]

        if (
            home_score is None
            or away_score is None
        ):
            continue

        if team_id == home_id:

            team_elo = elo
            opponent_elo = BASE_ELO

            team_elo, _ = elo_update(
                team_elo,
                opponent_elo,
                home_score,
                away_score
            )

            elo = team_elo

        else:

            opponent_elo = BASE_ELO
            team_elo = elo

            _, team_elo = elo_update(
                opponent_elo,
                team_elo,
                home_score,
                away_score
            )

            elo = team_elo

    _elo_cache[
        team_id
    ] = elo

    return elo


# ============================================================
# ELO GOAL ADJUSTMENT
# ============================================================

def apply_elo_to_lambdas(
    home_lambda: float,
    away_lambda: float,
    home_elo: float,
    away_elo: float
) -> Tuple[float, float]:
    """
    Convert ELO difference into a moderate goal-rate modifier.

    The adjustment is deliberately restrained so ELO does not
    completely dominate form/H2H/league averages.
    """

    elo_difference = (
        home_elo
        - away_elo
    )

    elo_factor = (
        elo_difference
        / 400.0
    )

    # Restrict ELO impact.
    elo_factor = max(
        -0.30,
        min(
            0.30,
            elo_factor
        )
    )

    home_lambda = (
        home_lambda
        * (
            1
            + elo_factor
            * 0.35
        )
    )

    away_lambda = (
        away_lambda
        * (
            1
            - elo_factor
            * 0.35
        )
    )

    return (
        max(
            MIN_LAMBDA,
            home_lambda
        ),
        max(
            MIN_LAMBDA,
            away_lambda
        )
    )


# ============================================================
# POISSON SCORE MATRIX
# ============================================================

def build_score_matrix(
    home_lambda: float,
    away_lambda: float
):
    """
    Build a theoretical Poisson score probability matrix.

    This is used together with Monte Carlo to make the score
    selection more stable.
    """

    matrix = {}

    total = 0.0

    for home_goals in range(
        MAX_GOALS + 1
    ):

        home_probability = poisson_pmf(
            home_goals,
            home_lambda
        )

        for away_goals in range(
            MAX_GOALS + 1
        ):

            away_probability = poisson_pmf(
                away_goals,
                away_lambda
            )

            probability = (
                home_probability
                * away_probability
            )

            matrix[
                (
                    home_goals,
                    away_goals
                )
            ] = probability

            total += probability

    # Normalize truncated matrix.
    if total > 0:

        for score in matrix:

            matrix[score] /= total

    return matrix


# ============================================================
# MONTE CARLO
# ============================================================

def monte_carlo_simulation(
    home_lambda: float,
    away_lambda: float,
    sims: int = MC_SIMS
):
    """
    Monte Carlo simulation.

    Returns:

        home win
        draw
        away win
        expected home goals
        expected away goals
        BTTS
        Over probabilities
        score distribution
    """

    home_win = 0
    draw = 0
    away_win = 0

    home_goals_total = 0
    away_goals_total = 0

    btts_count = 0

    over_counts = {
        line: 0
        for line in OVER_LINES
    }

    score_counter = Counter()

    # --------------------------------------------------------
    # SIMULATE
    # --------------------------------------------------------

    for _ in range(sims):

        home_goals = np_random_poisson(
            home_lambda
        )

        away_goals = np_random_poisson(
            away_lambda
        )

        home_goals_total += home_goals
        away_goals_total += away_goals

        score_counter[
            (
                home_goals,
                away_goals
            )
        ] += 1

        # ----------------------------------------------------
        # 1X2
        # ----------------------------------------------------

        if home_goals > away_goals:

            home_win += 1

        elif home_goals == away_goals:

            draw += 1

        else:

            away_win += 1

        # ----------------------------------------------------
        # BTTS
        # ----------------------------------------------------

        if (
            home_goals > 0
            and away_goals > 0
        ):

            btts_count += 1

        # ----------------------------------------------------
        # OVER
        # ----------------------------------------------------

        total_goals = (
            home_goals
            + away_goals
        )

        for line in OVER_LINES:

            if total_goals > line:

                over_counts[
                    line
                ] += 1

    # --------------------------------------------------------
    # PROBABILITIES
    # --------------------------------------------------------

    probabilities = {

        "home": (
            home_win
            / sims
        ),

        "draw": (
            draw
            / sims
        ),

        "away": (
            away_win
            / sims
        ),

        "btts": (
            btts_count
            / sims
        ),
    }

    for line in OVER_LINES:

        key = (
            "over_"
            + str(line).replace(
                ".",
                "_"
            )
        )

        probabilities[key] = (
            over_counts[line]
            / sims
        )

    probabilities[
        "expected_home"
    ] = (
        home_goals_total
        / sims
    )

    probabilities[
        "expected_away"
    ] = (
        away_goals_total
        / sims
    )

    probabilities[
        "scores"
    ] = score_counter

    return probabilities


# ============================================================
# NUMPY POISSON HELPER
# ============================================================

def np_random_poisson(
    lam: float
) -> int:
    """
    Small wrapper around NumPy without requiring the caller
    to import NumPy directly.
    """

    # Python's random module does not provide Poisson.
    # Use NumPy through a local import so the rest of the file
    # remains lightweight.
    import numpy as np

    return int(
        np.random.poisson(
            lam
        )
    )


# ============================================================
# SCORE SELECTION
# ============================================================

def select_primary_score(
    score_counter: Counter
):
    """
    Select the most frequently simulated scoreline.
    """

    if not score_counter:

        return (
            1,
            1
        )

    return max(
        score_counter,
        key=score_counter.get
    )


def select_alternative_score(
    score_counter: Counter,
    primary_score
):
    """
    Select a strong alternative scoreline.

    It must differ from the primary score.

    Preference:

        1. High simulation frequency
        2. Realistic goal count
        3. Avoid extreme scores
        4. Prefer close scorelines

    Example:

        Primary:
            1-1

        Alternative:
            2-1
    """

    if not score_counter:

        return (
            2,
            1
        )

    ranked = sorted(
        score_counter.items(),
        key=lambda item: item[1],
        reverse=True
    )

    best_score = None
    best_value = -1.0

    max_count = ranked[0][1]

    for score, count in ranked:

        if score == primary_score:

            continue

        home_goals = score[0]
        away_goals = score[1]

        # ----------------------------------------------------
        # Remove unrealistic scores.
        # ----------------------------------------------------

        if (
            home_goals
            > MAX_ALTERNATIVE_GOALS
        ):
            continue

        if (
            away_goals
            > MAX_ALTERNATIVE_GOALS
        ):
            continue

        total_goals = (
            home_goals
            + away_goals
        )

        if (
            total_goals
            > MAX_ALTERNATIVE_GOALS
        ):
            continue

        # ----------------------------------------------------
        # Frequency score
        # ----------------------------------------------------

        frequency = (
            count
            / max_count
        )

        # ----------------------------------------------------
        # Goal-total realism
        # ----------------------------------------------------

        if total_goals <= 4:

            realism = 1.00

        elif total_goals == 5:

            realism = 0.95

        elif total_goals == 6:

            realism = 0.85

        else:

            realism = 0.70

        # ----------------------------------------------------
        # Score closeness
        # ----------------------------------------------------

        difference = abs(
            home_goals
            - away_goals
        )

        if difference == 0:

            closeness = 1.00

        elif difference == 1:

            closeness = 0.98

        elif difference == 2:

            closeness = 0.90

        else:

            closeness = 0.75

        # ----------------------------------------------------
        # Final ranking value
        # ----------------------------------------------------

        value = (
            frequency
            * realism
            * closeness
        )

        if value > best_value:

            best_value = value
            best_score = score

    if best_score is None:

        for score, _ in ranked:

            if score != primary_score:

                return score

        return (
            2,
            1
        )

    return best_score


# ============================================================
# SCORE PROBABILITY
# ============================================================

def score_probability(
    score_counter: Counter,
    score
) -> float:

    if not score_counter:

        return 0.0

    total = sum(
        score_counter.values()
    )

    if total <= 0:

        return 0.0

    return (
        score_counter.get(
            score,
            0
        )
        / total
    )


# ============================================================
# PREDICTION LABEL
# ============================================================

def prediction_label(
    home_probability: float,
    draw_probability: float,
    away_probability: float
) -> str:

    if (
        home_probability
        >= draw_probability
        and home_probability
        >= away_probability
    ):

        return "Home Win"

    if (
        away_probability
        >= home_probability
        and away_probability
        >= draw_probability
    ):

        return "Away Win"

    return "Draw"


# ============================================================
# MAIN PREDICTOR
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
            f"🔹 V4B_GOALS predicting "
            f"match {match_id}"
        )

        # ====================================================
        # MATCH
        # ====================================================

        row = await fetch_match(
            conn,
            match_id
        )

        if not row:

            print(
                f"⚠️ Match {match_id} "
                f"not found"
            )

            return None

        ref_date = parse_date(
            row["utcdate"]
        )

        home_id = (
            home_id
            or row["home_team_id"]
        )

        away_id = (
            away_id
            or row["away_team_id"]
        )

        if (
            not home_id
            or not away_id
        ):

            return None

        # ====================================================
        # LEAGUE AVERAGES
        # ====================================================

        league_home_avg, league_away_avg = (
            await fetch_league_avgs(
                conn,
                ref_date
            )
        )

        # ====================================================
        # RECENT FORM
        # ====================================================

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

        # ====================================================
        # ATTACK / DEFENSE
        # ====================================================

        home_attack, home_defense = (
            attack_defense(
                home_recent,
                home_id,
                ref_date
            )
        )

        away_attack, away_defense = (
            attack_defense(
                away_recent,
                away_id,
                ref_date
            )
        )

        # ====================================================
        # LEAGUE-NORMALIZED LAMBDAS
        # ====================================================

        home_lambda = (
            league_home_avg
            * home_attack
            * away_defense
            * HOME_ADV
        )

        away_lambda = (
            league_away_avg
            * away_attack
            * home_defense
        )

        # ====================================================
        # FORM MOMENTUM
        # ====================================================

        # Compare team's recent scoring rate with league
        # scoring baseline.

        if league_home_avg > 0:

            home_form_ratio = (
                home_attack
                / league_home_avg
            )

        else:

            home_form_ratio = 1.0

        if league_away_avg > 0:

            away_form_ratio = (
                away_attack
                / league_away_avg
            )

        else:

            away_form_ratio = 1.0

        home_form_modifier = (
            1.0
            + FORM_LAMBDA_WEIGHT
            * (
                home_form_ratio
                - 1.0
            )
        )

        away_form_modifier = (
            1.0
            + FORM_LAMBDA_WEIGHT
            * (
                away_form_ratio
                - 1.0
            )
        )

        home_lambda *= (
            max(
                0.75,
                min(
                    1.25,
                    home_form_modifier
                )
            )
        )

        away_lambda *= (
            max(
                0.75,
                min(
                    1.25,
                    away_form_modifier
                )
            )
        )

        # ====================================================
        # H2H
        # ====================================================

        h2h_home_modifier, h2h_away_modifier = (
            await h2h_modifier(
                conn,
                home_id,
                away_id,
                ref_date
            )
        )

        home_lambda *= (
            h2h_home_modifier
        )

        away_lambda *= (
            h2h_away_modifier
        )

        # ====================================================
        # ELO
        # ====================================================

        home_elo = await compute_elo(
            conn,
            home_id
        )

        away_elo = await compute_elo(
            conn,
            away_id
        )

        home_lambda, away_lambda = (
            apply_elo_to_lambdas(
                home_lambda,
                away_lambda,
                home_elo,
                away_elo
            )
        )

        # ====================================================
        # FINAL SAFETY
        # ====================================================

        home_lambda = max(
            MIN_LAMBDA,
            min(
                MAX_LAMBDA,
                home_lambda
            )
        )

        away_lambda = max(
            MIN_LAMBDA,
            min(
                MAX_LAMBDA,
                away_lambda
            )
        )

        # ====================================================
        # MONTE CARLO
        # ====================================================

        simulation = (
            monte_carlo_simulation(
                home_lambda,
                away_lambda,
                MC_SIMS
            )
        )

        home_probability = (
            simulation["home"]
        )

        draw_probability = (
            simulation["draw"]
        )

        away_probability = (
            simulation["away"]
        )

        # ====================================================
        # PRIMARY SCORE
        # ====================================================

        primary_score = (
            select_primary_score(
                simulation["scores"]
            )
        )

        primary_score_probability = (
            score_probability(
                simulation["scores"],
                primary_score
            )
        )

        # ====================================================
        # ALTERNATIVE SCORE
        # ====================================================

        alternative_score = (
            select_alternative_score(
                simulation["scores"],
                primary_score
            )
        )

        alternative_score_probability = (
            score_probability(
                simulation["scores"],
                alternative_score
            )
        )

        # ====================================================
        # CONFIDENCE
        # ====================================================

        model_confidence = confidence(
            home_probability,
            draw_probability,
            away_probability
        )

        # ====================================================
        # PREDICTION
        # ====================================================

        label = prediction_label(
            home_probability,
            draw_probability,
            away_probability
        )

        # ====================================================
        # BTTS
        # ====================================================

        btts_probability = (
            simulation["btts"]
        )

        btts_prediction = (
            "Yes"
            if btts_probability >= 0.50
            else "No"
        )

        # ====================================================
        # OVER MARKETS
        # ====================================================

        over_1_5 = (
            simulation["over_1_5"]
        )

        over_2_5 = (
            simulation["over_2_5"]
        )

        over_3_5 = (
            simulation["over_3_5"]
        )

        over_4_5 = (
            simulation["over_4_5"]
        )

        # ====================================================
        # TOTAL-GOAL EXPECTATION
        # ====================================================

        expected_home_goals = (
            simulation[
                "expected_home"
            ]
        )

        expected_away_goals = (
            simulation[
                "expected_away"
            ]
        )

        expected_total_goals = (
            expected_home_goals
            + expected_away_goals
        )

        # ====================================================
        # RETURN
        # ====================================================

        return {

            "prediction": label,

            "primary_score": (
                f"{primary_score[0]}"
                f"-"
                f"{primary_score[1]}"
            ),

            "alternative_score": (
                f"{alternative_score[0]}"
                f"-"
                f"{alternative_score[1]}"
            ),

            "primary_score_probability": round(
                primary_score_probability,
                3
            ),

            "alternative_score_probability": round(
                alternative_score_probability,
                3
            ),

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
                    expected_home_goals,
                    2
                ),

                "away": round(
                    expected_away_goals,
                    2
                ),

                "total": round(
                    expected_total_goals,
                    2
                ),
            },

            "markets": {

                "btts": round(
                    btts_probability,
                    3
                ),

                "btts_prediction": (
                    btts_prediction
                ),

                "over_1_5": round(
                    over_1_5,
                    3
                ),

                "over_2_5": round(
                    over_2_5,
                    3
                ),

                "over_3_5": round(
                    over_3_5,
                    3
                ),

                "over_4_5": round(
                    over_4_5,
                    3
                ),
            },

            "confidence": model_confidence,

            "model_version": (
                "V4B_GOALS_TIMEAWARE"
                "_H2H_FORM_POISSON_MC_ELO"
            ),

            "generated_at": (
                datetime.now(
                    UTC
                ).isoformat()
            ),

        }

    except Exception:

        traceback.print_exc()

        return None


# ============================================================
# WRAPPER
# ============================================================

async def predict_home_away(
    conn: asyncpg.Connection,
    match_id: int,
    home_id: Optional[int] = None,
    away_id: Optional[int] = None,
    **kwargs
):

    return await predict(
        conn,
        match_id,
        home_id,
        away_id,
        **kwargs
    )


# ============================================================
# SIMPLE TEST
# ============================================================

async def main_test():

    conn = await asyncpg.connect(
        DATABASE_URL
    )

    try:

        result = await predict(
            conn,
            match_id=1
        )

        print()
        print(
            "=============================="
        )

        print(
            "V4B_GOALS TEST RESULT"
        )

        print(
            "=============================="
        )

        print(
            result
        )

    finally:

        await conn.close()


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    import asyncio

    asyncio.run(
        main_test()
    )
