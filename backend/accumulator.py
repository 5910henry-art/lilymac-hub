#!/usr/bin/env python3
"""
accumulator.py — probability-only accumulator builder
PostgreSQL version using asyncpg

RULES:
- Insert ONLY if probability meets market threshold
- 3-way → predictions table
- Other markets → value table
- Matches must be SCHEDULED, TIMED, or POSTPONED
"""

import asyncio
import asyncpg
import json
from datetime import datetime, UTC
from config2 import DATABASE_URL

# ---------------- THRESHOLDS ----------------
THRESHOLDS = {
    "3-way": 0.55,
    "BTTS": 0.55,
    "O1.5": 0.65,
    "O2.5": 0.60,
    "O3.5": 0.60,
    "O4.5": 0.60,
}

ALLOWED_STATUSES = ("SCHEDULED", "POSTPONED", "TIMED")


# ---------------- HELPERS ----------------
def derive_3way(prediction_json: str):
    """Return (selection, probability)"""
    data = json.loads(prediction_json)
    probs = data["probabilities"]
    mapping = {"home_win": "HOME", "draw": "DRAW", "away_win": "AWAY"}
    key = max(probs, key=probs.get)
    return mapping[key], float(probs[key])


def ensure_utc_naive(dt):
    """Convert any datetime to naive UTC (NO timezone)"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def utc_naive_now():
    """Current UTC time as a naive datetime for DB storage."""
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------- POPULATE ----------------
async def populate_accumulator():
    conn = await asyncpg.connect(DATABASE_URL)

    now = utc_naive_now()
    inserted = 0

    try:
        # Clear previous accumulator
        await conn.execute("DELETE FROM accumulator")

        # Fetch matches joined with predictions + value
        rows = await conn.fetch(
            """
            SELECT
                m.id AS match_id,
                m.utcDate AS match_time,
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
            FROM matches m
            JOIN predictions p ON p.match_id = m.id
            JOIN value v ON v.match_id = m.id
            WHERE m.status = ANY($1::text[])
            """,
            ALLOWED_STATUSES,
        )

        insert_query = """
            INSERT INTO accumulator (
                match_id, home_team_id, away_team_id,
                market, selection, probability,
                prob_btts, prob_over_1_5,
                match_time, match_status,
                home_team_name, away_team_name,
                model_version, generated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
        """

        for row in rows:
            match_id = row["match_id"]
            home_team = row["home_team_name"]
            away_team = row["away_team_name"]
            model_version = row["model_version"]
            match_time = ensure_utc_naive(row["match_time"])

            base_args = [
                match_id,
                row["home_team_id"],
                row["away_team_id"],
            ]

            # ---------------- 3-WAY ----------------
            selection, prob = derive_3way(row["prediction_json"])
            if prob >= THRESHOLDS["3-way"]:
                await conn.execute(
                    insert_query,
                    *base_args,
                    "3-way",
                    selection,
                    prob,
                    row["conf_btts"],
                    row["conf_over_1_5"],
                    match_time,
                    row["match_status"],
                    home_team,
                    away_team,
                    model_version,
                    now,
                )
                inserted += 1

            # ---------------- BTTS ----------------
            prob_btts = row["conf_btts"]
            if prob_btts is not None and prob_btts >= THRESHOLDS["BTTS"]:
                await conn.execute(
                    insert_query,
                    *base_args,
                    "BTTS",
                    "YES",
                    prob_btts,
                    prob_btts,
                    row["conf_over_1_5"],
                    match_time,
                    row["match_status"],
                    home_team,
                    away_team,
                    model_version,
                    now,
                )
                inserted += 1

            # ---------------- OVERS ----------------
            overs = {
                "O1.5": row["conf_over_1_5"],
                "O2.5": row["conf_over_2_5"],
                "O3.5": row["conf_over_3_5"],
                "O4.5": row["conf_over_4_5"],
            }

            for market, prob in overs.items():
                if prob is not None and prob >= THRESHOLDS[market]:
                    await conn.execute(
                        insert_query,
                        *base_args,
                        market,
                        "OVER",
                        prob,
                        row["conf_btts"],
                        row["conf_over_1_5"],
                        match_time,
                        row["match_status"],
                        home_team,
                        away_team,
                        model_version,
                        now,
                    )
                    inserted += 1

        print(f"✅ Accumulator populated: {inserted} qualified tips")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(populate_accumulator())
