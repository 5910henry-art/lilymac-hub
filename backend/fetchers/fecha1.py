#!/usr/bin/env python3
import asyncio
import aiohttp
import aiosqlite
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from dateutil import parser
from colorama import Fore, Style, init as color_init
from config import DB_FILE, BASE_URL, HEADERS, COMPETITION_MAP

# --------------------------------------------------
# Init
# --------------------------------------------------
color_init(autoreset=True)

KENYA = ZoneInfo("Africa/Nairobi")
UTC = timezone.utc

MAX_CONCURRENT = 3
API_DELAY = 1
semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# --------------------------------------------------
# Time helpers
# --------------------------------------------------
def now_kenya():
    return datetime.now(KENYA)

# --------------------------------------------------
# HTTP fetch helper
# --------------------------------------------------
async def fetch_json(session, url, retries=5):
    for attempt in range(retries):
        try:
            async with semaphore:
                await asyncio.sleep(API_DELAY)
                async with session.get(url, headers=HEADERS, timeout=15) as resp:
                    if resp.status == 429:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    resp.raise_for_status()
                    return await resp.json()
        except Exception:
            await asyncio.sleep(2 ** attempt)
            print(f"{Fore.RED}[FAIL] {url}{Style.RESET_ALL}")
    return None

# --------------------------------------------------
# Fetch teams
# --------------------------------------------------
async def fetch_teams(session, code, db):
    data = await fetch_json(session, f"{BASE_URL}/competitions/{code}/teams")
    if not data:
        return 0

    new_count = 0
    for t in data.get("teams", []):
        await db.execute("""
            INSERT OR IGNORE INTO teams
            (id, name, short_name, tla, crest, venue, founded)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            t.get("id"),
            t.get("name"),
            t.get("shortName"),
            t.get("tla"),
            t.get("crest"),
            t.get("venue"),
            t.get("founded")
        ))
        if db.total_changes > 0:
            new_count += 1

    await db.commit()
    return new_count

# --------------------------------------------------
# Fetch matches
# --------------------------------------------------
async def fetch_matches(session, code, season, recent_season, db):
    url = f"{BASE_URL}/competitions/{code}/matches?season={season}"
    data = await fetch_json(session, url)
    if not data:
        return 0

    new_count = 0
    updated_count = 0

    for m in data.get("matches", []):
        match_id = m.get("id")

        async with db.execute(
            "SELECT status, home_score, away_score FROM matches WHERE id=?",
            (match_id,)
        ) as cursor:
            row = await cursor.fetchone()

        home_score = m.get("score", {}).get("fullTime", {}).get("home")
        away_score = m.get("score", {}).get("fullTime", {}).get("away")
        status = m.get("status")

        utc_date = m.get("utcDate")
        if utc_date:
            utc_date = parser.isoparse(utc_date)
        else:
            utc_date = (
                datetime.now(UTC) + timedelta(days=2)
            ).replace(hour=15, minute=0, second=0, microsecond=0)

        if row:
            old_status, old_home, old_away = row
            if (
                season == recent_season
                and (old_status != status
                     or old_home != home_score
                     or old_away != away_score)
            ):
                await db.execute("""
                    UPDATE matches
                    SET status=?,
                        home_score=?,
                        away_score=?,
                        utcdate=?,
                        generated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                """, (status, home_score, away_score, utc_date, match_id))
                updated_count += 1
            continue

        await db.execute("""
            INSERT INTO matches (
                id, competition, matchday, utcdate, status,
                home_team_id, away_team_id,
                home_score, away_score,
                home_team_name, away_team_name,
                season, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            match_id,
            m.get("competition", {}).get("name", "UNKNOWN"),
            m.get("matchday"),
            utc_date,
            status,
            m.get("homeTeam", {}).get("id"),
            m.get("awayTeam", {}).get("id"),
            home_score,
            away_score,
            m.get("homeTeam", {}).get("name"),
            m.get("awayTeam", {}).get("name"),
            season
        ))
        new_count += 1

    await db.commit()

    if season == recent_season:
        print(f"   → {new_count} new, {updated_count} updated (season {season})")
    else:
        print(f"   → {new_count} new (old season {season})")

    return new_count + updated_count

# --------------------------------------------------
# Update standings
# --------------------------------------------------
async def update_league_standings(session, db, code):
    url = f"{BASE_URL}/competitions/{code}/standings"
    data = await fetch_json(session, url)

    if not data or not data.get("standings"):
        print(f"{Fore.YELLOW}[Skip] {code} standings{Style.RESET_ALL}")
        return 0

    table = data["standings"][0].get("table", [])
    if not table:
        return 0

    for s in table:
        team = s.get("team", {})
        season_year = s.get("season", {}).get("startDate", now_kenya()).year

        await db.execute("""
            INSERT INTO standings (
                league_code, season, team_id,
                rank, points, win, draw, lose,
                goals_for, goals_against, goal_diff,
                last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (league_code, season, team_id)
            DO UPDATE SET
                rank=excluded.rank,
                points=excluded.points,
                win=excluded.win,
                draw=excluded.draw,
                lose=excluded.lose,
                goals_for=excluded.goals_for,
                goals_against=excluded.goals_against,
                goal_diff=excluded.goal_diff,
                last_updated=CURRENT_TIMESTAMP
        """, (
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
            s.get("goalDifference")
        ))

    await db.commit()
    print(f"{Fore.GREEN}[OK] {COMPETITION_MAP.get(code, code)} standings updated{Style.RESET_ALL}")
    return len(table)

# --------------------------------------------------
# Main
# --------------------------------------------------
async def main():
    print("[INIT] SQLite multi-season fetch started...")

    async with aiohttp.ClientSession() as session, aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row

        LEAGUES = {
            "Premier League": "PL",
            "La Liga": "PD",
            "Serie A": "SA",
            "Bundesliga": "BL1",
            "Ligue 1": "FL1",
            "Champions League": "CL",
        }

        now = datetime.now(UTC)
        recent_season = now.year if now.month >= 7 else now.year - 1
        seasons = range(now.year - 1, 2022, -1)

        for league, code in LEAGUES.items():
            print(f"\n[LEAGUE] {league} ({code})")
            new_teams = await fetch_teams(session, code, db)
            print(f" → {new_teams} new teams")

            for season in seasons:
                await fetch_matches(session, code, season, recent_season, db)

        print("\n🚀 Updating standings...")
        for code in LEAGUES.values():
            await update_league_standings(session, db, code)

if __name__ == "__main__":
    asyncio.run(main())
