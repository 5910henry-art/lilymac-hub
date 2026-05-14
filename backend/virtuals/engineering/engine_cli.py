# engine_cli.py
# Usage:
#   python engine_cli.py results.txt
#   python engine_cli.py results.txt --predict "Real Madrid" "Barcelona"

import argparse
import math
from collections import defaultdict

from reverse_engine_ai import (
    parse_matches,
    ReverseEngineAI,
    detect_determinism,
)


# -----------------------------
# SAFE MATCH ACCESS
# -----------------------------
def get_match_field(m, field):
    """
    Supports both dict-style and object-style matches.
    """
    if isinstance(m, dict):
        return m[field]
    return getattr(m, field)


def match_points(home_goals, away_goals):
    if home_goals > away_goals:
        return 3, 0
    if home_goals < away_goals:
        return 0, 3
    return 1, 1


def recent_form_score(history, last_n=5):
    if not history:
        return 0.0
    sample = history[-last_n:]
    return sum(sample) / len(sample)


def summarize_result_points(data):
    if not data:
        return {"win_rate": 0.0, "draw_rate": 0.0, "loss_rate": 0.0}

    wins = sum(1 for x in data if x == 3)
    draws = sum(1 for x in data if x == 1)
    losses = sum(1 for x in data if x == 0)
    total = len(data)

    return {
        "win_rate": round(wins / total, 3),
        "draw_rate": round(draws / total, 3),
        "loss_rate": round(losses / total, 3),
    }


# -----------------------------
# FORM IMPACT ANALYSIS
# -----------------------------
def analyze_form_impact(matches, last_n=5):
    """
    Measures whether recent form tends to be followed by better/worse results.
    """
    team_history = defaultdict(list)

    good_form_results = []
    bad_form_results = []

    for m in matches:
        home = get_match_field(m, "home")
        away = get_match_field(m, "away")
        hg = get_match_field(m, "home_goals")
        ag = get_match_field(m, "away_goals")

        home_pts, away_pts = match_points(hg, ag)

        team_history[home].append(home_pts)
        team_history[away].append(away_pts)

    for team, results in team_history.items():
        for i in range(last_n, len(results)):
            recent_form = results[i - last_n:i]
            next_result = results[i]
            avg_form = sum(recent_form) / last_n

            if avg_form >= 2.0:
                good_form_results.append(next_result)
            elif avg_form <= 1.0:
                bad_form_results.append(next_result)

    return {
        "good_form": summarize_result_points(good_form_results),
        "bad_form": summarize_result_points(bad_form_results),
        "samples": {
            "good_form_samples": len(good_form_results),
            "bad_form_samples": len(bad_form_results),
        },
    }


# -----------------------------
# TRUE FORM IMPACT ON NEXT MATCH
# -----------------------------
def analyze_true_form_impact(matches, last_n=5):
    """
    Measures whether a team's form BEFORE a match affects its result IN that match.
    This is closer to a causal form check than the mixed aggregate analysis above.
    """
    team_history = defaultdict(list)
    good_form_next = []
    bad_form_next = []

    for m in matches:
        home = get_match_field(m, "home")
        away = get_match_field(m, "away")
        hg = get_match_field(m, "home_goals")
        ag = get_match_field(m, "away_goals")

        home_pts, away_pts = match_points(hg, ag)

        def get_form(team):
            if len(team_history[team]) < last_n:
                return None
            return sum(team_history[team][-last_n:]) / last_n

        home_form = get_form(home)
        away_form = get_form(away)

        if home_form is not None:
            if home_form >= 2.0:
                good_form_next.append(home_pts)
            elif home_form <= 1.0:
                bad_form_next.append(home_pts)

        if away_form is not None:
            if away_form >= 2.0:
                good_form_next.append(away_pts)
            elif away_form <= 1.0:
                bad_form_next.append(away_pts)

        team_history[home].append(home_pts)
        team_history[away].append(away_pts)

    return {
        "good_form": summarize_result_points(good_form_next),
        "bad_form": summarize_result_points(bad_form_next),
        "samples": {
            "good_form_samples": len(good_form_next),
            "bad_form_samples": len(bad_form_next),
        },
    }


