#!/usr/bin/env python3

"""
Lilymac Prediction Hub
Current-season match updater.

Purpose:
    Update ONLY existing matches for the current season.

Tracked fields:
    - status
    - utcdate
    - home_score
    - away_score

Safety:
    - NEVER inserts matches
    - NEVER changes team IDs
    - NEVER changes competition
    - NEVER writes utcDate into status
    - Only updates existing match IDs
    - Only updates rows whose tracked data changed
    - Uses config2.py for all DB/API configuration
    - Skips unavailable competitions instead of crashing
"""

import asyncio
from datetime import datetime, timezone

import aiohttp
import asyncpg

from config2 import (
    BASE_URL,
    HEADERS,
    DB_CONNECT_URL,
    DB_SCHEMA,
)


# ============================================================
# CONFIG
# ============================================================

SEASON = 2026

COMPETITIONS = {
    "PL": "Premier League",
    "PD": "La Liga",
    "SA": "Serie A",
    "BL1": "Bundesliga",
    "FL1": "Ligue 1",
    "CL": "Champions League",
}

REQUEST_TIMEOUT = 60


# ============================================================
# VALID FOOTBALL DATA API STATUSES
# ============================================================

VALID_STATUSES = {
    "SCHEDULED",
    "TIMED",
    "IN_PLAY",
    "PAUSED",
    "FINISHED",
    "POSTPONED",
    "SUSPENDED",
    "CANCELLED",
}


# ============================================================
# STATUS NORMALIZATION
# ============================================================

def normalize_status(match):
    """
    Return a valid Football Data API status.

    Some API responses appear to contain a datetime string
    inside the status field, for example:

        2026-08-28 19:00:00Z

    Such values must NEVER be written to PostgreSQL status.

    Returns:
        status, invalid_status_flag
    """

    status = match.get("status")

    # --------------------------------------------------------
    # Valid API status
    # --------------------------------------------------------

    if status in VALID_STATUSES:
        return status, False

    # --------------------------------------------------------
    # Invalid status.
    #
    # If utcDate exists, safely classify the fixture as TIMED.
    # --------------------------------------------------------

    if match.get("utcDate"):
        return "TIMED", True

    # --------------------------------------------------------
    # Absolute fallback.
    # --------------------------------------------------------

    return "SCHEDULED", True


# ============================================================
# DATABASE
# ============================================================

async def get_connection():
    return await asyncpg.connect(
        DB_CONNECT_URL,
        server_settings={
            "search_path": f"{DB_SCHEMA},public"
        },
        command_timeout=60,
    )


# ============================================================
# DATETIME
# ============================================================

def normalize_datetime(value):
    """
    Convert Football Data API utcDate into UTC datetime.
    """

    if not value:
        return None

    dt = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt.astimezone(
        timezone.utc
    )


# ============================================================
# API
# ============================================================

async def fetch_competition_matches(
    session,
    competition_code,
):
    """
    Fetch all matches for one competition and season.

    Returns:
        matches

    Returns None when the competition endpoint is unavailable.
    """

    url = (
        f"{BASE_URL}/competitions/"
        f"{competition_code}/matches"
    )

    params = {
        "season": SEASON,
    }

    try:

        async with session.get(
            url,
            headers=HEADERS,
            params=params,
        ) as response:

            text = await response.text()

            # ------------------------------------------------
            # 404
            # ------------------------------------------------

            if response.status == 404:

                print(
                    f"      ⚠️ API returned 404. "
                    f"Skipping {competition_code}."
                )

                return None

            # ------------------------------------------------
            # Other HTTP errors
            # ------------------------------------------------

            if response.status != 200:

                print(
                    f"      ⚠️ API error "
                    f"{response.status}: "
                    f"{text[:300]}"
                )

                return None

            # ------------------------------------------------
            # JSON
            # ------------------------------------------------

            try:

                data = await response.json()

            except Exception:

                print(
                    "      ⚠️ Invalid JSON response."
                )

                return None

            return data.get(
                "matches",
                []
            )

    except asyncio.TimeoutError:

        print(
            f"      ⚠️ API timeout. "
            f"Skipping {competition_code}."
        )

        return None

    except aiohttp.ClientError as exc:

        print(
            f"      ⚠️ API connection error: "
            f"{exc}"
        )

        return None


# ============================================================
# LOAD DATABASE MATCHES
# ============================================================

async def load_existing_matches(conn):
    """
    Load only current-season matches.

    Key:
        match ID
    """

    rows = await conn.fetch(
        """
        SELECT
            id,
            competition,
            status,
            utcdate,
            home_score,
            away_score
        FROM matches
        WHERE season = $1
        """,
        SEASON,
    )

    return {
        row["id"]: row
        for row in rows
    }


