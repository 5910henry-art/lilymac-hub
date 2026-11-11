#!/usr/bin/env python3
"""
V4B_CORRECTED — Time-safe football predictor

Core:
- PostgreSQL + asyncpg
- Hard-coded matches.competition
- Competition-specific historical goal averages
- Competition-specific recent form
- Proper chronological ELO using both teams' ratings
- No future-match leakage
- Time-decayed H2H
- Exact Poisson score grid
- Mild form momentum adjustment
- Stable entropy confidence
- Small bounded caches
- Preserves existing predict_home_away() interface

Public interface:

    await predict_home_away(
        conn,
        match_id,
        home_id=None,
        away_id=None,
    )
"""

from datetime import datetime, timezone
from math import exp, factorial, log2
import traceback
from typing import Optional, Tuple, List, Dict, Any

import asyncpg

from config2 import DATABASE_URL


UTC = timezone.utc


# ============================================================
# CONFIG
# ============================================================

H2H_N = 8
FORM_MATCHES = 15

# Minimum completed historical matches required before
# trusting competition-specific goal averages.
MIN_COMPETITION_HISTORY = 20

# Exponential decay half-life for recent matches.
# 30 days means a result 30 days old has ~50% weight.
FORM_HALF_LIFE_DAYS = 30.0

# H2H uses a slower decay because H2H samples are sparse.
H2H_HALF_LIFE_DAYS = 365.0

MAX_GOALS = 8

HOME_ADV = 1.08
MIN_LAMBDA = 0.25
MAX_LAMBDA = 4.50

# Form momentum is deliberately mild.
FORM_LAMBDA_WEIGHT = 0.15

# H2H influence is deliberately mild.
H2H_LAMBDA_WEIGHT = 0.10

MIN_CONFIDENCE = 0.55

# Proper chronological ELO.
ELO_K = 20.0
INITIAL_ELO = 1500.0

# Keep ELO bounded so a bad database/history cannot create
# absurd goal-rate multipliers.
MIN_ELO_FACTOR = 0.85
MAX_ELO_FACTOR = 1.15

# Number of historical matches used to build the ELO snapshot.
# None = use all historical finished matches.
ELO_LOOKBACK = None


# ============================================================
# CACHES
# ============================================================

_recent_cache: Dict[
    Tuple[int, str, Optional[str]],
    List[asyncpg.Record]
] = {}

_h2h_cache: Dict[
    Tuple[int, int, str],
    Tuple[float, float]
] = {}

_competition_avg_cache: Dict[
    Tuple[str, Optional[str]],
    Tuple[float, float]
] = {}

_elo_snapshot_cache: Dict[
    str,
    Dict[int, float]
] = {}


# ============================================================
# DATE / NUMERIC UTILS
# ============================================================

def parse_date(d: Any) -> datetime:
    """
    Safely convert PostgreSQL datetime/string into UTC datetime.
    """
    try:
        if isinstance(d, datetime):
            if d.tzinfo is None:
                return d.replace(tzinfo=UTC)

            return d.astimezone(UTC)

        return datetime.fromisoformat(
            str(d).replace("Z", "+00:00")
        ).astimezone(UTC)

    except Exception:
        return datetime.now(UTC)


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(
        minimum,
        min(maximum, value),
    )


def decay_weight(
    match_date: datetime,
    ref_date: datetime,
    half_life_days: float,
) -> float:
    """
    Exponential time decay.

    At exactly one half-life:
        weight = 0.5
    """

    days = max(
        0.0,
        (
            ref_date - match_date
        ).total_seconds() / 86400.0,
    )

    if half_life_days <= 0:
        return 1.0

    return 0.5 ** (
        days / half_life_days
    )


