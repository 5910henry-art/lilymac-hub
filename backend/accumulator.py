#!/usr/bin/env python3
"""
accumulator.py — optimized probability-only accumulator builder

PostgreSQL + asyncpg

RULES:
- Insert ONLY if probability meets market threshold
- 3-way → prediction probability
- BTTS → value probability
- O1.5/O2.5/O3.5/O4.5 → value probabilities
- Matches must be SCHEDULED, POSTPONED, or TIMED

OPTIMIZATIONS:
- Explicit henry_schema usage
- One database transaction
- Bulk executemany() insertion
- No INSERT round-trip per individual tip
- Single fetch of eligible matches
"""

import asyncio
import asyncpg
import json
from datetime import datetime, UTC

from config2 import DATABASE_URL


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

DB_SCHEMA = "henry_schema"


# --------------------------------------------------
# THRESHOLDS
# --------------------------------------------------

THRESHOLDS = {
    "3-way": 0.55,
    "BTTS": 0.55,
    "O1.5": 0.65,
    "O2.5": 0.60,
    "O3.5": 0.60,
    "O4.5": 0.60,
}


# --------------------------------------------------
# ALLOWED MATCH STATUSES
# --------------------------------------------------

ALLOWED_STATUSES = (
    "SCHEDULED",
    "POSTPONED",
    "TIMED",
)


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def derive_3way(prediction_json):
    """
    Return:
        (selection, probability)
    """

    if isinstance(prediction_json, str):
        data = json.loads(prediction_json)
    else:
        data = prediction_json

    probs = data["probabilities"]

    mapping = {
        "home_win": "HOME",
        "draw": "DRAW",
        "away_win": "AWAY",
    }

    key = max(probs, key=probs.get)

    return (
        mapping[key],
        float(probs[key]),
    )


def ensure_utc_naive(dt):
    """
    Convert datetime to naive UTC.
    """

    if dt is None:
        return None

    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(
            tzinfo=None
        )

    return dt


def utc_naive_now():
    """
    Current UTC time as naive datetime.
    """

    return datetime.now(UTC).replace(
        tzinfo=None
    )


# --------------------------------------------------
# BUILD ONE ACCUMULATOR ROW
# --------------------------------------------------

def build_rows(row, generated_at):
    """
    Convert one database match row into zero or more
    accumulator rows.
    """

    results = []

    match_id = row["match_id"]

    home_team_id = row["home_team_id"]
    away_team_id = row["away_team_id"]

    home_team_name = row["home_team_name"]
    away_team_name = row["away_team_name"]

    match_time = ensure_utc_naive(
        row["match_time"]
    )

    match_status = row["match_status"]

    model_version = row["model_version"]

    # ----------------------------------------------
    # 3-WAY
    # ----------------------------------------------

    try:

        selection, probability = derive_3way(
            row["prediction_json"]
        )

        if probability >= THRESHOLDS["3-way"]:

            results.append(
                (
                    match_id,
                    home_team_id,
                    away_team_id,
                    "3-way",
                    selection,
                    probability,
                    row["conf_btts"],
                    row["conf_over_1_5"],
                    match_time,
                    match_status,
                    home_team_name,
                    away_team_name,
                    model_version,
                    generated_at,
                )
            )

    except (
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ):

        # Invalid prediction data.
        # Skip only this match.
        return results

    # ----------------------------------------------
    # BTTS
    # ----------------------------------------------

    prob_btts = row["conf_btts"]

    if (
        prob_btts is not None
        and prob_btts >= THRESHOLDS["BTTS"]
    ):

        results.append(
            (
                match_id,
                home_team_id,
                away_team_id,
                "BTTS",
                "YES",
                float(prob_btts),
                prob_btts,
                row["conf_over_1_5"],
                match_time,
                match_status,
                home_team_name,
                away_team_name,
                model_version,
                generated_at,
            )
        )

    # ----------------------------------------------
    # OVERS
    # ----------------------------------------------

    overs = (
        ("O1.5", row["conf_over_1_5"]),
        ("O2.5", row["conf_over_2_5"]),
        ("O3.5", row["conf_over_3_5"]),
        ("O4.5", row["conf_over_4_5"]),
    )

    for market, probability in overs:

        if (
            probability is not None
            and probability >= THRESHOLDS[market]
        ):

            results.append(
                (
                    match_id,
                    home_team_id,
                    away_team_id,
                    market,
                    "OVER",
                    float(probability),
                    row["conf_btts"],
                    row["conf_over_1_5"],
                    match_time,
                    match_status,
                    home_team_name,
                    away_team_name,
                    model_version,
                    generated_at,
                )
            )

    return results


# --------------------------------------------------
# MAIN BUILDER
# --------------------------------------------------

