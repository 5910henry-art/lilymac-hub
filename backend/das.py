#!/usr/bin/env python3
"""
dashboard_full_volatility_color.py — recent performance + volatility of all models per league (color-coded)

- Computes accuracy over last RECENT_DAYS
- Computes volatility (standard deviation of correctness per match)
- Prints leaderboard per league with color-coded volatility
"""

import sqlite3
import json
import asyncio
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import math

from config import DB_FILE  # Make sure this points to your DB

# ==========================================================
# CONFIG
# ==========================================================
UTC = timezone.utc
RECENT_DAYS = 60
MIN_MATCHES = 1  # Include all models with at least 1 match
_CACHE_TTL_MINUTES = 10

# Cache
_dashboard_cache = {}
_cache_timestamp = None
_cache_lock = asyncio.Lock()

# ANSI color codes
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"

def _now():
    return datetime.now(UTC)

def color_volatility(vol):
    """
    Returns colored string based on volatility:
    Green: low, Yellow: medium, Red: high
    """
    if vol < 0.15:
        color = COLOR_GREEN
    elif vol < 0.35:
        color = COLOR_YELLOW
    else:
        color = COLOR_RED
    return f"{color}{vol:.4f}{COLOR_RESET}"

# ==========================================================
# CORE DASHBOARD COMPUTATION
# ==========================================================
async def get_full_dashboard(force_refresh=False):
    """
    Returns recent performance of all models per league as dict:
    { league_name: [ {model_version, correct, total, accuracy, volatility}, ... ] }
    Volatility = standard deviation of correctness per match (0=stable, 1=all wrong/right alternating)
    """
    global _dashboard_cache, _cache_timestamp

    async with _cache_lock:
        now = _now()
        if _dashboard_cache and _cache_timestamp and not force_refresh:
            if now - _cache_timestamp < timedelta(minutes=_CACHE_TTL_MINUTES):
                return _dashboard_cache

        try:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute(f"""
                SELECT id, competition, home_score, away_score, utcDate
                FROM matches
                WHERE status='FINISHED'
                  AND utcDate >= datetime('now', '-{RECENT_DAYS} days')
            """)
            recent_matches = cur.fetchall()
            if not recent_matches:
                conn.close()
                _dashboard_cache = {}
                _cache_timestamp = now
                return {}

            # Store results per match for volatility calculation
            perf = defaultdict(lambda: defaultdict(lambda: {"correct":0,"total":0,"results":[]}))

            for match in recent_matches:
                match_id = match["id"]
                league = match["competition"] or "_global"
                home_score = match["home_score"]
                away_score = match["away_score"]

                if home_score is None or away_score is None:
                    continue

                if home_score > away_score:
                    actual = "Home Win"
                elif home_score < away_score:
                    actual = "Away Win"
                else:
                    actual = "Draw"

                cur.execute("SELECT model_version, prediction_json FROM models WHERE match_id = ?", (match_id,))
                for r in cur.fetchall():
                    version = r["model_version"]
                    try:
                        pjson = json.loads(r["prediction_json"])
                        probs = pjson.get("probabilities", {})
                        label_scores = {
                            "Home Win": float(probs.get("home_win",0)),
                            "Draw": float(probs.get("draw",0)),
                            "Away Win": float(probs.get("away_win",0)),
                        }
                        predicted = max(label_scores, key=lambda k: label_scores[k])
                    except Exception:
                        predicted = "Draw"

                    correct_flag = 1 if predicted == actual else 0
                    perf[league][version]["total"] += 1
                    perf[league][version]["correct"] += correct_flag
                    perf[league][version]["results"].append(correct_flag)

            # Build dashboard: include all models per league
            dashboard = {}
            for league, models in perf.items():
                model_list = []
                for version, stats in models.items():
                    if stats["total"] < MIN_MATCHES:
                        continue
                    accuracy = stats["correct"] / stats["total"] if stats["total"] else 0.0
                    results = stats["results"]
                    if results:
                        mean = accuracy
                        variance = sum((r - mean)**2 for r in results) / len(results)
                        volatility = math.sqrt(variance)
                    else:
                        volatility = 0.0
                    model_list.append({
                        "model_version": version,
                        "correct": stats["correct"],
                        "total": stats["total"],
                        "accuracy": round(accuracy,4),
                        "volatility": round(volatility,4)
                    })
                # Sort descending by accuracy
                model_list.sort(key=lambda x: x["accuracy"], reverse=True)
                if model_list:
                    dashboard[league] = model_list

            conn.close()
            _dashboard_cache = dashboard
            _cache_timestamp = now
            return dashboard

        except Exception as e:
            print(f"⚠️ dashboard computation failed: {e}")
            return {}

# ==========================================================
# PRINTING FUNCTION WITH COLORS
# ==========================================================
async def print_dashboard(force_refresh=False):
    """
    Prints all leagues and models in leaderboard format with color-coded volatility
    """
    dashboard = await get_full_dashboard(force_refresh=force_refresh)
    if not dashboard:
        print("No recent matches found.")
        return

    for league, models in dashboard.items():
        print(f"\n=== {league} ===")
        print(f"{'Model':<10} | {'Correct':<7} | {'Total':<5} | {'Accuracy':<8} | {'Volatility':<9}")
        print("-"*55)
        for m in models:
            vol_colored = color_volatility(m['volatility'])
            print(f"{m['model_version']:<10} | {m['correct']:<7} | {m['total']:<5} | {m['accuracy']:<8.4f} | {vol_colored:<9}")

# ==========================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    asyncio.run(print_dashboard())
