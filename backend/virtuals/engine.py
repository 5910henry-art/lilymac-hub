# virtuals/engine.py

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from .odds_refresh import refresh_open_fixture_odds
from .utils import now_utc, try_set_fixture_status_atomic

logger = logging.getLogger("virtual-engine")

engine_thread: threading.Thread | None = None
simulation_executor: ThreadPoolExecutor | None = None
settlement_executor: ThreadPoolExecutor | None = None

FORCE_FINISH_GRACE_SECONDS = int(
    os.getenv("VIRTUAL_FORCE_FINISH_GRACE_SECONDS", "120")
)

# Cap how many match simulations can be submitted at once.
# Keep this lower than or equal to your DB comfort level.
ENGINE_WORKERS = int(os.getenv("VIRTUAL_ENGINE_WORKERS", "10"))

# How old a fixture must be before we stop "resuming" it and fully re-queue it.
RECOVERY_STALE_SECONDS = int(os.getenv("VIRTUAL_RECOVERY_STALE_SECONDS", "900"))

# Stagger match starts a little so they do not all hit the DB at the same instant.
ENGINE_START_STAGGER_SECONDS = float(
    os.getenv("VIRTUAL_ENGINE_START_STAGGER_SECONDS", "0.2")
)

# How often to print engine health.
ENGINE_HEALTH_LOG_SECONDS = int(os.getenv("VIRTUAL_ENGINE_HEALTH_LOG_SECONDS", "30"))

# ---------------- GLOBAL SHUTDOWN FLAG ----------------
shutdown_flag = threading.Event()

# Prevent the same match from being submitted twice at the same time.
simulation_guard_lock = threading.Lock()
active_simulations: set[int] = set()

# Prevent repeated season regeneration attempts for the same terminal state.
season_generation_lock = threading.Lock()
last_season_generation_key: str | None = None


def _fmt_dt(value):
    """Format datetime for logs without crashing on None."""
    if value is None:
        return "None"
    try:
        return value.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def _sleep_or_shutdown(seconds: float, step: float = 0.25):
    """Sleep in small chunks so shutdown stays responsive."""
    remaining = seconds
    while remaining > 0 and not shutdown_flag.is_set():
        chunk = min(step, remaining)
        shutdown_flag.wait(chunk)
        remaining -= chunk


def _active_fixture_count(db, Fixture, STATUS_FINISHED):
    return (
        db.session.query(Fixture.id)
        .filter(Fixture.status != STATUS_FINISHED)
        .count()
    )


def _running_fixture_count(db, Fixture, STATUS_RUNNING):
    return db.session.query(Fixture.id).filter(Fixture.status == STATUS_RUNNING).count()


def _last_round_number(db, Fixture):
    row = db.session.query(Fixture.round).order_by(Fixture.round.desc()).first()
    return row[0] if row else None


def _settle_unsettled_finished_matches(db, Fixture, STATUS_FINISHED, settle_virtual_bets):
    """
    Settle any finished matches that have not yet been settled.
    Returns the number of matches processed.
    """
    unsettled_matches = (
        db.session.query(Fixture)
        .filter(
            Fixture.is_settled == False,  # noqa: E712
            Fixture.status == STATUS_FINISHED,
        )
        .all()
    )

    processed = 0

    for m in unsettled_matches:
        try:
            settle_virtual_bets(m.id)
            processed += 1
        except Exception:
            logger.exception("Error force-settling match %s", m.id)

    return processed


