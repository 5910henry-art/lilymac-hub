#!/usr/bin/env python3
import argparse
import math
import json

import numpy as np

EPS = 1e-12
SMOOTH_EPS = 1e-8


# ----------------------------
# SIGMOID
# ----------------------------
def sigmoid(x):
    if x >= 0:
        z = math.exp(-x)
        return 1 / (1 + z)
    z = math.exp(x)
    return z / (1 + z)


# ----------------------------
# CORE MODEL
# ----------------------------
def predict_probs(r_home, r_away, home_adv, base_draw, draw_k, T=1.2):
    diff = (r_home + home_adv) - r_away

    p_home_core = sigmoid(diff / T)

    p_draw = base_draw * math.exp(-draw_k * abs(diff))
    p_draw = min(max(p_draw, EPS), 1.0 - EPS)

    rem = 1.0 - p_draw
    p_home = rem * p_home_core
    p_away = rem * (1.0 - p_home_core)

    p = np.array([p_home, p_draw, p_away], dtype=float)
    return p / p.sum()
# ----------------------------
# MARKET CALIBRATION
# ----------------------------
def market_calibrate(p, T, draw_boost=0.0):
    p = np.clip(p, EPS, 1.0)

    x = np.log(p) / T

    # learned market distortion
    x[1] += draw_boost

    x -= np.max(x)

    e = np.exp(x)
    return e / np.sum(e)


# ----------------------------
# ODDS HELPERS
# ----------------------------
def to_odds(probs):
    return 1 / np.clip(probs, EPS, 1.0)


def apply_overround(probs, margin):
    probs = np.clip(probs, EPS, 1.0)
    k = (1.0 + margin) / probs.sum()
    return probs * k

# ----------------------------
# MAIN
# ----------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("home")
    parser.add_argument("away")
    parser.add_argument("--margin", type=float, default=0.0)
    args = parser.parse_args()

    with open(args.model, "r", encoding="utf-8") as f:
        model = json.load(f)

    ratings = model["ratings"]
    home_adv = model["home_adv"]
    base_draw = model["base_draw"]
    draw_k = model["draw_k"]

    T = model.get("temperature", 1.0)
    draw_boost = model.get("draw_boost", 0.0)

    if args.home not in ratings or args.away not in ratings:
        print("❌ Team not found in model")
        return

    r_home = ratings[args.home]
    r_away = ratings[args.away]

    # ----------------------------
    # RAW PROBABILITIES
    # ----------------------------
    probs = predict_probs(r_home, r_away, home_adv, base_draw, draw_k)

    # ----------------------------
    # MARKET CALIBRATION
    # ----------------------------
    probs = market_calibrate(probs, T, draw_boost)

    print("\n📊 Probabilities (Market-Calibrated):")
    print(f"{args.home:15s}: {probs[0]:.3f}")
    print(f"Draw           : {probs[1]:.3f}")
    print(f"{args.away:15s}: {probs[2]:.3f}")

    # ----------------------------
    # FAIR ODDS
    # ----------------------------
    odds = to_odds(probs)

    print("\n💰 Fair Odds:")
    print(f"{args.home:15s}: {odds[0]:.2f}")
    print(f"Draw           : {odds[1]:.2f}")
    print(f"{args.away:15s}: {odds[2]:.2f}")

    # ----------------------------
    # BOOKMAKER MARGIN
    # ----------------------------
    if args.margin > 0:
        probs_m = apply_overround(probs, args.margin)
        odds_m = to_odds(probs_m)

        print(f"\n🏦 With Margin ({args.margin*100:.1f}%):")
        print(f"{args.home:15s}: {odds_m[0]:.2f}")
        print(f"Draw           : {odds_m[1]:.2f}")
        print(f"{args.away:15s}: {odds_m[2]:.2f}")


if __name__ == "__main__":
    main()

