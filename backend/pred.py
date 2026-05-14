#!/usr/bin/env python3

import sqlite3
import json
import sys
from datetime import datetime, timezone
from collections import defaultdict, deque

import pandas as pd

# =========================
# CONFIG
# =========================
DB_PATH = "football.db"
MODEL_VERSION = "fer_v3_fast"
MAX_MATCHES_USED = 20
BAR_WIDTH = 30
TARGET_MATCH_ID = None
UTC = timezone.utc

# =========================
# Progress bar
# =========================
def progress_bar(current, total, prefix="Processing"):
    if total == 0:
        return
    pct = current / total
    filled = int(BAR_WIDTH * pct)
    bar = "█" * filled + "░" * (BAR_WIDTH - filled)
    sys.stdout.write(f"\r{prefix} [{bar}] {int(pct*100)}% ({current}/{total})")
    sys.stdout.flush()


# =========================
# DB & Load data
# =========================
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

matches = pd.read_sql("SELECT * FROM matches", conn)
matches["utcDate"] = pd.to_datetime(matches["utcDate"], errors="coerce", utc=True)

past = matches[matches["status"] == "FINISHED"].copy()
future = matches[matches["status"].isin(["TIMED", "SCHEDULED"])].copy()

past["result"] = past.apply(
    lambda r: "Home Win"
    if r["home_score"] > r["away_score"]
    else ("Draw" if r["home_score"] == r["away_score"] else "Away Win"),
    axis=1,
)

# =========================
# PRECOMPUTE (FAST)
# =========================
print("🧠 Precomputing team & H2H caches...")

team_home = defaultdict(list)
team_away = defaultdict(list)
h2h = defaultdict(list)

for r in past.itertuples(index=False):
    team_home[r.home_team_id].append(r)
    team_away[r.away_team_id].append(r)
    key = tuple(sorted((r.home_team_id, r.away_team_id)))
    h2h[key].append(r)

# Sort once
for d in (team_home, team_away, h2h):
    for k in d:
        d[k].sort(key=lambda x: x.utcDate)

print("✅ Caches ready\n")

# =========================
# FEATURE HELPERS (FAST)
# =========================
def last_n_before(rows, match_date, n):
    out = deque(maxlen=n)
    for r in rows:
        if r.utcDate < match_date:
            out.append(r)
    return out


def home_features(team_id, match_date):
    rows = team_home.get(team_id)
    if not rows:
        return dict.fromkeys(
            ["recent_wins_home", "recent_draws_home", "recent_losses_home",
             "avg_goals_for_home", "avg_goals_against_home"], 0
        )

    recent = last_n_before(rows, match_date, MAX_MATCHES_USED)
    if not recent:
        return dict.fromkeys(
            ["recent_wins_home", "recent_draws_home", "recent_losses_home",
             "avg_goals_for_home", "avg_goals_against_home"], 0
        )

    wins = sum(r.home_score > r.away_score for r in recent)
    draws = sum(r.home_score == r.away_score for r in recent)
    losses = len(recent) - wins - draws

    return {
        "recent_wins_home": wins,
        "recent_draws_home": draws,
        "recent_losses_home": losses,
        "avg_goals_for_home": sum(r.home_score for r in recent) / len(recent),
        "avg_goals_against_home": sum(r.away_score for r in recent) / len(recent),
    }


def away_features(team_id, match_date):
    rows = team_away.get(team_id)
    if not rows:
        return dict.fromkeys(
            ["recent_wins_away", "recent_draws_away", "recent_losses_away",
             "avg_goals_for_away", "avg_goals_against_away"], 0
        )

    recent = last_n_before(rows, match_date, MAX_MATCHES_USED)
    if not recent:
        return dict.fromkeys(
            ["recent_wins_away", "recent_draws_away", "recent_losses_away",
             "avg_goals_for_away", "avg_goals_against_away"], 0
        )

    wins = sum(r.away_score > r.home_score for r in recent)
    draws = sum(r.away_score == r.home_score for r in recent)
    losses = len(recent) - wins - draws

    return {
        "recent_wins_away": wins,
        "recent_draws_away": draws,
        "recent_losses_away": losses,
        "avg_goals_for_away": sum(r.away_score for r in recent) / len(recent),
        "avg_goals_against_away": sum(r.home_score for r in recent) / len(recent),
    }