# -----------------------------
# TRAP DETECTION
# -----------------------------
def detect_traps(matches, ai, last_n=5, min_strength_gap=5.0):
    """
    Trap match = a strong favorite fails to win, or a high-confidence match
    ends in a draw/loss.

    Severity combines:
      - strength gap
      - expected bias
      - form pressure
      - low-score shock
    """
    table = ai.team_table(matches)
    strength_map = {
        row["team"]: row["pts"] + (row["gd"] * 0.1)
        for row in table
    }

    history = defaultdict(list)
    traps = []

    for m in matches:
        home = get_match_field(m, "home")
        away = get_match_field(m, "away")
        hg = get_match_field(m, "home_goals")
        ag = get_match_field(m, "away_goals")

        home_pts, away_pts = match_points(hg, ag)

        home_strength = strength_map.get(home, 0.0)
        away_strength = strength_map.get(away, 0.0)

        home_form = recent_form_score(history[home], last_n)
        away_form = recent_form_score(history[away], last_n)

        strength_gap = abs(home_strength - away_strength)
        total_strength = home_strength + away_strength + 1e-5
        expected_bias = abs(home_strength - away_strength) / total_strength
        streak_pressure = abs(home_form - 1.5) + abs(away_form - 1.5)
        score_shock = 1 if (hg + ag <= 1 and strength_gap > min_strength_gap) else 0

        severity_base = (
            strength_gap * 0.6
            + expected_bias * 10.0
            + streak_pressure * 2.0
            + score_shock * 5.0
        )

        home_expected = home_strength >= away_strength + min_strength_gap
        away_expected = away_strength >= home_strength + min_strength_gap

        # Home favorite fails to win
        if home_expected and hg <= ag:
            severity = severity_base
            if home_form >= 2.0 and away_form <= 1.0:
                severity += 3.0

            traps.append({
                "type": "HOME TRAP",
                "home": home,
                "away": away,
                "score": f"{hg}-{ag}",
                "favored": home,
                "underdog": away,
                "result": "home failed to win",
                "home_form": round(home_form, 3),
                "away_form": round(away_form, 3),
                "strength_gap": round(strength_gap, 3),
                "expected_bias": round(expected_bias, 3),
                "severity": round(severity, 3),
            })

        # Away favorite fails to win
        elif away_expected and ag <= hg:
            severity = severity_base
            if away_form >= 2.0 and home_form <= 1.0:
                severity += 3.0

            traps.append({
                "type": "AWAY TRAP",
                "home": home,
                "away": away,
                "score": f"{hg}-{ag}",
                "favored": away,
                "underdog": home,
                "result": "away failed to win",
                "home_form": round(home_form, 3),
                "away_form": round(away_form, 3),
                "strength_gap": round(strength_gap, 3),
                "expected_bias": round(expected_bias, 3),
                "severity": round(severity, 3),
            })

        # Form reversal trap
        if home_form >= 2.2 and hg < ag:
            traps.append({
                "type": "FORM REVERSAL TRAP",
                "home": home,
                "away": away,
                "score": f"{hg}-{ag}",
                "favored": home,
                "underdog": away,
                "result": "strong home form collapsed",
                "home_form": round(home_form, 3),
                "away_form": round(away_form, 3),
                "strength_gap": round(strength_gap, 3),
                "expected_bias": round(expected_bias, 3),
                "severity": round(severity_base + 4.0, 3),
            })

        if away_form >= 2.2 and ag < hg:
            traps.append({
                "type": "FORM REVERSAL TRAP",
                "home": home,
                "away": away,
                "score": f"{hg}-{ag}",
                "favored": away,
                "underdog": home,
                "result": "strong away form collapsed",
                "home_form": round(home_form, 3),
                "away_form": round(away_form, 3),
                "strength_gap": round(strength_gap, 3),
                "expected_bias": round(expected_bias, 3),
                "severity": round(severity_base + 4.0, 3),
            })

        history[home].append(home_pts)
        history[away].append(away_pts)

    traps.sort(key=lambda x: x["severity"], reverse=True)
    return traps


