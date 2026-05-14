# simulation.py

import hashlib
import math
import os
import random
from collections import deque, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock

from virtuals.config import logger, db, app
from virtuals.config_settings import (
    MATCH_SIM_SECONDS,
    STATUS_OPEN,
    STATUS_RUNNING,
    STATUS_FINISHED,
    STATUS_SCHEDULED,
    TEAMS,
    MAX_EVENTS_PER_MATCH,
    VIRTUAL_RTP_TARGET,
    ROUND_INTERVAL,
    BETTING_TIME,
    TOTAL_ROUNDS,
)
from virtuals.model import Odds, Fixture, Event
from virtuals.settlement import settle_virtual_bets
from virtuals.utils import (
    get_session_local,
    match_lock,
    safe_commit,
    now_utc,
    shutdown_flag,
    to_utc,
)

settlement_executor = ThreadPoolExecutor(max_workers=3)

MATCH_SIM_BUFFER_SECONDS = int(os.getenv("VIRTUAL_MATCH_SIM_BUFFER_SECONDS", "30"))
MATCH_SIM_TIMEOUT_SECONDS = max(1, MATCH_SIM_SECONDS + MATCH_SIM_BUFFER_SECONDS)

ANALYTICS_HISTORY_SIZE = int(os.getenv("VIRTUAL_SIM_HISTORY", "250"))
simulation_history = deque(maxlen=ANALYTICS_HISTORY_SIZE)
analytics_lock = Lock()

# Small pacing controls so the simulation feels alive instead of instant.
SIM_MIN_EVENT_GAP_SECONDS = float(os.getenv("VIRTUAL_SIM_MIN_EVENT_GAP_SECONDS", "0.35"))
SIM_POST_MATCH_PAUSE_SECONDS = float(os.getenv("VIRTUAL_SIM_POST_MATCH_PAUSE_SECONDS", "0.15"))

# Optional global tuning knobs.
LEAGUE_GOAL_BIAS = float(os.getenv("VIRTUAL_LEAGUE_GOAL_BIAS", "0.00"))
LEAGUE_DRAW_BIAS = float(os.getenv("VIRTUAL_LEAGUE_DRAW_BIAS", "0.00"))
LEAGUE_HOME_ADVANTAGE_BIAS = float(os.getenv("VIRTUAL_LEAGUE_HOME_ADVANTAGE_BIAS", "0.00"))

# Optional per-team styles can be injected later if you want:
# TEAM_STYLES = {
#     "Team Name": {"attack": 1.08, "defense": 0.94},
# }
TEAM_STYLES = {}


def _settle_virtual_bets_with_context(match_id):
    """Run settlement safely inside a Flask application context."""
    with app.app_context():
        settle_virtual_bets(match_id)


def _clamp(value, low, high):
    return max(low, min(high, value))


def _normalize_three(a, b, c):
    total = a + b + c
    if total <= 0:
        return 0.4, 0.2, 0.4
    return a / total, b / total, c / total


def _seed_int(*parts):
    payload = "|".join(str(p) for p in parts if p is not None)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _get_attr_or_key(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _season_key(fixture):
    """
    Prefer explicit season identity.
    This avoids round-based collisions across different seasons.
    """
    for attr in ("season_id", "season"):
        value = _get_attr_or_key(fixture, attr, None)
        if value not in (None, "", 0):
            return f"season-{value}"

    for attr in ("open_time", "start_time", "created_at", "updated_at"):
        value = _get_attr_or_key(fixture, attr, None)
        if value:
            dt = to_utc(value)
            if dt:
                return dt.strftime("%Y-%m")
            return str(value)

    fixture_id = _get_attr_or_key(fixture, "id", "unknown")
    return f"fixture-{fixture_id}"


def _fmt_dt(value):
    if value is None:
        return "None"
    try:
        return value.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def _poisson_pmf(k, lmb):
    if lmb <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lmb) * (lmb**k) / math.factorial(k)


def _weighted_choice(rng, items):
    total = sum(max(0.0, w) for _, w in items)
    if total <= 0:
        return items[0][0]

    pick = rng.uniform(0, total)
    upto = 0.0
    for value, weight in items:
        upto += max(0.0, weight)
        if upto >= pick:
            return value
    return items[-1][0]


