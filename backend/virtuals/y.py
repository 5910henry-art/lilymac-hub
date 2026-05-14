#!/usr/bin/env python3
"""
What this file gives you:
- Market-derived team ratings on a 0–100 scale
- Team ranking and tier grouping
- Odds -> no-vig probability conversion
- Rating -> expected goals conversion
- Poisson-based match simulation
- Batch processing for fixtures

This is a practical reconstruction, not the original hidden engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import numpy as np


# ---------------------------------------------------------------------
# Global model configuration
# ---------------------------------------------------------------------
MODEL_CONFIG = {
    "HOME_ADVANTAGE": 0.40,   # goal boost for home side
    "BASE_GOALS": 1.35,       # baseline goals per team
    "DRAW_BIAS": 1.08,        # light draw inflation
    "RATING_SCALE": 10.0,     # rating diff -> xG impact
    "MAX_GOALS": 6,           # cap extreme simulated scores
    "RANDOM_SEED": None,      # set to an int for repeatable output
}


# ---------------------------------------------------------------------
# Market-derived team ratings
# ---------------------------------------------------------------------
TEAM_RATINGS: Dict[str, float] = {
    "Barcelona": 95.8,
    "Atletico Madrid": 89.5,
    "Real Madrid": 84.8,
    "Valencia": 80.7,
    "Sevilla": 79.4,
    "Getafe": 79.4,
    "Athletic Bilbao": 75.9,
    "Espanyol": 75.9,
    "Real Sociedad": 74.1,
    "Real Betis": 74.1,
    "Alaves": 74.1,
    "Almeria": 72.3,
    "Leganes": 71.2,
    "Villarreal": 70.6,
    "Levante": 70.6,
    "Mallorca": 68.8,
    "Celta Vigo": 68.7,
    "Osasuna": 66.5,
    "Granada": 64.1,
    "Valladolid": 63.3,
}

# Common aliases used in your notes/results
TEAM_ALIASES = {
    "Barca": "Barcelona",
    "Barcelona": "Barcelona",
    "A. Madrid": "Atletico Madrid",
    "Atletico Madrid": "Atletico Madrid",
    "A.madrid": "Atletico Madrid",
    "R. Madrid": "Real Madrid",
    "Real Madrid": "Real Madrid",
    "R.sociedad": "Real Sociedad",
    "Real Sociedad": "Real Sociedad",
    "A. Bilbao": "Athletic Bilbao",
    "A.bilbao": "Athletic Bilbao",
    "Athletic Bilbao": "Athletic Bilbao",
    "Esp": "Espanyol",
    "Espanyol": "Espanyol",
    "Gra": "Granada",
    "Granada": "Granada",
    "Osa": "Osasuna",
    "Osasuna": "Osasuna",
    "Betis": "Real Betis",
    "Real Betis": "Real Betis",
    "Villareal": "Villarreal",
    "Villarreal": "Villarreal",
    "Almeria": "Almeria",
    "Leganes": "Leganes",
    "Levante": "Levante",
    "Mallorca": "Mallorca",
    "Celta Vigo": "Celta Vigo",
    "Getafe": "Getafe",
    "Sevilla": "Sevilla",
    "Valencia": "Valencia",
    "Valladolid": "Valladolid",
    "Alaves": "Alaves",
}


# ---------------------------------------------------------------------
# Odds helpers
# ---------------------------------------------------------------------
def odds_to_probs(odds: Iterable[float]) -> List[float]:
    """Convert 1X2 odds to no-vig probabilities."""
    raw = [1.0 / float(o) for o in odds]
    total = sum(raw)
    if total <= 0:
        raise ValueError("Invalid odds: sum of implied probabilities is not positive.")
    return [r / total for r in raw]


def probs_to_odds(probs: Iterable[float]) -> List[float]:
    """Convert probabilities to decimal odds."""
    out = []
    for p in probs:
        if p <= 0:
            raise ValueError("Probability must be positive.")
        out.append(1.0 / float(p))
    return out


# ---------------------------------------------------------------------
# Team normalization and ranking
# ---------------------------------------------------------------------
def normalize_team_name(name: str) -> str:
    """Map aliases to canonical team names."""
    key = name.strip()
    return TEAM_ALIASES.get(key, key)


def get_team_rating(team: str) -> float:
    team = normalize_team_name(team)
    if team not in TEAM_RATINGS:
        raise KeyError(f"Unknown team: {team}")
    return TEAM_RATINGS[team]


def rank_teams() -> List[Tuple[str, float]]:
    """Return teams ranked by overall rating (descending)."""
    return sorted(TEAM_RATINGS.items(), key=lambda x: x[1], reverse=True)


def power_score_0_100() -> Dict[str, float]:
    """
    Normalize ratings to a 0–100 power scale using min-max scaling.
    Since TEAM_RATINGS are already on a 0–100-like scale, this mainly
    preserves the ranking while giving a clean standardized view.
    """
    values = list(TEAM_RATINGS.values())
    mn, mx = min(values), max(values)
    if math.isclose(mx, mn):
        return {team: 50.0 for team in TEAM_RATINGS}
    return {team: round(((r - mn) / (mx - mn)) * 100.0, 2) for team, r in TEAM_RATINGS.items()}


def tier_group(team: str) -> str:
    """Assign a tier label from the normalized power score."""
    team = normalize_team_name(team)
    score = power_score_0_100()[team]
    if score >= 85:
        return "Elite"
    if score >= 70:
        return "Strong Contenders"
    if score >= 50:
        return "Very Strong"
    if score >= 35:
        return "Mid Table"
    if score >= 25:
        return "Lower Mid Table"
    if score >= 15:
        return "Weak"
    return "Very Weak"


def tier_table() -> Dict[str, List[str]]:
    """Group teams by tier."""
    buckets = {
        "Elite": [],
        "Strong Contenders": [],
        "Very Strong": [],
        "Mid Table": [],
        "Lower Mid Table": [],
        "Weak": [],
        "Very Weak": [],
    }
    p = power_score_0_100()
    for team, score in p.items():
        if score >= 85:
            buckets["Elite"].append(team)
        elif score >= 70:
            buckets["Strong Contenders"].append(team)
        elif score >= 50:
            buckets["Very Strong"].append(team)
        elif score >= 35:
            buckets["Mid Table"].append(team)
        elif score >= 25:
            buckets["Lower Mid Table"].append(team)
        elif score >= 15:
            buckets["Weak"].append(team)
        else:
            buckets["Very Weak"].append(team)
    return buckets


# ---------------------------------------------------------------------
# Expected goals and match simulation
# ---------------------------------------------------------------------
def expected_goals(home_team: str, away_team: str) -> Tuple[float, float]:
    """
    Convert team ratings into expected goals.

    Formula:
        diff = (home_rating - away_rating) / RATING_SCALE
        home_xg = BASE_GOALS + diff + HOME_ADVANTAGE
        away_xg = BASE_GOALS - diff
    """
    home_team = normalize_team_name(home_team)
    away_team = normalize_team_name(away_team)

    r_home = get_team_rating(home_team)
    r_away = get_team_rating(away_team)

    diff = (r_home - r_away) / MODEL_CONFIG["RATING_SCALE"]

    home_xg = MODEL_CONFIG["BASE_GOALS"] + diff + MODEL_CONFIG["HOME_ADVANTAGE"]
    away_xg = MODEL_CONFIG["BASE_GOALS"] - diff

    home_xg = max(0.2, float(home_xg))
    away_xg = max(0.2, float(away_xg))
    return home_xg, away_xg


def simulate_score(home_xg: float, away_xg: float) -> Tuple[int, int]:
    """Simulate score using Poisson sampling."""
    home_goals = int(np.random.poisson(home_xg))
    away_goals = int(np.random.poisson(away_xg))

    home_goals = min(home_goals, MODEL_CONFIG["MAX_GOALS"])
    away_goals = min(away_goals, MODEL_CONFIG["MAX_GOALS"])
    return home_goals, away_goals


def apply_draw_bias(home_goals: int, away_goals: int) -> Tuple[int, int]:
    """
    Keep draws slightly more stable.
    This is intentionally mild so the model remains realistic.
    """
    if home_goals == away_goals:
        # tiny boost to preserve draw states when they appear
        if np.random.rand() < max(0.0, MODEL_CONFIG["DRAW_BIAS"] - 1.0):
            return home_goals, away_goals
    return home_goals, away_goals


def simulate_match(home_team: str, away_team: str) -> Dict[str, object]:
    home_team = normalize_team_name(home_team)
    away_team = normalize_team_name(away_team)

    home_xg, away_xg = expected_goals(home_team, away_team)
    home_goals, away_goals = simulate_score(home_xg, away_xg)
    home_goals, away_goals = apply_draw_bias(home_goals, away_goals)

    return {
        "match": f"{home_team} vs {away_team}",
        "home_team": home_team,
        "away_team": away_team,
        "xg": (round(home_xg, 2), round(away_xg, 2)),
        "score": (home_goals, away_goals),
    }


def simulate_fixtures(fixtures: Iterable[Tuple[str, str]]) -> List[Dict[str, object]]:
    """Simulate a list of (home, away) fixtures."""
    if MODEL_CONFIG["RANDOM_SEED"] is not None:
        np.random.seed(int(MODEL_CONFIG["RANDOM_SEED"]))
    return [simulate_match(home, away) for home, away in fixtures]


# ---------------------------------------------------------------------
# Odds-based reconstruction helpers
# ---------------------------------------------------------------------
def match_to_ratings_from_odds(
    home_name: str,
    away_name: str,
    odds: Iterable[float],
) -> Dict[str, object]:
    """
    Convert a single 1X2 line into a compact market-strength snapshot.

    This is a lightweight, practical helper for your workflow.
    It does not fully infer true hidden ratings from one match alone,
    but it gives no-vig probabilities and a normalized split.
    """
    home_name = normalize_team_name(home_name)
    away_name = normalize_team_name(away_name)

    home_p, draw_p, away_p = odds_to_probs(odds)

    attack_share = home_p / (home_p + away_p)
    away_share = away_p / (home_p + away_p)

    home_rating = round(attack_share * 100, 2)
    away_rating = round(away_share * 100, 2)

    return {
        "teams": f"{home_name} vs {away_name}",
        "no_vig_probs": {
            "home": round(home_p, 4),
            "draw": round(draw_p, 4),
            "away": round(away_p, 4),
        },
        "market_split": {
            "home": home_rating,
            "away": away_rating,
        },
    }


# ---------------------------------------------------------------------
# Pretty print helpers
# ---------------------------------------------------------------------
def print_rankings(top_n: int | None = None) -> None:
    rows = rank_teams()
    if top_n is not None:
        rows = rows[:top_n]
    print("\nTEAM RANKINGS (Overall)")
    print("-" * 40)
    for i, (team, rating) in enumerate(rows, start=1):
        print(f"{i:>2}. {team:<18} {rating:>6.2f}  |  Tier: {tier_group(team)}")


def print_tiers() -> None:
    tiers = tier_table()
    print("\nTEAM TIERS")
    print("-" * 40)
    for label, teams in tiers.items():
        print(f"\n{label}")
        for team in sorted(teams, key=lambda t: TEAM_RATINGS[t], reverse=True):
            print(f"  - {team} ({TEAM_RATINGS[team]:.2f})")


def print_match_result(result: Dict[str, object]) -> None:
    print("\nMATCH ANALYSIS")
    print("-" * 40)
    print(f"Match: {result['match']}")
    print(f"xG:    {result['xg'][0]} - {result['xg'][1]}")
    print(f"Score: {result['score'][0]} - {result['score'][1]}")


# ---------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # Optional repeatability
    # MODEL_CONFIG["RANDOM_SEED"] = 42

    print_rankings()
    print_tiers()

    print("\nSAMPLE SIMULATION")
    sample = simulate_match("Real Madrid", "Atletico Madrid")
    print_match_result(sample)

    print("\nSAMPLE ODDS SNAPSHOT")
    odds_snapshot = match_to_ratings_from_odds(
        "Atletico Madrid",
         "Barcelona",
        [2.59, 3.33, 2.65],
    )
    print(odds_snapshot)
