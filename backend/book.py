#!/usr/bin/env python3
"""
book.py
- Matches live_odds to matches
- Handles team and league normalization
- Calculates EV for 1X2, Totals (0.5/1.5/2.5/3.5) and BTTS
- Selects best EV bet and computes Kelly stake
- Writes full betting board to both SQLite (football.db) and PostgreSQL (DATABASE_URL)
- Prints unmatched rows
"""

import os
import re
import unicodedata
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from sqlalchemy import create_engine
import sqlite3

# ---------- CONFIG ----------
BANKROLL = 10_000
KELLY_FRACTION = 0.25
MAX_STAKE_PCT = 0.05

PAIR_THRESHOLD = 118
SINGLE_STRONG = 68
SINGLE_MIN_OTHER = 50

TIME_TOLERANCE_MINUTES = 15

DB_PATH = "football.db"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://henry:kyu@localhost:5432/virtualfootball"
)

# ---------- LEAGUE & TEAM ALIASES ----------
LEAGUE_ALIASES = {
    "la liga": "la liga",
    "primera division": "la liga",
    "champions league": "champions league",
    "uefa champions league": "champions league",
    "premier league": "premier league",
    "ligue": "ligue",
    "serie a": "serie a",
    "bundesliga": "bundesliga",
}
TEAM_ALIASES = {
    "ac milan": "AC Milan",
    "milan": "AC Milan",
    "inter milan": "FC Internazionale Milano",
    "internazionale": "FC Internazionale Milano",
    "fc inter": "FC Internazionale Milano",
    "napoli": "SSC Napoli",
    "lazio": "SS Lazio",
    "atalanta bc": "Atalanta BC",
    "atalanta": "Atalanta BC",
    "torino": "Torino FC",
    "parma": "Parma Calcio 1913",
    "parma calcio": "Parma Calcio 1913",
    "parma calcio 1913": "Parma Calcio 1913",
    "juventus": "Juventus FC",
    "fiorentina": "ACF Fiorentina",
    "acf fiorentina": "ACF Fiorentina",
    "roma": "AS Roma",
    "as roma": "AS Roma",
    "cagliari": "Cagliari Calcio",
    "bologna": "Bologna FC 1909",
    "bologna fc": "Bologna FC 1909",
    "sassuolo": "US Sassuolo Calcio",
    "us sassuolo calcio": "US Sassuolo Calcio",
    "udinese": "Udinese Calcio",
    "genoa": "Genoa CFC",
    "genoa cfc": "Genoa CFC",
    "hellas verona": "Hellas Verona FC",
    "hellas verona fc": "Hellas Verona FC",
    "pisa": "Pisa 1909",
    "como": "Como 1907",
    "lecce": "US Lecce",
    "salernitana": "US Salernitana 1919",
    "us salernitana 1919": "US Salernitana 1919",
    "venezia": "Venezia FC",
    "empoli": "Empoli FC",
    "frosinone": "Frosinone Calcio",
    "monza": "AC Monza",
}

