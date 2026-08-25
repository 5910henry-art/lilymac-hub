#!/usr/bin/env python3

import asyncio
import os
import asyncpg


DATABASE_URL = os.getenv("RENDER_DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")


SQL = """
CREATE SCHEMA IF NOT EXISTS henry_schema;

CREATE TABLE IF NOT EXISTS henry_schema.competitions (
    code TEXT PRIMARY KEY,
    name TEXT,
    area TEXT,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS henry_schema.teams (
    id INTEGER PRIMARY KEY,
    name TEXT,
    short_name TEXT,
    tla TEXT,
    crest TEXT,
    venue TEXT,
    founded INTEGER,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS henry_schema.players (
    id INTEGER PRIMARY KEY,
    name TEXT,
    team_id INTEGER,
    position TEXT,
    rating REAL,
    goals INTEGER DEFAULT 0,
    assists INTEGER DEFAULT 0,
    key_player BOOLEAN DEFAULT FALSE,
    is_injured BOOLEAN DEFAULT FALSE,
    UNIQUE(team_id, name)
);

CREATE TABLE IF NOT EXISTS henry_schema.injuries (
    id INTEGER PRIMARY KEY,
    team_id INTEGER,
    player_id INTEGER,
    injury_type TEXT,
    start_date TEXT,
    end_date TEXT,
    impact_factor REAL DEFAULT 0.1
);

CREATE TABLE IF NOT EXISTS henry_schema.matches (
    id INTEGER PRIMARY KEY,
    competition TEXT,
    matchday INTEGER,
    utcdate TIMESTAMPTZ,
    localdate TIMESTAMPTZ,
    status TEXT,
    home_team_id INTEGER,
    away_team_id INTEGER,
    home_score INTEGER,
    away_score INTEGER,
    home_team_name TEXT,
    away_team_name TEXT,
    venue TEXT,
    generated_at TIMESTAMPTZ,
    season INTEGER
);

CREATE TABLE IF NOT EXISTS henry_schema.lineups (
    id SERIAL PRIMARY KEY,
    match_id INTEGER,
    team_id INTEGER,
    player_id INTEGER,
    position TEXT
);

CREATE TABLE IF NOT EXISTS henry_schema.match_events (
    id SERIAL PRIMARY KEY,
    match_id INTEGER,
    team_id INTEGER,
    player_id INTEGER,
    event_type TEXT,
    minute INTEGER
);

CREATE TABLE IF NOT EXISTS henry_schema.h2h (
    id SERIAL PRIMARY KEY,
    home_team_id INTEGER,
    away_team_id INTEGER,
    match_id INTEGER,
    home_score INTEGER,
    away_score INTEGER,
    date_played TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_h2h_match_id
ON henry_schema.h2h(match_id);

CREATE TABLE IF NOT EXISTS henry_schema.standings (
    id SERIAL PRIMARY KEY,
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
    last_updated TIMESTAMPTZ,
    UNIQUE(league_code, season, team_id)
);

CREATE TABLE IF NOT EXISTS henry_schema.features (
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
    generated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS henry_schema.predictions (
    id INTEGER PRIMARY KEY,
    match_id INTEGER,
    model_version TEXT,
    prediction_json TEXT,
    confidence REAL,
    generated_at TIMESTAMPTZ,
    UNIQUE(match_id, model_version)
);

CREATE TABLE IF NOT EXISTS henry_schema.models (
    id INTEGER PRIMARY KEY,
    match_id INTEGER,
    model_version TEXT,
    prediction_json TEXT,
    confidence REAL,
    generated_at TIMESTAMPTZ,
    UNIQUE(match_id, model_version)
);

CREATE TABLE IF NOT EXISTS henry_schema.value (
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
    generated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS henry_schema.live_odds (
    id SERIAL PRIMARY KEY,
    league TEXT,
    home_team TEXT,
    away_team TEXT,
    match_time TIMESTAMPTZ,
    home_odds REAL,
    draw_odds REAL,
    away_odds REAL,
    goals_line REAL,
    over_goals REAL,
    under_goals REAL,
    gg_yes REAL,
    gg_no REAL,
    fetched_at TIMESTAMPTZ,
    UNIQUE(league, home_team, away_team, match_time)
);

CREATE TABLE IF NOT EXISTS henry_schema.bookmark (
    match_id INTEGER,
    home_team TEXT,
    away_team TEXT,
    home_odds REAL,
    draw_odds REAL,
    away_odds REAL,
    p_home REAL,
    p_draw REAL,
    p_away REAL,
    ev_home REAL,
    ev_draw REAL,
    ev_away REAL,
    best_ev_bet TEXT,
    top_ev_value REAL,
    generated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS henry_schema.accumulator (
    id SERIAL PRIMARY KEY,
    match_id INTEGER NOT NULL,
    home_team_id INTEGER NOT NULL,
    away_team_id INTEGER NOT NULL,
    home_team_name TEXT NOT NULL,
    away_team_name TEXT NOT NULL,
    match_time TIMESTAMPTZ NOT NULL,
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
    generated_at TIMESTAMPTZ NOT NULL,
    UNIQUE(match_id, market, selection)
);
"""


async def main():
    print("[INIT] Connecting to PostgreSQL...")

    conn = await asyncpg.connect(
        DATABASE_URL
    )

    try:
        await conn.execute(SQL)

        await conn.execute(
            "SET search_path TO henry_schema"
        )

        rows = await conn.fetch("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'henry_schema'
            ORDER BY tablename
        """)

        print("\n[OK] PostgreSQL database initialized.")
        print("[OK] Schema: henry_schema")
        print("\n[TABLES]")

        for row in rows:
            print(f"  ✓ {row['tablename']}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