def poisson_pmf(
    k: int,
    lam: float,
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
# PROBABILITY / CONFIDENCE
# ============================================================

def confidence(
    h: float,
    d: float,
    a: float,
) -> float:
    """
    Entropy-based confidence.

    Higher concentration of probability
    -> higher confidence.
    """

    probabilities = (
        h,
        d,
        a,
    )

    entropy = -sum(
        p * log2(p)
        for p in probabilities
        if p > 0
    )

    max_entropy = log2(3)

    value = 1.0 - (
        entropy / max_entropy
    )

    return round(
        clamp(
            value,
            MIN_CONFIDENCE,
            0.95,
        ),
        3,
    )


def fast_poisson_probs(
    lh: float,
    la: float,
):
    """
    Exact independent-Poisson score matrix.

    Calculates probabilities for:
        0-0 through MAX_GOALS-MAX_GOALS

    Then renormalizes the 1X2 probabilities so that:

        home + draw + away = 1
    """

    lh = clamp(
        lh,
        MIN_LAMBDA,
        MAX_LAMBDA,
    )

    la = clamp(
        la,
        MIN_LAMBDA,
        MAX_LAMBDA,
    )

    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    expected_home = 0.0
    expected_away = 0.0

    home_probs = [
        poisson_pmf(h, lh)
        for h in range(MAX_GOALS + 1)
    ]

    away_probs = [
        poisson_pmf(a, la)
        for a in range(MAX_GOALS + 1)
    ]

    for h in range(MAX_GOALS + 1):

        for a in range(MAX_GOALS + 1):

            p = (
                home_probs[h]
                * away_probs[a]
            )

            expected_home += h * p
            expected_away += a * p

            if h > a:
                home_win += p

            elif h < a:
                away_win += p

            else:
                draw += p

    total = (
        home_win
        + draw
        + away_win
    )

    if total <= 0:

        return (
            1 / 3,
            1 / 3,
            1 / 3,
            lh,
            la,
        )

    home_win /= total
    draw /= total
    away_win /= total

    return (
        home_win,
        draw,
        away_win,
        expected_home,
        expected_away,
    )


# ============================================================
# DATABASE HELPERS
# ============================================================

async def fetch_match(
    conn: asyncpg.Connection,
    match_id: int,
):
    """
    Fetch the target fixture.

    competition is deliberately hard-coded because the
    matches table schema is known.
    """

    return await conn.fetchrow(
        """
        SELECT
            utcDate,
            home_team_id,
            away_team_id,
            competition
        FROM matches
        WHERE id = $1
        LIMIT 1
        """,
        match_id,
    )


async def fetch_competition(
    conn: asyncpg.Connection,
    match_id: int,
) -> Optional[str]:
    """
    Retrieve the competition identifier for a fixture.

    This helper is retained for callers that need to retrieve
    competition independently of fetch_match().
    """

    row = await conn.fetchrow(
        """
        SELECT competition
        FROM matches
        WHERE id = $1
        LIMIT 1
        """,
        match_id,
    )

    if not row or row["competition"] is None:
        return None

    return str(
        row["competition"]
    )


# ============================================================
# COMPETITION GOAL AVERAGES
# ============================================================

async def fetch_competition_avgs(
    conn: asyncpg.Connection,
    ref_date: datetime,
    competition: Optional[str],
) -> Tuple[float, float]:
    """
    Get historical home/away scoring averages using ONLY
    matches before the prediction fixture.

    When enough historical data exists, averages are restricted
    to the same competition.

    If the competition has insufficient historical data, global
    historical averages are used instead.
    """

    cache_key = (
        ref_date.isoformat(),
        competition,
    )

    cached = _competition_avg_cache.get(
        cache_key
    )

    if cached is not None:
        return cached

    row = None

    # --------------------------------------------------------
    # COMPETITION-SPECIFIC AVERAGES
    # --------------------------------------------------------

    if competition is not None:

        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS match_count,
                AVG(home_score) AS h_avg,
                AVG(away_score) AS a_avg
            FROM matches
            WHERE utcDate < $1
              AND status = 'FINISHED'
              AND competition = $2
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
            """,
            ref_date,
            competition,
        )

        if not (
            row
            and row["match_count"] is not None
            and int(row["match_count"])
                >= MIN_COMPETITION_HISTORY
            and row["h_avg"] is not None
            and row["a_avg"] is not None
        ):
            row = None

    # --------------------------------------------------------
    # GLOBAL FALLBACK
    # --------------------------------------------------------

    if row is None:

        row = await conn.fetchrow(
            """
            SELECT
                AVG(home_score) AS h_avg,
                AVG(away_score) AS a_avg
            FROM matches
            WHERE utcDate < $1
              AND status = 'FINISHED'
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
            """,
            ref_date,
        )

    # --------------------------------------------------------
    # DEFAULT FALLBACK
    # --------------------------------------------------------

    if (
        row
        and row["h_avg"] is not None
        and row["a_avg"] is not None
    ):

        result = (
            float(row["h_avg"]),
            float(row["a_avg"]),
        )

    else:

        result = (
            1.40,
            1.10,
        )

    result = (
        clamp(
            result[0],
            0.60,
            2.50,
        ),
        clamp(
            result[1],
            0.60,
            2.50,
        ),
    )

    _competition_avg_cache[
        cache_key
    ] = result

    return result


# ============================================================
# RECENT FORM
# ============================================================

async def fetch_recent(
    conn: asyncpg.Connection,
    team_id: int,
    ref_date: datetime,
    competition: Optional[str],
) -> List[asyncpg.Record]:
    """
    Fetch recent completed matches for a team.

    When competition is available, only matches from that
    competition are considered.

    No match at or after ref_date can enter the sample.
    """

    key = (
        team_id,
        ref_date.isoformat(),
        competition,
    )

    if key in _recent_cache:
        return _recent_cache[key]

    # --------------------------------------------------------
    # COMPETITION-SPECIFIC FORM
    # --------------------------------------------------------

    if competition is not None:

        rows = await conn.fetch(
            f"""
            SELECT
                utcDate,
                home_team_id,
                away_team_id,
                home_score,
                away_score
            FROM matches
            WHERE utcDate < $1
              AND status = 'FINISHED'
              AND competition = $3
              AND (
                    home_team_id = $2
                    OR away_team_id = $2
              )
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
            ORDER BY utcDate DESC
            LIMIT {FORM_MATCHES}
            """,
            ref_date,
            team_id,
            competition,
        )

    # --------------------------------------------------------
    # GLOBAL FALLBACK
    # --------------------------------------------------------

    else:

        rows = await conn.fetch(
            f"""
            SELECT
                utcDate,
                home_team_id,
                away_team_id,
                home_score,
                away_score
            FROM matches
            WHERE utcDate < $1
              AND status = 'FINISHED'
              AND (
                    home_team_id = $2
                    OR away_team_id = $2
              )
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
            ORDER BY utcDate DESC
            LIMIT {FORM_MATCHES}
            """,
            ref_date,
            team_id,
        )

    _recent_cache[key] = rows

    return rows


def attack_defense(
    matches: List[asyncpg.Record],
    team_id: int,
    ref_date: datetime,
    competition_home_avg: float,
    competition_away_avg: float,
) -> Tuple[float, float]:
    """
    Calculate weighted attack/defence strengths.

    Attack:
        goals scored / relevant competition scoring baseline

    Defence:
        goals conceded / relevant competition scoring baseline

    Returns relative strengths rather than raw goals.
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
            ref_date,
            FORM_HALF_LIFE_DAYS,
        )

        if team_id == match["home_team_id"]:

            scored_goals = float(
                match["home_score"]
            )

            conceded_goals = float(
                match["away_score"]
            )

            scoring_baseline = (
                competition_home_avg
            )

        else:

            scored_goals = float(
                match["away_score"]
            )

            conceded_goals = float(
                match["home_score"]
            )

            scoring_baseline = (
                competition_away_avg
            )

        scored += (
            scored_goals
            * weight
        )

        conceded += (
            conceded_goals
            * weight
        )

        weight_sum += weight

    if weight_sum <= 0:
        return 1.0, 1.0

    avg_scored = (
        scored / weight_sum
    )

    avg_conceded = (
        conceded / weight_sum
    )

    attack_strength = (
        avg_scored
        / max(scoring_baseline, 0.50)
    )

    defence_strength = (
        avg_conceded
        / max(scoring_baseline, 0.50)
    )

    return (
        clamp(
            attack_strength,
            0.45,
            2.20,
        ),
        clamp(
            defence_strength,
            0.45,
            2.20,
        ),
    )


