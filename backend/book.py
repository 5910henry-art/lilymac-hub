#!/usr/bin/env python3
"""
book.py
============================================================

LilyMac Hub bookmark generator.

Purpose:
    Match Odds API fixtures against Football API fixtures,
    attach the latest prediction for each Football API match,
    calculate EV, and safely rebuild henry_schema.bookmark.

IMPORTANT IDs:
    match_id       = Football API / matches.id
    odds_event_id  = The Odds API event ID

Features:
    - Season restricted to 2026
    - Directional home/away matching
    - Kickoff tolerance
    - H2H odds
    - Totals 0.5 / 1.5 / 2.5 / 3.5
    - GG / NG
    - Prediction deduplication
    - Duplicate ID protection
    - Safe transactional bookmark update
    - Automatic odds_event_id column creation
    - Preserves bookmarks referenced by bet_selection
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

SEASON = 2026

TIME_TOLERANCE_MINUTES = 120

TEAM_MATCH_THRESHOLD = 70


# ============================================================
# DATABASE ENGINE
# ============================================================

engine = create_engine(
    DATABASE_URL,
    future=True,
    connect_args={
        "options": f"-c search_path={DB_SCHEMA},public"
    }
)


print("=" * 70)
print("LILYMAC BOOKMARK GENERATOR")
print("=" * 70)

print("\n[CONFIG]")
print(f"Season:                  {SEASON}")
print(f"Time tolerance:          {TIME_TOLERANCE_MINUTES} minutes")
print(f"Team threshold:          {TEAM_MATCH_THRESHOLD}")
print(f"Schema:                  {DB_SCHEMA}")


# ============================================================
# HELPERS
# ============================================================

def normalize_team(name: str) -> str:
    """
    Normalize football team names for matching.
    """

    if not isinstance(name, str):
        return ""

    name = unicodedata.normalize("NFKD", name)

    name = (
        name
        .encode("ascii", "ignore")
        .decode("ascii")
    )

    name = name.lower()

    # Remove common football suffixes.
    name = re.sub(
        r"\b(fc|cf|ac|sc|afc|rc|club)\b",
        "",
        name
    )

    # Keep letters and spaces.
    name = re.sub(
        r"[^a-z ]",
        "",
        name
    )

    # Collapse whitespace.
    name = re.sub(
        r"\s+",
        " ",
        name
    )

    return name.strip()


def to_utc(series):
    """
    Convert timestamps to UTC and floor to minute.
    """

    dt = pd.to_datetime(
        series,
        errors="coerce",
        utc=True
    )

    return dt.dt.floor("min")


def numeric_or_none(value):
    """
    Convert pandas numeric values safely.
    """

    if pd.isna(value):
        return None

    return float(value)


# ============================================================
# ENSURE BOOKMARK HAS ODDS API ID
# ============================================================

print("\n[DATABASE] Checking bookmark schema...")

with engine.begin() as conn:

    exists = conn.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = :schema
                  AND table_name = 'bookmark'
                  AND column_name = 'odds_event_id'
            )
        """),
        {
            "schema": DB_SCHEMA
        }
    ).scalar()

    if not exists:

        print(
            "⚠️ odds_event_id missing from bookmark."
        )

        print(
            "→ Adding odds_event_id column..."
        )

        conn.execute(
            text("""
                ALTER TABLE henry_schema.bookmark
                ADD COLUMN odds_event_id TEXT
            """)
        )

        print(
            "✅ odds_event_id added."
        )

    else:

        print(
            "✅ odds_event_id already exists."
        )


# ============================================================
# LOAD ODDS
# ============================================================

print("\n[1/7] Loading Odds API data...")

df_odds = pd.read_sql(
    text("""
        SELECT
            id,
            league,
            home_team,
            away_team,
            home_team_norm,
            away_team_norm,
            match_time,

            home_odds,
            draw_odds,
            away_odds,

            over05,
            under05,

            over15,
            under15,

            over25,
            under25,

            over35,
            under35,

            gg_odds,
            ng_odds,

            fetched_at,
            odds_event_id

        FROM henry_schema.live_odds

        WHERE odds_event_id IS NOT NULL
    """),
    engine
)


print(
    f"   Odds rows loaded: {len(df_odds)}"
)


if df_odds.empty:

    raise RuntimeError(
        "\n❌ live_odds contains no rows.\n"
        "Run Odds.py first."
    )


