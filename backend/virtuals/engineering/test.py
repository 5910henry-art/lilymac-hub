import argparse
import itertools
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
    "betis": "Real Betis",
    "real betis": "Real Betis",
    "sevilla": "Sevilla",
    "leganes": "Leganes",
    "mallorca": "Mallorca",
    "celta vigo": "Celta Vigo",
    "celtavigo": "Celta Vigo",
    "celta": "Celta Vigo",
}


def normalize_team(name: str) -> str:
    raw = str(name).strip()
    raw = raw.split("(")[0].strip()
    key = raw.lower().replace(".", "").replace("-", " ").replace("_", " ")
    key = " ".join(key.split())
    key_compact = key.replace(" ", "")

    mapped = TEAM_ALIASES.get(key) or TEAM_ALIASES.get(key_compact)
    if mapped:
        return mapped
    return key.title()


# =========================================================
# LOAD / PREP DATA
# =========================================================
def load_data(path: str = "result_clean.csv") -> pd.DataFrame:
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
# TEAM STATS + CLASSIFICATION
# =========================================================
def _style_from_metrics(
    attack: float,
    defense: float,
    win_rate: float,
    draw_rate: float,
    clean_rate: float,
    failed_rate: float,
    volatility: float,
    team_score: float,
) -> str:
    if attack >= 1.55 and defense <= 1.05 and win_rate >= 0.50:
        return "Elite"
    if draw_rate >= 0.35 and attack <= 1.28:
        return "Draw/Passive"
    if defense >= 1.45 or volatility >= 1.15:
        return "Chaotic/Weak Defense"
    if team_score >= 0.72:
        return "Strong"
    if team_score >= 0.20:
        return "Balanced"
    return "Weak"


