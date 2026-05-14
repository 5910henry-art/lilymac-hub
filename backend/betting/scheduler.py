# scheduler.py
import logging
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import or_
from sqlalchemy.orm import sessionmaker

from betting.models import (
    db,
    Match,
    Bet,
    BetSelection,
    BetSlip,
    Bookmark,
    User,
    Transaction,
)
from betting.utils import to_decimal, evaluate_selection_win, calculate_live_cashout

logger = logging.getLogger(__name__)

BATCH_SIZE = 250
_missing_match_logged = set()
_missing_cashout_logged = set()


def _utcnow():
    return datetime.now(timezone.utc)


def _safe_add_warning(cache_set, key, message, *args):
    if key in cache_set:
        return
    cache_set.add(key)
    logger.warning(message, *args)
    if len(cache_set) > 5000:
        cache_set.clear()


def _has_actionable_matches(now, session=None):
    """
    Returns True if there are matches that could require processing now:
    - FINISHED
    - IN_PLAY
    - POSTPONED
    - ABANDONED

    Matches with utcdate in the future are ignored.
    """
    session = session or db.session
    return (
        session.query(Match.id)
        .filter(
            Match.status.in_(["FINISHED", "IN_PLAY", "POSTPONED", "ABANDONED"]),
            or_(Match.utcdate.is_(None), Match.utcdate <= now),
        )
        .first()
        is not None
    )


def settle_single_bet(session, bet, match):
    if bet.cashed_out or bet.status != "pending":
        return bet.status

    user = session.get(User, bet.user_id)
    if not user:
        logger.warning("Bet %s has no user assigned", bet.id)
        return None

    try:
        won = evaluate_selection_win(match.home_score, match.away_score, bet.selection)
    except Exception as e:
        logger.exception("Error evaluating bet %s: %s", bet.id, e)
        return None

    if won is True:
        bet.status = "won"
        user.balance = to_decimal(user.balance) + to_decimal(bet.potential)
        session.add(
            Transaction(
                user_id=user.id,
                type="bet_win",
                amount=to_decimal(bet.potential),
                balance_after=to_decimal(user.balance),
            )
        )
    elif won is False:
        bet.status = "lost"
        session.add(
            Transaction(
                user_id=user.id,
                type="bet_loss",
                amount=Decimal("0.00"),
                balance_after=to_decimal(user.balance),
            )
        )

    session.add(bet)
    return bet.status


