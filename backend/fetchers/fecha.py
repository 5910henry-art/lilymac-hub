#!/usr/bin/env python3

import asyncio
import aiohttp
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dateutil import parser
from colorama import Fore, Style, init as color_init

from config2 import (
    BASE_URL,
    HEADERS,
    COMPETITION_MAP,
    get_pool,
    close_pool,
)


# ============================================================
# INIT
# ============================================================

color_init(autoreset=True)

KENYA = ZoneInfo("Africa/Nairobi")
UTC = timezone.utc

MAX_CONCURRENT = 5
API_DELAY = 0.2

semaphore = asyncio.Semaphore(MAX_CONCURRENT)


# ============================================================
# DATABASE
# ============================================================

# IMPORTANT:
# No DATABASE_URL is defined here.
#
# No SQLAlchemy engine is created here.
#
# The database comes exclusively from config2.py:
#
#     config2.py
#          ↓
#     DATABASE_URL
#          ↓
#     Render PostgreSQL
#          ↓
#     henry_schema
#
# This guarantees that the importer and API use the same DB.


# ============================================================
# TIME HELPER
# ============================================================

def now_kenya():
    return datetime.now(KENYA)


# ============================================================
# UTC DATE PARSER
# ============================================================

def parse_utc_date(raw_date):
    if not raw_date:
        return datetime.now(UTC)

    dt = parser.isoparse(raw_date)

    if dt.tzinfo is not None:
        return dt.astimezone(UTC)

    return dt.replace(tzinfo=UTC)


# ============================================================
# HTTP FETCH HELPER
# ============================================================

async def fetch_json(session, url, retries=5):
    for attempt in range(retries):
        try:
            async with semaphore:
                await asyncio.sleep(API_DELAY)

                async with session.get(
                    url,
                    headers=HEADERS,
                    timeout=15,
                ) as resp:

                    if resp.status == 429:
                        await asyncio.sleep(2 ** attempt)
                        continue

                    resp.raise_for_status()

                    return await resp.json()

        except Exception:
            await asyncio.sleep(2 ** attempt)

            print(
                f"{Fore.RED}"
                f"[FAIL] {url}"
                f"{Style.RESET_ALL}"
            )

    return None


# ============================================================
# FETCH TEAMS
# ============================================================

async def fetch_teams(session, code):

    data = await fetch_json(
        session,
        f"{BASE_URL}/competitions/{code}/teams",
    )

    if not data:
        return 0

    new_count = 0

    pool = await get_pool()

    async with pool.acquire() as db:

        async with db.transaction():

            for t in data.get("teams", []):

                result = await db.execute(
                    """
                    INSERT INTO teams
                    (
                        id,
                        name,
                        short_name,
                        tla,
                        crest,
                        venue,
                        founded
                    )
                    VALUES
                    (
                        $1,
                        $2,
                        $3,
                        $4,
                        $5,
                        $6,
                        $7
                    )
                    ON CONFLICT(id) DO NOTHING
                    """,
                    t.get("id"),
                    t.get("name"),
                    t.get("shortName"),
                    t.get("tla"),
                    t.get("crest"),
                    t.get("venue"),
                    t.get("founded"),
                )

                # asyncpg returns e.g.:
                # "INSERT 0 1"
                #
                # The final number represents rows affected.

                if result.endswith(" 1"):
                    new_count += 1

    return new_count


# ============================================================
# FETCH MATCHES
# ============================================================

async def fetch_matches(
    session,
    code,
    season,
    recent_season,
):

    url = (
        f"{BASE_URL}/competitions/"
        f"{code}/matches?season={season}"
    )

    data = await fetch_json(session, url)

    if not data:
        return 0

    new_count = 0
    updated_count = 0

    pool = await get_pool()

    async with pool.acquire() as db:

        async with db.transaction():

            for m in data.get("matches", []):

                match_id = m.get("id")

                utc_date = parse_utc_date(
                    m.get("utcDate")
                )

                # ------------------------------------------------
                # Check whether match already exists
                # ------------------------------------------------

                row = await db.fetchrow(
                    """
                    SELECT
                        status,
                        home_score,
                        away_score,
                        utcdate
                    FROM matches
                    WHERE id = $1
                    """,
                    match_id,
                )

                # ------------------------------------------------
                # Match data
                # ------------------------------------------------

                home_score = (
                    m.get("score", {})
                    .get("fullTime", {})
                    .get("home")
                )

                away_score = (
                    m.get("score", {})
                    .get("fullTime", {})
                    .get("away")
                )

                status = m.get("status")

                # ------------------------------------------------
                # Existing match
                # ------------------------------------------------

                if row:

                    old_status = row["status"]
                    old_home = row["home_score"]
                    old_away = row["away_score"]
                    old_utcdate = row["utcdate"]

                    if (
                        season == recent_season
                        and (
                            old_status != status
                            or old_home != home_score
                            or old_away != away_score
                            or old_utcdate != utc_date
                        )
                    ):

                        await db.execute(
                            """
                            UPDATE matches
                            SET
                                status = $1,
                                home_score = $2,
                                away_score = $3,
                                utcdate = $4,
                                generated_at = CURRENT_TIMESTAMP
                            WHERE id = $5
                            """,
                            status,
                            home_score,
                            away_score,
                            utc_date,
                            match_id,
                        )

                        updated_count += 1

                    continue

                # ------------------------------------------------
                # New match
                # ------------------------------------------------

                await db.execute(
                    """
                    INSERT INTO matches
                    (
                        id,
                        competition,
                        matchday,
                        utcdate,
                        status,
                        home_team_id,
                        away_team_id,
                        home_score,
                        away_score,
                        home_team_name,
                        away_team_name,
                        season,
                        generated_at
                    )
                    VALUES
                    (
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
                        CURRENT_TIMESTAMP
                    )
                    ON CONFLICT(id) DO NOTHING
                    """,
                    match_id,
                    m.get("competition", {}).get(
                        "name",
                        "UNKNOWN",
                    ),
                    m.get("matchday"),
                    utc_date,
                    status,
                    m.get("homeTeam", {}).get("id"),
                    m.get("awayTeam", {}).get("id"),
                    home_score,
                    away_score,
                    m.get("homeTeam", {}).get("name"),
                    m.get("awayTeam", {}).get("name"),
                    season,
                )

                new_count += 1

    # ------------------------------------------------------------
    # Report
    # ------------------------------------------------------------

    if season == recent_season:

        print(
            f"   → {new_count} new, "
            f"{updated_count} updated "
            f"(season {season})"
        )

    else:

        print(
            f"   → {new_count} new "
            f"(old season {season})"
        )

    return new_count + updated_count


