#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Optional, List, Sequence, Tuple

import numpy as np

EPS = 1e-12
SMOOTH_EPS = 1e-8

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL_PATH = os.path.join(BASE_DIR, "model.json")
DEFAULT_FIXTURES_PATH = os.path.join(BASE_DIR, "fixtures.txt")

# Draw shaping parameters
DRAW_SHAPE_AMP = 0.35
DRAW_SHAPE_BETA = 2.5
DRAW_CAP = 0.35  # smooth upper bound for draw probability

# Market bias exponents
HOME_BIAS_EXP = 0.985
DRAW_BIAS_EXP = 1.020
AWAY_BIAS_EXP = 1.035


@dataclass
class Fixture:
    home: str
    away: str
    home_odds: float
    draw_odds: float
    away_odds: float
    target_probs: np.ndarray
    overround: float
    result: Optional[int] = None


_TEAM_ALIAS = {
    "barca": "Barcelona",
    "barsa": "Barcelona",
    "r. madrid": "Real Madrid",
    "real madrid": "Real Madrid",
    "a. madrid": "Atletico Madrid",
    "atletico madrid": "Atletico Madrid",
    "atleti": "Atletico Madrid",
    "a. bilbao": "Athletic Bilbao",
    "athletic bilbao": "Athletic Bilbao",
    "r. sociedad": "Real Sociedad",
    "real sociedad": "Real Sociedad",
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
    "atletico madrid": "Atletico Madrid",
    "athletic club": "Athletic Bilbao",
}

_RESULT_MAP = {"1": 0, "H": 0, "HOME": 0, "X": 1, "D": 1, "DRAW": 1, "2": 2, "A": 2, "AWAY": 2}


def normalize_team_name(name: str) -> str:
    name = str(name).strip()
    name = re.sub(r"\s+", " ", name)
    m = re.search(r"\(([^)]+)\)", name)
    if m:
        name = m.group(1).strip()
    key = name.lower()
    return _TEAM_ALIAS.get(key, _TEAM_ALIAS.get(name, name))


def parse_result_token(token: str) -> Optional[int]:
    t = re.sub(r"[^A-Z0-9_]+", "", token.strip().upper())
    return _RESULT_MAP.get(t)


def _parse_pipe_line(line: str):
    parts = [p.strip() for p in line.split("|") if p.strip()]
    if len(parts) < 5:
        raise ValueError("bad pipe format")
    home = normalize_team_name(parts[0])
    away = normalize_team_name(parts[1])
    home_odds = float(parts[2])
    draw_odds = float(parts[3])
    away_odds = float(parts[4])
    result = parse_result_token(parts[5]) if len(parts) >= 6 else None
    return home, away, home_odds, draw_odds, away_odds, result


def _parse_vs_line(line: str):
    m = re.match(r"^(.+?)\s+vs\s+(.+?)\s+[\u2014\u2013-]\s+(.+)$", line)
    if not m:
        raise ValueError("not vs format")
    home = normalize_team_name(m.group(1))
    away = normalize_team_name(m.group(2))
    odds_part = m.group(3)
    o1 = re.search(r"1:\s*([\d.]+)", odds_part)
    ox = re.search(r"X:\s*([\d.]+)", odds_part)
    o2 = re.search(r"2:\s*([\d.]+)", odds_part)
    r = re.search(r"(?:result|winner|outcome)[:=]\s*([A-Za-z0-9_]+)", odds_part)
    if not (o1 and ox and o2):
        raise ValueError("missing odds")
    result = parse_result_token(r.group(1)) if r else None
    return home, away, float(o1.group(1)), float(ox.group(1)), float(o2.group(1)), result


def _parse_fallback_line(line: str):
    m = re.match(
        r"^(?P<prefix>.*?)(?:\s{2,}|\t+|,\s*)(?P<away>.*?)(?:\s{2,}|\t+|,\s*)"
        r"(?P<ho>\d+(?:\.\d+)?)\s+(?P<do>\d+(?:\.\d+)?)\s+(?P<ao>\d+(?:\.\d+)?)(?:\s+(?P<res>[A-Za-z0-9_]+))?\s*$",
        line,
    )
    if not m:
        raise ValueError("bad format")
    result = parse_result_token(m.group("res")) if m.group("res") else None
    return (
        normalize_team_name(m.group("prefix")),
        normalize_team_name(m.group("away")),
        float(m.group("ho")),
        float(m.group("do")),
        float(m.group("ao")),
        result,
    )


