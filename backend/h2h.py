#!/usr/bin/env python3
"""
h2h.py
Populate h2h table from matches table (PostgreSQL version)

✔ Inserts only FINISHED matches with final scores
✔ Handles both string and datetime utcDate from Postgres
✔ Normalizes date_played to ISO-8601 UTC: YYYY-MM-DDTHH:MM:SSZ
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from config2 import DATABASE_URL


def db_connect():
    return psycopg2.connect(DATABASE_URL)


def normalize_datetime_to_iso_utc(value) -> str:
    """
    Accepts:
      - ISO string
      - datetime object (Postgres)
    Returns:
      ISO-8601 UTC string (Z format)
    """
    if value is None:
        raise ValueError("utcDate is NULL")

    # If already datetime (Postgres usually returns this)
    if isinstance(value, datetime):
        dt = value

    # If string, parse it
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

    else:
        raise ValueError(f"Unsupported utcDate type: {type(value)}")

    # Ensure timezone awareness
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def populate_h2h():
    conn = db_connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT
            id AS match_id,
            home_team_id,
            away_team_id,
            home_score,
            away_score,
            utcDate
        FROM matches
        WHERE status = 'FINISHED'
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
          AND utcDate IS NOT NULL
        ORDER BY utcDate ASC
    """)

    matches = cur.fetchall()
    inserted = 0

    for m in matches:
        try:
            date_played = normalize_datetime_to_iso_utc(m["utcdate"])
        except Exception as e:
            print(f"⚠️ Skipping match_id={m['match_id']} (bad utcDate): {e}")
            continue

        cur.execute("""
            INSERT INTO h2h
            (home_team_id, away_team_id, match_id, home_score, away_score, date_played)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (match_id) DO NOTHING
        """, (
            m["home_team_id"],
            m["away_team_id"],
            m["match_id"],
            m["home_score"],
            m["away_score"],
            date_played
        ))

        if cur.rowcount == 1:
            inserted += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"✅ Inserted {inserted} new H2H records (ISO-8601 UTC).")


if __name__ == "__main__":
    populate_h2h()