# ============================================================
# LOAD ONLY SEASON 2026 MATCHES
# ============================================================

print(
    f"\n[2/7] Loading Football API matches "
    f"for season {SEASON}..."
)

df_matches = pd.read_sql(
    text("""
        SELECT *
        FROM henry_schema.matches
        WHERE season = :season
    """),
    engine,
    params={
        "season": SEASON
    }
)


print(
    f"   Season {SEASON} matches loaded: "
    f"{len(df_matches)}"
)


if df_matches.empty:

    raise RuntimeError(
        f"\n❌ No matches found for season {SEASON}."
    )


# ============================================================
# VERIFY REQUIRED MATCH COLUMNS
# ============================================================

required_match_columns = [
    "id",
    "home_team_name",
    "away_team_name",
]


missing_match_columns = [
    col
    for col in required_match_columns
    if col not in df_matches.columns
]


if missing_match_columns:

    raise RuntimeError(
        "\n❌ Missing required columns in matches:\n"
        + "\n".join(
            f"   - {col}"
            for col in missing_match_columns
        )
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

    raise RuntimeError(
        "\n❌ No match time column found.\n"
        f"Available columns:\n{list(df_matches.columns)}"
    )


print(
    f"   Football match time column: {time_col}"
)


# ============================================================
# LOAD LATEST UNIQUE PREDICTION PER MATCH
# ============================================================

print(
    "\n[3/7] Loading predictions..."
)

"""
IMPORTANT:

A match may have multiple prediction rows.

We select only ONE prediction per match_id:
    newest generated_at

This prevents:

    1 match
      ×
    2 predictions

from becoming:

    2 bookmark rows.
"""

df_preds = pd.read_sql(
    text("""
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
            )::float AS p_away,

            generated_at

        FROM (
            SELECT
                match_id,
                prediction_json,
                generated_at,

                ROW_NUMBER() OVER (
                    PARTITION BY match_id
                    ORDER BY generated_at DESC NULLS LAST
                ) AS rn

            FROM henry_schema.predictions
        ) p

        WHERE rn = 1
    """),
    engine
)


print(
    f"   Unique prediction rows: "
    f"{len(df_preds)}"
)


# ============================================================
# SAFETY CHECK PREDICTIONS
# ============================================================

prediction_duplicates = df_preds[
    df_preds.duplicated(
        "match_id",
        keep=False
    )
]


if not prediction_duplicates.empty:

    raise RuntimeError(
        "\n❌ Prediction deduplication failed.\n"
        "Multiple predictions still exist for the same match_id."
    )


print(
    "   ✅ Prediction IDs are unique."
)


# ============================================================
# NORMALIZE TEAM NAMES
# ============================================================

print(
    "\n[4/7] Normalizing team names..."
)

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
# NORMALIZE TIMES
# ============================================================

df_odds["match_time"] = to_utc(
    df_odds["match_time"]
)

df_matches["utcdate"] = to_utc(
    df_matches[time_col]
)


# ============================================================
# REMOVE INVALID ODDS TIMES
# ============================================================

invalid_odds_time = df_odds[
    df_odds["match_time"].isna()
]


if not invalid_odds_time.empty:

    print(
        f"\n⚠️ Removing "
        f"{len(invalid_odds_time)} odds rows "
        f"with invalid kickoff times."
    )

    df_odds = df_odds[
        df_odds["match_time"].notna()
    ].copy()


# ============================================================
# MATCH FIXTURES
# ============================================================

print(
    "\n[5/7] Matching Odds API fixtures "
    f"to Football API season {SEASON}..."
)

matched_rows = []
unmatched_rows = []


for _, odds in df_odds.iterrows():

    odds_home = odds["home_norm"]
    odds_away = odds["away_norm"]

    odds_time = odds["match_time"]

    if not odds_home or not odds_away:

        unmatched_rows.append(
            odds
        )

        continue


    # --------------------------------------------------------
    # TIME WINDOW
    # --------------------------------------------------------

    start = (
        odds_time
        - pd.Timedelta(
            minutes=TIME_TOLERANCE_MINUTES
        )
    )

    end = (
        odds_time
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
            f"   ❌ No time match: "
            f"{odds['home_team']} vs "
            f"{odds['away_team']}"
        )

        unmatched_rows.append(
            odds
        )

        continue


    # --------------------------------------------------------
    # BEST MATCH
    # --------------------------------------------------------

    found = None

    best_score = -1

    best_home_score = 0
    best_away_score = 0
    best_time_diff = None


    for _, match in candidates.iterrows():

        home_score = fuzz.token_sort_ratio(
            odds_home,
            match["home_norm"]
        )

        away_score = fuzz.token_sort_ratio(
            odds_away,
            match["away_norm"]
        )


        # ----------------------------------------------------
        # EXACT DIRECTIONAL MATCH
        # ----------------------------------------------------

        if (
            odds_home == match["home_norm"]
            and
            odds_away == match["away_norm"]
        ):

            found = match

            best_score = 1000

            best_home_score = 100

            best_away_score = 100

            best_time_diff = abs(
                (
                    odds_time
                    - match["utcdate"]
                ).total_seconds()
            ) / 60

            break


        # ----------------------------------------------------
        # BOTH TEAMS MUST PASS THRESHOLD
        # ----------------------------------------------------

        if (
            home_score < TEAM_MATCH_THRESHOLD
            or
            away_score < TEAM_MATCH_THRESHOLD
        ):

            continue


        time_diff = abs(
            (
                odds_time
                - match["utcdate"]
            ).total_seconds()
        ) / 60


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
                # Football API ID
                "match_id":
                    int(found["id"]),

                # Odds API ID
                "odds_event_id":
                    str(odds["odds_event_id"]),

                "league":
                    odds["league"],

                "home_team":
                    odds["home_team"],

                "away_team":
                    odds["away_team"],

                "match_time":
                    odds["match_time"],

                # H2H
                "home_odds":
                    odds["home_odds"],

                "draw_odds":
                    odds["draw_odds"],

                "away_odds":
                    odds["away_odds"],

                # Totals
                "over05":
                    odds["over05"],

                "under05":
                    odds["under05"],

                "over15":
                    odds["over15"],

                "under15":
                    odds["under15"],

                "over25":
                    odds["over25"],

                "under25":
                    odds["under25"],

                "over35":
                    odds["over35"],

                "under35":
                    odds["under35"],

                # BTTS
                "gg_odds":
                    odds["gg_odds"],

                "ng_odds":
                    odds["ng_odds"],

                # Debug information
                "_home_score":
                    best_home_score,

                "_away_score":
                    best_away_score,

                "_time_diff":
                    best_time_diff,
            }
        )

    else:

        print(
            f"   ⚠️ Rejected: "
            f"{odds['home_team']} vs "
            f"{odds['away_team']}"
        )

        unmatched_rows.append(
            odds
        )