def parse_line(line: str):
    line = line.strip()
    if not line or line.lower().startswith("home"):
        raise ValueError("skip")
    if "|" in line and "vs" not in line:
        return _parse_pipe_line(line)
    if "vs" in line:
        return _parse_vs_line(line)
    return _parse_fallback_line(line)


def load_fixtures(path: str):
    fixtures: List[Fixture] = []
    teams = set()
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            try:
                home, away, ho, do, ao, result = parse_line(raw_line)
            except ValueError:
                continue
            inv = np.array([1.0 / ho, 1.0 / do, 1.0 / ao], dtype=float)
            overround = float(inv.sum())
            target_probs = inv / max(overround, EPS)
            fixtures.append(Fixture(home, away, ho, do, ao, target_probs, overround, result))
            teams.add(home)
            teams.add(away)
    return fixtures, sorted(teams)


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def contextual_base_draw(diff: float, base_draw: float) -> float:
    x = abs(diff)
    return base_draw * (1.0 + DRAW_SHAPE_AMP * math.exp(-DRAW_SHAPE_BETA * x))


def soft_draw_cap(raw_draw: float, cap: float = DRAW_CAP) -> float:
    z = raw_draw / max(cap, EPS)
    return cap * sigmoid(z)


def soft_draw_cap_derivative(raw_draw: float, cap: float = DRAW_CAP) -> float:
    z = raw_draw / max(cap, EPS)
    s = sigmoid(z)
    return s * (1.0 - s)


def predict_probs(r_home, r_away, home_adv, base_draw, draw_k, temp=1.0):
    diff = (r_home + home_adv) - r_away
    gap = abs(diff)

    p_home_core = sigmoid(diff / max(temp, EPS))

    draw_raw = contextual_base_draw(diff, base_draw)
    draw_raw = draw_raw * (1.0 + draw_k * math.exp(-2.2 * gap))
    p_draw = soft_draw_cap(draw_raw, DRAW_CAP)

    rem = 1.0 - p_draw
    p_home = rem * p_home_core
    p_away = rem * (1.0 - p_home_core)

    p_home = p_home ** HOME_BIAS_EXP
    p_draw = p_draw ** DRAW_BIAS_EXP
    p_away = p_away ** AWAY_BIAS_EXP

    probs = np.array([p_home, p_draw, p_away], dtype=float)
    probs = np.clip(probs, EPS, 1.0)
    probs /= probs.sum()
    return probs, diff, gap, p_home_core, p_draw


def probs_to_odds_with_overround(probs, overround):
    probs = np.array(probs, dtype=float)
    implied = probs * float(overround)
    return 1.0 / np.clip(implied, EPS, 1.0)


def odds_to_probs(odds: Sequence[float]) -> np.ndarray:
    odds_arr = np.array(list(odds), dtype=float)
    inv = 1.0 / np.clip(odds_arr, EPS, None)
    inv_sum = float(inv.sum())
    return inv / max(inv_sum, EPS)


def build_templates(fixtures) -> List[Tuple[float, float, float]]:
    templates = set()
    for fx in fixtures:
        templates.add((round(fx.home_odds, 2), round(fx.draw_odds, 2), round(fx.away_odds, 2)))
    return sorted(templates)


def find_closest_template(
    pred_probs: np.ndarray,
    templates: Sequence[Tuple[float, float, float]],
    metric: str = "12",
) -> Tuple[float, float, float]:
    if not templates:
        raise ValueError("no templates available")

    pred_probs = np.asarray(pred_probs, dtype=float)
    best_tpl = templates[0]
    best_dist = float("inf")

    for tpl in templates:
        tpl_probs = odds_to_probs(tpl)
        if metric == "log":
            dist = float(np.sum((np.log(pred_probs + EPS) - np.log(tpl_probs + EPS)) ** 2))
        else:
            dist = float(np.sum((pred_probs - tpl_probs) ** 2))

        if dist < best_dist:
            best_dist = dist
            best_tpl = tpl

    return best_tpl


