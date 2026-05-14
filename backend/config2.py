#!/usr/bin/env python3
"""
Configuration for Lilymac Prediction Hub

PostgreSQL version
- Async with asyncpg
- Connection pool for concurrency
- Supports :named params (auto-converted to $1, $2 for asyncpg)
"""

import os
import asyncio
import re
from datetime import timezone
from zoneinfo import ZoneInfo
import asyncpg

# --------------------------------------
# Database
# --------------------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://henry:kyu@localhost:5432/virtualfootball"
)

DB_SCHEMA = "henry_schema"

# Connection pool (initialized lazily)
_pool: asyncpg.pool.Pool = None
MAX_CONCURRENT = 10

# --------------------------------------
# Named → Positional Converter
# --------------------------------------
_named_param_pattern = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")


def _convert_named_to_positional(sql: str, params):
    """
    Convert :named params → $1, $2 for asyncpg
    """
    if params is None:
        return sql, ()

    # Already positional
    if isinstance(params, (list, tuple)):
        return sql, tuple(params)

    # Not a dict → wrap
    if not isinstance(params, dict):
        return sql, (params,)

    keys = []

    def replacer(match):
        key = match.group(1)
        keys.append(key)
        return f"${len(keys)}"

    new_sql = _named_param_pattern.sub(replacer, sql)

    try:
        new_params = tuple(params[k] for k in keys)
    except KeyError as e:
        raise KeyError(f"Missing SQL parameter: {e.args[0]}")

    return new_sql, new_params


# --------------------------------------
# Connection Pool
# --------------------------------------
async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=1,
            max_size=MAX_CONCURRENT,
            command_timeout=60
        )
    return _pool


# --------------------------------------
# Async database helpers
# --------------------------------------
async def query_db(sql: str, params=()):
    """
    Execute SELECT query and return rows as dictionaries.
    Supports :named params automatically.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        sql, params = _convert_named_to_positional(sql, params)
        records = await conn.fetch(sql, *params)
        return [dict(r) for r in records]


async def execute_db(sql: str, params=()):
    """
    Execute INSERT / UPDATE / DELETE query safely.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        sql, params = _convert_named_to_positional(sql, params)
        await conn.execute(sql, *params)


# --------------------------------------
# Football Data API
# --------------------------------------
BASE_URL = "https://api.football-data.org/v4"
API_KEY = os.environ.get("FOOTBALL_API_KEY", "122f5e4029e94637bdf313c05a579df3")

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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
