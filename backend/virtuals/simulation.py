from __future__ import annotations

import math
import os
import random
import re
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

import numpy as np

from virtuals.config import logger, app
from virtuals.config_settings import (
    MATCH_SIM_SECONDS,
    STATUS_OPEN,
    STATUS_RUNNING,
    STATUS_FINISHED,
)
from virtuals.model import Odds, Fixture, Event
from virtuals.odds_updated import generate_odds
from virtuals.settlement import settle_virtual_bets
from virtuals.sim_events import (
    _apply_goal_event,
    _build_event_plan,
    _event_timestamp_for_minute,
    _wait_until,
)
from virtuals.sim_helpers import _clamp, _seed_int
from virtuals.utils import (
    get_session_local,
    match_lock,
    safe_commit,
    now_utc,
    shutdown_flag,
)

# Try to load the football intelligence model from engineering file.
try:
    from virtuals.engineering.test import build_team_stats, load_data, predict_match
except Exception:  # pragma: no cover
    build_team_stats = None
    load_data = None
    predict_match = None

try:
    from virtuals.sim_odds import normalize_team_name as normalize_market_team_name
except Exception:  # pragma: no cover
    normalize_market_team_name = None


# ---------------- Executors ----------------
settlement_executor = ThreadPoolExecutor(max_workers=3)

# ---------------- Security ----------------
SECRET_SALT = os.getenv("SIM_SECRET", "change_this_in_prod")

# ---------------- Model path ----------------
SIM_RESULT_PATH = os.getenv("SIM_RESULT_PATH", "result.txt")

# ---------------- State ----------------
REALISM_STATE = {
    "home_streak": {},
    "away_streak": {},
    "draw_streak": 0,
    "goal_trend": deque(maxlen=20),
}


def _secure_seed(*args):
    return _seed_int(*args, SECRET_SALT, os.urandom(4))


# ---------------- Helpers ----------------
def _settle_virtual_bets_with_context(match_id):
    with app.app_context():
        settle_virtual_bets(match_id)


def _normalize_three(a: float, b: float, c: float):
    total = a + b + c
    if total <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return a / total, b / total, c / total


def _entropy_three(home_p, draw_p, away_p):
    eps = 1e-9
    return -(
        home_p * math.log(home_p + eps)
        + draw_p * math.log(draw_p + eps)
        + away_p * math.log(away_p + eps)
    )


def _trap_index_v121(home_p, draw_p, away_p):
    fav = max(home_p, away_p)
    dog = min(home_p, away_p)

    if dog <= 0:
        return 100.0

    raw = (fav / dog) * (1 - draw_p)
    trap = 100 / (1 + math.exp(-0.08 * (raw - 10)))
    return round(trap, 2)


def _stability_v121(home_p, away_p):
    return round((1 - abs(home_p - away_p)) * 100, 2)


def _zone_v121(entropy, trap, stability):
    if trap > 70:
        return "DETONATION_TRAP"
    if entropy > 1.0 and stability < 55:
        return "CHAOS_ZONE"
    if stability > 70:
        return "CONTROLLED_FAVORITE"
    if entropy < 0.9:
        return "DRAW_FIELD"
    return "BALANCED"


def _market_state_v121(draw_p, trap, stability, entropy):
    if trap > 70 and entropy > 1.0:
        return "HIGH_MANIPULATION"
    if draw_p > 0.38:
        return "DRAW_PRESSURE"
    if stability > 70 and trap < 35:
        return "DEAD_MARKET"
    if entropy > 1.02:
        return "HIGH_VARIANCE"
    return "NORMAL"


