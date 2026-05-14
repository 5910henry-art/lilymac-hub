#!/usr/bin/env python3
"""
combined_pred_goals.py
Combines the fast pred.py pipeline (features + model predictions) with the
goals.py Monte Carlo / value-table logic and odds blending — synchronous version.
- Uses sqlite3, pandas, numpy                                   - Termux-friendly, production-safe guards
"""
import sqlite3
import json
import sys
import time
import unicodedata
import re
from datetime import datetime, timezone
from collections import Counter, defaultdict, deque
from typing import Any, Dict, Iterable, Tuple

import pandas as pd
import numpy as np

# ============= CONFIG =============
DB_PATH = "football.db"
MODEL_VERSION = "fer_v3_combined"
MAX_MATCHES_USED = 20
BAR_WIDTH = 30
TARGET_MATCH_ID = None
UTC = timezone.utc

# Monte Carlo / goals config (from goals.py)
H2H_N = 10
DECAY = 0.9
HOME_ADV_BASE = 1.2
MC_SIMS = 10000            # reduce to 2000 while testing if too slow
ODDS_SIGNAL_WEIGHT = 0.15
OVER_LINES = [1.5, 2.5, 3.5, 4.5]


# ============= Utilities & progress =============
def progress_bar(current: int, total: int, prefix: str = "Processing"):
    if total == 0:
        return
    pct = current / total
    filled = int(BAR_WIDTH * pct)
    bar = "█" * filled + "░" * (BAR_WIDTH - filled)
    sys.stdout.write(f"\r{prefix} [{bar}] {int(pct*100)}% ({current}/{total})")
    sys.stdout.flush()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ============= simple team normalization helper ============