def _sample_unique_minutes(rng, pool, count):
    if count <= 0 or not pool:
        return []

    pool = list(pool)
    weights = []
    for minute in pool:
        # Slightly more action in the middle and late stages.
        t = minute / 90.0
        weights.append(0.45 + math.sin(math.pi * t) + (0.15 if minute >= 70 else 0.0))

    chosen = []
    for _ in range(min(count, len(pool))):
        minute = _weighted_choice(rng, list(zip(pool, weights)))
        idx = pool.index(minute)
        chosen.append(minute)
        pool.pop(idx)
        weights.pop(idx)

    return sorted(chosen)


def _table_position_bonus(rank, total_teams):
    if total_teams <= 1:
        return 0.0

    normalized = (total_teams - rank) / (total_teams - 1)  # 0..1
    return _clamp((normalized - 0.5) * 6.0, -3.0, 3.0)


def _form_bonus(form):
    """
    W = +2
    D =  0
    L = -2
    last 5 only
    """
    weights = {"W": 2, "D": 0, "L": -2}
    score = sum(weights.get(x, 0) for x in (form or [])[-5:])
    return _clamp(score * 0.35, -2.5, 2.5)


def _context_attack_adjustment(team_context=None, total_teams=0):
    ctx = team_context or {}
    adj = 0.0

    if ctx:
        adj += _table_position_bonus(ctx.get("rank", total_teams), total_teams)
        adj += _form_bonus(ctx.get("form", []))
        played = max(1, ctx.get("played", 1))
        ppg = ctx.get("points", 0) / played
        adj += _clamp((ppg - 1.5) * 2.0, -2.0, 2.0)

    return adj


def _team_style_adjustment(team):
    style = TEAM_STYLES.get(team) or {}
    attack = float(style.get("attack", 1.0))
    defense = float(style.get("defense", 1.0))
    return attack, defense


def _match_strengths(match, team_context=None, total_teams=0):
    home = _get_attr_or_key(match, "home", None)
    away = _get_attr_or_key(match, "away", None)

    home_rating = TEAMS.get(home, 75)
    away_rating = TEAMS.get(away, 75)

    home_ctx = (team_context or {}).get(home)
    away_ctx = (team_context or {}).get(away)

    home_rating += _context_attack_adjustment(home_ctx, total_teams)
    away_rating += _context_attack_adjustment(away_ctx, total_teams)

    home_attack, home_defense = _team_style_adjustment(home)
    away_attack, away_defense = _team_style_adjustment(away)

    # Attack strength lifts a team's scoring profile.
    # Opponent defense slightly suppresses scoring.
    home_rating *= _clamp(home_attack, 0.85, 1.20)
    away_rating *= _clamp(away_attack, 0.85, 1.20)

    away_defense = _clamp(away_defense, 0.85, 1.20)
    home_defense = _clamp(home_defense, 0.85, 1.20)

    home_rating *= 1.0 / away_defense
    away_rating *= 1.0 / home_defense

    return home_rating, away_rating


def _expected_goals(home_rating, away_rating, rng):
    base_total_goals = 2.05 + ((home_rating + away_rating) - 150) / 140.0
    season_goal_shift = rng.uniform(-0.25, 0.35)
    matchup_style_shift = 0.18 if abs(home_rating - away_rating) < 6 else 0.0

    return _clamp(
        base_total_goals
        + season_goal_shift
        + matchup_style_shift
        + LEAGUE_GOAL_BIAS,
        1.35,
        4.35,
    )


def _outcome_probabilities(home_rating, away_rating, rng):
    rating_gap = home_rating - away_rating
    home_advantage = 4.5 + LEAGUE_HOME_ADVANTAGE_BIAS
    compressed_gap = math.tanh((rating_gap + home_advantage) / 24.0)

    raw_home = 0.41 + (compressed_gap * 0.17) + rng.uniform(-0.025, 0.025)
    raw_away = 0.37 - (compressed_gap * 0.15) + rng.uniform(-0.025, 0.025)
    raw_draw = 0.22 - abs(compressed_gap) * 0.04 + rng.uniform(-0.015, 0.015) + LEAGUE_DRAW_BIAS

    raw_home = _clamp(raw_home, 0.20, 0.60)
    raw_away = _clamp(raw_away, 0.20, 0.60)
    raw_draw = _clamp(raw_draw, 0.12, 0.30)

    return _normalize_three(raw_home, raw_draw, raw_away)