def form_momentum(
    matches: List[asyncpg.Record],
    team_id: int,
    ref_date: datetime,
) -> float:
    """
    Mild form momentum.

    Combines:
      - weighted points per game
      - weighted goal difference

    Output is deliberately bounded around 1.0.
    """

    points = 0.0
    goal_diff = 0.0
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
            ref_date,
            FORM_HALF_LIFE_DAYS,
        )

        if team_id == match["home_team_id"]:

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

        if goals_for > goals_against:
            match_points = 3.0

        elif goals_for == goals_against:
            match_points = 1.0

        else:
            match_points = 0.0

        points += (
            match_points
            * weight
        )

        gd = clamp(
            goals_for - goals_against,
            -4.0,
            4.0,
        )

        goal_diff += (
            gd * weight
        )

        weight_sum += weight

    if weight_sum <= 0:
        return 1.0

    ppg = (
        points / weight_sum
    )

    avg_gd = (
        goal_diff / weight_sum
    )

    # PPG around 1.5 is neutral.
    point_component = (
        ppg - 1.5
    ) / 1.5

    # Goal difference around 0 is neutral.
    gd_component = (
        avg_gd / 3.0
    )

    momentum = (
        1.0
        + 0.08 * point_component
        + 0.07 * gd_component
    )

    return clamp(
        momentum,
        0.90,
        1.10,
    )


