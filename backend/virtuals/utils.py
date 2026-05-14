import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from virtuals.config_settings import (
    STATUS_RUNNING,
    STATUS_FINISHED,
    STATUS_OPEN,
    STATUS_SCHEDULED,
    T_FIXTURES,
)
from virtuals.config import logger, db, redis_client, app
from virtuals.model import Odds

# ---------------- DB session helper ----------------
SessionLocal = None


def get_session_local():
    """
    Lazily create a session factory bound to the current SQLAlchemy engine.
    Must be called inside an app context before first use.
    """
    global SessionLocal
    if SessionLocal is None:
        with app.app_context():
            SessionLocal = sessionmaker(bind=db.engine)
    return SessionLocal


# ---------------- time helpers ----------------
def now_utc():
    return datetime.now(timezone.utc)


def to_utc(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ---------------- shutdown flag ----------------
shutdown_flag = threading.Event()


# ---------------- concurrency primitives ----------------
_match_locks = {}
_match_locks_lock = threading.Lock()


@contextmanager
def match_lock(match_id, blocking=True, timeout=None):
    with _match_locks_lock:
        if match_id not in _match_locks:
            _match_locks[match_id] = threading.Lock()
        lock = _match_locks[match_id]

    acquired = (
        lock.acquire(blocking=blocking, timeout=timeout)
        if timeout is not None
        else lock.acquire(blocking=blocking)
    )
    try:
        if not acquired:
            raise RuntimeError(f"Could not acquire lock for match {match_id}")
        yield
    finally:
        if acquired:
            try:
                lock.release()
            except RuntimeError:
                pass


# ---------------- DB helpers ----------------
def try_set_fixture_status_atomic(session, match_id, expected_status, new_status):
    """
    Atomic UPDATE ... WHERE status = expected_status.
    Prevents race conditions between scheduler workers.
    """
    q = text(
        f"UPDATE {T_FIXTURES} "
        "SET status = :new "
        "WHERE id = :mid AND status = :exp"
    )
    res = session.execute(q, {"new": new_status, "mid": match_id, "exp": expected_status})
    return getattr(res, "rowcount", 0) == 1


def safe_commit(session, max_retries=3, backoff=0.05):
    """
    Commit with retry for optimistic concurrency conflicts.
    """
    for attempt in range(1, max_retries + 1):
        try:
            session.commit()
            return True
        except StaleDataError as e:
            session.rollback()
            logger.warning(
                "StaleDataError on commit (attempt %d/%d): %s",
                attempt,
                max_retries,
                e,
            )
            if attempt == max_retries:
                raise
            time.sleep(backoff * attempt)
        except Exception:
            session.rollback()
            raise


# ---------------- Match status helper ----------------
def compute_match_status(m):
    now = now_utc()
    ot = to_utc(getattr(m, "open_time", None))
    st = to_utc(getattr(m, "start_time", None))
    et = to_utc(getattr(m, "end_time", None))

    if st and et and st <= now <= et:
        return STATUS_RUNNING
    if et and now > et:
        return STATUS_FINISHED
    if ot and now >= ot and (not st or now < st):
        return STATUS_OPEN
    return STATUS_SCHEDULED


# ---------------- Redis / odds cache keys ----------------
def exposure_key(match_id, selection):
    return f"match:{match_id}:exposure:{selection}"


def total_exposure_key(match_id):
    return f"match:{match_id}:exposure:total"


def cache_odds_key(match_id):
    return f"match:{match_id}:odds:cached"


# ---------------- Match serialization ----------------
def _match_to_dict(m):
    cached = {}
    try:
        cached_raw = redis_client.hgetall(cache_odds_key(m.id))
        if cached_raw:
            cached = {k.decode(): float(v.decode()) for k, v in cached_raw.items()}
    except Exception:
        logger.exception("Failed to read cached odds for match %s", m.id)

    odds = cached or None
    if not odds:
        odds_row = (
            db.session.query(Odds)
            .filter_by(match_id=m.id)
            .order_by(Odds.created_at.desc())
            .first()
        )
        if odds_row:
            odds = {
             "home": float(odds_row.home) if odds_row.home is not None else None,
             "draw": float(odds_row.draw) if odds_row.draw is not None else None,
             "away": float(odds_row.away) if odds_row.away is not None else None,
             "over25": float(odds_row.over25) if odds_row.over25 is not None else None,
             "under25": float(odds_row.under25) if odds_row.under25 is not None else None,
             "over15": float(odds_row.over15) if odds_row.over15 is not None else None,
             "under15": float(odds_row.under15) if odds_row.under15 is not None else None,
             "btts_yes": float(odds_row.btts_yes) if odds_row.btts_yes is not None else None,
             "btts_no": float(odds_row.btts_no) if odds_row.btts_no is not None else None,
}

    now = now_utc()
    start = to_utc(getattr(m, "start_time", None))
    end = to_utc(getattr(m, "end_time", None))
    open_time = to_utc(getattr(m, "open_time", None))

    return {
        "id": m.id,
        "home": m.home,
        "away": m.away,
        "status": compute_match_status(m),
        "round": getattr(m, "round", None),
        "open_time": open_time.isoformat() if open_time else None,
        "start_time": start.isoformat() if start else None,
        "end_time": end.isoformat() if end else None,
        "score": f"{getattr(m, 'home_score', 0) or 0}-{getattr(m, 'away_score', 0) or 0}",
        "time_to_start": int((start - now).total_seconds()) if start else None,
        "time_to_end": int((end - now).total_seconds()) if end else None,
        "event_count": getattr(m, "event_count", 0) or 0,
        "odds": odds,
    }