def h2h_features(home_id, away_id, match_date):
    rows = h2h.get(tuple(sorted((home_id, away_id))))
    if not rows:
        return {"h2h_home_wins": 0, "h2h_away_wins": 0, "h2h_draws": 0, "h2h_avg_goals": 0}

    recent = last_n_before(rows, match_date, MAX_MATCHES_USED)
    if not recent:
        return {"h2h_home_wins": 0, "h2h_away_wins": 0, "h2h_draws": 0, "h2h_avg_goals": 0}

    hw = aw = dr = goals = 0
    for r in recent:
        goals += r.home_score + r.away_score
        if r.home_score == r.away_score:
            dr += 1
        elif r.home_team_id == home_id and r.home_score > r.away_score:
            hw += 1
        elif r.away_team_id == home_id and r.away_score > r.home_score:
            hw += 1
        else:
            aw += 1

    return {
        "h2h_home_wins": hw,
        "h2h_away_wins": aw,
        "h2h_draws": dr,
        "h2h_avg_goals": goals / (2 * len(recent)),
    }


# =========================
# MATCH SELECTION
# =========================
if TARGET_MATCH_ID:
    all_matches = matches[matches["id"] == TARGET_MATCH_ID]
else:
    all_matches = pd.concat([past, future], ignore_index=True)

# =========================
# FEATURE BUILD (FAST)
# =========================
rows = []
total = len(all_matches)
print(f"🏗️ Building features for {total} matches")

for i, r in enumerate(all_matches.itertuples(index=False), 1):
    md = r.utcDate.to_pydatetime().replace(tzinfo=UTC)

    feat = {
        "match_id": r.id,
        "home_team_id": r.home_team_id,
        "away_team_id": r.away_team_id,
        "home_team_name": r.home_team_name,
        "away_team_name": r.away_team_name,
        "competition": r.competition,
        "matchday": r.matchday,
        "season": r.season,
    }

    feat.update(home_features(r.home_team_id, md))
    feat.update(away_features(r.away_team_id, md))
    feat.update(h2h_features(r.home_team_id, r.away_team_id, md))

    if hasattr(r, "result"):
        feat["result"] = r.result

    rows.append(feat)

    if i % 10 == 0 or i == total:
        progress_bar(i, total, "🏗️ Features")

print("\n✅ Feature build complete")

features_df = pd.DataFrame(rows)

# =========================
# PREDICT & SAVE
# =========================
def predict(row):
    hs = (
        2*row.recent_wins_home + row.recent_draws_home - row.recent_losses_home +
        row.avg_goals_for_home - row.avg_goals_against_home +
        row.h2h_home_wins - row.h2h_away_wins + row.h2h_avg_goals
    )

    as_ = (
        2*row.recent_wins_away + row.recent_draws_away - row.recent_losses_away +
        row.avg_goals_for_away - row.avg_goals_against_away +
        row.h2h_away_wins - row.h2h_home_wins + row.h2h_avg_goals
    )

    ds = (row.recent_draws_home + row.recent_draws_away + row.h2h_draws) / MAX_MATCHES_USED

    hs, as_, ds = max(hs, 0), max(as_, 0), max(ds, 0)
    tot = hs + as_ + ds + 1e-6

    probs = {
        "Home Win": round(hs / tot, 3),
        "Draw": round(ds / tot, 3),
        "Away Win": round(as_ / tot, 3),
    }

    pred = max(probs, key=probs.get)
    return pred, probs, probs[pred]


for i, r in enumerate(features_df.itertuples(index=False), 1):
    pred, probs, conf = predict(r)

    payload = {
        "prediction": pred,
        "probabilities": probs,
        "confidence": conf,
        "model_version": MODEL_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    cursor.execute(
        """INSERT OR REPLACE INTO models
           (match_id, model_version, prediction_json, confidence, generated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (r.match_id, MODEL_VERSION, json.dumps(payload), conf, payload["generated_at"])
    )

    if i % 10 == 0 or i == total:
        progress_bar(i, total, "📊 Predicting")

conn.commit()
conn.close()

print("\n\n✅ Predictions saved")
