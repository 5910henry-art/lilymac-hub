#!/usr/bin/env python3
"""
h2h.py
Populate H2H table from matches table.

Optimized version:
- Uses the centralized config2.py database URL.
- Uses henry_schema automatically.
- Fetches ONLY finished matches not already in H2H.
- Uses PostgreSQL NOT EXISTS for incremental processing.
- Uses psycopg2 execute_values for bulk insertion.
- Keeps ON CONFLICT as a safety net.
"""

from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

from config2 import DB_CONNECT_URL, DB_SCHEMA


def db_connect():
    """Open a PostgreSQL connection using the configured schema."""
    return psycopg2.connect(
        DB_CONNECT_URL,
        options=f"-c search_path={DB_SCHEMA},public",
    )


def normalize_datetime_to_iso_utc(value) -> str:
    """
    Convert a PostgreSQL datetime or ISO string to:

        YYYY-MM-DDTHH:MM:SSZ
    """

    if value is None:
        raise ValueError("utcDate is NULL")

    if isinstance(value, datetime):
        dt = value

    elif isinstance(value, str):
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

    else:
        raise ValueError(
            f"Unsupported utcDate type: {type(value)}"
        )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def populate_h2h():
    conn = db_connect()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            # ==================================================
            # FETCH ONLY NEW FINISHED MATCHES
            # ==================================================
            cur.execute("""
                SELECT
                    m.id AS match_id,
                    m.home_team_id,
                    m.away_team_id,
                    m.home_score,
                    m.away_score,
                    m.utcDate AS utcdate
                FROM matches m
                WHERE m.status = 'FINISHED'
                  AND m.home_score IS NOT NULL
                  AND m.away_score IS NOT NULL
                  AND m.utcDate IS NOT NULL

                  -- Skip matches already populated in H2H
                  AND NOT EXISTS (
                      SELECT 1
                      FROM h2h h
                      WHERE h.match_id = m.id
                  )

                ORDER BY m.utcDate ASC
            """)

            matches = cur.fetchall()

            print(
                f"Found {len(matches)} NEW finished matches "
                "eligible for H2H."
            )

            # ==================================================
            # NOTHING NEW
            # ==================================================
            if not matches:
                print("✅ H2H is already up to date.")
                return

            # ==================================================
            # PREPARE BULK INSERT
            # ==================================================
            rows = []
            skipped = 0

            for match in matches:
                try:
                    date_played = normalize_datetime_to_iso_utc(
                        match["utcdate"]
                    )

                    rows.append((
                        match["home_team_id"],
                        match["away_team_id"],
                        match["match_id"],
                        match["home_score"],
                        match["away_score"],
                        date_played,
                    ))

                except Exception as exc:
                    skipped += 1

                    print(
                        f"⚠️ Skipping match_id="
                        f"{match['match_id']} "
                        f"(bad utcDate): {exc}"
                    )

            # ==================================================
            # NO VALID ROWS
            # ==================================================
            if not rows:
                print("No valid new H2H records to insert.")
                return

            # ==================================================
            # SINGLE BULK INSERT
            # ==================================================
            execute_values(
                cur,
                """
                INSERT INTO h2h
                (
                    home_team_id,
                    away_team_id,
                    match_id,
                    home_score,
                    away_score,
                    date_played
                )
                VALUES %s
                ON CONFLICT (match_id) DO NOTHING
                """,
                rows,
                page_size=1000,
            )

            conn.commit()

            print(
                f"✅ Bulk insert completed: "
                f"{len(rows)} new records processed."
            )

            if skipped:
                print(
                    f"⚠️ Skipped {skipped} records "
                    "because of invalid dates."
                )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    populate_h2h()
