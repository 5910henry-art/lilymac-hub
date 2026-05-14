import pandas as pd
import math
import numpy as np
import random
from collections import Counter

# =========================
# 0. REPRODUCIBILITY
# =========================
np.random.seed(42)
random.seed(42)

# =========================
# 1. LOAD DATA
# =========================
df = pd.read_csv("result_clean.csv")

print("Data Loaded:")
print(df.head())

# =========================
# 2. BASIC DISTRIBUTION CHECKS (NO PLOTTING)
# =========================
print("\n=== GOAL DISTRIBUTION ===")
print(df["home_goals"].value_counts().sort_index())
print("\n=== AWAY GOAL DISTRIBUTION ===")
print(df["away_goals"].value_counts().sort_index())

print("\n=== WEEKLY AVERAGES ===")
weekly_avg = df.groupby("week")[["home_goals", "away_goals"]].mean()
print(weekly_avg.head(10))

# =========================
# 3. CONVERT TO TEAM DATASET
# =========================
def create_team_dataset(df: pd.DataFrame) -> pd.DataFrame:
    home_df = df[["week", "home_team", "away_team", "home_goals", "away_goals"]].copy()
    home_df.columns = ["week", "team", "opponent", "goals_for", "goals_against"]
    home_df["home"] = 1

    away_df = df[["week", "away_team", "home_team", "away_goals", "home_goals"]].copy()
    away_df.columns = ["week", "team", "opponent", "goals_for", "goals_against"]
    away_df["home"] = 0

    team_df = pd.concat([home_df, away_df], ignore_index=True)
    return team_df

team_df = create_team_dataset(df)

# =========================
# 4. ROLLING FEATURES
# =========================
def add_rolling_features(team_df: pd.DataFrame) -> pd.DataFrame:
    team_df = team_df.sort_values(["team", "week"]).reset_index(drop=True)

    team_df["attack_strength"] = team_df.groupby("team")["goals_for"].transform(
        lambda x: x.rolling(5, min_periods=1).mean()
    )
    team_df["defense_strength"] = team_df.groupby("team")["goals_against"].transform(
        lambda x: x.rolling(5, min_periods=1).mean()
    )

    return team_df

team_df = add_rolling_features(team_df)

# =========================
# 5. SIMPLE POISSON MODEL (PURE PYTHON)
# =========================
def train_poisson(team_df: pd.DataFrame, lr: float = 0.001, epochs: int = 300):
    teams = team_df["team"].unique()

    attack = {t: 0.1 for t in teams}
    defense = {t: 0.1 for t in teams}
    home_adv = 0.1

    for epoch in range(epochs):
        total_loss = 0.0

        for _, row in team_df.iterrows():
            t = row["team"]
            o = row["opponent"]
            y = float(row["goals_for"])
            home = float(row["home"])

            lam = np.exp(attack[t] - defense[o] + home_adv * home)

            # Poisson negative log-likelihood up to constant
            loss = lam - y * np.log(lam + 1e-8)
            total_loss += loss

            grad = lam - y
            attack[t] -= lr * grad
            defense[o] += lr * grad
            home_adv -= lr * grad * home

        if epoch % 50 == 0:
            print(f"Epoch {epoch}, Loss {total_loss:.2f}")

    return attack, defense, home_adv

attack, defense, home_adv = train_poisson(team_df)

# =========================
# 6. PREDICT GOALS
# =========================
def predict_lambda(row):
    return np.exp(
        attack[row["team"]] - defense[row["opponent"]] + home_adv * row["home"]
    )

team_df["lambda_pred"] = team_df.apply(predict_lambda, axis=1)

# =========================
# 7. BUILD MATCH DATA
# =========================
def build_match_predictions(df: pd.DataFrame, team_df: pd.DataFrame) -> pd.DataFrame:
    home_preds = team_df[team_df["home"] == 1][["week", "team", "lambda_pred"]].copy()
    away_preds = team_df[team_df["home"] == 0][["week", "team", "lambda_pred"]].copy()

    home_preds.columns = ["week", "home_team", "lambda_home"]
    away_preds.columns = ["week", "away_team", "lambda_away"]

    matches = df.merge(home_preds, on=["week", "home_team"], how="left")
    matches = matches.merge(away_preds, on=["week", "away_team"], how="left")

    return matches

matches = build_match_predictions(df, team_df)

# =========================
# 8. MATCH PROBABILITIES
# =========================
def poisson_pmf(k: int, lam: float) -> float:
    return (lam ** k * np.exp(-lam)) / math.factorial(k)


