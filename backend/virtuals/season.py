# season.py

import logging
from datetime import timedelta
from virtuals.utils import now_utc
from virtuals.config_settings import (
    TEAMS,
    ROUND_INTERVAL,
    BETTING_TIME,
    MATCH_SIM_SECONDS,
    TOTAL_ROUNDS,
    STATUS_SCHEDULED,
    STATUS_OPEN,
    STATUS_RUNNING,
    SCHEMA,
)
from virtuals.config import app, db
from virtuals.model import Fixture
from virtuals.sim_odds import generate_virtual_odds

from virtuals.style_resolver import build_season_progress

logger = logging.getLogger("virtual-season-engine")


# ---------------- META TABLE ----------------
class Meta(db.Model):
    __tablename__ = "virtual_meta"
    __table_args__ = {"schema": SCHEMA} if SCHEMA else {}

    id = db.Column(db.Integer, primary_key=True)
    current_season = db.Column(db.Integer, default=1)


def get_current_season():
    meta = db.session.query(Meta).first()
    if not meta:
        meta = Meta(current_season=1)
        db.session.add(meta)
        db.session.commit()
    return meta.current_season


def advance_season():
    meta = db.session.query(Meta).first()
    if not meta:
        meta = Meta(current_season=1)
        db.session.add(meta)
    else:
        meta.current_season += 1
    db.session.commit()
    logger.info("➡️ Advanced to season %s", meta.current_season)


# ---------------- ROUND ROBIN ----------------
def generate_round_robin(teams):
    teams = list(teams)
    if len(teams) % 2:
        teams.append(None)

    n = len(teams)
    rounds = []

    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            home = teams[i]
            away = teams[n - 1 - i]
            if home and away:
                pairs.append((home, away) if r % 2 == 0 else (away, home))
        rounds.append(pairs)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]

    second_half = [[(away, home) for home, away in rnd] for rnd in rounds]

    return (rounds + second_half)[:TOTAL_ROUNDS]


# ---------------- GENERATE FULL SEASON ----------------
def generate_full_season(team_context=None, team_styles=None, form_history=None):
    with app.app_context():
        try:
            active_fixture = (
                db.session.query(Fixture.id)
                .filter(Fixture.status.in_([STATUS_SCHEDULED, STATUS_OPEN, STATUS_RUNNING]))
                .first()
            )
            if active_fixture:
                logger.warning("Active season in progress — skipping generation")
                return

            current_season = get_current_season()
            teams = list(TEAMS)
            schedule = generate_round_robin(teams)
            base_time = now_utc().replace(second=0, microsecond=0) + timedelta(seconds=10)

            all_fixtures = []

            # ---------------- CREATE FIXTURES ----------------
            for round_id, matches in enumerate(schedule, start=1):
                round_start = base_time + timedelta(seconds=(round_id - 1) * ROUND_INTERVAL)
                for home, away in matches:
                    f = Fixture(
                        home=home,
                        away=away,
                        status=STATUS_SCHEDULED,
                        round=round_id,
                        season=current_season,
                        open_time=round_start,
                        start_time=round_start + timedelta(seconds=BETTING_TIME),
                        end_time=round_start + timedelta(seconds=BETTING_TIME + MATCH_SIM_SECONDS),
                    )
                    all_fixtures.append(f)

            db.session.add_all(all_fixtures)
            db.session.flush()

            #  BUILD SEASON PROGRESS (SAFE)
            season_progress_data = {}
            if team_context:
                try:
                    season_progress_data = build_season_progress(team_context)
                except Exception:
                    logger.exception("Failed to build season progress")
                    season_progress_data = {}

            # ---------------- GENERATE ODDS ----------------
            odds_objects = []
            total_teams = len(teams)

            for f in all_fixtures:
                try:
                    odds = generate_virtual_odds(
                        f,
                        team_context=team_context,
                        total_teams=total_teams,
                        team_styles=team_styles,
                        form_history=form_history,
                        season_progress=season_progress_data,
                        season_phase=f.round / TOTAL_ROUNDS,
                    )
                    odds_objects.append(odds)
                except Exception:
                    logger.exception("Failed odds for fixture %s vs %s", f.home, f.away)

            if odds_objects:
                db.session.add_all(odds_objects)

            db.session.commit()

            logger.info(
                "✅ Season %s generated: %d rounds | %d fixtures",
                current_season,
                len(set(f.round for f in all_fixtures)),
                len(all_fixtures),
            )

            advance_season()

        except Exception:
            logger.exception("❌ Season generation failed")
            db.session.rollback()