def _odds_to_normalized_probs(source: Any):
    """
    Accepts either:
    - Odds ORM row with home/draw/away odds
    - dict from generate_odds() with home_odds/draw_odds/away_odds
    - dict with nested odds like {"odds": {"home": ...}}
    """
    if source is None:
        return 1 / 3, 1 / 3, 1 / 3

    if isinstance(source, Mapping) and isinstance(source.get("odds"), Mapping):
        source = source["odds"]

    def pick(*names: str):
        if isinstance(source, Mapping):
            for name in names:
                if source.get(name) is not None:
                    try:
                        return float(source[name])
                    except Exception:
                        pass
        for name in names:
            if hasattr(source, name):
                value = getattr(source, name)
                if value is not None:
                    try:
                        return float(value)
                    except Exception:
                        pass
        return None

    home = pick("home", "home_odds", "1", "odds1", "odd1")
    draw = pick("draw", "draw_odds", "x", "X", "oddsx", "oddx")
    away = pick("away", "away_odds", "2", "odds2", "odd2")

    if not home or not draw or not away or home <= 0 or draw <= 0 or away <= 0:
        return 1 / 3, 1 / 3, 1 / 3

    inv = np.array([1.0 / home, 1.0 / draw, 1.0 / away], dtype=float)
    s = float(inv.sum())
    if s <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    inv /= s
    return float(inv[0]), float(inv[1]), float(inv[2])


def _resolve_stats_team(team: str, stats_map: dict) -> Optional[str]:
    if team in stats_map:
        return team

    if normalize_market_team_name is not None:
        try:
            normalized = normalize_market_team_name(team)
            if normalized in stats_map:
                return normalized
        except Exception:
            pass

    raw = str(team).strip().lower()
    raw = re.sub(r"[._-]+", " ", raw)
    raw = " ".join(raw.split())
    compact = raw.replace(" ", "")

    for key in stats_map.keys():
        k = str(key).strip().lower()
        k_norm = re.sub(r"[._-]+", " ", k)
        k_norm = " ".join(k_norm.split())
        if k_norm == raw or k_norm.replace(" ", "") == compact:
            return key

    return None


@lru_cache(maxsize=1)
def _load_football_stats_map():
    """
    Loads and caches the football model from test.py.
    This uses result.txt (or SIM_RESULT_PATH) to build team stats once.
    """
    if load_data is None or build_team_stats is None:
        logger.warning("Football model helpers are unavailable; market-only fallback will be used.")
        return {}

    path = Path(SIM_RESULT_PATH)
    if not path.exists():
        logger.warning("SIM_RESULT_PATH not found: %s", path)
        return {}

    try:
        df = load_data(str(path))
        team_df = build_team_stats(df)
        return team_df.set_index("team").to_dict("index")
    except Exception:
        logger.exception("Failed loading football stats from %s", path)
        return {}


def _football_model_prediction(home: str, away: str):
    """
    Returns the full prediction dict from test.py, or None if unavailable.
    """
    if predict_match is None:
        return None

    stats_map = _load_football_stats_map()
    if not stats_map:
        return None

    try:
        home_key = _resolve_stats_team(home, stats_map)
        away_key = _resolve_stats_team(away, stats_map)
        if home_key is None or away_key is None:
            return None

        return predict_match(home_key, away_key, stats_map=stats_map)
    except Exception:
        logger.exception("Football model prediction failed for %s vs %s", home, away)
        return None


def _market_probs_for_match(home: str, away: str, session, match_id):
    """
    Prefer persisted odds from DB. If missing, generate a temporary market estimate.
    """
    odds_row = session.query(Odds).filter(Odds.match_id == match_id).first()
    if odds_row is not None:
        return _odds_to_normalized_probs(odds_row)

    try:
        generated = generate_odds(home, away)
        return _odds_to_normalized_probs(generated)
    except Exception:
        logger.exception("Market odds generation failed for %s vs %s", home, away)

    if normalize_market_team_name is not None:
        try:
            nh = normalize_market_team_name(home)
            na = normalize_market_team_name(away)
            generated = generate_odds(nh, na)
            return _odds_to_normalized_probs(generated)
        except Exception:
            logger.exception(
                "Fallback market odds generation failed for normalized names %s vs %s",
                home,
                away,
            )

    return 1 / 3, 1 / 3, 1 / 3


