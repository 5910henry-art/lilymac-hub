
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from typing import Dict, Tuple, Optional, List

import pandas as pd


# =========================================================
# TEAM NAME NORMALIZATION
# =========================================================

TEAM_ALIASES = {
    "barca": "Barcelona",
    "barcelona": "Barcelona",
    "a.madrid": "Atletico Madrid",
    "atmadrid": "Atletico Madrid",
    "atleticomadrid": "Atletico Madrid",
    "atletico madrid": "Atletico Madrid",
    "a.bilbao": "Athletic Bilbao",
    "abilbao": "Athletic Bilbao",
    "athleticbilbao": "Athletic Bilbao",
    "athletic bilbao": "Athletic Bilbao",
    "r.sociedad": "Real Sociedad",
    "rsociedad": "Real Sociedad",
    "real sociedad": "Real Sociedad",
    "realmadrid": "Real Madrid",
    "real madrid": "Real Madrid",
    "villareal": "Villarreal",
    "villarreal": "Villarreal",
    "esp": "Espanyol",
    "espanyol": "Espanyol",
    "osa": "Osasuna",
    "osasuna": "Osasuna",
    "gra": "Granada",
    "granada": "Granada",
    "levante": "Levante",
    "getafe": "Getafe",
    "valladolid": "Valladolid",
    "valencia": "Valencia",
    "alaves": "Alaves",
    "almeria": "Almeria",
    "betis": "Betis",
    "sevilla": "Sevilla",
    "leganes": "Leganes",
    "mallorca": "Mallorca",
    "celta vigo": "Celta Vigo",
    "celtavigo": "Celta Vigo",
    "celta": "Celta Vigo",
}

DEFAULT_HOME_ADV = 0.10
DEFAULT_MARKET_WEIGHT = 0.65
DEFAULT_TEMP = 1.25
DEFAULT_DRAW_SCALE = 1.0


def normalize_team(name: str) -> str:
    raw = str(name).strip()
    key = raw.lower().replace(".", "").replace("-", " ").replace("_", " ")
    key = " ".join(key.split())
    key_compact = key.replace(" ", "")
    return TEAM_ALIASES.get(key, TEAM_ALIASES.get(key_compact, raw))


# =========================================================
# LOAD / PREP DATA
# =========================================================

def load_data(path: str = "result.txt") -> pd.DataFrame:
    df = pd.read_csv(path)

    for col in ["home_team", "away_team"]:
        df[col] = df[col].apply(normalize_team)

    for col in ["home_goals", "away_goals", "week"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["home_team", "away_team", "home_goals", "away_goals", "week"]).copy()
    df["home_goals"] = df["home_goals"].astype(int)
    df["away_goals"] = df["away_goals"].astype(int)
    df["week"] = df["week"].astype(int)

    df["result"] = df.apply(
        lambda r: "H" if r["home_goals"] > r["away_goals"] else ("A" if r["home_goals"] < r["away_goals"] else "D"),
        axis=1,
    )

    return df


# =========================================================
# TEAM STATS
# =========================================================

def last5_points(frame: pd.DataFrame, team: str) -> int:
    matches = frame[(frame["home_team"] == team) | (frame["away_team"] == team)].sort_values("week")
    last5 = matches.tail(5)
    pts = 0

    for _, r in last5.iterrows():
        if r["home_team"] == team:
            if r["home_goals"] > r["away_goals"]:
                pts += 3
            elif r["home_goals"] == r["away_goals"]:
                pts += 1
        else:
            if r["away_goals"] > r["home_goals"]:
                pts += 3
            elif r["away_goals"] == r["home_goals"]:
                pts += 1

    return pts


