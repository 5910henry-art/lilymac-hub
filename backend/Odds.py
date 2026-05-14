#!/usr/bin/env python3
"""
Postgres odds ingestor for sportsbook backend
- H2H (1X2)
- Totals (Over/Under 0.5,1.5,2.5,3.5)
- Optional GG/NG (BTTS) per event
- Stores directly into Postgres live_odds table
"""

import requests
import re
import unicodedata
from datetime import datetime, timezone
from statistics import median
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import os
from sqlalchemy import create_engine, text

# ---------------- CONFIG ----------------
API_KEY = "4e55c0aac6d2e2ef1871c3bac439a4e1"
REGION = "eu"
ODDS_FORMAT = "decimal"
MAX_THREADS = 10

LEAGUES = {
    "soccer_epl": "Premier League",
    "soccer_spain_la_liga": "La Liga",
    "soccer_italy_serie_a": "Serie A",
    "soccer_germany_bundesliga": "Bundesliga",
    "soccer_france_ligue_one": "Ligue 1"
}

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://henry:kyu@localhost:5432/virtualfootball"
)

# ---------------- HELPERS ----------------
def is_valid_odd(x):
    return isinstance(x, (int, float)) and 1.05 <= x <= 50

def normalize_team(name: str):
    if not name:
        return ""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    name = re.sub(r'[^a-z0-9 ]', '', name)
    name = re.sub(r'\b(fc|cf|sc|afc)\b', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()

def normalize_kickoff(iso_time: str):
    dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00")).astimezone(timezone.utc)
    return dt.replace(second=0, microsecond=0)

# ---------------- FETCH ----------------
def fetch_odds(league_key, markets="h2h,totals"):
    url = f"https://api.the-odds-api.com/v4/sports/{league_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGION,
        "markets": markets,
        "oddsFormat": ODDS_FORMAT
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        remaining = r.headers.get("x-requests-remaining", "0")
        print(f"{league_key} → {r.status_code} | Remaining: {remaining}")
        if r.status_code == 200:
            return r.json(), int(remaining)
        print(f"API error {r.status_code} for league {league_key}")
        return [], int(remaining)
    except Exception as e:
        print("Request failed:", e)
        return [], 0

# ---------------- BTTS ----------------
def fetch_btts_for_event(league_key, event_id):
    url = f"https://api.the-odds-api.com/v4/sports/{league_key}/events/{event_id}/odds"
    try:
        r = requests.get(url, params={
            "apiKey": API_KEY,
            "regions": REGION,
            "markets": "btts",
            "oddsFormat": ODDS_FORMAT
        }, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"BTTS request failed for {event_id}: {e}")
    return None

def fetch_btts_odds(league_key, matches):
    results = {}
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(fetch_btts_for_event, league_key, m["id"]): m for m in matches}
        for future in as_completed(futures):
            data = future.result()
            if data:
                results[data["id"]] = data
    return results