def normalize_team(name: str) -> str:
    """Normalize team names to a simple ascii lowercase form used in live_odds.home_team_norm"""
    if not isinstance(name, str):
        return ""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    name = re.sub(r"\b(fc|cf|ac|sc|afc|rc|sk|ud|club)\b", "", name)
    name = re.sub(r"\d{4}", "", name)
    name = re.sub(r"[^a-z ]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


# ============= DB helpers (sync) =============
def query_db(conn: sqlite3.Connection, query: str, args: Iterable[Any] = (), one: bool = False):
    cur = conn.execute(query, args)
    rows = cur.fetchall()
    if one:
        return rows[0] if rows else None
    return rows


def execute_db(conn: sqlite3.Connection, query: str, args: Iterable[Any] = ()):
    conn.execute(query, args)
    conn.commit()


# ============= Load matches & build caches (fast pred style) =============
def build_caches(conn: sqlite3.Connection):
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

    # caches: lists of namedtuples (itertuples) sorted by utcDate asc (older -> newer)
    team_home = defaultdict(list)
    team_away = defaultdict(list)
    h2h = defaultdict(list)

    for r in past.itertuples(index=False):
        # r has attributes: id, utcDate, home_team_id, away_team_id, home_score, away_score, ...
        team_home[r.home_team_id].append(r)
        team_away[r.away_team_id].append(r)
        key = tuple(sorted((r.home_team_id, r.away_team_id)))
        h2h[key].append(r)

    # ensure sorted by utcDate ascending
    for d in (team_home, team_away, h2h):
        for k in d:
            d[k].sort(key=lambda x: x.utcDate)

    all_matches = pd.concat([past, future], ignore_index=True)
    if TARGET_MATCH_ID:
        target = all_matches[all_matches["id"] == TARGET_MATCH_ID]
        all_matches = target

    return matches, past, future, team_home, team_away, h2h, all_matches


# ============= fast feature helpers (sync) =============
def last_n_before_rows(rows, match_dt: datetime, n: int):
    """Return deque of up to n rows with utcDate < match_dt (keeps most recent last)"""
    out = deque(maxlen=n)
    for r in rows:
        # r.utcDate is a pandas Timestamp or datetime with tzinfo
        if r.utcDate is not None and r.utcDate.to_pydatetime() < match_dt:
            out.append(r)
    return out


def home_features_sync(team_home, team_id, match_dt):
    rows = team_home.get(team_id)
    if not rows:
        return {
            "recent_wins_home": 0,
            "recent_draws_home": 0,
            "recent_losses_home": 0,
            "avg_goals_for_home": 0.0,
            "avg_goals_against_home": 0.0,
        }

    recent = last_n_before_rows(rows, match_dt, MAX_MATCHES_USED)
    if not recent:
        return {
            "recent_wins_home": 0,
            "recent_draws_home": 0,
            "recent_losses_home": 0,
            "avg_goals_for_home": 0.0,
            "avg_goals_against_home": 0.0,
        }

    wins = sum(r.home_score > r.away_score for r in recent)
    draws = sum(r.home_score == r.away_score for r in recent)
    losses = len(recent) - wins - draws

    return {
        "recent_wins_home": int(wins),
        "recent_draws_home": int(draws),
        "recent_losses_home": int(losses),
        "avg_goals_for_home": float(sum(r.home_score for r in recent) / len(recent)),
        "avg_goals_against_home": float(sum(r.away_score for r in recent) / len(recent)),
    }


def away_features_sync(team_away, team_id, match_dt):
    rows = team_away.get(team_id)
    if not rows:
        return {
            "recent_wins_away": 0,
            "recent_draws_away": 0,
            "recent_losses_away": 0,
            "avg_goals_for_away": 0.0,
            "avg_goals_against_away": 0.0,
        }

    recent = last_n_before_rows(rows, match_dt, MAX_MATCHES_USED)
    if not recent:
        return {
            "recent_wins_away": 0,
            "recent_draws_away": 0,
            "recent_losses_away": 0,
            "avg_goals_for_away": 0.0,
            "avg_goals_against_away": 0.0,
        }

    wins = sum(r.away_score > r.home_score for r in recent)
    draws = sum(r.away_score == r.home_score for r in recent)
    losses = len(recent) - wins - draws

    return {
        "recent_wins_away": int(wins),
        "recent_draws_away": int(draws),
        "recent_losses_away": int(losses),
        "avg_goals_for_away": float(sum(r.away_score for r in recent) / len(recent)),
        "avg_goals_against_away": float(sum(r.home_score for r in recent) / len(recent)),
    }


# ============= H2H / goals estimate (sync) =============
def compute_h2h_score_sync(h2h_cache, home_id, away_id, match_dt: datetime, match_id, last_n=H2H_N) -> Tuple[float, float, int]:
    key = tuple(sorted((home_id, away_id)))
    rows = h2h_cache.get(key, [])
    if not rows:
        return 0.8, 0.8, 0

    # collect recent matches BEFORE match_dt and exclude same match_id
    recent = []
    for r in reversed(rows):  # rows are ascending; reversed gives newest first
        if r.id == match_id:
            continue
        if r.utcDate is None:
            continue
        if r.utcDate.to_pydatetime() < match_dt:
            recent.append(r)
            if len(recent) >= last_n:
                break

    if not recent:
        return 0.8, 0.8, 0

    wh = wa = tw = 0.0
    used = 0
    for i, r in enumerate(recent):
        # decay with i (0 is newest)
        w = (DECAY ** i)
        if r.home_team_id == home_id:
            w *= HOME_ADV_BASE
            hg, ag = r.home_score, r.away_score
        else:
            # home_id was away in that past match
            hg, ag = r.away_score, r.home_score

        if hg is None or ag is None:
            continue

        wh += hg * w
        wa += ag * w
        tw += w
        used += 1

    if tw == 0 or used == 0:
        return 0.8, 0.8, 0

    return wh / tw, wa / tw, used


# ============= Standings / form / injuries (sync) =============
def get_standings_sync(conn: sqlite3.Connection, team_id, match_dt: datetime, season, league):
    match_str = match_dt.isoformat()
    row = query_db(conn, """
        SELECT goal_diff
        FROM standings
        WHERE team_id=? AND season=? AND league_code=?
          AND last_updated < ?
        ORDER BY last_updated DESC
        LIMIT 1
    """, (team_id, season, league, match_str), one=True)
    return row


def get_form_sync(conn: sqlite3.Connection, match_id):
    """
    Fetch home and away form for a given match_id from features table.
    Returns multipliers for expected goals (1 + form/10).
    Works with sqlite3.Row or tuple rows safely.
    """
    row = query_db(conn, """
        SELECT home_form, away_form
        FROM features
        WHERE match_id=?
    """, (match_id,), one=True)

    if not row:
        return 1.0, 1.0

    # convert row to dict safely
    if isinstance(row, tuple):
        hf = float(row[0] or 0)
        af = float(row[1] or 0)
    else:
        # sqlite3.Row supports keys()
        row_dict = dict(row)
        hf = float(row_dict.get("home_form", 0) or 0)
        af = float(row_dict.get("away_form", 0) or 0)

    return 1 + hf / 10.0, 1 + af / 10.0

def get_injury_factor_sync(conn: sqlite3.Connection, team_id, match_dt: datetime):
    """
    Compute the injury adjustment factor for a team at a given match date.
    Returns a multiplier between 0.6 and 1.0.
    Works safely with sqlite3.Row or tuple rows.
    """
    match_str = match_dt.isoformat()
    row = query_db(conn, """
        SELECT SUM(impact_factor) AS impact
        FROM injuries
        WHERE team_id=? AND start_date<=? AND end_date>=?
    """, (team_id, match_str, match_str), one=True)

    impact = 0.0
    if row:
        try:
            if isinstance(row, tuple):
                impact = float(row[0] or 0.0)
            else:
                row_dict = dict(row)
                impact = float(row_dict.get("impact", 0.0) or 0.0)
        except Exception:
            impact = 0.0

    return max(0.6, 1.0 - impact)
# ============= Monte Carlo (sync) =============
def monte_carlo_sync(home_goals: float, away_goals: float, sims: int = MC_SIMS) -> Dict[str, Any]:
    res = {
        "home": 0, "draw": 0, "away": 0,
        "btts": 0,
        "over": {l: 0 for l in OVER_LINES},
        "scores": Counter()
    }

    # looped Poisson sims for memory-safety on Termux
    for _ in range(sims):
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
        "home": res["home"] / sims,
        "draw": res["draw"] / sims,
        "away": res["away"] / sims,
        "btts": res["btts"] / sims,
    }

    for l in OVER_LINES:
        probs[f"over_{str(l).replace('.', '_')}"] = res["over"][l] / sims

    probs["score"] = max(res["scores"], key=res["scores"].get) if res["scores"] else (0, 0)
    return probs


