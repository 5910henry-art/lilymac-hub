#!/usr/bin/env python3
"""
V5 — RECENT 5 MATCH PREDICTOR

A lightweight time-aware football predictor.

CORE IDEA
---------
V5 ONLY looks at the most recent 5 FINISHED matches for each team
before the target match.

It does NOT use:

    - H2H
    - ELO
    - Standings
    - Bookmaker odds
    - Future matches
    - League averages from future data

It uses:

    - Last 5 matches
    - Recency decay
    - Goals scored
    - Goals conceded
    - Win / draw / loss form
    - Home team's recent home performance where available
    - Away team's recent away performance where available
    - Poisson goal probabilities
    - Monte Carlo simulation

OUTPUT
------
    - Home Win probability
    - Draw probability
    - Away Win probability
    - Prediction
    - Predicted score
    - Alternative score
    - Expected goals
    - BTTS probability
    - Over 1.5
    - Over 2.5
    - Over 3.5
    - Over 4.5
    - Confidence

IMPORTANT
---------
Every prediction is calculated using information available BEFORE
the target match's utcdate.

The model intentionally keeps the sample small: exactly the latest
5 completed matches for each team.

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
# CONFIGURATION
# ============================================================

# ONLY five recent matches
RECENT_MATCHES = 5

# Recent matches have stronger influence
DECAY = 0.85

# Number of Monte Carlo simulations
MC_SIMS = 10000

# Minimum expected goals
MIN_LAMBDA = 0.20

# Maximum expected goals
MAX_LAMBDA = 5.00

# Home advantage
HOME_ADVANTAGE = 1.08

# How strongly recent form changes the goal expectation
FORM_WEIGHT = 0.30

# Maximum score considered when selecting score predictions
MAX_SCORE = 7

# Goal markets
OVER_LINES = (
    1.5,
    2.5,
    3.5,
    4.5,
)


# ============================================================
# CACHE
# ============================================================

_recent_cache: Dict[
    Tuple[int, str],
    List[asyncpg.Record]
] = {}


# ============================================================
# DATE HELPERS
# ============================================================

def parse_date(value) -> datetime:
    """
    Safely convert a database datetime or ISO string to UTC.
    """

    try:

        if isinstance(value, datetime):

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


# ============================================================
# DECAY
# ============================================================

def decay_weight(index: int) -> float:
    """
    Recency weighting.

    index 0 = most recent match
    index 1 = second most recent
    etc.

    Example with DECAY=0.85:

        Match 1 = 1.000
        Match 2 = 0.850
        Match 3 = 0.7225
        Match 4 = 0.614
        Match 5 = 0.522
    """

    return DECAY ** index


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
        FROM matches
        WHERE id=$1
        LIMIT 1
        """,
        match_id
    )


# ============================================================
# LAST 5 MATCHES
# ============================================================

async def fetch_recent_matches(
    conn: asyncpg.Connection,
    team_id: int,
    ref_date: datetime
) -> List[asyncpg.Record]:
    """
    Fetch ONLY the five most recent finished matches
    before the target match.
    """

    cache_key = (
        team_id,
        ref_date.isoformat()
    )

    if cache_key in _recent_cache:

        return _recent_cache[
            cache_key
        ]

    rows = await conn.fetch(
        f"""
        SELECT
            id,
            utcdate,
            home_team_id,
            away_team_id,
            home_score,
            away_score
        FROM matches
        WHERE utcdate < $1
          AND status='FINISHED'
          AND (
              home_team_id=$2
              OR away_team_id=$2
          )
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
        ORDER BY utcdate DESC
        LIMIT {RECENT_MATCHES}
        """,
        ref_date,
        team_id
    )

    _recent_cache[
        cache_key
    ] = rows

    return rows


# ============================================================
# TEAM RECENT FORM
# ============================================================

