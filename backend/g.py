# Goals_FAST_V2.py

import asyncio
import math
import time
import logging
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

from config2 import query_db, execute_db


# ============================================================
# CONFIG
# ============================================================

SCHEMA = "henry_schema"

MATCHES_TABLE = f"{SCHEMA}.matches"
H2H_TABLE = f"{SCHEMA}.h2h"
STANDINGS_TABLE = f"{SCHEMA}.standings"
HISTORICAL_STANDINGS_TABLE = f"{SCHEMA}.historical_standings"
ODDS_TABLE = f"{SCHEMA}.live_odds"
VALUE_TABLE = f"{SCHEMA}.value"

FORM_MATCHES = 5
H2H_MATCHES = 10

FORM_DECAY = 0.90
H2H_DECAY = 0.90

MIN_LAMBDA = 0.15
MAX_LAMBDA = 5.00

MAX_GOALS = 10

FORM_WEIGHT = 0.36
POSITION_WEIGHT = 0.12
H2H_WEIGHT = 0.12
HOME_AWAY_WEIGHT = 0.18

ODDS_WEIGHT = 0.15

SAVE_CHUNK = 100
BATCH_SIZE = 500
PROGRESS_EVERY = 100


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger("GOALS_FAST_V2")


# ============================================================
# GENERIC HELPERS
# ============================================================

def first_value(row, *names, default=None):
    if row is None:
        return default

    for name in names:
        try:
            if name in row:
                value = row[name]
                if value is not None:
                    return value
        except Exception:
            pass

        try:
            value = row.get(name)
            if value is not None:
                return value
        except Exception:
            pass

    return default


def as_int(value, default=None):
    if value is None:
        return default

    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return default


def as_float(value, default=0.0):
    if value is None:
        return default

    try:
        return float(value)
    except Exception:
        return default


def normalize_team_id(value):
    if value is None:
        return None

    try:
        return int(value)
    except Exception:
        return str(value)