def build_team_stats(frame: pd.DataFrame) -> pd.DataFrame:
    teams = sorted(pd.unique(frame[["home_team", "away_team"]].values.ravel("K")))
    rows: List[dict] = []

    for team in teams:
        home = frame[frame["home_team"] == team]
        away = frame[frame["away_team"] == team]

        played = len(home) + len(away)

        scored_list = list(home["home_goals"]) + list(away["away_goals"])
        conceded_list = list(home["away_goals"]) + list(away["home_goals"])

        goals_scored = sum(scored_list)
        goals_conceded = sum(conceded_list)

        wins = (
            (home["home_goals"] > home["away_goals"]).sum()
            + (away["away_goals"] > away["home_goals"]).sum()
        )
        draws = (
            (home["home_goals"] == home["away_goals"]).sum()
            + (away["away_goals"] == away["home_goals"]).sum()
        )
        losses = played - wins - draws

        clean_sheets = (home["away_goals"] == 0).sum() + (away["home_goals"] == 0).sum()
        failed_to_score = (home["home_goals"] == 0).sum() + (away["away_goals"] == 0).sum()

        home_attack = home["home_goals"].mean() if len(home) else 0.0
        home_defense = home["away_goals"].mean() if len(home) else 0.0
        away_attack = away["away_goals"].mean() if len(away) else 0.0
        away_defense = away["home_goals"].mean() if len(away) else 0.0

        attack = goals_scored / played if played else 0.0
        defense = goals_conceded / played if played else 0.0
        win_rate = wins / played if played else 0.0
        draw_rate = draws / played if played else 0.0
        loss_rate = losses / played if played else 0.0

        scored_vol = pd.Series(scored_list).std(ddof=0) if len(scored_list) > 1 else 0.0
        conceded_vol = pd.Series(conceded_list).std(ddof=0) if len(conceded_list) > 1 else 0.0

        failed_rate = failed_to_score / played if played else 0.0
        clean_rate = clean_sheets / played if played else 0.0

        finishing = (attack * 0.85) + (win_rate * 0.45) - (failed_rate * 0.55)
        suppression = (1.6 - (defense * 0.6)) + (clean_rate * 0.9)

        rows.append(
            {
                "team": team,
                "matches": played,
                "goals_scored": int(goals_scored),
                "goals_conceded": int(goals_conceded),
                "attack": attack,
                "home_attack": home_attack,
                "home_defense": home_defense,
                "away_attack": away_attack,
                "away_defense": away_defense,
                "defense": defense,
                "win_rate": win_rate,
                "draw_rate": draw_rate,
                "loss_rate": loss_rate,
                "goal_diff": int(goals_scored - goals_conceded),
                "clean_sheets": int(clean_sheets),
                "failed_to_score": int(failed_to_score),
                "failed_rate": failed_rate,
                "clean_rate": clean_rate,
                "scored_vol": scored_vol,
                "conceded_vol": conceded_vol,
                "last5_pts": last5_points(frame, team),
                "finishing": finishing,
                "suppression": suppression,
            }
        )

    team_df = pd.DataFrame(rows)

    def classify_style(row) -> str:
        if row["attack"] >= 1.40 and row["defense"] <= 1.20 and row["win_rate"] >= 0.43:
            return "Strong/Balanced"
        if row["draw_rate"] >= 0.35 and row["attack"] <= 1.25:
            return "Draw/Passive"
        if row["defense"] >= 1.50 or row["scored_vol"] >= 1.15 or row["conceded_vol"] >= 1.15:
            return "Chaotic/Weak Defense"
        return "Average"

    team_df["style"] = team_df.apply(classify_style, axis=1)
    return team_df


# =========================================================
# POISSON / PROBABILITY HELPERS
# =========================================================

def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def clamp(x: float, lo: float = 0.10, hi: float = 4.80) -> float:
    return max(lo, min(hi, x))


def implied_probs_from_odds(home_odds: float, draw_odds: float, away_odds: float) -> Tuple[float, float, float]:
    if home_odds <= 1.0 or draw_odds <= 1.0 or away_odds <= 1.0:
        raise ValueError("Odds must be greater than 1.0")

    inv_home = 1.0 / home_odds
    inv_draw = 1.0 / draw_odds
    inv_away = 1.0 / away_odds
    total = inv_home + inv_draw + inv_away
    return inv_home / total, inv_draw / total, inv_away / total


def blend_with_market(
    model_probs: Tuple[float, float, float],
    market_probs: Tuple[float, float, float],
    weight: float = DEFAULT_MARKET_WEIGHT,
) -> Tuple[float, float, float]:
    mw = max(0.0, min(1.0, weight))
    blended = tuple((mw * m) + ((1.0 - mw) * o) for m, o in zip(model_probs, market_probs))
    s = sum(blended)
    return tuple(p / s for p in blended) if s > 0 else blended


