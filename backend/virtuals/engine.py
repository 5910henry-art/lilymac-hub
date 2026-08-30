# virtuals/engine.py

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import text

from .odds_refresh import refresh_open_fixture_odds
from .utils import now_utc, try_set_fixture_status_atomic

logger = logging.getLogger("virtual-engine")


# ============================================================
# ENGINE GLOBALS
# ============================================================

engine_thread: threading.Thread | None = None
simulation_executor: ThreadPoolExecutor | None = None
settlement_executor: ThreadPoolExecutor | None = None


# ============================================================
# ENGINE SETTINGS
# ============================================================

FORCE_FINISH_GRACE_SECONDS = int(
    os.getenv(
        "VIRTUAL_FORCE_FINISH_GRACE_SECONDS",
        "120",
    )
)

ENGINE_WORKERS = int(
    os.getenv(
        "VIRTUAL_ENGINE_WORKERS",
        "10",
    )
)

RECOVERY_STALE_SECONDS = int(
    os.getenv(
        "VIRTUAL_RECOVERY_STALE_SECONDS",
        "900",
    )
)

ENGINE_START_STAGGER_SECONDS = float(
    os.getenv(
        "VIRTUAL_ENGINE_START_STAGGER_SECONDS",
        "0.2",
    )
)

ENGINE_HEALTH_LOG_SECONDS = int(
    os.getenv(
        "VIRTUAL_ENGINE_HEALTH_LOG_SECONDS",
        "30",
    )
)


# ============================================================
# SHUTDOWN
# ============================================================

shutdown_flag = threading.Event()


# ============================================================
# SIMULATION PROTECTION
# ============================================================

simulation_guard_lock = threading.Lock()

active_simulations: set[int] = set()

# Protect executor creation / submit / shutdown.
executor_lock = threading.RLock()

# Settlement protection.
#
# is_settled is updated by the settlement worker, so checking only
# the database flag is not enough: the engine can see the same
# finished fixture for several 1-second loops while settlement is
# still running. These in-memory claims prevent duplicate jobs.
settlement_guard_lock = threading.Lock()
active_settlements: set[int] = set()

# If settlement fails immediately, do not hammer the same fixture
# once per engine loop. A failed job becomes eligible again after
# this delay.
settlement_retry_after: dict[int, float] = {}
SETTLEMENT_RETRY_SECONDS = int(
    os.getenv(
        "VIRTUAL_SETTLEMENT_RETRY_SECONDS",
        "5",
    )
)


# ============================================================
# SEASON GENERATION PROTECTION
# ============================================================

season_generation_lock = threading.Lock()

last_season_generation_key: str | None = None


# ============================================================
# POSTGRES ENGINE LOCK
# ============================================================

# Prevent multiple virtual engines from operating against
# the same PostgreSQL database simultaneously.
ENGINE_ADVISORY_LOCK_KEY = 742913

engine_lock_connection = None


# ============================================================
# POSTGRES ADVISORY LOCK
# ============================================================

def _acquire_engine_advisory_lock(db):
    global engine_lock_connection

    try:
        engine_lock_connection = db.engine.connect()

        acquired = engine_lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {
                "key": ENGINE_ADVISORY_LOCK_KEY,
            },
        ).scalar()

        if acquired:
            logger.info(
                "ðŸ” Virtual engine advisory lock acquired"
            )
            return True

        engine_lock_connection.close()
        engine_lock_connection = None

        logger.warning(
            "ðŸš« Another virtual engine is already running"
        )

        return False

    except Exception:
        logger.exception(
            "Failed acquiring engine advisory lock"
        )

        if engine_lock_connection:
            try:
                engine_lock_connection.close()
            except Exception:
                pass

        engine_lock_connection = None

        return False


def _release_engine_advisory_lock():
    global engine_lock_connection

    if engine_lock_connection is None:
        return

    try:
        engine_lock_connection.execute(
            text(
                "SELECT pg_advisory_unlock(:key)"
            ),
            {
                "key": ENGINE_ADVISORY_LOCK_KEY,
            },
        )

        logger.info(
            "ðŸ”“ Virtual engine advisory lock released"
        )

    except Exception:
        logger.exception(
            "Failed releasing advisory lock"
        )

    finally:
        try:
            engine_lock_connection.close()
        except Exception:
            pass

        engine_lock_connection = None


# ============================================================
# DATETIME HELPERS
# ============================================================

def _fmt_dt(value):
    """Format datetime for logs without crashing on None."""

    if value is None:
        return "None"

    try:
        return value.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    except Exception:
        return str(value)


def _sleep_or_shutdown(
    seconds: float,
    step: float = 0.25,
):
    """
    Sleep in small chunks so shutdown stays responsive.
    """

    remaining = seconds

    while (
        remaining > 0
        and not shutdown_flag.is_set()
    ):
        chunk = min(
            step,
            remaining,
        )

        shutdown_flag.wait(
            chunk
        )

        remaining -= chunk


# ============================================================
# FIXTURE / SEASON HELPERS
# ============================================================

def _active_fixture_count(
    db,
    Fixture,
    STATUS_FINISHED,
):
    """
    Count unfinished fixtures across the database.

    This intentionally includes all seasons because any unfinished
    fixture means the engine still has work to do.
    """

    return (
        db.session
        .query(Fixture.id)
        .filter(
            Fixture.status != STATUS_FINISHED
        )
        .count()
    )


def _running_fixture_count(
    db,
    Fixture,
    STATUS_RUNNING,
    season_id=None,
):
    """
    Count RUNNING fixtures.

    If season_id is provided, only count fixtures from that season.
    """

    query = (
        db.session
        .query(Fixture.id)
        .filter(
            Fixture.status == STATUS_RUNNING
        )
    )

    if season_id is not None:
        query = query.filter(
            Fixture.season == season_id
        )

    return query.count()


