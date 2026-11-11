#!/usr/bin/env python3

import asyncio
import aiohttp
import sys
import argparse

from pathlib import Path
from collections import deque
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.append(
    str(Path(__file__).resolve().parents[1])
)

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


# ============================================================
# CONSTANTS
# ============================================================

KENYA = ZoneInfo("Africa/Nairobi")
UTC = timezone.utc

# football-data.org free tier:
#
# 10 requests / minute
#
# We intentionally use 9 to leave one request as safety margin.
API_MAX_CALLS = 9
API_WINDOW_SECONDS = 60.0

HTTP_TIMEOUT = aiohttp.ClientTimeout(
    total=30,
    connect=10,
    sock_read=25,
)


# ============================================================
# COMPETITIONS
# ============================================================

LEAGUES = {
    "Premier League": "PL",
    "La Liga": "PD",
    "Serie A": "SA",
    "Bundesliga": "BL1",
    "Ligue 1": "FL1",
    "Champions League": "CL",
}


# ============================================================
# API RATE LIMITER
# ============================================================

class APIRateLimiter:
    """
    Conservative rolling-window rate limiter.

    Maximum:
        9 requests / 60 seconds

    This is deliberately below the documented
    free-tier limit of 10 requests/minute.
    """

    def __init__(
        self,
        max_calls=API_MAX_CALLS,
        window_seconds=API_WINDOW_SECONDS,
    ):
        self.max_calls = max_calls
        self.window_seconds = window_seconds

        self.timestamps = deque()

        self.lock = asyncio.Lock()

        self.server_blocked_until = 0.0

        self.requests_total = 0

    async def acquire(self):
        """
        Wait until another API request is allowed.
        """

        loop = asyncio.get_running_loop()

        while True:

            wait_for = 0.0

            async with self.lock:

                now = loop.time()

                # ------------------------------------------------
                # Respect server-provided block.
                # ------------------------------------------------

                if now < self.server_blocked_until:

                    wait_for = (
                        self.server_blocked_until
                        - now
                    )

                else:

                    # ------------------------------------------------
                    # Remove requests older than 60 seconds.
                    # ------------------------------------------------

                    while (
                        self.timestamps
                        and
                        now - self.timestamps[0]
                        >= self.window_seconds
                    ):
                        self.timestamps.popleft()

                    # ------------------------------------------------
                    # We have a request slot.
                    # ------------------------------------------------

                    if (
                        len(self.timestamps)
                        < self.max_calls
                    ):

                        self.timestamps.append(
                            now
                        )

                        self.requests_total += 1

                        return

                    # ------------------------------------------------
                    # No request slot.
                    # ------------------------------------------------

                    wait_for = (
                        self.window_seconds
                        - (
                            now
                            - self.timestamps[0]
                        )
                        + 0.25
                    )

            if wait_for > 0:

                print(
                    f"{Fore.YELLOW}"
                    f"[RATE LIMIT] "
                    f"Waiting {wait_for:.1f}s"
                    f"{Style.RESET_ALL}"
                )

                await asyncio.sleep(
                    wait_for
                )

    def update_from_headers(
        self,
        headers,
    ):
        """
        Read server rate-limit headers.
        """

        available_raw = headers.get(
            "X-Requests-Available-Minute"
        )

        reset_raw = headers.get(
            "X-RequestCounter-Reset"
        )

        try:

            available = (
                int(available_raw)
                if available_raw is not None
                else None
            )

        except (
            TypeError,
            ValueError,
        ):

            available = None

        try:

            reset_seconds = (
                float(reset_raw)
                if reset_raw is not None
                else None
            )

        except (
            TypeError,
            ValueError,
        ):

            reset_seconds = None

        # --------------------------------------------------------
        # If server says zero requests remain, honor reset time.
        # --------------------------------------------------------

        if (
            available is not None
            and available <= 0
            and reset_seconds is not None
        ):

            loop = asyncio.get_running_loop()

            self.server_blocked_until = max(
                self.server_blocked_until,
                loop.time()
                + reset_seconds
                + 0.5,
            )

    async def handle_429(
        self,
        headers,
    ):
        """
        Handle HTTP 429.

        Prefer:
            Retry-After

        Then:
            X-RequestCounter-Reset

        Finally:
            60 seconds.
        """

        delay = None

        retry_after = headers.get(
            "Retry-After"
        )

        reset_raw = headers.get(
            "X-RequestCounter-Reset"
        )

        try:

            if retry_after:
                delay = float(
                    retry_after
                )

        except (
            TypeError,
            ValueError,
        ):

            delay = None

        if delay is None:

            try:

                if reset_raw:
                    delay = float(
                        reset_raw
                    )

            except (
                TypeError,
                ValueError,
            ):

                delay = None

        if delay is None:
            delay = 60.0

        delay += 1.0

        loop = asyncio.get_running_loop()

        self.server_blocked_until = max(
            self.server_blocked_until,
            loop.time()
            + delay,
        )

        print(
            f"{Fore.YELLOW}"
            f"[429] API quota reached. "
            f"Waiting {delay:.1f}s."
            f"{Style.RESET_ALL}"
        )

        await asyncio.sleep(
            delay
        )