def soften_probs(probs: Tuple[float, float, float], temp: float = DEFAULT_TEMP) -> Tuple[float, float, float]:
    temp = max(1.0, float(temp))
    softened = [max(p, 1e-12) ** (1.0 / temp) for p in probs]
    s = sum(softened)
    return tuple(p / s for p in softened) if s > 0 else probs


# =========================================================
# CORE ESTIMATION
# =========================================================

def estimate_lambdas(
    home_team: str,
    away_team: str,
    stats_map: Dict[str, dict],
    home_adv: float = DEFAULT_HOME_ADV,
) -> Tuple[float, float]:
    h = stats_map[home_team]
    a = stats_map[away_team]

    base_home = (h["attack"] + a["defense"]) / 2.0
    base_away = (a["attack"] + h["defense"]) / 2.0

    split_home = (h["home_attack"] + a["away_defense"]) / 2.0
    split_away = (a["away_attack"] + h["home_defense"]) / 2.0

    home_xg = (0.45 * base_home) + (0.55 * split_home)
    away_xg = (0.45 * base_away) + (0.55 * split_away)

    # Home advantage and matchup asymmetry
    home_edge = h["home_attack"] - h["away_attack"]
    away_weak = a["away_defense"] - a["home_defense"]
    home_xg += home_adv + (home_edge * 0.25) + (away_weak * 0.20)

    # Recent form
    form_delta = (h["last5_pts"] - a["last5_pts"]) / 15.0
    home_xg += form_delta * 0.20
    away_xg -= form_delta * 0.20

    # Finishing vs suppression
    home_xg += (h["finishing"] - 1.0) * 0.18
    away_xg += (a["finishing"] - 1.0) * 0.18
    home_xg -= (a["suppression"] - 1.0) * 0.14
    away_xg -= (h["suppression"] - 1.0) * 0.14

    # Strong defense
    if a["defense"] <= 1.05:
        home_xg -= 0.22
    if h["defense"] <= 1.05:
        away_xg -= 0.22

    # Style effects
    if h["style"] == "Chaotic/Weak Defense" and a["style"] == "Chaotic/Weak Defense":
        home_xg += 0.04
        away_xg += 0.04

    if h["style"] == "Draw/Passive" and a["style"] == "Draw/Passive":
        home_xg -= 0.22
        away_xg -= 0.22

    if h["style"] == "Strong/Balanced" and a["style"] == "Draw/Passive":
        home_xg += 0.12
    if h["style"] == "Draw/Passive" and a["style"] == "Strong/Balanced":
        away_xg += 0.12

    if h["style"] == "Strong/Balanced" and a["style"] == "Strong/Balanced":
        home_xg -= 0.08
        away_xg -= 0.08

    # Suppression rules
    both_low_finishing = (h["finishing"] < 1.05 and a["finishing"] < 1.05)
    both_low_attack = (h["attack"] < 1.20 and a["attack"] < 1.20)
    if both_low_finishing and both_low_attack:
        home_xg -= 0.25
        away_xg -= 0.25

    if h["failed_rate"] >= 0.25 and a["failed_rate"] >= 0.25:
        home_xg -= 0.18
        away_xg -= 0.18

    if (a["suppression"] >= 1.15 and h["finishing"] <= 0.95) or (h["suppression"] >= 1.15 and a["finishing"] <= 0.95):
        home_xg -= 0.15
        away_xg -= 0.15

    if a["away_attack"] < 1.0:
        away_xg -= 0.15
    if h["home_defense"] < 1.0:
        away_xg -= 0.18

    if h["style"] == "Chaotic/Weak Defense" and h["home_attack"] > h["away_attack"]:
        home_xg += 0.08

    # Dampening to reduce over-adjustment
    home_xg = 0.85 * home_xg + 0.15 * base_home
    away_xg = 0.85 * away_xg + 0.15 * base_away

    return clamp(home_xg), clamp(away_xg)


