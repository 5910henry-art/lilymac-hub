#!/usr/bin/env python3
"""
book.py — PostgreSQL bookmark generator
Safe fixture matching + prediction EV calculation
"""

import re
import unicodedata

import pandas as pd
from rapidfuzz import fuzz
from sqlalchemy import create_engine, text

from config2 import DATABASE_URL, DB_SCHEMA


# ============================================================
# CONFIG
# ============================================================

# Maximum allowed kickoff-time difference when matching fixtures.
TIME_TOLERANCE_MINUTES = 120

# Minimum directional similarity for BOTH teams.
TEAM_MATCH_THRESHOLD = 70


# ============================================================
# HELPERS
# ============================================================

def normalize_team(name: str) -> str:
    """
    Normalize football team names for reliable comparison.
    """

    if not isinstance(name, str):
        return ""

    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")

    name = name.lower()

    # Remove common football suffixes.
    name = re.sub(
        r"\b(fc|cf|ac|sc|afc|rc|club)\b",
        "",
        name
    )

    # Keep only letters/spaces.
    name = re.sub(r"[^a-z ]", "", name)

    # Collapse whitespace.
    name = re.sub(r"\s+", " ", name).strip()

    return name


def to_utc(series):
    """
    Convert timestamps to UTC and remove seconds.
    """

    dt = pd.to_datetime(series, errors="coerce")

    if dt.dt.tz is not None:
        return dt.dt.tz_convert("UTC").dt.floor("min")

    return dt.dt.tz_localize("UTC").dt.floor("min")


# ============================================================
# DATABASE
# ============================================================

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "options": f"-c search_path={DB_SCHEMA},public"
    }
)


print(f"🗄️ Database: {DATABASE_URL}")
print(f"📂 Schema: {DB_SCHEMA}")


# ============================================================
# LOAD DATA
# ============================================================

df_odds = pd.read_sql(
    "SELECT * FROM live_odds",
    engine
)

df_matches = pd.read_sql(
    "SELECT * FROM matches",
    engine
)

df_preds = pd.read_sql(
    """
    SELECT
        match_id,

        (
            prediction_json::jsonb
            -> 'probabilities'
            ->> 'home_win'
        )::float AS p_home,

        (
            prediction_json::jsonb
            -> 'probabilities'
            ->> 'draw'
        )::float AS p_draw,

        (
            prediction_json::jsonb
            -> 'probabilities'
            ->> 'away_win'
        )::float AS p_away

    FROM henry_schema.predictions
    """,
    engine
)


# ============================================================
# DETECT MATCH TIME COLUMN
# ============================================================

time_col = None

for col in df_matches.columns:

    if col.lower() in [
        "utcdate",
        "utc_date",
        "match_time",
        "date"
    ]:
        time_col = col
        break


if time_col is None:

    raise ValueError(
        "No time column found in matches table: "
        f"{list(df_matches.columns)}"
    )


print(f"🕒 Using match time column: {time_col}")


# ============================================================
# PREPARE TEAM NAMES
# ============================================================

df_odds["home_norm"] = (
    df_odds["home_team"]
    .apply(normalize_team)
)

df_odds["away_norm"] = (
    df_odds["away_team"]
    .apply(normalize_team)
)


df_matches["home_norm"] = (
    df_matches["home_team_name"]
    .apply(normalize_team)
)

df_matches["away_norm"] = (
    df_matches["away_team_name"]
    .apply(normalize_team)
)


# ============================================================
# TIME ALIGNMENT
# ============================================================

df_odds["match_time"] = to_utc(
    df_odds["match_time"]
)

df_matches["utcdate"] = to_utc(
    df_matches[time_col]
)


# ============================================================
# DEBUG SAMPLE
# ============================================================

print("\n=== SAMPLE ODDS DATA ===")

print(
    df_odds[
        [
            "home_team",
            "away_team",
            "match_time"
        ]
    ].head(3)
)


print("\n=== SAMPLE MATCH DATA ===")

print(
    df_matches[
        [
            "home_team_name",
            "away_team_name",
            "utcdate"
        ]
    ].head(3)
)


# ============================================================
# MATCH FIXTURES
# ============================================================

matched_rows = []
unmatched_rows = []