def _pick_outcome(rng, home_prob, draw_prob, away_prob):
    return _weighted_choice(
        rng,
        [
            ("HOME", home_prob),
            ("DRAW", draw_prob),
            ("AWAY", away_prob),
        ],
    )


def _pick_scoreline(rng, outcome, expected_goals, home_rating, away_rating):
    home_xg = _clamp(
        expected_goals / 2.0 + ((home_rating - away_rating) / 30.0),
        0.35,
        3.25,
    )
    away_xg = _clamp(expected_goals - home_xg, 0.25, 3.10)

    max_goals_per_team = 5
    candidates = []

    for h in range(max_goals_per_team + 1):
        for a in range(max_goals_per_team + 1):
            total_goals = h + a
            if total_goals > MAX_EVENTS_PER_MATCH:
                continue

            base = _poisson_pmf(h, home_xg) * _poisson_pmf(a, away_xg)
            if base <= 0:
                continue

            if outcome == "HOME":
                result_bonus = 2.9 if h > a else 0.12
                shape_bonus = 1.25 / (1.0 + abs((h - a) - 1.0) * 0.60)
                if h == 0 and a == 0:
                    shape_bonus *= 0.55
            elif outcome == "AWAY":
                result_bonus = 2.9 if a > h else 0.12
                shape_bonus = 1.25 / (1.0 + abs((a - h) - 1.0) * 0.60)
                if h == 0 and a == 0:
                    shape_bonus *= 0.55
            else:
                if h == a:
                    result_bonus = 3.1
                    if h == 0:
                        result_bonus *= 0.40
                    elif h == 1:
                        result_bonus *= 1.20
                    elif h == 2:
                        result_bonus *= 1.20
                    shape_bonus = 1.50 / (1.0 + abs(total_goals - 2.0) * 0.55)
                else:
                    result_bonus = 0.05
                    shape_bonus = 0.55

            total_bonus = 1.18 / (1.0 + abs(total_goals - expected_goals) * 0.35)
            weight = base * result_bonus * shape_bonus * total_bonus
            candidates.append(((h, a), weight))

    if not candidates:
        if outcome == "HOME":
            return 1, 0
        if outcome == "AWAY":
            return 0, 1
        return 1, 1

    return _weighted_choice(rng, candidates)


def _build_event_plan(match, home_goals, away_goals, expected_goals, rng):
    home_team = _get_attr_or_key(match, "home", None)
    away_team = _get_attr_or_key(match, "away", None)

    total_goals = home_goals + away_goals
    goal_minutes = _sample_unique_minutes(rng, range(3, 91), total_goals)

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

    remaining_capacity = max(0, MAX_EVENTS_PER_MATCH - total_goals)

    if total_goals == 0:
        non_goal_target = min(
            remaining_capacity,
            max(2, int(round(2 + rng.uniform(0, 2)))),
        )
    else:
        non_goal_target = min(
            remaining_capacity,
            max(1, int(round(2 + expected_goals * 0.9 + rng.uniform(0, 2)))),
        )

    used_minutes = set(goal_minutes)
    available_minutes = [m for m in range(1, 91) if m not in used_minutes]
    extra_minutes = _sample_unique_minutes(rng, available_minutes, non_goal_target)

    for minute in extra_minutes:
        team = rng.choice([home_team, away_team])
        roll = rng.random()

        if minute in (44, 45, 46) and roll < 0.30:
            evt_type = "SUB"
            desc = f"🔁 {minute}' Substitution for {team}"
        elif roll < 0.10:
            evt_type = "RED"
            desc = f"🟥 {minute}' Red card for {team}"
        elif roll < 0.25:
            evt_type = "PENALTY"
            desc = f"🟦 {minute}' Penalty awarded to {team}"
        elif roll < 0.45:
            evt_type = "YELLOW"
            desc = f"🟨 {minute}' Yellow card for {team}"
        elif roll < 0.65:
            evt_type = "SHOT"
            desc = f"🎯 {minute}' Shot on target by {team}"
        elif roll < 0.80:
            evt_type = "CORNER"
            desc = f"🚩 {minute}' Corner for {team}"
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