def scoreline_probs(home_lam: float, away_lam: float, max_goals: int = 8) -> Dict[Tuple[int, int], float]:
    probs: Dict[Tuple[int, int], float] = {}
    for hg in range(max_goals + 1):
        for ag in range(max_goals + 1):
            p = poisson_pmf(hg, home_lam) * poisson_pmf(ag, away_lam)
            probs[(hg, ag)] = p

    total = sum(probs.values())
    if total > 0:
        for k in probs:
            probs[k] /= total
    return probs


def result_probs(probs: Dict[Tuple[int, int], float]) -> Tuple[float, float, float]:
    home_win = draw = away_win = 0.0
    for (hg, ag), p in probs.items():
        if hg > ag:
            home_win += p
        elif hg < ag:
            away_win += p
        else:
            draw += p
    return home_win, draw, away_win


def draw_boost_from_style(
    h: dict,
    a: dict,
    home_lam: float,
    away_lam: float,
    scale: float = DEFAULT_DRAW_SCALE,
) -> float:
    """
    Smooth draw engine:
    - boosts draws in low-tempo / passive matches
    - boosts draws when teams are closely matched
    - capped to avoid runaway draw inflation
    """
    boost = 0.0

    if h["style"] in ["Draw/Passive", "Average"] and a["style"] in ["Draw/Passive", "Average"]:
        boost += 0.08

    if h["style"] == "Draw/Passive" and a["style"] == "Draw/Passive":
        boost += 0.10

    gap = abs(home_lam - away_lam)
    boost += 0.12 * math.exp(-3.5 * gap)

    if h["style"] == "Strong/Balanced" and a["style"] in ["Draw/Passive", "Average"]:
        boost += 0.03
    if a["style"] == "Strong/Balanced" and h["style"] in ["Draw/Passive", "Average"]:
        boost += 0.03

    boost *= max(0.0, float(scale))
    return min(boost, 0.18)


def estimate_temp(base_temp: float, h: dict, a: dict) -> float:
    """
    Variance only: chaos should make the outcome distribution softer,
    not directly inflate the goal means.
    """
    temp = max(1.0, float(base_temp))
    max_vol = max(h["scored_vol"], h["conceded_vol"], a["scored_vol"], a["conceded_vol"])

    if max_vol >= 1.20:
        temp += 0.08
    if h["style"] == "Chaotic/Weak Defense" or a["style"] == "Chaotic/Weak Defense":
        temp += 0.10

    return temp