def _normalize_scoreline_item(item):
    """
    Accepts:
    - ((hg, ag), prob)
    - ("1-1", prob)
    - ((hg, ag),)
    """
    if not item:
        return None

    score = None
    prob = None

    if isinstance(item, (list, tuple)):
        if len(item) >= 2:
            score, prob = item[0], item[1]
        elif len(item) == 1:
            score = item[0]
            prob = 1.0
        else:
            return None
    else:
        return None

    if isinstance(score, str):
        m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", score)
        if not m:
            return None
        hg, ag = int(m.group(1)), int(m.group(2))
    elif isinstance(score, (list, tuple)) and len(score) >= 2:
        hg, ag = int(score[0]), int(score[1])
    else:
        return None

    try:
        prob = float(prob)
    except Exception:
        prob = 0.0

    if prob < 0:
        prob = 0.0

    return (hg, ag), prob


def _fallback_scorelines():
    return [
        ((1, 1), 0.24),
        ((2, 1), 0.18),
        ((1, 2), 0.18),
        ((2, 2), 0.12),
        ((1, 0), 0.10),
        ((0, 1), 0.10),
        ((2, 0), 0.04),
        ((0, 2), 0.04),
    ]


def _scoreline_zone_weight(score, zone, market_probs):
    hg, ag = score
    total = hg + ag
    gap = abs(hg - ag)

    home_p, draw_p, away_p = market_probs
    fav_is_home = home_p >= away_p
    is_draw = hg == ag
    home_win = hg > ag
    away_win = ag > hg

    weight = 1.0

    if zone == "DRAW_FIELD":
        if is_draw:
            weight *= 1.35 if total <= 4 else 1.18
        elif gap == 1:
            weight *= 1.08
        else:
            weight *= 0.88

    elif zone == "CONTROLLED_FAVORITE":
        fav_win = (fav_is_home and home_win) or ((not fav_is_home) and away_win)
        if fav_win:
            weight *= 1.20 if gap <= 1 else 1.08
        elif is_draw:
            weight *= 0.90
        else:
            weight *= 0.80

    elif zone == "DETONATION_TRAP":
        if fav_is_home:
            if away_win:
                weight *= 1.40
            elif is_draw:
                weight *= 1.15
            else:
                weight *= 0.78
        else:
            if home_win:
                weight *= 1.40
            elif is_draw:
                weight *= 1.15
            else:
                weight *= 0.78

    elif zone == "CHAOS_ZONE":
        # Flatten slightly and keep scorelines competitive
        if abs(total - 3) <= 1:
            weight *= 1.05
        if gap >= 2:
            weight *= 1.03
        weight *= 0.98

    else:  # BALANCED
        if is_draw:
            weight *= 1.02
        elif gap == 1:
            weight *= 1.01

    if draw_p >= 0.35 and is_draw:
        weight *= 1.05

    return max(weight, 1e-9)


def _prepare_scoring_pool(football_pred, market_probs, zone):
    raw_scores = []
    if football_pred is not None:
        raw_scores = football_pred.get("top_scores") or football_pred.get("scorelines") or []

    candidates = []
    for item in raw_scores:
        parsed = _normalize_scoreline_item(item)
        if parsed is None:
            continue
        score, prob = parsed
        candidates.append((score, prob))

    if not candidates:
        candidates = _fallback_scorelines()

    weighted = []
    for score, prob in candidates:
        zone_weight = _scoreline_zone_weight(score, zone, market_probs)
        final_weight = max(float(prob), 1e-9) * zone_weight
        weighted.append((score, final_weight))

    total = sum(w for _, w in weighted)
    if total <= 0:
        return _fallback_scorelines()

    return [(score, w / total) for score, w in weighted]


def _pick_weighted_scoreline(rng: random.Random, scoring_pool: Sequence[Tuple[Tuple[int, int], float]]):
    if not scoring_pool:
        return 1, 1

    total = sum(max(weight, 0.0) for _, weight in scoring_pool)
    if total <= 0:
        return scoring_pool[0][0]

    pick = rng.uniform(0.0, total)
    cumulative = 0.0
    for score, weight in scoring_pool:
        cumulative += max(weight, 0.0)
        if pick <= cumulative:
            return score

    return scoring_pool[-1][0]


def _score_to_outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "HOME"
    if home_goals < away_goals:
        return "AWAY"
    return "DRAW"


