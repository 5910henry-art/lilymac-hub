#!/usr/bin/env python3
from config import get_db, query_db, execute_db
"""
dataM.py — Lilymac Prediction Hub DB Manager
Features:
- Initialize, reset, backup, restore database
- Drop, truncate, delete records, check records
- View schema and table info
- List tables and row counts
"""

import os
import shutil
import argparse
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

import aiosqlite  # Ensure aiosqlite is installed (used by get_db in most setups)

DB_FILE = "football.db"
BACKUP_DIR = "backups"
KENYA = ZoneInfo("Africa/Nairobi")


# -----------------------------
# Time Helper
# -----------------------------
def now_kenya() -> str:
    return datetime.now(KENYA).strftime("%Y-%m-%d %H:%M:%S")


# -----------------------------
# Confirmation Helper
# -----------------------------
def confirm(prompt: str, force: bool = False) -> bool:
    if force:
        return True
    response = input(f"{prompt} [y/N]: ").strip().lower()
    return response == "y"


# -----------------------------
# Backup / Restore
# -----------------------------
def backup_db() -> Optional[str]:
    if not os.path.exists(DB_FILE):
        print("❌ No database file found.")
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now(KENYA).strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = os.path.join(BACKUP_DIR, f"football_{timestamp}.db")
    shutil.copy(DB_FILE, backup_path)
    print(f"📦 Backup created: {backup_path}")
    return backup_path


def restore_db(path: str, force: bool = False) -> None:
    if not os.path.exists(path):
        print(f"❌ Backup not found: {path}")
        return
    if confirm(f"⚠️  This will overwrite {DB_FILE} with {path}. Continue?", force):
        shutil.copy(path, DB_FILE)
        print(f"✅ Restored database from {path} at {now_kenya()}.")
    else:
        print("❌ Operation cancelled.")