def _apply_goal_event(match, team):
    home_team = _get_attr_or_key(match, "home", None)
    if team == home_team:
        match.home_score = (match.home_score or 0) + 1
    else:
        match.away_score = (match.away_score or 0) + 1


def _event_timestamp_for_minute(start_dt, end_dt, minute):
    """
    Map a match minute (1..90) onto the simulated time window.
    """
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


def poisson_random(lmb, rng=None):
    if lmb <= 0:
        return 0
    rng = rng or random
    L = math.exp(-lmb)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def poisson_over_probability(lmb, threshold):
    if lmb <= 0:
        return 0.0
    cdf = 0.0
    for k in range(0, threshold + 1):
        cdf += math.exp(-lmb) * (lmb**k) / math.factorial(k)
    return _clamp(1.0 - cdf, 0.01, 0.99)


def prob_to_odds(p):
    return round(max(1.2, 1 / max(p, 0.05)), 2)


def apply_rtp_to_odds(odds_obj, rtp_target=VIRTUAL_RTP_TARGET):
    variance = random.uniform(-0.015, 0.015)
    effective_rtp = _clamp(rtp_target + variance, 0.80, 0.98)

    for attr in [
        "home",
        "draw",
        "away",
        "over15",
        "under15",
        "over25",
        "under25",
        "btts_yes",
        "btts_no",
    ]:
        raw = getattr(odds_obj, attr)
        adjusted = round(raw / effective_rtp, 2)
        adjusted = max(1.01, min(adjusted, 50.0))
        setattr(odds_obj, attr, adjusted)

    return odds_obj


def apply_market_deductions(odds_obj):
    """
    Apply your configured deductions after RTP adjustment.

    Rules:
    - 1X2: subtract 0.5 from home, draw, away
    - Over/Under 1.5: subtract 0.16 from both over15 and under15
    - Over/Under 2.5: subtract 0.2 from both over25 and under25
    - BTTS Yes: subtract 1.35
    - BTTS No: unchanged
    """
    deductions = {
        "home": 0.5,
        "draw": 2.23,
        "away": 0.5,
        "over15": 0.16,
        "under15": 0.16,
        "over25": 0.2,
        "under25": 0.2,
        "btts_yes": 1.35,
    }

    for attr, deduction in deductions.items():
        if hasattr(odds_obj, attr):
            raw = getattr(odds_obj, attr)
            adjusted = round(max(1.01, raw - deduction), 2)
            setattr(odds_obj, attr, adjusted)

    return odds_obj


def _odds_to_normalized_probs(odds_obj):
    if not odds_obj:
        return None

    try:
        home = 1.0 / max(float(odds_obj.home), 1.01)
        draw = 1.0 / max(float(odds_obj.draw), 1.01)
        away = 1.0 / max(float(odds_obj.away), 1.01)
        return _normalize_three(home, draw, away)
    except Exception:
        return None


def _blend_three_prob_sets(model_probs, market_probs=None, market_weight=0.45):
    """
    Blend model probabilities with market probabilities so the simulation
    stays realistic but not perfectly deterministic.
    """
    if not market_probs:
        return model_probs

    market_weight = _clamp(market_weight, 0.10, 0.80)
    model_weight = 1.0 - market_weight

    home = (model_probs[0] * model_weight) + (market_probs[0] * market_weight)
    draw = (model_probs[1] * model_weight) + (market_probs[1] * market_weight)
    away = (model_probs[2] * model_weight) + (market_probs[2] * market_weight)
    return _normalize_three(home, draw, away)