# ============================================================
# BUILD MATCHED DATAFRAME
# ============================================================

df_matched = pd.DataFrame(
    matched_rows
)

df_unmatched = pd.DataFrame(
    unmatched_rows
)


print(
    f"\n   ✅ Odds fixtures matched: "
    f"{len(df_matched)}"
)

print(
    f"   ⚠️ Odds fixtures unmatched: "
    f"{len(df_unmatched)}"
)


if df_matched.empty:

    raise RuntimeError(
        "\n❌ Nothing matched.\n"
        "Existing bookmark was NOT modified."
    )


# ============================================================
# DUPLICATE FOOTBALL MATCH ID CHECK
# ============================================================

print(
    "\n[CHECK 1] Duplicate Football match IDs..."
)

duplicate_match_ids = df_matched[
    df_matched.duplicated(
        "match_id",
        keep=False
    )
].sort_values(
    "match_id"
)


if not duplicate_match_ids.empty:

    print(
        duplicate_match_ids[
            [
                "match_id",
                "odds_event_id",
                "league",
                "home_team",
                "away_team",
                "match_time"
            ]
        ].to_string(index=False)
    )

    raise RuntimeError(
        "\n❌ DUPLICATE FOOTBALL match_id DETECTED.\n"
        "Bookmark was NOT modified."
    )


print(
    "   ✅ Football match_id values are unique."
)


# ============================================================
# DUPLICATE ODDS EVENT ID CHECK
# ============================================================

print(
    "\n[CHECK 2] Duplicate Odds API event IDs..."
)

duplicate_odds_ids = df_matched[
    df_matched.duplicated(
        "odds_event_id",
        keep=False
    )
].sort_values(
    "odds_event_id"
)