def calculate_recent_form(
    rows: List[asyncpg.Record],
    team_id: int
) -> Dict[str, float]:
    """
    Calculate statistics from ONLY the supplied recent matches.

    Returns:

        goals_for
        goals_against
        attack
        defense
        win_rate
        draw_rate
        loss_rate
        points_rate
        btts_rate
        over_1_5_rate
        over_2_5_rate
        over_3_5_rate
        home_games
        away_games
    """

    if not rows:

        return {
            "goals_for": 1.0,
            "goals_against": 1.0,
            "attack": 1.0,
            "defense": 1.0,
            "win_rate": 0.333,
            "draw_rate": 0.333,
            "loss_rate": 0.333,
            "points_rate": 0.333,
            "btts_rate": 0.50,
            "over_1_5_rate": 0.50,
            "over_2_5_rate": 0.50,
            "over_3_5_rate": 0.30,
            "over_4_5_rate": 0.15,
            "home_games": 0.0,
            "away_games": 0.0,
        }

    goals_for = 0.0
    goals_against = 0.0

    total_weight = 0.0

    wins = 0.0
    draws = 0.0
    losses = 0.0

    points = 0.0

    btts = 0.0

    over_1_5 = 0.0
    over_2_5 = 0.0
    over_3_5 = 0.0
    over_4_5 = 0.0

    home_games = 0
    away_games = 0

    for index, row in enumerate(rows):

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

        home_score = float(
            home_score
        )

        away_score = float(
            away_score
        )

        weight = decay_weight(
            index
        )

        # ----------------------------------------------------
        # Determine team's goals
        # ----------------------------------------------------

        if (
            row["home_team_id"]
            == team_id
        ):

            scored = home_score
            conceded = away_score

            home_games += 1

        else:

            scored = away_score
            conceded = home_score

            away_games += 1

        # ----------------------------------------------------
        # Goals
        # ----------------------------------------------------

        goals_for += (
            scored
            * weight
        )

        goals_against += (
            conceded
            * weight
        )

        total_weight += weight

        # ----------------------------------------------------
        # Result
        # ----------------------------------------------------

        if scored > conceded:

            wins += weight
            points += (
                3
                * weight
            )

        elif scored == conceded:

            draws += weight
            points += (
                1
                * weight
            )

        else:

            losses += weight

        # ----------------------------------------------------
        # BTTS
        # ----------------------------------------------------

        if (
            scored > 0
            and conceded > 0
        ):

            btts += weight

        # ----------------------------------------------------
        # Goal totals
        # ----------------------------------------------------

        total_goals = (
            scored
            + conceded
        )

        if total_goals > 1.5:

            over_1_5 += weight

        if total_goals > 2.5:

            over_2_5 += weight

        if total_goals > 3.5:

            over_3_5 += weight

        if total_goals > 4.5:

            over_4_5 += weight

    if total_weight <= 0:

        return {
            "goals_for": 1.0,
            "goals_against": 1.0,
            "attack": 1.0,
            "defense": 1.0,
            "win_rate": 0.333,
            "draw_rate": 0.333,
            "loss_rate": 0.333,
            "points_rate": 0.333,
            "btts_rate": 0.50,
            "over_1_5_rate": 0.50,
            "over_2_5_rate": 0.50,
            "over_3_5_rate": 0.30,
            "over_4_5_rate": 0.15,
            "home_games": 0.0,
            "away_games": 0.0,
        }

    return {

        "goals_for": (
            goals_for
            / total_weight
        ),

        "goals_against": (
            goals_against
            / total_weight
        ),

        "attack": (
            goals_for
            / total_weight
        ),

        "defense": (
            goals_against
            / total_weight
        ),

        "win_rate": (
            wins
            / total_weight
        ),

        "draw_rate": (
            draws
            / total_weight
        ),

        "loss_rate": (
            losses
            / total_weight
        ),

        "points_rate": (
            points
            / (
                3
                * total_weight
            )
        ),

        "btts_rate": (
            btts
            / total_weight
        ),

        "over_1_5_rate": (
            over_1_5
            / total_weight
        ),

        "over_2_5_rate": (
            over_2_5
            / total_weight
        ),

        "over_3_5_rate": (
            over_3_5
            / total_weight
        ),

        "over_4_5_rate": (
            over_4_5
            / total_weight
        ),

        "home_games": float(
            home_games
        ),

        "away_games": float(
            away_games
        ),
    }