def _record_simulation_metrics(match):
    home = match.home_score or 0
    away = match.away_score or 0
    total = home + away

    REALISM_STATE["goal_trend"].append(total)

    if home > away:
        REALISM_STATE["home_streak"][match.home] = REALISM_STATE["home_streak"].get(match.home, 0) + 1
        REALISM_STATE["away_streak"][match.away] = 0
        REALISM_STATE["draw_streak"] = 0
    elif away > home:
        REALISM_STATE["away_streak"][match.away] = REALISM_STATE["away_streak"].get(match.away, 0) + 1
        REALISM_STATE["home_streak"][match.home] = 0
        REALISM_STATE["draw_streak"] = 0
    else:
        REALISM_STATE["draw_streak"] += 1


# ---------------- Simulation ----------------
def simulate_match(match_id, emit_update_callback=None):
    logger.info("[simulate] match %s", match_id)
    SessionMaker = get_session_local()

    try:
        with app.app_context():
            with match_lock(match_id):
                with SessionMaker() as session:
                    match = session.query(Fixture).filter(Fixture.id == match_id).first()
                    if not match or match.status not in (STATUS_OPEN, STATUS_RUNNING):
                        return

                    match.status = STATUS_RUNNING
                    match.is_simulating = True
                    safe_commit(session)

                    home = match.home
                    away = match.away

                    market_probs = _market_probs_for_match(home, away, session, match.id)
                    home_p, draw_p, away_p = market_probs

                    entropy = _entropy_three(home_p, draw_p, away_p)
                    trap = _trap_index_v121(home_p, draw_p, away_p)
                    stability = _stability_v121(home_p, away_p)
                    zone = _zone_v121(entropy, trap, stability)
                    market_state = _market_state_v121(draw_p, trap, stability, entropy)

                    football_pred = _football_model_prediction(home, away)
                    scoring_pool = _prepare_scoring_pool(football_pred, market_probs, zone)

                    logger.info(
                        "[simulate] match %s | zone=%s | state=%s | market=%.3f/%.3f/%.3f",
                        match_id,
                        zone,
                        market_state,
                        home_p,
                        draw_p,
                        away_p,
                    )

        rng = random.Random(_secure_seed(match_id, home, away))
        final_home, final_away = _pick_weighted_scoreline(rng, scoring_pool)
        outcome = _score_to_outcome(final_home, final_away)

        if football_pred is not None:
            expected_goals = float(football_pred.get("total_goals", final_home + final_away))
            likely_type = football_pred.get("likely_type")
        else:
            expected_goals = float(final_home + final_away)
            likely_type = None

        # ---------------- EVENT SYNC ----------------
        event_rng = random.Random(_secure_seed(match_id, "events"))

        match_snapshot = {
            "home": home,
            "away": away,
        }

        event_plan = _build_event_plan(
            match_snapshot,
            final_home,
            final_away,
            max(expected_goals, 0.5),
            event_rng,
        )

        start_dt = now_utc()
        end_dt = start_dt + timedelta(seconds=MATCH_SIM_SECONDS)

        with SessionMaker() as session:
            match_live = session.query(Fixture).filter(Fixture.id == match_id).first()
            if match_live is None:
                return

            for item in event_plan:
                if shutdown_flag.is_set():
                    break

                event_dt = _event_timestamp_for_minute(start_dt, end_dt, item["minute"])

                if not _wait_until(event_dt):
                    break

                if item["type"] == "GOAL":
                    _apply_goal_event(match_live, item["team"])

                session.add(
                    Event(
                        match_id=match_live.id,
                        minute=item["minute"],
                        team=item["team"],
                        type=item["type"],
                        description=item["description"],
                    )
                )

                match_live.event_count = (match_live.event_count or 0) + 1
                safe_commit(session)

                if emit_update_callback:
                    emit_update_callback(match_live)

            # FINALIZE
            match_live.home_score = final_home
            match_live.away_score = final_away
            match_live.status = STATUS_FINISHED
            match_live.is_simulating = False

            safe_commit(session)

            settlement_executor.submit(_settle_virtual_bets_with_context, match_id)
            _record_simulation_metrics(match_live)

            logger.info(
                "[simulate] finished match %s | score=%s-%s | outcome=%s | likely_type=%s",
                match_id,
                final_home,
                final_away,
                outcome,
                likely_type,
            )

    except Exception:
        logger.exception("Simulation error %s", match_id)