def main():
    parser = argparse.ArgumentParser(description="Virtual League AI Reverse Engine")

    parser.add_argument("file", help="Path to results text file")
    parser.add_argument("--predict", nargs=2, metavar=("HOME", "AWAY"),
                        help="Predict a match")
    parser.add_argument("--sims", type=int, default=4000,
                        help="Simulation count for predictions")
    parser.add_argument("--upsets", type=int, default=10,
                        help="Number of upsets to display")
    parser.add_argument("--traps", type=int, default=10,
                        help="Number of trap matches to display")
    parser.add_argument("--form_n", type=int, default=5,
                        help="Number of matches to calculate form")

    args = parser.parse_args()

    # -----------------------------
    # LOAD DATA
    # -----------------------------
    with open(args.file, "r", encoding="utf-8") as f:
        raw = f.read()

    matches = parse_matches(raw)

    if not matches:
        print("❌ No matches parsed. Check file format.")
        return

    print(f"✅ Loaded {len(matches)} matches")

    # -----------------------------
    # TRAIN AI
    # -----------------------------
    ai = ReverseEngineAI().fit(matches)

    # -----------------------------
    # PROFILE OUTPUT
    # -----------------------------
    print("\n🔥 ENGINE PROFILE")
    print("=" * 50)
    for k, v in ai.profile.items():
        print(f"{k:25}: {v}")

    # -----------------------------
    # RATINGS
    # -----------------------------
    print("\n📊 TEAM RATINGS")
    print("=" * 50)
    ratings = ai.ratings_report()
    for team, r in ratings.items():
        print(f"{team:20} attack={r['attack']:.3f}  defense={r['defense']:.3f}")

    # -----------------------------
    # TABLE
    # -----------------------------
    print("\n🏆 LEAGUE TABLE")
    print("=" * 70)
    table = ai.team_table(matches)

    print(f"{'Team':20} {'P':>2} {'W':>2} {'D':>2} {'L':>2} {'GF':>3} {'GA':>3} {'GD':>3} {'Pts':>3}")
    for row in table:
        print(
            f"{row['team']:20} {row['played']:>2} {row['w']:>2} {row['d']:>2} {row['l']:>2} "
            f"{row['gf']:>3} {row['ga']:>3} {row['gd']:>3} {row['pts']:>3}"
        )

    # -----------------------------
    # UPSETS
    # -----------------------------
    print("\n⚠️  TOP UPSETS")
    print("=" * 50)
    upsets = ai.upset_matches(matches)

    for u in upsets[:args.upsets]:
        print(f"{u['home']} vs {u['away']} → {u['score']} "
              f"(favored: {u['favored']} | winner: {u['winner']})")

    # -----------------------------
    # TRAP DETECTION
    # -----------------------------
    print("\n🎯 TRAP DETECTION")
    print("=" * 50)
    traps = detect_traps(matches, ai, last_n=args.form_n)

    if not traps:
        print("No trap matches detected.")
    else:
        for t in traps[:args.traps]:
            print(
                f"{t['type']}: {t['home']} vs {t['away']} → {t['score']} | "
                f"favored: {t['favored']} | {t['result']} | "
                f"home_form={t['home_form']} away_form={t['away_form']} | "
                f"gap={t['strength_gap']} | bias={t['expected_bias']} | severity={t['severity']}"
            )

    # -----------------------------
    # FORM IMPACT ANALYSIS
    # -----------------------------
    print("\n📈 FORM IMPACT ANALYSIS")
    print("=" * 50)

    form_impact = analyze_form_impact(matches, last_n=args.form_n)

    print("\n➡️ GOOD FORM (recent strong performance)")
    for k, v in form_impact["good_form"].items():
        print(f"{k:20}: {v}")

    print("\n➡️ BAD FORM (recent poor performance)")
    for k, v in form_impact["bad_form"].items():
        print(f"{k:20}: {v}")

    print("\n📊 SAMPLE SIZE")
    for k, v in form_impact["samples"].items():
        print(f"{k:20}: {v}")

    print("\n🧠 INTERPRETATION")
    gf = form_impact["good_form"]["win_rate"]
    bf = form_impact["bad_form"]["win_rate"]

    if gf > bf + 0.15:
        print("✅ Strong form influence detected (last 5 matters a lot)")
    elif abs(gf - bf) < 0.05:
        print("⚠️ Form has little to no effect (last 5 is weak)")
    else:
        print("🟡 Moderate form influence")

    # -----------------------------
    # TRUE FORM IMPACT ON NEXT MATCH
    # -----------------------------
    print("\n🧪 TRUE FORM → NEXT MATCH IMPACT")
    print("=" * 50)

    true_form_impact = analyze_true_form_impact(matches, last_n=args.form_n)

    print("\n➡️ GOOD FORM BEFORE MATCH")
    for k, v in true_form_impact["good_form"].items():
        print(f"{k:20}: {v}")

    print("\n➡️ BAD FORM BEFORE MATCH")
    for k, v in true_form_impact["bad_form"].items():
        print(f"{k:20}: {v}")

    print("\n📊 SAMPLE SIZE")
    for k, v in true_form_impact["samples"].items():
        print(f"{k:20}: {v}")

    print("\n🧠 INTERPRETATION")
    gf2 = true_form_impact["good_form"]["win_rate"]
    bf2 = true_form_impact["bad_form"]["win_rate"]

    if gf2 > bf2 + 0.15:
        print("✅ Last-5 form clearly affects the next result")
    elif abs(gf2 - bf2) < 0.05:
        print("⚠️ Last-5 form has little to no effect")
    else:
        print("🟡 Last-5 form has moderate effect")

    # -----------------------------
    # PREDICTION
    # -----------------------------
    if args.predict:
        home, away = args.predict
        print("\n🔮 MATCH PREDICTION")
        print("=" * 50)

        pred = ai.predict(home, away, sims=args.sims)
        for k, v in pred.items():
            print(f"{k:20}: {v}")

        print("\n🧪 DETERMINISM TEST")
        print("=" * 50)
        det = detect_determinism(ai, home, away)
        for k, v in det.items():
            print(f"{k:20}: {v}")


if __name__ == "__main__":
    main()