# ============================================================
# HOME/AWAY SPLIT
# ============================================================

def calculate_home_away_split(
    rows: List[asyncpg.Record],
    team_id: int,
    venue: str
) -> Optional[Dict[str, float]]:
    """
    Calculate recent performance only from the team's relevant
    venue matches.

    venue:

        "home"
        "away"

    Because only five matches are used overall, there may be fewer
    than five relevant venue matches.

    If there are not enough relevant matches, the caller should
    fall back toward the overall five-match form.
    """

    filtered = []

    for row in rows:

        if venue == "home":

            if (
                row["home_team_id"]
                == team_id
            ):

                filtered.append(row)

        elif venue == "away":

            if (
                row["away_team_id"]
                == team_id
            ):

                filtered.append(row)

    if not filtered:

        return None

    return calculate_recent_form(
        filtered,
        team_id
    )


# ============================================================
# LAMBDA CALCULATION
# ============================================================

def calculate_lambdas(
    home_form: Dict[str, float],
    away_form: Dict[str, float],
    home_venue: Optional[Dict[str, float]],
    away_venue: Optional[Dict[str, float]]
) -> Tuple[float, float]:
    """
    Convert recent five-match form into expected goals.

    Main signal:

        Home recent attack
        Away recent defense

        Away recent attack
        Home recent defense

    Venue-specific form is blended when available.

    No league averages are used.
    """

    # --------------------------------------------------------
    # Overall recent attack / defense
    # --------------------------------------------------------

    home_attack = (
        home_form["attack"]
    )

    home_defense = (
        home_form["defense"]
    )

    away_attack = (
        away_form["attack"]
    )

    away_defense = (
        away_form["defense"]
    )

    # --------------------------------------------------------
    # Venue-specific information
    # --------------------------------------------------------

    if home_venue:

        home_attack = (
            0.65
            * home_attack
            + 0.35
            * home_venue["attack"]
        )

        home_defense = (
            0.65
            * home_defense
            + 0.35
            * home_venue["defense"]
        )

    if away_venue:

        away_attack = (
            0.65
            * away_attack
            + 0.35
            * away_venue["attack"]
        )

        away_defense = (
            0.65
            * away_defense
            + 0.35
            * away_venue["defense"]
        )

    # --------------------------------------------------------
    # Basic goal expectation
    # --------------------------------------------------------

    home_lambda = (
        home_attack
        * (
            0.70
            + 0.30
            * away_defense
        )
    )

    away_lambda = (
        away_attack
        * (
            0.70
            + 0.30
            * home_defense
        )
    )

    # --------------------------------------------------------
    # Form momentum
    # --------------------------------------------------------

    # Strong recent points rate gives a modest increase.
    #
    # Weak recent points rate gives a modest decrease.

    home_form_modifier = (
        1.0
        + FORM_WEIGHT
        * (
            home_form["points_rate"]
            - 0.50
        )
    )

    away_form_modifier = (
        1.0
        + FORM_WEIGHT
        * (
            away_form["points_rate"]
            - 0.50
        )
    )

    home_lambda *= (
        home_form_modifier
    )

    away_lambda *= (
        away_form_modifier
    )

    # --------------------------------------------------------
    # Home advantage
    # --------------------------------------------------------

    home_lambda *= (
        HOME_ADVANTAGE
    )

    # --------------------------------------------------------
    # Safety limits
    # --------------------------------------------------------

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

    return (
        home_lambda,
        away_lambda
    )


# ============================================================
# POISSON
# ============================================================

def poisson_pmf(
    goals: int,
    lam: float
) -> float:

    try:

        return (
            (lam ** goals)
            * exp(-lam)
            / factorial(goals)
        )

    except Exception:

        return 0.0


# ============================================================
# POISSON SCORE MATRIX
# ============================================================