def match_probs(lh: float, la: float, max_goals: int = 6):
    home_win = 0.0
    draw = 0.0
    away_win = 0.0

    for i in range(max_goals):
        for j in range(max_goals):
            p = poisson_pmf(i, lh) * poisson_pmf(j, la)
            if i > j:
                home_win += p
            elif i == j:
                draw += p
            else:
                away_win += p

    return home_win, draw, away_win

matches[["p_home", "p_draw", "p_away"]] = matches.apply(
    lambda row: pd.Series(match_probs(row["lambda_home"], row["lambda_away"])),
    axis=1,
)

# =========================
# 9. MATCHUP CONSISTENCY
# =========================
print("\n=== MATCHUP CONSISTENCY ===")
matchup_stats = df.groupby(["home_team", "away_team"]).agg(
    home_goals_mean=("home_goals", "mean"),
    home_goals_std=("home_goals", "std"),
    away_goals_mean=("away_goals", "mean"),
    away_goals_std=("away_goals", "std"),
    most_common_result=("result", lambda x: x.value_counts().index[0]),
)

consistent = matchup_stats[
    (matchup_stats["home_goals_std"].fillna(0) < 0.8)
    & (matchup_stats["away_goals_std"].fillna(0) < 0.8)
]
print("\nHighly consistent matchups:")
print(consistent.sort_values("home_goals_std").head(10))

# =========================
# 10. TEAM FORM STABILITY
# =========================
print("\n=== TEAM FORM VARIANCE ===")
form_var = team_df.groupby("team")["goals_for"].std().sort_values()
print(form_var)

# =========================
# 11. TEAM STYLES
# =========================
team_style = team_df.groupby("team").agg(
    goals_for=("goals_for", "mean"),
    goals_against=("goals_against", "mean"),
    lambda_pred=("lambda_pred", "mean"),
)
team_style["attack_defense_ratio"] = team_style["goals_for"] / (team_style["goals_against"] + 1e-5)
team_style["chaos"] = team_df.groupby("team")["goals_for"].std()

print("\n=== TEAM STYLES ===")
print(team_style.sort_values("attack_defense_ratio"))

print("\n=== CHAOTIC TEAMS ===")
print(team_style.sort_values("chaos", ascending=False))

# =========================
# 12. NOISE MODEL
# =========================
print("\n=== NOISE MODEL ===")
team_df["expected_var"] = team_df["lambda_pred"]
actual_var = team_df.groupby("team")["goals_for"].var()
expected_var = team_df.groupby("team")["expected_var"].mean()
noise_df = pd.DataFrame({"actual_var": actual_var, "expected_var": expected_var})
noise_df["noise_ratio"] = noise_df["actual_var"] / (noise_df["expected_var"] + 1e-6)
print(noise_df.sort_values("noise_ratio", ascending=False))

# =========================
# 13. ENGINE SIMULATION
# =========================
print("\n=== ENGINE SIMULATION ===")

def simulate_match(lh: float, la: float, noise_h: float = 1.0, noise_a: float = 1.0):
    lh_adj = max(lh * noise_h, 1e-8)
    la_adj = max(la * noise_a, 1e-8)
    return np.random.poisson(lh_adj), np.random.poisson(la_adj)

sim_results = []
for _, row in matches.head(100).iterrows():
    nh = float(noise_df.loc[row["home_team"], "noise_ratio"])
    na = float(noise_df.loc[row["away_team"], "noise_ratio"])
    hg, ag = simulate_match(float(row["lambda_home"]), float(row["lambda_away"]), nh, na)
    sim_results.append((hg, ag))

sim_df = pd.DataFrame(sim_results, columns=["sim_home", "sim_away"])
print(sim_df.describe())

# =========================
# 14. EDGE DETECTION
# =========================
print("\n=== EDGE ZONES ===")

def get_noise(team: str) -> float:
    return float(noise_df.loc[team, "noise_ratio"])

matches["noise_home"] = matches["home_team"].apply(get_noise)
matches["noise_away"] = matches["away_team"].apply(get_noise)
matches["edge_score"] = (
    (matches["p_home"].sub(0.33).abs() + matches["p_away"].sub(0.33).abs())
    / (matches["noise_home"] + matches["noise_away"])
)
edges = matches.sort_values("edge_score", ascending=False)
print(edges[["home_team", "away_team", "p_home", "p_away", "edge_score"]].head(20))

# =========================
# 15. SIMPLE HIGH-CONFIDENCE FILTERS
# =========================
def detect_scripted(matches: pd.DataFrame):
    grouped = matches.groupby(["home_team", "away_team"])
    scripted = grouped["p_home"].std().sort_values()
    print("\n=== LOW VARIANCE MATCHUPS ===")
    print(scripted.head(20))
    return scripted


