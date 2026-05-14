#!/usr/bin/env python3
"""
Goals.py (v23.3 – PostgreSQL stable)
Fixes:
✅ timezone safe
✅ no injuries table crash
✅ odds use team names (not IDs)
✅ fixed indentation
"""

from collections import Counter
from datetime import datetime
import time
import numpy as np

from config2 import query_db, execute_db, UTC

# ---------------- CONFIG ----------------
H2H_N = 10
DECAY = 0.9
HOME_ADV_BASE = 1.2
MC_SIMS = 10000
ODDS_SIGNAL_WEIGHT = 0.15
OVER_LINES = [1.5, 2.5, 3.5, 4.5]

# ---------------- TIME ----------------
def to_db_time(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=None)

def now_db():
    return datetime.now(UTC).replace(tzinfo=None)
# ---------------- H2H ----------------
async def compute_h2h_score(home_id, away_id, match_utc, last_n=H2H_N):
    match_dt = to_db_time(match_utc)

    rows = await query_db("""
        SELECT home_team_id, away_team_id, home_score, away_score
        FROM henry_schema.h2h
        WHERE ((home_team_id=$1 AND away_team_id=$2)
            OR (home_team_id=$2 AND away_team_id=$1))
          AND date_played < $3
        ORDER BY date_played DESC
        LIMIT $4
    """, (home_id, away_id, match_dt, last_n))

    if not rows:
        return 0.8, 0.8, 0

    wh = wa = tw = 0.0
    used = 0

    for i, r in enumerate(rows):
        if r["home_score"] is None or r["away_score"] is None:
            continue

        w = DECAY ** i

        if r["home_team_id"] == home_id:
            w *= HOME_ADV_BASE
            hg, ag = r["home_score"], r["away_score"]
        else:
            hg, ag = r["away_score"], r["home_score"]

        wh += hg * w
        wa += ag * w
        tw += w
        used += 1

    return wh / tw, wa / tw, used

# ---------------- STANDINGS ----------------
async def get_standings(team_id, match_utc, season, league):
    match_dt = to_db_time(match_utc)

    rows = await query_db("""
        SELECT goal_diff
        FROM henry_schema.standings
        WHERE team_id=$1 AND season=$2 AND league_code=$3
          AND last_updated < $4
        ORDER BY last_updated DESC
        LIMIT 1
    """, (team_id, season, league, match_dt))

    return rows[0] if rows else None

# ---------------- FORM ----------------
async def get_form(match_id):
    rows = await query_db("""
        SELECT home_form, away_form
        FROM henry_schema.features
        WHERE match_id=$1
    """, (match_id,))

    if not rows:
        return 1.0, 1.0

    row = rows[0]
    return 1 + (row["home_form"] or 0) / 10, 1 + (row["away_form"] or 0) / 10

# ---------------- INJURY (DISABLED SAFE) ----------------
async def get_injury_factor(team_id, match_utc):
    # Table doesn't exist → safe fallback
    return 1.0

# ---------------- MONTE CARLO ----------------
async def monte_carlo(home_goals, away_goals):
    res = {
        "home": 0, "draw": 0, "away": 0,
        "btts": 0,
        "over": {l: 0 for l in OVER_LINES},
        "scores": Counter()
    }

    for _ in range(MC_SIMS):
        h = np.random.poisson(home_goals)
        a = np.random.poisson(away_goals)

        if h > a:
            res["home"] += 1
        elif h == a:
            res["draw"] += 1
        else:
            res["away"] += 1

        if h > 0 and a > 0:
            res["btts"] += 1

        for l in OVER_LINES:
            if h + a > l:
                res["over"][l] += 1

        res["scores"][(h, a)] += 1

    probs = {
        "home": res["home"] / MC_SIMS,
        "draw": res["draw"] / MC_SIMS,
        "away": res["away"] / MC_SIMS,
        "btts": res["btts"] / MC_SIMS,
    }

    for l in OVER_LINES:
        probs[f"over_{str(l).replace('.', '_')}"] = res["over"][l] / MC_SIMS

    probs["score"] = max(res["scores"], key=res["scores"].get)

    return probs