def predict_match(
    home_team: str,
    away_team: str,
    stats_map: Dict[str, dict],
    market_odds: Optional[Tuple[float, float, float]] = None,
    market_weight: float = DEFAULT_MARKET_WEIGHT,
    temp: float = DEFAULT_TEMP,
    draw_scale: float = DEFAULT_DRAW_SCALE,
    home_adv: float = DEFAULT_HOME_ADV,
):
    home_team = normalize_team(home_team)
    away_team = normalize_team(away_team)

    if home_team not in stats_map:
        raise ValueError(f"Unknown home team: {home_team}")
    if away_team not in stats_map:
        raise ValueError(f"Unknown away team: {away_team}")

    h = stats_map[home_team]
    a = stats_map[away_team]

    home_lam, away_lam = estimate_lambdas(home_team, away_team, stats_map, home_adv=home_adv)

    effective_temp = estimate_temp(temp, h, a)

    probs = scoreline_probs(home_lam, away_lam, max_goals=8)
    hw, dr, aw = result_probs(probs)

    # Draw adjustment first, then soften
    draw_boost = draw_boost_from_style(h, a, home_lam, away_lam, scale=draw_scale)
    if draw_boost > 0:
        dr += draw_boost
        hw -= draw_boost / 2.0
        aw -= draw_boost / 2.0

    hw = max(hw, 1e-12)
    dr = max(dr, 1e-12)
    aw = max(aw, 1e-12)
    s = hw + dr + aw
    hw, dr, aw = hw / s, dr / s, aw / s

    hw, dr, aw = soften_probs((hw, dr, aw), temp=effective_temp)

    market_probs = None
    if market_odds is not None:
        market_probs = implied_probs_from_odds(*market_odds)
        hw, dr, aw = blend_with_market((hw, dr, aw), market_probs, weight=market_weight)

    ranked = sorted(probs.items(), key=lambda x: x[1], reverse=True)[:7]
    total_goals = home_lam + away_lam

    likely_type = "Balanced"
    if total_goals < 2.2:
        likely_type = "Low scoring"
    elif total_goals >= 3.2:
        likely_type = "High scoring"

    if h["style"] == "Chaotic/Weak Defense" and a["style"] == "Chaotic/Weak Defense":
        likely_type = "Volatile / wide-range"
    if h["style"] == "Draw/Passive" and a["style"] == "Draw/Passive":
        likely_type = "Draw-heavy / tight"

    suppression_flag = (
        (h["finishing"] < 1.00 and a["suppression"] > 1.10)
        or (a["finishing"] < 1.00 and h["suppression"] > 1.10)
        or (h["failed_rate"] >= 0.25 and a["failed_rate"] >= 0.25)
    )

    value_edge = None
    if market_probs is not None:
        value_edge = {
            "home": hw - market_probs[0],
            "draw": dr - market_probs[1],
            "away": aw - market_probs[2],
        }

    fair_odds = {
        "home": (1.0 / hw) if hw > 0 else None,
        "draw": (1.0 / dr) if dr > 0 else None,
        "away": (1.0 / aw) if aw > 0 else None,
    }

    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_style": h["style"],
        "away_style": a["style"],
        "home_lambda": home_lam,
        "away_lambda": away_lam,
        "home_win": hw,
        "draw": dr,
        "away_win": aw,
        "fair_odds": fair_odds,
        "likely_type": likely_type,
        "top_scores": ranked,
        "total_goals": total_goals,
        "suppression_flag": suppression_flag,
        "market_used": market_odds is not None,
        "market_probs": market_probs,
        "value_edge": value_edge,
        "effective_temp": effective_temp,
        "draw_boost": draw_boost,
    }


# =========================================================
# EVALUATION / CALIBRATION
# =========================================================

def _build_eval_rows(
    df_all: pd.DataFrame,
    stats_map: Dict[str, dict],
    market_weight: float,
    temp: float,
    draw_scale: float,
    home_adv: float,
) -> List[dict]:
    rows: List[dict] = []

    for _, row in df_all.iterrows():
        home = row["home_team"]
        away = row["away_team"]

        if home not in stats_map or away not in stats_map:
            continue

        pred = predict_match(
            home,
            away,
            stats_map=stats_map,
            market_weight=market_weight,
            temp=temp,
            draw_scale=draw_scale,
            home_adv=home_adv,
        )
        rows.append(
            {
                "week": int(row["week"]),
                "home_team": home,
                "away_team": away,
                "actual": row["result"],
                "pred_home": pred["home_win"],
                "pred_draw": pred["draw"],
                "pred_away": pred["away_win"],
                "predicted": max(
                    [("H", pred["home_win"]), ("D", pred["draw"]), ("A", pred["away_win"])],
                    key=lambda x: x[1],
                )[0],
                "home_style": pred["home_style"],
                "away_style": pred["away_style"],
            }
        )

    return rows