def _adam_step(param, grad, m, v, t, lr):
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    m = beta1 * m + (1.0 - beta1) * grad
    v = beta2 * v + (1.0 - beta2) * (grad * grad)
    m_hat = m / (1.0 - beta1**t)
    v_hat = v / (1.0 - beta2**t)
    param -= lr * m_hat / (np.sqrt(v_hat) + eps)
    return param, m, v


def fit_bookmaker_model(
    fixtures,
    teams,
    lr=0.01,
    epochs=12000,
    reg=1e-4,
    draw_k_init=0.06,
    base_draw_init=0.24,
    temp_init=1.0,
):
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    ratings = np.zeros(n, dtype=float)
    home_adv = 0.25
    base_draw = float(base_draw_init)
    draw_k = float(draw_k_init)
    temp = float(temp_init)

    m_r = np.zeros(n, dtype=float)
    v_r = np.zeros(n, dtype=float)
    m_home = v_home = 0.0
    m_draw = v_draw = 0.0
    m_draw_k = v_draw_k = 0.0
    m_temp = v_temp = 0.0

    total = len(fixtures)

    for epoch in range(1, epochs + 1):
        grad_r = np.zeros(n, dtype=float)
        grad_home = 0.0
        grad_draw = 0.0
        grad_draw_k = 0.0
        grad_temp = 0.0
        loss = 0.0

        for fx in fixtures:
            h = idx[fx.home]
            a = idx[fx.away]

            pred, diff, gap, p_home_core, p_draw = predict_probs(
                ratings[h], ratings[a], home_adv, base_draw, draw_k, temp=temp
            )

            true_odds = np.array([fx.home_odds, fx.draw_odds, fx.away_odds], dtype=float)
            pred_odds = probs_to_odds_with_overround(pred, fx.overround)

            loss += float(np.sum((np.log(pred_odds + EPS) - np.log(true_odds + EPS)) ** 2))

            err_home = math.log(pred_odds[0] + EPS) - math.log(true_odds[0] + EPS)
            err_draw = math.log(pred_odds[1] + EPS) - math.log(true_odds[1] + EPS)
            err_away = math.log(pred_odds[2] + EPS) - math.log(true_odds[2] + EPS)

            dL_dp_home = -2.0 * err_home / max(pred[0], EPS)
            dL_dp_draw = -2.0 * err_draw / max(pred[1], EPS)
            dL_dp_away = -2.0 * err_away / max(pred[2], EPS)

            p = p_home_core
            ds_ddiff = p * (1.0 - p) / max(temp, EPS)

            exp_gap = math.exp(-2.2 * gap)
            draw_anchor = contextual_base_draw(diff, base_draw)

            abs_diff = abs(diff)
            sign_diff = 0.0 if abs_diff < EPS else (diff / abs_diff)
            shape_lift = math.exp(-DRAW_SHAPE_BETA * abs_diff)

            d_draw_anchor_ddiff = base_draw * DRAW_SHAPE_AMP * (-DRAW_SHAPE_BETA * shape_lift * sign_diff)
            d_draw_raw_ddiff = d_draw_anchor_ddiff * (1.0 + draw_k * exp_gap)
            d_draw_raw_ddiff += draw_anchor * (draw_k * (-2.2 * exp_gap * sign_diff))

            d_draw_raw_dbase = (1.0 + DRAW_SHAPE_AMP * shape_lift) * (1.0 + draw_k * exp_gap)
            d_draw_raw_ddk = draw_anchor * exp_gap

            draw_raw = draw_anchor * (1.0 + draw_k * exp_gap)
            dpdraw_ddraw = soft_draw_cap_derivative(draw_raw, DRAW_CAP)
            dpdraw_ddiff = dpdraw_ddraw * d_draw_raw_ddiff
            dpdraw_dbase = dpdraw_ddraw * d_draw_raw_dbase
            dpdraw_ddk = dpdraw_ddraw * d_draw_raw_ddk

            dL_dpcore = dL_dp_home * (1.0 - p_draw) - dL_dp_away * (1.0 - p_draw)
            dL_dpdraw = dL_dp_home * (-p_home_core) + dL_dp_away * (-(1.0 - p_home_core)) + dL_dp_draw

            grad_diff = dL_dpcore * ds_ddiff + dL_dpdraw * dpdraw_ddiff
            grad_r[h] += grad_diff
            grad_r[a] -= grad_diff
            grad_home += grad_diff
            grad_draw += dL_dpdraw * dpdraw_dbase
            grad_draw_k += dL_dpdraw * dpdraw_ddk
            grad_temp += dL_dpcore * (p * (1.0 - p)) * (-diff / max(temp * temp, EPS))

        loss += reg * float(np.sum(ratings * ratings))
        grad_r += 2.0 * reg * ratings

        loss += 0.25 * (base_draw - 0.26) ** 2
        loss += 0.35 * (draw_k - 0.06) ** 2
        loss += 0.01 * (temp - 1.0) ** 2
        grad_draw += 0.50 * (base_draw - 0.26)
        grad_draw_k += 0.70 * (draw_k - 0.06)
        grad_temp += 0.02 * (temp - 1.0)

        ratings, m_r, v_r = _adam_step(ratings, grad_r, m_r, v_r, epoch, lr)
        home_adv, m_home, v_home = _adam_step(home_adv, grad_home, m_home, v_home, epoch, lr)
        base_draw, m_draw, v_draw = _adam_step(base_draw, grad_draw, m_draw, v_draw, epoch, lr)
        draw_k, m_draw_k, v_draw_k = _adam_step(draw_k, grad_draw_k, m_draw_k, v_draw_k, epoch, lr)
        temp, m_temp, v_temp = _adam_step(temp, grad_temp, m_temp, v_temp, epoch, lr)

        ratings -= ratings.mean()
        base_draw = float(np.clip(base_draw, 0.05, 0.45))
        draw_k = float(np.clip(draw_k, 0.03, 0.12))
        temp = float(np.clip(temp, 0.85, 1.15))
        home_adv = float(np.clip(home_adv, -0.20, 0.40))

        if epoch % 500 == 0 or epoch == 1:
            print(
                f"Epoch {epoch} | loss {loss/total:.6f} | "
                f"base_draw {base_draw:.4f} | draw_k {draw_k:.4f} | temp {temp:.4f}"
            )

    return ratings, home_adv, base_draw, draw_k, temp, idx