if not duplicate_odds_ids.empty:

    print(
        duplicate_odds_ids[
            [
                "match_id",
                "odds_event_id",
                "league",
                "home_team",
                "away_team",
                "match_time"
            ]
        ].to_string(index=False)
    )

    raise RuntimeError(
        "\n❌ DUPLICATE Odds API odds_event_id DETECTED.\n"
        "Bookmark was NOT modified."
    )


print(
    "   ✅ Odds API event IDs are unique."
)


# ============================================================
# JOIN PREDICTIONS
# ============================================================

print(
    "\n[6/7] Joining predictions..."
)


df_matched = df_matched.merge(
    df_preds[
        [
            "match_id",
            "p_home",
            "p_draw",
            "p_away",
            "generated_at"
        ]
    ],
    on="match_id",
    how="left",
    validate="one_to_one"
)


# ============================================================
# REMOVE MATCHES WITHOUT PREDICTION
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
).copy()


removed_predictions = (
    before_predictions
    - len(df_matched)
)


print(
    f"   Matches without predictions removed: "
    f"{removed_predictions}"
)


if df_matched.empty:

    raise RuntimeError(
        "\n❌ No matched fixtures have predictions.\n"
        "Bookmark was NOT modified."
    )


# ============================================================
# PREDICTION VALIDATION
# ============================================================

print(
    "\n[CHECK 3] Validating prediction probabilities..."
)


def probability_valid(value):

    return (
        pd.notna(value)
        and
        0 <= float(value) <= 1
    )


invalid_probability_rows = df_matched[
    ~df_matched["p_home"].apply(probability_valid)
    |
    ~df_matched["p_draw"].apply(probability_valid)
    |
    ~df_matched["p_away"].apply(probability_valid)
]


if not invalid_probability_rows.empty:

    print(
        invalid_probability_rows[
            [
                "match_id",
                "home_team",
                "away_team",
                "p_home",
                "p_draw",
                "p_away"
            ]
        ].to_string(index=False)
    )

    raise RuntimeError(
        "\n❌ Invalid prediction probability detected.\n"
        "Bookmark was NOT modified."
    )


print(
    "   ✅ Prediction probabilities valid."
)


# ============================================================
# CALCULATE EV
# ============================================================

print(
    "\n[CALC] Calculating expected value..."
)


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

def calculate_best(row):

    evs = {
        "Home": row["EV_home"],
        "Draw": row["EV_draw"],
        "Away": row["EV_away"],
    }

    # Remove unavailable markets.
    evs = {
        key: value
        for key, value in evs.items()
        if pd.notna(value)
    }

    if not evs:

        return (
            None,
            None
        )

    selection = max(
        evs,
        key=evs.get
    )

    return (
        selection,
        evs[selection]
    )


df_matched[
    ["Best", "EV"]
] = df_matched.apply(
    lambda row: pd.Series(
        calculate_best(row)
    ),
    axis=1
)


# ============================================================
# FINAL DUPLICATE CHECK
# ============================================================

print(
    "\n[CHECK 4] Final duplicate protection..."
)


final_match_dupes = df_matched[
    df_matched.duplicated(
        "match_id",
        keep=False
    )
]


if not final_match_dupes.empty:

    raise RuntimeError(
        "\n❌ Duplicate match_id after prediction merge.\n"
        "Bookmark was NOT modified."
    )


final_odds_dupes = df_matched[
    df_matched.duplicated(
        "odds_event_id",
        keep=False
    )
]


if not final_odds_dupes.empty:

    raise RuntimeError(
        "\n❌ Duplicate odds_event_id after prediction merge.\n"
        "Bookmark was NOT modified."
    )


print(
    "   ✅ Final IDs are unique."
)


# ============================================================
# REMOVE INTERNAL DEBUG COLUMNS
# ============================================================

df_matched = df_matched.drop(
    columns=[
        "_home_score",
        "_away_score",
        "_time_diff"
    ],
    errors="ignore"
)


# ============================================================
# PREPARE GENERATED_AT
# ============================================================

df_matched["generated_at"] = pd.to_datetime(
    df_matched["generated_at"],
    errors="coerce"
)


# Bookmark uses timestamp without timezone.
if hasattr(
    df_matched["generated_at"].dt,
    "tz"
):

    if df_matched["generated_at"].dt.tz is not None:

        df_matched["generated_at"] = (
            df_matched["generated_at"]
            .dt.tz_convert("UTC")
            .dt.tz_localize(None)
        )


# ============================================================
# PREPARE MATCH TIME
# ============================================================