def _calc_table_from_fixtures(fixtures):
    table = defaultdict(lambda: {
        "team": None,
        "played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "gf": 0,
        "ga": 0,
        "points": 0,
        "form": [],
    })

    for f in fixtures:
        home = f.home
        away = f.away
        h = int(f.home_score or 0)
        a = int(f.away_score or 0)

        for team in (home, away):
            table[team]["team"] = team

        table[home]["played"] += 1
        table[away]["played"] += 1

        table[home]["gf"] += h
        table[home]["ga"] += a
        table[away]["gf"] += a
        table[away]["ga"] += h

        if h > a:
            table[home]["wins"] += 1
            table[home]["points"] += 3
            table[away]["losses"] += 1
            table[home]["form"].append("W")
            table[away]["form"].append("L")
        elif a > h:
            table[away]["wins"] += 1
            table[away]["points"] += 3
            table[home]["losses"] += 1
            table[away]["form"].append("W")
            table[home]["form"].append("L")
        else:
            table[home]["draws"] += 1
            table[away]["draws"] += 1
            table[home]["points"] += 1
            table[away]["points"] += 1
            table[home]["form"].append("D")
            table[away]["form"].append("D")

    rows = list(table.values())
    rows.sort(key=lambda x: (x["points"], x["gf"] - x["ga"], x["gf"]), reverse=True)

    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
        row["goal_difference"] = row["gf"] - row["ga"]
        row["form"] = row["form"][-5:]

    return {row["team"]: row for row in rows}, len(rows)


def build_previous_season_context(season_id, session=None):
    if not season_id or season_id <= 0:
        return {}, 0

    if session is not None:
        fixtures = (
            session.query(Fixture)
            .filter(
                Fixture.season == season_id,
                Fixture.status == STATUS_FINISHED,
                Fixture.is_settled.is_(True),
            )
            .all()
        )
        return _calc_table_from_fixtures(fixtures)

    with app.app_context():
        fixtures = (
            db.session.query(Fixture)
            .filter(
                Fixture.season_id == season_id,
                Fixture.status == STATUS_FINISHED,
                Fixture.is_settled.is_(True),
            )
            .all()
        )
        return _calc_table_from_fixtures(fixtures)


def get_current_season():
    """
    Returns the current season number. Creates a meta row if none exists.
    """
    from virtuals.config_settings import SCHEMA

    class Meta(db.Model):
        __tablename__ = "virtual_meta"
        __table_args__ = {"schema": SCHEMA} if SCHEMA else {}

        id = db.Column(db.Integer, primary_key=True)
        current_season = db.Column(db.Integer, default=1)

    with app.app_context():
        meta = db.session.query(Meta).first()

        if not meta:
            meta = Meta(current_season=1)
            db.session.add(meta)
            db.session.commit()

        return meta.current_season


def advance_season():
    from virtuals.config_settings import SCHEMA

    class Meta(db.Model):
        __tablename__ = "virtual_meta"
        __table_args__ = {"schema": SCHEMA} if SCHEMA else {}

        id = db.Column(db.Integer, primary_key=True)
        current_season = db.Column(db.Integer, default=1)

    with app.app_context():
        meta = db.session.query(Meta).first()

        if not meta:
            meta = Meta(current_season=1)
            db.session.add(meta)
        else:
            meta.current_season += 1

        db.session.commit()
        logger.info("➡️ Advanced to season %s", meta.current_season)


def generate_virtual_odds(fixture, team_context=None, total_teams=0):
    home_rating = TEAMS.get(fixture.home, 75)
    away_rating = TEAMS.get(fixture.away, 75)

    home_ctx = (team_context or {}).get(fixture.home)
    away_ctx = (team_context or {}).get(fixture.away)

    home_rating += _context_attack_adjustment(home_ctx, total_teams)
    away_rating += _context_attack_adjustment(away_ctx, total_teams)

    home_attack, home_defense = _team_style_adjustment(fixture.home)
    away_attack, away_defense = _team_style_adjustment(fixture.away)

    home_rating *= _clamp(home_attack, 0.85, 1.20)
    away_rating *= _clamp(away_attack, 0.85, 1.20)
    home_rating *= 1.0 / _clamp(away_defense, 0.85, 1.20)
    away_rating *= 1.0 / _clamp(home_defense, 0.85, 1.20)

    season_key = _season_key(fixture)

    rng = random.Random(
        _seed_int(fixture.id, season_key, fixture.home, fixture.away, "odds")
    )

    home_prob, draw_prob, away_prob = _outcome_probabilities(home_rating, away_rating, rng)
    expected_goals = _expected_goals(home_rating, away_rating, rng)

    over15_prob = _clamp(
        poisson_over_probability(expected_goals, 1) + rng.uniform(-0.02, 0.02),
        0.22,
        0.92,
    )
    over25_prob = _clamp(
        poisson_over_probability(expected_goals, 2) + rng.uniform(-0.02, 0.02),
        0.10,
        over15_prob - 0.06,
    )
    under15_prob = _clamp(1.0 - over15_prob, 0.08, 0.78)
    under25_prob = _clamp(1.0 - over25_prob, 0.08, 0.90)

    btts_yes_prob = _clamp(
        (over15_prob * 0.65) + (expected_goals - 2.0) * 0.10 + rng.uniform(-0.03, 0.03),
        0.22,
        0.70,
    )
    btts_no_prob = _clamp(1.0 - btts_yes_prob, 0.30, 0.78)

    odds = Odds(
        match_id=fixture.id,
        home=prob_to_odds(home_prob),
        draw=prob_to_odds(draw_prob),
        away=prob_to_odds(away_prob),
        over15=prob_to_odds(over15_prob),
        under15=prob_to_odds(under15_prob),
        over25=prob_to_odds(over25_prob),
        under25=prob_to_odds(under25_prob),
        btts_yes=prob_to_odds(btts_yes_prob),
        btts_no=prob_to_odds(btts_no_prob),
    )
    odds = apply_rtp_to_odds(odds)
    odds = apply_market_deductions(odds)
    return odds