def simulate_strategy(matches: pd.DataFrame):
    bankroll = 1000.0
    for _, row in matches.iterrows():
        if row["p_home"] > 0.65:
            bankroll += row["p_home"] * 10 - 10
    print("Final bankroll:", bankroll)
    return bankroll

# =========================
# 16. PURE PYTHON KMEANS (NO SKLEARN)
# =========================
def kmeans(X, k=3, max_iters=100):
    X = np.array(X, dtype=float)
    if len(X) < k:
        raise ValueError("k cannot be larger than the number of samples")

    centroids = X[np.random.choice(len(X), k, replace=False)]

    for _ in range(max_iters):
        distances = np.linalg.norm(X[:, None] - centroids, axis=2)
        labels = np.argmin(distances, axis=1)

        new_centroids = np.array([
            X[labels == i].mean(axis=0) if np.any(labels == i) else centroids[i]
            for i in range(k)
        ])

        if np.allclose(centroids, new_centroids):
            break
        centroids = new_centroids

    return labels, centroids

X = team_style[["goals_for", "goals_against"]].fillna(0).values
labels, centers = kmeans(X, k=3)
team_style = team_style.copy()
team_style["tier"] = labels

print("\n=== TIER CENTERS ===")
for i, c in enumerate(centers):
    print(f"Tier {i}: goals_for={c[0]:.3f}, goals_against={c[1]:.3f}")

# Rank tiers by scoring strength and map names
    tier_strength = {}
for i in range(3):
    subset = team_style[team_style["tier"] == i]
    tier_strength[i] = subset["goals_for"].mean()

sorted_tiers = sorted(tier_strength.items(), key=lambda x: x[1])
tier_name_map = {
    sorted_tiers[0][0]: "LOW",
    sorted_tiers[1][0]: "MID",
    sorted_tiers[2][0]: "HIGH",
}

team_style["tier_name"] = team_style["tier"].map(tier_name_map)
print("\n=== TIER RANKING ===")
for tier, val in sorted_tiers:
    print(f"Tier {tier}: avg goals = {val:.3f}")

# Attach tier names back to matches (based on team names)
team_tiers = team_style[["tier", "tier_name"]].copy()
team_tiers = team_tiers.reset_index()  # brings team out of index
team_tier_lookup = team_style[["tier", "tier_name"]].copy()
team_tier_lookup = team_style.reset_index()[["team", "tier", "tier_name"]]

matches = matches.merge(
    team_tier_lookup[["team", "tier_name"]].rename(columns={"team": "home_team", "tier_name": "home_tier"}),
    on="home_team",
    how="left",
)
matches = matches.merge(
    team_tier_lookup[["team", "tier_name"]].rename(columns={"team": "away_team", "tier_name": "away_tier"}),
    on="away_team",
    how="left",
)

# =========================
# 17. TIER MATRIX
# =========================
def build_tier_matrix(matches: pd.DataFrame):
    matrix = matches.groupby(["home_tier", "away_tier"]).agg(
        p_home=("p_home", "mean"),
        p_draw=("p_draw", "mean"),
        p_away=("p_away", "mean"),
    ).reset_index()
    counts = matches.groupby(["home_tier", "away_tier"]).size().reset_index(name="count")
    matrix = matrix.merge(counts, on=["home_tier", "away_tier"], how="left")
    matrix["dominance"] = matrix["p_home"] - matrix["p_away"]
    print("\n=== TIER VS TIER MATRIX ===")
    print(matrix.sort_values(["home_tier", "away_tier"]))
    print("\n=== DOMINANCE (HOME - AWAY) ===")
    print(matrix.sort_values("dominance", ascending=False))
    return matrix

tier_matrix = build_tier_matrix(matches)

print("\n=== HIGH CONFIDENCE HOME ===")
print(tier_matrix[tier_matrix["p_home"] > 0.6])
print("\n=== HIGH CONFIDENCE AWAY ===")
print(tier_matrix[tier_matrix["p_away"] > 0.6])
print("\n=== DRAW HEAVY ===")
print(tier_matrix[tier_matrix["p_draw"] > 0.35])

# =========================
# 18. PATTERN DETECTION
# =========================
def detect_repeating_draws(df: pd.DataFrame):
    grouped = df.groupby(["home_team", "away_team"])
    patterns = []

    for (home, away), group in grouped:
        draw_rows = group[group["result"] == "D"].sort_values("week")
        if len(draw_rows) >= 3:
            scores = list(zip(draw_rows["home_goals"], draw_rows["away_goals"]))
            patterns.append((home, away, scores))

    print("\n=== REPEATING DRAW PATTERNS ===")
    for p in patterns[:10]:
        print(p)
    return patterns