def build_team_stats(frame: pd.DataFrame) -> pd.DataFrame:
    teams = sorted(pd.unique(frame[["home_team", "away_team"]].values.ravel("K")))
    rows = []

    for team in teams:
        home = frame[frame["home_team"] == team]
        away = frame[frame["away_team"] == team]
        played_home = len(home)
        played_away = len(away)
        played = played_home + played_away

        home_scored = home["home_goals"].sum() if played_home else 0
        home_conceded = home["away_goals"].sum() if played_home else 0
        away_scored = away["away_goals"].sum() if played_away else 0
        away_conceded = away["home_goals"].sum() if played_away else 0

        goals_scored = int(home_scored + away_scored)
        goals_conceded = int(home_conceded + away_conceded)

        wins = (home["home_goals"] > home["away_goals"]).sum() + (away["away_goals"] > away["home_goals"]).sum()
        draws = (home["home_goals"] == home["away_goals"]).sum() + (away["away_goals"] == away["home_goals"]).sum()
        losses = played - wins - draws

        home_wins = (home["home_goals"] > home["away_goals"]).sum()
        home_draws = (home["home_goals"] == home["away_goals"]).sum()
        home_losses = played_home - home_wins - home_draws

        away_wins = (away["away_goals"] > away["home_goals"]).sum()
        away_draws = (away["away_goals"] == away["home_goals"]).sum()
        away_losses = played_away - away_wins - away_draws

        clean_sheets = (home["away_goals"] == 0).sum() + (away["home_goals"] == 0).sum()
        failed_to_score = (home["home_goals"] == 0).sum() + (away["away_goals"] == 0).sum()

        home_attack = home["home_goals"].mean() if played_home else 0.0
        home_defense = home["away_goals"].mean() if played_home else 0.0
        away_attack = away["away_goals"].mean() if played_away else 0.0
        away_defense = away["home_goals"].mean() if played_away else 0.0

        attack = goals_scored / played if played else 0.0
        defense = goals_conceded / played if played else 0.0
        win_rate = wins / played if played else 0.0
        draw_rate = draws / played if played else 0.0
        loss_rate = losses / played if played else 0.0
        home_win_rate = home_wins / played_home if played_home else 0.0
        away_win_rate = away_wins / played_away if played_away else 0.0
        home_draw_rate = home_draws / played_home if played_home else 0.0
        away_draw_rate = away_draws / played_away if played_away else 0.0
        home_loss_rate = home_losses / played_home if played_home else 0.0
        away_loss_rate = away_losses / played_away if played_away else 0.0

        scored_list = list(home["home_goals"]) + list(away["away_goals"])
        conceded_list = list(home["away_goals"]) + list(away["home_goals"])

        scored_vol = pd.Series(scored_list).std(ddof=0) if len(scored_list) > 1 else 0.0
        conceded_vol = pd.Series(conceded_list).std(ddof=0) if len(conceded_list) > 1 else 0.0
        volatility = (scored_vol + conceded_vol) / 2.0

        failed_rate = failed_to_score / played if played else 0.0
        clean_rate = clean_sheets / played if played else 0.0
        goal_diff = (goals_scored - goals_conceded) / played if played else 0.0

        team_score = (
            (1.00 * attack)
            - (0.78 * defense)
            + (0.55 * win_rate)
            - (0.18 * draw_rate)
            + (0.20 * clean_rate)
            - (0.28 * failed_rate)
            + (0.08 * goal_diff)
            - (0.12 * volatility)
        )

        overall_style = _style_from_metrics(
            attack=attack,
            defense=defense,
            win_rate=win_rate,
            draw_rate=draw_rate,
            clean_rate=clean_rate,
            failed_rate=failed_rate,
            volatility=volatility,
            team_score=team_score,
        )

        home_team_score = (
            (1.00 * home_attack)
            - (0.82 * home_defense)
            + (0.48 * home_win_rate)
            - (0.20 * home_draw_rate)
            - (0.12 * home_loss_rate)
            + (0.10 * clean_rate)
            - (0.10 * failed_rate)
        )
        away_team_score = (
            (1.00 * away_attack)
            - (0.82 * away_defense)
            + (0.48 * away_win_rate)
            - (0.20 * away_draw_rate)
            - (0.12 * away_loss_rate)
            + (0.10 * clean_rate)
            - (0.10 * failed_rate)
        )

        home_style = _style_from_metrics(
            attack=home_attack,
            defense=home_defense,
            win_rate=home_win_rate,
            draw_rate=home_draw_rate,
            clean_rate=clean_rate,
            failed_rate=failed_rate,
            volatility=volatility,
            team_score=home_team_score,
        )
        away_style = _style_from_metrics(
            attack=away_attack,
            defense=away_defense,
            win_rate=away_win_rate,
            draw_rate=away_draw_rate,
            clean_rate=clean_rate,
            failed_rate=failed_rate,
            volatility=volatility,
            team_score=away_team_score,
        )

        rows.append(
            {
                "team": team,
                "matches": played,
                "home_matches": played_home,
                "away_matches": played_away,
                "goals_scored": goals_scored,
                "goals_conceded": goals_conceded,
                "attack": attack,
                "defense": defense,
                "home_attack": home_attack,
                "home_defense": home_defense,
                "away_attack": away_attack,
                "away_defense": away_defense,
                "win_rate": win_rate,
                "draw_rate": draw_rate,
                "loss_rate": loss_rate,
                "home_win_rate": home_win_rate,
                "home_draw_rate": home_draw_rate,
                "home_loss_rate": home_loss_rate,
                "away_win_rate": away_win_rate,
                "away_draw_rate": away_draw_rate,
                "away_loss_rate": away_loss_rate,
                "goal_diff": int(goals_scored - goals_conceded),
                "clean_sheets": int(clean_sheets),
                "failed_to_score": int(failed_to_score),
                "failed_rate": failed_rate,
                "clean_rate": clean_rate,
                "scored_vol": scored_vol,
                "conceded_vol": conceded_vol,
                "volatility": volatility,
                "team_score": team_score,
                "style": overall_style,
                "home_style": home_style,
                "away_style": away_style,
            }
        )

    return pd.DataFrame(rows)


# =========================================================
# POISSON / MODEL PARAMS
# =========================================================
@dataclass(frozen=True)
class ModelParams:
    attack_share: float = 0.64
    home_adv: float = 0.12
    away_bias: float = 0.03
    draw_gap_boost: float = 0.10
    draw_low_total_boost: float = 0.04
    temp: float = 1.30
    draw_cap: float = 0.14
    chaos_temp_add: float = 0.15
    home_form_weight: float = 0.70
    away_form_weight: float = 0.70
    defensive_pressure_cut: float = 0.10


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
    weight: float = 0.65,
) -> Tuple[float, float, float]:
    mw = max(0.0, min(1.0, weight))
    blended = tuple((mw * m) + ((1.0 - mw) * o) for m, o in zip(model_probs, market_probs))
    s = sum(blended)
    return tuple(p / s for p in blended) if s > 0 else blended