# ---------------- UPSERT ----------------
def upsert_matches(matches, league, include_btts=False, btts_map=None):
    engine = create_engine(DATABASE_URL, future=True)
    inserted = 0
    fetched_at = datetime.now(timezone.utc)

    with engine.begin() as conn:
        for m in matches:
            home, away, kickoff, event_id = m.get("home_team"), m.get("away_team"), m.get("commence_time"), m.get("id")
            if not home or not away or not kickoff:
                continue

            home_norm, away_norm = normalize_team(home), normalize_team(away)
            match_time = normalize_kickoff(kickoff)

            h, d, a, gg, ng = [], [], [], [], []
            totals = {0.5: {"over": [], "under": []}, 1.5: {"over": [], "under": []},
                      2.5: {"over": [], "under": []}, 3.5: {"over": [], "under": []}}

            for book in m.get("bookmakers", []):
                for market in book.get("markets", []):
                    key = market.get("key")
                    if key == "h2h":
                        for o in market["outcomes"]:
                            p = o["price"]
                            if not is_valid_odd(p): continue
                            if o["name"] == home: h.append(p)
                            elif o["name"] == "Draw": d.append(p)
                            elif o["name"] == away: a.append(p)
                    elif key == "totals":
                        for o in market["outcomes"]:
                            p, point = o["price"], o.get("point")
                            if not is_valid_odd(p) or point not in totals: continue
                            if o["name"] == "Over": totals[point]["over"].append(p)
                            elif o["name"] == "Under": totals[point]["under"].append(p)

            if include_btts and btts_map and event_id in btts_map:
                for book in btts_map[event_id].get("bookmakers", []):
                    for market in book.get("markets", []):
                        if market.get("key") == "btts":
                            for o in market.get("outcomes", []):
                                p = o["price"]
                                if not is_valid_odd(p): continue
                                if o["name"] == "Yes": gg.append(p)
                                elif o["name"] == "No": ng.append(p)

            # Upsert into Postgres
            conn.execute(text("""
            INSERT INTO live_odds (
                league, home_team, away_team, home_team_norm, away_team_norm, match_time,
                home_odds, draw_odds, away_odds,
                over05, under05, over15, under15, over25, under25, over35, under35,
                gg_odds, ng_odds, fetched_at
            ) VALUES (
                :league, :home, :away, :home_norm, :away_norm, :match_time,
                :home_odds, :draw_odds, :away_odds,
                :over05, :under05, :over15, :under15, :over25, :under25, :over35, :under35,
                :gg_odds, :ng_odds, :fetched_at
            )
            ON CONFLICT (league, home_team_norm, away_team_norm, match_time)
            DO UPDATE SET
                home_odds=excluded.home_odds,
                draw_odds=excluded.draw_odds,
                away_odds=excluded.away_odds,
                over05=excluded.over05,
                under05=excluded.under05,
                over15=excluded.over15,
                under15=excluded.under15,
                over25=excluded.over25,
                under25=excluded.under25,
                over35=excluded.over35,
                under35=excluded.under35,
                gg_odds=excluded.gg_odds,
                ng_odds=excluded.ng_odds,
                fetched_at=excluded.fetched_at
            """), {
                "league": league,
                "home": home,
                "away": away,
                "home_norm": home_norm,
                "away_norm": away_norm,
                "match_time": match_time,
                "home_odds": median(h) if h else None,
                "draw_odds": median(d) if d else None,
                "away_odds": median(a) if a else None,
                "over05": median(totals[0.5]["over"]) if totals[0.5]["over"] else None,
                "under05": median(totals[0.5]["under"]) if totals[0.5]["under"] else None,
                "over15": median(totals[1.5]["over"]) if totals[1.5]["over"] else None,
                "under15": median(totals[1.5]["under"]) if totals[1.5]["under"] else None,
                "over25": median(totals[2.5]["over"]) if totals[2.5]["over"] else None,
                "under25": median(totals[2.5]["under"]) if totals[2.5]["under"] else None,
                "over35": median(totals[3.5]["over"]) if totals[3.5]["over"] else None,
                "under35": median(totals[3.5]["under"]) if totals[3.5]["under"] else None,
                "gg_odds": median(gg) if gg else None,
                "ng_odds": median(ng) if ng else None,
                "fetched_at": fetched_at
            })
            inserted += 1

    print(f"Stored {inserted} matches in Postgres")

# ---------------- MAIN ----------------
def main(include_btts=False):
    for key, league in LEAGUES.items():
        print(f"\nFetching {league} H2H + Totals")
        matches, remaining = fetch_odds(key)
        if remaining == 0:
            print(f"Quota exhausted. Skipping {league}...")
            continue

        btts_map = None
        if include_btts and matches:
            print(f"Fetching {league} GG/NG (BTTS per event)")
            btts_map = fetch_btts_odds(key, matches)

        if matches:
            upsert_matches(matches, league, include_btts=include_btts, btts_map=btts_map)

    print("\nOdds update finished")

# ---------------- ARGPARSE ----------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch football odds into Postgres")
    parser.add_argument("--btts", action="store_true", help="Include BTTS (GG/NG) odds")
    args = parser.parse_args()
    main(include_btts=args.btts)