df_matched["match_time"] = pd.to_datetime(
    df_matched["match_time"],
    errors="coerce",
    utc=True
)


df_matched["match_time"] = (
    df_matched["match_time"]
    .dt.tz_convert("UTC")
    .dt.tz_localize(None)
)


# ============================================================
# FINAL COLUMN ORDER
# ============================================================

bookmark_columns = [
    "match_id",
    "odds_event_id",

    "league",

    "home_team",
    "away_team",

    "match_time",

    "home_odds",
    "draw_odds",
    "away_odds",

    "over05",
    "under05",

    "over15",
    "under15",

    "over25",
    "under25",

    "over35",
    "under35",

    "gg_odds",
    "ng_odds",

    "p_home",
    "p_draw",
    "p_away",

    "generated_at",

    "EV_home",
    "EV_draw",
    "EV_away",

    "Best",
    "EV",
]


missing_bookmark_columns = [
    col
    for col in bookmark_columns
    if col not in df_matched.columns
]


if missing_bookmark_columns:

    raise RuntimeError(
        "\n❌ Missing final bookmark columns:\n"
        + "\n".join(
            f"   - {col}"
            for col in missing_bookmark_columns
        )
    )


df_matched = df_matched[
    bookmark_columns
].copy()


# ============================================================
# FINAL NULL / DATA VALIDATION
# ============================================================

print(
    "\n[CHECK 5] Final data validation..."
)


if df_matched["match_id"].isna().any():

    raise RuntimeError(
        "❌ NULL match_id detected."
    )


if df_matched["odds_event_id"].isna().any():

    raise RuntimeError(
        "❌ NULL odds_event_id detected."
    )


if df_matched["odds_event_id"].astype(str).str.strip().eq("").any():

    raise RuntimeError(
        "❌ Empty odds_event_id detected."
    )


if df_matched["home_team"].isna().any():

    raise RuntimeError(
        "❌ NULL home_team detected."
    )


if df_matched["away_team"].isna().any():

    raise RuntimeError(
        "❌ NULL away_team detected."
    )


print(
    "   ✅ Final data passed validation."
)


# ============================================================
# SUMMARY BEFORE DATABASE CHANGE
# ============================================================

print(
    "\n" + "=" * 70
)

print(
    "BOOKMARK REBUILD SUMMARY"
)

print(
    "=" * 70
)

print(
    f"Season:                 {SEASON}"
)

print(
    f"Odds fixtures loaded:   {len(df_odds)}"
)

print(
    f"Fixtures matched:       {len(df_matched)}"
)

print(
    f"Fixtures unmatched:     {len(df_unmatched)}"
)

print(
    f"Unique match IDs:       "
    f"{df_matched['match_id'].nunique()}"
)

print(
    f"Unique odds event IDs:  "
    f"{df_matched['odds_event_id'].nunique()}"
)


print(
    "\nMarkets preserved:"
)

print(
    "   H2H       → Home / Draw / Away"
)

print(
    "   Totals    → O/U 0.5, 1.5, 2.5, 3.5"
)

print(
    "   BTTS      → GG / NG"
)


# ============================================================
# SAFE DATABASE UPDATE
# ============================================================

print(
    "\n[7/7] Safely updating bookmark..."
)


"""
CRITICAL DATABASE DESIGN:

bookmark.match_id is the PRIMARY KEY.

bet_selection.bookmark_id references:

    bookmark(match_id)

Therefore we CANNOT do:

    DELETE FROM bookmark

because existing bets may reference those rows.

Instead:

    UPDATE existing bookmarks
    INSERT new bookmarks
    DELETE stale bookmarks ONLY when unreferenced

Everything happens inside ONE transaction.

If anything fails, PostgreSQL rolls back everything.
"""