def build_score_matrix(
    home_lambda: float,
    away_lambda: float
) -> Dict[Tuple[int, int], float]:
    """
    Theoretical Poisson score probabilities.
    """

    matrix = {}

    total = 0.0

    for home_goals in range(
        MAX_SCORE + 1
    ):

        home_probability = poisson_pmf(
            home_goals,
            home_lambda
        )

        for away_goals in range(
            MAX_SCORE + 1
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

    if total > 0:

        for score in matrix:

            matrix[score] /= total

    return matrix


# ============================================================
# MONTE CARLO
# ============================================================

def poisson_random(
    lam: float
) -> int:
    """
    Generate a Poisson random number using Knuth's algorithm.

    This avoids requiring NumPy for the V5 predictor.
    """

    L = exp(-lam)

    k = 0
    p = 1.0

    while p > L:

        k += 1

        p *= random.random()

    return k - 1


def monte_carlo(
    home_lambda: float,
    away_lambda: float,
    sims: int = MC_SIMS
) -> Dict[str, Any]:
    """
    Simulate the match many times.

    BTTS and Over probabilities are calculated directly from
    the simulated scorelines.
    """

    home_wins = 0
    draws = 0
    away_wins = 0

    btts = 0

    over_counts = {
        line: 0
        for line in OVER_LINES
    }

    home_goals_total = 0
    away_goals_total = 0

    scores = Counter()

    for _ in range(sims):

        home_goals = poisson_random(
            home_lambda
        )

        away_goals = poisson_random(
            away_lambda
        )

        # ----------------------------------------------------
        # Store score
        # ----------------------------------------------------

        scores[
            (
                home_goals,
                away_goals
            )
        ] += 1

        # ----------------------------------------------------
        # Total goals
        # ----------------------------------------------------

        total_goals = (
            home_goals
            + away_goals
        )

        home_goals_total += (
            home_goals
        )

        away_goals_total += (
            away_goals
        )

        # ----------------------------------------------------
        # 1X2
        # ----------------------------------------------------

        if home_goals > away_goals:

            home_wins += 1

        elif home_goals == away_goals:

            draws += 1

        else:

            away_wins += 1

        # ----------------------------------------------------
        # BTTS
        # ----------------------------------------------------

        if (
            home_goals > 0
            and away_goals > 0
        ):

            btts += 1

        # ----------------------------------------------------
        # OVER
        # ----------------------------------------------------

        for line in OVER_LINES:

            if total_goals > line:

                over_counts[line] += 1

    result = {

        "home": (
            home_wins
            / sims
        ),

        "draw": (
            draws
            / sims
        ),

        "away": (
            away_wins
            / sims
        ),

        "btts": (
            btts
            / sims
        ),

        "expected_home": (
            home_goals_total
            / sims
        ),

        "expected_away": (
            away_goals_total
            / sims
        ),

        "scores": scores,
    }

    for line in OVER_LINES:

        result[
            "over_"
            + str(line).replace(
                ".",
                "_"
            )
        ] = (
            over_counts[line]
            / sims
        )

    return result


# ============================================================
# SCORE SELECTION
# ============================================================

def select_primary_score(
    scores: Counter
) -> Tuple[int, int]:
    """
    Most frequently simulated score.
    """

    if not scores:

        return (
            1,
            1
        )

    return max(
        scores,
        key=scores.get
    )


def select_alternative_score(
    scores: Counter,
    primary_score: Tuple[int, int]
) -> Tuple[int, int]:
    """
    Select the second strongest realistic scoreline.

    It must be different from the primary score.
    """

    if not scores:

        return (
            2,
            1
        )

    ranked = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True
    )

    for score, _ in ranked:

        if score == primary_score:

            continue

        home_goals, away_goals = score

        if (
            home_goals <= MAX_SCORE
            and away_goals <= MAX_SCORE
        ):

            return score

    return (
        2,
        1
    )


# ============================================================
# SCORE PROBABILITY
# ============================================================

def score_probability(
    scores: Counter,
    score: Tuple[int, int]
) -> float:

    total = sum(
        scores.values()
    )

    if total <= 0:

        return 0.0

    return (
        scores.get(
            score,
            0
        )
        / total
    )


# ============================================================
# CONFIDENCE
# ============================================================