for _, odds in df_odds.iterrows():

    # --------------------------------------------------------
    # Invalid time
    # --------------------------------------------------------

    if pd.isna(odds["match_time"]):

        print(
            f"\n⚠️ INVALID TIME: "
            f"{odds['home_team']} vs "
            f"{odds['away_team']}"
        )

        unmatched_rows.append(odds)

        continue


    # --------------------------------------------------------
    # Time window
    # --------------------------------------------------------

    start = (
        odds["match_time"]
        - pd.Timedelta(
            minutes=TIME_TOLERANCE_MINUTES
        )
    )

    end = (
        odds["match_time"]
        + pd.Timedelta(
            minutes=TIME_TOLERANCE_MINUTES
        )
    )


    candidates = df_matches[
        (df_matches["utcdate"] >= start)
        &
        (df_matches["utcdate"] <= end)
    ]


    if candidates.empty:

        print(
            f"\n❌ NO TIME MATCH: "
            f"{odds['home_team']} vs "
            f"{odds['away_team']} "
            f"{odds['match_time']}"
        )

        unmatched_rows.append(odds)

        continue


    # --------------------------------------------------------
    # Find BEST directional match
    # --------------------------------------------------------

    found = None
    best_score = -1

    best_home_score = 0
    best_away_score = 0
    best_time_diff = None


    for _, match in candidates.iterrows():

        # ----------------------------------------------------
        # HOME must match HOME
        # AWAY must match AWAY
        # ----------------------------------------------------

        home_score = fuzz.token_sort_ratio(
            odds["home_norm"],
            match["home_norm"]
        )

        away_score = fuzz.token_sort_ratio(
            odds["away_norm"],
            match["away_norm"]
        )


        # ----------------------------------------------------
        # Exact directional match
        # ----------------------------------------------------

        exact_match = (
            odds["home_norm"]
            == match["home_norm"]
            and
            odds["away_norm"]
            == match["away_norm"]
        )


        if exact_match:

            found = match

            best_score = 1000

            best_home_score = 100
            best_away_score = 100

            best_time_diff = abs(
                (
                    odds["match_time"]
                    - match["utcdate"]
                ).total_seconds()
            ) / 60

            break


        # ----------------------------------------------------
        # BOTH teams must be strong
        # ----------------------------------------------------

        if (
            home_score < TEAM_MATCH_THRESHOLD
            or
            away_score < TEAM_MATCH_THRESHOLD
        ):
            continue


        # ----------------------------------------------------
        # Time difference
        # ----------------------------------------------------

        time_diff = abs(
            (
                odds["match_time"]
                - match["utcdate"]
            ).total_seconds()
        ) / 60


        # ----------------------------------------------------
        # Combined score
        #
        # Small time penalty prevents an equally similar
        # fixture farther away in time from winning.
        # ----------------------------------------------------

        score = (
            home_score
            + away_score
            - (time_diff * 0.05)
        )


        if score > best_score:

            best_score = score

            found = match

            best_home_score = home_score
            best_away_score = away_score
            best_time_diff = time_diff


    # ========================================================
    # ACCEPT MATCH
    # ========================================================

    if found is not None:

        matched_rows.append(
            {
                "match_id": found["id"],

                "home_team":
                    odds["home_team"],

                "away_team":
                    odds["away_team"],

                "match_time":
                    odds["match_time"],

                "home_odds":
                    odds["home_odds"],

                "draw_odds":
                    odds["draw_odds"],

                "away_odds":
                    odds["away_odds"],
            }
        )

    else:

        print(
            f"\n⚠️ REJECTED MATCH: "
            f"{odds['home_team']} vs "
            f"{odds['away_team']}"
        )

        unmatched_rows.append(odds)


# ============================================================
# DATAFRAMES
# ============================================================

df_matched = pd.DataFrame(
    matched_rows
)

df_unmatched = pd.DataFrame(
    unmatched_rows
)


print(
    f"\n✅ Total matched: "
    f"{len(df_matched)}"
)

print(
    f"⚠️ Total unmatched: "
    f"{len(df_unmatched)}"
)


# ============================================================
# STOP IF NOTHING MATCHED
# ============================================================

if df_matched.empty:

    print(
        "\n❌ No matches found. "
        "Nothing will be written to bookmark."
    )

    raise SystemExit(0)


# ============================================================
# DUPLICATE MATCH ID CHECK
#
# THIS MUST HAPPEN BEFORE JOINING PREDICTIONS.
# ============================================================