def evaluate_results(fixtures, ratings, home_adv, base_draw, draw_k, temp, idx):
    n = correct = 0
    logloss = brier = 0.0
    for fx in fixtures:
        if fx.result is None:
            continue
        probs, *_ = predict_probs(
            ratings[idx[fx.home]], ratings[idx[fx.away]], home_adv, base_draw, draw_k, temp=temp
        )
        y = fx.result
        logloss += -math.log(float(probs[y]) + EPS)
        brier += float(np.sum((probs - np.eye(3)[y]) ** 2))
        correct += int(int(np.argmax(probs)) == y)
        n += 1
    if n == 0:
        return None
    return {"matches": n, "accuracy": correct / n, "logloss": logloss / n, "brier": brier / n}


def _resolve_model_path(path: Optional[str]) -> str:
    if not path:
        return DEFAULT_MODEL_PATH
    if os.path.isabs(path):
        return path
    candidate = os.path.join(BASE_DIR, path)
    if os.path.exists(candidate):
        return candidate
    return os.path.abspath(path)


def load_model(path: str = DEFAULT_MODEL_PATH):
    path = _resolve_model_path(path)
    with open(path, "r", encoding="utf-8") as f:
        m = json.load(f)

    ratings = m["ratings"]
    teams = list(ratings.keys())

    idx = {t: i for i, t in enumerate(teams)}
    rating_arr = np.array([ratings[t] for t in teams], dtype=float)

    home_adv = m["home_adv"]
    base_draw = m["base_draw"]
    draw_k = m["draw_k"]
    temp = m["temp"]
    templates = [tuple(x) for x in m["templates"]]

    return rating_arr, idx, home_adv, base_draw, draw_k, temp, templates