def generate_round_robin(teams):
    teams = list(teams)

    if len(teams) % 2:
        teams.append(None)

    n = len(teams)
    rounds = []

    for r in range(n - 1):
        pairs = []

        for i in range(n // 2):
            home = teams[i]
            away = teams[n - 1 - i]

            if home and away:
                pairs.append((home, away) if r % 2 == 0 else (away, home))

        rounds.append(pairs)

        # rotate teams
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]

    second_half = [[(away, home) for home, away in rnd] for rnd in rounds]

    return (rounds + second_half)[:TOTAL_ROUNDS]


def generate_full_season():
    with app.app_context():
        try:
            # Block if fixtures still active
            active_fixture = (
                db.session.query(Fixture.id)
                .filter(Fixture.status.in_([STATUS_SCHEDULED, STATUS_OPEN, STATUS_RUNNING]))
                .first()
            )

            if active_fixture:
                logger.warning("Active season in progress — skipping generation")
                return

            # Current season is the one we are generating now
            current_season = get_current_season()
            previous_season = current_season - 1
            team_context, total_teams = build_previous_season_context(previous_season, session=db.session)

            teams = list(TEAMS.keys())
            schedule = generate_round_robin(teams)

            base_time = now_utc().replace(second=0, microsecond=0) + timedelta(seconds=10)

            all_fixtures = []

            # ---------------- CREATE FIXTURES ----------------
            for round_id, matches in enumerate(schedule, start=1):
                round_start = base_time + timedelta(
                    seconds=(round_id - 1) * ROUND_INTERVAL
                )

                for home, away in matches:
                    f = Fixture(
                        home=home,
                        away=away,
                        status=STATUS_SCHEDULED,
                        round=round_id,
                        season_id=current_season,
                        open_time=round_start,
                        start_time=round_start + timedelta(seconds=BETTING_TIME),
                        end_time=round_start + timedelta(
                            seconds=BETTING_TIME + MATCH_SIM_SECONDS
                        ),
                    )
                    all_fixtures.append(f)

            db.session.add_all(all_fixtures)
            db.session.flush()

            # ---------------- GENERATE ODDS ----------------
            odds_objects = []

            for f in all_fixtures:
                try:
                    odds = generate_virtual_odds(
                        f,
                        team_context=team_context,
                        total_teams=total_teams,
                    )
                    odds_objects.append(odds)
                except Exception:
                    logger.exception(
                        "Failed odds for fixture %s vs %s", f.home, f.away
                    )

            if odds_objects:
                db.session.add_all(odds_objects)

            # ✅ SINGLE COMMIT (atomic)
            db.session.commit()

            logger.info(
                "✅ Season %s generated: %d rounds | %d fixtures",
                current_season,
                len(set(f.round for f in all_fixtures)),
                len(all_fixtures),
            )

            # Move to next season AFTER generation
            advance_season()

        except Exception:
            logger.exception("❌ Season generation failed")
            db.session.rollback()


