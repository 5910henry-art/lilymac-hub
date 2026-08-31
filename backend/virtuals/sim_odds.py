from __future__ import annotations

from typing import Any, Dict, Optional

from virtuals.config_settings import normalize_team_name, validate_team
from virtuals.model import Odds
from virtuals.odds_updated import (
    generate_odds,
    load_model,
    predict_probs,
    find_closest_template,
    DEFAULT_MODEL_PATH,
)


# ============================================================
# MODEL CACHE
# ============================================================

_MODEL_CACHE = None


def get_model():
    """
    Load the odds model once and reuse it.

    This prevents model.json from being opened and parsed
    for every fixture during season generation.
    """
    global _MODEL_CACHE

    if _MODEL_CACHE is None:
        _MODEL_CACHE = load_model(DEFAULT_MODEL_PATH)

    return _MODEL_CACHE


def reload_model():
    """
    Force the odds model to be reloaded.
    Useful if model.json changes while the process is running.
    """
    global _MODEL_CACHE
    _MODEL_CACHE = load_model(DEFAULT_MODEL_PATH)
    return _MODEL_CACHE


# ============================================================
# SINGLE MATCH ODDS
# ============================================================

def match_odds(home_team: str, away_team: str) -> Dict[str, object]:

    home_team = validate_team(
        normalize_team_name(home_team)
    )

    away_team = validate_team(
        normalize_team_name(away_team)
    )

    (
        ratings,
        idx,
        home_adv,
        base_draw,
        draw_k,
        temp,
        templates,
    ) = get_model()

    if home_team not in idx or away_team not in idx:
        raise ValueError("Unknown team")

    probs, *_ = predict_probs(
        ratings[idx[home_team]],
        ratings[idx[away_team]],
        home_adv,
        base_draw,
        draw_k,
        temp=temp,
    )

    odds = find_closest_template(
        probs,
        templates,
        metric="log",
    )

    return {
        "home_prob": float(probs[0]),
        "draw_prob": float(probs[1]),
        "away_prob": float(probs[2]),
        "home_odds": float(odds[0]),
        "draw_odds": float(odds[1]),
        "away_odds": float(odds[2]),
        "probs": probs.tolist(),
    }


def predict(home_team: str, away_team: str) -> Dict[str, object]:
    return match_odds(home_team, away_team)


# ============================================================
# VIRTUAL FIXTURE ODDS
# ============================================================

def generate_virtual_odds(
    fixture: Any,
    *args,
    **kwargs,
) -> Optional[Odds]:

    home_raw = getattr(fixture, "home", "")
    away_raw = getattr(fixture, "away", "")

    try:
        home = validate_team(
            normalize_team_name(home_raw)
        )

        away = validate_team(
            normalize_team_name(away_raw)
        )

        (
            ratings,
            idx,
            home_adv,
            base_draw,
            draw_k,
            temp,
            templates,
        ) = get_model()

        if home not in idx or away not in idx:
            raise ValueError(
                f"Unknown team: {home} vs {away}"
            )

        probs, *_ = predict_probs(
            ratings[idx[home]],
            ratings[idx[away]],
            home_adv,
            base_draw,
            draw_k,
            temp=temp,
        )

        odds = find_closest_template(
            probs,
            templates,
            metric="log",
        )

    except ValueError as exc:

        print(
            f"[ERROR] {exc}: "
            f"'{home_raw}' vs '{away_raw}'"
        )

        return None

    return Odds(
        match_id=getattr(fixture, "id", None),
        home=odds[0],
        draw=odds[1],
        away=odds[2],
    )


__all__ = [
    "generate_virtual_odds",
    "match_odds",
    "predict",
    "get_model",
    "reload_model",
]