def detect_score_cycles(df: pd.DataFrame):
    grouped = df.groupby(["home_team", "away_team"])
    print("\n=== SCORE CYCLES (SAME RESULT ACROSS MULTIPLE MEETINGS) ===")

    for (home, away), group in grouped:
        if len(group) >= 3:
            results = group["result"].unique()
            scores = list(zip(group["home_goals"], group["away_goals"]))
            if len(results) == 1:
                print((home, away), results[0], scores)


def classify_patterns(df: pd.DataFrame, min_games: int = 3):
    grouped = df.groupby(["home_team", "away_team"])
    pattern_results = []

    for (home, away), group in grouped:
        if len(group) < min_games:
            continue

        group = group.sort_values("week")
        results = group["result"].tolist()
        scores = list(zip(group["home_goals"], group["away_goals"]))
        unique_results = set(results)

        pattern_type = "RANDOM"

        # Strongest signal: arithmetic progression in scorelines
        if len(scores) >= 3:
            diffs = [
                (scores[i][0] - scores[i - 1][0], scores[i][1] - scores[i - 1][1])
                for i in range(1, len(scores))
            ]
            if len(set(diffs)) == 1:
                pattern_type = "PROGRESSION"
            elif all(h == a for h, a in scores):
                if len(set(results)) == 1 and results[0] == "D":
                    pattern_type = "DRAW_CYCLE"
                else:
                    pattern_type = "DRAW_PATTERN"
            elif unique_results == {"H"}:
                pattern_type = "HOME_CYCLE"
            elif unique_results == {"A"}:
                pattern_type = "AWAY_CYCLE"

        pattern_results.append(
            {
                "home_team": home,
                "away_team": away,
                "pattern": pattern_type,
                "games": len(group),
                "scores": scores,
            }
        )

    pattern_df = pd.DataFrame(pattern_results)
    print("\n=== PATTERN CLASSIFICATION ===")
    if not pattern_df.empty:
        print(pattern_df["pattern"].value_counts())
        print("\n=== STRONG PATTERNS ===")
        print(pattern_df[pattern_df["pattern"] != "RANDOM"].head(20))
    else:
        print("No patterns found.")

    return pattern_df

pattern_df = classify_patterns(df)


def attach_patterns(matches: pd.DataFrame, pattern_df: pd.DataFrame):
    if pattern_df.empty:
        matches["pattern"] = np.nan
        return matches

    matches = matches.merge(
        pattern_df[["home_team", "away_team", "pattern"]],
        on=["home_team", "away_team"],
        how="left",
    )
    return matches

matches = attach_patterns(matches, pattern_df)

if "pattern" in matches.columns:
    print("\n=== PATTERN VS PROBABILITY ===")
    print(matches.groupby("pattern")[["p_home", "p_draw", "p_away"]].mean())


def detect_score_progression(pattern_df: pd.DataFrame):
    print("\n=== SCORE PROGRESSION ===")
    if pattern_df.empty:
        print("No patterns available.")
        return

    for _, row in pattern_df.iterrows():
        scores = row["scores"]
        if len(scores) >= 3:
            diffs = [
                (scores[i][0] - scores[i - 1][0], scores[i][1] - scores[i - 1][1])
                for i in range(1, len(scores))
            ]
            if len(set(diffs)) == 1:
                print(
                    row["home_team"],
                    "vs",
                    row["away_team"],
                    "Pattern:",
                    row["pattern"],
                    "Step:",
                    diffs[0],
                    "Scores:",
                    scores,
                )

detect_score_progression(pattern_df)


def pattern_predictions(matches: pd.DataFrame):
    print("\n=== HIGH CONFIDENCE PICKS ===")
    if "pattern" not in matches.columns:
        print("Pattern column not available.")
        return pd.DataFrame()

    picks = matches[
        matches["pattern"].isin(["DRAW_CYCLE", "HOME_CYCLE", "AWAY_CYCLE", "PROGRESSION"])
    ].copy()
    print(picks[["home_team", "away_team", "pattern", "p_home", "p_draw", "p_away"]].head(20))
    return picks

high_conf_picks = pattern_predictions(matches)

# =========================
# 19. ANALYSIS SUMMARY
# =========================
print("\n=== HOME ADVANTAGE ===")
print(home_adv)

print("\n=== TEAM ATTACK STRENGTH ===")
print(sorted(attack.items(), key=lambda x: x[1]))

print("\n=== TEAM DEFENSE STRENGTH ===")
print(sorted(defense.items(), key=lambda x: x[1]))

print("\n=== SAMPLE PREDICTIONS ===")
print(matches[["home_team", "away_team", "p_home", "p_draw", "p_away"]].head())

print("\n=== CONFIDENCE CHECK ===")
print(matches[["p_home", "p_draw", "p_away"]].max())

print("\nPipeline complete.")
