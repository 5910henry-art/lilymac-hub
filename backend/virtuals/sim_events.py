# sim_events.py

import random
from datetime import timedelta

from virtuals.config import logger
from virtuals.config_settings import MATCH_SIM_SECONDS, MAX_EVENTS_PER_MATCH
from virtuals.model import Event
from virtuals.sim_helpers import (
    _clamp,
    _get_attr_or_key,
    _sample_unique_minutes,
    _seed_int,
)
from virtuals.utils import now_utc, shutdown_flag, safe_commit, to_utc


def _apply_goal_event(match, team):
    home_team = _get_attr_or_key(match, "home", None)
    if team == home_team:
        match.home_score = (match.home_score or 0) + 1
    else:
        match.away_score = (match.away_score or 0) + 1


def _event_timestamp_for_minute(start_dt, end_dt, minute):
    start_dt = to_utc(start_dt) or now_utc()
    end_dt = to_utc(end_dt) or (start_dt + timedelta(seconds=MATCH_SIM_SECONDS))
    duration = max(1.0, (end_dt - start_dt).total_seconds())

    ratio = _clamp(minute / 90.0, 0.0, 1.0)
    return start_dt + timedelta(seconds=duration * ratio)


def _wait_until(target_dt):
    target_dt = to_utc(target_dt) or now_utc()

    while True:
        if shutdown_flag.is_set():
            return False

        remaining = (target_dt - now_utc()).total_seconds()
        if remaining <= 0:
            return True

        shutdown_flag.wait(min(0.25, max(0.01, remaining)))


def _weighted_minute_sample(rng, count):
    """
    More realistic distribution:
    - fewer early events
    - peak mid/late game
    """
    minutes = list(range(1, 91))

    weights = []
    for m in minutes:
        if m < 10:
            w = 0.6
        elif m < 30:
            w = 1.0
        elif m < 60:
            w = 1.2
        elif m < 80:
            w = 1.4
        else:
            w = 1.2
        weights.append(w)

    chosen = set()
    while len(chosen) < count and minutes:
        pick = rng.choices(minutes, weights=weights, k=1)[0]
        idx = minutes.index(pick)
        chosen.add(pick)
        minutes.pop(idx)
        weights.pop(idx)

    return sorted(chosen)


def _build_event_plan(match, home_goals, away_goals, expected_goals, rng):
    home_team = _get_attr_or_key(match, "home", None)
    away_team = _get_attr_or_key(match, "away", None)

    total_goals = home_goals + away_goals

    # --- GOAL MINUTES (with spacing control) ---
    raw_goal_minutes = _weighted_minute_sample(rng, total_goals)

    goal_minutes = []
    last_min = -10
    for m in raw_goal_minutes:
        if m - last_min < 3:  # enforce spacing
            m = min(90, m + rng.randint(2, 5))
        goal_minutes.append(m)
        last_min = m

    goal_teams = [home_team] * home_goals + [away_team] * away_goals
    rng.shuffle(goal_teams)

    plan = []
    for minute, team in zip(goal_minutes, goal_teams):
        plan.append(
            {
                "minute": minute,
                "team": team,
                "type": "GOAL",
                "description": f"⚽ {minute}' GOAL! {team} scores!",
            }
        )

    # --- NON-GOAL EVENTS (scaled by match intensity) ---
    remaining_capacity = max(0, MAX_EVENTS_PER_MATCH - total_goals)

    intensity = _clamp(expected_goals / 2.5, 0.7, 1.4)

    base_events = 2 + int(expected_goals * 1.2)
    non_goal_target = int(base_events * intensity + rng.uniform(0, 2))
    non_goal_target = min(remaining_capacity, max(1, non_goal_target))

    used_minutes = set(goal_minutes)
    available_minutes = [m for m in range(1, 91) if m not in used_minutes]

    extra_minutes = _weighted_minute_sample(rng, non_goal_target)

    for minute in extra_minutes:
        team = rng.choice([home_team, away_team])
        roll = rng.random()

        # --- REALISTIC EVENT DISTRIBUTION ---
        if roll < 0.04:
            evt_type = "RED"
            desc = f"🟥 {minute}' Red card for {team}"
        elif roll < 0.18:
            evt_type = "YELLOW"
            desc = f"🟨 {minute}' Yellow card for {team}"
        elif roll < 0.28:
            evt_type = "PENALTY"
            desc = f"🟦 {minute}' Penalty awarded to {team}"
        elif roll < 0.50:
            evt_type = "SHOT"
            desc = f"🎯 {minute}' Shot on target by {team}"
        elif roll < 0.70:
            evt_type = "CORNER"
            desc = f"🚩 {minute}' Corner for {team}"
        elif roll < 0.82:
            evt_type = "SUB"
            desc = f"🔁 {minute}' Substitution for {team}"
        else:
            evt_type = "MISS"
            desc = f"❌ {minute}' Missed chance by {team}"

        plan.append(
            {
                "minute": minute,
                "team": team,
                "type": evt_type,
                "description": desc,
            }
        )

    # --- SORT EVENTS PROPERLY ---
    plan.sort(
        key=lambda item: (
            item["minute"],
            {
                "GOAL": 0,
                "PENALTY": 1,
                "RED": 2,
                "YELLOW": 3,
                "SUB": 4,
                "SHOT": 5,
                "CORNER": 6,
                "MISS": 7,
            }.get(item["type"], 9),
        )
    )

    return plan


def generate_event_for_match(match, session, emit_update_callback=None, now_dt=None):
    """
    Fallback random event generator (less important now).
    """
    try:
        if (match.event_count or 0) >= MAX_EVENTS_PER_MATCH:
            return

        minute = random.randint(1, 90)
        rng = random.Random(_seed_int(match.id, match.event_count or 0, minute, "event"))

        team = rng.choice([match.home, match.away])
        roll = rng.random()

        if roll < 0.06:
            evt_type = "GOAL"
            desc = f"⚽ {minute}' GOAL! {team} scores!"
            _apply_goal_event(match, team)
        elif roll < 0.10:
            evt_type = "RED"
            desc = f"🟥 {minute}' Red card for {team}"
        elif roll < 0.22:
            evt_type = "YELLOW"
            desc = f"🟨 {minute}' Yellow card for {team}"
        elif roll < 0.32:
            evt_type = "PENALTY"
            desc = f"🟦 {minute}' Penalty awarded to {team}"
        elif roll < 0.55:
            evt_type = "SHOT"
            desc = f"🎯 {minute}' Shot on target by {team}"
        elif roll < 0.72:
            evt_type = "CORNER"
            desc = f"🚩 {minute}' Corner for {team}"
        elif roll < 0.85:
            evt_type = "SUB"
            desc = f"🔁 {minute}' Substitution for {team}"
        else:
            evt_type = "MISS"
            desc = f"❌ {minute}' Missed chance by {team}"

        event = Event(
            match_id=match.id,
            minute=minute,
            team=team,
            type=evt_type,
            description=desc,
        )
        session.add(event)

        match.event_count = (match.event_count or 0) + 1
        session.add(match)
        safe_commit(session)

        if emit_update_callback:
            emit_update_callback(match)

    except Exception:
        session.rollback()
        logger.exception("Event generation failed %s", match.id)
