# virtuals/season.py

import logging
import time
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


# ============================================================
# META TABLE
# ============================================================

class Meta(db.Model):
    __tablename__ = "virtual_meta"
    __table_args__ = {"schema": SCHEMA} if SCHEMA else {}

    id = db.Column(db.Integer, primary_key=True)
    current_season = db.Column(db.Integer, default=1)


# ============================================================
# SEASON META
# ============================================================

def get_current_season():
    """
    Return the current season stored in virtual_meta.

    If the meta row does not exist, create season 1.
    """

    meta = db.session.query(Meta).first()

    if not meta:
        meta = Meta(current_season=1)
        db.session.add(meta)
        db.session.flush()

    return meta.current_season


def advance_season():
    """
    Advance the season number by one.

    The caller controls the transaction.
    """

    meta = db.session.query(Meta).first()

    if not meta:
        meta = Meta(current_season=1)
        db.session.add(meta)
        db.session.flush()
    else:
        meta.current_season += 1

    logger.info(
        "➡️ Advanced to season %s",
        meta.current_season,
    )

    return meta.current_season


# ============================================================
# ROUND ROBIN
# ============================================================

def generate_round_robin(teams):
    """
    Generate a double round-robin schedule.

    Each team plays every other team twice:
        - once home
        - once away
    """

    teams = list(teams)

    if len(teams) < 2:
        return []

    if len(teams) % 2:
        teams.append(None)

    n = len(teams)

    rounds = []

    for r in range(n - 1):

        pairs = []

        for i in range(n // 2):

            home = teams[i]
            away = teams[n - 1 - i]

            if home is None or away is None:
                continue

            if r % 2 == 0:
                pairs.append((home, away))
            else:
                pairs.append((away, home))

        rounds.append(pairs)

        teams = (
            [teams[0]]
            + [teams[-1]]
            + teams[1:-1]
        )

    second_half = [
        [
            (away, home)
            for home, away in rnd
        ]
        for rnd in rounds
    ]

    return (rounds + second_half)[:TOTAL_ROUNDS]


# ============================================================
# GENERATE FULL SEASON
# ============================================================

def generate_full_season(
    team_context=None,
    team_styles=None,
    form_history=None,
):
    """
    Generate the next complete virtual season.

    Important:
        Fixtures are flushed BEFORE odds are generated.

    This guarantees that every fixture has a database ID,
    allowing Odds.match_id to correctly reference Fixture.id.
    """

    started_at = time.monotonic()

    with app.app_context():

        try:

            # =================================================
            # 1. DO NOT GENERATE WHILE MATCHES ARE ACTIVE
            # =================================================

            check_started = time.monotonic()

            active_fixture = (
                db.session
                .query(Fixture.id)
                .filter(
                    Fixture.status.in_(
                        (
                            STATUS_SCHEDULED,
                            STATUS_OPEN,
                            STATUS_RUNNING,
                        )
                    )
                )
                .first()
            )

            logger.info(
                "[season] active-fixture check: %.3fs",
                time.monotonic() - check_started,
            )

            if active_fixture:

                logger.warning(
                    "⏸️ Active fixture exists — "
                    "skipping season generation"
                )

                return False

            # =================================================
            # 2. DETERMINE NEXT SEASON
            # =================================================

            meta_started = time.monotonic()

            meta = (
                db.session
                .query(Meta)
                .first()
            )

            latest_season_row = (
                db.session
                .query(Fixture.season)
                .filter(
                    Fixture.season.isnot(None)
                )
                .order_by(
                    Fixture.season.desc()
                )
                .first()
            )

            latest_fixture_season = (
                latest_season_row[0]
                if latest_season_row
                else None
            )

            if latest_fixture_season is None:

                if meta is None:

                    meta = Meta(
                        current_season=1
                    )

                    db.session.add(meta)
                    db.session.flush()

                current_season = max(
                    1,
                    meta.current_season,
                )

            else:

                current_season = (
                    latest_fixture_season + 1
                )

                if meta is None:

                    meta = Meta(
                        current_season=current_season
                    )

                    db.session.add(meta)

                else:

                    meta.current_season = (
                        current_season
                    )

                db.session.flush()

            logger.info(
                "➡️ Preparing next season: %s",
                current_season,
            )

            logger.info(
                "[season] season/meta preparation: %.3fs",
                time.monotonic() - meta_started,
            )

            # =================================================
            # 3. TEAM LIST + SCHEDULE
            # =================================================

            schedule_started = time.monotonic()

            teams = [
                team
                for team in TEAMS
                if team
            ]

            if len(teams) < 2:

                logger.error(
                    "❌ Not enough teams to generate season: %d",
                    len(teams),
                )

                db.session.rollback()

                return False

            schedule = generate_round_robin(
                teams
            )

            logger.info(
                "[season] schedule generation: %.3fs | "
                "teams=%d | rounds=%d",
                time.monotonic() - schedule_started,
                len(teams),
                len(schedule),
            )

            if not schedule:

                logger.error(
                    "❌ No rounds generated for season %s",
                    current_season,
                )

                db.session.rollback()

                return False

            # =================================================
            # 4. BASE TIME
            # =================================================

            base_time = (
                now_utc()
                + timedelta(seconds=2)
            )

            # =================================================
            # 5. CREATE ALL FIXTURES IN MEMORY
            # =================================================

            fixture_started = time.monotonic()

            all_fixtures = []

            for round_id, matches in enumerate(
                schedule,
                start=1,
            ):

                round_start = (
                    base_time
                    + timedelta(
                        seconds=(
                            round_id - 1
                        )
                        * ROUND_INTERVAL
                    )
                )

                start_time = (
                    round_start
                    + timedelta(
                        seconds=BETTING_TIME
                    )
                )

                end_time = (
                    start_time
                    + timedelta(
                        seconds=MATCH_SIM_SECONDS
                    )
                )

                for home, away in matches:

                    all_fixtures.append(
                        Fixture(
                            home=home,
                            away=away,
                            status=STATUS_SCHEDULED,
                            round=round_id,
                            season=current_season,
                            open_time=round_start,
                            start_time=start_time,
                            end_time=end_time,
                        )
                    )

            logger.info(
                "[season] fixture objects created: %.3fs | "
                "fixtures=%d",
                time.monotonic() - fixture_started,
                len(all_fixtures),
            )

            if not all_fixtures:

                logger.error(
                    "❌ No fixtures were generated "
                    "for season %s",
                    current_season,
                )

                db.session.rollback()

                return False

            # =================================================
            # 6. ADD + FLUSH FIXTURES
            # =================================================
            #
            # CRITICAL FIX:
            #
            # Odds generation requires fixture.id.
            #
            # Before flush():
            #
            #     fixture.id == None
            #
            # After flush():
            #
            #     fixture.id == actual database ID
            #
            # We therefore flush fixtures BEFORE generating odds.
            # This does NOT commit the transaction.

            fixture_insert_started = time.monotonic()

            db.session.add_all(
                all_fixtures
            )

            db.session.flush()

            logger.info(
                "[season] fixtures inserted/flushed: %.3fs | "
                "fixtures=%d",
                time.monotonic() - fixture_insert_started,
                len(all_fixtures),
            )

            # =================================================
            # 7. VERIFY FIXTURE IDS
            # =================================================

            missing_ids = [
                fixture
                for fixture in all_fixtures
                if getattr(fixture, "id", None) is None
            ]

            if missing_ids:

                raise RuntimeError(
                    "Fixture flush completed but "
                    f"{len(missing_ids)} fixture(s) have no ID"
                )

            logger.info(
                "[season] fixture IDs verified successfully"
            )

            # =================================================
            # 8. BUILD SEASON PROGRESS ONCE
            # =================================================

            progress_started = time.monotonic()

            season_progress_data = {}

            if team_context:

                try:

                    season_progress_data = (
                        build_season_progress(
                            team_context
                        )
                    )

                except Exception:

                    logger.exception(
                        "Failed to build season progress"
                    )

                    season_progress_data = {}

            logger.info(
                "[season] season progress: %.3fs",
                time.monotonic() - progress_started,
            )

            # =================================================
            # 9. GENERATE ODDS
            # =================================================

            odds_started = time.monotonic()

            odds_objects = []

            total_teams = len(teams)

            for index, fixture in enumerate(
                all_fixtures,
                start=1,
            ):

                try:

                    odds = generate_virtual_odds(
                        fixture,
                        team_context=team_context,
                        total_teams=total_teams,
                        team_styles=team_styles,
                        form_history=form_history,
                        season_progress=season_progress_data,
                        season_phase=(
                            fixture.round
                            / TOTAL_ROUNDS
                        ),
                    )

                    if odds is not None:

                        # Safety check.
                        if getattr(
                            odds,
                            "match_id",
                            None,
                        ) is None:

                            raise RuntimeError(
                                "Generated odds have no match_id "
                                f"for fixture {fixture.id}"
                            )

                        odds_objects.append(
                            odds
                        )

                except Exception:

                    logger.exception(
                        "Failed odds for fixture "
                        "%s vs %s "
                        "(fixture_id=%s)",
                        fixture.home,
                        fixture.away,
                        getattr(
                            fixture,
                            "id",
                            None,
                        ),
                    )

                # Progress every 50 fixtures.
                if index % 50 == 0:

                    logger.info(
                        "[season] odds progress: "
                        "%d/%d",
                        index,
                        len(all_fixtures),
                    )

            odds_elapsed = (
                time.monotonic()
                - odds_started
            )

            logger.info(
                "[season] odds generation: %.3fs | "
                "odds=%d",
                odds_elapsed,
                len(odds_objects),
            )

            # =================================================
            # 10. ADD ODDS
            # =================================================

            odds_insert_started = time.monotonic()

            if odds_objects:

                db.session.add_all(
                    odds_objects
                )

            logger.info(
                "[season] odds added to session: %.3fs",
                time.monotonic()
                - odds_insert_started,
            )

            # =================================================
            # 11. UPDATE META
            # =================================================

            if meta is None:

                meta = Meta(
                    current_season=current_season
                )

                db.session.add(meta)

            else:

                meta.current_season = (
                    current_season
                )

            # =================================================
            # 12. SINGLE COMMIT
            # =================================================

            commit_started = time.monotonic()

            db.session.commit()

            commit_elapsed = (
                time.monotonic()
                - commit_started
            )

            logger.info(
                "[season] database commit: %.3fs",
                commit_elapsed,
            )

            # =================================================
            # 13. SUCCESS
            # =================================================

            total_elapsed = (
                time.monotonic()
                - started_at
            )

            logger.info(
                "✅ Season %s generated successfully: "
                "%d rounds | %d fixtures | "
                "%d odds | total=%.3fs",
                current_season,
                len(schedule),
                len(all_fixtures),
                len(odds_objects),
                total_elapsed,
            )

            return True

        except Exception:

            logger.exception(
                "❌ Season generation failed"
            )

            db.session.rollback()

            return False