# ============================================================
# PREPARE UPDATES
# ============================================================

def prepare_updates(
    api_matches,
    existing,
):
    """
    Compare API data against PostgreSQL.

    Only existing match IDs are considered.

    Returns:
        updates
        statistics
    """

    updates = []

    status_changes = 0
    time_changes = 0
    home_score_changes = 0
    away_score_changes = 0

    invalid_statuses = 0

    for match in api_matches:

        match_id = match.get("id")

        if not match_id:
            continue

        # ----------------------------------------------------
        # SAFETY:
        # NEVER insert new matches.
        # ----------------------------------------------------

        old = existing.get(match_id)

        if old is None:
            continue

        # ----------------------------------------------------
        # API STATUS
        # ----------------------------------------------------

        new_status, invalid_status = normalize_status(
            match
        )

        if invalid_status:
            invalid_statuses += 1

        # ----------------------------------------------------
        # API DATE
        # ----------------------------------------------------

        try:

            new_utcdate = normalize_datetime(
                match.get("utcDate")
            )

        except (ValueError, TypeError):

            new_utcdate = old["utcdate"]

        # ----------------------------------------------------
        # API SCORE
        # ----------------------------------------------------

        score = (
            match.get("score")
            or {}
        )

        full_time = (
            score.get("fullTime")
            or {}
        )

        new_home_score = (
            full_time.get("home")
        )

        new_away_score = (
            full_time.get("away")
        )

        # ----------------------------------------------------
        # Detect individual changes
        # ----------------------------------------------------

        status_changed = (
            old["status"]
            != new_status
        )

        time_changed = (
            old["utcdate"]
            != new_utcdate
        )

        home_score_changed = (
            old["home_score"]
            != new_home_score
        )

        away_score_changed = (
            old["away_score"]
            != new_away_score
        )

        changed = (
            status_changed
            or time_changed
            or home_score_changed
            or away_score_changed
        )

        if not changed:
            continue

        # ----------------------------------------------------
        # Statistics
        # ----------------------------------------------------

        if status_changed:
            status_changes += 1

        if time_changed:
            time_changes += 1

        if home_score_changed:
            home_score_changes += 1

        if away_score_changed:
            away_score_changes += 1

        # ----------------------------------------------------
        # Store update.
        # ----------------------------------------------------

        updates.append(
            (
                match_id,
                new_status,
                new_utcdate,
                new_home_score,
                new_away_score,
            )
        )

    stats = {
        "status": status_changes,
        "time": time_changes,
        "home_score": home_score_changes,
        "away_score": away_score_changes,
        "invalid_statuses": invalid_statuses,
    }

    return updates, stats


# ============================================================
# APPLY UPDATES
# ============================================================

async def apply_updates(
    conn,
    updates,
):
    """
    Apply updates in one transaction.

    No INSERT operations are performed.

    Final application-side validation prevents invalid
    statuses from reaching PostgreSQL.
    """

    if not updates:
        return 0

    # --------------------------------------------------------
    # Final safety check
    # --------------------------------------------------------

    for (
        match_id,
        status,
        utcdate,
        home_score,
        away_score,
    ) in updates:

        if status not in VALID_STATUSES:

            raise ValueError(
                f"Refusing to write invalid status "
                f"'{status}' for match {match_id}"
            )

    # --------------------------------------------------------
    # Transaction
    # --------------------------------------------------------

    async with conn.transaction():

        await conn.executemany(
            """
            UPDATE matches
            SET
                status = $2,
                utcdate = $3,
                home_score = $4,
                away_score = $5,
                generated_at = NOW()
            WHERE id = $1
              AND season = $6
            """,
            [
                (
                    match_id,
                    status,
                    utcdate,
                    home_score,
                    away_score,
                    SEASON,
                )
                for (
                    match_id,
                    status,
                    utcdate,
                    home_score,
                    away_score,
                ) in updates
            ],
        )

    return len(updates)


# ============================================================
# MAIN
# ============================================================