try:

    with engine.begin() as conn:

        # ====================================================
        # EXISTING BOOKMARK COUNT
        # ====================================================

        old_count = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM henry_schema.bookmark
            """)
        ).scalar()


        print(
            f"   Existing bookmark rows: "
            f"{old_count}"
        )


        # ====================================================
        # EXISTING MATCH IDs
        # ====================================================

        existing_rows = conn.execute(
            text("""
                SELECT match_id
                FROM henry_schema.bookmark
            """)
        ).fetchall()


        existing_match_ids = {
            int(row[0])
            for row in existing_rows
        }


        # ====================================================
        # NEW MATCH IDs
        # ====================================================

        new_match_ids = {
            int(value)
            for value in df_matched["match_id"]
        }


        update_ids = (
            existing_match_ids
            &
            new_match_ids
        )


        insert_ids = (
            new_match_ids
            -
            existing_match_ids
        )


        stale_ids = (
            existing_match_ids
            -
            new_match_ids
        )


        print(
            f"   Existing matches to update: "
            f"{len(update_ids)}"
        )

        print(
            f"   New matches to insert:       "
            f"{len(insert_ids)}"
        )

        print(
            f"   Potential stale bookmarks:   "
            f"{len(stale_ids)}"
        )


        # ====================================================
        # UPDATE EXISTING BOOKMARKS
        # ====================================================

        update_sql = text("""
            UPDATE henry_schema.bookmark
            SET
                odds_event_id = :odds_event_id,
                league = :league,
                home_team = :home_team,
                away_team = :away_team,
                match_time = :match_time,

                home_odds = :home_odds,
                draw_odds = :draw_odds,
                away_odds = :away_odds,

                over05 = :over05,
                under05 = :under05,

                over15 = :over15,
                under15 = :under15,

                over25 = :over25,
                under25 = :under25,

                over35 = :over35,
                under35 = :under35,

                gg_odds = :gg_odds,
                ng_odds = :ng_odds,

                p_home = :p_home,
                p_draw = :p_draw,
                p_away = :p_away,

                generated_at = :generated_at,

                "EV_home" = :EV_home,
                "EV_draw" = :EV_draw,
                "EV_away" = :EV_away,

                "Best" = :Best,
                "EV" = :EV

            WHERE match_id = :match_id
        """)


        update_count = 0


        if update_ids:

            update_rows = df_matched[
                df_matched["match_id"].isin(
                    update_ids
                )
            ].copy()


            for _, row in update_rows.iterrows():

                params = {
                    "match_id":
                        int(row["match_id"]),

                    "odds_event_id":
                        str(row["odds_event_id"]),

                    "league":
                        row["league"],

                    "home_team":
                        row["home_team"],

                    "away_team":
                        row["away_team"],

                    "match_time":
                        row["match_time"],

                    "home_odds":
                        numeric_or_none(
                            row["home_odds"]
                        ),

                    "draw_odds":
                        numeric_or_none(
                            row["draw_odds"]
                        ),

                    "away_odds":
                        numeric_or_none(
                            row["away_odds"]
                        ),

                    "over05":
                        numeric_or_none(
                            row["over05"]
                        ),

                    "under05":
                        numeric_or_none(
                            row["under05"]
                        ),

                    "over15":
                        numeric_or_none(
                            row["over15"]
                        ),

                    "under15":
                        numeric_or_none(
                            row["under15"]
                        ),

                    "over25":
                        numeric_or_none(
                            row["over25"]
                        ),

                    "under25":
                        numeric_or_none(
                            row["under25"]
                        ),

                    "over35":
                        numeric_or_none(
                            row["over35"]
                        ),

                    "under35":
                        numeric_or_none(
                            row["under35"]
                        ),

                    "gg_odds":
                        numeric_or_none(
                            row["gg_odds"]
                        ),

                    "ng_odds":
                        numeric_or_none(
                            row["ng_odds"]
                        ),

                    "p_home":
                        numeric_or_none(
                            row["p_home"]
                        ),

                    "p_draw":
                        numeric_or_none(
                            row["p_draw"]
                        ),

                    "p_away":
                        numeric_or_none(
                            row["p_away"]
                        ),

                    "generated_at":
                        row["generated_at"],

                    "EV_home":
                        numeric_or_none(
                            row["EV_home"]
                        ),

                    "EV_draw":
                        numeric_or_none(
                            row["EV_draw"]
                        ),

                    "EV_away":
                        numeric_or_none(
                            row["EV_away"]
                        ),

                    "Best":
                        row["Best"],

                    "EV":
                        numeric_or_none(
                            row["EV"]
                        ),
                }


                conn.execute(
                    update_sql,
                    params
                )

                update_count += 1


        print(
            f"   ✅ Existing bookmarks updated: "
            f"{update_count}"
        )


        # ====================================================
        # INSERT NEW BOOKMARKS
        # ====================================================

        insert_sql = text("""
            INSERT INTO henry_schema.bookmark (
                match_id,
                odds_event_id,

                league,

                home_team,
                away_team,

                match_time,

                home_odds,
                draw_odds,
                away_odds,

                over05,
                under05,

                over15,
                under15,

                over25,
                under25,

                over35,
                under35,

                gg_odds,
                ng_odds,

                p_home,
                p_draw,
                p_away,

                generated_at,

                "EV_home",
                "EV_draw",
                "EV_away",

                "Best",
                "EV"
            )
            VALUES (
                :match_id,
                :odds_event_id,

                :league,

                :home_team,
                :away_team,

                :match_time,

                :home_odds,
                :draw_odds,
                :away_odds,

                :over05,
                :under05,

                :over15,
                :under15,

                :over25,
                :under25,

                :over35,
                :under35,

                :gg_odds,
                :ng_odds,

                :p_home,
                :p_draw,
                :p_away,

                :generated_at,

                :EV_home,
                :EV_draw,
                :EV_away,

                :Best,
                :EV
            )
        """)


        insert_count = 0


        if insert_ids:

            insert_rows = df_matched[
                df_matched["match_id"].isin(
                    insert_ids
                )
            ].copy()


            for _, row in insert_rows.iterrows():

                params = {
                    "match_id":
                        int(row["match_id"]),

                    "odds_event_id":
                        str(row["odds_event_id"]),

                    "league":
                        row["league"],

                    "home_team":
                        row["home_team"],

                    "away_team":
                        row["away_team"],

                    "match_time":
                        row["match_time"],

                    "home_odds":
                        numeric_or_none(
                            row["home_odds"]
                        ),

                    "draw_odds":
                        numeric_or_none(
                            row["draw_odds"]
                        ),

                    "away_odds":
                        numeric_or_none(
                            row["away_odds"]
                        ),

                    "over05":
                        numeric_or_none(
                            row["over05"]
                        ),

                    "under05":
                        numeric_or_none(
                            row["under05"]
                        ),

                    "over15":
                        numeric_or_none(
                            row["over15"]
                        ),

                    "under15":
                        numeric_or_none(
                            row["under15"]
                        ),

                    "over25":
                        numeric_or_none(
                            row["over25"]
                        ),

                    "under25":
                        numeric_or_none(
                            row["under25"]
                        ),

                    "over35":
                        numeric_or_none(
                            row["over35"]
                        ),

                    "under35":
                        numeric_or_none(
                            row["under35"]
                        ),

                    "gg_odds":
                        numeric_or_none(
                            row["gg_odds"]
                        ),

                    "ng_odds":
                        numeric_or_none(
                            row["ng_odds"]
                        ),

                    "p_home":
                        numeric_or_none(
                            row["p_home"]
                        ),

                    "p_draw":
                        numeric_or_none(
                            row["p_draw"]
                        ),

                    "p_away":
                        numeric_or_none(
                            row["p_away"]
                        ),

                    "generated_at":
                        row["generated_at"],

                    "EV_home":
                        numeric_or_none(
                            row["EV_home"]
                        ),

                    "EV_draw":
                        numeric_or_none(
                            row["EV_draw"]
                        ),

                    "EV_away":
                        numeric_or_none(
                            row["EV_away"]
                        ),

                    "Best":
                        row["Best"],

                    "EV":
                        numeric_or_none(
                            row["EV"]
                        ),
                }


                conn.execute(
                    insert_sql,
                    params
                )

                insert_count += 1


        print(
            f"   ✅ New bookmarks inserted: "
            f"{insert_count}"
        )


        # ====================================================
        # SAFE STALE BOOKMARK CLEANUP
        # ====================================================

        """
        A bookmark is stale when it no longer exists in the
        freshly generated df_matched dataset.

        We may delete it ONLY if no bet_selection references
        its match_id.

        Referenced stale bookmarks are deliberately preserved.
        """

        deleted_stale = 0
        protected_stale = 0


        if stale_ids:

            for stale_match_id in stale_ids:

                dependent_count = conn.execute(
                    text("""
                        SELECT COUNT(*)
                        FROM henry_schema.bet_selection
                        WHERE bookmark_id = :match_id
                    """),
                    {
                        "match_id":
                            stale_match_id
                    }
                ).scalar()


                if dependent_count == 0:

                    conn.execute(
                        text("""
                            DELETE FROM henry_schema.bookmark
                            WHERE match_id = :match_id
                        """),
                        {
                            "match_id":
                                stale_match_id
                        }
                    )

                    deleted_stale += 1

                else:

                    protected_stale += 1

                    print(
                        f"   ⚠️ Preserved referenced stale "
                        f"bookmark: {stale_match_id} "
                        f"({dependent_count} bet selection(s))"
                    )


        print(
            f"   ✅ Stale bookmarks deleted: "
            f"{deleted_stale}"
        )

        print(
            f"   🛡️ Stale bookmarks protected: "
            f"{protected_stale}"
        )


        # ====================================================
        # VERIFY NO BROKEN BET REFERENCES
        # ====================================================

        broken_references = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM henry_schema.bet_selection bs
                LEFT JOIN henry_schema.bookmark b
                    ON b.match_id = bs.bookmark_id
                WHERE b.match_id IS NULL
            """)
        ).scalar()


        if broken_references != 0:

            raise RuntimeError(
                "\n❌ BROKEN BET REFERENCES DETECTED.\n"
                f"Broken references: {broken_references}\n"
                "Transaction will be rolled back."
            )


        print(
            "   ✅ All bet_selection bookmark references valid."
        )


        # ====================================================
        # VERIFY BOOKMARK COUNT
        # ====================================================

        saved_count = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM henry_schema.bookmark
            """)
        ).scalar()


        # ====================================================
        # VERIFY DUPLICATE MATCH IDs
        # ====================================================

        duplicate_match_count = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM (
                    SELECT match_id
                    FROM henry_schema.bookmark
                    GROUP BY match_id
                    HAVING COUNT(*) > 1
                ) d
            """)
        ).scalar()


        if duplicate_match_count != 0:

            raise RuntimeError(
                "\n❌ Database contains duplicate match_id.\n"
                "Transaction will be rolled back."
            )


        # ====================================================
        # VERIFY DUPLICATE ODDS EVENT IDs
        # ====================================================

        duplicate_odds_count = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM (
                    SELECT odds_event_id
                    FROM henry_schema.bookmark
                    WHERE odds_event_id IS NOT NULL
                    GROUP BY odds_event_id
                    HAVING COUNT(*) > 1
                ) d
            """)
        ).scalar()


        if duplicate_odds_count != 0:

            raise RuntimeError(
                "\n❌ Database contains duplicate odds_event_id.\n"
                "Transaction will be rolled back."
            )


        print(
            f"   ✅ Database verification passed: "
            f"{saved_count} rows"
        )


except Exception as exc:

    print(
        "\n" + "=" * 70
    )

    print(
        "❌ BOOKMARK UPDATE FAILED"
    )

    print(
        "=" * 70
    )

    print(
        str(exc)
    )

    print(
        "\n⚠️ Transaction rolled back."
    )

    print(
        "⚠️ Existing bookmarks were NOT permanently modified."
    )

    raise


# ============================================================
# FINAL DATABASE VERIFICATION
# ============================================================

with engine.connect() as conn:

    final_count = conn.execute(
        text("""
            SELECT COUNT(*)
            FROM henry_schema.bookmark
        """)
    ).scalar()


    final_match_ids = conn.execute(
        text("""
            SELECT COUNT(DISTINCT match_id)
            FROM henry_schema.bookmark
        """)
    ).scalar()


    final_odds_ids = conn.execute(
        text("""
            SELECT COUNT(DISTINCT odds_event_id)
            FROM henry_schema.bookmark
            WHERE odds_event_id IS NOT NULL
        """)
    ).scalar()


    final_broken_refs = conn.execute(
        text("""
            SELECT COUNT(*)
            FROM henry_schema.bet_selection bs
            LEFT JOIN henry_schema.bookmark b
                ON b.match_id = bs.bookmark_id
            WHERE b.match_id IS NULL
        """)
    ).scalar()


print(
    "\n" + "=" * 70
)

print(
    "🎉 BOOKMARK REBUILD SUCCESSFUL"
)

print(
    "=" * 70
)

print(
    f"Rows saved:             {final_count}"
)

print(
    f"Unique match_id:        {final_match_ids}"
)

print(
    f"Unique odds_event_id:   {final_odds_ids}"
)

print(
    f"Broken bet references:  {final_broken_refs}"
)

print(
    f"Season:                 {SEASON}"
)

print(
    "\nFootball API ID: match_id"
)

print(
    "Odds API ID:     odds_event_id"
)

print(
    "\nAll requested odds markets preserved."
)

print(
    "\nExisting bet_selection references preserved."
)

print(
    "\n✅ book.py completed successfully."
)