print(
    "\n=== DUPLICATE MATCH IDS "
    "AFTER MATCHING ==="
)


dupes = df_matched[
    df_matched.duplicated(
        "match_id",
        keep=False
    )
].sort_values("match_id")


if not dupes.empty:

    print(
        dupes[
            [
                "match_id",
                "home_team",
                "away_team",
                "match_time",
                "home_odds",
                "draw_odds",
                "away_odds"
            ]
        ].to_string(index=False)
    )

    raise RuntimeError(
        "\n❌ DUPLICATE MATCH IDS DETECTED.\n"
        "The matcher produced multiple odds "
        "fixtures for the same database match ID.\n"
        "Bookmark was NOT modified."
    )


print("NONE")


# ============================================================
# JOIN PREDICTIONS
# ============================================================

df_matched = df_matched.merge(
    df_preds,
    on="match_id",
    how="left"
)


# ============================================================
# REMOVE MATCHES WITH NO PREDICTION
# ============================================================

before_predictions = len(
    df_matched
)


df_matched = df_matched.dropna(
    subset=[
        "p_home",
        "p_draw",
        "p_away"
    ],
    how="all"
)


removed_predictions = (
    before_predictions
    - len(df_matched)
)


print(
    f"\n🧠 Matches without predictions removed: "
    f"{removed_predictions}"
)


if df_matched.empty:

    print(
        "\n❌ No predictions available. "
        "Bookmark was NOT modified."
    )

    raise SystemExit(0)


# ============================================================
# CALCULATE EV
# ============================================================

df_matched["EV_home"] = (
    df_matched["p_home"]
    * df_matched["home_odds"]
    - 1
)


df_matched["EV_draw"] = (
    df_matched["p_draw"]
    * df_matched["draw_odds"]
    - 1
)


df_matched["EV_away"] = (
    df_matched["p_away"]
    * df_matched["away_odds"]
    - 1
)


# ============================================================
# BEST BET
# ============================================================

def best(row):

    evs = {
        "Home": row["EV_home"],
        "Draw": row["EV_draw"],
        "Away": row["EV_away"],
    }

    best_selection = max(
        evs,
        key=evs.get
    )

    return (
        best_selection,
        evs[best_selection]
    )


df_matched[
    ["Best", "EV"]
] = df_matched.apply(
    lambda row: pd.Series(best(row)),
    axis=1
)


# ============================================================
# FINAL DUPLICATE CHECK
#
# Check AGAIN after predictions merge.
# ============================================================

print(
    "\n=== FINAL DUPLICATE MATCH IDS ==="
)


final_dupes = df_matched[
    df_matched.duplicated(
        "match_id",
        keep=False
    )
].sort_values("match_id")


if not final_dupes.empty:

    print(
        final_dupes[
            [
                "match_id",
                "home_team",
                "away_team",
                "match_time",
                "home_odds",
                "draw_odds",
                "away_odds"
            ]
        ].to_string(index=False)
    )

    raise RuntimeError(
        "\n❌ Duplicate match IDs detected "
        "after prediction merge.\n"
        "Bookmark was NOT modified."
    )


print("NONE")


# ============================================================
# FINAL SUMMARY
# ============================================================

print(
    f"\n📊 Final bookmark rows: "
    f"{len(df_matched)}"
)


# ============================================================
# SAVE
#
# Only delete existing bookmark AFTER every validation
# above has passed.
# ============================================================

with engine.begin() as conn:

    conn.execute(
        text(
            "DELETE FROM henry_schema.bookmark"
        )
    )


# Explicit schema so there is absolutely no ambiguity.
df_matched.to_sql(
    "bookmark",
    engine,
    schema=DB_SCHEMA,
    if_exists="append",
    index=False
)


# ============================================================
# VERIFY DATABASE
# ============================================================

with engine.connect() as conn:

    saved_count = conn.execute(
        text(
            "SELECT COUNT(*) "
            "FROM henry_schema.bookmark"
        )
    ).scalar()


print(
    f"\n✅ Bookmark saved successfully "
    f"({saved_count} rows)"
)


if saved_count != len(df_matched):

    raise RuntimeError(
        f"❌ Verification failed: "
        f"expected {len(df_matched)} rows, "
        f"database contains {saved_count}."
    )


print(
    "\n🎉 book.py completed successfully."
)
