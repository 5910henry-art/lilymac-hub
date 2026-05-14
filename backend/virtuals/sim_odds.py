from __future__ import annotations

from typing import Any, Dict, Optional

from virtuals.config_settings import normalize_team_name, validate_team
from virtuals.model import Odds
from virtuals.odds_updated import generate_odds


def match_odds(home_team: str, away_team: str) -> Dict[str, object]:
    home_team = validate_team(normalize_team_name(home_team))
    away_team = validate_team(normalize_team_name(away_team))
    return generate_odds(home_team, away_team)


def predict(home_team: str, away_team: str) -> Dict[str, object]:
    return match_odds(home_team, away_team)


def generate_virtual_odds(fixture: Any, *args, **kwargs) -> Optional[Odds]:
    home_raw = getattr(fixture, "home", "")
    away_raw = getattr(fixture, "away", "")

    try:
        home = validate_team(normalize_team_name(home_raw))
        away = validate_team(normalize_team_name(away_raw))
        result = generate_odds(home, away)
    except ValueError as exc:
        print(f"[ERROR] {exc}: '{home_raw}' vs '{away_raw}'")
        return None

    return Odds(
        match_id=getattr(fixture, "id", None),
        home=result["home_odds"],
        draw=result["draw_odds"],
        away=result["away_odds"],
    )


__all__ = [
    "generate_virtual_odds",
    "match_odds",
    "predict",
]
