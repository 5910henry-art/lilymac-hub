#!/usr/bin/env python3
"""
fitcher.py – Incremental fetcher for players, lineups, match events, player stats
PostgreSQL version using asyncpg and config2.py
"""

import asyncio
import aiohttp
import sys
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.append(str(Path(__file__).resolve().parents[1]))

from config2 import BASE_URL, HEADERS, DB_SCHEMA, get_pool

# -------------------------
# Config
# -------------------------
KENYA = ZoneInfo("Africa/Nairobi")
MAX_CONCURRENT = 1
API_DELAY = 1  # seconds
RECENT_DAYS = 30

semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# -------------------------
# Logging
# -------------------------
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("fetch")


# -------------------------
# Helpers
# -------------------------
def now_ke():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def table(name: str) -> str:
    """Safely build a schema-qualified table name from fixed config."""
    return f"{DB_SCHEMA}.{name}"


async def fetch_json(session: aiohttp.ClientSession, url: str, retries: int = 3, backoff: int = 1):
    for attempt in range(retries):
        try:
            async with semaphore:
                await asyncio.sleep(API_DELAY)
                async with session.get(url, headers=HEADERS, timeout=30) as resp:
                    if resp.status == 429:
                        wait = backoff * (2 ** attempt)
                        log.warning("429 Rate limit -> waiting %.1fs", wait)
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as e:
            wait = backoff * (2 ** attempt)
            log.warning("Fetch error (%s) -> retrying in %.1fs", e, wait)
            await asyncio.sleep(wait)
    return None


async def batch_process(tasks, batch_size: int = 3):
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        await asyncio.gather(*batch)


# -------------------------
# Competitions
# -------------------------
async def fetch_competitions(session: aiohttp.ClientSession, pool):
    data = await fetch_json(session, f"{BASE_URL}/competitions")
    if not data:
        log.warning("No competitions data")
        return

    competitions = data.get("competitions", [])
    async with pool.acquire() as conn:
        for c in competitions:
            await conn.execute(
                f"""
                INSERT INTO {table("competitions")} (code, name, area, last_updated)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    area = EXCLUDED.area,
                    last_updated = EXCLUDED.last_updated
                """,
                c.get("code"),
                c.get("name"),
                c.get("area", {}).get("name"),
                now_ke(),
            )

    log.info("Saved %d competitions", len(competitions))


# -------------------------
# Players (incremental)
# -------------------------
async def fetch_team_players(session: aiohttp.ClientSession, pool, team_id: int):
    async with pool.acquire() as conn:
        exists = await conn.fetchrow(
            f"SELECT 1 FROM {table('players')} WHERE team_id = $1 LIMIT 1",
            team_id,
        )
        if exists:
            log.info("Players already exist for team %s", team_id)
            return

    data = await fetch_json(session, f"{BASE_URL}/teams/{team_id}")
    if not data:
        log.warning("No data for team %s", team_id)
        return

    squad = data.get("squad", [])
    async with pool.acquire() as conn:
        for p in squad:
            await conn.execute(
                f"""
                INSERT INTO {table("players")}
                    (id, name, team_id, position, rating, goals, assists, key_player, is_injured)
                VALUES
                    ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    team_id = EXCLUDED.team_id,
                    position = EXCLUDED.position,
                    rating = EXCLUDED.rating,
                    goals = EXCLUDED.goals,
                    assists = EXCLUDED.assists,
                    key_player = EXCLUDED.key_player,
                    is_injured = EXCLUDED.is_injured
                """,
                p.get("id"),
                p.get("name"),
                team_id,
                p.get("position"),
                p.get("rating"),
                p.get("goals", 0),
                p.get("assists", 0),
                bool(p.get("keyPlayer", False)),
                bool(p.get("injured", False)),
            )

    log.info("Saved %d players for team %s", len(squad), team_id)