def generate_event_for_match(match, session, emit_update_callback=None, now_dt=None):
    """
    Backward-compatible helper for generating a single live event.
    """
    try:
        if (match.event_count or 0) >= MAX_EVENTS_PER_MATCH:
            return

        minute = random.randint(1, 90)
        rng = random.Random(
            _seed_int(match.id, match.event_count or 0, minute, "event")
        )
        team = rng.choice([match.home, match.away])
        roll = rng.random()

        if roll < 0.08:
            evt_type = "GOAL"
            desc = f"⚽ {minute}' GOAL! {team} scores!"
            _apply_goal_event(match, team)
        elif roll < 0.15:
            evt_type = "RED"
            desc = f"🟥 {minute}' Red card for {team}"
        elif roll < 0.25:
            evt_type = "YELLOW"
            desc = f"🟨 {minute}' Yellow card for {team}"
        elif roll < 0.35:
            evt_type = "PENALTY"
            desc = f"🟦 {minute}' Penalty awarded to {team}"
        elif roll < 0.48:
            evt_type = "SHOT"
            desc = f"🎯 {minute}' Shot on target by {team}"
        elif roll < 0.60:
            evt_type = "CORNER"
            desc = f"🚩 {minute}' Corner for {team}"
        elif roll < 0.72:
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


def _record_simulation_metrics(match):
    home = match.home_score or 0
    away = match.away_score or 0
    total = home + away

    row = {
        "total_goals": total,
        "draw": int(home == away),
        "over25": int(total >= 3),
        "btts": int(home > 0 and away > 0),
        "home_goals": home,
        "away_goals": away,
    }

    with analytics_lock:
        simulation_history.append(row)
        n = len(simulation_history)
        avg_goals = sum(x["total_goals"] for x in simulation_history) / n
        draw_rate = sum(x["draw"] for x in simulation_history) / n
        over25_rate = sum(x["over25"] for x in simulation_history) / n
        btts_rate = sum(x["btts"] for x in simulation_history) / n

    logger.info(
        "[analytics] last=%d avg_goals=%.2f draw=%.1f%% over2.5=%.1f%% btts=%.1f%%",
        n,
        avg_goals,
        draw_rate * 100.0,
        over25_rate * 100.0,
        btts_rate * 100.0,
    )