def settle_bets_for_matches(session, finished_matches):
    settled_count = 0

    for match in finished_matches:
        if match.home_score is None or match.away_score is None:
            continue

        last_id = 0
        while True:
            bets = (
                session.query(Bet)
                .enable_eagerloads(False)
                .filter(
                    Bet.match_id == match.id,
                    Bet.status == "pending",
                    Bet.id > last_id,
                )
                .order_by(Bet.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
                .all()
            )

            if not bets:
                break

            for bet in bets:
                try:
                    result = settle_single_bet(session, bet, match)
                    if result in ("won", "lost"):
                        settled_count += 1
                except Exception as e:
                    logger.exception("Error settling bet %s: %s", bet.id, e)

            last_id = bets[-1].id

    return settled_count


def _resolve_match_for_selection(sel, matches_map, bookmarks_map):
    if not sel.bookmark_id:
        return None

    bookmark = bookmarks_map.get(sel.bookmark_id)
    if bookmark and getattr(bookmark, "match_id", None):
        match = matches_map.get(bookmark.match_id)
        if match:
            return match

    return matches_map.get(sel.bookmark_id)


def settle_bet_selections(session, pending_selections, matches_map, bookmarks_map, now):
    settled = 0
    voided = 0

    for sel in pending_selections:
        if not sel.bookmark_id:
            _safe_add_warning(
                _missing_match_logged,
                f"sel-no-bookmark-{sel.id}",
                "BetSelection %s has no bookmark_id assigned",
                sel.id,
            )
            continue

        match = _resolve_match_for_selection(sel, matches_map, bookmarks_map)
        if not match:
            _safe_add_warning(
                _missing_match_logged,
                f"sel-no-match-{sel.id}",
                "BetSelection %s has no match assigned",
                sel.id,
            )
            continue

        if match.utcdate and match.utcdate > now:
            continue

        if match.status in ("POSTPONED", "ABANDONED"):
            if sel.status != "voided":
                sel.status = "voided"
                session.add(sel)
                voided += 1
            continue

        if match.status != "FINISHED":
            continue

        if match.home_score is None or match.away_score is None:
            continue

        try:
            won = evaluate_selection_win(match.home_score, match.away_score, sel.selection)
            new_status = "won" if won else "lost" if won is False else "pending"
            if new_status != sel.status:
                sel.status = new_status
                session.add(sel)
                if new_status in ("won", "lost"):
                    settled += 1
        except Exception as e:
            logger.exception("Error settling BetSelection %s: %s", sel.id, e)

    return settled, voided


def settle_betslips(session, pending_slips):
    settled = 0
    voided = 0

    for slip in pending_slips:
        try:
            if slip.status != "pending":
                continue

            selections = slip.selections
            if not selections:
                continue

            if any(s.status == "pending" for s in selections):
                continue

            user = session.get(User, slip.user_id)
            if not user:
                logger.warning("BetSlip %s has no user assigned", slip.id)
                continue

            if any(s.status == "voided" for s in selections):
                slip.status = "voided"
                stake = to_decimal(getattr(slip, "stake", Decimal("0.00")))
                user.balance = to_decimal(user.balance) + stake
                session.add(
                    Transaction(
                        user_id=user.id,
                        type="bet_voided",
                        amount=stake,
                        balance_after=to_decimal(user.balance),
                    )
                )
                session.add(slip)
                voided += 1
                continue

            if any(s.status == "lost" for s in selections):
                slip.status = "lost"
                session.add(
                    Transaction(
                        user_id=user.id,
                        type="bet_loss",
                        amount=Decimal("0.00"),
                        balance_after=to_decimal(user.balance),
                    )
                )
            else:
                slip.status = "won"
                user.balance = to_decimal(user.balance) + to_decimal(slip.potential)
                session.add(
                    Transaction(
                        user_id=user.id,
                        type="bet_win",
                        amount=to_decimal(slip.potential),
                        balance_after=to_decimal(user.balance),
                    )
                )

            session.add(slip)
            settled += 1

        except Exception as e:
            logger.exception("Error settling BetSlip %s: %s", slip.id, e)

    return settled, voided


def update_bet_cashout(session, bet, matches_map, bookmarks_map, now):
    try:
        match = matches_map.get(bet.match_id)
        bookmark = bookmarks_map.get(bet.match_id)

        if not match:
            _safe_add_warning(
                _missing_cashout_logged,
                f"bet-no-match-cashout-{bet.id}",
                "Bet %s has no match assigned for cashout",
                bet.id,
            )
            return False

        if match.utcdate and match.utcdate > now:
            return False

        if match.status != "IN_PLAY":
            return False

        bet.current_cashout = calculate_live_cashout(bet, match, bookmark)
        session.add(bet)
        return True

    except Exception as e:
        logger.exception("Error updating cashout for bet %s: %s", bet.id, e)
        return False


def _selection_market_family(selection):
    sel = (selection or "").lower()

    if sel in ("home_odds", "home", "draw_odds", "draw", "away_odds", "away"):
        return "1x2"

    if sel.startswith("over") or sel.startswith("under"):
        return "ou"

    if sel in ("gg_odds", "btts", "ng_odds", "no_btts"):
        return "btts"

    return "other"


def _leg_probability(sel, match, bookmark):
    """
    Estimate the current probability for a single betslip leg by reusing
    calculate_live_cashout on a temp bet with potential=1.00.
    """
    class TempBet:
        pass

    temp = TempBet()
    temp.status = "pending"
    temp.cashed_out = False
    temp.selection = sel.selection
    temp.odds = sel.odds
    temp.potential = Decimal("1.00")

    cashout = calculate_live_cashout(temp, match, bookmark)
    prob = to_decimal(cashout, quantize=False)

    return max(Decimal("0.0"), min(Decimal("1.0"), prob))


def _correlation_factor(legs):
    """
    Reduce cashout when legs are correlated.
    Same-match legs are penalized more heavily than same-family legs.
    """
    factor = Decimal("1.0")
    match_counts = {}
    family_counts = {}

    for leg in legs:
        match_counts[leg["match_id"]] = match_counts.get(leg["match_id"], 0) + 1
        family_counts[leg["family"]] = family_counts.get(leg["family"], 0) + 1

    for count in match_counts.values():
        if count > 1:
            factor *= Decimal("0.88") ** (count - 1)

    for count in family_counts.values():
        if count > 1:
            factor *= Decimal("0.95") ** (count - 1)

    if len(legs) >= 4:
        factor *= Decimal("0.98")

    return max(Decimal("0.50"), min(Decimal("1.0"), factor))


def update_betslip_cashout(session, slip, matches_map, bookmarks_map, now):
    """
    Update live cashout for a BetSlip using:
    - per-leg live probability
    - correlation penalty for overlapping selections
    - conservative margin and caps
    """
    try:
        stake = to_decimal(getattr(slip, "stake", Decimal("0.00")))
        potential = to_decimal(slip.potential)

        if potential <= 0:
            slip.current_cashout = Decimal("0.00")
            session.add(slip)
            return False

        legs = []

        for sel in slip.selections:
            bookmark = bookmarks_map.get(sel.bookmark_id) if sel.bookmark_id else None

            match = None
            if bookmark and getattr(bookmark, "match_id", None):
                match = matches_map.get(bookmark.match_id)

            if not match and sel.bookmark_id:
                match = matches_map.get(sel.bookmark_id)

            if not match:
                _safe_add_warning(
                    _missing_cashout_logged,
                    f"slip-sel-no-match-cashout-{sel.id}",
                    "BetSelection %s has no match for cashout",
                    sel.id,
                )
                continue

            if match.utcdate and match.utcdate > now:
                continue

            if match.status != "IN_PLAY":
                continue

            leg_prob = _leg_probability(sel, match, bookmark)
            if leg_prob <= 0:
                continue

            legs.append(
                {
                    "sel_id": sel.id,
                    "match_id": match.id,
                    "family": _selection_market_family(sel.selection),
                    "prob": leg_prob,
                }
            )

        if not legs:
            slip.current_cashout = Decimal("0.00")
            session.add(slip)
            return False

        combined_prob = Decimal("1.0")
        for leg in legs:
            combined_prob *= leg["prob"]

        combined_prob = combined_prob.quantize(Decimal("0.0000001"), rounding=ROUND_DOWN)
        correlation = _correlation_factor(legs)

        slip_margin = Decimal("0.97")
        cashout = potential * combined_prob * correlation * slip_margin

        max_cashout = potential * Decimal("0.95")
        min_cashout = stake * Decimal("0.10") if stake > 0 else Decimal("0.00")

        cashout = min(cashout, max_cashout)
        cashout = max(cashout, min_cashout)

        slip.current_cashout = cashout.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        session.add(slip)
        return True

    except Exception as e:
        logger.exception("Error updating cashout for BetSlip %s: %s", slip.id, e)
        return False


def auto_settle_bets(session=None):
    """Settle all pending bets, selections, and betslips in batches."""
    session = session or db.session
    now = _utcnow()

    finished_matches = session.query(Match).filter(
        Match.status == "FINISHED",
        or_(Match.utcdate.is_(None), Match.utcdate <= now),
    ).order_by(Match.id).all()

    settled_bets = settle_bets_for_matches(session, finished_matches)

    matches = session.query(Match).all()
    bookmarks = session.query(Bookmark).all()

    matches_map = {m.id: m for m in matches}
    bookmarks_map = {b.match_id: b for b in bookmarks}

    total_sel_settled = 0
    total_sel_voided = 0

    last_id = 0
    while True:
        pending_selections = (
            session.query(BetSelection)
            .enable_eagerloads(False)
            .filter(
                BetSelection.status == "pending",
                BetSelection.id > last_id,
            )
            .order_by(BetSelection.id)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
            .all()
        )
        if not pending_selections:
            break

        settled, voided = settle_bet_selections(
            session, pending_selections, matches_map, bookmarks_map, now
        )
        total_sel_settled += settled
        total_sel_voided += voided
        last_id = pending_selections[-1].id

    session.flush()

    total_slip_settled = 0
    total_slip_voided = 0

    last_id = 0
    while True:
        pending_slips = (
            session.query(BetSlip)
            .enable_eagerloads(False)
            .filter(
                BetSlip.status == "pending",
                BetSlip.id > last_id,
            )
            .order_by(BetSlip.id)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
            .all()
        )
        if not pending_slips:
            break

        settled, voided = settle_betslips(session, pending_slips)
        total_slip_settled += settled
        total_slip_voided += voided
        last_id = pending_slips[-1].id

    return {
        "bets_settled": settled_bets,
        "selections_settled": total_sel_settled,
        "selections_voided": total_sel_voided,
        "slips_settled": total_slip_settled,
        "slips_voided": total_slip_voided,
    }


def auto_update_live_cashouts(session=None):
    """Update live cashouts for pending bets and betslips."""
    session = session or db.session
    now = _utcnow()

    live_matches = session.query(Match).filter(
        Match.status == "IN_PLAY",
        or_(Match.utcdate.is_(None), Match.utcdate <= now),
    ).all()

    if not live_matches:
        return {"bets_updated": 0, "slips_updated": 0}

    matches_map = {m.id: m for m in live_matches}
    bookmarks = session.query(Bookmark).all()
    bookmarks_map = {b.match_id: b for b in bookmarks}

    total_bets = 0
    total_slips = 0

    last_id = 0
    while True:
        bets = (
            session.query(Bet)
            .enable_eagerloads(False)
            .filter(
                Bet.status == "pending",
                Bet.id > last_id,
            )
            .order_by(Bet.id)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
            .all()
        )
        if not bets:
            break

        for bet in bets:
            if bet.match_id in matches_map and update_bet_cashout(session, bet, matches_map, bookmarks_map, now):
                total_bets += 1

        last_id = bets[-1].id

    last_id = 0
    while True:
        slips = (
            session.query(BetSlip)
            .enable_eagerloads(False)
            .filter(
                BetSlip.status == "pending",
                BetSlip.id > last_id,
            )
            .order_by(BetSlip.id)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
            .all()
        )
        if not slips:
            break

        for slip in slips:
            if update_betslip_cashout(session, slip, matches_map, bookmarks_map, now):
                total_slips += 1

        last_id = slips[-1].id

    return {"bets_updated": total_bets, "slips_updated": total_slips}


def start_scheduler(app, interval_seconds=60, daemon=True, stop_event=None):
    """
    Background scheduler for:
    - auto-settle bets, bet selections, betslips
    - update live cashouts

    Uses a dedicated SQLAlchemy session so it does not share Flask's scoped session
    with request handlers.
    """
    def run_scheduler():
        _missing_match_logged.clear()
        _missing_cashout_logged.clear()

        SessionLocal = None

        with app.app_context():
            SessionLocal = sessionmaker(
                bind=db.engine,
                autoflush=False,
                expire_on_commit=False,
            )

        while True:
            if stop_event is not None and stop_event.is_set():
                logger.info("Scheduler stopped.")
                break

            cycle_started = _utcnow()
            next_run_at = cycle_started.timestamp() + interval_seconds

            session = SessionLocal()
            try:
                pending_bets_count = session.query(Bet).filter(Bet.status == "pending").count()
                pending_selections_count = session.query(BetSelection).filter(BetSelection.status == "pending").count()
                pending_slips_count = session.query(BetSlip).filter(BetSlip.status == "pending").count()

                has_actionable_matches = _has_actionable_matches(cycle_started, session)

                if (
                    pending_bets_count == 0
                    and pending_selections_count == 0
                    and pending_slips_count == 0
                ):
                    logger.info(
                        "Scheduler idle at %s; no pending bets, selections, or slips. Next run at %s UTC.",
                        cycle_started.isoformat(),
                        datetime.fromtimestamp(next_run_at, tz=timezone.utc).isoformat(),
                    )

                elif not has_actionable_matches:
                    logger.info(
                        "Scheduler waiting at %s; pending bets=%d, selections=%d, slips=%d, but no matches are due yet. Next run at %s UTC.",
                        cycle_started.isoformat(),
                        pending_bets_count,
                        pending_selections_count,
                        pending_slips_count,
                        datetime.fromtimestamp(next_run_at, tz=timezone.utc).isoformat(),
                    )

                else:
                    logger.info(
                        "Scheduler active at %s; pending bets=%d, selections=%d, slips=%d; next run at %s UTC.",
                        cycle_started.isoformat(),
                        pending_bets_count,
                        pending_selections_count,
                        pending_slips_count,
                        datetime.fromtimestamp(next_run_at, tz=timezone.utc).isoformat(),
                    )

                    try:
                        settle_stats = auto_settle_bets(session)
                        cashout_stats = auto_update_live_cashouts(session)

                        session.commit()

                        logger.info(
                            "Cycle complete at %s UTC: bets_settled=%d, selections_settled=%d, selections_voided=%d, slips_settled=%d, slips_voided=%d, cashout_bets=%d, cashout_slips=%d",
                            cycle_started.isoformat(),
                            settle_stats["bets_settled"],
                            settle_stats["selections_settled"],
                            settle_stats["selections_voided"],
                            settle_stats["slips_settled"],
                            settle_stats["slips_voided"],
                            cashout_stats["bets_updated"],
                            cashout_stats["slips_updated"],
                        )

                    except Exception as e:
                        session.rollback()
                        logger.exception("Error during scheduler cycle: %s", e)

            except Exception as e:
                logger.exception("Outer scheduler error: %s", e)
                try:
                    session.rollback()
                except Exception:
                    pass

            finally:
                session.close()

            if stop_event:
                stop_event.wait(interval_seconds)
            else:
                time.sleep(interval_seconds)

    t = threading.Thread(target=run_scheduler, daemon=daemon)
    t.start()
    return t


def assign_betslip_match_id(betslip, selections):
    """Ensure BetSlip.match_id is set from first selection if missing."""
    if not betslip.match_id and selections:
        betslip.match_id = selections[0].match_id