def _get_active_season_id(
    db,
    Fixture,
    STATUS_FINISHED,
):
    """
    Return the season containing the earliest unfinished fixture.

    The engine must operate only on this season.

    This prevents old FINISHED seasons from being mixed with the
    currently active season.
    """

    row = (
        db.session
        .query(Fixture.season)
        .filter(
            Fixture.status != STATUS_FINISHED,
            Fixture.season.isnot(None),
        )
        .order_by(
            Fixture.season.asc(),
            Fixture.round.asc(),
            Fixture.id.asc(),
        )
        .first()
    )

    return row[0] if row else None


def _last_round_number(
    db,
    Fixture,
    season_id=None,
):
    """
    Get the last round for a specific season.

    If season_id is omitted, get the highest round globally.
    """

    query = db.session.query(
        Fixture.round
    )

    if season_id is not None:
        query = query.filter(
            Fixture.season == season_id
        )

    row = (
        query
        .order_by(
            Fixture.round.desc()
        )
        .first()
    )

    return row[0] if row else None


def _season_fixture_count(
    db,
    Fixture,
    season_id,
):
    """
    Number of fixtures belonging to a season.
    """

    if season_id is None:
        return 0

    return (
        db.session
        .query(Fixture.id)
        .filter(
            Fixture.season == season_id
        )
        .count()
    )


# ============================================================
# BET SETTLEMENT
# ============================================================

def _settle_unsettled_finished_matches(
    db,
    Fixture,
    STATUS_FINISHED,
    settle_virtual_bets,
    season_id=None,
):
    """
    Settle finished matches that have not yet been settled.

    When season_id is supplied, only settle matches from that season.
    """

    query = (
        db.session
        .query(Fixture)
        .filter(
            Fixture.is_settled == False,  # noqa: E712
            Fixture.status == STATUS_FINISHED,
        )
    )

    if season_id is not None:
        query = query.filter(
            Fixture.season == season_id
        )

    unsettled_matches = query.all()

    processed = 0

    for m in unsettled_matches:

        try:
            settle_virtual_bets(
                m.id
            )

            processed += 1

        except Exception:
            logger.exception(
                "Error force-settling match %s",
                m.id,
            )

    return processed


# ============================================================
# FRESH SEASON GENERATION
# ============================================================

