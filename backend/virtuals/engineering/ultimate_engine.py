# ultimate_engine.py

import math
import re
from collections import defaultdict

from reverse_engine_ai import ReverseEngineAI, parse_matches


# -----------------------------
# DATA MODEL
# -----------------------------
class Game:
    def __init__(self, home, away, odds, score):
        self.home = home
        self.away = away
        self.odds = odds
        self.home_goals, self.away_goals = score

    def result(self):
        if self.home_goals > self.away_goals:
            return "home"
        elif self.home_goals < self.away_goals:
            return "away"
        return "draw"

    def favorite(self):
        odds_map = {
            "home": self.odds[0],
            "draw": self.odds[1],
            "away": self.odds[2],
        }
        return min(odds_map, key=odds_map.get)


# -----------------------------
# PARSING
# -----------------------------
def parse_fixtures_results(text):
    """
    Expected line format:
    Team A vs Team B | 2.10 3.30 3.60 | 1-1

    This parser is tolerant to extra spaces.
    """
    games = []

    pattern = re.compile(
        r"^(.+?)\s+vs\s+(.+?)\s*\|\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\|\s*(\d+)-(\d+)\s*$"
    )

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        m = pattern.match(line)
        if not m:
            continue

        home = m.group(1).strip()
        away = m.group(2).strip()
        odds = (float(m.group(3)), float(m.group(4)), float(m.group(5)))
        score = (int(m.group(6)), int(m.group(7)))

        games.append(Game(home, away, odds, score))

    return games


# -----------------------------
# PROBABILITY HELPERS
# -----------------------------
def poisson_pmf(k, lam):
    if lam < 0:
        return 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_1x2(lambda_home, lambda_away, max_goals=10):
    """
    Convert Poisson lambdas into 1X2 probabilities.
    Returns dict with home/draw/away probabilities.
    """
    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    home_probs = [poisson_pmf(i, lambda_home) for i in range(max_goals + 1)]
    away_probs = [poisson_pmf(j, lambda_away) for j in range(max_goals + 1)]

    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = home_probs[i] * away_probs[j]
            if i > j:
                home_win += p
            elif i < j:
                away_win += p
            else:
                draw += p

    total = home_win + draw + away_win
    if total <= 0:
        return {"home": 0.0, "draw": 0.0, "away": 0.0}

    return {
        "home": home_win / total,
        "draw": draw / total,
        "away": away_win / total,
    }


def extract_probs(pred):
    """
    Prefer proper 1X2 probabilities if lambdas exist.
    Fall back gracefully if the model output is different.
    """
    lambda_home = pred.get("lambda_home")
    lambda_away = pred.get("lambda_away")

    if lambda_home is not None and lambda_away is not None:
        return poisson_1x2(lambda_home, lambda_away)

    home = pred.get("home_prob")
    draw = pred.get("draw_prob")
    away = pred.get("away_prob")

    if home is None and "prob_home" in pred:
        home = pred.get("prob_home")
    if draw is None and "prob_draw" in pred:
        draw = pred.get("prob_draw")
    if away is None and "prob_away" in pred:
        away = pred.get("prob_away")

    probs = {
        "home": home if home is not None else 0.0,
        "draw": draw if draw is not None else 0.0,
        "away": away if away is not None else 0.0,
    }

    total = sum(probs.values())
    if total <= 0:
        return {"home": 0.0, "draw": 0.0, "away": 0.0}

    return {k: v / total for k, v in probs.items()}


def implied_probability(odd):
    if odd <= 0:
        return 0.0
    return 1.0 / odd


def ev_from_prob(prob, odd):
    return (prob * odd) - 1.0


# -----------------------------
# PATTERN ANALYSIS
# -----------------------------
def pattern_analysis(games):
    traps = []
    odds_perf = defaultdict(lambda: {"wins": 0, "total": 0})

    for g in games:
        odds = {
            "home": g.odds[0],
            "draw": g.odds[1],
            "away": g.odds[2],
        }

        actual = g.result()
        favorite = min(odds, key=odds.get)

        # Trap = favorite did not win
        if actual != favorite:
            traps.append({
                "match": f"{g.home} vs {g.away}",
                "fav": favorite,
                "result": actual,
                "odds": odds[favorite],
            })

        # Favorite odds bucket performance
        bucket = round(odds[favorite], 1)
        odds_perf[bucket]["total"] += 1
        if actual == favorite:
            odds_perf[bucket]["wins"] += 1

    perf = {
        k: round(v["wins"] / v["total"], 3)
        for k, v in odds_perf.items()
        if v["total"] > 0
    }

    return {
        "traps": traps,
        "odds_performance": perf,
    }


