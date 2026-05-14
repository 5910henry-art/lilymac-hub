# engine.py
import random
import math

from config import (
    ELO_START_RATING,
    ELO_K_FACTOR,
    HOME_ADVANTAGE_ELO,
    BASE_HOME_GOALS,
    BASE_AWAY_GOALS,
    ATTACK_DEFENSE_WEIGHT,
    MATCH_NOISE_STD,
    MAX_GOALS_PER_TEAM,
    TEAM_STYLE,
    STYLE_MULTIPLIERS,
    TEAMS,
    TEAM_ALIASES,
)
from bookmarks import build_bookmarks, refresh_bookmarks


# ==============================
# TEAM STATE STORAGE
# ==============================

class Team:
    def __init__(self, name):
        self.name = name
        self.elo = ELO_START_RATING
        self.goals_for = 0
        self.goals_against = 0
        self.played = 0
        self.wins = 0
        self.draws = 0
        self.losses = 0

    @property
    def points(self):
        return (self.wins * 3) + self.draws


teams = {name: Team(name) for name in TEAMS}


# Build the first snapshot cache
build_bookmarks(teams)


# ==============================
# TEAM NAME HELPERS
# ==============================

def _normalize(name):
    return "".join(ch for ch in name.lower() if ch.isalnum())


def normalize_team_name(name):
    cleaned = _normalize(name)
    return TEAM_ALIASES.get(cleaned, name)


def resolve_team_name(name):
    canonical = normalize_team_name(name)
    if canonical not in teams:
        raise KeyError(f"Unknown team: {name}")
    return canonical


# ==============================
# STYLE HELPERS
# ==============================

def get_style(team_name):
    team_name = resolve_team_name(team_name)
    return TEAM_STYLE.get(team_name, "balanced")


def style_multiplier(team_name):
    style = get_style(team_name)
    return STYLE_MULTIPLIERS.get(style, STYLE_MULTIPLIERS["balanced"])


# ==============================
# POISSON GOAL GENERATOR
# ==============================

def clamp_goals(x):
    return max(0, min(int(round(x)), MAX_GOALS_PER_TEAM))


def poisson(lmbda):
    L = math.exp(-lmbda)
    k = 0
    p = 1.0

    while p > L:
        k += 1
        p *= random.random()

    return k - 1


# ==============================
# EXPECTED GOALS MODEL
# ==============================

def expected_goals(home, away):
    home = resolve_team_name(home)
    away = resolve_team_name(away)

    home_team = teams[home]
    away_team = teams[away]

    style_h = style_multiplier(home)
    style_a = style_multiplier(away)

    home_played = max(1, home_team.played)
    away_played = max(1, away_team.played)

    home_gf_pg = home_team.goals_for / home_played
    home_ga_pg = home_team.goals_against / home_played
    away_gf_pg = away_team.goals_for / away_played
    away_ga_pg = away_team.goals_against / away_played

    elo_diff = (home_team.elo - away_team.elo) + HOME_ADVANTAGE_ELO
    strength = elo_diff * ATTACK_DEFENSE_WEIGHT / 100.0

    home_attack = 1.0 + (home_gf_pg / 1.7) + ((home_team.elo - 1500) / 1100.0)
    away_attack = 1.0 + (away_gf_pg / 1.7) + ((away_team.elo - 1500) / 1100.0)

    home_defense = 1.15 - (home_ga_pg / 2.3) + ((home_team.elo - 1500) / 1400.0)
    away_defense = 1.15 - (away_ga_pg / 2.3) + ((away_team.elo - 1500) / 1400.0)

    home_xg = BASE_HOME_GOALS + strength
    away_xg = BASE_AWAY_GOALS - strength

    home_xg *= home_attack * away_defense * style_h["goal_modifier"] * style_h["attack_boost"]
    away_xg *= away_attack * home_defense * style_a["goal_modifier"] * style_a["attack_boost"]

    home_xg += random.gauss(0, MATCH_NOISE_STD) * 0.10 * style_h["variance"]
    away_xg += random.gauss(0, MATCH_NOISE_STD) * 0.10 * style_a["variance"]

    return max(0.10, home_xg), max(0.10, away_xg)


# ==============================
# SIMULATE MATCH
# ==============================

def simulate_match(home, away):
    home = resolve_team_name(home)
    away = resolve_team_name(away)

    home_xg, away_xg = expected_goals(home, away)

    home_goals = clamp_goals(poisson(home_xg))
    away_goals = clamp_goals(poisson(away_xg))

    return home_goals, away_goals


# ==============================
# ELO UPDATE SYSTEM
# ==============================

def expected_result(elo_a, elo_b):
    return 1 / (1 + 10 ** ((elo_b - elo_a) / 400.0))


def update_elo(home, away, home_goals, away_goals):
    home = resolve_team_name(home)
    away = resolve_team_name(away)

    home_team = teams[home]
    away_team = teams[away]

    exp_home = expected_result(home_team.elo, away_team.elo)

    if home_goals > away_goals:
        score_home = 1.0
    elif home_goals < away_goals:
        score_home = 0.0
    else:
        score_home = 0.5

    delta = ELO_K_FACTOR * (score_home - exp_home)

    home_team.elo += delta
    away_team.elo -= delta


# ==============================
# PLAY MATCH
# ==============================

def play_match(home, away, verbose=True):
    home = resolve_team_name(home)
    away = resolve_team_name(away)

    hg, ag = simulate_match(home, away)
    update_elo(home, away, hg, ag)

    home_team = teams[home]
    away_team = teams[away]

    home_team.goals_for += hg
    home_team.goals_against += ag
    away_team.goals_for += ag
    away_team.goals_against += hg

    home_team.played += 1
    away_team.played += 1

    if hg > ag:
        home_team.wins += 1
        away_team.losses += 1
    elif hg < ag:
        away_team.wins += 1
        home_team.losses += 1
    else:
        home_team.draws += 1
        away_team.draws += 1

    if verbose:
        print(f"{home} {hg} - {ag} {away}")

    refresh_bookmarks(teams)

    return hg, ag


def play_round(fixtures):
    for home, away in fixtures:
        play_match(home, away)


# ==============================
# TABLE GENERATOR
# ==============================

def get_table():
    table = []

    for t in teams.values():
        table.append({
            "team": t.name,
            "played": t.played,
            "wins": t.wins,
            "draws": t.draws,
            "losses": t.losses,
            "gf": t.goals_for,
            "ga": t.goals_against,
            "gd": t.goals_for - t.goals_against,
            "points": t.points,
            "elo": round(t.elo, 1),
        })

    return sorted(table, key=lambda x: (x["points"], x["gd"], x["gf"]), reverse=True)


# ==============================
# RESET SEASON
# ==============================

def reset():
    for t in teams.values():
        t.elo = ELO_START_RATING
        t.goals_for = 0
        t.goals_against = 0
        t.played = 0
        t.wins = 0
        t.draws = 0
        t.losses = 0

    refresh_bookmarks(teams)