# ---------------- ODDS ----------------
def normalize_odds(row):
    inv = {}
    for k in ("home_odds", "draw_odds", "away_odds"):
        v = row.get(k)
        if v:
            inv[k] = 1 / float(v)

    s = sum(inv.values())
    if not s:
        return {}

    return {
        "home": inv.get("home_odds", 0) / s,
        "draw": inv.get("draw_odds", 0) / s,
        "away": inv.get("away_odds", 0) / s,
    }

def blend_odds(probs, odds_row):
    if not odds_row:
        return probs

    norm = normalize_odds(odds_row)

    for k in ("home", "draw", "away"):
        if k in norm:
            probs[k] = (1 - ODDS_SIGNAL_WEIGHT) * probs[k] + ODDS_SIGNAL_WEIGHT * norm[k]

    return probs

# ---------------- MAIN ----------------
async def predict_all():
    start_time = time.time()

    matches = await query_db("""
        SELECT *
        FROM henry_schema.matches
        WHERE status IN ('SCHEDULED','TIMED')
        ORDER BY utcdate ASC
    """)

    print(f"⚽ Processing {len(matches)} matches...")

    for m in matches:
        # --- FIX datetime ---
        utc_val = m["utcdate"]

        if isinstance(utc_val, str):
            match_utc = datetime.fromisoformat(utc_val.replace("Z", "+00:00"))
        else:
            match_utc = utc_val

        if match_utc.tzinfo is None:
            match_utc = match_utc.replace(tzinfo=UTC)

        # --- CORE ---
        hg, ag, used = await compute_h2h_score(
            m["home_team_id"], m["away_team_id"], match_utc
        )

        hs = await get_standings(m["home_team_id"], match_utc, m["season"], m["competition"])
        as_ = await get_standings(m["away_team_id"], match_utc, m["season"], m["competition"])

        if hs and as_:
            diff = hs["goal_diff"] - as_["goal_diff"]
            hg *= max(0.7, 1 + diff / 100)
            ag *= max(0.7, 1 - diff / 100)

        hf, af = await get_form(m["id"])
        hg *= hf
        ag *= af

        probs = await monte_carlo(hg, ag)

        # --- FIX ODDS (use names, not IDs) ---
        odds_rows = await query_db("""
            SELECT home_odds, draw_odds, away_odds
            FROM henry_schema.live_odds
            WHERE home_team=$1 AND away_team=$2
            LIMIT 1
        """, (m["home_team_name"], m["away_team_name"]))

        odds = odds_rows[0] if odds_rows else None
        probs = blend_odds(probs, odds)

        conf_score = round(max(probs["home"], probs["draw"], probs["away"]), 2)

        await execute_db("""
            INSERT INTO henry_schema.value VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19
            )
            ON CONFLICT (match_id) DO UPDATE SET
                conf_score = EXCLUDED.conf_score,
                generated_at = EXCLUDED.generated_at
        """, (
            m["id"],
            m["home_team_id"],
            m["away_team_id"],
            round(hg, 2),
            round(ag, 2),
            f"{probs['score'][0]}-{probs['score'][1]}",
            used,
            conf_score,
            round(probs["btts"], 2),
            round(probs["over_1_5"], 2),
            round(probs["over_2_5"], 2),
            round(probs["over_3_5"], 2),
            round(probs["over_4_5"], 2),
            probs["over_1_5"] > 0.5,
            probs["over_2_5"] > 0.5,
            probs["over_3_5"] > 0.5,
            probs["over_4_5"] > 0.5,
            probs["btts"] > 0.5,
            now_db()
        ))

    print(f"✅ Done in {time.time() - start_time:.2f}s")

# ---------------- ENTRY ----------------
if __name__ == "__main__":
    import asyncio
    print("🚀 Running PostgreSQL predictor (v23.3)...")
    asyncio.run(predict_all())
