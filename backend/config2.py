#!/usr/bin/env python3
"""
Lilymac Prediction Hub
Central PostgreSQL configuration.

-- All database connections use henry_schema.
- asyncpg is used for async PostgreSQL access.
"""

import os
import re
from datetime import timezone
from zoneinfo import ZoneInfo

import asyncpg


# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Set DATABASE_URL to the local or deployment PostgreSQL database."
    )

if DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql+asyncpg://",
        "postgresql://",
        1,
    )

DB_SCHEMA = "henry_schema"

MAX_CONCURRENT = 10

_pool: asyncpg.Pool | None = None
# ============================================================
# NAMED PARAMETER CONVERTER
# ============================================================

_named_param_pattern = re.compile(
    r":([A-Za-z_][A-Za-z0-9_]*)"
)


def _convert_named_to_positional(sql: str, params):
    """
    Convert:

        WHERE id = :id AND season = :season

    into:

        WHERE id = $1 AND season = $2

    for asyncpg.
    """

    if params is None:
        return sql, ()

    # Already positional.
    if isinstance(params, (list, tuple)):
        return sql, tuple(params)

    # Single non-dict parameter.
    if not isinstance(params, dict):
        return sql, (params,)

    keys = []

    def replacer(match):
        key = match.group(1)
        keys.append(key)
        return f"${len(keys)}"

    new_sql = _named_param_pattern.sub(
        replacer,
        sql,
    )

    try:
        new_params = tuple(params[key] for key in keys)
    except KeyError as exc:
        raise KeyError(
            f"Missing SQL parameter: {exc.args[0]}"
        ) from exc

    return new_sql, new_params


# ============================================================
# CONNECTION POOL
# ============================================================

async def get_pool():
    """
    Return the shared PostgreSQL connection pool.

    Every connection automatically uses:

        henry_schema, public
    """

    global _pool

    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=1,
            max_size=MAX_CONCURRENT,
            command_timeout=60,
            server_settings={
                "search_path": f"{DB_SCHEMA},public"
            },
        )

    return _pool


# ============================================================
# DATABASE HELPERS
# ============================================================

async def query_db(sql: str, params=()):
    """
    Execute SELECT and return dictionaries.
    """

    pool = await get_pool()

    sql, params = _convert_named_to_positional(
        sql,
        params,
    )

    async with pool.acquire() as conn:
        records = await conn.fetch(
            sql,
            *params,
        )

        return [dict(row) for row in records]


async def execute_db(sql: str, params=()):
    """
    Execute INSERT / UPDATE / DELETE.
    """

    pool = await get_pool()

    sql, params = _convert_named_to_positional(
        sql,
        params,
    )

    async with pool.acquire() as conn:
        return await conn.execute(
            sql,
            *params,
        )


# ============================================================
# CLOSE DATABASE
# ============================================================

async def close_pool():
    """
    Close the PostgreSQL connection pool cleanly.
    """

    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None


# ============================================================
# DATABASE IDENTITY CHECK
# ============================================================

async def get_database_info():
    """
    Return the actual PostgreSQL database identity.

    Useful for verifying that scripts are connected to
    intended  PostgreSQL and the correct schema.
    """

    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                current_database() AS database,
                current_schema() AS schema,
                current_setting('search_path') AS search_path,
                current_user AS user
            """
        )

        return dict(row)


# ============================================================
# FOOTBALL DATA API
# ============================================================

BASE_URL = "https://api.football-data.org/v4"

API_KEY = os.environ.get("FOOTBALL_API_KEY")

if not API_KEY:
    raise RuntimeError("FOOTBALL_API_KEY is not set.")

HEADERS = {
    "X-Auth-Token": API_KEY,
    "Content-Type": "application/json",
}

if not API_KEY:
    raise RuntimeError(
        "FOOTBALL_API_KEY is not set."
    )

HEADERS = {
    "X-Auth-Token": API_KEY,
    "Content-Type": "application/json",
}


# ============================================================
# COMPETITIONS
# ============================================================

COMPETITION_MAP = {
    "PL": "Premier League",
    "PD": "La Liga",
    "SA": "Serie A",
    "BL1": "Bundesliga",
    "FL1": "Ligue 1",
    "CL": "Champions League",
}


# ============================================================
# OPTIONAL TEAM NEWS API
# ============================================================

TEAM_NEWS_API = None


# ============================================================
# TIMEZONES
# ============================================================

UTC = timezone.utc
KENYA = ZoneInfo("Africa/Nairobi")


# ============================================================
# PROJECT DIRECTORIES
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

PREDICTORS_DIR = os.path.join(
    BASE_DIR,
    "predictors",
)


# ============================================================
# QUERY LIMITS
# ============================================================

MAX_LIMIT = 500


# ============================================================
# CACHE TTLs
# ============================================================

CACHE_TTL = {
    "/matches": 90,
    "/matches/recent": 90,
    "/matches/upcoming": 100,
}
