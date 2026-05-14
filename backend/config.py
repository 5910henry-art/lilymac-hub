#!/usr/bin/env python3
"""
Configuration for Lilymac Prediction Hub

Optimized SQLite version
- Faster queries
- Better concurrency
- Stable under multiple workers
"""

import os
from datetime import timezone
from zoneinfo import ZoneInfo
import aiosqlite


# --------------------------------------
# Base directory & database
# --------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "football.db")


# --------------------------------------
# SQLite performance settings
# --------------------------------------

SQLITE_PRAGMAS = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA cache_size=-100000",      # ~100MB cache
    "PRAGMA mmap_size=268435456",     # 256MB memory mapped I/O
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000"
]


async def _init_pragmas(conn):
    """Apply performance PRAGMAs."""
    for pragma in SQLITE_PRAGMAS:
        await conn.execute(pragma)


# --------------------------------------
# Async database helpers
# --------------------------------------

async def query_db(sql: str, params=()):
    """
    Execute SELECT query and return rows as dictionaries.
    Opens a fresh SQLite connection per request to avoid
    threading issues with aiosqlite.
    """

    async with aiosqlite.connect(DB_FILE, timeout=30, isolation_level=None) as conn:
        conn.row_factory = aiosqlite.Row
        await _init_pragmas(conn)

        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]


async def execute_db(sql: str, params=()):
    """
    Execute INSERT / UPDATE / DELETE query safely.
    """

    async with aiosqlite.connect(DB_FILE, timeout=30, isolation_level=None) as conn:
        conn.row_factory = aiosqlite.Row
        await _init_pragmas(conn)

        await conn.execute(sql, params)
        await conn.commit()


# --------------------------------------
# Concurrency
# --------------------------------------

MAX_CONCURRENT = 10


# --------------------------------------
# Football Data API
# --------------------------------------

BASE_URL = "https://api.football-data.org/v4"

API_KEY = os.environ.get(
    "FOOTBALL_API_KEY",
    "122f5e4029e94637bdf313c05a579df3"
)

HEADERS = {
    "X-Auth-Token": API_KEY,
    "Content-Type": "application/json",
}


# --------------------------------------
# Competitions
# --------------------------------------

COMPETITION_MAP = {
    "PL": "Premier League",
    "PD": "La Liga",
    "SA": "Serie A",
    "BL1": "Bundesliga",
    "FL1": "Ligue 1",
    "CL": "Champions League",
}


# --------------------------------------
# Optional team news API
# --------------------------------------

TEAM_NEWS_API = None


# --------------------------------------
# Timezones
# --------------------------------------

UTC = timezone.utc
KENYA = ZoneInfo("Africa/Nairobi")


# --------------------------------------
# Predictors folder
# --------------------------------------

PREDICTORS_DIR = os.path.join(BASE_DIR, "predictors")


# --------------------------------------
# Query limits
# --------------------------------------

MAX_LIMIT = 500


# --------------------------------------
# Cache TTLs
# --------------------------------------

CACHE_TTL = {
    "/matches": 90,
    "/matches/recent": 90,
    "/matches/upcoming": 100,
}
