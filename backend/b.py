#!/usr/bin/env python3
"""
b.py — FINAL FIXED VERSION (PostgreSQL + robust matching)
"""

import os
import re
import unicodedata
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from sqlalchemy import create_engine, text

# ---------- CONFIG ----------
TIME_TOLERANCE_MINUTES = 360

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://henry:kyu@localhost:5432/virtualfootball"
)

PAIR_THRESHOLD = 118
SINGLE_STRONG = 68
SINGLE_MIN_OTHER = 50

# ---------- HELPERS ----------
def normalize_team(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    name = re.sub(r"\b(fc|cf|ac|sc|afc|rc|club)\b", "", name)
    name = re.sub(r"[^a-z ]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def pair_score(oh, oa, mh, ma):
    return max(
        fuzz.token_sort_ratio(oh, mh) + fuzz.token_sort_ratio(oa, ma),
        fuzz.token_sort_ratio(oh, ma) + fuzz.token_sort_ratio(oa, mh),
    )

def single_scores(oh, oa, mh, ma):
    scores = [
        fuzz.token_sort_ratio(oh, mh),
        fuzz.token_sort_ratio(oh, ma),
        fuzz.token_sort_ratio(oa, mh),
        fuzz.token_sort_ratio(oa, ma),
    ]
    scores.sort(reverse=True)
    return scores[0], scores[1]

def to_utc(series):
    dt = pd.to_datetime(series, errors="coerce")
    if dt.dt.tz is not None:
        return dt.dt.tz_convert("UTC").dt.floor("min")
    return dt.dt.tz_localize("UTC").dt.floor("min")

# ---------- LOAD FROM POSTGRES ----------
engine = create_engine(DATABASE_URL)

df_odds = pd.read_sql("SELECT * FROM live_odds", engine)
df_matches = pd.read_sql("SELECT * FROM matches", engine)

df_preds = pd.read_sql("""
SELECT match_id,
       (prediction_json->'probabilities'->>'home_win')::float AS p_home,
       (prediction_json->'probabilities'->>'draw')::float AS p_draw,
       (prediction_json->'probabilities'->>'away_win')::float AS p_away
FROM predictions
""", engine)

# ---------- DETECT MATCH TIME COLUMN ----------
time_col = None
for col in df_matches.columns:
    if col.lower() in ["utcdate", "utc_date", "match_time", "date"]:
        time_col = col
        break

if time_col is None:
    raise ValueError(f"No time column found in matches table: {df_matches.columns}")

print(f"🕒 Using match time column: {time_col}")

# ---------- PREP ----------
df_odds["home_norm"] = df_odds["home_team"].apply(normalize_team)
df_odds["away_norm"] = df_odds["away_team"].apply(normalize_team)

df_matches["home_norm"] = df_matches["home_team_name"].apply(normalize_team)
df_matches["away_norm"] = df_matches["away_team_name"].apply(normalize_team)

# ---------- TIME ALIGN ----------
df_odds["match_time"] = to_utc(df_odds["match_time"])
df_matches["utcdate"] = to_utc(df_matches[time_col])

# ---------- DEBUG ----------
print("\n=== SAMPLE DATA ===")
print(df_odds[["home_team","away_team","match_time"]].head(3))
print(df_matches[["home_team_name","away_team_name","utcdate"]].head(3))

# ---------- MATCH ----------
matched_rows = []
unmatched_rows = []

for _, odds in df_odds.iterrows():

    if pd.isna(odds["match_time"]):
        unmatched_rows.append(odds)
        continue

    start = odds["match_time"] - pd.Timedelta(minutes=TIME_TOLERANCE_MINUTES)
    end = odds["match_time"] + pd.Timedelta(minutes=TIME_TOLERANCE_MINUTES)

    candidates = df_matches[
        (df_matches["utcdate"] >= start) &
        (df_matches["utcdate"] <= end)
    ]

    if candidates.empty:
        print(f"\n❌ NO TIME MATCH: {odds['home_team']} vs {odds['away_team']} {odds['match_time']}")
        unmatched_rows.append(odds)
        continue

    found = None

    for _, match in candidates.iterrows():

        # exact match
        if odds["home_norm"] == match["home_norm"] and odds["away_norm"] == match["away_norm"]:
            found = match
            break

        # fuzzy pair
        ps = pair_score(
            odds["home_norm"], odds["away_norm"],
            match["home_norm"], match["away_norm"]
        )
        if ps >= PAIR_THRESHOLD:
            found = match
            break

        # partial fallback
        sb, so = single_scores(
            odds["home_norm"], odds["away_norm"],
            match["home_norm"], match["away_norm"]
        )
        if sb >= SINGLE_STRONG and so >= SINGLE_MIN_OTHER:
            found = match
            break

    if found is not None:
        matched_rows.append({
            "match_id": found["id"],
            "home_team": odds["home_team"],
            "away_team": odds["away_team"],
            "match_time": odds["match_time"],
            "home_odds": odds["home_odds"],
            "draw_odds": odds["draw_odds"],
            "away_odds": odds["away_odds"],
        })
    else:
        unmatched_rows.append(odds)

df_matched = pd.DataFrame(matched_rows)
df_unmatched = pd.DataFrame(unmatched_rows)

print(f"\n✅ Total matched: {len(df_matched)}")
print(f"⚠️ Total unmatched: {len(df_unmatched)}")

# ---------- JOIN PREDICTIONS ----------
if df_matched.empty:
    print("No matches — exiting")
    exit()

df_matched = df_matched.merge(df_preds, on="match_id", how="left")
df_matched = df_matched.dropna(subset=["p_home","p_draw","p_away"], how="all")

if df_matched.empty:
    print("No predictions — exiting")
    exit()

# ---------- EV ----------
df_matched["EV_home"] = df_matched["p_home"] * df_matched["home_odds"] - 1
df_matched["EV_draw"] = df_matched["p_draw"] * df_matched["draw_odds"] - 1
df_matched["EV_away"] = df_matched["p_away"] * df_matched["away_odds"] - 1

def best(row):
    evs = {
        "Home": row["EV_home"],
        "Draw": row["EV_draw"],
        "Away": row["EV_away"],
    }
    k = max(evs, key=evs.get)
    return k, evs[k]

df_matched[["Best","EV"]] = df_matched.apply(lambda r: pd.Series(best(r)), axis=1)

# ---------- SAVE (SAFE) ----------
with engine.begin() as conn:
    conn.execute(text("DELETE FROM bookmark"))

df_matched.to_sql("bookmark", engine, if_exists="append", index=False)

print(f"\n✅ Bookmark saved ({len(df_matched)} rows)")
