#!/usr/bin/env python3

import asyncio
import aiohttp
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dateutil import parser
from colorama import Fore, Style, init as color_init

from config import BASE_URL, HEADERS, COMPETITION_MAP

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


# ============================================================
# INIT
# ============================================================

color_init(autoreset=True)

KENYA = ZoneInfo("Africa/Nairobi")
UTC = timezone.utc

MAX_CONCURRENT = 3
API_DELAY = 1

semaphore = asyncio.Semaphore(MAX_CONCURRENT)


# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.getenv(
    "ASYNC_DATABASE_URL",
    "postgresql+asyncpg://henry:kyu@localhost:5432/virtualfootball"
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args={
        "server_settings": {
            "search_path": "henry_schema"
        }
    }
)

async_session = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


# ============================================================
# TIME HELPERS
# ============================================================

def now_kenya():
    return datetime.now(KENYA)


def parse_utc_date(raw_date):
    if not raw_date:
        return datetime.now(UTC)

    dt = parser.isoparse(raw_date)

    if dt.tzinfo is not None:
        return dt.astimezone(UTC)

    return dt.replace(tzinfo=UTC)


# ============================================================
# HTTP FETCH
# ============================================================

async def fetch_json(session, url, retries=5):

    for attempt in range(retries):

        try:

            async with semaphore:

                await asyncio.sleep(API_DELAY)

                async with session.get(
                    url,
                    headers=HEADERS,
                    timeout=20
                ) as resp:

                    # Rate limit
                    if resp.status == 429:

                        print(
                            f"{Fore.YELLOW}"
                            f"[RATE LIMIT] {url}"
                            f"{Style.RESET_ALL}"
                        )

                        await asyncio.sleep(2 ** attempt)
                        continue

                    # Read response body for useful error information
                    if resp.status >= 400:

                        try:
                            body = await resp.text()
                        except Exception:
                            body = ""

                        print(
                            f"{Fore.RED}"
                            f"[HTTP {resp.status}] {url}"
                            f"{Style.RESET_ALL}"
                        )

                        if body:
                            print(
                                f"   {body[:300]}"
                            )

                        # Retry temporary server errors
                        if resp.status >= 500:
                            await asyncio.sleep(2 ** attempt)
                            continue

                        # Don't repeatedly retry permanent errors
                        return None

                    return await resp.json()

        except asyncio.CancelledError:
            raise

        except Exception as e:

            print(
                f"{Fore.RED}"
                f"[FAIL] {url}"
                f"{Style.RESET_ALL}"
            )

            print(
                f"   {type(e).__name__}: {e}"
            )

            await asyncio.sleep(2 ** attempt)

    return None


# ============================================================
# FETCH TEAMS
# ============================================================

async def fetch_teams(session, code):

    url = f"{BASE_URL}/competitions/{code}/teams"

    data = await fetch_json(
        session,
        url
    )

    if not data:
        return 0

    new_count = 0

    async with async_session() as db:

        async with db.begin():

            for team in data.get("teams", []):

                result = await db.execute(
                    text("""
                        INSERT INTO teams (
                            id,
                            name,
                            short_name,
                            tla,
                            crest,
                            venue,
                            founded
                        )
                        VALUES (
                            :id,
                            :name,
                            :short_name,
                            :tla,
                            :crest,
                            :venue,
                            :founded
                        )
                        ON CONFLICT(id) DO NOTHING
                    """),
                    {
                        "id": team.get("id"),
                        "name": team.get("name"),
                        "short_name": team.get("shortName"),
                        "tla": team.get("tla"),
                        "crest": team.get("crest"),
                        "venue": team.get("venue"),
                        "founded": team.get("founded")
                    }
                )

                if result.rowcount > 0:
                    new_count += 1

    return new_count


# ============================================================
# FETCH MATCHES
# ============================================================