def evaluate_model(
    frame: pd.DataFrame,
    cutoff_week: Optional[int] = None,
    walk_forward: bool = False,
    market_weight: float = DEFAULT_MARKET_WEIGHT,
    temp: float = DEFAULT_TEMP,
    draw_scale: float = DEFAULT_DRAW_SCALE,
    home_adv: float = DEFAULT_HOME_ADV,
) -> None:
    df_all = frame.sort_values(["week", "home_team", "away_team"]).reset_index(drop=True)

    if walk_forward:
        rows: List[dict] = []
        weeks = sorted(df_all["week"].unique())
        for wk in weeks:
            test_week = df_all[df_all["week"] == wk]
            train_week = df_all[df_all["week"] < wk]
            if len(train_week) == 0 or len(test_week) == 0:
                continue

            stats = build_team_stats(train_week)
            stats_map = stats.set_index("team").to_dict("index")

            rows.extend(
                _build_eval_rows(
                    test_week,
                    stats_map=stats_map,
                    market_weight=market_weight,
                    temp=temp,
                    draw_scale=draw_scale,
                    home_adv=home_adv,
                )
            )
    else:
        if cutoff_week is None:
            cutoff_week = int(df_all["week"].median())

        train = df_all[df_all["week"] <= cutoff_week].copy()
        test = df_all[df_all["week"] > cutoff_week].copy()

        if len(train) == 0 or len(test) == 0:
            raise ValueError("Train/test split produced an empty side. Adjust cutoff_week.")

        stats = build_team_stats(train)
        stats_map = stats.set_index("team").to_dict("index")

        rows = _build_eval_rows(
            test,
            stats_map=stats_map,
            market_weight=market_weight,
            temp=temp,
            draw_scale=draw_scale,
            home_adv=home_adv,
        )

    if not rows:
        print("\n=== MODEL EVALUATION ===")
        print("No evaluable matches found.")
        return

    eval_df = pd.DataFrame(rows)

    correct = 0
    total = len(eval_df)
    log_loss = 0.0
    brier_sum = 0.0

    style_errors = {}
    style_counts = {}
    conf = {"H": {"H": 0, "D": 0, "A": 0}, "D": {"H": 0, "D": 0, "A": 0}, "A": {"H": 0, "D": 0, "A": 0}}

    for _, r in eval_df.iterrows():
        actual = r["actual"]
        predicted = r["predicted"]
        if predicted == actual:
            correct += 1

        p_home = float(r["pred_home"])
        p_draw = float(r["pred_draw"])
        p_away = float(r["pred_away"])

        if actual == "H":
            p = p_home
            y = (1.0, 0.0, 0.0)
        elif actual == "D":
            p = p_draw
            y = (0.0, 1.0, 0.0)
        else:
            p = p_away
            y = (0.0, 0.0, 1.0)

        p = max(p, 1e-12)
        log_loss += -math.log(p)
        brier_sum += (p_home - y[0]) ** 2 + (p_draw - y[1]) ** 2 + (p_away - y[2]) ** 2

        conf[actual][predicted] += 1

        hstyle = r["home_style"]
        astyle = r["away_style"]
        pair_key = f"{hstyle} | {astyle}"
        style_counts[pair_key] = style_counts.get(pair_key, 0) + 1
        if predicted != actual:
            style_errors[pair_key] = style_errors.get(pair_key, 0) + 1

    accuracy = correct / total if total else 0.0
    avg_log_loss = log_loss / total if total else 0.0
    avg_brier = brier_sum / total if total else 0.0

    print("\n=== MODEL EVALUATION ===")
    if walk_forward:
        print("Mode: walk-forward")
    else:
        print(f"Mode: holdout split | cutoff week <= {cutoff_week}")

    print(f"Matches evaluated: {total}")
    print(f"Accuracy: {accuracy:.2%}")
    print(f"Log loss: {avg_log_loss:.4f}")
    print(f"Brier score: {avg_brier:.4f}")

    print("\nConfusion matrix (actual rows, predicted columns):")
    print(
        pd.DataFrame(conf).T.reindex(index=["H", "D", "A"], columns=["H", "D", "A"])
        .fillna(0)
        .astype(int)
        .to_string()
    )

    print("\nError by style pair:")
    for key in sorted(style_counts.keys(), key=lambda k: style_counts[k], reverse=True):
        cnt = style_counts[key]
        err = style_errors.get(key, 0)
        rate = err / cnt if cnt else 0.0
        print(f"{key}: {err}/{cnt}  ({rate:.2%})")


@dataclass
class CalibrationResult:
    cutoff_week: int
    temp: float
    draw_scale: float
    home_adv: float
    log_loss: float
    accuracy: float
    brier: float