# ============= Odds normalize & blend =============
def _is_number(x) -> bool:
    try:
        float(x)
        return True
    except Exception:
        return False


def _extract_three_odds_from_row_sync(row) -> Dict[str, float]:
    if not row:
        return {}
    # row from sqlite3 is a tuple by default; fetch column names by cursor.description isn't available here easily,
    # so try mapping by common indices if a dict-like is returned; fallback: try to treat as mapping
    try:
        # sqlite3.Row supports mapping interface
        d = dict(row)
    except Exception:
        # if row is tuple, we must attempt to locate columns (common schema unpredictable)
        # best-effort: look for 3 numeric values at positions and map to home/draw/away
        if isinstance(row, tuple):
            nums = [x for x in row if _is_number(x)]
            if len(nums) >= 3:
                return {"home": float(nums[0]), "draw": float(nums[1]), "away": float(nums[2])}
            return {}
        return {}

    # common name groups
    candidates = [
        ("odds_home", "odds_draw", "odds_away"),
        ("home", "draw", "away"),
        ("h", "d", "a"),
        ("home_odds", "draw_odds", "away_odds"),
        ("home_price", "draw_price", "away_price"),
        ("price_home", "price_draw", "price_away"),
    ]

    for names in candidates:
        mapped = {}
        for out_key, in_key in zip(("home", "draw", "away"), names):
            if in_key in d and d[in_key] is not None:
                try:
                    mapped[out_key] = float(d[in_key])
                except Exception:
                    pass
        if len(mapped) == 3:
            return mapped

    # last resort, pattern matching keys
    possible = {}
    for k, v in d.items():
        lk = str(k).lower()
        if ("home" in lk or lk.endswith("_h")) and _is_number(v):
            possible["home"] = float(v)
        if ("away" in lk or lk.endswith("_a")) and _is_number(v):
            possible["away"] = float(v)
        if ("draw" in lk or "x" == lk or lk.endswith("_d")) and _is_number(v):
            possible["draw"] = float(v)
    if len(possible) == 3:
        return possible

    return {}


