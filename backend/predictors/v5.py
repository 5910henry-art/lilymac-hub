#!/usr/bin/env python3
"""
V5_POSITION_AWARE — Recent 5 Matches + Opponent Strength Predictor

Uses ONLY:
    - Each team's latest 5 finished matches before the target match
    - Historical opponent league position
    - Historical opponent goal difference
    - Recency weighting
    - Goals scored / conceded
    - Form
    - Home / away venue performance
    - Poisson goal model
    - Monte Carlo simulation

Does NOT use:
    - H2H
    - ELO
    - Bookmaker odds
    - Current/future standings
    - Future match results

Markets:
    - Home / Draw / Away
    - Predicted score
    - Alternative score
    - BTTS
    - Over 1.5
    - Over 2.5
    - Over 3.5
    - Over 4.5
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
# CONFIG
# ============================================================

RECENT_MATCHES = 5

# More recent matches matter more
DECAY = 0.85

# Monte Carlo simulations
MC_SIMS = 10000

# Goal limits
MIN_LAMBDA = 0.20
MAX_LAMBDA = 5.00

# Home advantage
HOME_ADVANTAGE = 1.08

# How strongly recent points form affects goals
FORM_WEIGHT = 0.25

# How strongly opponent strength affects goals
OPPONENT_STRENGTH_WEIGHT = 0.30

# Score matrix
MAX_SCORE = 7

# Over markets
OVER_LINES = (
    1.5,
    2.5,
    3.5,
    4.5,
)


UTC = timezone.utc


# ============================================================
# CACHE
# ============================================================

_recent_cache: Dict[
    Tuple[int, str],
    List[asyncpg.Record]
] = {}

_standing_cache: Dict[
    Tuple[int, int, str, str],
    Optional[asyncpg.Record]
] = {}


# ============================================================
# DATE
# ============================================================

def parse_date(value) -> datetime:

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

    return DECAY ** index


# ============================================================
# TARGET MATCH
# ============================================================

async def fetch_match(
    conn: asyncpg.Connection,
    match_id: int
):

    return await conn.fetchrow(
        """
        SELECT
            id,
            utcdate,
            home_team_id,
            away_team_id,
            season,
            competition
        FROM matches
        WHERE id=$1
        LIMIT 1
        """,
        match_id
    )


# ============================================================
# RECENT MATCHES
# ============================================================

async def fetch_recent_matches(
    conn: asyncpg.Connection,
    team_id: int,
    ref_date: datetime
) -> List[asyncpg.Record]:

    key = (
        team_id,
        ref_date.isoformat()
    )

    if key in _recent_cache:

        return _recent_cache[key]

    rows = await conn.fetch(
        f"""
        SELECT
            id,
            utcdate,
            home_team_id,
            away_team_id,
            home_score,
            away_score,
            season,
            competition
        FROM matches
        WHERE utcdate < $1
          AND status='FINISHED'
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
          AND (
              home_team_id=$2
              OR away_team_id=$2
          )
        ORDER BY utcdate DESC
        LIMIT {RECENT_MATCHES}
        """,
        ref_date,
        team_id
    )

    _recent_cache[key] = rows

    return rows


# ============================================================
# HISTORICAL STANDINGS
# ============================================================

async def get_historical_standing(
    conn: asyncpg.Connection,
    team_id: int,
    season: int,
    league: str,
    match_date: datetime
) -> Optional[asyncpg.Record]:
    """
    Find the most recent historical standings snapshot
    strictly BEFORE the historical match.

    Uses henry_schema.historical_standings rather than the
    current standings table to prevent future-information leakage.
    """

    code_to_competition = {
        "PL": "Premier League",
        "PD": "Primera Division",
        "BL1": "Bundesliga",
        "FL1": "Ligue 1",
        "SA": "Serie A",
        "CL": "UEFA Champions League",
    }

    league_name = code_to_competition.get(
        str(league).upper(),
        str(league)
    )

    key = (
        team_id,
        season,
        league_name,
        match_date.isoformat()
    )

    if key in _standing_cache:
        return _standing_cache[key]

    row = await conn.fetchrow(
        """
        SELECT
            competition,
            league_code,
            season,
            matchday,
            snapshot_date,
            team_id,
            rank,
            points,
            win,
            draw,
            lose,
            goals_for,
            goals_against,
            goal_diff,
            matches_played
        FROM henry_schema.historical_standings
        WHERE team_id = $1
          AND season = $2
          AND competition = $3
          AND snapshot_date < $4
        ORDER BY snapshot_date DESC, matchday DESC
        LIMIT 1
        """,
        team_id,
        season,
        league_name,
        match_date
    )

    _standing_cache[key] = row

    return row


# ============================================================
# OPPONENT STRENGTH
# ============================================================

def rank_strength(rank: Optional[int]) -> float:
    """
    Convert league rank into opponent strength.

    Lower rank = stronger opponent.

    Example:

        #1  -> strong
        #5  -> strong
        #10 -> average
        #15 -> weaker
        #20 -> weak

    The value is centered around 1.0.
    """

    if rank is None:

        return 1.0

    try:

        rank = int(rank)

    except Exception:

        return 1.0

    if rank <= 2:

        return 1.20

    if rank <= 4:

        return 1.16

    if rank <= 6:

        return 1.12

    if rank <= 8:

        return 1.08

    if rank <= 10:

        return 1.04

    if rank <= 12:

        return 1.00

    if rank <= 14:

        return 0.96

    if rank <= 16:

        return 0.92

    if rank <= 18:

        return 0.88

    return 0.84


# ============================================================
# OPPONENT GOAL-DIFFERENCE STRENGTH
# ============================================================

def goal_difference_strength(
    standing: Optional[asyncpg.Record]
) -> float:
    """
    Additional opponent-strength signal from goal difference.

    It is intentionally capped so that one extreme statistic
    cannot dominate the model.
    """

    if not standing:

        return 1.0

    try:

        gd = float(
            standing["goal_diff"]
            or 0
        )

    except Exception:

        return 1.0

    # Approximately +/- 30 goal difference represents the useful
    # range for this modifier.

    modifier = (
        1.0
        + max(
            -0.12,
            min(
                0.12,
                gd / 250.0
            )
        )
    )

    return modifier


# ============================================================
# COMBINED OPPONENT STRENGTH
# ============================================================

def opponent_strength(
    standing: Optional[asyncpg.Record]
) -> float:

    if not standing:

        return 1.0

    rank_factor = rank_strength(
        standing["rank"]
    )

    gd_factor = goal_difference_strength(
        standing
    )

    strength = (
        0.70
        * rank_factor
        + 0.30
        * gd_factor
    )

    return max(
        0.80,
        min(
            1.20,
            strength
        )
    )


# ============================================================
# ADJUST HISTORICAL GOALS
# ============================================================

def strength_adjusted_goals(
    scored: float,
    conceded: float,
    strength: float
) -> Tuple[float, float]:
    """
    Adjust historical performance based on opponent quality.

    Scoring against a strong opponent is rewarded.

    Conceding against a strong opponent is treated as less
    damaging than conceding against a weak opponent.
    """

    if strength <= 0:

        strength = 1.0

    adjusted_scored = (
        scored
        * (
            1.0
            + OPPONENT_STRENGTH_WEIGHT
            * (strength - 1.0)
        )
    )

    adjusted_conceded = (
        conceded
        * (
            1.0
            - OPPONENT_STRENGTH_WEIGHT
            * (strength - 1.0)
        )
    )

    return (
        adjusted_scored,
        adjusted_conceded
    )


# ============================================================
# RECENT FORM
# ============================================================

async def calculate_recent_form(
    conn: asyncpg.Connection,
    rows: List[asyncpg.Record],
    team_id: int
) -> Dict[str, float]:

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
            "strength_average": 1.0,
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

    strength_sum = 0.0

    home_games = 0
    away_games = 0

    for index, row in enumerate(rows):

        if (
            row["home_score"] is None
            or row["away_score"] is None
        ):

            continue

        try:

            home_score = float(
                row["home_score"]
            )

            away_score = float(
                row["away_score"]
            )

        except Exception:

            continue

        # ----------------------------------------------------
        # Historical match date
        # ----------------------------------------------------

        match_date = parse_date(
            row["utcdate"]
        )

        # ----------------------------------------------------
        # Opponent
        # ----------------------------------------------------

        if (
            row["home_team_id"]
            == team_id
        ):

            opponent_id = (
                row["away_team_id"]
            )

            scored = home_score
            conceded = away_score

            home_games += 1

        else:

            opponent_id = (
                row["home_team_id"]
            )

            scored = away_score
            conceded = home_score

            away_games += 1

        # ----------------------------------------------------
        # Historical opponent position
        # ----------------------------------------------------

        standing = await get_historical_standing(
            conn,
            opponent_id,
            int(row["season"]),
            str(row["competition"]),
            match_date
        )

        strength = opponent_strength(
            standing
        )

        # ----------------------------------------------------
        # Adjust goals for opponent strength
        # ----------------------------------------------------

        adjusted_scored, adjusted_conceded = (
            strength_adjusted_goals(
                scored,
                conceded,
                strength
            )
        )

        # ----------------------------------------------------
        # Recency
        # ----------------------------------------------------

        weight = decay_weight(
            index
        )

        # ----------------------------------------------------
        # Goals
        # ----------------------------------------------------

        goals_for += (
            adjusted_scored
            * weight
        )

        goals_against += (
            adjusted_conceded
            * weight
        )

        strength_sum += (
            strength
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
        # Total goals
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

    # ========================================================
    # SAFETY
    # ========================================================

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
            "strength_average": 1.0,
            "home_games": 0.0,
            "away_games": 0.0,
        }

    # ========================================================
    # RESULT
    # ========================================================

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

        "strength_average": (
            strength_sum
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
# VENUE FORM
# ============================================================

async def calculate_venue_form(
    conn: asyncpg.Connection,
    rows: List[asyncpg.Record],
    team_id: int,
    venue: str
) -> Optional[Dict[str, float]]:

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

    return await calculate_recent_form(
        conn,
        filtered,
        team_id
    )


# ============================================================
# EXPECTED GOALS
# ============================================================

def calculate_lambdas(
    home_form: Dict[str, float],
    away_form: Dict[str, float],
    home_venue: Optional[Dict[str, float]],
    away_venue: Optional[Dict[str, float]]
) -> Tuple[float, float]:

    # --------------------------------------------------------
    # Overall attack / defense
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
    # Venue information
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
    # Basic expected goals
    # --------------------------------------------------------

    home_lambda = (
        0.65
        * home_attack
        + 0.35
        * away_defense
    )

    away_lambda = (
        0.65
        * away_attack
        + 0.35
        * home_defense
    )

    # --------------------------------------------------------
    # Form momentum
    # --------------------------------------------------------

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
    # Opponent strength adjustment
    #
    # If Chelsea recently played strong opponents, Chelsea's
    # attacking/defensive numbers have already been adjusted.
    #
    # We apply only a small final balancing effect here.
    # --------------------------------------------------------

    home_strength = (
        home_form["strength_average"]
    )

    away_strength = (
        away_form["strength_average"]
    )

    home_lambda *= (
        1.0
        + 0.08
        * (
            away_strength
            - 1.0
        )
    )

    away_lambda *= (
        1.0
        + 0.08
        * (
            home_strength
            - 1.0
        )
    )

    # --------------------------------------------------------
    # Safety
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

    matrix = {}

    total = 0.0

    for home_goals in range(
        MAX_SCORE + 1
    ):

        hp = poisson_pmf(
            home_goals,
            home_lambda
        )

        for away_goals in range(
            MAX_SCORE + 1
        ):

            ap = poisson_pmf(
                away_goals,
                away_lambda
            )

            probability = (
                hp * ap
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
# POISSON RANDOM
# ============================================================

def poisson_random(
    lam: float
) -> int:

    L = exp(-lam)

    k = 0
    p = 1.0

    while p > L:

        k += 1

        p *= random.random()

    return k - 1


# ============================================================
# MONTE CARLO
# ============================================================

def monte_carlo(
    home_lambda: float,
    away_lambda: float,
    sims: int = MC_SIMS
) -> Dict[str, Any]:

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
        # Score
        # ----------------------------------------------------

        scores[
            (
                home_goals,
                away_goals
            )
        ] += 1

        # ----------------------------------------------------
        # Goals
        # ----------------------------------------------------

        home_goals_total += (
            home_goals
        )

        away_goals_total += (
            away_goals
        )

        total_goals = (
            home_goals
            + away_goals
        )

        # ----------------------------------------------------
        # Result
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
# SCORE
# ============================================================

def select_primary_score(
    scores: Counter
) -> Tuple[int, int]:

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
    primary: Tuple[int, int]
) -> Tuple[int, int]:

    if not scores:

        return (
            2,
            1
        )

    ranked = sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    for score, _ in ranked:

        if score != primary:

            return score

    return (
        2,
        1
    )


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

    confidence = (
        1
        - entropy / 1.585
    )

    confidence = max(
        0.50,
        min(
            0.95,
            confidence
        )
    )

    return round(
        confidence,
        3
    )


# ============================================================
# PREDICTION
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
# YES / NO
# ============================================================

def yes_no(
    probability: float
) -> str:

    if probability >= 0.50:

        return "Yes"

    return "No"


# ============================================================
# MAIN PREDICT
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
            f"🔹 V5 Position-Aware predicting "
            f"match {match_id}"
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
        # LAST 5
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

        print(
            f"   Home recent matches: "
            f"{len(home_recent)}"
        )

        print(
            f"   Away recent matches: "
            f"{len(away_recent)}"
        )

        # ====================================================
        # FORM
        # ====================================================

        home_form = (
            await calculate_recent_form(
                conn,
                home_recent,
                home_id
            )
        )

        away_form = (
            await calculate_recent_form(
                conn,
                away_recent,
                away_id
            )
        )

        # ====================================================
        # VENUE
        # ====================================================

        home_venue = (
            await calculate_venue_form(
                conn,
                home_recent,
                home_id,
                "home"
            )
        )

        away_venue = (
            await calculate_venue_form(
                conn,
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

        print(
            f"   Home λ: "
            f"{home_lambda:.3f}"
        )

        print(
            f"   Away λ: "
            f"{away_lambda:.3f}"
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
        # SCORE
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
        # MARKETS
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

            "model_version":
                "V5_POSITION_AWARE_RECENT_5",

            "prediction":
                prediction,

            # ------------------------------------------------
            # SCORE
            # ------------------------------------------------

            "predicted_score":
                f"{primary_score[0]}-{primary_score[1]}",

            "alternative_score":
                f"{alternative_score[0]}-{alternative_score[1]}",

            "score_probability":
                round(
                    primary_score_probability,
                    3
                ),

            "alternative_score_probability":
                round(
                    alternative_score_probability,
                    3
                ),

            # ------------------------------------------------
            # 1X2
            # ------------------------------------------------

            "probabilities": {

                "home_win":
                    round(
                        home_probability,
                        3
                    ),

                "draw":
                    round(
                        draw_probability,
                        3
                    ),

                "away_win":
                    round(
                        away_probability,
                        3
                    ),
            },

            # ------------------------------------------------
            # EXPECTED GOALS
            # ------------------------------------------------

            "expected_goals": {

                "home":
                    round(
                        expected_home,
                        2
                    ),

                "away":
                    round(
                        expected_away,
                        2
                    ),

                "total":
                    round(
                        expected_total,
                        2
                    ),
            },

            # ------------------------------------------------
            # MARKETS
            # ------------------------------------------------

            "markets": {

                "btts":
                    round(
                        btts_probability,
                        3
                    ),

                "btts_prediction":
                    yes_no(
                        btts_probability
                    ),

                "over_1_5":
                    round(
                        over_1_5,
                        3
                    ),

                "over_1_5_prediction":
                    yes_no(
                        over_1_5
                    ),

                "over_2_5":
                    round(
                        over_2_5,
                        3
                    ),

                "over_2_5_prediction":
                    yes_no(
                        over_2_5
                    ),

                "over_3_5":
                    round(
                        over_3_5,
                        3
                    ),

                "over_3_5_prediction":
                    yes_no(
                        over_3_5
                    ),

                "over_4_5":
                    round(
                        over_4_5,
                        3
                    ),

                "over_4_5_prediction":
                    yes_no(
                        over_4_5
                    ),
            },

            # ------------------------------------------------
            # CONFIDENCE
            # ------------------------------------------------

            "confidence":
                confidence,

            # ------------------------------------------------
            # RECENT DATA
            # ------------------------------------------------

            "data": {

                "home_recent_matches":
                    len(home_recent),

                "away_recent_matches":
                    len(away_recent),

                "home_goals_for":
                    round(
                        home_form["goals_for"],
                        2
                    ),

                "home_goals_against":
                    round(
                        home_form["goals_against"],
                        2
                    ),

                "away_goals_for":
                    round(
                        away_form["goals_for"],
                        2
                    ),

                "away_goals_against":
                    round(
                        away_form["goals_against"],
                        2
                    ),

                "home_win_rate":
                    round(
                        home_form["win_rate"],
                        3
                    ),

                "home_draw_rate":
                    round(
                        home_form["draw_rate"],
                        3
                    ),

                "home_loss_rate":
                    round(
                        home_form["loss_rate"],
                        3
                    ),

                "away_win_rate":
                    round(
                        away_form["win_rate"],
                        3
                    ),

                "away_draw_rate":
                    round(
                        away_form["draw_rate"],
                        3
                    ),

                "away_loss_rate":
                    round(
                        away_form["loss_rate"],
                        3
                    ),

                "home_opponent_strength":
                    round(
                        home_form[
                            "strength_average"
                        ],
                        3
                    ),

                "away_opponent_strength":
                    round(
                        away_form[
                            "strength_average"
                        ],
                        3
                    ),
            },

            # ------------------------------------------------
            # INTERNAL MODEL
            # ------------------------------------------------

            "model_values": {

                "home_lambda":
                    round(
                        home_lambda,
                        3
                    ),

                "away_lambda":
                    round(
                        away_lambda,
                        3
                    ),

                "home_attack":
                    round(
                        home_form["attack"],
                        3
                    ),

                "home_defense":
                    round(
                        home_form["defense"],
                        3
                    ),

                "away_attack":
                    round(
                        away_form["attack"],
                        3
                    ),

                "away_defense":
                    round(
                        away_form["defense"],
                        3
                    ),
            },

            # ------------------------------------------------
            # GENERATION TIME
            # ------------------------------------------------

            "generated_at":
                datetime.now(
                    UTC
                ).isoformat(),
        }

    except Exception:

        traceback.print_exc()

        return None


# ============================================================
# COMPATIBILITY WRAPPER
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
            "================================================"
        )

        print(
            "V5 POSITION-AWARE RESULT"
        )

        print(
            "================================================"
        )

        print(
            result
        )

        print(
            "================================================"
        )

    finally:

        await conn.close()


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    import asyncio

    print(
        "🚀 Running V5 Position-Aware Predictor..."
    )

    asyncio.run(
        main_test()
    )