def soften_probs(probs: Tuple[float, float, float], temp: float = 1.30) -> Tuple[float, float, float]:
    temp = max(1.0, float(temp))
    softened = [max(p, 1e-12) ** (1.0 / temp) for p in probs]
    s = sum(softened)
    return tuple(p / s for p in softened) if s > 0 else probs


# =========================================================
# FIT PARAMETERS AUTOMATICALLY
# =========================================================
def internal_split_by_week(frame: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    weeks = sorted(frame["week"].unique())
    if len(weeks) < 6:
        cutoff = int(frame["week"].median())
    else:
        cutoff = weeks[max(1, int(len(weeks) * 0.8)) - 1]

    train = frame[frame["week"] <= cutoff].copy()
    valid = frame[frame["week"] > cutoff].copy()

    if len(valid) == 0:
        cutoff = int(frame["week"].median())
        train = frame[frame["week"] <= cutoff].copy()
        valid = frame[frame["week"] > cutoff].copy()

    return train, valid


def fit_params(train_frame: pd.DataFrame) -> ModelParams:
    train, valid = internal_split_by_week(train_frame)
    if len(train) == 0 or len(valid) == 0:
        return ModelParams()

    stats = build_team_stats(train)
    stats_map = stats.set_index("team").to_dict("index")

    attack_share_grid = [0.58, 0.64, 0.70]
    home_adv_grid = [0.08, 0.12, 0.16]
    draw_boost_grid = [0.08, 0.10, 0.12]
    temp_grid = [1.20, 1.30, 1.40]
    form_grid = [0.60, 0.70, 0.80]

    best_loss = float("inf")
    best = ModelParams()

    for attack_share, home_adv, draw_gap_boost, temp, home_form_weight, away_form_weight in itertools.product(
        attack_share_grid, home_adv_grid, draw_boost_grid, temp_grid, form_grid, form_grid
    ):
        params = ModelParams(
            attack_share=attack_share,
            home_adv=home_adv,
            away_bias=0.03,
            draw_gap_boost=draw_gap_boost,
            draw_low_total_boost=0.04,
            temp=temp,
            draw_cap=0.14,
            chaos_temp_add=0.15,
            home_form_weight=home_form_weight,
            away_form_weight=away_form_weight,
            defensive_pressure_cut=0.10,
        )

        loss, n = evaluate_params_on_frame(valid, stats_map, params)
        if n > 0:
            avg_loss = loss / n
            if avg_loss < best_loss:
                best_loss = avg_loss
                best = params

    return best


# =========================================================
# MODEL CORE
# =========================================================
def estimate_lambdas(home_team: str, away_team: str, stats_map: Dict[str, dict], params: ModelParams) -> Tuple[float, float]:
    h = stats_map[home_team]
    a = stats_map[away_team]

    home_attack_base = (params.home_form_weight * h["home_attack"]) + ((1.0 - params.home_form_weight) * h["attack"])
    away_defense_base = (params.away_form_weight * a["away_defense"]) + ((1.0 - params.away_form_weight) * a["defense"])

    away_attack_base = (params.away_form_weight * a["away_attack"]) + ((1.0 - params.away_form_weight) * a["attack"])
    home_defense_base = (params.home_form_weight * h["home_defense"]) + ((1.0 - params.home_form_weight) * h["defense"])

    base_home = (params.attack_share * home_attack_base) + ((1.0 - params.attack_share) * away_defense_base)
    base_away = (params.attack_share * away_attack_base) + ((1.0 - params.attack_share) * home_defense_base)

    split_home = (h["home_attack"] + a["away_defense"]) / 2.0
    split_away = (a["away_attack"] + h["home_defense"]) / 2.0

    home_xg = (0.58 * base_home) + (0.42 * split_home)
    away_xg = (0.58 * base_away) + (0.42 * split_away)

    # Home advantage and slight away correction.
    home_xg += params.home_adv
    away_xg += params.away_bias

    strong = {"Elite", "Strong"}
    passive = {"Draw/Passive", "Balanced"}
    chaotic = {"Chaotic/Weak Defense"}

    if h["home_style"] in strong and a["away_style"] in passive:
        home_xg += 0.08
    if a["away_style"] in strong and h["home_style"] in passive:
        away_xg += 0.08

    if h["style"] in chaotic and a["style"] in chaotic:
        home_xg -= 0.04
        away_xg -= 0.04

    if h["style"] == "Draw/Passive" and a["style"] == "Draw/Passive":
        home_xg -= 0.18
        away_xg -= 0.18

    # Defensive pressure from current schema, no stale suppression key.
    home_pressure = h["home_defense"] * (1.0 + h["failed_rate"] + 0.50 * h["volatility"])
    away_pressure = a["away_defense"] * (1.0 + a["failed_rate"] + 0.50 * a["volatility"])

    if away_pressure >= 1.50:
        home_xg -= params.defensive_pressure_cut
    if home_pressure >= 1.50:
        away_xg -= params.defensive_pressure_cut

    if h["attack"] < 1.20 and a["attack"] < 1.20:
        home_xg -= 0.18
        away_xg -= 0.18

    if h["failed_rate"] >= 0.25 and a["failed_rate"] >= 0.25:
        home_xg -= 0.10
        away_xg -= 0.10

    # When one side is poor at finishing and the other is strong defensively, tighten the match.
    if (away_pressure >= 1.55 and h["failed_rate"] >= 0.25) or (home_pressure >= 1.55 and a["failed_rate"] >= 0.25):
        home_xg -= 0.10
        away_xg -= 0.10

    if h["style"] == "Elite" and a["style"] == "Elite":
        home_xg -= 0.06
        away_xg -= 0.06

    return clamp(home_xg), clamp(away_xg)


def scoreline_probs(home_lam: float, away_lam: float, max_goals: int = 8) -> Dict[Tuple[int, int], float]:
    probs = {}
    for hg in range(max_goals + 1):
        for ag in range(max_goals + 1):
            probs[(hg, ag)] = poisson_pmf(hg, home_lam) * poisson_pmf(ag, away_lam)

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


def draw_boost_from_style(h: dict, a: dict, home_lam: float, away_lam: float, params: ModelParams) -> float:
    boost = 0.0

    if h["style"] in ["Draw/Passive", "Balanced"] and a["style"] in ["Draw/Passive", "Balanced"]:
        boost += 0.05

    if h["style"] == "Draw/Passive" and a["style"] == "Draw/Passive":
        boost += 0.06

    gap = abs(home_lam - away_lam)
    boost += params.draw_gap_boost * math.exp(-3.2 * gap)

    if (home_lam + away_lam) < 2.4:
        boost += params.draw_low_total_boost

    if h["style"] in ["Strong", "Elite"] and a["style"] in ["Draw/Passive", "Balanced"]:
        boost += 0.02
    if a["style"] in ["Strong", "Elite"] and h["style"] in ["Draw/Passive", "Balanced"]:
        boost += 0.02

    return min(boost, params.draw_cap)


def estimate_temp(base_temp: float, h: dict, a: dict, params: ModelParams) -> float:
    temp = max(1.0, float(base_temp))
    max_vol = max(h["scored_vol"], h["conceded_vol"], a["scored_vol"], a["conceded_vol"])

    if max_vol >= 1.20:
        temp += 0.10
    if h["style"] == "Chaotic/Weak Defense" or a["style"] == "Chaotic/Weak Defense":
        temp += params.chaos_temp_add

    return temp


def predict_match(
    home_team: str,
    away_team: str,
    stats_map: Dict[str, dict],
    params: ModelParams,
    market_odds: Optional[Tuple[float, float, float]] = None,
    market_weight: float = 0.65,
):
    home_team = normalize_team(home_team)
    away_team = normalize_team(away_team)

    if home_team not in stats_map:
        raise ValueError(f"Unknown home team: {home_team}")
    if away_team not in stats_map:
        raise ValueError(f"Unknown away team: {away_team}")

    h = stats_map[home_team]
    a = stats_map[away_team]

    home_lam, away_lam = estimate_lambdas(home_team, away_team, stats_map, params)
    effective_temp = estimate_temp(params.temp, h, a, params)

    probs = scoreline_probs(home_lam, away_lam, max_goals=8)
    hw, dr, aw = result_probs(probs)
    hw, dr, aw = soften_probs((hw, dr, aw), temp=effective_temp)

    draw_boost = draw_boost_from_style(h, a, home_lam, away_lam, params)
    if draw_boost > 0:
        dr += draw_boost
        hw -= draw_boost / 2.0
        aw -= draw_boost / 2.0

    hw = max(hw, 1e-12)
    dr = max(dr, 1e-12)
    aw = max(aw, 1e-12)
    s = hw + dr + aw
    hw, dr, aw = hw / s, dr / s, aw / s

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

    home_pressure = h["home_defense"] * (1.0 + h["failed_rate"] + 0.50 * h["volatility"])
    away_pressure = a["away_defense"] * (1.0 + a["failed_rate"] + 0.50 * a["volatility"])

    pressure_flag = (
        (h["failed_rate"] >= 0.25 and away_pressure > 1.40)
        or (a["failed_rate"] >= 0.25 and home_pressure > 1.40)
        or (h["attack"] < 1.20 and a["attack"] < 1.20)
    )

    value_edge = None
    if market_probs is not None:
        value_edge = {
            "home": hw - market_probs[0],
            "draw": dr - market_probs[1],
            "away": aw - market_probs[2],
        }

    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_style": h["home_style"],
        "away_style": a["away_style"],
        "overall_home_style": h["style"],
        "overall_away_style": a["style"],
        "home_lambda": home_lam,
        "away_lambda": away_lam,
        "home_win": hw,
        "draw": dr,
        "away_win": aw,
        "likely_type": likely_type,
        "top_scores": ranked,
        "total_goals": total_goals,
        "pressure_flag": pressure_flag,
        "market_used": market_odds is not None,
        "market_probs": market_probs,
        "value_edge": value_edge,
        "effective_temp": effective_temp,
    }


