from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple, Dict


# =========================================================
# HELPERS
# =========================================================

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def tanh01(x: float) -> float:
    return math.tanh(x)


def normalize_rating(r: float, scale: str = "auto") -> float:
    """
    Converts ratings into a stable internal scale.

    - If 0–100 → convert to pseudo-ELO (×20 + 1000)
    - If already large (>300) → assume ELO and return as-is
    """
    if scale == "elo":
        return r
    if scale == "0-100":
        return r * 20 + 1000
    # auto-detect
    return r * 20 + 1000 if r <= 100 else r


# =========================================================
# CONFIG
# =========================================================

@dataclass(frozen=True)
class OddsConfig:
    home_adv: float = 45.0  # Elo-equivalent home boost

    overround: float = 1.06

    draw_floor: float = 0.21
    draw_peak: float = 0.06
    draw_scale: float = 400.0
    draw_curve: float = 1.35

    home_win_scale: float = 400.0
    away_win_scale: float = 420.0

    home_cap: float = 0.86
    away_cap: float = 0.65


DEFAULT_CONFIG = OddsConfig()


# =========================================================
# CORE MODEL
# =========================================================

def _draw_probability(abs_gap: float, cfg: OddsConfig) -> float:
    draw = cfg.draw_floor + cfg.draw_peak * math.exp(
        -((abs_gap / cfg.draw_scale) ** cfg.draw_curve)
    )
    return clamp(draw, 0.18, 0.30)


def _win_split(gap: float, cfg: OddsConfig) -> Tuple[float, float]:
    if gap >= 0:
        home = 0.5 + 0.5 * tanh01(gap / cfg.home_win_scale)
        home = clamp(home, 0.50, cfg.home_cap)
        away = 1 - home
    else:
        away = 0.5 + 0.5 * tanh01(abs(gap) / cfg.away_win_scale)
        away = clamp(away, 0.50, cfg.away_cap)
        home = 1 - away

    return home, away


def probabilities_v3_1(
    home_rating: float,
    away_rating: float,
    rating_scale: str = "auto",
    cfg: OddsConfig = DEFAULT_CONFIG,
) -> Dict[str, float]:

    home = normalize_rating(home_rating, rating_scale)
    away = normalize_rating(away_rating, rating_scale)

    gap = (home + cfg.home_adv) - away
    abs_gap = abs(gap)

    draw = _draw_probability(abs_gap, cfg)
    win_mass = 1 - draw

    home_share, away_share = _win_split(gap, cfg)

    p_home = win_mass * home_share
    p_away = win_mass * away_share
    p_draw = draw

    total = p_home + p_draw + p_away
    return {
        "home": p_home / total,
        "draw": p_draw / total,
        "away": p_away / total,
    }


def odds_v3_1(
    home_rating: float,
    away_rating: float,
    rating_scale: str = "auto",
    overround: float = DEFAULT_CONFIG.overround,
    cfg: OddsConfig = DEFAULT_CONFIG,
) -> Tuple[float, float, float]:

    probs = probabilities_v3_1(
        home_rating,
        away_rating,
        rating_scale,
        cfg,
    )

    p_home = probs["home"] * overround
    p_draw = probs["draw"] * overround
    p_away = probs["away"] * overround

    return (
        round(1 / p_home, 2),
        round(1 / p_draw, 2),
        round(1 / p_away, 2),
    )


# =========================================================
# DEBUG TOOL
# =========================================================

def explain_v3_1(home_rating, away_rating, rating_scale="auto"):
    probs = probabilities_v3_1(home_rating, away_rating, rating_scale)
    odds = odds_v3_1(home_rating, away_rating, rating_scale)

    return {
        "probabilities": probs,
        "odds": {
            "home": odds[0],
            "draw": odds[1],
            "away": odds[2],
        }
    }


# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":
    tests = [
        (100, 90),
        (95, 85),
        (92, 88),
        (85, 95),
    ]

    for h, a in tests:
        result = explain_v3_1(h, a, "0-100")
        print(f"{h} vs {a}")
        print(result)
        print()