api_limiter = APIRateLimiter()


# ============================================================
# TIME HELPERS
# ============================================================

def now_kenya():
    return datetime.now(
        KENYA
    )


# ============================================================
# UTC DATE PARSER
# ============================================================

def parse_utc_date(
    raw_date,
):

    if not raw_date:
        return datetime.now(
            UTC
        )

    dt = parser.isoparse(
        raw_date
    )

    if dt.tzinfo is not None:

        return dt.astimezone(
            UTC
        )

    return dt.replace(
        tzinfo=UTC
    )


# ============================================================
# HTTP FETCH
# ============================================================

async def fetch_json(
    session,
    url,
    retries=4,
):
    """
    Fetch JSON while respecting the API quota.

    Retry policy:

        2xx     -> return JSON

        404     -> DO NOT RETRY

        400     -> DO NOT RETRY

        403     -> DO NOT RETRY

        429     -> wait and retry

        500+    -> retry

        network -> retry
    """

    for attempt in range(
        retries
    ):

        try:

            # ------------------------------------------------
            # Reserve API request slot.
            # ------------------------------------------------

            await api_limiter.acquire()

            async with session.get(
                url,
                headers=HEADERS,
            ) as resp:

                # ------------------------------------------------
                # Always process rate-limit headers.
                # ------------------------------------------------

                api_limiter.update_from_headers(
                    resp.headers
                )

                # ------------------------------------------------
                # 404:
                #
                # Resource doesn't exist.
                #
                # DO NOT RETRY.
                # ------------------------------------------------

                if resp.status == 404:

                    print(
                        f"{Fore.YELLOW}"
                        f"[404] Resource unavailable:"
                        f"{Style.RESET_ALL}"
                    )

                    print(
                        f"      {url}"
                    )

                    return None

                # ------------------------------------------------
                # 400:
                #
                # Bad request.
                # ------------------------------------------------

                if resp.status == 400:

                    body = await resp.text()

                    print(
                        f"{Fore.YELLOW}"
                        f"[400] Bad request:"
                        f"{Style.RESET_ALL}"
                    )

                    print(
                        f"      {url}"
                    )

                    if body:
                        print(
                            f"      {body[:300]}"
                        )

                    return None

                # ------------------------------------------------
                # 403:
                #
                # Restricted resource / permission.
                # ------------------------------------------------

                if resp.status == 403:

                    body = await resp.text()

                    print(
                        f"{Fore.YELLOW}"
                        f"[403] Access restricted:"
                        f"{Style.RESET_ALL}"
                    )

                    print(
                        f"      {url}"
                    )

                    if body:
                        print(
                            f"      {body[:300]}"
                        )

                    return None

                # ------------------------------------------------
                # 429:
                #
                # Retry after server reset.
                # ------------------------------------------------

                if resp.status == 429:

                    await api_limiter.handle_429(
                        resp.headers
                    )

                    continue

                # ------------------------------------------------
                # 5xx:
                #
                # Temporary server failure.
                # ------------------------------------------------

                if resp.status >= 500:

                    body = await resp.text()

                    raise RuntimeError(
                        f"HTTP {resp.status}: "
                        f"{body[:300]}"
                    )

                # ------------------------------------------------
                # Other errors.
                # ------------------------------------------------

                resp.raise_for_status()

                return await resp.json()

        except asyncio.CancelledError:

            raise

        except Exception as exc:

            if (
                attempt
                >= retries - 1
            ):

                print(
                    f"{Fore.RED}"
                    f"[FAIL] {url}"
                    f"{Style.RESET_ALL}"
                )

                print(
                    f"       "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                return None

            delay = min(
                2 ** attempt,
                15,
            )

            print(
                f"{Fore.YELLOW}"
                f"[RETRY "
                f"{attempt + 1}/{retries}] "
                f"{type(exc).__name__}: "
                f"{exc} → {delay}s"
                f"{Style.RESET_ALL}"
            )

            await asyncio.sleep(
                delay
            )

    return None


# ============================================================
# DISCOVER COMPETITION SEASONS
# ============================================================

async def discover_competition(
    session,
    code,
    wanted_seasons,
):
    """
    Query:

        /competitions/{code}

    and use the returned season catalogue.

    Returns:

        {
            "current_season": 2026,
            "available_seasons": [2026, 2025, ...],
            "competition": {...}
        }

    This prevents invalid requests such as:

        CL/matches?season=2026

    when that season is not available.
    """

    url = (
        f"{BASE_URL}/competitions/"
        f"{code}"
    )

    data = await fetch_json(
        session,
        url,
    )

    if not data:

        print(
            f"{Fore.YELLOW}"
            f"[DISCOVERY] "
            f"{code}: unable to read competition catalogue"
            f"{Style.RESET_ALL}"
        )

        return {
            "current_season": None,
            "available_seasons": [],
            "competition": None,
        }

    # --------------------------------------------------------
    # Current season.
    # --------------------------------------------------------

    current = (
        data.get(
            "currentSeason"
        )
        or {}
    )

    current_start = current.get(
        "startDate"
    )

    current_season = None

    if current_start:

        try:

            current_season = (
                parser.isoparse(
                    current_start
                ).year
            )

        except Exception:
            current_season = None

    # --------------------------------------------------------
    # Available seasons.
    # --------------------------------------------------------

    available = set()

    for season in (
        data.get(
            "seasons",
            []
        )
    ):

        start_date = season.get(
            "startDate"
        )

        if not start_date:
            continue

        try:

            year = (
                parser.isoparse(
                    start_date
                ).year
            )

            available.add(
                year
            )

        except Exception:
            continue

    # Include currentSeason if catalogue parsing somehow
    # omitted it.
    if current_season is not None:

        available.add(
            current_season
        )

    # Only seasons the caller actually wants.
    filtered = sorted(
        (
            year
            for year in available
            if year in wanted_seasons
        ),
        reverse=True,
    )

    print(
        f"{Fore.CYAN}"
        f"[SEASONS] {code}: "
        f"{', '.join(map(str, filtered)) if filtered else 'none'}"
        f"{Style.RESET_ALL}"
    )

    if current_season is not None:

        print(
            f"          current: "
            f"{current_season}"
        )

    return {
        "current_season": current_season,
        "available_seasons": filtered,
        "competition": data,
    }


# ============================================================
# FETCH TEAMS
# ============================================================

async def fetch_teams(
    session,
    code,
):
    """
    Fetch teams.

    Database writes are batched.
    """

    url = (
        f"{BASE_URL}/competitions/"
        f"{code}/teams"
    )

    data = await fetch_json(
        session,
        url,
    )

    if not data:
        return 0

    teams = data.get(
        "teams",
        []
    )

    if not teams:
        return 0

    records = []

    for team in teams:

        team_id = team.get(
            "id"
        )

        if team_id is None:
            continue

        records.append(
            (
                team_id,
                team.get("name"),
                team.get("shortName"),
                team.get("tla"),
                team.get("crest"),
                team.get("venue"),
                team.get("founded"),
            )
        )

    if not records:
        return 0

    pool = await get_pool()

    async with pool.acquire() as db:

        async with db.transaction():

            team_ids = [
                record[0]
                for record in records
            ]

            existing_rows = (
                await db.fetch(
                    """
                    SELECT id
                    FROM teams
                    WHERE id = ANY(
                        $1::bigint[]
                    )
                    """,
                    team_ids,
                )
            )

            existing_ids = {
                row["id"]
                for row in existing_rows
            }

            new_records = [
                record
                for record in records
                if record[0]
                not in existing_ids
            ]

            if new_records:

                await db.executemany(
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
                    ON CONFLICT(id)
                    DO NOTHING
                    """,
                    new_records,
                )

    return len(
        new_records
    )


# ============================================================
# BUILD MATCH RECORD
# ============================================================

def normalize_match_status(match):
    """
    Normalize Football Data API match status.

    The API has occasionally returned a datetime string
    in the status field, for example:

        status = "2026-10-18 16:30:00Z"

    Such values are invalid statuses.

    If the status is a datetime, derive the correct
    pre-match status from utcDate.
    """

    status = match.get("status")

    if not status:
        return None

    # --------------------------------------------------------
    # Detect corrupted datetime-in-status values.
    # --------------------------------------------------------

    if (
        isinstance(status, str)
        and len(status) >= 10
        and status[0:4].isdigit()
        and status[4] == "-"
        and status[7] == "-"
    ):
        utc_date = match.get("utcDate")

        if utc_date:
            return "TIMED"

        return "SCHEDULED"

    return status

def build_match_record(
    match,
    season,
):

    home = (
        match.get(
            "homeTeam"
        )
        or {}
    )

    away = (
        match.get(
            "awayTeam"
        )
        or {}
    )

    score = (
        match.get(
            "score"
        )
        or {}
    )

    full_time = (
        score.get(
            "fullTime"
        )
        or {}
    )

    home_score = (
        full_time.get(
            "home"
        )
    )

    if home_score is None:

        home_score = (
            full_time.get(
                "homeTeam"
            )
        )

    away_score = (
        full_time.get(
            "away"
        )
    )

    if away_score is None:

        away_score = (
            full_time.get(
                "awayTeam"
            )
        )

    competition = (
        match.get(
            "competition"
        )
        or {}
    )

    return (
        match.get("id"),
        competition.get(
            "name",
            "UNKNOWN",
        ),
        match.get(
            "matchday"
        ),
        parse_utc_date(
            match.get(
                "utcDate"
            )
        ),
        normalize_match_status(match),
        home.get("id"),
        away.get("id"),
        home_score,
        away_score,
        home.get("name"),
        away.get("name"),
        season,
    )


# ============================================================
# FETCH MATCHES
# ============================================================

async def fetch_matches(
    session,
    code,
    season,
    recent_season,
):
    """
    Fetch a single valid competition season.

    Historical:
        insert only

    Current:
        insert new
        update changed
    """

    url = (
        f"{BASE_URL}/competitions/"
        f"{code}/matches"
        f"?season={season}"
    )

    data = await fetch_json(
        session,
        url,
    )

    # 404/400/403/failed request:
    # fetch_json already handled it.
    if not data:
        return 0

    matches = data.get(
        "matches",
        []
    )

    if not matches:

        print(
            f"   → 0 matches "
            f"(season {season})"
        )

        return 0

    records = []

    for match in matches:

        if match.get("id") is None:
            continue

        records.append(
            build_match_record(
                match,
                season,
            )
        )

    if not records:
        return 0

    pool = await get_pool()

    new_count = 0
    updated_count = 0

    async with pool.acquire() as db:

        async with db.transaction():

            match_ids = [
                record[0]
                for record in records
            ]

            # ------------------------------------------------
            # ONE SELECT for entire season.
            # ------------------------------------------------

            existing_rows = (
                await db.fetch(
                    """
                    SELECT
                        id,
                        status,
                        home_score,
                        away_score,
                        utcdate
                    FROM matches
                    WHERE id = ANY(
                        $1::bigint[]
                    )
                    """,
                    match_ids,
                )
            )

            existing = {
                row["id"]: row
                for row in existing_rows
            }

            new_records = []
            update_records = []

            for record in records:

                match_id = record[0]

                old = existing.get(
                    match_id
                )

                # ------------------------------------------------
                # New match.
                # ------------------------------------------------

                if old is None:

                    new_records.append(
                        record
                    )

                    continue

                # ------------------------------------------------
                # Historical seasons are immutable.
                # ------------------------------------------------

                if season != recent_season:
                    continue

                (
                    _id,
                    _competition,
                    _matchday,
                    utc_date,
                    status,
                    _home_id,
                    _away_id,
                    home_score,
                    away_score,
                    _home_name,
                    _away_name,
                    _season,
                ) = record

                changed = (
                    old["status"]
                    != status
                    or
                    old["home_score"]
                    != home_score
                    or
                    old["away_score"]
                    != away_score
                    or
                    old["utcdate"]
                    != utc_date
                )

                if changed:

                    update_records.append(
                        (
                            status,
                            home_score,
                            away_score,
                            utc_date,
                            match_id,
                        )
                    )

            # ------------------------------------------------
            # Batch INSERT.
            # ------------------------------------------------

            if new_records:

                await db.executemany(
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
                    ON CONFLICT(id)
                    DO NOTHING
                    """,
                    new_records,
                )

                new_count = len(
                    new_records
                )

            # ------------------------------------------------
            # Batch UPDATE current season.
            # ------------------------------------------------

            if update_records:

                await db.executemany(
                    """
                    UPDATE matches
                    SET
                        status = $1,
                        home_score = $2,
                        away_score = $3,
                        utcdate = $4,
                        generated_at =
                            CURRENT_TIMESTAMP
                    WHERE id = $5
                    """,
                    update_records,
                )

                updated_count = len(
                    update_records
                )

    # --------------------------------------------------------
    # Output.
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

    return (
        new_count
        + updated_count
    )


# ============================================================
# UPDATE STANDINGS
# ============================================================

async def update_league_standings(
    session,
    code,
):
    """
    Fetch current standings.

    One API request + one batch PostgreSQL operation.
    """

    url = (
        f"{BASE_URL}/competitions/"
        f"{code}/standings"
    )

    data = await fetch_json(
        session,
        url,
    )

    if (
        not data
        or not data.get(
            "standings"
        )
    ):

        print(
            f"{Fore.YELLOW}"
            f"[Skip] {code} standings"
            f"{Style.RESET_ALL}"
        )

        return 0

    # --------------------------------------------------------
    # Prefer TOTAL standings.
    # --------------------------------------------------------

    table = None

    for standing in data.get(
        "standings",
        []
    ):

        if standing.get(
            "type"
        ) == "TOTAL":

            table = (
                standing.get(
                    "table"
                )
                or []
            )

            break

    if table is None:

        table = (
            data["standings"][0]
            .get(
                "table",
                []
            )
        )

    if not table:
        return 0

    # --------------------------------------------------------
    # Determine season from API response.
    # --------------------------------------------------------

    season_data = (
        data.get(
            "season"
        )
        or {}
    )

    start_date = season_data.get(
        "startDate"
    )

    if start_date:

        try:

            season_year = (
                parser.isoparse(
                    start_date
                ).year
            )

        except Exception:

            season_year = (
                datetime.now(
                    UTC
                ).year
            )

    else:

        season_year = (
            datetime.now(
                UTC
            ).year
        )

    records = []

    for standing in table:

        team = (
            standing.get(
                "team"
            )
            or {}
        )

        team_id = team.get(
            "id"
        )

        if team_id is None:
            continue

        records.append(
            (
                code,
                season_year,
                team_id,
                standing.get(
                    "position"
                ),
                standing.get(
                    "points"
                ),
                standing.get(
                    "won"
                ),
                standing.get(
                    "draw"
                ),
                standing.get(
                    "lost"
                ),
                standing.get(
                    "goalsFor"
                ),
                standing.get(
                    "goalsAgainst"
                ),
                standing.get(
                    "goalDifference"
                ),
            )
        )

    if not records:
        return 0

    pool = await get_pool()

    async with pool.acquire() as db:

        async with db.transaction():

            await db.executemany(
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
                    rank =
                        EXCLUDED.rank,
                    points =
                        EXCLUDED.points,
                    win =
                        EXCLUDED.win,
                    draw =
                        EXCLUDED.draw,
                    lose =
                        EXCLUDED.lose,
                    goals_for =
                        EXCLUDED.goals_for,
                    goals_against =
                        EXCLUDED.goals_against,
                    goal_diff =
                        EXCLUDED.goal_diff,
                    last_updated =
                        CURRENT_TIMESTAMP
                """,
                records,
            )

    print(
        f"{Fore.GREEN}"
        f"[OK] "
        f"{COMPETITION_MAP.get(code, code)} "
        f"standings updated "
        f"({len(records)} teams)"
        f"{Style.RESET_ALL}"
    )

    return len(records)


# ============================================================
# DATABASE VERIFICATION
# ============================================================

async def verify_database():

    pool = await get_pool()

    async with pool.acquire() as db:

        row = await db.fetchrow(
            """
            SELECT
                current_database()
                    AS database,
                current_schema()
                    AS schema,
                current_setting(
                    'search_path'
                ) AS search_path
            """
        )

    print(
        "\n[DATABASE]"
    )

    print(
        f"   database:    "
        f"{row['database']}"
    )

    print(
        f"   schema:      "
        f"{row['schema']}"
    )

    print(
        f"   search_path: "
        f"{row['search_path']}"
    )

    # --------------------------------------------------------
    # Safety checks.
    # --------------------------------------------------------

    if (
        row["database"]
        != "lilymac_db"
    ):

        raise RuntimeError(
            "SAFETY STOP: importer is not "
            "connected to lilymac_db."
        )

    if (
        row["schema"]
        != "henry_schema"
    ):

        raise RuntimeError(
            "SAFETY STOP: importer is not "
            "using henry_schema."
        )


# ============================================================
# PROCESS ONE LEAGUE
# ============================================================

async def process_league(
    session,
    league,
    code,
    wanted_seasons,
    recent_season,
    full_history,
    refresh_teams,
):
    """
    Process one competition.

    First:
        discover available seasons

    Then:
        optionally fetch teams

    Then:
        fetch valid seasons only
    """

    print(
        f"\n[LEAGUE] "
        f"{league} ({code})"
    )

    # --------------------------------------------------------
    # Discover actual API season catalogue.
    # --------------------------------------------------------

    catalogue = (
        await discover_competition(
            session,
            code,
            wanted_seasons,
        )
    )

    available_seasons = (
        catalogue[
            "available_seasons"
        ]
    )

    api_current_season = (
        catalogue[
            "current_season"
        ]
    )

    # --------------------------------------------------------
    # Teams.
    # --------------------------------------------------------

    if refresh_teams:

        new_teams = await fetch_teams(
            session,
            code,
        )

        print(
            f" → {new_teams} new teams"
        )

    else:

        print(
            " → teams skipped "
            "(use --refresh-teams)"
        )

    # --------------------------------------------------------
    # Normal mode:
    #
    # Use API's actual current season if it is within our
    # desired range.
    #
    # Otherwise use the newest available season.
    # --------------------------------------------------------

    if not full_history:

        target_season = None

        if (
            api_current_season
            in wanted_seasons
        ):

            target_season = (
                api_current_season
            )

        elif available_seasons:

            target_season = (
                available_seasons[0]
            )

        if target_season is None:

            print(
                f"{Fore.YELLOW}"
                f"   → No valid current "
                f"season available"
                f"{Style.RESET_ALL}"
            )

            return

        await fetch_matches(
            session,
            code,
            target_season,
            recent_season,
        )

        return

    # --------------------------------------------------------
    # Full history:
    #
    # Only request seasons actually present in catalogue.
    # --------------------------------------------------------

    if not available_seasons:

        print(
            f"{Fore.YELLOW}"
            f"   → No requested seasons "
            f"available"
            f"{Style.RESET_ALL}"
        )

        return

    print(
        f"   → importing valid seasons: "
        f"{', '.join(map(str, available_seasons))}"
    )

    for season in available_seasons:

        await fetch_matches(
            session,
            code,
            season,
            recent_season,
        )


# ============================================================
# ARGUMENTS
# ============================================================

def parse_arguments():

    parser_obj = argparse.ArgumentParser(
        description=(
            "LilyMac Hub Football Data importer"
        )
    )

    parser_obj.add_argument(
        "--full-history",
        action="store_true",
        help=(
            "Import all available seasons "
            "between 2023 and the current season."
        ),
    )

    parser_obj.add_argument(
        "--refresh-teams",
        action="store_true",
        help=(
            "Fetch teams from the API."
        ),
    )

    parser_obj.add_argument(
        "--skip-teams",
        action="store_true",
        help=(
            "Never fetch teams."
        ),
    )

    return parser_obj.parse_args()


# ============================================================
# MAIN
# ============================================================

async def main():

    args = parse_arguments()

    print(
        "[INIT] "
        "Season-aware rate-limited "
        "async fetch started..."
    )

    start_time = (
        asyncio.get_running_loop()
        .time()
    )

    # --------------------------------------------------------
    # Database safety.
    # --------------------------------------------------------

    await verify_database()

    print(
        "\n[DATABASE] "
        "Render PostgreSQL connection verified."
    )

    # --------------------------------------------------------
    # Current season based on calendar.
    #
    # Used only as a fallback/comparison.
    # Actual API current season is discovered per competition.
    # --------------------------------------------------------

    now = datetime.now(
        UTC
    )

    recent_season = (
        now.year
        if now.month >= 7
        else now.year - 1
    )

    # --------------------------------------------------------
    # Requested historical range.
    #
    # Current year down to 2023.
    # --------------------------------------------------------

    wanted_seasons = set(
        range(
            now.year,
            2022,
            -1,
        )
    )

    # --------------------------------------------------------
    # Team behavior.
    # --------------------------------------------------------

    if args.skip_teams:

        refresh_teams = False

    elif args.refresh_teams:

        refresh_teams = True

    elif args.full_history:

        refresh_teams = True

    else:

        refresh_teams = False

    # --------------------------------------------------------
    # Configuration.
    # --------------------------------------------------------

    print(
        "\n[CONFIG]"
        f"\n   API limit:       "
        f"{API_MAX_CALLS} calls/minute"
        f"\n   Safety margin:   "
        f"1 request"
        f"\n   Requested years: "
        f"{', '.join(map(str, sorted(wanted_seasons, reverse=True)))}"
        f"\n   Calendar recent: "
        f"{recent_season}"
        f"\n   Competitions:    "
        f"{len(LEAGUES)}"
        f"\n   Full history:    "
        f"{args.full_history}"
        f"\n   Refresh teams:   "
        f"{refresh_teams}"
    )

    # --------------------------------------------------------
    # HTTP connector.
    # --------------------------------------------------------

    connector = aiohttp.TCPConnector(
        limit=2,
        limit_per_host=2,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
    )

    try:

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=HTTP_TIMEOUT,
        ) as session:

            # ------------------------------------------------
            # Process competitions sequentially.
            #
            # This is deliberate.
            #
            # Every API request still passes through the
            # 9/minute limiter.
            # ------------------------------------------------

            for league, code in LEAGUES.items():

                await process_league(
                    session=session,
                    league=league,
                    code=code,
                    wanted_seasons=wanted_seasons,
                    recent_season=recent_season,
                    full_history=args.full_history,
                    refresh_teams=refresh_teams,
                )

            # ------------------------------------------------
            # Current standings.
            #
            # Standings endpoint returns latest/current table.
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

        # ----------------------------------------------------
        # Always close PostgreSQL pool.
        # ----------------------------------------------------

        await close_pool()

        elapsed = (
            asyncio.get_running_loop()
            .time()
            - start_time
        )

        print(
            "\n[DATABASE] "
            "PostgreSQL pool closed."
        )

        print(
            f"[DONE] "
            f"Importer completed in "
            f"{elapsed / 60:.2f} minutes."
        )

        print(
            f"[API] "
            f"Requests made: "
            f"{api_limiter.requests_total}"
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\n"
            f"{Fore.YELLOW}"
            "[STOP] "
            "Importer interrupted by user."
            f"{Style.RESET_ALL}"
        )