# -----------------------------
# BETTING / VALUE ENGINE
# -----------------------------
def analyze_fixtures(ai, fixtures):
    results = []

    for home, away, odds in fixtures:
        pred = ai.predict(home, away)
        probs = extract_probs(pred)

        side_to_index = {"home": 0, "draw": 1, "away": 2}

        scored = []
        for side in ("home", "draw", "away"):
            odd = odds[side_to_index[side]]
            model_prob = probs.get(side, 0.0)
            market_prob = implied_probability(odd)
            ev = ev_from_prob(model_prob, odd)

            # Stability-weighted ranking score
            value_score = ev * max(model_prob, 0.05)

            scored.append({
                "side": side,
                "model_prob": model_prob,
                "market_prob": market_prob,
                "ev": ev,
                "value_score": value_score,
                "odd": odd,
            })

        best = max(scored, key=lambda x: x["value_score"])

        lambda_home = pred.get("lambda_home")
        lambda_away = pred.get("lambda_away")
        draw_prob = probs.get("draw", 0.0)

        if lambda_home is not None and lambda_away is not None:
            goal_gap = abs(lambda_home - lambda_away)
        else:
            goal_gap = None

        # Tightened risk logic
        if best["side"] == "draw" or draw_prob >= 0.30:
            risk = "DRAW RISK"
        elif best["model_prob"] >= 0.62 and best["ev"] >= 0.08:
            risk = "SAFE"
        elif best["model_prob"] >= 0.52 and best["ev"] >= 0.03:
            risk = "MEDIUM"
        else:
            risk = "RISKY"

        if draw_prob >= 0.30 or (goal_gap is not None and goal_gap < 0.25):
            if risk in ("SAFE", "MEDIUM"):
                risk = "DRAW RISK"

        results.append({
            "match": f"{home} vs {away}",
            "best_bet": best["side"],
            "edge": round(best["ev"], 4),
            "prob": round(best["model_prob"], 4),
            "odds": best["odd"],
            "score": pred.get("most_likely_score", "N/A"),
            "risk": risk,
        })

    results.sort(key=lambda x: (x["edge"], x["prob"]), reverse=True)
    return results


# -----------------------------
# PRINT REPORT
# -----------------------------
def print_full_report(ai, games, fixtures):
    print("\n🧠 ENGINE PROFILE")
    print("=" * 60)
    for k, v in ai.profile.items():
        print(f"{k:25}: {v}")

    patterns = pattern_analysis(games)

    print("\n🪤 PATTERN INSIGHTS")
    print("=" * 60)
    print(f"Total traps: {len(patterns['traps'])}")

    print("\n📊 Odds Performance:")
    for k, v in sorted(patterns["odds_performance"].items()):
        print(f"{k} → {v}")

    print("\n🔥 BETTING PICKS")
    print("=" * 60)

    picks = analyze_fixtures(ai, fixtures)

    for p in picks:
        print(f"\n⚽ {p['match']}")
        print(f"👉 Bet: {p['best_bet'].upper()}")
        print(f"📊 Prob: {p['prob']}")
        print(f"📈 Edge: {p['edge']}")
        print(f"💰 Odds: {p['odds']}")
        print(f"🎯 Score: {p['score']}")
        print(f"⚠️ Risk: {p['risk']}")


# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    # TRAINING DATA
    with open("results.txt", encoding="utf-8") as f:
        raw_results = f.read()

    matches = parse_matches(raw_results)
    ai = ReverseEngineAI(seed=42).fit(matches)

    # HISTORICAL ODDS + RESULTS
    with open("fixtures_results.txt", encoding="utf-8") as f:
        raw_games = f.read()

    games = parse_fixtures_results(raw_games)

    # TODAY FIXTURES
    fixtures = [
        ("Esp", "Villareal", (2.05, 3.30, 3.65)),
        ("Getafe", "Almeria", (1.98, 3.36, 3.83)),
        ("Valencia", "Celta Vigo", (1.81, 3.54, 4.37)),
        ("Alaves", "Betis", (2.32, 3.11, 3.22)),
        ("A.madrid", "Leganes", (1.62, 3.83, 5.37)),
        ("A.bilbao", "Mallorca", (1.98, 3.36, 3.83)),
        ("Real Madrid", "Gra", (1.57, 3.95, 5.83)),
        ("Barca", "Osa", (1.40, 4.43, 8.10)),
        ("R.sociedad", "Levante", (2.15, 3.20, 3.51)),
        ("Valladolid", "Sevilla", (3.17, 3.68, 2.10)),
    ]

    # RUN FULL SYSTEM
    print_full_report(ai, games, fixtures)