def calculate_confidence(
    home: float,
    draw: float,
    away: float
) -> float:
    """
    Entropy-based confidence.

    Confidence increases when the three-way distribution
    becomes more decisive.
    """

    values = (
        home,
        draw,
        away
    )

    entropy = -sum(
        p * log2(p)
        for p in values
        if p > 0
    )

    confidence_value = (
        1
        - entropy / 1.585
    )

    # V5 has a minimum floor but does not pretend that
    # an uncertain match is highly confident.

    confidence_value = max(
        0.50,
        min(
            0.95,
            confidence_value
        )
    )

    return round(
        confidence_value,
        3
    )


# ============================================================
# PREDICTION LABEL
# ============================================================

def get_prediction(
    home: float,
    draw: float,
    away: float
) -> str:

    if (
        home >= draw
        and home >= away
    ):

        return "Home Win"

    if (
        away >= home
        and away >= draw
    ):

        return "Away Win"

    return "Draw"


# ============================================================
# MARKET LABELS
# ============================================================

def yes_no(
    probability: float
) -> str:

    return (
        "Yes"
        if probability >= 0.50
        else "No"
    )


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
            f"🔹 V5 predicting match "
            f"{match_id}"
        )

        # ====================================================
        # TARGET MATCH
        # ====================================================

        match = await fetch_match(
            conn,
            match_id
        )

        if not match:

            print(
                f"⚠️ Match {match_id} "
                f"not found"
            )

            return None

        ref_date = parse_date(
            match["utcdate"]
        )

        home_id = (
            home_id
            or match["home_team_id"]
        )

        away_id = (
            away_id
            or match["away_team_id"]
        )

        if (
            not home_id
            or not away_id
        ):

            return None

        # ====================================================
        # LAST 5 ONLY
        # ====================================================

        home_recent = (
            await fetch_recent_matches(
                conn,
                home_id,
                ref_date
            )
        )

        away_recent = (
            await fetch_recent_matches(
                conn,
                away_id,
                ref_date
            )
        )

        # ====================================================
        # FORM
        # ====================================================

        home_form = calculate_recent_form(
            home_recent,
            home_id
        )

        away_form = calculate_recent_form(
            away_recent,
            away_id
        )

        # ====================================================
        # VENUE SPLIT
        # ====================================================

        home_venue = (
            calculate_home_away_split(
                home_recent,
                home_id,
                "home"
            )
        )

        away_venue = (
            calculate_home_away_split(
                away_recent,
                away_id,
                "away"
            )
        )

        # ====================================================
        # EXPECTED GOALS
        # ====================================================

        home_lambda, away_lambda = (
            calculate_lambdas(
                home_form,
                away_form,
                home_venue,
                away_venue
            )
        )

        # ====================================================
        # MONTE CARLO
        # ====================================================

        simulation = monte_carlo(
            home_lambda,
            away_lambda,
            MC_SIMS
        )

        # ====================================================
        # 1X2
        # ====================================================

        home_probability = (
            simulation["home"]
        )

        draw_probability = (
            simulation["draw"]
        )

        away_probability = (
            simulation["away"]
        )

        prediction = get_prediction(
            home_probability,
            draw_probability,
            away_probability
        )

        # ====================================================
        # SCORES
        # ====================================================

        primary_score = (
            select_primary_score(
                simulation["scores"]
            )
        )

        alternative_score = (
            select_alternative_score(
                simulation["scores"],
                primary_score
            )
        )

        primary_score_probability = (
            score_probability(
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
        # EXPECTED GOALS
        # ====================================================

        expected_home = (
            simulation["expected_home"]
        )

        expected_away = (
            simulation["expected_away"]
        )

        expected_total = (
            expected_home
            + expected_away
        )

        # ====================================================
        # GOAL MARKETS
        # ====================================================

        btts_probability = (
            simulation["btts"]
        )

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
        # CONFIDENCE
        # ====================================================

        confidence = calculate_confidence(
            home_probability,
            draw_probability,
            away_probability
        )

        # ====================================================
        # RETURN
        # ====================================================

        return {

            # ------------------------------------------------
            # MODEL
            # ------------------------------------------------

            "model_version": (
                "V5_RECENT_5_ONLY"
            ),

            "prediction": prediction,

            # ------------------------------------------------
            # SCORE
            # ------------------------------------------------

            "predicted_score": (
                f"{primary_score[0]}"
                f"-"
                f"{primary_score[1]}"
            ),

            "alternative_score": (
                f"{alternative_score[0]}"
                f"-"
                f"{alternative_score[1]}"
            ),

            "score_probability": round(
                primary_score_probability,
                3
            ),

            "alternative_score_probability": round(
                alternative_score_probability,
                3
            ),

            # ------------------------------------------------
            # 1X2
            # ------------------------------------------------

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

            # ------------------------------------------------
            # EXPECTED GOALS
            # ------------------------------------------------

            "expected_goals": {

                "home": round(
                    expected_home,
                    2
                ),

                "away": round(
                    expected_away,
                    2
                ),

                "total": round(
                    expected_total,
                    2
                ),
            },

            # ------------------------------------------------
            # MARKETS
            # ------------------------------------------------

            "markets": {

                "btts": round(
                    btts_probability,
                    3
                ),

                "btts_prediction": yes_no(
                    btts_probability
                ),

                "over_1_5": round(
                    over_1_5,
                    3
                ),

                "over_1_5_prediction": yes_no(
                    over_1_5
                ),

                "over_2_5": round(
                    over_2_5,
                    3
                ),

                "over_2_5_prediction": yes_no(
                    over_2_5
                ),

                "over_3_5": round(
                    over_3_5,
                    3
                ),

                "over_3_5_prediction": yes_no(
                    over_3_5
                ),

                "over_4_5": round(
                    over_4_5,
                    3
                ),

                "over_4_5_prediction": yes_no(
                    over_4_5
                ),
            },

            # ------------------------------------------------
            # CONFIDENCE
            # ------------------------------------------------

            "confidence": confidence,

            # ------------------------------------------------
            # DATA USED
            # ------------------------------------------------

            "data": {

                "home_recent_matches": len(
                    home_recent
                ),

                "away_recent_matches": len(
                    away_recent
                ),

                "home_last_5_goals_for": round(
                    home_form["goals_for"],
                    2
                ),

                "home_last_5_goals_against": round(
                    home_form["goals_against"],
                    2
                ),

                "away_last_5_goals_for": round(
                    away_form["goals_for"],
                    2
                ),

                "away_last_5_goals_against": round(
                    away_form["goals_against"],
                    2
                ),

                "home_win_rate": round(
                    home_form["win_rate"],
                    3
                ),

                "home_draw_rate": round(
                    home_form["draw_rate"],
                    3
                ),

                "home_loss_rate": round(
                    home_form["loss_rate"],
                    3
                ),

                "away_win_rate": round(
                    away_form["win_rate"],
                    3
                ),

                "away_draw_rate": round(
                    away_form["draw_rate"],
                    3
                ),

                "away_loss_rate": round(
                    away_form["loss_rate"],
                    3
                ),
            },

            # ------------------------------------------------
            # INTERNAL MODEL VALUES
            # ------------------------------------------------

            "model_values": {

                "home_lambda": round(
                    home_lambda,
                    3
                ),

                "away_lambda": round(
                    away_lambda,
                    3
                ),

                "home_attack": round(
                    home_form["attack"],
                    3
                ),

                "home_defense": round(
                    home_form["defense"],
                    3
                ),

                "away_attack": round(
                    away_form["attack"],
                    3
                ),

                "away_defense": round(
                    away_form["defense"],
                    3
                ),
            },

            # ------------------------------------------------
            # TIME
            # ------------------------------------------------

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
# TEST
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
            "=========================================="
        )

        print(
            "V5 — RECENT 5 MATCH PREDICTOR"
        )

        print(
            "=========================================="
        )

        print(
            result
        )

        print(
            "=========================================="
        )

    finally:

        await conn.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    import asyncio

    print(
        "🚀 Running V5 — Recent 5 Match Predictor..."
    )

    asyncio.run(
        main_test()
    )