# ============================================================
# UPDATE LEAGUE STANDINGS
# ============================================================

async def update_league_standings(session, code):

    url = (
        f"{BASE_URL}/competitions/"
        f"{code}/standings"
    )

    data = await fetch_json(
        session,
        url,
    )

    if not data or not data.get("standings"):

        print(
            f"{Fore.YELLOW}"
            f"[Skip] {code} standings"
            f"{Style.RESET_ALL}"
        )

        return 0

    table = (
        data["standings"][0]
        .get("table", [])
    )

    if not table:
        return 0

    pool = await get_pool()

    async with pool.acquire() as db:

        async with db.transaction():

            for s in table:

                team = s.get("team", {})

                season_start = (
                    s.get("season", {})
                    .get(
                        "startDate",
                        now_kenya(),
                    )
                )

                if isinstance(
                    season_start,
                    str,
                ):
                    season_year = (
                        parser.isoparse(
                            season_start
                        ).year
                    )
                else:
                    season_year = season_start.year

                await db.execute(
                    """
                    INSERT INTO standings
                    (
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
                    )
                    VALUES
                    (
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
                        CURRENT_TIMESTAMP
                    )
                    ON CONFLICT
                    (
                        league_code,
                        season,
                        team_id
                    )
                    DO UPDATE SET
                        rank = EXCLUDED.rank,
                        points = EXCLUDED.points,
                        win = EXCLUDED.win,
                        draw = EXCLUDED.draw,
                        lose = EXCLUDED.lose,
                        goals_for = EXCLUDED.goals_for,
                        goals_against = EXCLUDED.goals_against,
                        goal_diff = EXCLUDED.goal_diff,
                        last_updated = CURRENT_TIMESTAMP
                    """,
                    code,
                    season_year,
                    team.get("id"),
                    s.get("position"),
                    s.get("points"),
                    s.get("won"),
                    s.get("draw"),
                    s.get("lost"),
                    s.get("goalsFor"),
                    s.get("goalsAgainst"),
                    s.get("goalDifference"),
                )

    print(
        f"{Fore.GREEN}"
        f"[OK] "
        f"{COMPETITION_MAP.get(code, code)} "
        f"standings updated"
        f"{Style.RESET_ALL}"
    )

    return len(table)


# ============================================================
# DATABASE VERIFICATION
# ============================================================

async def verify_database():

    pool = await get_pool()

    async with pool.acquire() as db:

        row = await db.fetchrow(
            """
            SELECT
                current_database() AS database,
                current_schema() AS schema,
                current_setting('search_path') AS search_path
            """
        )

    print(
        "\n[DATABASE]"
    )

    print(
        f"   database:    {row['database']}"
    )

    print(
        f"   schema:      {row['schema']}"
    )

    print(
        f"   search_path: {row['search_path']}"
    )

    # Safety check.
    if row["database"] != "lilymac_db":
        raise RuntimeError(
            "SAFETY STOP: importer is not connected "
            "to lilymac_db."
        )

    if row["schema"] != "henry_schema":
        raise RuntimeError(
            "SAFETY STOP: importer is not using "
            "henry_schema."
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    print(
        "[INIT] Async multi-season fetch started..."
    )

    # --------------------------------------------------------
    # Verify database BEFORE importing anything.
    # --------------------------------------------------------

    await verify_database()

    print(
        "\n[DATABASE] "
        "Render PostgreSQL connection verified."
    )

    # --------------------------------------------------------
    # HTTP session
    # --------------------------------------------------------

    try:

        async with aiohttp.ClientSession() as session:

            LEAGUES = {
                "Premier League": "PL",
                "La Liga": "PD",
                "Serie A": "SA",
                "Bundesliga": "BL1",
                "Ligue 1": "FL1",
                "Champions League": "CL",
            }

            now = datetime.now(UTC)

            recent_season = (
                now.year
                if now.month >= 7
                else now.year - 1
            )

            seasons = range(
                now.year,
                2022,
                -1,
            )

            # ------------------------------------------------
            # Fetch teams and matches
            # ------------------------------------------------

            for league, code in LEAGUES.items():

                print(
                    f"\n[LEAGUE] "
                    f"{league} ({code})"
                )

                new_teams = await fetch_teams(
                    session,
                    code,
                )

                print(
                    f" → {new_teams} new teams"
                )

                for season in seasons:

                    await fetch_matches(
                        session,
                        code,
                        season,
                        recent_season,
                    )

            # ------------------------------------------------
            # Standings
            # ------------------------------------------------

            print(
                "\n🚀 Updating standings..."
            )

            for code in LEAGUES.values():

                await update_league_standings(
                    session,
                    code,
                )

    finally:

        # Always close the shared PostgreSQL pool.
        await close_pool()

        print(
            "\n[DATABASE] PostgreSQL pool closed."
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