# =========================================================
# EVALUATION
# =========================================================
def evaluate_params_on_frame(frame: pd.DataFrame, stats_map: Dict[str, dict], params: ModelParams) -> Tuple[float, int]:
    loss = 0.0
    n = 0

    for _, row in frame.iterrows():
        home = row["home_team"]
        away = row["away_team"]
        if home not in stats_map or away not in stats_map:
            continue

        pred = predict_match(home, away, stats_map, params)
        actual = row["result"]

        p_home = float(pred["home_win"])
        p_draw = float(pred["draw"])
        p_away = float(pred["away_win"])

        if actual == "H":
            p = p_home
        elif actual == "D":
            p = p_draw
        else:
            p = p_away

        loss += -math.log(max(p, 1e-12))
        n += 1

    return loss, n


def evaluate_model(
    frame: pd.DataFrame,
    cutoff_week: Optional[int] = None,
    walk_forward: bool = False,
    market_weight: float = 0.65,
) -> None:
    df_all = frame.sort_values(["week", "home_team", "away_team"]).reset_index(drop=True)
    rows = []

    if walk_forward:
        weeks = sorted(df_all["week"].unique())
        for wk in weeks:
            test_week = df_all[df_all["week"] == wk]
            train_week = df_all[df_all["week"] < wk]

            if len(train_week) == 0 or len(test_week) == 0:
                continue

            params = fit_params(train_week)
            stats = build_team_stats(train_week)
            stats_map = stats.set_index("team").to_dict("index")

            for _, row in test_week.iterrows():
                home = row["home_team"]
                away = row["away_team"]
                if home not in stats_map or away not in stats_map:
                    continue

                pred = predict_match(home, away, stats_map, params, market_weight=market_weight)
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
    else:
        if cutoff_week is None:
            cutoff_week = int(df_all["week"].median())

        train = df_all[df_all["week"] <= cutoff_week].copy()
        test = df_all[df_all["week"] > cutoff_week].copy()

        if len(train) == 0 or len(test) == 0:
            raise ValueError("Train/test split produced an empty side. Adjust cutoff_week.")

        params = fit_params(train)
        stats = build_team_stats(train)
        stats_map = stats.set_index("team").to_dict("index")

        for _, row in test.iterrows():
            home = row["home_team"]
            away = row["away_team"]
            if home not in stats_map or away not in stats_map:
                continue

            pred = predict_match(home, away, stats_map, params, market_weight=market_weight)
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

        pair_key = f"{r['home_style']} | {r['away_style']}"
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
        pd.DataFrame(conf)
        .T.reindex(index=["H", "D", "A"], columns=["H", "D", "A"])
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