# ============================================================
# H2H
# ============================================================

async def h2h_modifier(
    conn: asyncpg.Connection,
    home_id: int,
    away_id: int,
    ref_date: datetime,
) -> Tuple[float, float]:

    key = (
        home_id,
        away_id,
        ref_date.isoformat(),
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
            utcDate
        FROM matches
        WHERE utcDate < $1
          AND status = 'FINISHED'
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
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
        ORDER BY utcDate DESC
        LIMIT {H2H_N}
        """,
        ref_date,
        home_id,
        away_id,
    )

    if not rows:

        result = (
            1.0,
            1.0,
        )

        _h2h_cache[key] = result

        return result

    home_signal = 0.0
    away_signal = 0.0
    total_weight = 0.0

    for row in rows:

        match_date = parse_date(
            row["utcdate"]
        )

        weight = decay_weight(
            match_date,
            ref_date,
            H2H_HALF_LIFE_DAYS,
        )

        hs = float(
            row["home_score"]
        )

        aws = float(
            row["away_score"]
        )

        if row["home_team_id"] == home_id:

            current_home_gd = (
                hs - aws
            )

        else:

            current_home_gd = (
                aws - hs
            )

        if current_home_gd > 0:
            result_signal = 1.0

        elif current_home_gd < 0:
            result_signal = -1.0

        else:
            result_signal = 0.0

        gd_signal = clamp(
            current_home_gd / 3.0,
            -1.0,
            1.0,
        )

        signal = (
            0.70 * result_signal
            + 0.30 * gd_signal
        )

        home_signal += (
            signal * weight
        )

        away_signal -= (
            signal * weight
        )

        total_weight += weight

    if total_weight <= 0:

        result = (
            1.0,
            1.0,
        )

        _h2h_cache[key] = result

        return result

    home_signal /= total_weight
    away_signal /= total_weight

    home_modifier = (
        1.0
        + H2H_LAMBDA_WEIGHT
        * home_signal
    )

    away_modifier = (
        1.0
        + H2H_LAMBDA_WEIGHT
        * away_signal
    )

    result = (
        clamp(
            home_modifier,
            0.92,
            1.08,
        ),
        clamp(
            away_modifier,
            0.92,
            1.08,
        ),
    )

    _h2h_cache[key] = result

    return result


# ============================================================
# PROPER CHRONOLOGICAL ELO
# ============================================================

def elo_update(
    home_elo: float,
    away_elo: float,
    home_score: int,
    away_score: int,
) -> Tuple[float, float]:

    expected_home = 1.0 / (
        1.0
        + 10.0 ** (
            (
                away_elo
                - home_elo
            ) / 400.0
        )
    )

    expected_away = (
        1.0
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

    new_home = (
        home_elo
        + ELO_K
        * (
            actual_home
            - expected_home
        )
    )

    new_away = (
        away_elo
        + ELO_K
        * (
            actual_away
            - expected_away
        )
    )

    return (
        new_home,
        new_away,
    )


async def compute_elo_snapshot(
    conn: asyncpg.Connection,
    ref_date: datetime,
) -> Dict[int, float]:
    """
    Build a genuine chronological ELO table.

    IMPORTANT:
        Only matches strictly before ref_date are included.

    Every opponent retains its own evolving rating.
    """

    cache_key = (
        ref_date.isoformat()
    )

    cached = _elo_snapshot_cache.get(
        cache_key
    )

    if cached is not None:
        return cached

    if ELO_LOOKBACK is None:

        rows = await conn.fetch(
            """
            SELECT
                home_team_id,
                away_team_id,
                home_score,
                away_score,
                utcDate
            FROM matches
            WHERE utcDate < $1
              AND status = 'FINISHED'
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
            ORDER BY utcDate ASC
            """,
            ref_date,
        )

    else:

        rows = await conn.fetch(
            f"""
            SELECT
                home_team_id,
                away_team_id,
                home_score,
                away_score,
                utcDate
            FROM matches
            WHERE utcDate < $1
              AND status = 'FINISHED'
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
            ORDER BY utcDate DESC
            LIMIT {ELO_LOOKBACK}
            """,
            ref_date,
        )

        rows = list(
            reversed(rows)
        )

    ratings: Dict[int, float] = {}

    for row in rows:

        home_id = row[
            "home_team_id"
        ]

        away_id = row[
            "away_team_id"
        ]

        if (
            home_id is None
            or away_id is None
        ):
            continue

        home_elo = ratings.get(
            home_id,
            INITIAL_ELO,
        )

        away_elo = ratings.get(
            away_id,
            INITIAL_ELO,
        )

        new_home, new_away = (
            elo_update(
                home_elo,
                away_elo,
                int(row["home_score"]),
                int(row["away_score"]),
            )
        )

        ratings[home_id] = new_home
        ratings[away_id] = new_away

    _elo_snapshot_cache[
        cache_key
    ] = ratings

    return ratings


async def compute_elo(
    conn: asyncpg.Connection,
    team_id: int,
    ref_date: datetime,
) -> float:

    ratings = await compute_elo_snapshot(
        conn,
        ref_date,
    )

    return ratings.get(
        team_id,
        INITIAL_ELO,
    )


def elo_lambda_factor(
    home_elo: float,
    away_elo: float,
) -> Tuple[float, float]:
    """
    Convert ELO difference into a small goal-rate adjustment.

    Adjustment is deliberately bounded so ELO cannot overwhelm
    the Poisson/form model.
    """

    diff = (
        home_elo
        - away_elo
    ) / 400.0

    strength_ratio = (
        10.0 ** diff
    )

    home_factor = (
        strength_ratio ** 0.20
    )

    away_factor = (
        strength_ratio ** -0.20
    )

    home_factor = clamp(
        home_factor,
        MIN_ELO_FACTOR,
        MAX_ELO_FACTOR,
    )

    away_factor = clamp(
        away_factor,
        MIN_ELO_FACTOR,
        MAX_ELO_FACTOR,
    )

    return (
        home_factor,
        away_factor,
    )


# ============================================================
# CACHE CONTROL
# ============================================================

def clear_caches():
    """
    Clear all in-process prediction caches.

    Useful after importing new historical data or changing
    database contents.
    """

    _recent_cache.clear()
    _h2h_cache.clear()
    _competition_avg_cache.clear()
    _elo_snapshot_cache.clear()


# ============================================================
# PREDICT
# ============================================================

async def predict(
    conn: asyncpg.Connection,
    match_id: int,
    home_id: Optional[int] = None,
    away_id: Optional[int] = None,
    **kwargs,
) -> Optional[Dict[str, Any]]:

    try:

        # ----------------------------------------------------
        # FIXTURE
        # ----------------------------------------------------

        row = await fetch_match(
            conn,
            match_id,
        )

        if not row:
            return None

        ref_date = parse_date(
            row["utcdate"]
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

        if not home_id or not away_id:
            return None

        # ----------------------------------------------------
        # COMPETITION
        # ----------------------------------------------------

        competition = row[
            "competition"
        ]

        if competition is not None:
            competition = str(
                competition
            )

        competition_home_avg, competition_away_avg = (
            await fetch_competition_avgs(
                conn,
                ref_date,
                competition,
            )
        )

        # ----------------------------------------------------
        # RECENT FORM
        # ----------------------------------------------------

        home_recent = await fetch_recent(
            conn,
            home_id,
            ref_date,
            competition,
        )

        away_recent = await fetch_recent(
            conn,
            away_id,
            ref_date,
            competition,
        )

        home_attack, home_defence = (
            attack_defense(
                home_recent,
                home_id,
                ref_date,
                competition_home_avg,
                competition_away_avg,
            )
        )

        away_attack, away_defence = (
            attack_defense(
                away_recent,
                away_id,
                ref_date,
                competition_home_avg,
                competition_away_avg,
            )
        )

        # ----------------------------------------------------
        # BASE POISSON LAMBDAS
        # ----------------------------------------------------

        # Home attack vs away defence.
        lh = (
            competition_home_avg
            * home_attack
            * away_defence
            * HOME_ADV
        )

        # Away attack vs home defence.
        la = (
            competition_away_avg
            * away_attack
            * home_defence
        )

        # ----------------------------------------------------
        # FORM MOMENTUM
        # ----------------------------------------------------

        home_form = form_momentum(
            home_recent,
            home_id,
            ref_date,
        )

        away_form = form_momentum(
            away_recent,
            away_id,
            ref_date,
        )

        # Blend form rather than multiplying the full raw factor.
        # This prevents recent form from overwhelming the model.

        lh *= (
            (1.0 - FORM_LAMBDA_WEIGHT)
            + FORM_LAMBDA_WEIGHT
            * home_form
        )

        la *= (
            (1.0 - FORM_LAMBDA_WEIGHT)
            + FORM_LAMBDA_WEIGHT
            * away_form
        )

        # ----------------------------------------------------
        # H2H
        # ----------------------------------------------------

        h2h_home, h2h_away = (
            await h2h_modifier(
                conn,
                home_id,
                away_id,
                ref_date,
            )
        )

        lh *= h2h_home
        la *= h2h_away

        # ----------------------------------------------------
        # ELO
        # ----------------------------------------------------

        home_elo = await compute_elo(
            conn,
            home_id,
            ref_date,
        )

        away_elo = await compute_elo(
            conn,
            away_id,
            ref_date,
        )

        elo_home_factor, elo_away_factor = (
            elo_lambda_factor(
                home_elo,
                away_elo,
            )
        )

        lh *= elo_home_factor
        la *= elo_away_factor

        # ----------------------------------------------------
        # FINAL SAFETY BOUNDS
        # ----------------------------------------------------

        lh = clamp(
            lh,
            MIN_LAMBDA,
            MAX_LAMBDA,
        )

        la = clamp(
            la,
            MIN_LAMBDA,
            MAX_LAMBDA,
        )

        # ----------------------------------------------------
        # EXACT POISSON
        # ----------------------------------------------------

        (
            ph,
            pd,
            pa,
            exp_home,
            exp_away,
        ) = fast_poisson_probs(
            lh,
            la,
        )

        conf = confidence(
            ph,
            pd,
            pa,
        )

        # ----------------------------------------------------
        # LABEL
        # ----------------------------------------------------

        if ph > max(
            pd,
            pa,
        ):

            label = "Home Win"

        elif pa > max(
            ph,
            pd,
        ):

            label = "Away Win"

        else:

            label = "Draw"

        score_prediction = (
            f"{round(exp_home)}-"
            f"{round(exp_away)}"
        )

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        return {
            "prediction": label,

            "predicted_score": (
                score_prediction
            ),

            "probabilities": {
                "home_win": round(
                    ph,
                    3,
                ),
                "draw": round(
                    pd,
                    3,
                ),
                "away_win": round(
                    pa,
                    3,
                ),
            },

            "expected_goals": {
                "home": round(
                    exp_home,
                    2,
                ),
                "away": round(
                    exp_away,
                    2,
                ),
            },

            "confidence": conf,

            "model_version": (
                "V4B_CORRECTED_"
                "COMPETITION_TIMEAWARE_"
                "POISSON_ELO"
            ),

            "model_details": {

                "competition": (
                    competition
                ),

                "competition_home_avg": round(
                    competition_home_avg,
                    3,
                ),

                "competition_away_avg": round(
                    competition_away_avg,
                    3,
                ),

                "home_attack": round(
                    home_attack,
                    3,
                ),

                "home_defence": round(
                    home_defence,
                    3,
                ),

                "away_attack": round(
                    away_attack,
                    3,
                ),

                "away_defence": round(
                    away_defence,
                    3,
                ),

                "home_form": round(
                    home_form,
                    3,
                ),

                "away_form": round(
                    away_form,
                    3,
                ),

                "home_elo": round(
                    home_elo,
                    1,
                ),

                "away_elo": round(
                    away_elo,
                    1,
                ),

                "lambda_home": round(
                    lh,
                    3,
                ),

                "lambda_away": round(
                    la,
                    3,
                ),
            },

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
# EXISTING WRAPPER — DO NOT CHANGE
# ============================================================

async def predict_home_away(
    conn: asyncpg.Connection,
    match_id: int,
    home_id: Optional[int] = None,
    away_id: Optional[int] = None,
    **kwargs,
):
    return await predict(
        conn,
        match_id,
        home_id,
        away_id,
        **kwargs,
    )


# ============================================================
# CONNECTION TEST
# ============================================================

async def main_test():

    conn = await asyncpg.connect(
        DATABASE_URL
    )

    try:

        result = await predict(
            conn,
            match_id=1,
        )

        print(result)

    finally:

        await conn.close()


if __name__ == "__main__":

    import asyncio

    asyncio.run(
        main_test()
    )