def generate_odds(home, away, model_path: Optional[str] = None):
    ratings, idx, home_adv, base_draw, draw_k, temp, templates = load_model(model_path or DEFAULT_MODEL_PATH)

    if home not in idx or away not in idx:
        raise ValueError("Unknown team")

    probs, *_ = predict_probs(
        ratings[idx[home]],
        ratings[idx[away]],
        home_adv,
        base_draw,
        draw_k,
        temp=temp
    )

    odds = find_closest_template(probs, templates, metric="log")

    return {
        "home_prob": float(probs[0]),
        "draw_prob": float(probs[1]),
        "away_prob": float(probs[2]),
        "home_odds": float(odds[0]),
        "draw_odds": float(odds[1]),
        "away_odds": float(odds[2]),
        "probs": probs.tolist()
    }


def main():
    parser = argparse.ArgumentParser(description="Reverse bookmaker odds from 1X2 market prices.")
    parser.add_argument("path", nargs="?", default=DEFAULT_FIXTURES_PATH, help="Input fixtures file")
    parser.add_argument("--lr", type=float, default=0.01)
    parser.add_argument("--epochs", type=int, default=12000)
    parser.add_argument("--reg", type=float, default=1e-4)
    parser.add_argument("--draw-k", type=float, default=0.06)
    parser.add_argument("--base-draw", type=float, default=0.24)
    parser.add_argument("--temp", type=float, default=1.0)
    parser.add_argument("--model-out", default=DEFAULT_MODEL_PATH)
    parser.add_argument("--preview", type=int, default=10)
    args = parser.parse_args()

    fixtures, teams = load_fixtures(args.path)
    if not fixtures:
        raise SystemExit(f"No fixtures parsed from {args.path}")

    templates = build_templates(fixtures)
    print(f"Templates found: {len(templates)}")
    print("Snap mode: ALWAYS ON")

    ratings, home_adv, base_draw, draw_k, temp, idx = fit_bookmaker_model(
        fixtures,
        teams,
        lr=args.lr,
        epochs=args.epochs,
        reg=args.reg,
        draw_k_init=args.draw_k,
        base_draw_init=args.base_draw,
        temp_init=args.temp,
    )

    print("\nDONE")
    print("Teams:", len(teams))
    print("Fixtures:", len(fixtures))
    print(f"home_adv: {home_adv:.6f}")
    print(f"base_draw: {base_draw:.6f}")
    print(f"draw_k: {draw_k:.6f}")
    print(f"temp: {temp:.6f}")

    print("\nReconstruction check:")
    for fx in fixtures[: max(1, args.preview)]:
        probs, *_ = predict_probs(
            ratings[idx[fx.home]], ratings[idx[fx.away]], home_adv, base_draw, draw_k, temp=temp
        )
        pred_odds = find_closest_template(probs, templates, metric="log")

        print(f"{fx.home} vs {fx.away}")
        print("Bookmaker: %.2f %.2f %.2f" % (fx.home_odds, fx.draw_odds, fx.away_odds))
        print("Model:     %.2f %.2f %.2f" % tuple(pred_odds))
        print()

    metrics = evaluate_results(fixtures, ratings, home_adv, base_draw, draw_k, temp, idx)
    if metrics is not None:
        print("\nResult validation:")
        print(f"matches: {metrics['matches']}")
        print(f"accuracy: {metrics['accuracy']:.4f}")
        print(f"logloss: {metrics['logloss']:.6f}")
        print(f"brier: {metrics['brier']:.6f}")
    else:
        print("\nResult validation: no result labels found in input")

    model = {
        "ratings": {team: float(ratings[idx[team]]) for team in idx},
        "home_adv": float(home_adv),
        "base_draw": float(base_draw),
        "draw_k": float(draw_k),
        "temp": float(temp),
        "templates": [list(t) for t in templates],
        "snap_templates": True,
    }
    with open(args.model_out, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    print(f"\nModel saved to {args.model_out}")


if __name__ == "__main__":
    main()