def simulate_match(match_id, emit_update_callback=None):
    """
    Simulate a single match from start to finish.

    Events are emitted over the simulated match window, with pacing that makes
    the match feel live rather than instantaneous.
    """
    logger.info("[simulate_task] Starting simulation for match %s", match_id)
    SessionMaker = get_session_local()

    match_snapshot = None
    started_here = False

    try:
        with app.app_context():
            with match_lock(match_id):
                with SessionMaker() as session:
                    match = session.query(Fixture).filter(Fixture.id == match_id).first()
                    if not match:
                        return

                    if getattr(match, "is_simulating", False):
                        logger.warning("Match %s already simulating — skipping", match_id)
                        return

                    if match.status not in (STATUS_OPEN, STATUS_RUNNING):
                        return

                    match.is_simulating = True
                    match.status = STATUS_RUNNING
                    session.add(match)
                    safe_commit(session)
                    started_here = True

                    current_season = _get_attr_or_key(match, "season_id", None) or _get_attr_or_key(match, "season", None)
                    previous_season = (current_season - 1) if current_season else None
                    team_context, total_teams = build_previous_season_context(previous_season, session=session)

                    home_rating, away_rating = _match_strengths(
                        match,
                        team_context=team_context,
                        total_teams=total_teams,
                    )

                    odds_row = session.query(Odds).filter(Odds.match_id == match.id).first()
                    market_probs = _odds_to_normalized_probs(odds_row)

                    match_snapshot = {
                        "id": match.id,
                        "home": match.home,
                        "away": match.away,
                        "home_score": match.home_score or 0,
                        "away_score": match.away_score or 0,
                        "event_count": match.event_count or 0,
                        "start_time": to_utc(match.start_time) or now_utc(),
                        "end_time": to_utc(match.end_time),
                        "season_key": _season_key(match),
                        "home_rating": home_rating,
                        "away_rating": away_rating,
                        "market_probs": market_probs,
                    }

        if not match_snapshot:
            return

        home_rating = match_snapshot["home_rating"]
        away_rating = match_snapshot["away_rating"]
        season_key = match_snapshot["season_key"]
        market_probs = match_snapshot["market_probs"]

        outcome_rng = random.Random(
            _seed_int(
                match_snapshot["id"],
                season_key,
                match_snapshot["home"],
                match_snapshot["away"],
                "outcome",
            )
        )
        model_home_prob, model_draw_prob, model_away_prob = _outcome_probabilities(
            home_rating, away_rating, outcome_rng
        )
        home_prob, draw_prob, away_prob = _blend_three_prob_sets(
            (model_home_prob, model_draw_prob, model_away_prob),
            market_probs=market_probs,
            market_weight=0.45,
        )

        expected_goals = _expected_goals(home_rating, away_rating, outcome_rng)
        outcome = _pick_outcome(outcome_rng, home_prob, draw_prob, away_prob)
        final_home, final_away = _pick_scoreline(
            outcome_rng,
            outcome,
            expected_goals,
            home_rating,
            away_rating,
        )

        event_rng = random.Random(
            _seed_int(
                match_snapshot["id"],
                season_key,
                match_snapshot["home"],
                match_snapshot["away"],
                "events",
            )
        )
        event_plan = _build_event_plan(
            match_snapshot,
            final_home,
            final_away,
            expected_goals,
            event_rng,
        )

        start_dt = match_snapshot["start_time"]
        end_dt = match_snapshot["end_time"] or (
            start_dt + timedelta(seconds=MATCH_SIM_SECONDS)
        )
        hard_end = start_dt + timedelta(seconds=MATCH_SIM_TIMEOUT_SECONDS)
        sim_end = min(end_dt, hard_end)

        with SessionMaker() as session:
            for item in event_plan:
                if shutdown_flag.is_set():
                    break

                event_dt = _event_timestamp_for_minute(start_dt, sim_end, item["minute"])
                if not _wait_until(event_dt):
                    break

                match_live = session.query(Fixture).filter(Fixture.id == match_id).first()
                if not match_live or match_live.status == STATUS_FINISHED:
                    break

                minute = item["minute"]
                team = item["team"]
                evt_type = item["type"]
                description = item["description"]

                if evt_type == "GOAL":
                    _apply_goal_event(match_live, team)

                event = Event(
                    match_id=match_live.id,
                    minute=minute,
                    team=team,
                    type=evt_type,
                    description=description,
                )
                session.add(event)

                match_live.event_count = (match_live.event_count or 0) + 1
                session.add(match_live)
                safe_commit(session)

                if emit_update_callback:
                    emit_update_callback(match_live)

                if SIM_MIN_EVENT_GAP_SECONDS > 0:
                    shutdown_flag.wait(SIM_MIN_EVENT_GAP_SECONDS)

            if not shutdown_flag.is_set():
                match_locked = session.query(Fixture).filter(Fixture.id == match_id).first()
                if match_locked and match_locked.status != STATUS_FINISHED:
                    match_locked.home_score = final_home
                    match_locked.away_score = final_away
                    match_locked.end_time = sim_end
                    match_locked.status = STATUS_FINISHED
                    match_locked.is_simulating = False
                    session.add(match_locked)
                    safe_commit(session)

                    try:
                        settlement_executor.submit(_settle_virtual_bets_with_context, match_id)
                    except Exception:
                        logger.exception("Failed to queue settlement for match %s", match_id)

                    _record_simulation_metrics(match_locked)

                if SIM_POST_MATCH_PAUSE_SECONDS > 0:
                    shutdown_flag.wait(SIM_POST_MATCH_PAUSE_SECONDS)

    except Exception:
        logger.exception("Simulation error %s", match_id)

    finally:
        try:
            if started_here:
                with match_lock(match_id):
                    with SessionMaker() as session:
                        cleanup_match = (
                            session.query(Fixture).filter(Fixture.id == match_id).first()
                        )
                        if cleanup_match and cleanup_match.is_simulating:
                            cleanup_match.is_simulating = False
                            session.add(cleanup_match)
                            safe_commit(session)
        except Exception:
            logger.exception("Failed to clear simulation flag for match %s", match_id)
