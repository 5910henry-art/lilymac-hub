# sim_helpers.py

import hashlib
import math
from collections import defaultdict
from datetime import datetime

from virtuals.config import app, db
from virtuals.config_settings import STATUS_FINISHED
from virtuals.model import Fixture


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

    normalized = (total_teams - rank) / (total_teams - 1)
    return _clamp((normalized - 0.5) * 6.0, -3.0, 3.0)


def _form_bonus(form):
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


def _team_style_adjustment(team, team_styles=None):
    team_styles = team_styles or {}
    style = team_styles.get(team) or {}
    attack = float(style.get("attack", 1.0))
    defense = float(style.get("defense", 1.0))
    return attack, defense


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