def _maybe_generate_fresh_season(
    app,
    db,
    Fixture,
    STATUS_FINISHED,
    generate_full_season,
    settle_virtual_bets=None,
):
    """
    Generate a fresh season only once for the same terminal DB state.
    """
    global last_season_generation_key

    with app.app_context():
        total_count = db.session.query(Fixture.id).count()
        active_count = _active_fixture_count(db, Fixture, STATUS_FINISHED)

        # If there are still active fixtures, do nothing.
        if active_count > 0:
            last_season_generation_key = None
            return False

        # Settle any unfinished finished fixtures before generating a new season.
        if settle_virtual_bets is not None:
            _settle_unsettled_finished_matches(
                db=db,
                Fixture=Fixture,
                STATUS_FINISHED=STATUS_FINISHED,
                settle_virtual_bets=settle_virtual_bets,
            )

        last_round = _last_round_number(db, Fixture)
        terminal_key = f"total={total_count}|last_round={last_round}"

        with season_generation_lock:
            if last_season_generation_key == terminal_key:
                return False

            if total_count > 0:
                logger.info(
                    "🧹 No active fixtures found, old fixtures remain intact and a fresh season will be generated"
                )
            else:
                logger.info("🆕 No fixtures found, generating a fresh season")

            try:
                generate_full_season()
                db.session.expire_all()
            except Exception:
                logger.exception("Error generating fresh season")
                db.session.rollback()
            finally:
                last_season_generation_key = terminal_key

        return True


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
    Hybrid startup recovery:
    - Recent RUNNING matches are resumed from now
    - Recent OPEN matches are nudged forward if needed
    - Stale or badly interrupted fixtures are fully re-queued cleanly
    """
    with app.app_context():
        incomplete = (
            db.session.query(Fixture)
            .filter(Fixture.status != STATUS_FINISHED)
            .order_by(Fixture.round.asc(), Fixture.id.asc())
            .all()
        )

        if not incomplete:
            return

        now = now_utc().replace(second=0, microsecond=0)
        stale_cutoff = now - timedelta(seconds=RECOVERY_STALE_SECONDS)

        rounds = sorted({m.round for m in incomplete if m.round is not None})
        round_start_map = {}
        for idx, round_no in enumerate(rounds):
            round_start_map[round_no] = now + timedelta(seconds=2 + idx * ROUND_INTERVAL)

        recovered = 0
        resumed = 0
        requeued = 0

        for m in incomplete:
            try:
                round_start = round_start_map.get(
                    m.round,
                    now + timedelta(seconds=2 + max(0, (m.round or 1) - 1) * ROUND_INTERVAL),
                )

                anchor_time = m.end_time or m.start_time or m.open_time
                is_stale = anchor_time is None or anchor_time <= stale_cutoff

                if is_stale:
                    m.status = STATUS_SCHEDULED
                    m.is_settled = False
                    m.event_count = 0
                    m.home_score = 0
                    m.away_score = 0
                    m.open_time = round_start
                    m.start_time = round_start + timedelta(seconds=BETTING_TIME)
                    m.end_time = round_start + timedelta(
                        seconds=BETTING_TIME + MATCH_SIM_SECONDS
                    )
                    requeued += 1
                    recovered += 1
                    continue

                if m.status == STATUS_RUNNING:
                    m.status = STATUS_OPEN
                    m.is_settled = False
                    m.event_count = 0
                    m.home_score = 0
                    m.away_score = 0
                    m.open_time = now + timedelta(seconds=2)
                    m.start_time = now + timedelta(seconds=5)
                    m.end_time = m.start_time + timedelta(seconds=MATCH_SIM_SECONDS)
                    resumed += 1
                    recovered += 1
                    continue

                if m.status == STATUS_OPEN:
                    if not m.start_time or m.start_time < now:
                        m.start_time = now + timedelta(seconds=5)
                    if not m.end_time or m.end_time <= m.start_time:
                        m.end_time = m.start_time + timedelta(seconds=MATCH_SIM_SECONDS)
                    resumed += 1
                    recovered += 1
                    continue

                if m.status == STATUS_SCHEDULED:
                    if (
                        not m.open_time
                        or not m.start_time
                        or not m.end_time
                        or m.open_time < now
                    ):
                        m.open_time = round_start
                        m.start_time = round_start + timedelta(seconds=BETTING_TIME)
                        m.end_time = round_start + timedelta(
                            seconds=BETTING_TIME + MATCH_SIM_SECONDS
                        )
                    recovered += 1

            except Exception:
                logger.exception("Failed recovering fixture %s", getattr(m, "id", "?"))

        db.session.commit()

        logger.info(
            "🔄 Recovered %d incomplete fixture(s) from previous run (%d resumed, %d re-queued)",
            recovered,
            resumed,
            requeued,
        )


def _force_finish_stuck_running_matches(db, Fixture, STATUS_RUNNING, STATUS_FINISHED):
    """
    Force-finish any RUNNING matches that appear stuck beyond the grace window.
    """
    now = now_utc()
    cutoff = now - timedelta(seconds=FORCE_FINISH_GRACE_SECONDS)

    running_matches = (
        db.session.query(Fixture)
        .filter(Fixture.status == STATUS_RUNNING)
        .order_by(Fixture.round.asc(), Fixture.id.asc())
        .all()
    )

    forced = 0

    for m in running_matches:
        try:
            effective_end = None
            if m.end_time is not None:
                effective_end = m.end_time
            elif m.start_time is not None:
                effective_end = m.start_time + timedelta(seconds=45)
            elif m.open_time is not None:
                effective_end = m.open_time + timedelta(seconds=45)
            else:
                effective_end = now - timedelta(seconds=1)

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

            if m.end_time is None or m.end_time < effective_end:
                m.end_time = effective_end

            db.session.commit()

            logger.warning(
                "⚠️ FORCE FINISH Match %d | open_time=%s | start_time=%s | end_time=%s",
                m.id,
                _fmt_dt(m.open_time),
                _fmt_dt(m.start_time),
                _fmt_dt(m.end_time),
            )
            forced += 1

        except Exception:
            logger.exception("Failed force-finishing stuck match %s", getattr(m, "id", "?"))
            db.session.rollback()

    return forced


def _log_engine_health(db, Fixture, STATUS_RUNNING, STATUS_FINISHED):
    try:
        active_count = _active_fixture_count(db, Fixture, STATUS_FINISHED)
    except Exception:
        active_count = None

    try:
        running_count = _running_fixture_count(db, Fixture, STATUS_RUNNING)
    except Exception:
        running_count = None

    with simulation_guard_lock:
        sim_count = len(active_simulations)

    logger.info(
        "[engine] health | active=%s | running=%s | simulating=%d",
        active_count if active_count is not None else "?",
        running_count if running_count is not None else "?",
        sim_count,
    )


def start_virtual_engine(emit_update_callback=None):
    global engine_thread
    global simulation_executor
    global settlement_executor

    if engine_thread is None or not engine_thread.is_alive():
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

        if simulation_executor is None:
            simulation_executor = ThreadPoolExecutor(max_workers=ENGINE_WORKERS)

        if settlement_executor is None:
            settlement_executor = ThreadPoolExecutor(max_workers=3)

        def _submit_simulation(match_id: int):
            """
            Submit one simulation exactly once per match at a time.
            """
            with simulation_guard_lock:
                if match_id in active_simulations:
                    logger.warning("Match %d already simulating — skipping", match_id)
                    return False
                active_simulations.add(match_id)

            def _runner():
                try:
                    simulate_match(match_id, emit_update_callback)
                except Exception:
                    logger.exception("Simulation crashed for match %s", match_id)
                finally:
                    with simulation_guard_lock:
                        active_simulations.discard(match_id)

            try:
                if simulation_executor is not None:
                    simulation_executor.submit(_runner)
                else:
                    threading.Thread(target=_runner, daemon=True).start()
                return True
            except Exception:
                with simulation_guard_lock:
                    active_simulations.discard(match_id)
                raise

        def _submit_settlement(match_id: int):
            try:
                if settlement_executor is not None:
                    settlement_executor.submit(settle_virtual_bets, match_id)
                else:
                    threading.Thread(
                        target=settle_virtual_bets,
                        args=(match_id,),
                        daemon=True,
                    ).start()
            except Exception:
                logger.exception("Error submitting settlement for match %s", match_id)

        def run_engine():
            with app.app_context():
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

                    _maybe_generate_fresh_season(
                        app=app,
                        db=db,
                        Fixture=Fixture,
                        STATUS_FINISHED=STATUS_FINISHED,
                        generate_full_season=generate_full_season,
                        settle_virtual_bets=settle_virtual_bets,
                    )
                except Exception:
                    logger.exception("Error preparing season at startup")
                    db.session.rollback()

                last_cleanup_check = time.time()
                last_health_log = time.time()
                last_odds_refresh = time.time()
                ODDS_REFRESH_INTERVAL = 60

                while not shutdown_flag.is_set():
                    try:
                        now = now_utc()

                        # -------- engine health --------
                        if time.time() - last_health_log > ENGINE_HEALTH_LOG_SECONDS:
                            _log_engine_health(db, Fixture, STATUS_RUNNING, STATUS_FINISHED)
                            last_health_log = time.time()

                        # -------- refresh open fixture odds --------
                        if time.time() - last_odds_refresh > ODDS_REFRESH_INTERVAL:
                            try:
                                refreshed_count = refresh_open_fixture_odds(db.session, lookback=5)
                                if refreshed_count:
                                    logger.info(
                                        "🎲 Refreshed odds for %d open fixtures", refreshed_count
                                    )
                            except Exception:
                                logger.exception("Error refreshing open fixture odds")
                            finally:
                                last_odds_refresh = time.time()

                        # -------- periodic settlement cleanup --------
                        if time.time() - last_cleanup_check > 10:
                            try:
                                _settle_unsettled_finished_matches(
                                    db=db,
                                    Fixture=Fixture,
                                    STATUS_FINISHED=STATUS_FINISHED,
                                    settle_virtual_bets=settle_virtual_bets,
                                )
                            except Exception:
                                logger.exception("Error during cleanup settlement")
                                db.session.rollback()

                            last_cleanup_check = time.time()

                        # -------- stuck match recovery --------
                        try:
                            _force_finish_stuck_running_matches(
                                db=db,
                                Fixture=Fixture,
                                STATUS_RUNNING=STATUS_RUNNING,
                                STATUS_FINISHED=STATUS_FINISHED,
                            )
                        except Exception:
                            logger.exception("Error force-finishing stuck matches")
                            db.session.rollback()

                        # -------- ensure active season --------
                        active_count = _active_fixture_count(db, Fixture, STATUS_FINISHED)
                        if active_count == 0:
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
                                logger.exception("Error ensuring active season")
                                db.session.rollback()

                            _sleep_or_shutdown(1)
                            continue

                        # -------- current round --------
                        current_round_row = (
                            db.session.query(Fixture.round)
                            .filter(
                                Fixture.status.in_(
                                    [STATUS_SCHEDULED, STATUS_OPEN, STATUS_RUNNING]
                                )
                            )
                            .order_by(Fixture.round.asc())
                            .first()
                        )

                        if not current_round_row:
                            logger.warning(
                                "⚠️ No active round found while fixtures exist. Attempting recovery..."
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
                                logger.exception("Error recovering broken round state")
                                db.session.rollback()

                            _sleep_or_shutdown(1)
                            continue

                        current_round = current_round_row[0]

                        # -------- open matches --------
                        running_count = _running_fixture_count(db, Fixture, STATUS_RUNNING)
                        slots_available = max(0, MAX_ACTIVE_MATCHES - running_count)

                        if slots_available > 0:
                            matches_to_open = (
                                Fixture.query.filter(
                                    Fixture.round == current_round,
                                    Fixture.status == STATUS_SCHEDULED,
                                    Fixture.open_time <= now,
                                )
                                .order_by(Fixture.id.asc())
                                .limit(min(slots_available, MATCHES_PER_ROUND))
                                .all()
                            )

                            for m in matches_to_open:
                                try:
                                    updated = try_set_fixture_status_atomic(
                                        db.session,
                                        m.id,
                                        STATUS_SCHEDULED,
                                        STATUS_OPEN,
                                    )
                                    if not updated:
                                        continue

                                    db.session.commit()

                                    logger.info(
                                        "🟢 OPEN Match %d (R%d): %s vs %s | open_time=%s",
                                        m.id,
                                        m.round,
                                        m.home,
                                        m.away,
                                        _fmt_dt(m.open_time),
                                    )

                                    socketio.emit(
                                        "match_open",
                                        {
                                            "match_id": m.id,
                                            "home": m.home,
                                            "away": m.away,
                                        },
                                    )

                                except Exception:
                                    logger.exception("Error opening match %s", m.id)
                                    db.session.rollback()

                        # -------- start matches --------
                        running_count = _running_fixture_count(db, Fixture, STATUS_RUNNING)
                        slots_available = max(0, MAX_ACTIVE_MATCHES - running_count)

                        if slots_available > 0:
                            to_start = (
                                Fixture.query.filter(
                                    Fixture.round == current_round,
                                    Fixture.status == STATUS_OPEN,
                                    Fixture.start_time <= now,
                                )
                                .order_by(Fixture.id.asc())
                                .limit(min(slots_available, ENGINE_WORKERS))
                                .all()
                            )

                            for idx, m in enumerate(to_start):
                                try:
                                    updated = try_set_fixture_status_atomic(
                                        db.session,
                                        m.id,
                                        STATUS_OPEN,
                                        STATUS_RUNNING,
                                    )
                                    if not updated:
                                        continue

                                    db.session.commit()

                                    logger.info(
                                        "▶️ START Match %d: %s vs %s | open_time=%s | start_time=%s",
                                        m.id,
                                        m.home,
                                        m.away,
                                        _fmt_dt(m.open_time),
                                        _fmt_dt(m.start_time),
                                    )

                                    if idx > 0 and ENGINE_START_STAGGER_SECONDS > 0:
                                        _sleep_or_shutdown(
                                            ENGINE_START_STAGGER_SECONDS * idx
                                        )

                                    _submit_simulation(m.id)

                                except Exception:
                                    logger.exception("Error starting match %s", m.id)
                                    db.session.rollback()

                        # -------- force finish overdue matches --------
                        timeout_cutoff = now - timedelta(
                            seconds=FORCE_FINISH_GRACE_SECONDS
                        )

                        finished = (
                            Fixture.query.filter(
                                Fixture.status == STATUS_RUNNING,
                                Fixture.end_time.isnot(None),
                                Fixture.end_time <= timeout_cutoff,
                            )
                            .order_by(Fixture.id.asc())
                            .all()
                        )

                        for m in finished:
                            if m.end_time and (now - m.end_time).total_seconds() > 10:
                                continue

                            try:
                                updated = try_set_fixture_status_atomic(
                                    db.session,
                                    m.id,
                                    STATUS_RUNNING,
                                    STATUS_FINISHED,
                                )
                                if not updated:
                                    continue

                                db.session.commit()
                                logger.warning(
                                    "⚠️ TIMEOUT FINISH Match %d | open_time=%s | start_time=%s | end_time=%s",
                                    m.id,
                                    _fmt_dt(m.open_time),
                                    _fmt_dt(m.start_time),
                                    _fmt_dt(m.end_time),
                                )

                            except Exception:
                                logger.exception("Error finishing match %s", m.id)
                                db.session.rollback()

                        # -------- round settlement --------
                        matches_in_round = Fixture.query.filter(
                            Fixture.round == current_round
                        ).all()

                        if matches_in_round and all(
                            m.status == STATUS_FINISHED for m in matches_in_round
                        ):
                            for m in matches_in_round:
                                if not m.is_settled:
                                    _submit_settlement(m.id)

                            logger.info(
                                "✅ Round %s settlement queued",
                                current_round,
                            )

                    except Exception as e:
                        logger.exception("Engine error: %s", e)
                        db.session.rollback()

                    _sleep_or_shutdown(1)

                logger.info("Engine loop exited")

        engine_thread = threading.Thread(target=run_engine, daemon=True)
        engine_thread.start()
        logger.info("✅ Virtual engine started")

    return engine_thread


def stop_engine(timeout: int = 10):
    logger.info("Stopping engine...")
    shutdown_flag.set()

    global engine_thread
    global simulation_executor
    global settlement_executor

    if simulation_executor is not None:
        try:
            simulation_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            logger.exception("Error shutting down simulation executor")
        finally:
            simulation_executor = None

    if settlement_executor is not None:
        try:
            settlement_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            logger.exception("Error shutting down settlement executor")
        finally:
            settlement_executor = None

    if engine_thread and engine_thread.is_alive():
        engine_thread.join(timeout=timeout)
        logger.info("✅ Engine stopped")
