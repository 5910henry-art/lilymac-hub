# bet_scanner.py

from reverse_engine_ai import ReverseEngineAI, parse_matches
from odds_decoder import decode_odds, find_value

from typing import List, Tuple, Dict


# -----------------------------
# CONFIG (YOU CAN TUNE THIS)
# -----------------------------

MIN_EDGE = 0.05          # minimum edge (5%)
MIN_PROB = 0.40          # minimum win probability
MAX_RANDOMNESS = 0.75    # avoid chaotic matches


# -----------------------------
# FIXTURE FORMAT
# -----------------------------
# ("Home Team", "Away Team", (home_odds, draw_odds, away_odds))

Fixture = Tuple[str, str, Tuple[float, float, float]]


# -----------------------------
# CORE SCANNER
# -----------------------------

def scan_bets(ai: ReverseEngineAI, fixtures: List[Fixture]) -> List[Dict]:
    picks = []

    for home, away, odds in fixtures:
        prediction = ai.predict(home, away)
        values = find_value(prediction, odds)

        for side in ["home", "draw", "away"]:
            data = values[side]

            prob = data["model_prob"]
            edge = data["edge"]

            # filters
            if prob >= MIN_PROB and edge >= MIN_EDGE:
                picks.append({
                    "match": f"{home} vs {away}",
                    "bet": side,
                    "odds": odds[["home", "draw", "away"].index(side)],
                    "prob": prob,
                    "edge": edge,
                    "value_score": data["value_score"],
                    "prediction": prediction["most_likely_score"],
                })

    # sort by strongest edge
    picks.sort(key=lambda x: x["edge"], reverse=True)
    return picks


# -----------------------------
# PRINT RESULTS
# -----------------------------

def print_bets(picks: List[Dict]):
    print("\n🔥 STRONG VALUE BETS")
    print("=" * 60)

    if not picks:
        print("❌ No strong value bets found today.")
        return

    for p in picks:
        print(f"\n⚽ {p['match']}")
        print(f"👉 Bet: {p['bet'].upper()}")
        print(f"💰 Odds: {p['odds']}")
        print(f"📊 Model Prob: {p['prob']}")
        print(f"📈 Edge: +{p['edge']}")
        print(f"🎯 Likely Score: {p['prediction']}")


# -----------------------------
# OPTIONAL: RISK TAGGING
# -----------------------------

def tag_risk(ai: ReverseEngineAI, home: str, away: str) -> str:
    det = ai.predict(home, away)

    diff = abs(det["lambda_home"] - det["lambda_away"])

    if diff < 0.25:
        return "HIGH DRAW RISK"
    elif diff < 0.6:
        return "BALANCED"
    else:
        return "CLEAR FAVORITE"


# -----------------------------
# MAIN RUN
# -----------------------------

if __name__ == "__main__":

    # 1. LOAD TRAINING DATA
    with open("results.txt") as f:
        raw = f.read()

    matches = parse_matches(raw)

    # 2. TRAIN AI
    ai = ReverseEngineAI(seed=42).fit(matches)

    print("\n🧠 ENGINE PROFILE")
    print("=" * 60)
    for k, v in ai.profile.items():
        print(f"{k:25}: {v}")

    # 3. TODAY'S FIXTURES + ODDS
    fixtures = [
        ("Real Madrid", "Barcelona", (1.83, 3.50, 4.31)),
        ("Getafe", "Villarreal", (2.40, 3.10, 2.90)),
        ("Atletico Madrid", "Sevilla", (1.95, 3.20, 4.10)),
        ("Valencia", "Betis", (2.50, 3.00, 2.80)),
    ]

    # 4. SCAN
    picks = scan_bets(ai, fixtures)

    # 5. PRINT
    print_bets(picks)

    # 6. EXTRA INSIGHT
    print("\n🧪 MATCH RISK LEVELS")
    print("=" * 60)
    for h, a, _ in fixtures:
        print(f"{h} vs {a} → {tag_risk(ai, h, a)}")