async def fetch_matches(
    session,
    code,
    season,
    recent_season
):

    url = (
        f"{BASE_URL}/competitions/"
        f"{code}/matches?season={season}"
    )

    data = await fetch_json(
        session,
        url
    )

    if not data:

        print(
            f"{Fore.YELLOW}"
            f"   → No match data for season {season}"
            f"{Style.RESET_ALL}"
        )

        return 0, 0, {}

    new_count = 0
    updated_count = 0

    # --------------------------------------------------------
    # Teams participating in this competition/season
    # --------------------------------------------------------

    season_teams = {}

    async with async_session() as db:

        async with db.begin():

            for match in data.get("matches", []):

                match_id = match.get("id")

                # ------------------------------------------------
                # Teams
                # ------------------------------------------------

                home_team = match.get(
                    "homeTeam",
                    {}
                )

                away_team = match.get(
                    "awayTeam",
                    {}
                )

                home_team_id = home_team.get("id")
                away_team_id = away_team.get("id")

                home_team_name = home_team.get(
                    "name",
                    f"Team {home_team_id}"
                )

                away_team_name = away_team.get(
                    "name",
                    f"Team {away_team_id}"
                )

                # Record participating teams
                if home_team_id:
                    season_teams[
                        home_team_id
                    ] = home_team_name

                if away_team_id:
                    season_teams[
                        away_team_id
                    ] = away_team_name

                # ------------------------------------------------
                # Match information
                # ------------------------------------------------

                utc_date = parse_utc_date(
                    match.get("utcDate")
                )

                home_score = (
                    match
                    .get("score", {})
                    .get("fullTime", {})
                    .get("home")
                )

                away_score = (
                    match
                    .get("score", {})
                    .get("fullTime", {})
                    .get("away")
                )

                status = match.get("status")

                # ------------------------------------------------
                # Check existing match
                # ------------------------------------------------

                result = await db.execute(
                    text("""
                        SELECT
                            status,
                            home_score,
                            away_score,
                            utcdate
                        FROM matches
                        WHERE id = :id
                    """),
                    {
                        "id": match_id
                    }
                )

                row = result.fetchone()

                # ------------------------------------------------
                # Existing match
                # ------------------------------------------------

                if row:

                    (
                        old_status,
                        old_home_score,
                        old_away_score,
                        old_utcdate
                    ) = row

                    # Only update current season
                    if (
                        season == recent_season
                        and (
                            old_status != status
                            or old_home_score != home_score
                            or old_away_score != away_score
                            or old_utcdate != utc_date
                        )
                    ):

                        await db.execute(
                            text("""
                                UPDATE matches
                                SET
                                    status = :status,
                                    home_score = :home_score,
                                    away_score = :away_score,
                                    utcdate = :utcdate,
                                    generated_at = CURRENT_TIMESTAMP
                                WHERE id = :id
                            """),
                            {
                                "status": status,
                                "home_score": home_score,
                                "away_score": away_score,
                                "utcdate": utc_date,
                                "id": match_id
                            }
                        )

                        updated_count += 1

                    continue

                # ------------------------------------------------
                # New match
                # ------------------------------------------------

                await db.execute(
                    text("""
                        INSERT INTO matches (
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
                        VALUES (
                            :id,
                            :competition,
                            :matchday,
                            :utcdate,
                            :status,
                            :home_team_id,
                            :away_team_id,
                            :home_score,
                            :away_score,
                            :home_team_name,
                            :away_team_name,
                            :season,
                            CURRENT_TIMESTAMP
                        )
                        ON CONFLICT(id) DO NOTHING
                    """),
                    {
                        "id": match_id,
                        "competition": (
                            match
                            .get("competition", {})
                            .get("name", "UNKNOWN")
                        ),
                        "matchday": match.get("matchday"),
                        "utcdate": utc_date,
                        "status": status,
                        "home_team_id": home_team_id,
                        "away_team_id": away_team_id,
                        "home_score": home_score,
                        "away_score": away_score,
                        "home_team_name": home_team_name,
                        "away_team_name": away_team_name,
                        "season": season
                    }
                )

                new_count += 1

    # --------------------------------------------------------
    # Output
    # --------------------------------------------------------

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

    # Number of participating teams
    if season_teams:

        print(
            f"      → {len(season_teams)} "
            f"teams participating in season {season}"
        )

    return (
        new_count + updated_count,
        len(season_teams),
        season_teams
    )


# ============================================================
# PROMOTION / RELEGATION DETECTION
# ============================================================

def detect_team_changes(
    previous_teams,
    current_teams
):

    previous_ids = set(
        previous_teams.keys()
    )

    current_ids = set(
        current_teams.keys()
    )

    # Present this season but not previous season
    entered = current_ids - previous_ids

    # Present previous season but not current season
    left = previous_ids - current_ids

    return entered, left


def print_team_changes(
    league,
    previous_season,
    current_season,
    previous_teams,
    current_teams
):

    entered, left = detect_team_changes(
        previous_teams,
        current_teams
    )

    print()
    print(
        f"{Fore.CYAN}"
        f"   =================================================="
        f"{Style.RESET_ALL}"
    )

    print(
        f"{Fore.CYAN}"
        f"   🔄 {league}: "
        f"{previous_season} → {current_season}"
        f"{Style.RESET_ALL}"
    )

    print(
        f"{Fore.CYAN}"
        f"   =================================================="
        f"{Style.RESET_ALL}"
    )

    # --------------------------------------------------------
    # Teams entering
    # --------------------------------------------------------

    if entered:

        print(
            f"{Fore.GREEN}"
            f"   🟢 Teams entering / promoted:"
            f"{Style.RESET_ALL}"
        )

        for team_id in sorted(entered):

            print(
                f"      + "
                f"{current_teams[team_id]} "
                f"(ID {team_id})"
            )

    else:

        print(
            "   🟢 Teams entering / promoted: None"
        )

    # --------------------------------------------------------
    # Teams leaving
    # --------------------------------------------------------

    if left:

        print(
            f"{Fore.RED}"
            f"   🔴 Teams leaving / relegated:"
            f"{Style.RESET_ALL}"
        )

        for team_id in sorted(left):

            print(
                f"      - "
                f"{previous_teams[team_id]} "
                f"(ID {team_id})"
            )

    else:

        print(
            "   🔴 Teams leaving / relegated: None"
        )