# =========================================================
# DISPLAY
# =========================================================
def print_team_table(team_df: pd.DataFrame) -> None:
    pd.set_option("display.width", 180)
    pd.set_option("display.max_columns", 80)

    print("\n=== TEAM BEHAVIOR ===\n")
    print(
        team_df.sort_values(["style", "team_score"], ascending=[True, False])[
            [
                "team",
                "style",
                "home_style",
                "away_style",
                "team_score",
                "attack",
                "defense",
                "home_attack",
                "home_defense",
                "away_attack",
                "away_defense",
                "win_rate",
                "draw_rate",
                "loss_rate",
                "home_win_rate",
                "away_win_rate",
                "goal_diff",
                "clean_rate",
                "failed_rate",
                "volatility",
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
    parser.add_argument("--data", default="result_clean.csv", help="Path to cleaned CSV file")
    parser.add_argument("--home-odds", type=float, default=None, help="Decimal home odds")
    parser.add_argument("--draw-odds", type=float, default=None, help="Decimal draw odds")
    parser.add_argument("--away-odds", type=float, default=None, help="Decimal away odds")
    parser.add_argument("--market-weight", type=float, default=0.65, help="Blend weight for model vs market")
    parser.add_argument("--evaluate", action="store_true", help="Run evaluation instead of a single fixture")
    parser.add_argument("--cutoff-week", type=int, default=None, help="Train on weeks <= cutoff and test on later weeks")
    parser.add_argument("--walk-forward", action="store_true", help="Use walk-forward evaluation by week")
    args = parser.parse_args()

    df = load_data(args.data)

    if args.evaluate:
        evaluate_model(
            df,
            cutoff_week=args.cutoff_week,
            walk_forward=args.walk_forward,
            market_weight=args.market_weight,
        )
        return

    team_df = build_team_stats(df)
    stats_map = team_df.set_index("team").to_dict("index")
    params = fit_params(df)

    print_team_table(team_df)

    team_df.to_csv("team_behavior_final.csv", index=False)
    print("\nSaved: team_behavior_final.csv")
    print(
        f"\nAuto-fit params: attack_share={params.attack_share:.2f}, "
        f"home_adv={params.home_adv:.2f}, draw_gap_boost={params.draw_gap_boost:.2f}, "
        f"temp={params.temp:.2f}, home_form_weight={params.home_form_weight:.2f}, "
        f"away_form_weight={params.away_form_weight:.2f}"
    )

    if args.home and args.away:
        market_odds = None
        if args.home_odds is not None and args.draw_odds is not None and args.away_odds is not None:
            market_odds = (args.home_odds, args.draw_odds, args.away_odds)

        pred = predict_match(
            args.home,
            args.away,
            stats_map=stats_map,
            params=params,
            market_odds=market_odds,
            market_weight=args.market_weight,
        )

        print("\n=== FIXTURE PREDICTION ===\n")
        print(f"{pred['home_team']} ({pred['home_style']}) vs {pred['away_team']} ({pred['away_style']})")
        print(f"Expected goals: {pred['home_lambda']:.2f} - {pred['away_lambda']:.2f}")
        print(f"Game type: {pred['likely_type']}")
        print(f"Effective temp: {pred['effective_temp']:.2f}")

        if pred["market_used"]:
            print("Market blend: ON")

        print(
            "1/X/2 probability: "
            f"Home {pred['home_win']:.2%} | Draw {pred['draw']:.2%} | Away {pred['away_win']:.2%}"
        )

        if pred["value_edge"] is not None:
            ve = pred["value_edge"]
            print(f"Value edge: Home {ve['home']:+.3f} | Draw {ve['draw']:+.3f} | Away {ve['away']:+.3f}")

        if pred["pressure_flag"]:
            print("\nPressure signal: YES")
            print("This fixture looks tighter than the base model suggests.")

        print("\nTop scorelines:")
        for (hg, ag), p in pred["top_scores"][:5]:
            print(f"{hg}-{ag}  ({p:.2%})")
    else:
        print("\nRun a fixture like this:")
        print('python test.py "Valencia" "Real Madrid"')
        print('python test.py "Valencia" "Real Madrid" --home-odds 4.20 --draw-odds 3.10 --away-odds 1.85')
        print('python test.py --evaluate --cutoff-week 20')
        print('python test.py --evaluate --walk-forward')


if __name__ == "__main__":
    main()