# -------------------------
# Match Details (incremental)
# -------------------------
async def fetch_match_details(session: aiohttp.ClientSession, pool, match_id: int):
    async with pool.acquire() as conn:
        exists = await conn.fetchrow(
            f"SELECT 1 FROM {table('lineups')} WHERE match_id = $1 LIMIT 1",
            match_id,
        )
        if exists:
            log.info("Match %s already has lineups/events", match_id)
            return

    data = await fetch_json(session, f"{BASE_URL}/matches/{match_id}")
    if not data:
        log.warning("No data for match %s", match_id)
        return

    match = data.get("match", {})

    async with pool.acquire() as conn:
        # Lineups
        for side in ("homeTeam", "awayTeam"):
            team = match.get(side, {}) or {}
            team_id = team.get("id")

            for p in team.get("lineup", []) or []:
                player_id = p.get("id")
                position = p.get("position")

                exists = await conn.fetchrow(
                    f"""
                    SELECT 1
                    FROM {table('lineups')}
                    WHERE match_id = $1 AND team_id = $2 AND player_id = $3
                    LIMIT 1
                    """,
                    match_id,
                    team_id,
                    player_id,
                )
                if exists:
                    continue

                await conn.execute(
                    f"""
                    INSERT INTO {table('lineups')}
                        (match_id, team_id, player_id, position)
                    VALUES
                        ($1, $2, $3, $4)
                    """,
                    match_id,
                    team_id,
                    player_id,
                    position,
                )

        # Events (goals, assists, cards, subs)
        for e in match.get("events", []) or []:
            player_id = (e.get("player") or {}).get("id")
            team_id = (e.get("team") or {}).get("id")
            event_type = e.get("type")
            minute = e.get("minute")
            assisted_by = (e.get("assist") or {}).get("id") if e.get("assist") else None

            exists = await conn.fetchrow(
                f"""
                SELECT 1
                FROM {table('match_events')}
                WHERE match_id = $1 AND player_id = $2 AND event_type = $3 AND minute = $4
                LIMIT 1
                """,
                match_id,
                player_id,
                event_type,
                minute,
            )
            if exists:
                continue

            await conn.execute(
                f"""
                INSERT INTO {table('match_events')}
                    (match_id, team_id, player_id, event_type, minute)
                VALUES
                    ($1, $2, $3, $4, $5)
                """,
                match_id,
                team_id,
                player_id,
                event_type,
                minute,
            )

            if event_type == "GOAL" and player_id:
                await conn.execute(
                    f"UPDATE {table('players')} SET goals = COALESCE(goals, 0) + 1 WHERE id = $1",
                    player_id,
                )

            if assisted_by:
                await conn.execute(
                    f"UPDATE {table('players')} SET assists = COALESCE(assists, 0) + 1 WHERE id = $1",
                    assisted_by,
                )

    log.info("Match %s details saved (lineups + events + player stats)", match_id)


# -------------------------
# Main
# -------------------------
async def main():
    pool = await get_pool()
    try:
        async with aiohttp.ClientSession() as session:
            # Competitions
            await fetch_competitions(session, pool)

            # Teams
            async with pool.acquire() as conn:
                rows = await conn.fetch(f"SELECT id FROM {table('teams')}")
                teams = [row["id"] for row in rows]

            log.info("Found %d teams", len(teams))
            await batch_process(
                [fetch_team_players(session, pool, t) for t in teams],
                batch_size=3,
            )

            # Recent matches
            recent_date = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT id FROM {table('matches')} WHERE utcDate >= $1",
                    recent_date,
                )
                matches = [row["id"] for row in rows]

            log.info("Found %d recent matches (last %d days)", len(matches), RECENT_DAYS)
            await batch_process(
                [fetch_match_details(session, pool, m) for m in matches],
                batch_size=3,
            )

        log.info("ALL DONE")
    finally:
        await pool.close()


# -------------------------
# Entry
# -------------------------
if __name__ == "__main__":
    asyncio.run(main())
