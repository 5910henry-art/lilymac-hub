from collections import defaultdict
from copy import deepcopy
from datetime import datetime

from virtuals.config import app, db
from virtuals.config_settings import STATUS_FINISHED, TEAMS
from virtuals.model import Fixture
from virtuals.sim_helpers import _clamp, _calc_table_from_fixtures


def build_team_form_history(
    session=None,
    *,
    before_dt=None,
    season_id=None,
    lookback=5,
    team_names=None
):
    """
    Returns:
        { team: ["W","D","L"] }
    """

    session = session or db.session

    # ✅ FIXED: TEAMS is a set, NOT dict
    team_filter = set(team_names) if team_names else set(TEAMS)

    query = session.query(Fixture).filter(
        Fixture.status == STATUS_FINISHED,
        Fixture.is_settled.is_(True),
    )

    if before_dt is not None:
        query = query.filter(Fixture.start_time < before_dt)

    if season_id is not None:
        query = query.filter(Fixture.season <= season_id)

    fixtures = query.order_by(Fixture.start_time.asc(), Fixture.id.asc()).all()

    history = defaultdict(list)

    for f in fixtures:
        h = int(f.home_score or 0)
        a = int(f.away_score or 0)

        if h > a:
            home_result, away_result = "W", "L"
        elif a > h:
            home_result, away_result = "L", "W"
        else:
            home_result = away_result = "D"

        if f.home in team_filter:
            history[f.home].append(home_result)
            history[f.home] = history[f.home][-lookback:]

        if f.away in team_filter:
            history[f.away].append(away_result)
            history[f.away] = history[f.away][-lookback:]

    return dict(history)


def build_season_progress(previous_table):
    if not previous_table:
        return {}

    rows = list(previous_table.values())
    rows.sort(key=lambda r: (r.get("rank", 999), -(r.get("points", 0))), reverse=False)

    total = len(rows)
    if total <= 1:
        return {}

    progress = {}

    for row in rows:
        team = row["team"]
        rank = int(row.get("rank", total))
        played = max(1, int(row.get("played", 1)))
        points = int(row.get("points", 0))
        ppg = points / played

        normalized = (total - rank) / (total - 1)
        strength = (normalized - 0.5) * 2.0

        progress[team] = {
            "attack": _clamp((strength * 0.06) + ((ppg - 1.5) * 0.015), -0.08, 0.08),
            "defense": _clamp((strength * 0.05) + ((ppg - 1.5) * 0.012), -0.08, 0.08),
            "tempo": _clamp(strength * 0.03, -0.06, 0.06),
            "risk": _clamp(strength * 0.025, -0.08, 0.08),
        }

    return progress


def build_previous_season_context(season_id, session=None):
    if not season_id or season_id <= 0:
        return {}, 0

    session = session or db.session

    fixtures = (
        session.query(Fixture)
        .filter(
            Fixture.season_id == season_id,
            Fixture.status == STATUS_FINISHED,
            Fixture.is_settled.is_(True),
        )
        .all()
    )

    return _calc_table_from_fixtures(fixtures)
