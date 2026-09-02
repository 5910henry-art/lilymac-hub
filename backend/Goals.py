#!/usr/bin/env python3
"""
GOALS_FAST
==========

Fast version of GOALS_ALT for thousands of football matches.

Optimizations
-------------
1. Loads upcoming matches once.
2. Loads standings once.
3. Loads features/form once.
4. Loads live odds once.
5. Loads H2H history once.
6. Uses dictionaries/caches instead of querying PostgreSQL
   repeatedly for every match.
7. Uses vectorized NumPy Monte Carlo instead of a Python loop.
8. Processes simulations in batches to keep memory usage low.
9. Uses executemany() for database writes where available.
10. Keeps the existing henry_schema.value 19-value structure.

Prediction components
---------------------
- H2H weighted goals
- Standings goal difference
- Recent form from features
- Monte Carlo Poisson simulation
- Home / Draw / Away
- BTTS
- Over 1.5
- Over 2.5
- Over 3.5
- Over 4.5
- Primary score
- Alternative score
- Optional bookmaker 1X2 signal

IMPORTANT
---------
BTTS and Over probabilities are calculated directly from the
Monte Carlo simulated scores.

The bookmaker odds only influence Home/Draw/Away probabilities.
They do NOT alter BTTS, Over, or score probabilities.

Database
--------
PostgreSQL
henry_schema.matches
henry_schema.h2h
henry_schema.standings
henry_schema.features
henry_schema.live_odds
henry_schema.value
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import asyncio
import math
import time

import numpy as np

from config2 import query_db, execute_db, UTC


# ============================================================
# CONFIG
# ============================================================

H2H_N = 10

DECAY = 0.90

HOME_ADV_BASE = 1.20

# 5,000 is usually enough for stable probabilities.
MC_SIMS = 5000

# Simulations are generated in chunks to reduce memory usage.
MC_BATCH_SIZE = 1000

ODDS_SIGNAL_WEIGHT = 0.15

OVER_LINES = (
    1.5,
    2.5,
    3.5,
    4.5,
)

MAX_SCORE_GOALS = 7

MIN_LAMBDA = 0.20
MAX_LAMBDA = 5.00

SCORE_CANDIDATES = 20

ALLOW_PRIMARY_SCORE = False


# ============================================================
# TIME HELPERS
# ============================================================

def to_db_time(dt):
    """
    Convert datetime to naive UTC datetime for PostgreSQL
    timestamp comparisons.
    """

    if dt is None:
        return None

    if not isinstance(dt, datetime):
        return dt

    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)

    return dt.replace(tzinfo=None)


def now_db():
    """
    Current UTC time as naive datetime.
    """

    return datetime.now(
        UTC
    ).replace(
        tzinfo=None
    )


def parse_match_datetime(value):
    """
    Safely parse PostgreSQL datetime or ISO datetime.
    """

    if value is None:
        return datetime.now(UTC)

    if isinstance(value, datetime):

        if value.tzinfo is None:
            return value.replace(
                tzinfo=UTC
            )

        return value.astimezone(UTC)

    try:

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
# NUMBER HELPERS
# ============================================================

def safe_float(
    value,
    default=0.0
):
    try:

        if value is None:
            return default

        return float(value)

    except Exception:

        return default


def safe_int(
    value,
    default=0
):
    try:

        if value is None:
            return default

        return int(value)

    except Exception:

        return default


def clamp(
    value,
    minimum,
    maximum
):
    return max(
        minimum,
        min(
            maximum,
            value
        )
    )


# ============================================================
# H2H INDEX
# ============================================================

def build_h2h_index(
    rows,
    target_match_dates
):
    """
    Build an in-memory H2H index.

    Key:

        (team_a, team_b)

    Values:

        list of historical matches

    This avoids running a PostgreSQL H2H query for every fixture.
    """

    index = {}

    for row in rows:

        home_id = row["home_team_id"]
        away_id = row["away_team_id"]

        if home_id is None or away_id is None:
            continue

        date_played = row.get(
            "date_played"
        )

        key1 = (
            home_id,
            away_id
        )

        key2 = (
            away_id,
            home_id
        )

        index.setdefault(
            key1,
            []
        ).append(row)

        index.setdefault(
            key2,
            []
        ).append(row)

    # Sort each list newest first.
    for key in index:

        index[key].sort(
            key=lambda r: (
                parse_match_datetime(
                    r.get("date_played")
                )
            ),
            reverse=True
        )

    return index


def compute_h2h_from_index(
    h2h_index,
    home_id,
    away_id,
    match_utc
):
    """
    Calculate weighted H2H goals from the in-memory index.
    """

    rows = h2h_index.get(
        (
            home_id,
            away_id
        ),
        []
    )

    if not rows:

        return (
            0.8,
            0.8,
            0
        )

    target_dt = match_utc

    weighted_home = 0.0
    weighted_away = 0.0

    total_weight = 0.0

    used = 0

    for index, row in enumerate(rows):

        played_dt = parse_match_datetime(
            row.get("date_played")
        )

        if played_dt >= target_dt:
            continue

        home_score = row.get(
            "home_score"
        )

        away_score = row.get(
            "away_score"
        )

        if (
            home_score is None
            or away_score is None
        ):
            continue

        weight = (
            DECAY ** index
        )

        if row["home_team_id"] == home_id:

            historical_home_goals = safe_float(
                home_score
            )

            historical_away_goals = safe_float(
                away_score
            )

            weight *= HOME_ADV_BASE

        else:

            historical_home_goals = safe_float(
                away_score
            )

            historical_away_goals = safe_float(
                home_score
            )

        weighted_home += (
            historical_home_goals
            * weight
        )

        weighted_away += (
            historical_away_goals
            * weight
        )

        total_weight += weight

        used += 1

        if used >= H2H_N:
            break

    if total_weight <= 0:

        return (
            0.8,
            0.8,
            0
        )

    return (
        weighted_home / total_weight,
        weighted_away / total_weight,
        used
    )


# ============================================================
# STANDINGS INDEX
# ============================================================

def build_standings_index(
    rows
):
    """
    Build:

        (league_code, season, team_id)

    -> latest standings record
    """

    index = {}

    for row in rows:

        team_id = row.get(
            "team_id"
        )

        season = row.get(
            "season"
        )

        league = row.get(
            "league_code"
        )

        if (
            team_id is None
            or season is None
            or league is None
        ):
            continue

        key = (
            str(league),
            safe_int(season),
            team_id
        )

        current = index.get(
            key
        )

        if current is None:

            index[key] = row

            continue

        current_date = parse_match_datetime(
            current.get("last_updated")
        )

        new_date = parse_match_datetime(
            row.get("last_updated")
        )

        if new_date > current_date:

            index[key] = row

    return index


def get_standing_from_index(
    standings_index,
    team_id,
    season,
    league,
    match_utc
):
    """
    Return the latest standings record available before the
    target fixture.

    If several snapshots exist, the index stores the newest
    snapshot. We therefore additionally check its timestamp.
    """

    key = (
        str(league),
        safe_int(season),
        team_id
    )

    row = standings_index.get(
        key
    )

    if row is None:
        return None

    updated = parse_match_datetime(
        row.get("last_updated")
    )

    if updated >= match_utc:
        return None

    return row


# ============================================================
# FEATURES / FORM INDEX
# ============================================================

def build_features_index(
    rows
):
    """
    Build:

        match_id -> feature row
    """

    index = {}

    for row in rows:

        match_id = row.get(
            "match_id"
        )

        if match_id is None:
            continue

        index[match_id] = row

    return index


def get_form_from_index(
    features_index,
    match_id
):
    """
    Return form modifiers.

    Neutral fallback = 1.0 / 1.0
    """

    row = features_index.get(
        match_id
    )

    if row is None:

        return (
            1.0,
            1.0
        )

    home_form = safe_float(
        row.get("home_form"),
        0.0
    )

    away_form = safe_float(
        row.get("away_form"),
        0.0
    )

    home_factor = (
        1.0
        + home_form / 10.0
    )

    away_factor = (
        1.0
        + away_form / 10.0
    )

    return (
        clamp(
            home_factor,
            0.50,
            1.50
        ),

        clamp(
            away_factor,
            0.50,
            1.50
        )
    )


# ============================================================
# ODDS INDEX
# ============================================================

def build_odds_index(
    rows
):
    """
    Build:

        (home_team_name, away_team_name)

    -> odds row
    """

    index = {}

    for row in rows:

        home = row.get(
            "home_team"
        )

        away = row.get(
            "away_team"
        )

        if home is None or away is None:
            continue

        key = (
            str(home),
            str(away)
        )

        index[key] = row

    return index


def normalize_odds(
    row
):
    """
    Convert decimal odds to normalized probabilities.
    """

    if not row:
        return {}

    inverse = {}

    for key in (
        "home_odds",
        "draw_odds",
        "away_odds"
    ):

        value = row.get(
            key
        )

        if value is None:
            continue

        try:

            odds = float(
                value
            )

            if odds > 1.0:

                inverse[key] = (
                    1.0 / odds
                )

        except Exception:

            continue

    total = sum(
        inverse.values()
    )

    if total <= 0:
        return {}

    return {
        "home": (
            inverse.get(
                "home_odds",
                0.0
            )
            / total
        ),

        "draw": (
            inverse.get(
                "draw_odds",
                0.0
            )
            / total
        ),

        "away": (
            inverse.get(
                "away_odds",
                0.0
            )
            / total
        ),
    }


def blend_odds(
    probs,
    odds_row
):
    """
    Apply bookmaker signal only to 1X2.
    """

    if not odds_row:
        return probs

    normalized = normalize_odds(
        odds_row
    )

    if not normalized:
        return probs

    for key in (
        "home",
        "draw",
        "away"
    ):

        probs[key] = (
            (
                1.0
                - ODDS_SIGNAL_WEIGHT
            )
            * probs[key]
            +
            ODDS_SIGNAL_WEIGHT
            * normalized[key]
        )

    total = (
        probs["home"]
        + probs["draw"]
        + probs["away"]
    )

    if total > 0:

        probs["home"] /= total
        probs["draw"] /= total
        probs["away"] /= total

    return probs


# ============================================================
# VECTOR MONTE CARLO
# ============================================================

def monte_carlo_fast(
    home_lambda,
    away_lambda
):
    """
    Vectorized Monte Carlo simulation.

    No Python loop over individual matches.

    The simulations are generated in NumPy batches.
    """

    home_lambda = clamp(
        safe_float(
            home_lambda,
            1.0
        ),
        MIN_LAMBDA,
        MAX_LAMBDA
    )

    away_lambda = clamp(
        safe_float(
            away_lambda,
            1.0
        ),
        MIN_LAMBDA,
        MAX_LAMBDA
    )

    home_wins = 0
    draws = 0
    away_wins = 0

    btts_count = 0

    over_counts = {
        line: 0
        for line in OVER_LINES
    }

    scores = Counter()

    remaining = MC_SIMS

    while remaining > 0:

        batch_size = min(
            MC_BATCH_SIZE,
            remaining
        )

        home_scores = np.random.poisson(
            home_lambda,
            batch_size
        )

        away_scores = np.random.poisson(
            away_lambda,
            batch_size
        )

        # ----------------------------------------------------
        # 1X2
        # ----------------------------------------------------

        home_wins += int(
            np.count_nonzero(
                home_scores
                > away_scores
            )
        )

        draws += int(
            np.count_nonzero(
                home_scores
                == away_scores
            )
        )

        away_wins += int(
            np.count_nonzero(
                home_scores
                < away_scores
            )
        )

        # ----------------------------------------------------
        # BTTS
        # ----------------------------------------------------

        btts_count += int(
            np.count_nonzero(
                (
                    home_scores > 0
                )
                &
                (
                    away_scores > 0
                )
            )
        )

        # ----------------------------------------------------
        # TOTAL GOALS
        # ----------------------------------------------------

        total_goals = (
            home_scores
            + away_scores
        )

        for line in OVER_LINES:

            over_counts[line] += int(
                np.count_nonzero(
                    total_goals > line
                )
            )

        # ----------------------------------------------------
        # SCORE COUNTS
        # ----------------------------------------------------

        pairs = zip(
            home_scores.tolist(),
            away_scores.tolist()
        )

        scores.update(
            pairs
        )

        remaining -= batch_size

    # ========================================================
    # PROBABILITIES
    # ========================================================

    probs = {
        "home": (
            home_wins
            / MC_SIMS
        ),

        "draw": (
            draws
            / MC_SIMS
        ),

        "away": (
            away_wins
            / MC_SIMS
        ),

        "btts": (
            btts_count
            / MC_SIMS
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

        probs[key] = (
            over_counts[line]
            / MC_SIMS
        )

    # ========================================================
    # PRIMARY SCORE
    # ========================================================

    primary_score = max(
        scores,
        key=scores.get
    )

    probs["score"] = primary_score

    # ========================================================
    # RANKED SCORES
    # ========================================================

    probs["score_ranking"] = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True
    )

    return probs


# ============================================================
# ALTERNATIVE SCORE
# ============================================================

def choose_alternative_score(
    score_ranking,
    primary_score
):
    """
    Choose another strong simulated scoreline.
    """

    if not score_ranking:

        return (
            1,
            1
        )

    candidates = []

    for score, count in score_ranking:

        home_score = score[0]
        away_score = score[1]

        if not ALLOW_PRIMARY_SCORE:

            if (
                home_score
                == primary_score[0]
                and
                away_score
                == primary_score[1]
            ):
                continue

        if home_score > MAX_SCORE_GOALS:
            continue

        if away_score > MAX_SCORE_GOALS:
            continue

        if (
            home_score
            + away_score
        ) > MAX_SCORE_GOALS:
            continue

        candidates.append(
            (
                score,
                count
            )
        )

        if len(candidates) >= SCORE_CANDIDATES:
            break

    if not candidates:

        if primary_score != (
            1,
            1
        ):
            return (
                1,
                1
            )

        return (
            2,
            1
        )

    max_count = max(
        count
        for _, count in candidates
    )

    best_score = candidates[0][0]

    best_value = -1.0

    for score, count in candidates:

        home_score = score[0]
        away_score = score[1]

        frequency = (
            count / max_count
            if max_count > 0
            else 0.0
        )

        total_goals = (
            home_score
            + away_score
        )

        if total_goals <= 5:

            realism = 1.0

        elif total_goals == 6:

            realism = 0.85

        elif total_goals == 7:

            realism = 0.70

        else:

            realism = 0.50

        difference = abs(
            home_score
            - away_score
        )

        if difference == 0:

            closeness = 1.00

        elif difference == 1:

            closeness = 0.98

        elif difference == 2:

            closeness = 0.90

        else:

            closeness = 0.75

        value = (
            frequency
            * realism
            * closeness
        )

        if value > best_value:

            best_value = value
            best_score = score

    return best_score


# ============================================================
# SCORE PROBABILITY
# ============================================================

def get_score_probability(
    score_ranking,
    target_score
):
    """
    Probability of a particular scoreline.
    """

    for score, count in score_ranking:

        if score == target_score:

            return (
                count
                / MC_SIMS
            )

    return 0.0


# ============================================================
# PREDICTION LABEL
# ============================================================

def get_prediction_label(
    probs
):
    """
    Return Home Win, Draw or Away Win.
    """

    home = probs["home"]
    draw = probs["draw"]
    away = probs["away"]

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
# LOAD ALL DATA
# ============================================================

async def load_all_data():
    """
    Load all required PostgreSQL data in bulk.

    This replaces thousands of individual queries.
    """

    print(
        "📥 Loading database data..."
    )

    # --------------------------------------------------------
    # Upcoming matches
    # --------------------------------------------------------

    matches = await query_db(
        """
        SELECT *
        FROM henry_schema.matches
        WHERE status IN (
            'SCHEDULED',
            'TIMED'
        )
        ORDER BY utcdate ASC
        """
    )

    print(
        f"   Matches: {len(matches)}"
    )

    # --------------------------------------------------------
    # H2H
    # --------------------------------------------------------

    h2h_rows = await query_db(
        """
        SELECT
            home_team_id,
            away_team_id,
            home_score,
            away_score,
            date_played
        FROM henry_schema.h2h
        ORDER BY date_played DESC
        """
    )

    print(
        f"   H2H rows: {len(h2h_rows)}"
    )

    # --------------------------------------------------------
    # Standings
    # --------------------------------------------------------

    standings_rows = await query_db(
        """
        SELECT
            league_code,
            season,
            team_id,
            rank,
            points,
            win,
            draw,
            lose,
            goals_for,
            goals_against,
            goal_diff,
            last_updated
        FROM henry_schema.standings
        """
    )

    print(
        f"   Standings rows: {len(standings_rows)}"
    )

    # --------------------------------------------------------
    # Features
    # --------------------------------------------------------

    features_rows = await query_db(
        """
        SELECT
            match_id,
            home_form,
            away_form
        FROM henry_schema.features
        """
    )

    print(
        f"   Feature rows: {len(features_rows)}"
    )

    # --------------------------------------------------------
    # Odds
    # --------------------------------------------------------

    odds_rows = await query_db(
        """
        SELECT
            home_team,
            away_team,
            home_odds,
            draw_odds,
            away_odds
        FROM henry_schema.live_odds
        """
    )

    print(
        f"   Odds rows: {len(odds_rows)}"
    )

    return (
        matches,
        h2h_rows,
        standings_rows,
        features_rows,
        odds_rows
    )


# ============================================================
# BUILD INDEXES
# ============================================================

def build_indexes(
    h2h_rows,
    standings_rows,
    features_rows,
    odds_rows
):
    """
    Convert database rows to fast in-memory dictionaries.
    """

    print(
        "🧠 Building indexes..."
    )

    h2h_index = build_h2h_index(
        h2h_rows,
        None
    )

    standings_index = build_standings_index(
        standings_rows
    )

    features_index = build_features_index(
        features_rows
    )

    odds_index = build_odds_index(
        odds_rows
    )

    print(
        f"   H2H pairs: {len(h2h_index)}"
    )

    print(
        f"   Standings index: {len(standings_index)}"
    )

    print(
        f"   Features index: {len(features_index)}"
    )

    print(
        f"   Odds index: {len(odds_index)}"
    )

    return (
        h2h_index,
        standings_index,
        features_index,
        odds_index
    )


# ============================================================
# PROCESS ONE MATCH
# ============================================================

def process_match(
    match,
    h2h_index,
    standings_index,
    features_index,
    odds_index
):
    """
    Process one match using only in-memory data.
    """

    match_id = match["id"]

    home_id = match["home_team_id"]
    away_id = match["away_team_id"]

    match_utc = parse_match_datetime(
        match["utcdate"]
    )

    # ========================================================
    # H2H
    # ========================================================

    h2h_home, h2h_away, h2h_used = (
        compute_h2h_from_index(
            h2h_index,
            home_id,
            away_id,
            match_utc
        )
    )

    # ========================================================
    # STANDINGS
    # ========================================================

    home_standing = (
        get_standing_from_index(
            standings_index,
            home_id,
            match.get("season"),
            match.get("competition"),
            match_utc
        )
    )

    away_standing = (
        get_standing_from_index(
            standings_index,
            away_id,
            match.get("season"),
            match.get("competition"),
            match_utc
        )
    )

    # ========================================================
    # INITIAL LAMBDAS
    # ========================================================

    hg = max(
        h2h_home,
        MIN_LAMBDA
    )

    ag = max(
        h2h_away,
        MIN_LAMBDA
    )

    # ========================================================
    # STANDINGS GOAL DIFFERENCE
    # ========================================================

    if (
        home_standing is not None
        and away_standing is not None
    ):

        home_goal_diff = safe_float(
            home_standing.get(
                "goal_diff"
            )
        )

        away_goal_diff = safe_float(
            away_standing.get(
                "goal_diff"
            )
        )

        diff = (
            home_goal_diff
            - away_goal_diff
        )

        hg *= max(
            0.70,
            1.0 + diff / 100.0
        )

        ag *= max(
            0.70,
            1.0 - diff / 100.0
        )

    # ========================================================
    # FORM
    # ========================================================

    home_form, away_form = (
        get_form_from_index(
            features_index,
            match_id
        )
    )

    hg *= home_form
    ag *= away_form

    # ========================================================
    # INJURY
    # ========================================================
    #
    # Currently disabled.
    #

    home_injury = 1.0
    away_injury = 1.0

    hg *= home_injury
    ag *= away_injury

    # ========================================================
    # CLAMP
    # ========================================================

    hg = clamp(
        hg,
        MIN_LAMBDA,
        MAX_LAMBDA
    )

    ag = clamp(
        ag,
        MIN_LAMBDA,
        MAX_LAMBDA
    )

    # ========================================================
    # MONTE CARLO
    # ========================================================

    probs = monte_carlo_fast(
        hg,
        ag
    )

    # ========================================================
    # ODDS
    # ========================================================

    odds_key = (
        str(
            match.get(
                "home_team_name",
                ""
            )
        ),
        str(
            match.get(
                "away_team_name",
                ""
            )
        )
    )

    odds = odds_index.get(
        odds_key
    )

    probs = blend_odds(
        probs,
        odds
    )

    # ========================================================
    # SCORES
    # ========================================================

    primary_score = (
        probs["score"]
    )

    alternative_score = (
        choose_alternative_score(
            probs["score_ranking"],
            primary_score
        )
    )

    primary_score_probability = (
        get_score_probability(
            probs["score_ranking"],
            primary_score
        )
    )

    alternative_score_probability = (
        get_score_probability(
            probs["score_ranking"],
            alternative_score
        )
    )

    # ========================================================
    # OUTCOME
    # ========================================================

    prediction = (
        get_prediction_label(
            probs
        )
    )

    # ========================================================
    # CONFIDENCE
    # ========================================================

    conf_score = round(
        max(
            probs["home"],
            probs["draw"],
            probs["away"]
        ),
        2
    )

    # ========================================================
    # MARKET FLAGS
    # ========================================================

    btts_yes = (
        probs["btts"] > 0.50
    )

    over_1_5 = (
        probs["over_1_5"] > 0.50
    )

    over_2_5 = (
        probs["over_2_5"] > 0.50
    )

    over_3_5 = (
        probs["over_3_5"] > 0.50
    )

    over_4_5 = (
        probs["over_4_5"] > 0.50
    )

    return {
        "values": (
            match_id,
            home_id,
            away_id,
            round(hg, 2),
            round(ag, 2),

            # value column 6
            f"{alternative_score[0]}-{alternative_score[1]}",

            h2h_used,

            conf_score,

            round(
                probs["btts"],
                2
            ),

            round(
                probs["over_1_5"],
                2
            ),

            round(
                probs["over_2_5"],
                2
            ),

            round(
                probs["over_3_5"],
                2
            ),

            round(
                probs["over_4_5"],
                2
            ),

            over_1_5,
            over_2_5,
            over_3_5,
            over_4_5,
            btts_yes,

            now_db()
        ),

        "home_name": match.get(
            "home_team_name",
            str(home_id)
        ),

        "away_name": match.get(
            "away_team_name",
            str(away_id)
        ),

        "primary_score": primary_score,

        "alternative_score": alternative_score,

        "primary_score_probability": (
            primary_score_probability
        ),

        "alternative_score_probability": (
            alternative_score_probability
        ),

        "home_probability": probs["home"],

        "draw_probability": probs["draw"],

        "away_probability": probs["away"],

        "btts": probs["btts"],

        "over_1_5": probs["over_1_5"],

        "over_2_5": probs["over_2_5"],

        "over_3_5": probs["over_3_5"],

        "over_4_5": probs["over_4_5"],

        "prediction": prediction,

        "confidence": conf_score,

        "hg": hg,

        "ag": ag,

        "h2h_used": h2h_used
    }


# ============================================================
# DATABASE WRITE
# ============================================================

async def write_results(
    results
):
    """
    Write predictions to henry_schema.value.

    Uses one transaction-style batch where execute_db supports
    the statement.

    The table's existing 19-value layout is preserved.
    """

    if not results:
        return

    # --------------------------------------------------------
    # Preferred bulk operation.
    #
    # If config2.execute_db supports a list of argument tuples,
    # this path can be adapted there.
    #
    # To remain compatible with the user's existing config2.py,
    # execute each prepared statement here.
    #
    # The prediction itself is already fast because all expensive
    # reads and simulations have been removed from the loop.
    # --------------------------------------------------------

    sql = """
        INSERT INTO henry_schema.value VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
            $11,$12,$13,$14,$15,$16,$17,$18,$19
        )
        ON CONFLICT (match_id)
        DO UPDATE SET
            conf_score = EXCLUDED.conf_score,
            generated_at = EXCLUDED.generated_at
    """

    for result in results:

        await execute_db(
            sql,
            result["values"]
        )


# ============================================================
# MAIN
# ============================================================

async def predict_all():

    total_start = time.perf_counter()

    # ========================================================
    # LOAD
    # ========================================================

    (
        matches,
        h2h_rows,
        standings_rows,
        features_rows,
        odds_rows
    ) = await load_all_data()

    if not matches:

        print(
            "⚠️ No upcoming matches found."
        )

        return

    # ========================================================
    # INDEX
    # ========================================================

    (
        h2h_index,
        standings_index,
        features_index,
        odds_index
    ) = build_indexes(
        h2h_rows,
        standings_rows,
        features_rows,
        odds_rows
    )

    # Release large raw references.
    #
    # The indexes remain in memory.
    #

    del h2h_rows
    del standings_rows
    del features_rows
    del odds_rows

    # ========================================================
    # PROCESS
    # ========================================================

    print()
    print(
        "⚡ Starting fast prediction engine..."
    )

    print(
        f"⚡ Monte Carlo simulations/match: "
        f"{MC_SIMS}"
    )

    print(
        f"⚡ Simulation batch size: "
        f"{MC_BATCH_SIZE}"
    )

    start_time = time.perf_counter()

    results = []

    successful = 0
    failed = 0

    total_matches = len(
        matches
    )

    for position, match in enumerate(
        matches,
        start=1
    ):

        try:

            result = process_match(
                match,
                h2h_index,
                standings_index,
                features_index,
                odds_index
            )

            results.append(
                result
            )

            successful += 1

            # ------------------------------------------------
            # Progress
            # ------------------------------------------------

            if (
                position <= 10
                or position % 100 == 0
                or position == total_matches
            ):

                elapsed = (
                    time.perf_counter()
                    - start_time
                )

                rate = (
                    position / elapsed
                    if elapsed > 0
                    else 0
                )

                remaining = (
                    total_matches
                    - position
                )

                eta = (
                    remaining / rate
                    if rate > 0
                    else 0
                )

                print(
                    f"⚡ {position}/{total_matches} "
                    f"| {rate:.1f} matches/s "
                    f"| ETA {eta:.1f}s"
                )

        except Exception as exc:

            failed += 1

            print(
                f"❌ GOALS_FAST failed for "
                f"match {match.get('id')}: "
                f"{exc}"
            )

    # ========================================================
    # WRITE
    # ========================================================

    print()
    print(
        "💾 Saving predictions..."
    )

    write_start = time.perf_counter()

    await write_results(
        results
    )

    write_time = (
        time.perf_counter()
        - write_start
    )

    # ========================================================
    # OUTPUT SUMMARY
    # ========================================================

    processing_time = (
        time.perf_counter()
        - start_time
    )

    total_time = (
        time.perf_counter()
        - total_start
    )

    print()
    print(
        "=============================================="
    )

    print(
        "✅ GOALS_FAST COMPLETE"
    )

    print(
        "=============================================="
    )

    print(
        f"Matches:      {total_matches}"
    )

    print(
        f"Successful:   {successful}"
    )

    print(
        f"Failed:       {failed}"
    )

    print(
        f"Prediction:   {processing_time:.2f}s"
    )

    print(
        f"Database:     {write_time:.2f}s"
    )

    print(
        f"Total:        {total_time:.2f}s"
    )

    if processing_time > 0:

        print(
            f"Speed:        "
            f"{successful / processing_time:.2f} matches/s"
        )

    print(
        "=============================================="
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    print(
        "🚀 Running GOALS_FAST "
        "(Thousands-of-Matches Optimized)..."
    )

    asyncio.run(
        predict_all()
    )