def calibrate_engine(
    frame: pd.DataFrame,
    cutoff_week: Optional[int] = None,
    temp_grid: Optional[List[float]] = None,
    draw_grid: Optional[List[float]] = None,
    home_adv_grid: Optional[List[float]] = None,
) -> CalibrationResult:
    df_all = frame.sort_values(["week", "home_team", "away_team"]).reset_index(drop=True)

    if cutoff_week is None:
        cutoff_week = int(df_all["week"].median())

    train = df_all[df_all["week"] <= cutoff_week].copy()
    test = df_all[df_all["week"] > cutoff_week].copy()

    if len(train) == 0 or len(test) == 0:
        raise ValueError("Train/test split produced an empty side. Adjust cutoff_week.")

    stats = build_team_stats(train)
    stats_map = stats.set_index("team").to_dict("index")

    temp_grid = temp_grid or [1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35, 1.40]
    draw_grid = draw_grid or [0.70, 0.85, 1.00, 1.15, 1.30]
    home_adv_grid = home_adv_grid or [0.00, 0.05, 0.10, 0.15, 0.20]

    best: Optional[CalibrationResult] = None

    for temp in temp_grid:
        for draw_scale in draw_grid:
            for home_adv in home_adv_grid:
                rows = _build_eval_rows(
                    test,
                    stats_map=stats_map,
                    market_weight=DEFAULT_MARKET_WEIGHT,
                    temp=temp,
                    draw_scale=draw_scale,
                    home_adv=home_adv,
                )
                if not rows:
                    continue

                eval_df = pd.DataFrame(rows)
                correct = 0
                log_loss = 0.0
                brier_sum = 0.0

                for _, r in eval_df.iterrows():
                    actual = r["actual"]
                    predicted = r["predicted"]
                    if predicted == actual:
                        correct += 1

                    p_home = float(r["pred_home"])
                    p_draw = float(r["pred_draw"])
                    p_away = float(r["pred_away"])

                    if actual == "H":
                        p = p_home
                        y = (1.0, 0.0, 0.0)
                    elif actual == "D":
                        p = p_draw
                        y = (0.0, 1.0, 0.0)
                    else:
                        p = p_away
                        y = (0.0, 0.0, 1.0)

                    p = max(p, 1e-12)
                    log_loss += -math.log(p)
                    brier_sum += (p_home - y[0]) ** 2 + (p_draw - y[1]) ** 2 + (p_away - y[2]) ** 2

                total = len(eval_df)
                result = CalibrationResult(
                    cutoff_week=cutoff_week,
                    temp=temp,
                    draw_scale=draw_scale,
                    home_adv=home_adv,
                    log_loss=log_loss / total if total else float("inf"),
                    accuracy=correct / total if total else 0.0,
                    brier=brier_sum / total if total else float("inf"),
                )

                if best is None or result.log_loss < best.log_loss:
                    best = result

    if best is None:
        raise ValueError("Calibration failed: no valid parameter combination produced evaluable matches.")

    return best


# =========================================================
# DISPLAY HELPERS
# =========================================================

def print_team_table(team_df: pd.DataFrame) -> None:
    pd.set_option("display.width", 180)
    pd.set_option("display.max_columns", 60)

    print("\n=== TEAM BEHAVIOR ===\n")
    print(
        team_df.sort_values(["style", "goal_diff"], ascending=[True, False])[
            [
                "team",
                "style",
                "attack",
                "defense",
                "win_rate",
                "draw_rate",
                "loss_rate",
                "goal_diff",
                "finishing",
                "suppression",
                "failed_rate",
                "scored_vol",
                "last5_pts",
            ]
        ].to_string(index=False)
    )


# =========================================================
# MAIN
# =========================================================