async def main():

    print("=" * 50)
    print(
        "LILYMAC CURRENT-SEASON MATCH UPDATE"
    )
    print("=" * 50)

    print(
        f"Season: {SEASON}"
    )

    print()

    conn = await get_connection()

    try:

        # ----------------------------------------------------
        # DATABASE IDENTITY
        # ----------------------------------------------------

        db_info = await conn.fetchrow(
            """
            SELECT
                current_database() AS database,
                current_schema() AS schema,
                current_setting('search_path')
                    AS search_path
            """
        )

        print(
            f"[DATABASE] {dict(db_info)}"
        )

        # ----------------------------------------------------
        # EXISTING MATCHES
        # ----------------------------------------------------

        existing = await load_existing_matches(
            conn
        )

        print(
            f"[DATABASE] Existing season matches: "
            f"{len(existing)}"
        )

        print()

        total_checked = 0

        all_updates = {}

        total_status_changes = 0
        total_time_changes = 0
        total_home_score_changes = 0
        total_away_score_changes = 0
        total_invalid_statuses = 0

        # ----------------------------------------------------
        # HTTP SESSION
        # ----------------------------------------------------

        timeout = aiohttp.ClientTimeout(
            total=REQUEST_TIMEOUT
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            for code, name in COMPETITIONS.items():

                print(
                    f"[API] {name} ({code})"
                )

                matches = await fetch_competition_matches(
                    session,
                    code,
                )

                # ------------------------------------------------
                # API unavailable
                # ------------------------------------------------

                if matches is None:
                    print()
                    continue

                print(
                    f"      API matches: "
                    f"{len(matches)}"
                )

                # ------------------------------------------------
                # Compare
                # ------------------------------------------------

                updates, stats = prepare_updates(
                    matches,
                    existing,
                )

                checked = sum(
                    1
                    for m in matches
                    if m.get("id") in existing
                )

                total_checked += checked

                # ------------------------------------------------
                # Statistics
                # ------------------------------------------------

                total_status_changes += (
                    stats["status"]
                )

                total_time_changes += (
                    stats["time"]
                )

                total_home_score_changes += (
                    stats["home_score"]
                )

                total_away_score_changes += (
                    stats["away_score"]
                )

                total_invalid_statuses += (
                    stats["invalid_statuses"]
                )

                # ------------------------------------------------
                # Store updates by ID
                # ------------------------------------------------

                for update in updates:

                    match_id = update[0]

                    all_updates[
                        match_id
                    ] = update

                # ------------------------------------------------
                # Competition result
                # ------------------------------------------------

                if updates:

                    print(
                        f"      Changes detected: "
                        f"{len(updates)}"
                    )

                    if stats["status"]:
                        print(
                            f"        status: "
                            f"{stats['status']}"
                        )

                    if stats["time"]:
                        print(
                            f"        time: "
                            f"{stats['time']}"
                        )

                    if stats["home_score"]:
                        print(
                            f"        home score: "
                            f"{stats['home_score']}"
                        )

                    if stats["away_score"]:
                        print(
                            f"        away score: "
                            f"{stats['away_score']}"
                        )

                else:

                    print(
                        "      No changes."
                    )

                # ------------------------------------------------
                # Clean invalid-status summary
                # ------------------------------------------------

                if stats["invalid_statuses"]:

                    print(
                        f"      ⚠️ Malformed API statuses "
                        f"normalized safely: "
                        f"{stats['invalid_statuses']}"
                    )

                print()

        # ----------------------------------------------------
        # FINAL UPDATE LIST
        # ----------------------------------------------------

        updates = list(
            all_updates.values()
        )

        print(
            "[CHECK]"
        )

        print(
            f"Existing matches checked: "
            f"{total_checked}"
        )

        print(
            f"Matches requiring update: "
            f"{len(updates)}"
        )

        print(
            f"Malformed API statuses normalized: "
            f"{total_invalid_statuses}"
        )

        # ----------------------------------------------------
        # NOTHING TO UPDATE
        # ----------------------------------------------------

        if not updates:

            print()

            print(
                "✅ DATABASE IS ALREADY UP TO DATE."
            )

            return

        # ----------------------------------------------------
        # APPLY
        # ----------------------------------------------------

        updated = await apply_updates(
            conn,
            updates,
        )

        # ----------------------------------------------------
        # SUMMARY
        # ----------------------------------------------------

        print()

        print(
            "UPDATE COMPLETE"
        )

        print(
            "=" * 50
        )

        print(
            f"Season:          {SEASON}"
        )

        print(
            f"Matches checked: {total_checked}"
        )

        print(
            f"Matches updated: {updated}"
        )

        print()

        print(
            "FIELD CHANGES"
        )

        print(
            f"Status changes:       "
            f"{total_status_changes}"
        )

        print(
            f"Time changes:         "
            f"{total_time_changes}"
        )

        print(
            f"Home score changes:   "
            f"{total_home_score_changes}"
        )

        print(
            f"Away score changes:   "
            f"{total_away_score_changes}"
        )

        print(
            f"Malformed statuses:    "
            f"{total_invalid_statuses}"
        )

        print(
            "=" * 50
        )

    finally:

        await conn.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