def normalize_odds_map_sync(odds_map: Dict[str, float]) -> Dict[str, float]:
    inv = {}
    for k, v in odds_map.items():
        try:
            if v and float(v) > 0:
                inv[k] = 1.0 / float(v)
        except Exception:
            pass
    s = sum(inv.values())
    if s <= 0:
        return {}
    return {k: inv[k] / s for k in inv}


def blend_odds_sync(probs: Dict[str, Any], odds_row) -> Dict[str, Any]:
    if not odds_row:
        return probs
    odds_map = _extract_three_odds_from_row_sync(odds_row)
    if not odds_map:
        return probs
    norm = normalize_odds_map_sync(odds_map)
    if not norm:
        return probs
    blended = {}
    for k in ("home", "draw", "away"):
        mc_val = float(probs.get(k, 0.0))
        odds_val = norm.get(k, mc_val)
        blended[k] = (1 - ODDS_SIGNAL_WEIGHT) * mc_val + ODDS_SIGNAL_WEIGHT * odds_val
    s = sum(blended.values()) or 1.0
    for k in blended:
        blended[k] = blended[k] / s
    out = dict(probs)
    out.update(blended)
    return out


# ============= Main combined run =============
def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # allow mapping access for fetched rows when desired

    matches_df, past, future, team_home, team_away, h2h_cache, all_matches = build_caches(conn)

    total = len(all_matches)
    print(f"🏗️ Building features & predicting for {total} matches")

    rows = []
    # Build features (fast)
    for i, r in enumerate(all_matches.itertuples(index=False), start=1):
        # some utcDate may be NaT
        if r.utcDate is None:
            match_dt = datetime.now(UTC)
        else:
            match_dt = r.utcDate.to_pydatetime().replace(tzinfo=UTC)

        feat = {
            "match_id": r.id,
            "home_team_id": r.home_team_id,
            "away_team_id": r.away_team_id,
            "home_team_name": getattr(r, "home_team_name", None),
            "away_team_name": getattr(r, "away_team_name", None),
            "competition": getattr(r, "competition", None),
            "matchday": getattr(r, "matchday", None),
            "season": getattr(r, "season", None),
        }

        feat.update(home_features_sync(team_home, r.home_team_id, match_dt))
        feat.update(away_features_sync(team_away, r.away_team_id, match_dt))

        # H2H summary used for the simple model prediction
        hg_h2h, ag_h2h, used_h2h = compute_h2h_score_sync(h2h_cache, r.home_team_id, r.away_team_id, match_dt, r.id)
        feat.update({
            "h2h_home_wins": 0, "h2h_away_wins": 0, "h2h_draws": 0, "h2h_avg_goals": (hg_h2h + ag_h2h) / 2.0
        })
        # Note: we keep only an h2h_avg_goals numeric to feed into the heuristic model.

        rows.append(feat)
        if i % 10 == 0 or i == total:
            progress_bar(i, total, prefix="🏗️ Features")

    print("\n✅ Feature build complete\n")
    features_df = pd.DataFrame(rows)

    # =========================
    # Heuristic model predictions (original pred logic)
    # =========================
    def predict_match_row(row):
        home_score = (
            2 * row["recent_wins_home"]
            + row["recent_draws_home"]
            - row["recent_losses_home"]
            + row["avg_goals_for_home"]
            - row["avg_goals_against_home"]
            + row["h2h_home_wins"]
            - row["h2h_away_wins"]
            + row["h2h_avg_goals"]
        )

        away_score = (
            2 * row["recent_wins_away"]
            + row["recent_draws_away"]
            - row["recent_losses_away"]
            + row["avg_goals_for_away"]
            - row["avg_goals_against_away"]
            + row["h2h_away_wins"]
            - row["h2h_home_wins"]
            + row["h2h_avg_goals"]
        )

        draw_score = (
            row["recent_draws_home"]
            + row["recent_draws_away"]
            + row["h2h_draws"]
        ) / max(1, MAX_MATCHES_USED)

        home_score = max(home_score, 0)
        away_score = max(away_score, 0)
        draw_score = max(draw_score, 0)

        total = home_score + draw_score + away_score + 1e-6

        probs = {
            "home_win": round(home_score / total, 3),
            "draw": round(draw_score / total, 3),
            "away_win": round(away_score / total, 3),
        }

        predicted_result = max(probs, key=lambda k: probs[k])

        pred_text_map = {
            "home_win": "Home Win",
            "draw": "Draw",
            "away_win": "Away Win",
        }

        predicted_result_text = pred_text_map[predicted_result]
        confidence = probs[predicted_result]

        predicted_goals = {
            "home": min(round(home_score / 2), 5),
            "away": min(round(away_score / 2), 5),
        }

        return predicted_result_text, probs, confidence, predicted_goals

    # Save models and compute values (Monte Carlo + odds) per match
    total_rows = len(features_df)
    print(f"📊 Predicting & Monte Carlo value for {total_rows} matches")
    for i, r in enumerate(features_df.itertuples(index=False), start=1):
        # heuristic model prediction (saved to models)
        pred_text, probs_model, conf, goals_pred = predict_match_row(r._asdict())
        payload = {
            "prediction": pred_text,
            "probabilities": probs_model,
            "predicted_goals": goals_pred,
            "confidence": conf,
            "model_version": MODEL_VERSION,
            "matches_used": MAX_MATCHES_USED,
            "generated_at": now_iso(),
            "extra": {"GG": 0.0, "Over_2.5": 0.0},
        }

        # INSERT OR REPLACE into models
        execute_db(conn,
            """
            INSERT OR REPLACE INTO models
            (match_id, model_version, prediction_json, confidence, generated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (r.match_id, MODEL_VERSION, json.dumps(payload), conf, payload["generated_at"])
        )

        # =========================
        # Now compute goals/values (Monte Carlo-like) using cached H2H + standings + form + injuries + odds
        # Note: we re-compute a more direct expected home/away goals using compute_h2h_score_sync and team features
        match_row = query_db(conn, "SELECT * FROM matches WHERE id=?", (r.match_id,), one=True)
        utc = r._asdict().get("utcDate")
        if isinstance(utc, pd.Timestamp):
            match_dt = utc.to_pydatetime().replace(tzinfo=UTC)
        else:
            # fallback: try to parse from DB row
            try:
                match_dt = datetime.fromisoformat(match_row["utcDate"].replace("Z", "+00:00"))
            except Exception:
                match_dt = datetime.now(UTC)

        # base H2H expected goals
        hg_h2h, ag_h2h, used_h2h = compute_h2h_score_sync(h2h_cache, r.home_team_id, r.away_team_id, match_dt, r.match_id)

        # incorporate team recent goals to form an initial baseline
        # compute avg goals for recent home/away (use previous home/away caches)
        home_recent = last_n_before_rows(team_home.get(r.home_team_id, []), match_dt, MAX_MATCHES_USED)
        away_recent = last_n_before_rows(team_away.get(r.away_team_id, []), match_dt, MAX_MATCHES_USED)
        avg_home_scored = float(sum(x.home_score for x in home_recent) / len(home_recent)) if home_recent else hg_h2h
        avg_away_scored = float(sum(x.away_score for x in away_recent) / len(away_recent)) if away_recent else ag_h2h

        # combine h2h baseline and team baseline (simple average, you can tune weights)
        base_hg = (hg_h2h + avg_home_scored) / 2.0
        base_ag = (ag_h2h + avg_away_scored) / 2.0

        # standings adjustment
        hs = get_standings_sync(conn, r.home_team_id, match_dt, r.season, r.competition)
        as_ = get_standings_sync(conn, r.away_team_id, match_dt, r.season, r.competition)
        if hs and as_:
            try:
                # hs & as_ may be sqlite3.Row or tuple
                hd = hs["goal_diff"] if "goal_diff" in hs.keys() else hs[0]
                ad = as_["goal_diff"] if "goal_diff" in as_.keys() else as_[0]
                diff = float(hd) - float(ad)
                base_hg *= max(0.7, 1 + diff / 100.0)
                base_ag *= max(0.7, 1 - diff / 100.0)
            except Exception:
                pass

        # form & injuries
        hf, af = get_form_sync(conn, r.match_id)
        base_hg *= hf * get_injury_factor_sync(conn, r.home_team_id, match_dt)
        base_ag *= af * get_injury_factor_sync(conn, r.away_team_id, match_dt)

        # Monte Carlo sims
        probs_mc = monte_carlo_sync(base_hg, base_ag)

        # -------------------------
        # odds for this fixture (use normalized team names first, with fallbacks)
        # -------------------------
        home_norm = normalize_team(r.home_team_name or "")
        away_norm = normalize_team(r.away_team_name or "")

        odds_row = query_db(conn, """
            SELECT *
            FROM live_odds
            WHERE home_team_norm = ? AND away_team_norm = ?
            LIMIT 1
        """, (home_norm, away_norm), one=True)

        # fallback: exact raw name match if normalized lookup failed
        if not odds_row:
            odds_row = query_db(conn, """
                SELECT *
                FROM live_odds
                WHERE home_team = ? AND away_team = ?
                LIMIT 1
            """, (r.home_team_name, r.away_team_name), one=True)

        # fallback 2: reversed teams (sometimes feed side swaps)
        if not odds_row:
            odds_row = query_db(conn, """
                SELECT *
                FROM live_odds
                WHERE home_team_norm = ? AND away_team_norm = ?
                LIMIT 1
            """, (away_norm, home_norm), one=True)

        # fallback 3: case-insensitive name match
        if not odds_row:
            odds_row = query_db(conn, """
                SELECT *
                FROM live_odds
                WHERE LOWER(home_team) = LOWER(?) AND LOWER(away_team) = LOWER(?)
                LIMIT 1
            """, (r.home_team_name or "", r.away_team_name or ""), one=True)

        probs_mc = blend_odds_sync(probs_mc, odds_row)

        conf_score = round(max(probs_mc.get("home", 0.0), probs_mc.get("draw", 0.0), probs_mc.get("away", 0.0)), 2)

        # persist into value table (named params)
        execute_db(conn, """
            INSERT OR REPLACE INTO value VALUES (
                :match_id,:home_team_id,:away_team_id,
                :home_goals_pred,:away_goals_pred,:most_likely_score,
                :matches_used,:conf_score,:conf_btts,
                :conf_over_1_5,:conf_over_2_5,
                :conf_over_3_5,:conf_over_4_5,
                :over_1_5,:over_2_5,:over_3_5,:over_4_5,
                :btts_yes,:generated_at
            )
        """, {
            "match_id": r.match_id,
            "home_team_id": r.home_team_id,
            "away_team_id": r.away_team_id,
            "home_goals_pred": round(base_hg, 2),
            "away_goals_pred": round(base_ag, 2),
            "most_likely_score": f"{probs_mc.get('score', (0,0))[0]}-{probs_mc.get('score', (0,0))[1]}",
            "matches_used": used_h2h,
            "conf_score": conf_score,
            "conf_btts": round(probs_mc.get("btts", 0.0), 2),
            "conf_over_1_5": round(probs_mc.get("over_1_5", 0.0), 2),
            "conf_over_2_5": round(probs_mc.get("over_2_5", 0.0), 2),
            "conf_over_3_5": round(probs_mc.get("over_3_5", 0.0), 2),
            "conf_over_4_5": round(probs_mc.get("over_4_5", 0.0), 2),
            "over_1_5": bool(probs_mc.get("over_1_5", 0.0) > 0.5),
            "over_2_5": bool(probs_mc.get("over_2_5", 0.0) > 0.5),
            "over_3_5": bool(probs_mc.get("over_3_5", 0.0) > 0.5),
            "over_4_5": bool(probs_mc.get("over_4_5", 0.0) > 0.5),
            "btts_yes": bool(probs_mc.get("btts", 0.0) > 0.5),
            "generated_at": now_iso()
        })

        if i % 10 == 0 or i == total_rows:
            progress_bar(i, total_rows, prefix="📊 Predicting")

    conn.close()
    print("\n\n✅ Combined predictions & values saved")


if __name__ == "__main__":
    start = time.time()
    print("🚀 Running combined_pred_goals (fast + Monte Carlo + odds) ...")
    main()
    print(f"Done in {time.time() - start:.2f}s")