# -----------------------------
# Drop Tables
# -----------------------------
async def drop_tables(force: bool = False) -> None:
    conn = await get_db()
    # Ensure row factory if needed (some helpers expect it)
    try:
        conn.row_factory = aiosqlite.Row
    except Exception:
        # If get_db returns a wrapper without row_factory, ignore
        pass

    tables_raw = await query_db("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [t["name"] for t in tables_raw] if tables_raw else []

    if not tables:
        print("⚠️ No tables found.")
        return

    if not confirm("⚠️  Do you want to drop all tables? (y/N)", force):
        print("Select table to drop (or leave empty to cancel):")
        for i, t in enumerate(tables, 1):
            print(f"{i}. {t}")
        choice = input("Enter number of table: ").strip()
        if not choice or not choice.isdigit() or int(choice) < 1 or int(choice) > len(tables):
            print("❌ Operation cancelled.")
            return
        tables = [tables[int(choice) - 1]]

    backup_db()
    async with conn.execute("BEGIN"):
        for t in tables:
            await conn.execute(f"DROP TABLE IF EXISTS {t}")
        await conn.commit()

    print(f"✅ Dropped table(s): {', '.join(tables)} at {now_kenya()}")


# -----------------------------
# Delete Records
# -----------------------------
async def delete_records() -> None:
    tables_raw = await query_db("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t["name"] for t in tables_raw] if tables_raw else []
    if not tables:
        print("⚠️ No tables found.")
        return

    print("Select table to delete records from:")
    for i, t in enumerate(tables, 1):
        print(f"{i}. {t}")
    choice = input("Enter number: ").strip()
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(tables):
        print("❌ Operation cancelled.")
        return
    table = tables[int(choice) - 1]

    if not confirm(f"⚠️ This will delete ALL records in {table}. Continue?"):
        print("❌ Operation cancelled.")
        return

    conn = await get_db()
    await conn.execute(f"DELETE FROM {table}")
    await conn.commit()
    print(f"✅ All records deleted from {table} at {now_kenya()}")


# -----------------------------
# Truncate Table (alias)
# -----------------------------
async def truncate_table() -> None:
    await delete_records()


# -----------------------------
# Check Records
# -----------------------------
async def check_records() -> None:
    tables_raw = await query_db("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t["name"] for t in tables_raw] if tables_raw else []
    if not tables:
        print("⚠️ No tables found.")
        return

    print("Select table to check records:")
    for i, t in enumerate(tables, 1):
        print(f"{i}. {t}")
    choice = input("Enter number: ").strip()
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(tables):
        print("❌ Operation cancelled.")
        return
    table = tables[int(choice) - 1]

    rows = await query_db(f"SELECT * FROM {table} LIMIT 10")
    if not rows:
        print(f"⚠️ No records found in {table}.")
        return
    print(f"📄 Records in {table} (first 10):")
    for r in rows:
        # r may be aiosqlite.Row or dict-like
        try:
            print(dict(r))
        except Exception:
            print(r)


# -----------------------------
# Schema Info
# -----------------------------
async def schema_info() -> None:
    tables_raw = await query_db("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [t["name"] for t in tables_raw] if tables_raw else []
    if not tables:
        print("⚠️ No tables found.")
        return

    print("Database Schema Info:")
    for table in tables:
        print(f"\n📋 {table}:")
        rows = await query_db(f"PRAGMA table_info({table})")
        if not rows:
            print("  (no info)")
            continue
        for row in rows:
            # row typically has: cid, name, type, notnull, dflt_value, pk
            name = row.get("name") if isinstance(row, dict) else row["name"]
            typ = row.get("type") if isinstance(row, dict) else row["type"]
            pk = row.get("pk") if isinstance(row, dict) else row["pk"]
            pk_str = "PK" if pk else ""
            print(f"  • {name} ({typ}) {pk_str}")


# -----------------------------
# List Tables
# -----------------------------
async def list_tables() -> None:
    tables_raw = await query_db("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [t["name"] for t in tables_raw] if tables_raw else []
    if not tables:
        print("⚠️ No tables found.")
        return

    print("📋 Tables in database:")
    for t in tables:
        count_row = await query_db(f"SELECT COUNT(*) as count FROM {t}", one=True)
        count = count_row["count"] if count_row and "count" in count_row else (count_row[0] if count_row else 0)
        print(f"  • {t}: {count} rows")


# -----------------------------
# Create Tables (full version)
# -----------------------------
async def create_tables() -> None:
    conn = await get_db()
    sql = """
        -- -----------------------------
        -- Competitions & Teams
        -- -----------------------------
        CREATE TABLE IF NOT EXISTS competitions (
            code TEXT PRIMARY KEY,
            name TEXT,
            area TEXT,
            last_updated TEXT
        );

        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY,
            name TEXT,
            short_name TEXT,
            tla TEXT,
            crest TEXT,
            venue TEXT,
            founded INTEGER,
            last_updated TEXT
        );

        -- -----------------------------
        -- Players & Injuries
        -- -----------------------------
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY,
            name TEXT,
            team_id INTEGER,
            position TEXT,
            rating REAL,
            goals INTEGER DEFAULT 0,
            assists INTEGER DEFAULT 0,
            key_player BOOLEAN DEFAULT 0,
            is_injured BOOLEAN DEFAULT 0,
            UNIQUE(team_id, name)
        );

        CREATE TABLE IF NOT EXISTS injuries (
            id INTEGER PRIMARY KEY,
            team_id INTEGER,
            player_id INTEGER,
            injury_type TEXT,
            start_date TEXT,
            end_date TEXT,
            impact_factor REAL DEFAULT 0.1
        );

        -- -----------------------------
        -- Matches & Lineups
        -- -----------------------------
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY,
            competition TEXT,
            matchday INTEGER,
            utcDate TEXT,
            localDate TEXT,
            status TEXT,
            home_team_id INTEGER,
            away_team_id INTEGER,
            home_score INTEGER,
            away_score INTEGER,
            home_team_name TEXT,
            away_team_name TEXT,
            venue TEXT,
            generated_at TEXT,
            season INTEGER
        );

        CREATE TABLE IF NOT EXISTS lineups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            team_id INTEGER,
            player_id INTEGER,
            position TEXT
        );

        CREATE TABLE IF NOT EXISTS match_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            team_id INTEGER,
            player_id INTEGER,
            event_type TEXT,
            minute INTEGER
        );

        CREATE TABLE IF NOT EXISTS h2h (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            home_team_id INTEGER,
            away_team_id INTEGER,
            match_id INTEGER,
            home_score INTEGER,
            away_score INTEGER,
            date_played TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_h2h_match_id
        ON h2h(match_id);

        -- -----------------------------
        -- Standings & Stats
        -- -----------------------------
        CREATE TABLE IF NOT EXISTS standings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league_code TEXT,
            season INTEGER,
            team_id INTEGER,
            rank INTEGER,
            points INTEGER,
            win INTEGER,
            draw INTEGER,
            lose INTEGER,
            goals_for INTEGER,
            goals_against INTEGER,
            goal_diff INTEGER,
            last_updated TEXT,
            UNIQUE(league_code, season, team_id)
        );

        CREATE TABLE IF NOT EXISTS features (
            id INTEGER PRIMARY KEY,
            match_id INTEGER,
            home_team_id INTEGER,
            away_team_id INTEGER,
            avg_goals_for_last_5_home REAL,
            avg_goals_against_last_5_home REAL,
            avg_goals_for_last_5_away REAL,
            avg_goals_against_last_5_away REAL,
            home_form REAL,
            away_form REAL,
            h2h_win_pct REAL,
            key_player_missing INTEGER,
            predicted_home_goals REAL,
            predicted_away_goals REAL,
            generated_at TEXT
        );

        -- -----------------------------
        -- Prediction Models
        -- -----------------------------
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY,
            match_id INTEGER,
            model_version TEXT,
            prediction_json TEXT,
            confidence REAL,
            generated_at TEXT,
            UNIQUE(match_id, model_version)
        );

        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY,
            match_id INTEGER,
            model_version TEXT,
            prediction_json TEXT,
            confidence REAL,
            generated_at TEXT,
            UNIQUE(match_id, model_version)
        );

        CREATE TABLE IF NOT EXISTS value (
            match_id INTEGER PRIMARY KEY,
            home_team_id INTEGER,
            away_team_id INTEGER,
            home_goals_pred REAL,
            away_goals_pred REAL,
            most_likely_score TEXT,
            matches_used INTEGER,
            conf_score REAL,
            conf_btts REAL,
            conf_over_1_5 REAL,
            conf_over_2_5 REAL,
            conf_over_3_5 REAL,
            conf_over_4_5 REAL,
            over_1_5 BOOLEAN,
            over_2_5 BOOLEAN,
            over_3_5 BOOLEAN,
            over_4_5 BOOLEAN,
            btts_yes BOOLEAN,
            generated_at TEXT
        );

        -- -----------------------------
        -- Odds & Bookmarks
        -- -----------------------------
        CREATE TABLE IF NOT EXISTS live_odds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            match_time TEXT,
            home_odds REAL,
            draw_odds REAL,
            away_odds REAL,
            goals_line REAL,
            over_goals REAL,
            under_goals REAL,
            gg_yes REAL,
            gg_no REAL,
            fetched_at TEXT,
            UNIQUE (league, home_team, away_team, match_time)
        );

        CREATE TABLE IF NOT EXISTS bookmark (
            match_id INTEGER,
            home_team TEXT,
            away_team TEXT,
            home_odds REAL,
            draw_odds REAL,
            away_odds REAL,
            p_home REAL,
            p_draw REAL,
            p_away REAL,
            EV_home REAL,
            EV_draw REAL,
            EV_away REAL,
            Best_EV_Bet TEXT,
            Top_EV_Value REAL,
            generated_at TEXT
        );

        -- -----------------------------
        -- Accumulator (folds / tips)
        -- -----------------------------
        CREATE TABLE IF NOT EXISTS accumulator (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            home_team_id INTEGER NOT NULL,
            away_team_id INTEGER NOT NULL,
            home_team_name TEXT NOT NULL,
            away_team_name TEXT NOT NULL,
            match_time TEXT NOT NULL,
            match_status TEXT NOT NULL,
            market TEXT NOT NULL,
            selection TEXT NOT NULL,
            probability REAL NOT NULL,
            prob_btts REAL,
            prob_over_1_5 REAL,
            prob_over_2_5 REAL,
            prob_over_3_5 REAL,
            prob_over_4_5 REAL,
            model_version TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            UNIQUE(match_id, market, selection)
        );
    """
    await conn.executescript(sql)
    # commit just to be safe (executescript should apply changes)
    try:
        await conn.commit()
    except Exception:
        pass
    print(f"✅ Full DB tables + indexes created at {now_kenya()}.")


# -----------------------------
# Reset DB
# -----------------------------
async def reset_db(force: bool = False) -> None:
    if not confirm("⚠️  This will DELETE and RECREATE the database. Continue?", force):
        print("❌ Operation cancelled.")
        return
    backup_db()
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print(f"🗑️  Deleted old {DB_FILE}.")
    await create_tables()
    print(f"✅ Database reset successfully at {now_kenya()}")


# -----------------------------
# Init DB
# -----------------------------
async def init_db() -> None:
    await create_tables()


# -----------------------------
# CLI / Main
# -----------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="🏗️ Lilymac Prediction Hub — DB Manager")
    parser.add_argument(
        "command",
        choices=["init", "info", "drop", "reset", "backup", "restore", "delete", "check", "schema", "truncate", "list"],
        help="Action to perform"
    )
    parser.add_argument("--path", help="Path to backup for restore")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompts")
    args = parser.parse_args()

    if args.command == "backup":
        backup_db()
    elif args.command == "restore":
        if not args.path:
            print("❌ Please provide --path to restore a backup.")
        else:
            restore_db(args.path, args.force)
    elif args.command == "info":
        asyncio.run(list_tables())
    elif args.command == "list":
        asyncio.run(list_tables())
    elif args.command == "drop":
        asyncio.run(drop_tables(args.force))
    elif args.command == "reset":
        asyncio.run(reset_db(args.force))
    elif args.command == "init":
        asyncio.run(init_db())
    elif args.command == "delete":
        asyncio.run(delete_records())
    elif args.command == "check":
        asyncio.run(check_records())
    elif args.command == "schema":
        asyncio.run(schema_info())
    elif args.command == "truncate":
        asyncio.run(truncate_table())
    else:
        print("Unknown command. Use -h for help.")


# -----------------------------
# Run Directly
# -----------------------------
if __name__ == "__main__":
    main()