# ============================================================
# UPDATE STANDINGS
# ============================================================

async def update_league_standings(
    session,
    code
):

    url = (
        f"{BASE_URL}/competitions/"
        f"{code}/standings"
    )

    data = await fetch_json(
        session,
        url
    )

    if (
        not data
        or not data.get("standings")
    ):

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

    async with async_session() as db:

        async with db.begin():

            for standing in table:

                team = standing.get(
                    "team",
                    {}
                )

                season_start = (
                    standing
                    .get("season", {})
                    .get(
                        "startDate",
                        None
                    )
                )

                if season_start:

                    season_year = parser.isoparse(
                        season_start
                    ).year

                else:

                    season_year = now_kenya().year

                await db.execute(
                    text("""
                        INSERT INTO standings (
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
                        VALUES (
                            :league_code,
                            :season,
                            :team_id,
                            :rank,
                            :points,
                            :win,
                            :draw,
                            :lose,
                            :goals_for,
                            :goals_against,
                            :goal_diff,
                            CURRENT_TIMESTAMP
                        )
                        ON CONFLICT (
                            league_code,
                            season,
                            team_id
                        )
                        DO UPDATE SET
                            rank = excluded.rank,
                            points = excluded.points,
                            win = excluded.win,
                            draw = excluded.draw,
                            lose = excluded.lose,
                            goals_for = excluded.goals_for,
                            goals_against = excluded.goals_against,
                            goal_diff = excluded.goal_diff,
                            last_updated = CURRENT_TIMESTAMP
                    """),
                    {
                        "league_code": code,
                        "season": season_year,
                        "team_id": team.get("id"),
                        "rank": standing.get("position"),
                        "points": standing.get("points"),
                        "win": standing.get("won"),
                        "draw": standing.get("draw"),
                        "lose": standing.get("lost"),
                        "goals_for": standing.get("goalsFor"),
                        "goals_against": standing.get(
                            "goalsAgainst"
                        ),
                        "goal_diff": standing.get(
                            "goalDifference"
                        )
                    }
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
# MAIN
# ============================================================

async def main():

    print(
        "[INIT] Async multi-season fetch started..."
    )

    async with aiohttp.ClientSession() as session:

        LEAGUES = {
            "Premier League": "PL",
            "La Liga": "PD",
            "Serie A": "SA",
            "Bundesliga": "BL1",
            "Ligue 1": "FL1",
            "Champions League": "CL"
        }

        # ----------------------------------------------------
        # Current season
        # ----------------------------------------------------

        now = datetime.now(UTC)

        recent_season = (
            now.year
            if now.month >= 7
            else now.year - 1
        )

        # IMPORTANT:
        # Include the current season.
        #
        # In August 2026 this becomes:
        # 2026, 2025, 2024, 2023
        # ----------------------------------------------------

        seasons = range(
            now.year,
            2022,
            -1
        )

        for league, code in LEAGUES.items():

            print()
            print(
                f"[LEAGUE] {league} ({code})"
            )

            # ------------------------------------------------
            # Fetch teams
            # ------------------------------------------------

            new_teams = await fetch_teams(
                session,
                code
            )

            print(
                f" → {new_teams} new teams"
            )

            # ------------------------------------------------
            # Store participating teams per season
            # ------------------------------------------------

            season_team_map = {}

            for season in seasons:

                (
                    _,
                    team_count,
                    season_teams
                ) = await fetch_matches(
                    session,
                    code,
                    season,
                    recent_season
                )

                if season_teams:

                    season_team_map[
                        season
                    ] = season_teams

            # ------------------------------------------------
            # Detect promotion / relegation
            #
            # Compare:
            # 2025 vs 2026
            # ------------------------------------------------

            previous_season = (
                recent_season - 1
            )

            current_season = recent_season

            if (
                previous_season in season_team_map
                and current_season in season_team_map
            ):

                print_team_changes(
                    league,
                    previous_season,
                    current_season,
                    season_team_map[
                        previous_season
                    ],
                    season_team_map[
                        current_season
                    ]
                )

            else:

                print()
                print(
                    f"{Fore.YELLOW}"
                    f"   ⚠ Cannot compare "
                    f"{previous_season} → "
                    f"{current_season}"
                    f"{Style.RESET_ALL}"
                )

                if previous_season not in season_team_map:

                    print(
                        f"      Missing season "
                        f"{previous_season} data"
                    )

                if current_season not in season_team_map:

                    print(
                        f"      Missing season "
                        f"{current_season} data"
                    )

        # ----------------------------------------------------
        # STANDINGS
        # ----------------------------------------------------

        print()
        print(
            "🚀 Updating standings..."
        )

        for code in LEAGUES.values():

            await update_league_standings(
                session,
                code
            )

    # --------------------------------------------------------
    # Close database engine
    # --------------------------------------------------------

    await engine.dispose()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print()
        print(
            f"{Fore.YELLOW}"
            "[STOPPED] Fetch interrupted by user"
            f"{Style.RESET_ALL}"
        )
