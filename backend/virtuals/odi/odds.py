# odds.py
import argparse

from engine import teams, poisson, resolve_team_name
from bookmarks import get_bookmark, build_bookmarks, BOOKMARKS
from config import BASE_HOME_GOALS, BASE_AWAY_GOALS, HOME_ADVANTAGE_ELO


# Ensure bookmarks exist if this module is run directly first
if not BOOKMARKS:
    build_bookmarks(teams)


# ==============================
# RATING HELPERS
# ==============================

def home_advantage_factor():
    return 1.0 + (HOME_ADVANTAGE_ELO / 1000.0)


def expected_goals_market(home, away):
    home = resolve_team_name(home)
    away = resolve_team_name(away)

    h = get_bookmark(home)
    a = get_bookmark(away)

    # Use cached team rating layer directly
    home_xg = BASE_HOME_GOALS * h["attack"] * a["defense"] * home_advantage_factor()
    away_xg = BASE_AWAY_GOALS * a["attack"] * h["defense"]

    # Secondary adjustment from strength gap
    elo_gap = (h["elo"] - a["elo"] + HOME_ADVANTAGE_ELO) / 6000.0
    home_xg *= (1.0 + elo_gap)
    away_xg *= (1.0 - elo_gap)

    home_xg = max(0.20, min(home_xg, 4.50))
    away_xg = max(0.20, min(away_xg, 4.50))

    return home_xg, away_xg


# ==============================
# SIMULATION SAMPLING
# ==============================

def simulate_match_distribution(home, away, sims=5000):
    home_xg, away_xg = expected_goals_market(home, away)

    results = {
        "home_win": 0,
        "draw": 0,
        "away_win": 0,
        "over25": 0,
        "under25": 0,
        "scorelines": {},
    }

    for _ in range(sims):
        hg = poisson(home_xg)
        ag = poisson(away_xg)

        if hg > ag:
            results["home_win"] += 1
        elif hg == ag:
            results["draw"] += 1
        else:
            results["away_win"] += 1

        if hg + ag > 2:
            results["over25"] += 1
        else:
            results["under25"] += 1

        key = (hg, ag)
        results["scorelines"][key] = results["scorelines"].get(key, 0) + 1

    return results, sims, home_xg, away_xg


# ==============================
# CONVERT PROBABILITY -> ODDS
# ==============================

def prob_to_odds(p):
    if p <= 0:
        return 0
    return round(1 / p, 2)


# ==============================
# MAIN ODDS ENGINE
# ==============================

def generate_odds(home, away, sims=5000):
    results, total, home_xg, away_xg = simulate_match_distribution(home, away, sims)

    p_home = results["home_win"] / total
    p_draw = results["draw"] / total
    p_away = results["away_win"] / total

    p_over = results["over25"] / total
    p_under = results["under25"] / total

    odds = {
        "teams": {
            "home": resolve_team_name(home),
            "away": resolve_team_name(away),
        },
        "xg": {
            "home": round(home_xg, 3),
            "away": round(away_xg, 3),
        },
        "1X2": {
            "home_win": prob_to_odds(p_home),
            "draw": prob_to_odds(p_draw),
            "away_win": prob_to_odds(p_away),
        },
        "probabilities": {
            "home": round(p_home, 3),
            "draw": round(p_draw, 3),
            "away": round(p_away, 3),
        },
        "over_under_2_5": {
            "over": prob_to_odds(p_over),
            "under": prob_to_odds(p_under),
            "p_over": round(p_over, 3),
            "p_under": round(p_under, 3),
        },
    }

    top_scores = sorted(
        results["scorelines"].items(),
        key=lambda x: x[1],
        reverse=True,
    )[:5]

    odds["correct_score_top"] = [
        {
            "score": f"{k[0]}-{k[1]}",
            "prob": round(v / total, 4),
            "odds": prob_to_odds(v / total),
        }
        for k, v in top_scores
    ]

    return odds


# ==============================
# PRETTY PRINT
# ==============================

def print_odds(home, away, sims=5000):
    odds = generate_odds(home, away, sims=sims)

    print(f"\n⚽ {odds['teams']['home']} vs {odds['teams']['away']} - ODDS\n")
    print(f"Expected Goals: {odds['xg']['home']} - {odds['xg']['away']}\n")

    print("1X2 Odds:")
    print(f"Home Win: {odds['1X2']['home_win']}")
    print(f"Draw:     {odds['1X2']['draw']}")
    print(f"Away Win: {odds['1X2']['away_win']}")

    print("\nOver/Under 2.5:")
    print(f"Over 2.5:  {odds['over_under_2_5']['over']}")
    print(f"Under 2.5: {odds['over_under_2_5']['under']}")

    print("\nTop Correct Scores:")
    for s in odds["correct_score_top"]:
        print(f"{s['score']} | Prob: {s['prob']} | Odds: {s['odds']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("home", nargs="?", default="Real Madrid")
    parser.add_argument("away", nargs="?", default="Barca")
    parser.add_argument("--sims", type=int, default=5000)
    args = parser.parse_args()

    print_odds(args.home, args.away, sims=args.sims)