def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("home", nargs="?", help="Home team")
    parser.add_argument("away", nargs="?", help="Away team")
    parser.add_argument("--home-odds", type=float, default=None, help="Decimal home odds")
    parser.add_argument("--draw-odds", type=float, default=None, help="Decimal draw odds")
    parser.add_argument("--away-odds", type=float, default=None, help="Decimal away odds")
    parser.add_argument("--market-weight", type=float, default=DEFAULT_MARKET_WEIGHT, help="Blend weight for model vs market")
    parser.add_argument("--temp", type=float, default=DEFAULT_TEMP, help="Temperature for probability softening")
    parser.add_argument("--draw-scale", type=float, default=DEFAULT_DRAW_SCALE, help="Scale factor for draw calibration")
    parser.add_argument("--home-adv", type=float, default=DEFAULT_HOME_ADV, help="Home advantage added to home xG")
    parser.add_argument("--evaluate", action="store_true", help="Run evaluation instead of a single fixture")
    parser.add_argument("--cutoff-week", type=int, default=None, help="Train on weeks <= cutoff and test on later weeks")
    parser.add_argument("--walk-forward", action="store_true", help="Use walk-forward evaluation by week")
    parser.add_argument("--calibrate", action="store_true", help="Fit temp / draw-scale / home-adv on a holdout split")
    args = parser.parse_args()

    df = load_data("result.txt")

    if args.calibrate:
        result = calibrate_engine(df, cutoff_week=args.cutoff_week)
        print("\n=== CALIBRATION RESULT ===")
        print(f"Cutoff week: {result.cutoff_week}")
        print(f"Best temp: {result.temp:.2f}")
        print(f"Best draw scale: {result.draw_scale:.2f}")
        print(f"Best home adv: {result.home_adv:.2f}")
        print(f"Accuracy: {result.accuracy:.2%}")
        print(f"Log loss: {result.log_loss:.4f}")
        print(f"Brier score: {result.brier:.4f}")
        return

    if args.evaluate:
        evaluate_model(
            df,
            cutoff_week=args.cutoff_week,
            walk_forward=args.walk_forward,
            market_weight=args.market_weight,
            temp=args.temp,
            draw_scale=args.draw_scale,
            home_adv=args.home_adv,
        )
        return

    team_df = build_team_stats(df)
    stats_map = team_df.set_index("team").to_dict("index")

    print_team_table(team_df)

    team_df.to_csv("team_behavior_final.csv", index=False)
    print("\nSaved: team_behavior_final.csv")

    if args.home and args.away:
        market_odds = None
        if args.home_odds is not None and args.draw_odds is not None and args.away_odds is not None:
            market_odds = (args.home_odds, args.draw_odds, args.away_odds)

        pred = predict_match(
            args.home,
            args.away,
            stats_map=stats_map,
            market_odds=market_odds,
            market_weight=args.market_weight,
            temp=args.temp,
            draw_scale=args.draw_scale,
            home_adv=args.home_adv,
        )

        print("\n=== FIXTURE PREDICTION ===\n")
        print(f"{pred['home_team']} ({pred['home_style']}) vs {pred['away_team']} ({pred['away_style']})")
        print(f"Expected goals: {pred['home_lambda']:.2f} - {pred['away_lambda']:.2f}")
        print(f"Game type: {pred['likely_type']}")
        print(f"Effective temp: {pred['effective_temp']:.2f}")
        print(f"Draw boost: {pred['draw_boost']:.3f}")

        if pred["market_used"]:
            print("Market blend: ON")

        print(
            "1/X/2 probability: "
            f"Home {pred['home_win']:.2%} | Draw {pred['draw']:.2%} | Away {pred['away_win']:.2%}"
        )

        print(
            "Fair odds: "
            f"Home {pred['fair_odds']['home']:.2f} | "
            f"Draw {pred['fair_odds']['draw']:.2f} | "
            f"Away {pred['fair_odds']['away']:.2f}"
        )

        if pred["value_edge"] is not None:
            ve = pred["value_edge"]
            print(f"Value edge: Home {ve['home']:+.3f} | Draw {ve['draw']:+.3f} | Away {ve['away']:+.3f}")

        if pred["suppression_flag"]:
            print("\nSuppression signal: YES")
            print("This fixture has a higher chance of a tighter scoreline than the base model suggests.")

        print("\nTop scorelines:")
        for (hg, ag), p in pred["top_scores"][:5]:
            print(f"{hg}-{ag}  ({p:.2%})")
    else:
        print("\nRun a fixture like this:")
        print('python test.py "Valencia" "Real Madrid"')
        print('python test.py "Valencia" "Real Madrid" --home-odds 4.20 --draw-odds 3.10 --away-odds 1.85')
        print('python test.py --evaluate --cutoff-week 20')
        print('python test.py --evaluate --walk-forward')
        print('python test.py --calibrate')


if __name__ == "__main__":
    main()
