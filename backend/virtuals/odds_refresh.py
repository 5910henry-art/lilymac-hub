# odds_refresh.py (ELITE: dynamic + anti-pattern + risk control + market realism)

import random
from collections import deque
from datetime import timedelta
from threading import Event, Thread

from virtuals.config import app, logger
from virtuals.model import Fixture, Odds
from virtuals.sim_helpers import build_previous_season_context, _clamp
from virtuals.style_resolver import build_team_form_history, build_season_progress
from virtuals.utils import get_session_local, safe_commit, now_utc, to_utc
from virtuals.sim_odds import generate_virtual_odds


_ODDS_REFRESH_STOP = Event()
_ODDS_REFRESH_THREAD = None

# ---------------- Config ----------------
HOUSE_MARGIN = 0.06
ODDS_JITTER = 0.015

# ---------------- Realism State ----------------
REALISM_STATE = {
    "home_streak": {},
    "away_streak": {},
    "draw_streak": 0,
    "goal_trend": deque(maxlen=20),
}

# ---------------- Main Logic ----------------
def refresh_open_fixture_odds(session, lookback: int = 5):
    now = now_utc()

    fixtures = session.query(Fixture).filter(
        Fixture.status.in_(["OPENED", "SCHEDULED"])
    ).all()

    if not fixtures:
        return 0

    season_id = getattr(fixtures[0], "season_id", None) or getattr(fixtures[0], "season", None)
    previous_season = (season_id - 1) if season_id else None

    team_context, total_teams = build_previous_season_context(previous_season, session=session)

    team_names = sorted({f.home for f in fixtures if f.home} | {f.away for f in fixtures if f.away})

    # ✅ FIXED CALL (IMPORTANT)
    form_history = build_team_form_history(
        session=session,
        before_dt=now,
        season_id=season_id,
        lookback=lookback,
        team_names=team_names
    )

    season_progress = build_season_progress(team_context)

    refreshed = 0

    for fixture in fixtures:
        start_dt = to_utc(fixture.start_time)

        if start_dt and start_dt <= now:
            continue
        if start_dt and (start_dt - now).total_seconds() <= 300:
            continue

        odds_obj = generate_virtual_odds(
            fixture,
            team_context=team_context,
            total_teams=total_teams,
            form_history=form_history,
            season_progress=season_progress,
        )

        session.add(odds_obj)
        refreshed += 1

    safe_commit(session)
    return refreshed


# ---------------- Scheduler ----------------
def start_odds_refresh_scheduler(interval_seconds: int = 30):
    global _ODDS_REFRESH_THREAD

    if _ODDS_REFRESH_THREAD and _ODDS_REFRESH_THREAD.is_alive():
        return _ODDS_REFRESH_THREAD

    _ODDS_REFRESH_STOP.clear()
    SessionMaker = get_session_local()

    def _loop():
        logger.info("[odds-refresh] scheduler started (%ss)", interval_seconds)

        while not _ODDS_REFRESH_STOP.wait(interval_seconds):
            try:
                with app.app_context():
                    with SessionMaker() as session:
                        count = refresh_open_fixture_odds(session)
                        if count:
                            logger.info("[odds-refresh] refreshed %d fixtures", count)
            except Exception:
                logger.exception("[odds-refresh] failed")

        logger.info("[odds-refresh] stopped")

    _ODDS_REFRESH_THREAD = Thread(target=_loop, daemon=True)
    _ODDS_REFRESH_THREAD.start()
    return _ODDS_REFRESH_THREAD


def stop_odds_refresh_scheduler():
    _ODDS_REFRESH_STOP.set()