def parse_datetime(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()

        if not text:
            return None

        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"

            dt = datetime.fromisoformat(text)

        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def get_match_date(row):
    return parse_datetime(
        first_value(
            row,
            "utcdate",
            "utcDate",
            "date",
            "match_date",
            "start_time",
            "scheduled",
            default=None
        )
    )


def get_match_id(row):
    return first_value(
        row,
        "id",
        "match_id",
        "fixture_id",
        default=None
    )


def get_home_id(row):
    return normalize_team_id(
        first_value(
            row,
            "home_team_id",
            "home_id",
            "hometeamid",
            "homeTeamId",
            default=None
        )
    )


def get_away_id(row):
    return normalize_team_id(
        first_value(
            row,
            "away_team_id",
            "away_id",
            "awayteamid",
            "awayTeamId",
            default=None
        )
    )


def get_home_name(row):
    return str(
        first_value(
            row,
            "home_team_name",
            "home_name",
            "home",
            "homeTeam",
            default="Home"
        )
    )


def get_away_name(row):
    return str(
        first_value(
            row,
            "away_team_name",
            "away_name",
            "away",
            "awayTeam",
            default="Away"
        )
    )


def get_home_score(row):
    return first_value(
        row,
        "home_score",
        "home_goals",
        "homeScore",
        "score_home",
        default=None
    )


def get_away_score(row):
    return first_value(
        row,
        "away_score",
        "away_goals",
        "awayScore",
        "score_away",
        default=None
    )


def get_league(row):
    return first_value(
        row,
        "league_code",
        "competition_code",
        "competition",
        "league",
        "competition_name",
        "league_name",
        default=None
    )


def get_season(row):
    return first_value(
        row,
        "season",
        "season_id",
        default=None
    )


# ============================================================
# FINISHED MATCH
# ============================================================

def is_finished_match(row):
    home_score = get_home_score(row)
    away_score = get_away_score(row)

    if home_score is None or away_score is None:
        return False

    try:
        float(home_score)
        float(away_score)
        return True
    except Exception:
        return False


# ============================================================
# RESULT
# ============================================================

def result_for_team(team_is_home, home_score, away_score):
    home_score = as_float(home_score)
    away_score = as_float(away_score)

    if team_is_home:
        if home_score > away_score:
            return "W"

        if home_score < away_score:
            return "L"

        return "D"

    if away_score > home_score:
        return "W"

    if away_score < home_score:
        return "L"

    return "D"


# ============================================================
# STANDINGS
# ============================================================

def position_bucket(rank, team_count=20):
    if rank is None:
        return "MID"

    team_count = max(
        int(team_count or 20),
        2
    )

    top_limit = max(
        1,
        int(math.ceil(team_count * 0.30))
    )

    bottom_start = max(
        top_limit + 1,
        int(math.floor(team_count * 0.70)) + 1
    )

    if rank <= top_limit:
        return "TOP"

    if rank >= bottom_start:
        return "BOTTOM"

    return "MID"


def opponent_strength(rank, team_count=20):
    bucket = position_bucket(
        rank,
        team_count
    )

    if bucket == "TOP":
        return 0.30

    if bucket == "BOTTOM":
        return -0.20

    return 0.0


def build_standings_index(rows):
    index = defaultdict(
        lambda: defaultdict(list)
    )

    for row in rows:

        league = first_value(
            row,
            "league_code",
            "competition_code",
            "competition",
            "league",
            default=None
        )

        season = first_value(
            row,
            "season",
            default=None
        )

        team_id = normalize_team_id(
            first_value(
                row,
                "team_id",
                "teamId",
                default=None
            )
        )

        rank = as_int(
            first_value(
                row,
                "rank",
                "position",
                default=None
            )
        )

        updated = parse_datetime(
            first_value(
                row,
                "last_updated",
                "updated_at",
                "updated",
                "date",
                default=None
            )
        )

        if team_id is None or rank is None:
            continue

        key = (
            str(league).lower()
            if league is not None
            else None,
            as_int(season, season)
        )

        index[key][team_id].append(
            {
                "rank": rank,
                "date": updated
            }
        )

    result = {}

    for key, teams in index.items():

        team_count = len(teams)

        result[key] = {}

        for team_id, snapshots in teams.items():

            snapshots.sort(
                key=lambda x: (
                    x["date"] is not None,
                    x["date"] or datetime.min.replace(
                        tzinfo=timezone.utc
                    )
                )
            )

            for snapshot in snapshots:
                snapshot["team_count"] = team_count

            result[key][team_id] = snapshots

    return result


def get_rank_from_snapshot(
    standings_index,
    league,
    season,
    team_id,
    before_date=None
):
    """
    Return the most recent historical/current standings rank
    available BEFORE the target match date.

    Historical standings are preferred.

    IMPORTANT:
    We use snapshot_date < before_date rather than <=.

    This prevents a match from seeing standings that may already
    contain results from the same matchday.
    """

    if team_id is None:
        return None, None

    key = (
        str(league).lower()
        if league is not None
        else None,
        as_int(season, season)
    )

    league_data = standings_index.get(key)

    if not league_data:
        return None, None

    snapshots = league_data.get(team_id)

    if not snapshots:
        return None, None

    # --------------------------------------------------------
    # Historical/current snapshot before target match
    # --------------------------------------------------------

    if before_date is not None:

        best = None

        for snapshot in snapshots:

            snapshot_date = snapshot.get("date")

            if snapshot_date is None:
                continue

            # STRICTLY BEFORE the match.
            #
            # Using <= could allow a same-day standings snapshot
            # containing results from the matchday itself.
            if snapshot_date < before_date:

                if (
                    best is None
                    or snapshot_date > best["date"]
                ):
                    best = snapshot

        if best is not None:

            return (
                best["rank"],
                best["team_count"]
            )

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    best = None

    for snapshot in snapshots:

        if best is None:
            best = snapshot

        elif snapshot.get("date") is not None:

            if (
                best.get("date") is None
                or snapshot["date"] > best["date"]
            ):
                best = snapshot

    if best:

        return (
            best["rank"],
            best["team_count"]
        )

    return None, None


def position_factor(rank, team_count=20):
    if rank is None:
        return 0.0

    team_count = max(
        int(team_count or 20),
        2
    )

    normalized = 1.0 - (
        (rank - 1)
        / float(team_count - 1)
    )

    return (
        normalized - 0.5
    ) * 0.40


# ============================================================
# MATCH HISTORY
# ============================================================

def build_match_history(matches):
    history = defaultdict(list)

    for row in matches:

        if not is_finished_match(row):
            continue

        date = get_match_date(row)

        if date is None:
            continue

        home_id = get_home_id(row)
        away_id = get_away_id(row)

        if home_id is None or away_id is None:
            continue

        item = {
            "id": get_match_id(row),
            "date": date,
            "home_id": home_id,
            "away_id": away_id,
            "home_score": as_float(
                get_home_score(row)
            ),
            "away_score": as_float(
                get_away_score(row)
            ),
            "league": get_league(row),
            "season": get_season(row)
        }

        history[home_id].append(item)
        history[away_id].append(item)

    for team_id in history:

        history[team_id].sort(
            key=lambda x: x["date"],
            reverse=True
        )

    return history


# ============================================================
# RECENT FORM
# ============================================================

def calculate_recent_form(
    team_id,
    target_date,
    target_league,
    target_season,
    history,
    standings_index
):
    matches = history.get(
        team_id,
        []
    )

    selected = []

    for match in matches:

        if match["date"] >= target_date:
            continue

        # Same league when available
        if (
            target_league is not None
            and match["league"] is not None
        ):

            if (
                str(match["league"]).lower()
                != str(target_league).lower()
            ):
                continue

        # Same season when available
        if (
            target_season is not None
            and match["season"] is not None
        ):

            if (
                as_int(match["season"], None)
                != as_int(target_season, None)
            ):
                continue

        selected.append(match)

        if len(selected) >= FORM_MATCHES:
            break

    if not selected:
        return {
            "attack": 0.0,
            "defence": 0.0,
            "points_rate": 0.0,
            "strength": 0.0,
            "home_attack": 0.0,
            "home_defence": 0.0,
            "away_attack": 0.0,
            "away_defence": 0.0,
            "matches_used": 0
        }

    attack_sum = 0.0
    defence_sum = 0.0
    points_sum = 0.0
    strength_sum = 0.0

    home_attack_sum = 0.0
    home_defence_sum = 0.0
    away_attack_sum = 0.0
    away_defence_sum = 0.0

    weight_sum = 0.0

    for index, match in enumerate(selected):

        weight = FORM_DECAY ** index

        is_home = (
            match["home_id"] == team_id
        )

        opponent_id = (
            match["away_id"]
            if is_home
            else match["home_id"]
        )

        scored = (
            match["home_score"]
            if is_home
            else match["away_score"]
        )

        conceded = (
            match["away_score"]
            if is_home
            else match["home_score"]
        )

        result = result_for_team(
            is_home,
            match["home_score"],
            match["away_score"]
        )

        if result == "W":
            points = 3.0

        elif result == "D":
            points = 1.0

        else:
            points = 0.0

        # Historical opponent position
        rank, team_count = get_rank_from_snapshot(
            standings_index,
            match["league"],
            match["season"],
            opponent_id,
            match["date"]
        )

        strength = opponent_strength(
            rank,
            team_count or 20
        )

        # Beating a stronger opponent receives more weight.
        attack_adjustment = (
            1.0
            + strength * 0.45
        )

        defence_adjustment = (
            1.0
            - strength * 0.30
        )

        adjusted_scored = (
            scored
            * attack_adjustment
        )

        adjusted_conceded = (
            conceded
            * defence_adjustment
        )

        attack_sum += (
            adjusted_scored
            * weight
        )

        defence_sum += (
            adjusted_conceded
            * weight
        )

        points_sum += (
            points
            * weight
        )

        strength_sum += (
            strength
            * weight
        )

        if is_home:

            home_attack_sum += (
                adjusted_scored
                * weight
            )

            home_defence_sum += (
                adjusted_conceded
                * weight
            )

        else:

            away_attack_sum += (
                adjusted_scored
                * weight
            )

            away_defence_sum += (
                adjusted_conceded
                * weight
            )

        weight_sum += weight

    if weight_sum <= 0:
        weight_sum = 1.0

    return {
        "attack": (
            attack_sum
            / weight_sum
        ),

        "defence": (
            defence_sum
            / weight_sum
        ),

        "points_rate": (
            points_sum
            / weight_sum
        ),

        "strength": (
            strength_sum
            / weight_sum
        ),

        "home_attack": (
            home_attack_sum
            / weight_sum
        ),

        "home_defence": (
            home_defence_sum
            / weight_sum
        ),

        "away_attack": (
            away_attack_sum
            / weight_sum
        ),

        "away_defence": (
            away_defence_sum
            / weight_sum
        ),

        "matches_used": len(selected)
    }


# ============================================================
# H2H
# ============================================================

def build_h2h_index(rows):
    index = defaultdict(list)

    for row in rows:

        home_id = normalize_team_id(
            first_value(
                row,
                "home_team_id",
                "home_id",
                "hometeamid",
                default=None
            )
        )

        away_id = normalize_team_id(
            first_value(
                row,
                "away_team_id",
                "away_id",
                "awayteamid",
                default=None
            )
        )

        if home_id is None or away_id is None:
            continue

        home_score = first_value(
            row,
            "home_score",
            "home_goals",
            "homeScore",
            default=None
        )

        away_score = first_value(
            row,
            "away_score",
            "away_goals",
            "awayScore",
            default=None
        )

        if home_score is None or away_score is None:
            continue

        date = parse_datetime(
            first_value(
                row,
                "utcdate",
                "utcDate",
                "date",
                "match_date",
                "played_at",
                default=None
            )
        )

        item = {
            "date": date,
            "home_id": home_id,
            "away_id": away_id,
            "home_score": as_float(
                home_score
            ),
            "away_score": as_float(
                away_score
            )
        }

        index[
            (home_id, away_id)
        ].append(item)

        index[
            (away_id, home_id)
        ].append(item)

    for key in index:

        index[key].sort(
            key=lambda x: (
                x["date"] is not None,
                x["date"] or datetime.min.replace(
                    tzinfo=timezone.utc
                )
            ),
            reverse=True
        )

    return index


def calculate_h2h(
    home_id,
    away_id,
    target_date,
    h2h_index
):
    rows = h2h_index.get(
        (home_id, away_id),
        []
    )

    if not rows:
        return 0.0, 0.0, 0

    selected = []

    for row in rows:

        if (
            row["date"] is not None
            and row["date"] >= target_date
        ):
            continue

        selected.append(row)

        if len(selected) >= H2H_MATCHES:
            break

    if not selected:
        return 0.0, 0.0, 0

    home_sum = 0.0
    away_sum = 0.0
    weight_sum = 0.0

    for index, row in enumerate(selected):

        weight = H2H_DECAY ** index

        if row["home_id"] == home_id:

            home_goals = row["home_score"]
            away_goals = row["away_score"]

        else:

            home_goals = row["away_score"]
            away_goals = row["home_score"]

        home_sum += (
            home_goals
            * weight
        )

        away_sum += (
            away_goals
            * weight
        )

        weight_sum += weight

    if weight_sum <= 0:
        return 0.0, 0.0, len(selected)

    home_avg = (
        home_sum
        / weight_sum
    )

    away_avg = (
        away_sum
        / weight_sum
    )

    home_modifier = (
        home_avg
        - away_avg
    ) * 0.12

    away_modifier = (
        away_avg
        - home_avg
    ) * 0.12

    return (
        home_modifier,
        away_modifier,
        len(selected)
    )


# ============================================================
# ODDS
# ============================================================

def build_odds_index(rows):
    index = {}

    for row in rows:

        match_id = first_value(
            row,
            "match_id",
            "fixture_id",
            "fixtureId",
            "id_match",
            default=None
        )

        if match_id is None:
            continue

        match_id = as_int(
            match_id,
            match_id
        )

        home = first_value(
            row,
            "home_odds",
            "odds_home",
            "home_win",
            "home_price",
            "odds1",
            "price_home",
            default=None
        )

        draw = first_value(
            row,
            "draw_odds",
            "odds_draw",
            "draw_price",
            "oddsx",
            "price_draw",
            default=None
        )

        away = first_value(
            row,
            "away_odds",
            "odds_away",
            "away_win",
            "away_price",
            "odds2",
            "price_away",
            default=None
        )

        odds_json = first_value(
            row,
            "odds",
            "markets",
            "data",
            default=None
        )

        if isinstance(odds_json, dict):

            if home is None:
                home = odds_json.get("home")

            if draw is None:
                draw = odds_json.get("draw")

            if away is None:
                away = odds_json.get("away")

        home = as_float(
            home,
            0.0
        )

        draw = as_float(
            draw,
            0.0
        )

        away = as_float(
            away,
            0.0
        )

        if (
            home > 1.0
            and draw > 1.0
            and away > 1.0
        ):
            index[match_id] = (
                home,
                draw,
                away
            )

    return index


def odds_probabilities(odds):
    if not odds:
        return None

    home, draw, away = odds

    if (
        home <= 1.0
        or draw <= 1.0
        or away <= 1.0
    ):
        return None

    implied = np.array(
        [
            1.0 / home,
            1.0 / draw,
            1.0 / away
        ],
        dtype=np.float64
    )

    total = implied.sum()

    if total <= 0:
        return None

    return implied / total


# ============================================================
# EXPECTED GOALS
# ============================================================

def calculate_expected_goals(
    home_form,
    away_form,
    home_rank,
    away_rank,
    team_count,
    h2h_home,
    h2h_away
):
    # Baseline
    base_home = 1.35
    base_away = 1.10

    # Recent attacking form
    home_attack_component = (
        home_form["attack"] - 1.30
    ) * FORM_WEIGHT

    away_attack_component = (
        away_form["attack"] - 1.10
    ) * FORM_WEIGHT

    # Opponent defence
    home_defence_component = (
        1.30 - away_form["defence"]
    ) * FORM_WEIGHT * 0.55

    away_defence_component = (
        1.10 - home_form["defence"]
    ) * FORM_WEIGHT * 0.55

    # Points form
    home_points_component = (
        home_form["points_rate"] - 1.5
    ) * 0.10

    away_points_component = (
        away_form["points_rate"] - 1.5
    ) * 0.10

    # Home-specific form
    home_specific_attack = 0.0
    home_specific_defence = 0.0

    if home_form["home_attack"] > 0:

        home_specific_attack = (
            home_form["home_attack"] - 1.30
        ) * HOME_AWAY_WEIGHT

    if home_form["home_defence"] > 0:

        home_specific_defence = (
            1.30 - home_form["home_defence"]
        ) * HOME_AWAY_WEIGHT * 0.40

    # Away-specific form
    away_specific_attack = 0.0
    away_specific_defence = 0.0

    if away_form["away_attack"] > 0:

        away_specific_attack = (
            away_form["away_attack"] - 1.10
        ) * HOME_AWAY_WEIGHT

    if away_form["away_defence"] > 0:

        away_specific_defence = (
            1.10 - away_form["away_defence"]
        ) * HOME_AWAY_WEIGHT * 0.40

    # Current league position
    home_position = position_factor(
        home_rank,
        team_count
    )

    away_position = position_factor(
        away_rank,
        team_count
    )

    position_home = (
        home_position
        - away_position * 0.60
    ) * POSITION_WEIGHT

    position_away = (
        away_position
        - home_position * 0.60
    ) * POSITION_WEIGHT

    # H2H
    h2h_home_component = (
        h2h_home
        * H2H_WEIGHT
    )

    h2h_away_component = (
        h2h_away
        * H2H_WEIGHT
    )

    # Final lambdas
    home_lambda = (
        base_home
        + home_attack_component
        + home_defence_component
        + home_points_component
        + home_specific_attack
        + home_specific_defence
        + position_home
        + h2h_home_component
    )

    away_lambda = (
        base_away
        + away_attack_component
        + away_defence_component
        + away_points_component
        + away_specific_attack
        + away_specific_defence
        + position_away
        + h2h_away_component
    )

    # Home advantage
    home_lambda += 0.12

    home_lambda = float(
        np.clip(
            home_lambda,
            MIN_LAMBDA,
            MAX_LAMBDA
        )
    )

    away_lambda = float(
        np.clip(
            away_lambda,
            MIN_LAMBDA,
            MAX_LAMBDA
        )
    )

    return (
        home_lambda,
        away_lambda
    )


# ============================================================
# POISSON DISTRIBUTION
# ============================================================

def poisson_distribution(
    lambdas,
    max_goals=MAX_GOALS
):
    lambdas = np.asarray(
        lambdas,
        dtype=np.float64
    )

    lambdas = np.clip(
        lambdas,
        MIN_LAMBDA,
        MAX_LAMBDA
    )

    count = len(lambdas)

    probabilities = np.empty(
        (
            count,
            max_goals + 1
        ),
        dtype=np.float64
    )

    probabilities[:, 0] = np.exp(
        -lambdas
    )

    for goal in range(
        1,
        max_goals + 1
    ):

        probabilities[:, goal] = (
            probabilities[:, goal - 1]
            * lambdas
            / float(goal)
        )

    # Normalize truncated distribution
    totals = probabilities.sum(
        axis=1
    )

    totals[totals <= 0] = 1.0

    probabilities /= totals[:, None]

    return probabilities


# ============================================================
# VECTORIZED MARKET ENGINE
# ============================================================

def calculate_markets_batch(
    home_lambdas,
    away_lambdas
):
    home_lambdas = np.asarray(
        home_lambdas,
        dtype=np.float64
    )

    away_lambdas = np.asarray(
        away_lambdas,
        dtype=np.float64
    )

    home_probs = poisson_distribution(
        home_lambdas
    )

    away_probs = poisson_distribution(
        away_lambdas
    )

    matrix = (
        home_probs[:, :, None]
        * away_probs[:, None, :]
    )

    count = len(home_lambdas)

    home_probability = np.zeros(
        count,
        dtype=np.float64
    )

    draw_probability = np.zeros(
        count,
        dtype=np.float64
    )

    away_probability = np.zeros(
        count,
        dtype=np.float64
    )

    # 1X2
    for home_goals in range(
        MAX_GOALS + 1
    ):

        for away_goals in range(
            MAX_GOALS + 1
        ):

            values = matrix[
                :,
                home_goals,
                away_goals
            ]

            if home_goals > away_goals:

                home_probability += values

            elif home_goals == away_goals:

                draw_probability += values

            else:

                away_probability += values

    # BTTS
    btts = (
        1.0
        - matrix[:, 0, :].sum(axis=1)
        - matrix[:, :, 0].sum(axis=1)
        + matrix[:, 0, 0]
    )

    # Totals
    over_1_5 = np.zeros(
        count,
        dtype=np.float64
    )

    over_2_5 = np.zeros(
        count,
        dtype=np.float64
    )

    over_3_5 = np.zeros(
        count,
        dtype=np.float64
    )

    over_4_5 = np.zeros(
        count,
        dtype=np.float64
    )

    for home_goals in range(
        MAX_GOALS + 1
    ):

        for away_goals in range(
            MAX_GOALS + 1
        ):

            values = matrix[
                :,
                home_goals,
                away_goals
            ]

            total_goals = (
                home_goals
                + away_goals
            )

            if total_goals >= 2:
                over_1_5 += values

            if total_goals >= 3:
                over_2_5 += values

            if total_goals >= 4:
                over_3_5 += values

            if total_goals >= 5:
                over_4_5 += values

    # Primary and alternative score
    flattened = matrix.reshape(
        count,
        -1
    )

    sorted_indices = np.argsort(
        flattened,
        axis=1
    )[:, ::-1]

    primary_indices = (
        sorted_indices[:, 0]
    )

    alternative_indices = (
        sorted_indices[:, 1]
    )

    primary_home = (
        primary_indices
        // (MAX_GOALS + 1)
    )

    primary_away = (
        primary_indices
        % (MAX_GOALS + 1)
    )

    alternative_home = (
        alternative_indices
        // (MAX_GOALS + 1)
    )

    alternative_away = (
        alternative_indices
        % (MAX_GOALS + 1)
    )

    # Normalize 1X2
    outcome_total = (
        home_probability
        + draw_probability
        + away_probability
    )

    outcome_total[
        outcome_total <= 0
    ] = 1.0

    home_probability /= outcome_total
    draw_probability /= outcome_total
    away_probability /= outcome_total

    return {
        "primary_home": primary_home,
        "primary_away": primary_away,

        "alternative_home":
            alternative_home,

        "alternative_away":
            alternative_away,

        "home_probability":
            home_probability,

        "draw_probability":
            draw_probability,

        "away_probability":
            away_probability,

        "btts":
            np.clip(
                btts,
                0.0,
                1.0
            ),

        "over_1_5":
            np.clip(
                over_1_5,
                0.0,
                1.0
            ),

        "over_2_5":
            np.clip(
                over_2_5,
                0.0,
                1.0
            ),

        "over_3_5":
            np.clip(
                over_3_5,
                0.0,
                1.0
            ),

        "over_4_5":
            np.clip(
                over_4_5,
                0.0,
                1.0
            )
    }


# ============================================================
# ODDS BLENDING
# ============================================================

def blend_1x2(
    home_probability,
    draw_probability,
    away_probability,
    odds
):
    bookmaker = odds_probabilities(
        odds
    )

    if bookmaker is None:

        return (
            home_probability,
            draw_probability,
            away_probability
        )

    model = np.array(
        [
            home_probability,
            draw_probability,
            away_probability
        ],
        dtype=np.float64
    )

    blended = (
        model
        * (1.0 - ODDS_WEIGHT)
        + bookmaker
        * ODDS_WEIGHT
    )

    total = blended.sum()

    if total > 0:
        blended /= total

    return (
        float(blended[0]),
        float(blended[1]),
        float(blended[2])
    )


# ============================================================
# PREDICTION
# ============================================================

def prediction_label(
    home_probability,
    draw_probability,
    away_probability
):
    probabilities = {
        "HOME": home_probability,
        "DRAW": draw_probability,
        "AWAY": away_probability
    }

    return max(
        probabilities,
        key=probabilities.get
    )


def confidence_level(
    home_probability,
    draw_probability,
    away_probability
):
    highest = max(
        home_probability,
        draw_probability,
        away_probability
    )

    if highest >= 0.70:
        return "VERY HIGH"

    if highest >= 0.58:
        return "HIGH"

    if highest >= 0.48:
        return "MEDIUM"

    return "LOW"


# ============================================================
# PREPARE MATCH
# ============================================================

def prepare_match(
    match,
    history,
    standings_index,
    h2h_index,
    odds_index
):
    match_id = get_match_id(match)

    home_id = get_home_id(match)
    away_id = get_away_id(match)

    home_name = get_home_name(match)
    away_name = get_away_name(match)

    target_date = get_match_date(match)

    if target_date is None:
        target_date = datetime.now(
            timezone.utc
        )

    league = get_league(match)
    season = get_season(match)

    # Recent form
    home_form = calculate_recent_form(
        home_id,
        target_date,
        league,
        season,
        history,
        standings_index
    )

    away_form = calculate_recent_form(
        away_id,
        target_date,
        league,
        season,
        history,
        standings_index
    )

    # Current standings
    home_rank, home_count = (
        get_rank_from_snapshot(
            standings_index,
            league,
            season,
            home_id,
            target_date
        )
    )

    away_rank, away_count = (
        get_rank_from_snapshot(
            standings_index,
            league,
            season,
            away_id,
            target_date
        )
    )

    team_count = (
        home_count
        or away_count
        or 20
    )

    # H2H
    h2h_home, h2h_away, h2h_used = (
        calculate_h2h(
            home_id,
            away_id,
            target_date,
            h2h_index
        )
    )

    # Expected goals
    home_lambda, away_lambda = (
        calculate_expected_goals(
            home_form,
            away_form,
            home_rank,
            away_rank,
            team_count,
            h2h_home,
            h2h_away
        )
    )

    odds = odds_index.get(
        as_int(
            match_id,
            match_id
        )
    )

    return {
        "match_id": match_id,

        "home_id": home_id,
        "away_id": away_id,

        "home_team": home_name,
        "away_team": away_name,

        "league": league,
        "season": season,

        "target_date": target_date,

        "home_form": home_form,
        "away_form": away_form,

        "home_rank": home_rank,
        "away_rank": away_rank,

        "team_count": team_count,

        "h2h_home": h2h_home,
        "h2h_away": h2h_away,
        "h2h_used": h2h_used,

        "home_lambda": home_lambda,
        "away_lambda": away_lambda,

        "odds": odds
    }


def build_historical_standings_index_fast(rows):
    """
    Build the historical standings index.

    IMPORTANT:
    get_league() in g.py returns the match's `competition` value
    for the current matches table.

    Therefore historical standings are normalized to the SAME
    competition names rather than PL/PD/BL1/etc.

    Key:
        (competition_name.lower(), season)

    Value:
        team_id -> ordered snapshots
    """

    index = defaultdict(
        lambda: defaultdict(list)
    )

    # --------------------------------------------------------
    # Convert API/database league codes into the exact
    # competition names used by matches.
    # --------------------------------------------------------

    code_to_competition = {
        "PL": "Premier League",
        "PD": "Primera Division",
        "BL1": "Bundesliga",
        "FL1": "Ligue 1",
        "SA": "Serie A",
        "CL": "UEFA Champions League",
    }

    for row in rows:

        competition = first_value(
            row,
            "competition",
            default=None
        )

        league_code = first_value(
            row,
            "league_code",
            default=None
        )

        # ----------------------------------------------------
        # Prefer competition because it is already exactly
        # what get_league(match) returns.
        # ----------------------------------------------------

        if competition is not None:

            competition = str(
                competition
            ).strip()

        elif league_code is not None:

            code = str(
                league_code
            ).strip().upper()

            competition = code_to_competition.get(
                code,
                code
            )

        else:
            continue

        season = as_int(
            first_value(
                row,
                "season",
                default=None
            ),
            None
        )

        team_id = normalize_team_id(
            first_value(
                row,
                "team_id",
                default=None
            )
        )

        rank = as_int(
            first_value(
                row,
                "rank",
                default=None
            ),
            None
        )

        snapshot_date = first_value(
            row,
            "snapshot_date",
            default=None
        )

        if season is None:
            continue

        if team_id is None:
            continue

        if rank is None:
            continue

        # ----------------------------------------------------
        # SAME KEY FORMAT AS build_standings_index()
        #
        # get_league(match) -> "Premier League"
        # therefore key -> "premier league"
        # ----------------------------------------------------

        key = (
            str(competition).lower(),
            season
        )

        index[key][team_id].append(
            {
                "rank": rank,
                "date": snapshot_date,
                "historical": True
            }
        )

    # --------------------------------------------------------
    # Calculate team count and sort snapshots.
    # --------------------------------------------------------

    result = {}

    for key, teams in index.items():

        team_count = len(teams)

        result[key] = {}

        for team_id, snapshots in teams.items():

            snapshots.sort(
                key=lambda x: (
                    x["date"] is not None,
                    x["date"] or datetime.min
                )
            )

            for snapshot in snapshots:

                snapshot["team_count"] = team_count

            result[key][team_id] = snapshots

    return result


# ============================================================
# HISTORICAL STANDINGS
# ============================================================

async def load_historical_standings():
    """
    Load reconstructed historical standings.

    The table contains snapshots after completed matchdays.

    These are converted into the same structure expected by
    get_rank_from_snapshot(), so the prediction engine can use
    historical positions without changing the rest of the model.
    """

    try:

        rows = await query_db(
            f"""
                SELECT
                    competition,
                    league_code,
                    season,
                    matchday,
                    snapshot_date,
                    team_id,
                    rank
                FROM {HISTORICAL_STANDINGS_TABLE}
                ORDER BY
                    league_code,
                    season,
                    team_id,
                    snapshot_date ASC
            """
        )

        rows = list(rows or [])

        index = defaultdict(
            lambda: defaultdict(list)
        )

        for row in rows:

            league_code = first_value(
                row,
                "league_code",
                default=None
            )

            competition = first_value(
                row,
                "competition",
                default=None
            )

            season = as_int(
                first_value(
                    row,
                    "season",
                    default=None
                ),
                None
            )

            team_id = normalize_team_id(
                first_value(
                    row,
                    "team_id",
                    default=None
                )
            )

            rank = as_int(
                first_value(
                    row,
                    "rank",
                    default=None
                ),
                None
            )

            snapshot_date = first_value(
                row,
                "snapshot_date",
                default=None
            )

            if season is None:
                continue

            if team_id is None:
                continue

            if rank is None:
                continue

            # ------------------------------------------------
            # Prefer league_code.
            #
            # If unavailable, normalize competition name.
            # ------------------------------------------------

            if league_code is None:

                aliases = {
                    "Premier League": "PL",
                    "Primera Division": "PD",
                    "Bundesliga": "BL1",
                    "Ligue 1": "FL1",
                    "Serie A": "SA",
                    "UEFA Champions League": "CL",
                }

                league_code = aliases.get(
                    str(competition),
                    str(competition).upper()
                )

            key = (
                str(league_code).lower(),
                season
            )

            index[key][team_id].append(
                {
                    "rank": rank,
                    "date": snapshot_date,
                    "historical": True
                }
            )

        # ----------------------------------------------------
        # Calculate team count for every league/season.
        # ----------------------------------------------------

        result = {}

        for key, teams in index.items():

            team_count = len(teams)

            result[key] = {}

            for team_id, snapshots in teams.items():

                snapshots.sort(
                    key=lambda x: (
                        x["date"] is not None,
                        x["date"] or datetime.min
                    )
                )

                for snapshot in snapshots:
                    snapshot["team_count"] = team_count

                result[key][team_id] = snapshots

        print(
            f"   Historical standings rows: {len(rows)}"
        )

        print(
            f"   Historical standings groups: {len(result)}"
        )

        return result

    except Exception as exc:

        logger.warning(
            "Historical standings unavailable: %s",
            exc
        )

        return {}


# ============================================================
# VALUE TABLE SCHEMA
# ============================================================

async def get_value_columns():
    sql = """
        SELECT
            column_name,
            ordinal_position,
            data_type,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = $1
          AND table_name = $2
        ORDER BY ordinal_position
    """

    try:

        rows = await query_db(
            sql,
            (
                SCHEMA,
                "value"
            )
        )

        return list(
            rows or []
        )

    except Exception as exc:

        logger.warning(
            "Could not inspect value table: %s",
            exc
        )

        return []


def find_column(columns, *names):
    wanted = {
        name.lower()
        for name in names
    }

    for column in columns:

        column_name = str(
            first_value(
                column,
                "column_name",
                default=""
            )
        )

        if column_name.lower() in wanted:
            return column_name

    return None


# ============================================================
# SAVE PREDICTIONS
# ============================================================

async def save_predictions(predictions):
    if not predictions:
        print("Nothing to save.")
        return

    print(
        f"   Preparing "
        f"{len(predictions)} predictions..."
    )

    # ========================================================
    # ACTUAL henry_schema.value TABLE
    #
    # 1  match_id
    # 2  home_team_id
    # 3  away_team_id
    # 4  home_goals_pred
    # 5  away_goals_pred
    # 6  most_likely_score
    # 7  matches_used
    # 8  conf_score
    # 9  conf_btts
    # 10 conf_over_1_5
    # 11 conf_over_2_5
    # 12 conf_over_3_5
    # 13 conf_over_4_5
    # 14 over_1_5
    # 15 over_2_5
    # 16 over_3_5
    # 17 over_4_5
    # 18 btts_yes
    # 19 generated_at
    # ========================================================

    print(
        "   Using actual 19-column "
        "henry_schema.value layout..."
    )

    def parse_score(score):
        if score is None:
            return 0.0, 0.0

        text = str(score).strip()

        text = (
            text
            .replace("–", "-")
            .replace("—", "-")
            .replace("−", "-")
        )

        if "-" not in text:
            return 0.0, 0.0

        parts = text.split("-", 1)

        try:
            home_goals = float(parts[0].strip())
        except Exception:
            home_goals = 0.0

        try:
            away_goals = float(parts[1].strip())
        except Exception:
            away_goals = 0.0

        return (
            max(0.0, home_goals),
            max(0.0, away_goals)
        )

    def get_score_string(prediction):
        score = (
            prediction.get("primary_score")
            or prediction.get("most_likely_score")
            or prediction.get("score")
        )

        if score is None:
            home = prediction.get(
                "home_goals_pred",
                prediction.get("home_lambda", 0)
            )
            away = prediction.get(
                "away_goals_pred",
                prediction.get("away_lambda", 0)
            )

            try:
                home = round(float(home))
            except Exception:
                home = 0

            try:
                away = round(float(away))
            except Exception:
                away = 0

            return f"{home}-{away}"

        return str(score)

    def probability_value(prediction, *keys):
        for key in keys:
            value = prediction.get(key)

            if value is None:
                continue

            try:
                value = float(value)

                if value > 1.0:
                    value /= 100.0

                return max(
                    0.0,
                    min(1.0, value)
                )

            except Exception:
                continue

        return 0.0

    def boolean_market(prediction, keys):
        return (
            probability_value(
                prediction,
                *keys
            ) >= 0.50
        )

    prepared_rows = []

    for prediction in predictions:

        # ----------------------------------------------------
        # Team IDs
        # ----------------------------------------------------

        home_team_id = (
            prediction.get("home_team_id")
            or prediction.get("home_id")
        )

        away_team_id = (
            prediction.get("away_team_id")
            or prediction.get("away_id")
        )

        try:
            home_team_id = int(home_team_id)
        except Exception:
            home_team_id = None

        try:
            away_team_id = int(away_team_id)
        except Exception:
            away_team_id = None

        # ----------------------------------------------------
        # Score
        # ----------------------------------------------------

        score_string = get_score_string(
            prediction
        )

        home_goals, away_goals = parse_score(
            score_string
        )

        # ----------------------------------------------------
        # Confidence
        # ----------------------------------------------------

        conf_score = probability_value(
            prediction,
            "conf_score",
            "score_confidence",
            "confidence"
        )

        if conf_score <= 0:
            conf_score = max(
                probability_value(
                    prediction,
                    "home_probability",
                    "home_prob",
                    "prob_home"
                ),
                probability_value(
                    prediction,
                    "draw_probability",
                    "draw_prob",
                    "prob_draw"
                ),
                probability_value(
                    prediction,
                    "away_probability",
                    "away_prob",
                    "prob_away"
                )
            )

        conf_btts = probability_value(
            prediction,
            "btts",
            "btts_probability",
            "btts_prob",
            "conf_btts"
        )

        conf_over_1_5 = probability_value(
            prediction,
            "over_1_5",
            "over15",
            "over15_probability",
            "conf_over_1_5"
        )

        conf_over_2_5 = probability_value(
            prediction,
            "over_2_5",
            "over25",
            "over25_probability",
            "conf_over_2_5"
        )

        conf_over_3_5 = probability_value(
            prediction,
            "over_3_5",
            "over35",
            "over35_probability",
            "conf_over_3_5"
        )

        conf_over_4_5 = probability_value(
            prediction,
            "over_4_5",
            "over45",
            "over45_probability",
            "conf_over_4_5"
        )

        # ----------------------------------------------------
        # Boolean markets
        # ----------------------------------------------------

        over_1_5 = boolean_market(
            prediction,
            (
                "over_1_5",
                "over15",
                "over15_probability",
                "conf_over_1_5"
            )
        )

        over_2_5 = boolean_market(
            prediction,
            (
                "over_2_5",
                "over25",
                "over25_probability",
                "conf_over_2_5"
            )
        )

        over_3_5 = boolean_market(
            prediction,
            (
                "over_3_5",
                "over35",
                "over35_probability",
                "conf_over_3_5"
            )
        )

        over_4_5 = boolean_market(
            prediction,
            (
                "over_4_5",
                "over45",
                "over45_probability",
                "conf_over_4_5"
            )
        )

        btts_yes = boolean_market(
            prediction,
            (
                "btts",
                "btts_probability",
                "btts_prob",
                "conf_btts"
            )
        )

        # ----------------------------------------------------
        # Matches used
        # ----------------------------------------------------

        h2h_used = prediction.get(
            "h2h_used",
            0
        )

        form_home_used = prediction.get(
            "form_home_used",
            0
        )

        form_away_used = prediction.get(
            "form_away_used",
            0
        )

        try:
            h2h_used = int(h2h_used or 0)
        except Exception:
            h2h_used = 0

        try:
            form_home_used = int(
                form_home_used or 0
            )
        except Exception:
            form_home_used = 0

        try:
            form_away_used = int(
                form_away_used or 0
            )
        except Exception:
            form_away_used = 0

        matches_used = max(
            form_home_used,
            form_away_used,
            h2h_used
        )

        # ----------------------------------------------------
        # Generated timestamp
        # ----------------------------------------------------

        generated_at = prediction.get(
            "generated_at"
        )

        if generated_at is None:
            generated_at = datetime.now(
                timezone.utc
            )

        if isinstance(
            generated_at,
            datetime
        ):
            if generated_at.tzinfo is not None:
                generated_at = (
                    generated_at
                    .astimezone(timezone.utc)
                    .replace(tzinfo=None)
                )

        # ----------------------------------------------------
        # Build database row
        # ----------------------------------------------------

        prepared_rows.append(
            (
                prediction.get("match_id"),
                home_team_id,
                away_team_id,
                float(home_goals),
                float(away_goals),
                score_string,
                matches_used,
                float(conf_score),
                float(conf_btts),
                float(conf_over_1_5),
                float(conf_over_2_5),
                float(conf_over_3_5),
                float(conf_over_4_5),
                over_1_5,
                over_2_5,
                over_3_5,
                over_4_5,
                btts_yes,
                generated_at,
            )
        )

    # --------------------------------------------------------
    # Bulk insert
    # --------------------------------------------------------

    total = len(prepared_rows)

    for start in range(
        0,
        total,
        SAVE_CHUNK
    ):

        chunk = prepared_rows[
            start:
            start + SAVE_CHUNK
        ]

        placeholders = []
        params = []

        parameter = 1

        for row in chunk:

            row_placeholders = []

            for value in row:

                row_placeholders.append(
                    f"${parameter}"
                )

                params.append(value)

                parameter += 1

            placeholders.append(
                "("
                + ", ".join(
                    row_placeholders
                )
                + ")"
            )

        sql = f"""
            INSERT INTO {VALUE_TABLE}
            (
                match_id,
                home_team_id,
                away_team_id,
                home_goals_pred,
                away_goals_pred,
                most_likely_score,
                matches_used,
                conf_score,
                conf_btts,
                conf_over_1_5,
                conf_over_2_5,
                conf_over_3_5,
                conf_over_4_5,
                over_1_5,
                over_2_5,
                over_3_5,
                over_4_5,
                btts_yes,
                generated_at
            )
            VALUES
            {", ".join(placeholders)}
            ON CONFLICT (match_id)
            DO UPDATE SET
                home_team_id = EXCLUDED.home_team_id,
                away_team_id = EXCLUDED.away_team_id,
                home_goals_pred = EXCLUDED.home_goals_pred,
                away_goals_pred = EXCLUDED.away_goals_pred,
                most_likely_score = EXCLUDED.most_likely_score,
                matches_used = EXCLUDED.matches_used,
                conf_score = EXCLUDED.conf_score,
                conf_btts = EXCLUDED.conf_btts,
                conf_over_1_5 = EXCLUDED.conf_over_1_5,
                conf_over_2_5 = EXCLUDED.conf_over_2_5,
                conf_over_3_5 = EXCLUDED.conf_over_3_5,
                conf_over_4_5 = EXCLUDED.conf_over_4_5,
                over_1_5 = EXCLUDED.over_1_5,
                over_2_5 = EXCLUDED.over_2_5,
                over_3_5 = EXCLUDED.over_3_5,
                over_4_5 = EXCLUDED.over_4_5,
                btts_yes = EXCLUDED.btts_yes,
                generated_at = EXCLUDED.generated_at
        """

        try:

            await execute_db(
                sql,
                tuple(params)
            )

        except Exception as exc:

            logger.error(
                "GOALS value-table save failed: %s",
                exc
            )

            logger.error(
                "Failed batch starting at %s",
                start
            )

            return

        saved = min(
            start + len(chunk),
            total
        )

        print(
            f"   Saved "
            f"{saved}/{total}"
        )

    print(
        f"   ✅ Successfully saved "
        f"{total} predictions"
    )


# ============================================================
# MAIN
# ============================================================

async def run_predictions():

    started = time.perf_counter()

    print()
    print(
        "🚀 Running GOALS_FAST_V2 "
        "(Position-Aware / Thousands Optimized)..."
    )
    print()

    # ========================================================
    # LOAD
    # ========================================================

    print(
        "📥 Loading database data..."
    )

    matches = await query_db(
        f"""
            SELECT *
            FROM {MATCHES_TABLE}
            ORDER BY utcdate ASC
        """
    )

    h2h_rows = await query_db(
        f"""
            SELECT *
            FROM {H2H_TABLE}
        """
    )

    standings_rows = await query_db(
        f"""
            SELECT *
            FROM {STANDINGS_TABLE}
        """
    )

    historical_standings_rows = await query_db(
        f"""
            SELECT
                competition,
                league_code,
                season,
                matchday,
                snapshot_date,
                team_id,
                rank
            FROM {HISTORICAL_STANDINGS_TABLE}
        """
    )

    odds_rows = await query_db(
        f"""
            SELECT *
            FROM {ODDS_TABLE}
        """
    )

    matches = list(
        matches or []
    )

    h2h_rows = list(
        h2h_rows or []
    )

    standings_rows = list(
        standings_rows or []
    )

    historical_standings_rows = list(
        historical_standings_rows or []
    )

    odds_rows = list(
        odds_rows or []
    )

    print(
        f"   Matches: {len(matches)}"
    )

    print(
        f"   H2H rows: {len(h2h_rows)}"
    )

    print(
        f"   Standings rows: "
        f"{len(standings_rows)}"
    )

    print(
        f"   Historical standings rows: "
        f"{len(historical_standings_rows)}"
    )

    print(
        f"   Odds rows: {len(odds_rows)}"
    )

    # ========================================================
    # INDEX
    # ========================================================

    print()
    print(
        "🧠 Building indexes..."
    )

    history = build_match_history(
        matches
    )

    h2h_index = build_h2h_index(
        h2h_rows
    )

    standings_index = build_standings_index(
        standings_rows
    )

    historical_standings_index = (
        build_historical_standings_index_fast(
            historical_standings_rows
        )
    )

    # --------------------------------------------------------
    # Merge historical snapshots into the normal standings
    # index.
    #
    # Historical data is inserted BEFORE current standings.
    # get_rank_from_snapshot() will therefore find the latest
    # snapshot available before the fixture date.
    # --------------------------------------------------------

    for key, teams in historical_standings_index.items():

        if key not in standings_index:
            standings_index[key] = {}

        for team_id, snapshots in teams.items():

            existing = standings_index[key].get(
                team_id,
                []
            )

            standings_index[key][team_id] = (
                snapshots + existing
            )

    odds_index = build_odds_index(
        odds_rows
    )

    print(
        f"   Teams with history: "
        f"{len(history)}"
    )

    print(
        f"   H2H pairs: "
        f"{len(h2h_index)}"
    )

    print(
        f"   Standings groups: "
        f"{len(standings_index)}"
    )

    print(
        f"   Odds index: "
        f"{len(odds_index)}"
    )

    # ========================================================
    # UPCOMING
    # ========================================================

    upcoming = []

    for match in matches:

        status = str(
            first_value(
                match,
                "status",
                default=""
            )
        ).upper()

        home_score = get_home_score(
            match
        )

        away_score = get_away_score(
            match
        )

        # Already completed
        if (
            home_score is not None
            and away_score is not None
        ):
            continue

        if status:

            allowed_statuses = {
                "SCHEDULED",
                "TIMED",
                "NOT_STARTED",
                "NS",
                "UPCOMING"
            }

            if status not in allowed_statuses:
                continue

        if (
            get_home_id(match) is None
            or get_away_id(match) is None
        ):
            continue

        if get_match_date(match) is None:
            continue

        upcoming.append(
            match
        )

    print()
    print(
        f"🎯 Upcoming matches: "
        f"{len(upcoming)}"
    )

    if not upcoming:
        print(
            "No upcoming matches."
        )
        return

    # ========================================================
    # PREPARE
    # ========================================================

    print()
    print(
        "🧠 Calculating recent "
        "position-aware form..."
    )

    prepared = []

    prep_start = time.perf_counter()

    for index, match in enumerate(
        upcoming,
        start=1
    ):

        try:

            prepared.append(
                prepare_match(
                    match,
                    history,
                    standings_index,
                    h2h_index,
                    odds_index
                )
            )

        except Exception as exc:

            logger.error(
                "Preparation failed "
                "for match %s: %s",
                get_match_id(match),
                exc
            )

        if (
            index % PROGRESS_EVERY == 0
            or index == len(upcoming)
        ):

            elapsed = (
                time.perf_counter()
                - prep_start
            )

            speed = (
                index / elapsed
                if elapsed > 0
                else 0
            )

            remaining = (
                len(upcoming)
                - index
            )

            eta = (
                remaining / speed
                if speed > 0
                else 0
            )

            print(
                f"   🧠 {index}/"
                f"{len(upcoming)} "
                f"| {speed:.1f} matches/s "
                f"| ETA {eta:.1f}s"
            )

    # ========================================================
    # POISSON
    # ========================================================

    print()
    print(
        "⚡ Starting fast prediction engine..."
    )

    print(
        f"⚡ Exact Poisson calculation"
    )

    print(
        f"⚡ Maximum score goals: "
        f"{MAX_GOALS}"
    )

    print(
        f"⚡ Batch size: "
        f"{BATCH_SIZE}"
    )

    predictions = []

    prediction_start = time.perf_counter()

    total = len(prepared)

    for start in range(
        0,
        total,
        BATCH_SIZE
    ):

        batch = prepared[
            start:
            start + BATCH_SIZE
        ]

        home_lambdas = np.array(
            [
                item["home_lambda"]
                for item in batch
            ],
            dtype=np.float64
        )

        away_lambdas = np.array(
            [
                item["away_lambda"]
                for item in batch
            ],
            dtype=np.float64
        )

        markets = calculate_markets_batch(
            home_lambdas,
            away_lambdas
        )

        for i, item in enumerate(
            batch
        ):

            model_home = float(
                markets[
                    "home_probability"
                ][i]
            )

            model_draw = float(
                markets[
                    "draw_probability"
                ][i]
            )

            model_away = float(
                markets[
                    "away_probability"
                ][i]
            )

            (
                final_home,
                final_draw,
                final_away
            ) = blend_1x2(
                model_home,
                model_draw,
                model_away,
                item["odds"]
            )

            label = prediction_label(
                final_home,
                final_draw,
                final_away
            )

            confidence = confidence_level(
                final_home,
                final_draw,
                final_away
            )

            primary_home = int(
                markets[
                    "primary_home"
                ][i]
            )

            primary_away = int(
                markets[
                    "primary_away"
                ][i]
            )

            alternative_home = int(
                markets[
                    "alternative_home"
                ][i]
            )

            alternative_away = int(
                markets[
                    "alternative_away"
                ][i]
            )

            primary_score = (
                f"{primary_home}-"
                f"{primary_away}"
            )

            alternative_score = (
                f"{alternative_home}-"
                f"{alternative_away}"
            )

            predictions.append(
                {
                    "match_id":
                        item["match_id"],

                    "home_team":
                        item["home_team"],

                    "away_team":
                        item["away_team"],

                    "prediction":
                        label,

                    "primary_score":
                        primary_score,

                    "alternative_score":
                        alternative_score,

                    "home_probability":
                        final_home * 100.0,

                    "draw_probability":
                        final_draw * 100.0,

                    "away_probability":
                        final_away * 100.0,

                    "btts":
                        float(
                            markets["btts"][i]
                        ) * 100.0,

                    "over_1_5":
                        float(
                            markets[
                                "over_1_5"
                            ][i]
                        ) * 100.0,

                    "over_2_5":
                        float(
                            markets[
                                "over_2_5"
                            ][i]
                        ) * 100.0,

                    "over_3_5":
                        float(
                            markets[
                                "over_3_5"
                            ][i]
                        ) * 100.0,

                    "over_4_5":
                        float(
                            markets[
                                "over_4_5"
                            ][i]
                        ) * 100.0,

                    "home_lambda":
                        item["home_lambda"],

                    "away_lambda":
                        item["away_lambda"],

                    "h2h_used":
                        item["h2h_used"],

                    "form_home_used":
                        item[
                            "home_form"
                        ]["matches_used"],

                    "form_away_used":
                        item[
                            "away_form"
                        ]["matches_used"],

                    "home_rank":
                        item["home_rank"],

                    "away_rank":
                        item["away_rank"],

                    "confidence":
                        confidence
                }
            )

        processed = min(
            start + len(batch),
            total
        )

        elapsed = (
            time.perf_counter()
            - prediction_start
        )

        speed = (
            processed / elapsed
            if elapsed > 0
            else 0
        )

        remaining = (
            total - processed
        )

        eta = (
            remaining / speed
            if speed > 0
            else 0
        )

        print(
            f"   ⚡ {processed}/"
            f"{total} "
            f"| {speed:.1f} matches/s "
            f"| ETA {eta:.1f}s"
        )

    # ========================================================
    # SAMPLE OUTPUT
    # ========================================================

    print()
    print(
        "📊 Prediction samples:"
    )
    print()

    for prediction in predictions[:10]:

        print(
            f"{prediction['home_team']} "
            f"vs "
            f"{prediction['away_team']}"
        )

        print(
            f"   Prediction: "
            f"{prediction['prediction']}"
        )

        print(
            f"   Primary: "
            f"{prediction['primary_score']}"
        )

        print(
            f"   Alternative: "
            f"{prediction['alternative_score']}"
        )

        print(
            f"   1X2: "
            f"H {prediction['home_probability']:.2f}% "
            f"| D {prediction['draw_probability']:.2f}% "
            f"| A {prediction['away_probability']:.2f}%"
        )

        print(
            f"   BTTS: "
            f"{prediction['btts']:.2f}%"
        )

        print(
            f"   O1.5: "
            f"{prediction['over_1_5']:.2f}% "
            f"| O2.5: "
            f"{prediction['over_2_5']:.2f}% "
            f"| O3.5: "
            f"{prediction['over_3_5']:.2f}% "
            f"| O4.5: "
            f"{prediction['over_4_5']:.2f}%"
        )

        print(
            f"   Lambda: "
            f"{prediction['home_lambda']:.2f} - "
            f"{prediction['away_lambda']:.2f}"
        )

        print(
            f"   Position: "
            f"{prediction['home_rank'] or '?'} - "
            f"{prediction['away_rank'] or '?'}"
        )

        print(
            f"   Recent form matches: "
            f"{prediction['form_home_used']} - "
            f"{prediction['form_away_used']}"
        )

        print(
            f"   H2H matches: "
            f"{prediction['h2h_used']}"
        )

        print(
            f"   Confidence: "
            f"{prediction['confidence']}"
        )

        print()

    # ========================================================
    # SAVE
    # ========================================================

    print(
        "💾 Saving predictions..."
    )

    save_start = time.perf_counter()

    await save_predictions(
        predictions
    )

    save_time = (
        time.perf_counter()
        - save_start
    )

    total_time = (
        time.perf_counter()
        - started
    )

    print()
    print(
        "============================================================"
    )

    print(
        "✅ GOALS_FAST_V2 COMPLETE"
    )

    print(
        f"   Predictions: "
        f"{len(predictions)}"
    )

    print(
        f"   Save time: "
        f"{save_time:.2f}s"
    )

    print(
        f"   Total time: "
        f"{total_time:.2f}s"
    )

    if total_time > 0:

        print(
            f"   Overall speed: "
            f"{len(predictions) / total_time:.1f} "
            f"matches/s"
        )

    print(
        "============================================================"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            run_predictions()
        )

    except KeyboardInterrupt:

        print()
        print(
            "🛑 GOALS_FAST_V2 stopped."
        )

    except Exception as exc:

        print()
        print(
            "❌ GOALS_FAST_V2 ERROR:"
        )

        print(
            repr(exc)
        )

        logger.exception(
            "Fatal GOALS_FAST_V2 error"
        )