async def populate_accumulator():

    print(
        "==================================================",
        flush=True,
    )

    print(
        "LILYMAC ACCUMULATOR BUILDER — OPTIMIZED",
        flush=True,
    )

    print(
        "==================================================",
        flush=True,
    )

    print(
        f"[DATABASE] Schema: {DB_SCHEMA}",
        flush=True,
    )

    conn = None

    try:

        # ------------------------------------------
        # CONNECT
        # ------------------------------------------

        print(
            "[DATABASE] Connecting...",
            flush=True,
        )

        conn = await asyncpg.connect(
            DATABASE_URL
        )

        print(
            "[DATABASE] Connected.",
            flush=True,
        )

        # ------------------------------------------
        # SEARCH PATH
        # ------------------------------------------

        await conn.execute(
            f"SET search_path TO {DB_SCHEMA}, public"
        )

        print(
            "[DATABASE] Search path:",
            await conn.fetchval(
                "SHOW search_path"
            ),
            flush=True,
        )

        # ------------------------------------------
        # VERIFY TABLE
        # ------------------------------------------

        table = await conn.fetchval(
            """
            SELECT to_regclass($1)
            """,
            f"{DB_SCHEMA}.accumulator",
        )

        if table is None:

            raise RuntimeError(
                f"{DB_SCHEMA}.accumulator does not exist"
            )

        print(
            f"[DATABASE] Table verified: {table}",
            flush=True,
        )

        generated_at = utc_naive_now()

        # ------------------------------------------
        # FETCH DATA
        # ------------------------------------------

        print(
            "[ACCUMULATOR] Fetching "
            "predictions + value...",
            flush=True,
        )

        rows = await conn.fetch(
            f"""
            SELECT
                m.id AS match_id,
                m.utcdate AS match_time,
                m.status AS match_status,

                m.home_team_id,
                m.away_team_id,

                m.home_team_name,
                m.away_team_name,

                p.prediction_json,
                p.model_version,

                v.conf_btts,
                v.conf_over_1_5,
                v.conf_over_2_5,
                v.conf_over_3_5,
                v.conf_over_4_5

            FROM {DB_SCHEMA}.matches AS m

            INNER JOIN {DB_SCHEMA}.predictions AS p
                ON p.match_id = m.id

            INNER JOIN {DB_SCHEMA}.value AS v
                ON v.match_id = m.id

            WHERE m.status = ANY($1::text[])

            ORDER BY m.utcdate ASC
            """,
            ALLOWED_STATUSES,
        )

        print(
            f"[ACCUMULATOR] Eligible matches: "
            f"{len(rows)}",
            flush=True,
        )

        # ------------------------------------------
        # BUILD INSERT DATA IN MEMORY
        # ------------------------------------------

        print(
            "[ACCUMULATOR] Calculating qualified tips...",
            flush=True,
        )

        accumulator_rows = []

        invalid_predictions = 0

        for row in rows:

            before = len(accumulator_rows)

            generated_rows = build_rows(
                row,
                generated_at,
            )

            accumulator_rows.extend(
                generated_rows
            )

            # A row with prediction JSON problems
            # produces no 3-way result, but may still
            # have other valid markets. We don't count
            # those as invalid unless necessary.

            if (
                len(generated_rows) == 0
                and len(accumulator_rows) == before
            ):
                invalid_predictions += 1

        print(
            f"[ACCUMULATOR] Qualified tips: "
            f"{len(accumulator_rows)}",
            flush=True,
        )

        # ------------------------------------------
        # TRANSACTION
        # ------------------------------------------

        print(
            "[DATABASE] Starting transaction...",
            flush=True,
        )

        async with conn.transaction():

            # --------------------------------------
            # CLEAR OLD DATA
            # --------------------------------------

            await conn.execute(
                f"""
                DELETE FROM {DB_SCHEMA}.accumulator
                """
            )

            # --------------------------------------
            # BULK INSERT
            # --------------------------------------

            if accumulator_rows:

                insert_query = f"""
                    INSERT INTO {DB_SCHEMA}.accumulator (
                        match_id,
                        home_team_id,
                        away_team_id,
                        market,
                        selection,
                        probability,
                        prob_btts,
                        prob_over_1_5,
                        match_time,
                        match_status,
                        home_team_name,
                        away_team_name,
                        model_version,
                        generated_at
                    )
                    VALUES (
                        $1,
                        $2,
                        $3,
                        $4,
                        $5,
                        $6,
                        $7,
                        $8,
                        $9,
                        $10,
                        $11,
                        $12,
                        $13,
                        $14
                    )
                """

                print(
                    "[DATABASE] Bulk inserting...",
                    flush=True,
                )

                await conn.executemany(
                    insert_query,
                    accumulator_rows,
                )

        # ------------------------------------------
        # VERIFY
        # ------------------------------------------

        final_count = await conn.fetchval(
            f"""
            SELECT COUNT(*)
            FROM {DB_SCHEMA}.accumulator
            """
        )

        distinct_matches = await conn.fetchval(
            f"""
            SELECT COUNT(DISTINCT match_id)
            FROM {DB_SCHEMA}.accumulator
            """
        )

        print(
            "",
            flush=True,
        )

        print(
            "==================================================",
            flush=True,
        )

        print(
            "✅ ACCUMULATOR COMPLETE",
            flush=True,
        )

        print(
            f"   Qualified tips : {len(accumulator_rows)}",
            flush=True,
        )

        print(
            f"   Database rows   : {final_count}",
            flush=True,
        )

        print(
            f"   Matches covered : {distinct_matches}",
            flush=True,
        )

        if invalid_predictions:

            print(
                f"   Invalid/empty predictions: "
                f"{invalid_predictions}",
                flush=True,
            )

        print(
            "==================================================",
            flush=True,
        )

    except Exception as exc:

        print(
            "",
            flush=True,
        )

        print(
            "❌ ACCUMULATOR ERROR",
            flush=True,
        )

        print(
            f"   {type(exc).__name__}: {exc}",
            flush=True,
        )

        raise

    finally:

        if conn is not None:

            await conn.close()

            print(
                "[DATABASE] Connection closed.",
                flush=True,
            )


# --------------------------------------------------
# ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":

    try:

        asyncio.run(
            populate_accumulator()
        )

    except KeyboardInterrupt:

        print(
            "\n[CTRL+C] Accumulator stopped.",
            flush=True,
        )