# ---------- HELPERS ----------
def normalize_team(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    name = re.sub(r"\b(fc|cf|ac|sc|afc|rc|sk|ud|club)\b", "", name)
    name = re.sub(r"\d{4}", "", name)
    name = re.sub(r"[^a-z ]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return TEAM_ALIASES.get(name, name)

def apply_league_alias(league: str) -> str:
    if not isinstance(league, str):
        return ""
    return LEAGUE_ALIASES.get(league.lower(), league.lower())

def pair_score(oh, oa, mh, ma):
    return max(
        fuzz.token_sort_ratio(str(oh), str(mh)) + fuzz.token_sort_ratio(str(oa), str(ma)),
        fuzz.token_sort_ratio(str(oh), str(ma)) + fuzz.token_sort_ratio(str(oa), str(mh)),
    )

def single_scores(oh, oa, mh, ma):
    scores = [
        fuzz.token_sort_ratio(str(oh), str(mh)),
        fuzz.token_sort_ratio(str(oh), str(ma)),
        fuzz.token_sort_ratio(str(oa), str(mh)),
        fuzz.token_sort_ratio(str(oa), str(ma)),
    ]
    scores.sort(reverse=True)
    return scores[0], scores[1]

def kelly_fraction(p, odds):
    try:
        if odds is None or np.isnan(odds) or odds <= 1:
            return 0.0
        if p is None or np.isnan(p):
            return 0.0
        b = odds - 1.0
        f = (p * odds - 1.0) / b
        return max(0.0, f)
    except Exception:
        return 0.0

# ---------- LOAD DATA ----------
# SQLite
conn_sqlite = sqlite3.connect(DB_PATH)

try:
    df_odds = pd.read_sql("SELECT * FROM live_odds", conn_sqlite)
except Exception:
    df_odds = pd.DataFrame()

try:
    df_matches = pd.read_sql("SELECT * FROM matches", conn_sqlite)
except Exception:
    df_matches = pd.DataFrame()

sql_preds = """
SELECT
    p.match_id,
    p.prediction_json,
    CAST(json_extract(p.prediction_json, '$.prediction') AS TEXT) AS model_prediction,
    CAST(json_extract(p.prediction_json, '$.probabilities.home_win') AS REAL) AS p_home,
    CAST(json_extract(p.prediction_json, '$.probabilities.draw') AS REAL) AS p_draw,
    CAST(json_extract(p.prediction_json, '$.probabilities.away_win') AS REAL) AS p_away,
    p.generated_at AS pred_generated_at
FROM predictions p
"""
try:
    df_preds = pd.read_sql(sql_preds, conn_sqlite)
except Exception:
    df_preds = pd.DataFrame()

sql_value = """
SELECT
    match_id,
    conf_btts AS p_btts,
    conf_over_1_5 AS p_over15,
    conf_over_2_5 AS p_over25,
    conf_over_3_5 AS p_over35
FROM value
"""
try:
    df_value = pd.read_sql(sql_value, conn_sqlite)
except Exception:
    df_value = pd.DataFrame()

conn_sqlite.close()

# ---------- PREP ----------
if df_odds.empty:
    print("No live_odds rows found — exiting")
    raise SystemExit(0)

for col in [
    "home_team", "away_team", "league", "match_time",
    "home_odds","draw_odds","away_odds",
    "over05","under05","over15","under15","over25","under25","over35","under35",
    "gg_odds","ng_odds"
]:
    if col not in df_odds.columns:
        df_odds[col] = np.nan if col not in ["home_team","away_team","league","match_time"] else ""

df_odds["home_norm"] = df_odds["home_team"].apply(normalize_team)
df_odds["away_norm"] = df_odds["away_team"].apply(normalize_team)
df_odds["league_norm"] = df_odds["league"].apply(apply_league_alias)
df_odds["match_time"] = pd.to_datetime(df_odds["match_time"], utc=True, errors="coerce").dt.floor("min")

if not df_matches.empty:
    for col in ["home_team_name","away_team_name","competition","utcDate","id"]:
        if col not in df_matches.columns:
            df_matches[col] = ""
    df_matches["home_norm"] = df_matches["home_team_name"].apply(normalize_team)
    df_matches["away_norm"] = df_matches["away_team_name"].apply(normalize_team)
    df_matches["league_norm"] = df_matches["competition"].apply(apply_league_alias)
    df_matches["utcDate"] = pd.to_datetime(df_matches["utcDate"], utc=True, errors="coerce").dt.floor("min")
else:
    df_matches = pd.DataFrame(columns=["id","home_norm","away_norm","league_norm","utcDate"])

# ---------- MATCHING ----------
matched_rows = []
unmatched_rows = []

for _, odds in df_odds.iterrows():
    start = pd.NaT if pd.isna(odds["match_time"]) else odds["match_time"] - pd.Timedelta(minutes=TIME_TOLERANCE_MINUTES)
    end = pd.NaT if pd.isna(odds["match_time"]) else odds["match_time"] + pd.Timedelta(minutes=TIME_TOLERANCE_MINUTES)
    candidates = df_matches if pd.isna(odds["match_time"]) else df_matches[
        (df_matches["utcDate"] >= start) &
        (df_matches["utcDate"] <= end) &
        (df_matches["league_norm"] == odds["league_norm"])
    ]

    found_match = None
    for _, match in candidates.iterrows() if not candidates.empty else []:
        if (odds["home_norm"] == match["home_norm"] and odds["away_norm"] == match["away_norm"]) or \
           (odds["home_norm"] == match["away_norm"] and odds["away_norm"] == match["home_norm"]):
            found_match = match
            break

        ps = pair_score(odds["home_norm"], odds["away_norm"], match["home_norm"], match["away_norm"])
        if ps >= PAIR_THRESHOLD:
            found_match = match
            break

        sb, so = single_scores(odds["home_norm"], odds["away_norm"], match["home_norm"], match["away_norm"])
        if sb >= SINGLE_STRONG and so >= SINGLE_MIN_OTHER:
            found_match = match
            break

    if found_match is not None:
        matched_rows.append({
            "match_id": found_match["id"],
            "league": odds.get("league",""),
            "home_team": odds.get("home_team",""),
            "away_team": odds.get("away_team",""),
            "match_time": odds.get("match_time"),
            "home_odds": odds.get("home_odds", np.nan),
            "draw_odds": odds.get("draw_odds", np.nan),
            "away_odds": odds.get("away_odds", np.nan),
            "over05": odds.get("over05", np.nan),
            "under05": odds.get("under05", np.nan),
            "over15": odds.get("over15", np.nan),
            "under15": odds.get("under15", np.nan),
            "over25": odds.get("over25", np.nan),
            "under25": odds.get("under25", np.nan),
            "over35": odds.get("over35", np.nan),
            "under35": odds.get("under35", np.nan),
            "gg_odds": odds.get("gg_odds", np.nan),
            "ng_odds": odds.get("ng_odds", np.nan),
        })
    else:
        unmatched_rows.append(odds)

df_matched = pd.DataFrame(matched_rows)
df_unmatched = pd.DataFrame(unmatched_rows)
print(f"✅ Total live_odds rows matched: {len(df_matched)}")
print(f"⚠️ Total unmatched rows: {len(df_unmatched)}")

# ---------- JOIN PREDICTIONS + VALUE ----------
if not df_matched.empty:
    if not df_preds.empty:
        df_matched = df_matched.merge(df_preds, on="match_id", how="left")
    else:
        for col in ["p_home","p_draw","p_away","model_prediction"]:
            df_matched[col] = np.nan
    if not df_value.empty:
        df_matched = df_matched.merge(df_value, on="match_id", how="left")
    else:
        for col in ["p_btts","p_over15","p_over25","p_over35"]:
            df_matched[col] = np.nan
else:
    # still write empty bookmark with schema
    empty_cols = ["match_id","league","home_team","away_team","match_time","generated_at"]
    pd.DataFrame(columns=empty_cols).to_sql("bookmark", sqlite3.connect(DB_PATH), if_exists="replace", index=False)
    pd.DataFrame(columns=empty_cols).to_sql("bookmark", create_engine(DATABASE_URL), if_exists="replace", index=False)
    print("No matched rows — exiting")
    raise SystemExit(0)

# require at least one 1X2 probability
df_matched = df_matched.dropna(subset=["p_home","p_draw","p_away"], how="all")
if df_matched.empty:
    print("No matched rows with predictions — exiting")
    raise SystemExit(0)

# ---------- NORMALIZE PROBABILITIES ----------
df_matched["p_under25"] = 1.0 - df_matched.get("p_over25", 0.0)
df_matched["p_under15"] = 1.0 - df_matched.get("p_over15", 0.0)
df_matched["p_under35"] = 1.0 - df_matched.get("p_over35", 0.0)
df_matched["p_no_btts"] = 1.0 - df_matched.get("p_btts", 0.0)

# ---------- EV CALCULATION ----------
for col in ["home_odds","draw_odds","away_odds",
            "over05","under05","over15","under15",
            "over25","under25","over35","under35",
            "gg_odds","ng_odds"]:
    if col not in df_matched.columns:
        df_matched[col] = np.nan

df_matched["EV_home"] = df_matched["p_home"] * df_matched["home_odds"] - 1
df_matched["EV_draw"] = df_matched["p_draw"] * df_matched["draw_odds"] - 1
df_matched["EV_away"] = df_matched["p_away"] * df_matched["away_odds"] - 1

df_matched["EV_over05"] = df_matched["p_over05"] * df_matched["over05"] - 1
df_matched["EV_under05"] = (1 - df_matched["p_over05"]) * df_matched["under05"] - 1
df_matched["EV_over15"] = df_matched["p_over15"] * df_matched["over15"] - 1
df_matched["EV_under15"] = df_matched["p_under15"] * df_matched["under15"] - 1
df_matched["EV_over25"] = df_matched["p_over25"] * df_matched["over25"] - 1
df_matched["EV_under25"] = df_matched["p_under25"] * df_matched["under25"] - 1
df_matched["EV_over35"] = df_matched["p_over35"] * df_matched["over35"] - 1
df_matched["EV_under35"] = df_matched["p_under35"] * df_matched["under35"] - 1
df_matched["EV_btts_yes"] = df_matched["p_btts"] * df_matched["gg_odds"] - 1
df_matched["EV_btts_no"] = df_matched["p_no_btts"] * df_matched["ng_odds"] - 1

# ---------- BEST EV MARKET PER MATCH ----------
def best_ev_pick(row):
    evs = {
        "Home": row.get("EV_home", np.nan),
        "Draw": row.get("EV_draw", np.nan),
        "Away": row.get("EV_away", np.nan),
        "Over0.5": row.get("EV_over05", np.nan),
        "Under0.5": row.get("EV_under05", np.nan),
        "Over1.5": row.get("EV_over15", np.nan),
        "Under1.5": row.get("EV_under15", np.nan),
        "Over2.5": row.get("EV_over25", np.nan),
        "Under2.5": row.get("EV_under25", np.nan),
        "Over3.5": row.get("EV_over35", np.nan),
        "Under3.5": row.get("EV_under35", np.nan),
        "BTTS Yes": row.get("EV_btts_yes", np.nan),
        "BTTS No": row.get("EV_btts_no", np.nan),
    }
    filtered = {k:v for k,v in evs.items() if pd.notna(v)}
    if not filtered:
        return None, np.nan
    best = max(filtered, key=filtered.get)
    return best, filtered[best]

res = df_matched.apply(lambda r: pd.Series(best_ev_pick(r)), axis=1)
res.columns = ["Best_EV_Bet","EV"]
df_matched = pd.concat([df_matched.reset_index(drop=True), res.reset_index(drop=True)], axis=1)

# ---------- PICK ODDS & PROB ----------
def pick_odds_and_prob(row):
    choice = row.get("Best_EV_Bet")
    mapping = {
        "Home": ("home_odds","p_home"),
        "Draw": ("draw_odds","p_draw"),
        "Away": ("away_odds","p_away"),
        "Over0.5": ("over05","p_over05"),
        "Under0.5": ("under05","p_under05"),
        "Over1.5": ("over15","p_over15"),
        "Under1.5": ("under15","p_under15"),
        "Over2.5": ("over25","p_over25"),
        "Under2.5": ("under25","p_under25"),
        "Over3.5": ("over35","p_over35"),
        "Under3.5": ("under35","p_under35"),
        "BTTS Yes": ("gg_odds","p_btts"),
        "BTTS No": ("ng_odds","p_no_btts"),
    }
    odds_col, prob_col = mapping.get(choice, (None,None))
    if odds_col and prob_col:
        odds = row.get(odds_col, np.nan)
        prob = row.get(prob_col, np.nan)
        # special case Under0.5
        if choice == "Under0.5" and pd.notna(row.get("p_over05")):
            prob = 1 - row["p_over05"]
        return odds, prob
    return np.nan, np.nan

pick_res = df_matched.apply(lambda r: pd.Series(pick_odds_and_prob(r)), axis=1)
pick_res.columns = ["odds","prob"]
df_matched = pd.concat([df_matched.reset_index(drop=True), pick_res.reset_index(drop=True)], axis=1)

# ---------- KELLY & STAKES ----------
df_matched["kelly"] = df_matched.apply(lambda r: kelly_fraction(r["prob"], r["odds"]), axis=1)
df_matched["stake_pct"] = (df_matched["kelly"] * KELLY_FRACTION).clip(upper=MAX_STAKE_PCT)
df_matched["stake_amount"] = df_matched["stake_pct"] * BANKROLL
df_matched["generated_at"] = datetime.now(timezone.utc).isoformat()

# ---------- SAVE to DATABASES ----------
bookmark_cols = [
    "match_id","league","home_team","away_team","match_time",
    "home_odds","draw_odds","away_odds",
    "over05","under05","over15","under15","over25","under25","over35","under35",
    "gg_odds","ng_odds",
    "p_home","p_draw","p_away","p_over15","p_under15","p_over25","p_under25","p_over35","p_under35","p_btts","p_no_btts",
    "EV_home","EV_draw","EV_away","EV_over05","EV_under05","EV_over15","EV_under15","EV_over25","EV_under25","EV_over35","EV_under35","EV_btts_yes","EV_btts_no",
    "model_prediction","Best_EV_Bet","EV","odds","prob","kelly","stake_pct","stake_amount","generated_at"
]

bookmark_cols = [c for c in bookmark_cols if c in df_matched.columns]
df_final = df_matched[bookmark_cols].copy()

# SQLite
conn_sqlite = sqlite3.connect(DB_PATH)
try:
    conn_sqlite.execute("DELETE FROM bookmark")
except Exception:
    pass
df_final.to_sql("bookmark", conn_sqlite, if_exists="append", index=False)
conn_sqlite.commit()
conn_sqlite.close()

# PostgreSQL
engine = create_engine(DATABASE_URL, future=True)
with engine.begin() as conn:
    try:
        conn.execute("DELETE FROM bookmark")
    except Exception:
        pass
df_final.to_sql("bookmark", engine, if_exists="append", index=False)

print(f"✅ Bookmark saved successfully ({len(df_final)} rows) to SQLite and PostgreSQL")

# ---------- PRINT UNMATCHED ----------
if not df_unmatched.empty:
    print("\n❌ UNMATCHED LIVE_ODDS ROWS")
    print("="*80)
    for _, row in df_unmatched.iterrows():
        print(f"[{row.get('league')}] {row.get('home_team')} vs {row.get('away_team')} | {row.get('match_time')}")
        print(f"   norm → {row.get('home_norm')} vs {row.get('away_norm')}")
        print("-"*80)
else:
    print("\n✅ No unmatched live_odds rows 🎯")