def _maybe_generate_fresh_season(
    app,
    db,
    Fixture,
    STATUS_FINISHED,
    generate_full_season,
    settle_virtual_bets=None,
):
    """
    Generate a fresh season only when there are no unfinished fixtures.

    Existing finished seasons are NEVER deleted.

    The generation key includes:
        - total fixture count
        - latest season
        - latest round
    """

    global last_season_generation_key

    with app.app_context():

        total_count = (
            db.session
            .query(Fixture.id)
            .count()
        )

        active_count = _active_fixture_count(
            db,
            Fixture,
            STATUS_FINISHED,
        )

        if active_count > 0:
            last_season_generation_key = None
            return False

        if settle_virtual_bets is not None:

            _settle_unsettled_finished_matches(
                db=db,
                Fixture=Fixture,
                STATUS_FINISHED=STATUS_FINISHED,
                settle_virtual_bets=settle_virtual_bets,
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

        latest_season = (
            latest_season_row[0]
            if latest_season_row
            else None
        )

        last_round = _last_round_number(
            db,
            Fixture,
            season_id=latest_season,
        )

        terminal_key = (
            f"total={total_count}"
            f"|season={latest_season}"
            f"|last_round={last_round}"
        )

        with season_generation_lock:

            if (
                last_season_generation_key
                == terminal_key
            ):
                return False

            if total_count > 0:

                logger.info(
                    "ðŸ§¹ No active fixtures found; "
                    "old fixtures remain intact and "
                    "a fresh season will be generated"
                )

            else:

                logger.info(
                    "ðŸ†• No fixtures found; "
                    "generating first season"
                )

            generation_succeeded = False

            try:

                generate_full_season()

                db.session.expire_all()
                generation_succeeded = True

                logger.info(
                    "ðŸ†• Fresh season generation completed"
                )

            except Exception:

                logger.exception(
                    "Error generating fresh season"
                )

                db.session.rollback()

            # Only remember a generation key after a successful
            # generation. If generation failed, the next engine loop
            # must be allowed to retry it.
            if generation_succeeded:
                last_season_generation_key = terminal_key

        return generation_succeeded


# ============================================================
# STARTUP RECOVERY
# ============================================================

def _recover_incomplete_fixtures(
    app,
    db,
    Fixture,
    STATUS_SCHEDULED,
    STATUS_OPEN,
    STATUS_RUNNING,
    STATUS_FINISHED,
    BETTING_TIME,
    MATCH_SIM_SECONDS,
    ROUND_INTERVAL,
):
    """
    Hybrid startup recovery.

    - Recent RUNNING matches are resumed from now.
    - Recent OPEN matches are nudged forward.
    - Stale/badly interrupted fixtures are fully re-queued.
    - Recovery operates independently for each active season.
    """

    with app.app_context():

        incomplete = (
            db.session
            .query(Fixture)
            .filter(
                Fixture.status != STATUS_FINISHED
            )
            .order_by(
                Fixture.season.asc(),
                Fixture.round.asc(),
                Fixture.id.asc(),
            )
            .all()
        )

        if not incomplete:
            return

        now = now_utc().replace(
            second=0,
            microsecond=0,
        )

        stale_cutoff = (
            now
            - timedelta(
                seconds=RECOVERY_STALE_SECONDS
            )
        )

        season_rounds = {}

        for m in incomplete:

            if m.season is None:
                continue

            season_rounds.setdefault(
                m.season,
                set(),
            ).add(m.round)

        round_start_map = {}

        for season_id, rounds in season_rounds.items():

            valid_rounds = sorted(
                r
                for r in rounds
                if r is not None
            )

            for idx, round_no in enumerate(
                valid_rounds
            ):

                round_start_map[
                    (
                        season_id,
                        round_no,
                    )
                ] = (
                    now
                    + timedelta(
                        seconds=2
                        + (
                            idx
                            * ROUND_INTERVAL
                        )
                    )
                )

        recovered = 0
        resumed = 0
        requeued = 0

        for m in incomplete:

            try:

                round_start = round_start_map.get(
                    (
                        m.season,
                        m.round,
                    ),
                    now
                    + timedelta(
                        seconds=2
                        + max(
                            0,
                            (m.round or 1) - 1,
                        )
                        * ROUND_INTERVAL
                    ),
                )

                anchor_time = (
                    m.end_time
                    or m.start_time
                    or m.open_time
                )

                is_stale = (
                    anchor_time is None
                    or anchor_time
                    <= stale_cutoff
                )

                # ------------------------------------------------
                # STALE FIXTURE
                # ------------------------------------------------

                if is_stale:

                    m.status = STATUS_SCHEDULED
                    m.is_settled = False

                    m.event_count = 0
                    m.home_score = 0
                    m.away_score = 0

                    m.open_time = round_start

                    m.start_time = (
                        round_start
                        + timedelta(
                            seconds=BETTING_TIME
                        )
                    )

                    m.end_time = (
                        round_start
                        + timedelta(
                            seconds=(
                                BETTING_TIME
                                + MATCH_SIM_SECONDS
                            )
                        )
                    )

                    if hasattr(
                        m,
                        "is_simulating",
                    ):
                        m.is_simulating = False

                    requeued += 1
                    recovered += 1

                    continue

                # ------------------------------------------------
                # RUNNING FIXTURE
                # ------------------------------------------------

                if m.status == STATUS_RUNNING:

                    m.status = STATUS_OPEN
                    m.is_settled = False

                    m.event_count = 0
                    m.home_score = 0
                    m.away_score = 0

                    if hasattr(
                        m,
                        "is_simulating",
                    ):
                        m.is_simulating = False

                    m.open_time = (
                        now
                        + timedelta(
                            seconds=2
                        )
                    )

                    m.start_time = (
                        now
                        + timedelta(
                            seconds=5
                        )
                    )

                    m.end_time = (
                        m.start_time
                        + timedelta(
                            seconds=MATCH_SIM_SECONDS
                        )
                    )

                    resumed += 1
                    recovered += 1

                    continue

                # ------------------------------------------------
                # OPEN FIXTURE
                # ------------------------------------------------

                if m.status == STATUS_OPEN:

                    if (
                        not m.start_time
                        or m.start_time < now
                    ):

                        m.start_time = (
                            now
                            + timedelta(
                                seconds=5
                            )
                        )

                    if (
                        not m.end_time
                        or m.end_time
                        <= m.start_time
                    ):

                        m.end_time = (
                            m.start_time
                            + timedelta(
                                seconds=MATCH_SIM_SECONDS
                            )
                        )

                    if hasattr(
                        m,
                        "is_simulating",
                    ):
                        m.is_simulating = False

                    resumed += 1
                    recovered += 1

                    continue

                # ------------------------------------------------
                # SCHEDULED FIXTURE
                # ------------------------------------------------

                if m.status == STATUS_SCHEDULED:

                    if (
                        not m.open_time
                        or not m.start_time
                        or not m.end_time
                        or m.open_time < now
                    ):

                        m.open_time = round_start

                        m.start_time = (
                            round_start
                            + timedelta(
                                seconds=BETTING_TIME
                            )
                        )

                        m.end_time = (
                            round_start
                            + timedelta(
                                seconds=(
                                    BETTING_TIME
                                    + MATCH_SIM_SECONDS
                                )
                            )
                        )

                    if hasattr(
                        m,
                        "is_simulating",
                    ):
                        m.is_simulating = False

                    recovered += 1

            except Exception:

                logger.exception(
                    "Failed recovering fixture %s",
                    getattr(
                        m,
                        "id",
                        "?",
                    ),
                )

        db.session.commit()

        logger.info(
            "ðŸ”„ Recovered %d incomplete fixture(s) "
            "from previous run (%d resumed, %d re-queued)",
            recovered,
            resumed,
            requeued,
        )


# ============================================================
# FORCE FINISH STUCK RUNNING MATCHES
# ============================================================

def _force_finish_stuck_running_matches(
    db,
    Fixture,
    STATUS_RUNNING,
    STATUS_FINISHED,
    season_id=None,
):
    """
    Force-finish RUNNING matches that are stuck beyond the
    configured grace window.
    """

    now = now_utc()

    cutoff = (
        now
        - timedelta(
            seconds=FORCE_FINISH_GRACE_SECONDS
        )
    )

    query = (
        db.session
        .query(Fixture)
        .filter(
            Fixture.status == STATUS_RUNNING
        )
        .order_by(
            Fixture.round.asc(),
            Fixture.id.asc(),
        )
    )

    if season_id is not None:
        query = query.filter(
            Fixture.season == season_id
        )

    running_matches = query.all()

    forced = 0

    for m in running_matches:

        try:

            if m.end_time is not None:

                effective_end = m.end_time

            elif m.start_time is not None:

                effective_end = (
                    m.start_time
                    + timedelta(
                        seconds=45
                    )
                )

            elif m.open_time is not None:

                effective_end = (
                    m.open_time
                    + timedelta(
                        seconds=45
                    )
                )

            else:

                effective_end = (
                    now
                    - timedelta(
                        seconds=1
                    )
                )

            if effective_end > cutoff:
                continue

            updated = try_set_fixture_status_atomic(
                db.session,
                m.id,
                STATUS_RUNNING,
                STATUS_FINISHED,
            )

            if not updated:
                continue

            if (
                m.end_time is None
                or m.end_time < effective_end
            ):
                m.end_time = effective_end

            if hasattr(
                m,
                "is_simulating",
            ):
                m.is_simulating = False

            db.session.commit()

            logger.warning(
                "âš ï¸ FORCE FINISH Match %d | "
                "season=%s | round=%s | "
                "open_time=%s | start_time=%s | end_time=%s",
                m.id,
                m.season,
                m.round,
                _fmt_dt(m.open_time),
                _fmt_dt(m.start_time),
                _fmt_dt(m.end_time),
            )

            forced += 1

        except Exception:

            logger.exception(
                "Failed force-finishing stuck match %s",
                getattr(
                    m,
                    "id",
                    "?",
                ),
            )

            db.session.rollback()

    return forced


# ============================================================
# ENGINE HEALTH
# ============================================================

def _log_engine_health(
    db,
    Fixture,
    STATUS_RUNNING,
    STATUS_FINISHED,
    season_id=None,
):
    try:

        if season_id is None:

            active_count = _active_fixture_count(
                db,
                Fixture,
                STATUS_FINISHED,
            )

        else:

            active_count = (
                db.session
                .query(Fixture.id)
                .filter(
                    Fixture.season == season_id,
                    Fixture.status != STATUS_FINISHED,
                )
                .count()
            )

    except Exception:

        active_count = None

    try:

        running_count = _running_fixture_count(
            db,
            Fixture,
            STATUS_RUNNING,
            season_id=season_id,
        )

    except Exception:

        running_count = None

    with simulation_guard_lock:
        sim_count = len(
            active_simulations
        )

    logger.info(
        "[engine] health | season=%s | active=%s | "
        "running=%s | simulating=%d",
        season_id
        if season_id is not None
        else "?",
        active_count
        if active_count is not None
        else "?",
        running_count
        if running_count is not None
        else "?",
        sim_count,
    )


# ============================================================
# EXECUTOR HELPERS
# ============================================================

def _ensure_simulation_executor():
    """
    Return a live simulation executor.

    A Render/Gunicorn restart can shut down the old executor.
    Never reuse an executor that has already been shut down.
    """

    global simulation_executor

    with executor_lock:

        if (
            simulation_executor is None
            or getattr(
                simulation_executor,
                "_shutdown",
                False,
            )
        ):

            simulation_executor = (
                ThreadPoolExecutor(
                    max_workers=ENGINE_WORKERS
                )
            )

            logger.info(
                "ðŸ”§ Simulation executor ready | workers=%d",
                ENGINE_WORKERS,
            )

        return simulation_executor


def _ensure_settlement_executor():
    """
    Return a live settlement executor.
    """

    global settlement_executor

    with executor_lock:

        if (
            settlement_executor is None
            or getattr(
                settlement_executor,
                "_shutdown",
                False,
            )
        ):

            settlement_executor = (
                ThreadPoolExecutor(
                    max_workers=3
                )
            )

            logger.info(
                "ðŸ”§ Settlement executor ready"
            )

        return settlement_executor


# ============================================================
# START ENGINE
# ============================================================

def start_virtual_engine(
    emit_update_callback=None,
):
    logger.warning(
        "ðŸ”¥ ENGINE CALLBACK | callback=%r | module=%s",
        emit_update_callback,
        getattr(
            emit_update_callback,
            "__module__",
            None,
        ),
    )

    global engine_thread

    # --------------------------------------------------------
    # Don't start another local engine thread.
    # --------------------------------------------------------

    if (
        engine_thread is not None
        and engine_thread.is_alive()
    ):

        logger.warning(
            "âš ï¸ Virtual engine already running"
        )

        return engine_thread

    from .config import app, db

    # --------------------------------------------------------
    # PostgreSQL global engine lock
    # --------------------------------------------------------

    with app.app_context():

        if not _acquire_engine_advisory_lock(db):

            return None

    from .config import app, db, socketio

    from .model import Fixture

    from .config_settings import (
        STATUS_SCHEDULED,
        STATUS_OPEN,
        STATUS_RUNNING,
        STATUS_FINISHED,
        MATCHES_PER_ROUND,
        MAX_ACTIVE_MATCHES,
        BETTING_TIME,
        MATCH_SIM_SECONDS,
        ROUND_INTERVAL,
    )

    from .simulation import simulate_match

    from .season import generate_full_season

    from .settlement import settle_virtual_bets

    shutdown_flag.clear()

    # --------------------------------------------------------
    # Executors
    # --------------------------------------------------------

    _ensure_simulation_executor()
    _ensure_settlement_executor()

    logger.info(
        "âš™ï¸ Settlement protection enabled | "
        "retry_seconds=%d",
        SETTLEMENT_RETRY_SECONDS,
    )

    # ========================================================
    # SUBMIT SIMULATION
    # ========================================================

    def _submit_simulation(
        match_id: int,
    ):
        """
        Submit one simulation exactly once per match.

        Shutdown-safe:
            - refuses work after shutdown begins
            - prevents duplicate submissions
            - recreates a dead executor
            - catches RuntimeError during Render restart
            - always removes the match from active_simulations
        """

        # ----------------------------------------------------
        # Don't accept new work during shutdown.
        # ----------------------------------------------------

        if shutdown_flag.is_set():

            logger.info(
                "â¹ï¸ Shutdown active; "
                "not submitting match %s",
                match_id,
            )

            return False

        # ----------------------------------------------------
        # Claim the match once.
        # ----------------------------------------------------

        with simulation_guard_lock:

            if match_id in active_simulations:

                logger.warning(
                    "Match %d already simulating â€” skipping",
                    match_id,
                )

                return False

            active_simulations.add(
                match_id
            )

        def _runner():

            try:

                logger.info(
                    "ðŸš€ Simulation worker started | match=%s",
                    match_id,
                )

                simulate_match(
                    match_id,
                    emit_update_callback,
                )

            except Exception:

                logger.exception(
                    "Simulation crashed for match %s",
                    match_id,
                )

            finally:

                with simulation_guard_lock:
                    active_simulations.discard(
                        match_id
                    )

                logger.info(
                    "ðŸ Simulation worker released | match=%s",
                    match_id,
                )

        # ----------------------------------------------------
        # Submit while protected by the executor lock.
        # ----------------------------------------------------

        try:

            with executor_lock:

                if shutdown_flag.is_set():

                    with simulation_guard_lock:
                        active_simulations.discard(
                            match_id
                        )

                    logger.info(
                        "â¹ï¸ Shutdown started before submit | "
                        "match=%s",
                        match_id,
                    )

                    return False

                executor = (
                    _ensure_simulation_executor()
                )

                try:

                    future = executor.submit(
                        _runner
                    )

                except RuntimeError as exc:

                    # ------------------------------------------------
                    # Executor may have been shut down concurrently.
                    # Recreate it once and retry.
                    # ------------------------------------------------

                    logger.warning(
                        "âš ï¸ Executor rejected match %s: %s",
                        match_id,
                        exc,
                    )

                    if shutdown_flag.is_set():

                        with simulation_guard_lock:
                            active_simulations.discard(
                                match_id
                            )

                        return False

                    simulation_executor_local = (
                        ThreadPoolExecutor(
                            max_workers=ENGINE_WORKERS
                        )
                    )

                    globals()[
                        "simulation_executor"
                    ] = simulation_executor_local

                    future = (
                        simulation_executor_local.submit(
                            _runner
                        )
                    )

                logger.info(
                    "âœ… Simulation submitted | "
                    "match=%s | future=%r",
                    match_id,
                    future,
                )

                return True

        except RuntimeError as exc:

            with simulation_guard_lock:
                active_simulations.discard(
                    match_id
                )

            logger.warning(
                "âš ï¸ Simulation submission rejected "
                "for match %s: %s",
                match_id,
                exc,
            )

            return False

        except Exception:

            with simulation_guard_lock:
                active_simulations.discard(
                    match_id
                )

            logger.exception(
                "Failed submitting simulation for match %s",
                match_id,
            )

            return False

    # ========================================================
    # SUBMIT SETTLEMENT
    # ========================================================

    def _submit_settlement(
        match_id: int,
    ):
        """
        Queue settlement exactly once at a time per match.

        The database is_settled flag is deliberately NOT used as the
        in-flight lock because the settlement worker may take longer
        than one engine loop. active_settlements closes that race.

        If settlement fails, the claim is released and the fixture is
        retried after SETTLEMENT_RETRY_SECONDS.
        """

        if shutdown_flag.is_set():

            logger.info(
                "â¹ï¸ Shutdown active; "
                "not submitting settlement for match %s",
                match_id,
            )

            return False

        now_mono = time.monotonic()

        # --------------------------------------------------------
        # Claim the match before submitting the job.
        # --------------------------------------------------------

        with settlement_guard_lock:

            if match_id in active_settlements:

                return False

            retry_at = settlement_retry_after.get(
                match_id,
                0.0,
            )

            if now_mono < retry_at:

                return False

            active_settlements.add(match_id)

        def _settlement_runner():

            succeeded = False

            try:

                logger.info(
                    "ðŸ’° Settlement worker started | match=%s",
                    match_id,
                )

                settle_virtual_bets(
                    match_id
                )

                succeeded = True

                logger.info(
                    "ðŸ’° Settlement worker completed | match=%s",
                    match_id,
                )

            except Exception:

                logger.exception(
                    "Settlement failed for match %s",
                    match_id,
                )

            finally:

                with settlement_guard_lock:

                    active_settlements.discard(
                        match_id
                    )

                    if succeeded:

                        settlement_retry_after.pop(
                            match_id,
                            None,
                        )

                    else:

                        settlement_retry_after[
                            match_id
                        ] = (
                            time.monotonic()
                            + SETTLEMENT_RETRY_SECONDS
                        )

        # --------------------------------------------------------
        # Submit while protected by the executor lock.
        # --------------------------------------------------------

        try:

            with executor_lock:

                if shutdown_flag.is_set():

                    with settlement_guard_lock:

                        active_settlements.discard(
                            match_id
                        )

                    return False

                executor = (
                    _ensure_settlement_executor()
                )

                try:

                    future = executor.submit(
                        _settlement_runner
                    )

                except RuntimeError as exc:

                    logger.warning(
                        "Settlement executor rejected "
                        "match %s: %s",
                        match_id,
                        exc,
                    )

                    if shutdown_flag.is_set():

                        with settlement_guard_lock:

                            active_settlements.discard(
                                match_id
                            )

                        return False

                    # Recreate the executor once and retry.
                    new_executor = (
                        ThreadPoolExecutor(
                            max_workers=3
                        )
                    )

                    globals()[
                        "settlement_executor"
                    ] = new_executor

                    try:

                        future = (
                            new_executor.submit(
                                _settlement_runner
                            )
                        )

                    except Exception:

                        new_executor.shutdown(
                            wait=False,
                            cancel_futures=True,
                        )

                        with settlement_guard_lock:

                            active_settlements.discard(
                                match_id
                            )

                            settlement_retry_after[
                                match_id
                            ] = (
                                time.monotonic()
                                + SETTLEMENT_RETRY_SECONDS
                            )

                        raise

                logger.info(
                    "âœ… Settlement submitted | "
                    "match=%s | future=%r",
                    match_id,
                    future,
                )

                return True

        except Exception:

            with settlement_guard_lock:

                active_settlements.discard(
                    match_id
                )

                settlement_retry_after[
                    match_id
                ] = (
                    time.monotonic()
                    + SETTLEMENT_RETRY_SECONDS
                )

            logger.exception(
                "Error submitting settlement "
                "for match %s",
                match_id,
            )

            return False


    # ========================================================
    # ENGINE LOOP
    # ========================================================

    def run_engine():

        logger.info(
            "ðŸŸ¢ Engine worker thread started"
        )

        with app.app_context():

            try:

                # ------------------------------------------------
                # Startup recovery
                # ------------------------------------------------

                _recover_incomplete_fixtures(
                    app=app,
                    db=db,
                    Fixture=Fixture,
                    STATUS_SCHEDULED=STATUS_SCHEDULED,
                    STATUS_OPEN=STATUS_OPEN,
                    STATUS_RUNNING=STATUS_RUNNING,
                    STATUS_FINISHED=STATUS_FINISHED,
                    BETTING_TIME=BETTING_TIME,
                    MATCH_SIM_SECONDS=MATCH_SIM_SECONDS,
                    ROUND_INTERVAL=ROUND_INTERVAL,
                )

                # ------------------------------------------------
                # If no active season exists, generate one.
                # ------------------------------------------------

                _maybe_generate_fresh_season(
                    app=app,
                    db=db,
                    Fixture=Fixture,
                    STATUS_FINISHED=STATUS_FINISHED,
                    generate_full_season=generate_full_season,
                    settle_virtual_bets=settle_virtual_bets,
                )

            except Exception:

                logger.exception(
                    "Error preparing season at startup"
                )

                db.session.rollback()

            # ------------------------------------------------
            # Timers
            # ------------------------------------------------

            last_cleanup_check = time.time()
            last_health_log = time.time()
            last_odds_refresh = time.time()

            ODDS_REFRESH_INTERVAL = 60

            # =================================================
            # MAIN LOOP
            # =================================================

            while not shutdown_flag.is_set():

                try:

                    now = now_utc()

                    # =========================================
                    # ACTIVE SEASON
                    # =========================================

                    active_season = (
                        _get_active_season_id(
                            db,
                            Fixture,
                            STATUS_FINISHED,
                        )
                    )

                    # =========================================
                    # ENGINE HEALTH
                    # =========================================

                    if (
                        time.time()
                        - last_health_log
                        > ENGINE_HEALTH_LOG_SECONDS
                    ):

                        _log_engine_health(
                            db,
                            Fixture,
                            STATUS_RUNNING,
                            STATUS_FINISHED,
                            season_id=active_season,
                        )

                        last_health_log = (
                            time.time()
                        )

                    # =========================================
                    # REFRESH OPEN ODDS
                    # =========================================

                    if (
                        time.time()
                        - last_odds_refresh
                        > ODDS_REFRESH_INTERVAL
                    ):

                        try:

                            refreshed_count = (
                                refresh_open_fixture_odds(
                                    db.session,
                                    lookback=5,
                                )
                            )

                            if refreshed_count:

                                logger.info(
                                    "ðŸŽ² Refreshed odds for %d "
                                    "open fixtures",
                                    refreshed_count,
                                )

                        except Exception:

                            logger.exception(
                                "Error refreshing "
                                "open fixture odds"
                            )

                        finally:

                            last_odds_refresh = (
                                time.time()
                            )

                    # =========================================
                    # PERIODIC SETTLEMENT CLEANUP
                    # =========================================

                    if (
                        time.time()
                        - last_cleanup_check
                        > 10
                    ):

                        try:

                            _settle_unsettled_finished_matches(
                                db=db,
                                Fixture=Fixture,
                                STATUS_FINISHED=STATUS_FINISHED,
                                settle_virtual_bets=settle_virtual_bets,
                                season_id=active_season,
                            )

                        except Exception:

                            logger.exception(
                                "Error during "
                                "cleanup settlement"
                            )

                            db.session.rollback()

                        last_cleanup_check = (
                            time.time()
                        )

                    # =========================================
                    # FORCE FINISH STUCK MATCHES
                    # =========================================

                    if active_season is not None:

                        try:

                            _force_finish_stuck_running_matches(
                                db=db,
                                Fixture=Fixture,
                                STATUS_RUNNING=STATUS_RUNNING,
                                STATUS_FINISHED=STATUS_FINISHED,
                                season_id=active_season,
                            )

                        except Exception:

                            logger.exception(
                                "Error force-finishing "
                                "stuck matches"
                            )

                            db.session.rollback()

                    # =========================================
                    # NO ACTIVE SEASON
                    # =========================================

                    if active_season is None:

                        try:

                            _maybe_generate_fresh_season(
                                app=app,
                                db=db,
                                Fixture=Fixture,
                                STATUS_FINISHED=STATUS_FINISHED,
                                generate_full_season=generate_full_season,
                                settle_virtual_bets=settle_virtual_bets,
                            )

                        except Exception:

                            logger.exception(
                                "Error ensuring active season"
                            )

                            db.session.rollback()

                        _sleep_or_shutdown(
                            1
                        )

                        continue

                    # =========================================
                    # CURRENT ROUND
                    # =========================================

                    current_round_row = (
                        db.session
                        .query(Fixture.round)
                        .filter(
                            Fixture.season
                            == active_season,

                            Fixture.status.in_(
                                [
                                    STATUS_SCHEDULED,
                                    STATUS_OPEN,
                                    STATUS_RUNNING,
                                ]
                            ),
                        )
                        .order_by(
                            Fixture.round.asc()
                        )
                        .first()
                    )

                    # =========================================
                    # BROKEN ROUND RECOVERY
                    # =========================================

                    if not current_round_row:

                        logger.warning(
                            "âš ï¸ No active round found "
                            "for season %s while fixtures exist. "
                            "Attempting recovery...",
                            active_season,
                        )

                        try:

                            _recover_incomplete_fixtures(
                                app=app,
                                db=db,
                                Fixture=Fixture,
                                STATUS_SCHEDULED=STATUS_SCHEDULED,
                                STATUS_OPEN=STATUS_OPEN,
                                STATUS_RUNNING=STATUS_RUNNING,
                                STATUS_FINISHED=STATUS_FINISHED,
                                BETTING_TIME=BETTING_TIME,
                                MATCH_SIM_SECONDS=MATCH_SIM_SECONDS,
                                ROUND_INTERVAL=ROUND_INTERVAL,
                            )

                        except Exception:

                            logger.exception(
                                "Error recovering "
                                "broken round state"
                            )

                            db.session.rollback()

                        _sleep_or_shutdown(
                            1
                        )

                        continue

                    current_round = (
                        current_round_row[0]
                    )

                    # =========================================
                    # OPEN MATCHES
                    # =========================================

                    running_count = (
                        _running_fixture_count(
                            db,
                            Fixture,
                            STATUS_RUNNING,
                            season_id=active_season,
                        )
                    )

                    slots_available = max(
                        0,
                        MAX_ACTIVE_MATCHES
                        - running_count,
                    )

                    if slots_available > 0:

                        matches_to_open = (
                            Fixture.query
                            .filter(
                                Fixture.season
                                == active_season,

                                Fixture.round
                                == current_round,

                                Fixture.status
                                == STATUS_SCHEDULED,

                                Fixture.open_time
                                <= now,
                            )
                            .order_by(
                                Fixture.id.asc()
                            )
                            .limit(
                                min(
                                    slots_available,
                                    MATCHES_PER_ROUND,
                                )
                            )
                            .all()
                        )

                        for m in matches_to_open:

                            if shutdown_flag.is_set():
                                break

                            try:

                                updated = (
                                    try_set_fixture_status_atomic(
                                        db.session,
                                        m.id,
                                        STATUS_SCHEDULED,
                                        STATUS_OPEN,
                                    )
                                )

                                if not updated:
                                    continue

                                db.session.commit()

                                logger.info(
                                    "ðŸŸ¢ OPEN Match %d "
                                    "(S%d R%d): %s vs %s "
                                    "| open_time=%s",
                                    m.id,
                                    m.season,
                                    m.round,
                                    m.home,
                                    m.away,
                                    _fmt_dt(
                                        m.open_time
                                    ),
                                )

                                try:

                                    socketio.emit(
                                        "match_open",
                                        {
                                            "match_id": m.id,
                                            "home": m.home,
                                            "away": m.away,
                                            "season": m.season,
                                            "round": m.round,
                                        },
                                    )

                                except Exception:

                                    logger.exception(
                                        "Socket emit failed "
                                        "for opening match %s",
                                        m.id,
                                    )

                            except Exception:

                                logger.exception(
                                    "Error opening match %s",
                                    m.id,
                                )

                                db.session.rollback()

                    # =========================================
                    # START MATCHES
                    # =========================================

                    running_count = (
                        _running_fixture_count(
                            db,
                            Fixture,
                            STATUS_RUNNING,
                            season_id=active_season,
                        )
                    )

                    slots_available = max(
                        0,
                        MAX_ACTIVE_MATCHES
                        - running_count,
                    )

                    if slots_available > 0:

                        to_start = (
                            Fixture.query
                            .filter(
                                Fixture.season
                                == active_season,

                                Fixture.round
                                == current_round,

                                Fixture.status
                                == STATUS_OPEN,

                                Fixture.start_time
                                <= now,
                            )
                            .order_by(
                                Fixture.id.asc()
                            )
                            .limit(
                                min(
                                    slots_available,
                                    ENGINE_WORKERS,
                                )
                            )
                            .all()
                        )

                        for idx, m in enumerate(
                            to_start
                        ):

                            if shutdown_flag.is_set():
                                break

                            try:

                                updated = (
                                    try_set_fixture_status_atomic(
                                        db.session,
                                        m.id,
                                        STATUS_OPEN,
                                        STATUS_RUNNING,
                                    )
                                )

                                if not updated:
                                    continue

                                db.session.commit()

                                logger.info(
                                    "â–¶ï¸ START Match %d "
                                    "(S%d R%d): %s vs %s "
                                    "| open_time=%s "
                                    "| start_time=%s",
                                    m.id,
                                    m.season,
                                    m.round,
                                    m.home,
                                    m.away,
                                    _fmt_dt(
                                        m.open_time
                                    ),
                                    _fmt_dt(
                                        m.start_time
                                    ),
                                )

                                if (
                                    idx > 0
                                    and ENGINE_START_STAGGER_SECONDS
                                    > 0
                                ):

                                    _sleep_or_shutdown(
                                        ENGINE_START_STAGGER_SECONDS
                                        * idx
                                    )

                                if shutdown_flag.is_set():
                                    break

                                submitted = (
                                    _submit_simulation(
                                        m.id
                                    )
                                )

                                if not submitted:

                                    logger.warning(
                                        "âš ï¸ Simulation was not "
                                        "submitted for match %s; "
                                        "engine will recover it later",
                                        m.id,
                                    )

                            except Exception:

                                logger.exception(
                                    "Error starting match %s",
                                    m.id,
                                )

                                db.session.rollback()

                    # =========================================
                    # FORCE FINISH OVERDUE MATCHES
                    # =========================================

                    timeout_cutoff = (
                        now
                        - timedelta(
                            seconds=FORCE_FINISH_GRACE_SECONDS
                        )
                    )

                    finished = (
                        Fixture.query
                        .filter(
                            Fixture.season
                            == active_season,

                            Fixture.status
                            == STATUS_RUNNING,

                            Fixture.end_time
                            .isnot(None),

                            Fixture.end_time
                            <= timeout_cutoff,
                        )
                        .order_by(
                            Fixture.id.asc()
                        )
                        .all()
                    )

                    for m in finished:

                        try:

                            updated = (
                                try_set_fixture_status_atomic(
                                    db.session,
                                    m.id,
                                    STATUS_RUNNING,
                                    STATUS_FINISHED,
                                )
                            )

                            if not updated:
                                continue

                            db.session.commit()

                            if hasattr(
                                m,
                                "is_simulating",
                            ):
                                m.is_simulating = False

                                try:
                                    db.session.commit()
                                except Exception:
                                    db.session.rollback()

                            logger.warning(
                                "âš ï¸ TIMEOUT FINISH Match %d "
                                "(S%d R%d) | "
                                "open_time=%s | "
                                "start_time=%s | "
                                "end_time=%s",
                                m.id,
                                m.season,
                                m.round,
                                _fmt_dt(
                                    m.open_time
                                ),
                                _fmt_dt(
                                    m.start_time
                                ),
                                _fmt_dt(
                                    m.end_time
                                ),
                            )

                        except Exception:

                            logger.exception(
                                "Error finishing match %s",
                                m.id,
                            )

                            db.session.rollback()

                    # =========================================
                    # ROUND SETTLEMENT
                    # =========================================

                    matches_in_round = (
                        Fixture.query
                        .filter(
                            Fixture.season
                            == active_season,

                            Fixture.round
                            == current_round,
                        )
                        .all()
                    )

                    if (
                        matches_in_round
                        and all(
                            m.status
                            == STATUS_FINISHED
                            for m in matches_in_round
                        )
                    ):

                        queued = 0

                        for m in matches_in_round:

                            if not m.is_settled:

                                if _submit_settlement(
                                    m.id
                                ):
                                    queued += 1

                        if queued:

                            logger.info(
                                "âœ… Season %s Round %s "
                                "settlement queued: %d match(es)",
                                active_season,
                                current_round,
                                queued,
                            )

                except Exception as e:

                    logger.exception(
                        "Engine error: %s",
                        e,
                    )

                    try:
                        db.session.rollback()
                    except Exception:
                        pass

                _sleep_or_shutdown(
                    1
                )

        logger.info(
            "Engine loop exited"
        )

    # ========================================================
    # START ENGINE THREAD
    # ========================================================

    engine_thread = threading.Thread(
        target=run_engine,
        daemon=True,
        name="virtual-engine",
    )

    engine_thread.start()

    logger.info(
        "âœ… Virtual engine started"
    )

    return engine_thread


# ============================================================
# STOP ENGINE
# ============================================================

def stop_engine(
    timeout: int = 10,
):
    global engine_thread
    global simulation_executor
    global settlement_executor

    logger.info(
        "Stopping engine..."
    )

    # --------------------------------------------------------
    # 1. Stop accepting NEW work.
    # --------------------------------------------------------

    shutdown_flag.set()

    # --------------------------------------------------------
    # 2. Wait for the engine loop to stop first.
    #
    # This is the critical fix:
    # the engine must finish before executors are shut down.
    # --------------------------------------------------------

    engine_stopped = True

    if (
        engine_thread is not None
        and engine_thread.is_alive()
    ):

        engine_thread.join(
            timeout=timeout
        )

        engine_stopped = not engine_thread.is_alive()

        if not engine_stopped:

            logger.error(
                "âš ï¸ Engine thread did not stop within %ss; "
                "keeping PostgreSQL advisory lock held",
                timeout,
            )

    # --------------------------------------------------------
    # 3. Shut down executors under one lock.
    # --------------------------------------------------------

    with executor_lock:

        # ----------------------------------------------------
        # Simulation executor
        # ----------------------------------------------------

        if simulation_executor is not None:

            try:

                simulation_executor.shutdown(
                    wait=False,
                    cancel_futures=True,
                )

            except Exception:

                logger.exception(
                    "Error shutting down "
                    "simulation executor"
                )

            finally:

                simulation_executor = None

        # ----------------------------------------------------
        # Settlement executor
        # ----------------------------------------------------

        if settlement_executor is not None:

            try:

                settlement_executor.shutdown(
                    wait=False,
                    cancel_futures=True,
                )

            except Exception:

                logger.exception(
                    "Error shutting down "
                    "settlement executor"
                )

            finally:

                settlement_executor = None

    # --------------------------------------------------------
    # 4. Clear any local active simulation claims.
    # --------------------------------------------------------

    with simulation_guard_lock:

        active_simulations.clear()

    with settlement_guard_lock:

        active_settlements.clear()
        settlement_retry_after.clear()

    # --------------------------------------------------------
    # 5. Release PostgreSQL advisory lock LAST.
    # --------------------------------------------------------
    #
    # Never release the global lock while the engine thread is still
    # alive. Doing so could allow a second Render/Gunicorn worker to
    # start another engine against the same database.
    # --------------------------------------------------------

    if engine_stopped:

        _release_engine_advisory_lock()

        engine_thread = None

        logger.info(
            "âœ… Engine stopped"
        )

    else:

        logger.error(
            "ðŸš¨ Engine shutdown incomplete; "
            "advisory lock remains held"
        )
