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

from betting.utils import (
    to_decimal,
    evaluate_selection_win,
    calculate_live_cashout,
)


logger = logging.getLogger(__name__)


# ============================================================
# SETTINGS
# ============================================================

BATCH_SIZE = 250

_missing_match_logged = set()
_missing_cashout_logged = set()


# ============================================================
# TIME
# ============================================================

def _utcnow():
    return datetime.now(timezone.utc)


# ============================================================
# LOGGING HELPERS
# ============================================================

def _safe_add_warning(cache_set, key, message, *args):
    """
    Prevent the same warning from being logged repeatedly.
    """

    if key in cache_set:
        return

    cache_set.add(key)

    logger.warning(message, *args)

    if len(cache_set) > 5000:
        cache_set.clear()


# ============================================================
# ACTIONABLE MATCH CHECK
# ============================================================

def _has_actionable_matches(now, session=None):
    """
    Cheap existence check for actionable matches.
    """

    session = session or db.session

    return (
        session.query(Match.id)
        .filter(
            Match.status.in_(
                [
                    "FINISHED",
                    "IN_PLAY",
                    "POSTPONED",
                    "ABANDONED",
                ]
            ),
            or_(
                Match.utcdate.is_(None),
                Match.utcdate <= now,
            ),
        )
        .first()
        is not None
    )


# ============================================================
# SINGLE NORMAL BET SETTLEMENT
# ============================================================

def settle_single_bet(session, bet, match):
    """
    Settle one normal Bet.

    Returns:
        won
        lost
        pending
        None
    """

    if getattr(bet, "cashed_out", False):
        return bet.status

    if bet.status != "pending":
        return bet.status

    user = session.get(User, bet.user_id)

    if not user:
        logger.warning(
            "Bet %s has no user assigned",
            bet.id,
        )
        return None

    try:
        won = evaluate_selection_win(
            match.home_score,
            match.away_score,
            bet.selection,
        )

    except Exception as e:
        logger.exception(
            "Error evaluating Bet %s: %s",
            bet.id,
            e,
        )
        return None

    # --------------------------------------------------------
    # WON
    # --------------------------------------------------------

    if won is True:

        bet.status = "won"

        user.balance = (
            to_decimal(user.balance)
            + to_decimal(bet.potential)
        )

        session.add(
            Transaction(
                user_id=user.id,
                type="bet_win",
                amount=to_decimal(bet.potential),
                balance_after=to_decimal(user.balance),
            )
        )

    # --------------------------------------------------------
    # LOST
    # --------------------------------------------------------

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

    else:
        return "pending"

    session.add(bet)

    return bet.status


# ============================================================
# SETTLE NORMAL BETS
# ============================================================

def settle_bets_for_matches(session, finished_matches):
    """
    Settle pending normal Bet records belonging to finished
    matches.

    No FOR UPDATE is used.
    """

    settled_count = 0

    for match in finished_matches:

        if match.home_score is None:
            continue

        if match.away_score is None:
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
                .all()
            )

            if not bets:
                break

            for bet in bets:

                try:

                    result = settle_single_bet(
                        session,
                        bet,
                        match,
                    )

                    if result in ("won", "lost"):
                        settled_count += 1

                except Exception as e:

                    logger.exception(
                        "Error settling Bet %s: %s",
                        bet.id,
                        e,
                    )

            last_id = bets[-1].id

            session.flush()

    return settled_count


# ============================================================
# RESOLVE MATCH FOR SELECTION
# ============================================================

def _resolve_match_for_selection(
    sel,
    matches_map,
    bookmarks_map,
):
    """
    Resolve the Match belonging to a BetSelection.

    IMPORTANT:

    Bookmark uses match_id.

    There is NO Bookmark.id assumption.
    """

    if not sel.bookmark_id:
        return None

    bookmark = bookmarks_map.get(
        sel.bookmark_id
    )

    if bookmark:

        match_id = getattr(
            bookmark,
            "match_id",
            None,
        )

        if match_id:

            match = matches_map.get(
                match_id
            )

            if match:
                return match

    # Legacy fallback:
    # some records may store the match ID directly.
    return matches_map.get(
        sel.bookmark_id
    )


# ============================================================
# LOAD BETTING CONTEXT
# ============================================================

def _load_betting_context(
    session,
    pending_selections,
    now=None,
):
    """
    Load ONLY bookmarks and matches referenced by the supplied
    pending selections.

    No Bookmark.id is used.

    No FOR UPDATE is used.
    """

    match_ids = set()
    bookmark_ids = set()

    for sel in pending_selections:

        if not sel.bookmark_id:
            continue

        bookmark_ids.add(
            sel.bookmark_id
        )

    if not bookmark_ids:
        return {}, {}

    # --------------------------------------------------------
    # Bookmark lookup
    #
    # IMPORTANT:
    # Bookmark has match_id.
    # --------------------------------------------------------

    bookmarks = (
        session.query(Bookmark)
        .filter(
            Bookmark.match_id.in_(
                bookmark_ids
            )
        )
        .all()
    )

    bookmarks_map = {
        b.match_id: b
        for b in bookmarks
        if getattr(b, "match_id", None)
        is not None
    }

    # --------------------------------------------------------
    # Extract actual Match IDs
    # --------------------------------------------------------

    for bookmark in bookmarks:

        match_id = getattr(
            bookmark,
            "match_id",
            None,
        )

        if match_id:
            match_ids.add(match_id)

    # --------------------------------------------------------
    # Legacy fallback
    # --------------------------------------------------------

    for bookmark_id in bookmark_ids:

        if bookmark_id not in bookmarks_map:
            match_ids.add(bookmark_id)

    if not match_ids:

        return {}, bookmarks_map

    # --------------------------------------------------------
    # Load only referenced matches
    # --------------------------------------------------------

    matches = (
        session.query(Match)
        .filter(
            Match.id.in_(match_ids)
        )
        .all()
    )

    matches_map = {
        m.id: m
        for m in matches
    }

    return matches_map, bookmarks_map


# ============================================================
# SETTLE BET SELECTIONS
# ============================================================

def settle_bet_selections(
    session,
    pending_selections,
    matches_map,
    bookmarks_map,
    now,
):
    """
    Settle BetSelection records.

    FINISHED:
        evaluate selection

    POSTPONED / ABANDONED:
        void

    IN_PLAY / TIMED:
        remain pending
    """

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

        match = _resolve_match_for_selection(
            sel,
            matches_map,
            bookmarks_map,
        )

        if not match:

            _safe_add_warning(
                _missing_match_logged,
                f"sel-no-match-{sel.id}",
                "BetSelection %s has no match assigned",
                sel.id,
            )

            continue

        # ----------------------------------------------------
        # Future match
        # ----------------------------------------------------

        if (
            match.utcdate
            and match.utcdate > now
        ):
            continue

        # ----------------------------------------------------
        # VOID
        # ----------------------------------------------------

        if match.status in (
            "POSTPONED",
            "ABANDONED",
        ):

            if sel.status != "voided":

                sel.status = "voided"

                session.add(sel)

                voided += 1

                logger.info(
                    "BetSelection %s VOIDED | match=%s | status=%s",
                    sel.id,
                    match.id,
                    match.status,
                )

            continue

        # ----------------------------------------------------
        # Only finished matches settle
        # ----------------------------------------------------

        if match.status != "FINISHED":
            continue

        if match.home_score is None:
            continue

        if match.away_score is None:
            continue

        try:

            won = evaluate_selection_win(
                match.home_score,
                match.away_score,
                sel.selection,
            )

            if won is True:
                new_status = "won"

            elif won is False:
                new_status = "lost"

            else:
                new_status = "pending"

            if new_status != sel.status:

                sel.status = new_status

                session.add(sel)

                if new_status in (
                    "won",
                    "lost",
                ):

                    settled += 1

                    logger.info(
                        "BetSelection %s %s | "
                        "selection=%s | "
                        "match=%s | "
                        "score=%s-%s",
                        sel.id,
                        new_status.upper(),
                        sel.selection,
                        match.id,
                        match.home_score,
                        match.away_score,
                    )

        except Exception as e:

            logger.exception(
                "Error settling BetSelection %s: %s",
                sel.id,
                e,
            )

    return settled, voided


# ============================================================
# SETTLE BETSLIPS
# ============================================================

def settle_betslips(
    session,
    pending_slips,
):
    """
    Settle completed BetSlips.

    Rules:

        pending  -> remain pending

        voided   -> voided + stake refunded

        lost     -> lost

        all won  -> won + potential paid
    """

    settled = 0
    voided = 0

    for slip in pending_slips:

        try:

            if slip.status != "pending":
                continue

            selections = list(
                slip.selections
            )

            if not selections:
                continue

            # ------------------------------------------------
            # STILL WAITING
            # ------------------------------------------------

            if any(
                s.status == "pending"
                for s in selections
            ):
                continue

            user = session.get(
                User,
                slip.user_id,
            )

            if not user:

                logger.warning(
                    "BetSlip %s has no user assigned",
                    slip.id,
                )

                continue

            # ------------------------------------------------
            # VOID
            # ------------------------------------------------

            if any(
                s.status == "voided"
                for s in selections
            ):

                slip.status = "voided"

                stake = to_decimal(
                    getattr(
                        slip,
                        "stake",
                        Decimal("0.00"),
                    )
                )

                user.balance = (
                    to_decimal(user.balance)
                    + stake
                )

                session.add(
                    Transaction(
                        user_id=user.id,
                        type="bet_voided",
                        amount=stake,
                        balance_after=to_decimal(
                            user.balance
                        ),
                    )
                )

                session.add(slip)

                voided += 1

                logger.info(
                    "BetSlip %s VOIDED | refund=%s",
                    slip.id,
                    stake,
                )

                continue

            # ------------------------------------------------
            # LOST
            # ------------------------------------------------

            if any(
                s.status == "lost"
                for s in selections
            ):

                slip.status = "lost"

                session.add(
                    Transaction(
                        user_id=user.id,
                        type="bet_loss",
                        amount=Decimal("0.00"),
                        balance_after=to_decimal(
                            user.balance
                        ),
                    )
                )

                logger.info(
                    "BetSlip %s LOST",
                    slip.id,
                )

            # ------------------------------------------------
            # ALL WON
            # ------------------------------------------------

            else:

                slip.status = "won"

                potential = to_decimal(
                    slip.potential
                )

                user.balance = (
                    to_decimal(user.balance)
                    + potential
                )

                session.add(
                    Transaction(
                        user_id=user.id,
                        type="bet_win",
                        amount=potential,
                        balance_after=to_decimal(
                            user.balance
                        ),
                    )
                )

                logger.info(
                    "BetSlip %s WON | payout=%s",
                    slip.id,
                    potential,
                )

            session.add(slip)

            settled += 1

        except Exception as e:

            logger.exception(
                "Error settling BetSlip %s: %s",
                slip.id,
                e,
            )

    return settled, voided


# ============================================================
# NORMAL BET CASHOUT
# ============================================================

def update_bet_cashout(
    session,
    bet,
    matches_map,
    bookmarks_map,
    now,
):
    """
    Update current cashout for a normal Bet.
    """

    try:

        if bet.status != "pending":
            return False

        if getattr(
            bet,
            "cashed_out",
            False,
        ):
            return False

        match = matches_map.get(
            bet.match_id
        )

        bookmark = bookmarks_map.get(
            bet.match_id
        )

        if not match:

            _safe_add_warning(
                _missing_cashout_logged,
                f"bet-no-match-cashout-{bet.id}",
                "Bet %s has no match assigned for cashout",
                bet.id,
            )

            return False

        if (
            match.utcdate
            and match.utcdate > now
        ):
            return False

        if match.status != "IN_PLAY":
            return False

        bet.current_cashout = (
            calculate_live_cashout(
                bet,
                match,
                bookmark,
            )
        )

        session.add(bet)

        return True

    except Exception as e:

        logger.exception(
            "Error updating cashout for Bet %s: %s",
            bet.id,
            e,
        )

        return False


# ============================================================
# MARKET FAMILY
# ============================================================

def _selection_market_family(selection):

    sel = (
        selection or ""
    ).lower()

    if sel in (
        "home_odds",
        "home",
        "draw_odds",
        "draw",
        "away_odds",
        "away",
    ):
        return "1x2"

    if (
        sel.startswith("over")
        or sel.startswith("under")
    ):
        return "ou"

    if sel in (
        "gg_odds",
        "btts",
        "ng_odds",
        "no_btts",
    ):
        return "btts"

    return "other"


# ============================================================
# LEG PROBABILITY
# ============================================================

def _leg_probability(
    sel,
    match,
    bookmark,
):
    """
    Calculate current probability of one accumulator leg.

    WON:
        1.00

    LOST:
        0.00

    FINISHED:
        evaluate final score

    IN_PLAY:
        live probability

    TIMED / SCHEDULED:
        pre-match probability
    """

    selection = (
        getattr(
            sel,
            "selection",
            "",
        )
        or ""
    ).lower()

    status = (
        getattr(
            match,
            "status",
            "",
        )
        or ""
    ).lower()

    # ========================================================
    # DATABASE SELECTION STATUS
    # ========================================================

    if sel.status == "won":
        return Decimal("1.00")

    if sel.status in (
        "lost",
        "voided",
    ):
        return Decimal("0.00")

    # ========================================================
    # FINISHED MATCH
    # ========================================================

    if status == "finished":

        if (
            match.home_score is None
            or match.away_score is None
        ):
            return Decimal("0.01")

        result = evaluate_selection_win(
            match.home_score,
            match.away_score,
            selection,
        )

        if result is True:
            return Decimal("1.00")

        if result is False:
            return Decimal("0.00")

        return Decimal("0.01")

    # ========================================================
    # PRE-MATCH
    # ========================================================

    if status in (
        "timed",
        "scheduled",
        "upcoming",
        "pending",
        "not_started",
        "",
    ):

        # ----------------------------------------------------
        # Prefer model probability from Bookmark
        # ----------------------------------------------------

        if bookmark:

            try:

                value = None

                if selection in (
                    "home_odds",
                    "home",
                ):

                    value = getattr(
                        bookmark,
                        "p_home",
                        None,
                    )

                elif selection in (
                    "draw_odds",
                    "draw",
                ):

                    value = getattr(
                        bookmark,
                        "p_draw",
                        None,
                    )

                elif selection in (
                    "away_odds",
                    "away",
                ):

                    value = getattr(
                        bookmark,
                        "p_away",
                        None,
                    )

                if value is not None:

                    value = to_decimal(
                        value,
                        quantize=False,
                    )

                    if value > 1:
                        value /= Decimal("100")

                    return max(
                        Decimal("0.01"),
                        min(
                            Decimal("0.99"),
                            value,
                        ),
                    )

            except Exception:
                pass

        # ----------------------------------------------------
        # Odds fallback
        # ----------------------------------------------------

        try:

            odds = to_decimal(
                getattr(
                    sel,
                    "odds",
                    None,
                ),
                quantize=False,
            )

            if odds > 0:

                probability = (
                    Decimal("1")
                    / odds
                )

                return max(
                    Decimal("0.01"),
                    min(
                        Decimal("0.99"),
                        probability,
                    ),
                )

        except Exception:
            pass

        return Decimal("0.50")

    # ========================================================
    # LIVE MATCH
    # ========================================================

    if status == "in_play":

        class TempBet:
            pass

        temp = TempBet()

        temp.status = "pending"
        temp.cashed_out = False
        temp.selection = sel.selection
        temp.odds = sel.odds
        temp.potential = Decimal("1.00")
        temp.stake = Decimal("1.00")

        try:

            live_value = calculate_live_cashout(
                temp,
                match,
                bookmark,
            )

            probability = to_decimal(
                live_value,
                quantize=False,
            )

            # calculate_live_cashout applies approximately
            # 8% margin. Remove that effect so the value can
            # be used as an approximate probability.
            probability /= Decimal("0.92")

            return max(
                Decimal("0.01"),
                min(
                    Decimal("0.99"),
                    probability,
                ),
            )

        except Exception:

            return Decimal("0.01")

    return Decimal("0.50")


# ============================================================
# CORRELATION
# ============================================================

def _correlation_factor(legs):
    """
    Reduce cashout slightly when selections are correlated.
    """

    factor = Decimal("1.00")

    match_counts = {}
    family_counts = {}

    for leg in legs:

        match_id = leg["match_id"]
        family = leg["family"]

        match_counts[match_id] = (
            match_counts.get(match_id, 0)
            + 1
        )

        family_counts[family] = (
            family_counts.get(family, 0)
            + 1
        )

    # Multiple markets on same match
    for count in match_counts.values():

        if count > 1:

            factor *= (
                Decimal("0.88")
                ** (count - 1)
            )

    # Same market family
    for count in family_counts.values():

        if count > 1:

            factor *= (
                Decimal("0.95")
                ** (count - 1)
            )

    if len(legs) >= 4:
        factor *= Decimal("0.98")

    return max(
        Decimal("0.50"),
        min(
            Decimal("1.00"),
            factor,
        ),
    )


# ============================================================
# BETSLIP CASHOUT
# ============================================================

def update_betslip_cashout(
    session,
    slip,
    matches_map,
    bookmarks_map,
    now,
):
    """
    Dynamic accumulator cashout.

    Examples:

        1 leg:
            probability(A)

        2 legs:
            probability(A) * probability(B)

        4 legs:
            probability(A)
            * probability(B)
            * probability(C)
            * probability(D)

    A leg already WON contributes 1.00.

    A leg that is LOST contributes 0.00.

    An unstarted leg uses its current pre-match probability.

    A live leg uses its current live probability.
    """

    try:

        if slip.status != "pending":
            return False

        potential = to_decimal(
            getattr(
                slip,
                "potential",
                Decimal("0.00"),
            )
        )

        stake = to_decimal(
            getattr(
                slip,
                "stake",
                Decimal("0.00"),
            )
        )

        if potential <= 0:

            slip.current_cashout = (
                Decimal("0.00")
            )

            session.add(slip)

            return False

        selections = list(
            slip.selections
        )

        if not selections:

            slip.current_cashout = (
                Decimal("0.00")
            )

            session.add(slip)

            return False

        combined_probability = (
            Decimal("1.00")
        )

        won_legs = 0
        live_legs = 0
        future_legs = 0
        unresolved_legs = 0

        # ====================================================
        # PROCESS EVERY LEG
        # ====================================================

        for sel in selections:

            # ------------------------------------------------
            # ALREADY WON
            # ------------------------------------------------

            if sel.status == "won":

                won_legs += 1

                # A confirmed winner has probability 1.
                continue

            # ------------------------------------------------
            # LOST / VOIDED
            # ------------------------------------------------

            if sel.status in (
                "lost",
                "voided",
            ):

                slip.current_cashout = (
                    Decimal("0.00")
                )

                session.add(slip)

                logger.info(
                    "BetSlip %s cashout=0 | "
                    "selection=%s status=%s",
                    slip.id,
                    sel.id,
                    sel.status,
                )

                return True

            # ------------------------------------------------
            # RESOLVE BOOKMARK
            # ------------------------------------------------

            bookmark = None

            if sel.bookmark_id:

                bookmark = bookmarks_map.get(
                    sel.bookmark_id
                )

            match = None

            if bookmark:

                match_id = getattr(
                    bookmark,
                    "match_id",
                    None,
                )

                if match_id:

                    match = matches_map.get(
                        match_id
                    )

            # Legacy fallback
            if (
                not match
                and sel.bookmark_id
            ):

                match = matches_map.get(
                    sel.bookmark_id
                )

            if not match:

                _safe_add_warning(
                    _missing_cashout_logged,
                    f"slip-sel-no-match-cashout-{sel.id}",
                    "BetSelection %s has no match for cashout",
                    sel.id,
                )

                # Unknown leg is treated conservatively.
                combined_probability *= (
                    Decimal("0.01")
                )

                unresolved_legs += 1

                continue

            # ------------------------------------------------
            # FUTURE MATCH
            # ------------------------------------------------

            if (
                match.utcdate
                and match.utcdate > now
            ):

                future_legs += 1

            # ------------------------------------------------
            # FINISHED MATCH
            # ------------------------------------------------

            if match.status == "FINISHED":

                if (
                    match.home_score is None
                    or match.away_score is None
                ):

                    combined_probability *= (
                        Decimal("0.01")
                    )

                    unresolved_legs += 1

                    continue

                result = evaluate_selection_win(
                    match.home_score,
                    match.away_score,
                    sel.selection,
                )

                # ------------------------------------------------
                # Finished and WON
                # ------------------------------------------------

                if result is True:

                    sel.status = "won"

                    session.add(sel)

                    won_legs += 1

                    continue

                # ------------------------------------------------
                # Finished and LOST
                # ------------------------------------------------

                if result is False:

                    sel.status = "lost"

                    session.add(sel)

                    slip.current_cashout = (
                        Decimal("0.00")
                    )

                    logger.info(
                        "BetSlip %s cashout=0 | "
                        "selection=%s lost | "
                        "match=%s | score=%s-%s",
                        slip.id,
                        sel.id,
                        match.id,
                        match.home_score,
                        match.away_score,
                    )

                    return True

            # ------------------------------------------------
            # LIVE
            # ------------------------------------------------

            if match.status == "IN_PLAY":

                live_legs += 1

            # ------------------------------------------------
            # GET CURRENT PROBABILITY
            # ------------------------------------------------

            probability = _leg_probability(
                sel,
                match,
                bookmark,
            )

            probability = max(
                Decimal("0.01"),
                min(
                    Decimal("0.99"),
                    probability,
                ),
            )

            combined_probability *= (
                probability
            )

            unresolved_legs += 1

            logger.debug(
                "Slip %s | selection=%s | "
                "match=%s | status=%s | probability=%s",
                slip.id,
                sel.id,
                match.id,
                match.status,
                probability,
            )

        # ====================================================
        # ALL LEGS WON
        # ====================================================

        if unresolved_legs == 0:

            slip.current_cashout = (
                potential
            )

            session.add(slip)

            logger.info(
                "BetSlip %s fully won | cashout=%s",
                slip.id,
                potential,
            )

            return True

        # ====================================================
        # CALCULATE FAIR VALUE
        # ====================================================

        cashout = (
            potential
            * combined_probability
        )

        # ====================================================
        # CORRELATION
        # ====================================================

        legs_for_correlation = []

        for sel in selections:

            if sel.status in (
                "lost",
                "voided",
            ):
                continue

            bookmark = (
                bookmarks_map.get(
                    sel.bookmark_id
                )
                if sel.bookmark_id
                else None
            )

            match = None

            if bookmark:

                match = matches_map.get(
                    getattr(
                        bookmark,
                        "match_id",
                        None,
                    )
                )

            if not match and sel.bookmark_id:

                match = matches_map.get(
                    sel.bookmark_id
                )

            if not match:
                continue

            legs_for_correlation.append(
                {
                    "sel_id": sel.id,
                    "match_id": match.id,
                    "family": _selection_market_family(
                        sel.selection
                    ),
                    "prob": Decimal("1.00"),
                }
            )

        correlation = _correlation_factor(
            legs_for_correlation
        )

        cashout *= correlation

        # ====================================================
        # BOOKMAKER MARGIN
        # ====================================================

        cashout *= Decimal("0.93")

        # ====================================================
        # MAXIMUM CASHOUT
        # ====================================================

        max_cashout = (
            potential
            * Decimal("0.98")
        )

        cashout = min(
            cashout,
            max_cashout,
        )

        # ====================================================
        # MINIMUM FLOOR
        #
        # Important:
        # Do not force a huge cashout when the bet is nearly
        # dead. Only keep a small minimum based on stake.
        # ====================================================

        if stake > 0:

            minimum_cashout = (
                stake
                * Decimal("0.01")
            )

            cashout = max(
                cashout,
                minimum_cashout,
            )

        # ====================================================
        # FINAL ROUNDING
        # ====================================================

        slip.current_cashout = (
            cashout.quantize(
                Decimal("0.01"),
                rounding=ROUND_DOWN,
            )
        )

        session.add(slip)

        logger.info(
            "BetSlip %s cashout updated | "
            "won=%d | unresolved=%d | "
            "live=%d | future=%d | "
            "combined_probability=%s | "
            "cashout=%s",
            slip.id,
            won_legs,
            unresolved_legs,
            live_legs,
            future_legs,
            combined_probability,
            slip.current_cashout,
        )

        return True

    except Exception as e:

        logger.exception(
            "Error updating BetSlip %s cashout: %s",
            slip.id,
            e,
        )

        return False


# ============================================================
# AUTO SETTLEMENT
# ============================================================

def auto_settle_bets(session=None):
    """
    Efficient pending-only settlement.

    Does NOT scan every finished Match.

    Process:

        1. Find match IDs from pending normal Bets
        2. Load only finished referenced matches
        3. Settle normal Bets
        4. Load pending BetSelections in batches
        5. Load only referenced Bookmarks/Matches
        6. Settle selections
        7. Load pending BetSlips
        8. Settle completed slips

    No FOR UPDATE is used.
    """

    session = session or db.session

    now = _utcnow()

    # ========================================================
    # 1. NORMAL BETS
    # ========================================================

    pending_bet_match_ids = [
        row[0]
        for row in (
            session.query(Bet.match_id)
            .filter(
                Bet.status == "pending",
                Bet.match_id.isnot(None),
            )
            .distinct()
            .all()
        )
    ]

    finished_matches = []

    if pending_bet_match_ids:

        finished_matches = (
            session.query(Match)
            .filter(
                Match.id.in_(
                    pending_bet_match_ids
                ),
                Match.status == "FINISHED",
                or_(
                    Match.utcdate.is_(None),
                    Match.utcdate <= now,
                ),
            )
            .order_by(Match.id)
            .all()
        )

    settled_bets = (
        settle_bets_for_matches(
            session,
            finished_matches,
        )
    )

    # ========================================================
    # 2. PENDING SELECTIONS
    # ========================================================

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
            .all()
        )

        if not pending_selections:
            break

        matches_map, bookmarks_map = (
            _load_betting_context(
                session,
                pending_selections,
                now,
            )
        )

        settled, voided = (
            settle_bet_selections(
                session,
                pending_selections,
                matches_map,
                bookmarks_map,
                now,
            )
        )

        total_sel_settled += settled
        total_sel_voided += voided

        last_id = (
            pending_selections[-1].id
        )

        session.flush()

    # ========================================================
    # 3. BETSLIPS
    # ========================================================

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
            .all()
        )

        if not pending_slips:
            break

        settled, voided = (
            settle_betslips(
                session,
                pending_slips,
            )
        )

        total_slip_settled += settled
        total_slip_voided += voided

        last_id = (
            pending_slips[-1].id
        )

        session.flush()

    return {
        "bets_settled": settled_bets,
        "selections_settled": total_sel_settled,
        "selections_voided": total_sel_voided,
        "slips_settled": total_slip_settled,
        "slips_voided": total_slip_voided,
    }


# ============================================================
# AUTO LIVE CASHOUT
# ============================================================

def auto_update_live_cashouts(session=None):
    """
    Update cashout for:

        - normal pending Bets
        - pending BetSlips

    IMPORTANT:

    BetSlip cashout is NOT dependent on there being a normal
    Bet record.

    This fixes accumulator-only cashout updates.
    """

    session = session or db.session

    now = _utcnow()

    # ========================================================
    # 1. FIND PENDING NORMAL BET MATCH IDS
    # ========================================================

    normal_bet_match_ids = {
        row[0]
        for row in (
            session.query(Bet.match_id)
            .filter(
                Bet.status == "pending",
                Bet.match_id.isnot(None),
            )
            .distinct()
            .all()
        )
    }

    # ========================================================
    # 2. FIND PENDING BETSLIP SELECTIONS
    # ========================================================

    pending_slip_selections = (
        session.query(BetSelection)
        .join(
            BetSlip,
            BetSlip.id
            == BetSelection.betslip_id,
        )
        .filter(
            BetSlip.status == "pending",
            BetSelection.status == "pending",
        )
        .all()
    )

    slip_bookmark_ids = {
        sel.bookmark_id
        for sel in pending_slip_selections
        if sel.bookmark_id
    }

    # ========================================================
    # 3. LOAD BOOKMARKS FOR BETSLIPS
    # ========================================================

    slip_bookmarks = []

    if slip_bookmark_ids:

        slip_bookmarks = (
            session.query(Bookmark)
            .filter(
                Bookmark.match_id.in_(
                    slip_bookmark_ids
                )
            )
            .all()
        )

    slip_bookmarks_map = {
        b.match_id: b
        for b in slip_bookmarks
        if getattr(b, "match_id", None)
        is not None
    }

    # ========================================================
    # 4. GET MATCH IDS FROM BETSLIP BOOKMARKS
    # ========================================================

    slip_match_ids = {
        b.match_id
        for b in slip_bookmarks
        if getattr(b, "match_id", None)
    }

    # Legacy fallback
    for bookmark_id in slip_bookmark_ids:

        if bookmark_id not in slip_bookmarks_map:

            slip_match_ids.add(
                bookmark_id
            )

    # ========================================================
    # 5. COMBINE ALL MATCH IDS
    # ========================================================

    all_match_ids = (
        normal_bet_match_ids
        | slip_match_ids
    )

    if not all_match_ids:

        return {
            "bets_updated": 0,
            "slips_updated": 0,
        }

    # ========================================================
    # 6. LOAD ONLY REQUIRED MATCHES
    #
    # Include both IN_PLAY and TIMED/SCHEDULED because
    # accumulator cashout needs the unstarted leg's probability.
    # ========================================================

    relevant_matches = (
        session.query(Match)
        .filter(
            Match.id.in_(
                list(all_match_ids)
            ),
            or_(
                Match.status.in_(
                    [
                        "IN_PLAY",
                        "TIMED",
                        "SCHEDULED",
                        "UPCOMING",
                        "PENDING",
                        "FINISHED",
                    ]
                ),
                Match.status.is_(None),
            ),
            or_(
                Match.utcdate.is_(None),
                Match.utcdate <= now,
            ),
        )
        .all()
    )

    matches_map = {
        m.id: m
        for m in relevant_matches
    }

    # ========================================================
    # 7. LOAD BOOKMARKS FOR NORMAL BETS
    # ========================================================

    normal_bet_bookmark_ids = {
        match_id
        for match_id in normal_bet_match_ids
    }

    normal_bookmarks = []

    if normal_bet_bookmark_ids:

        normal_bookmarks = (
            session.query(Bookmark)
            .filter(
                Bookmark.match_id.in_(
                    normal_bet_bookmark_ids
                )
            )
            .all()
        )

    bookmarks_map = {
        b.match_id: b
        for b in (
            slip_bookmarks
            + normal_bookmarks
        )
        if getattr(b, "match_id", None)
        is not None
    }

    total_bets = 0
    total_slips = 0

    # ========================================================
    # 8. NORMAL BET CASHOUT
    # ========================================================

    last_id = 0

    while True:

        bets = (
            session.query(Bet)
            .enable_eagerloads(False)
            .filter(
                Bet.status == "pending",
                Bet.id > last_id,
                Bet.match_id.in_(
                    list(normal_bet_match_ids)
                ),
            )
            .order_by(Bet.id)
            .limit(BATCH_SIZE)
            .all()
        )

        if not bets:
            break

        for bet in bets:

            if update_bet_cashout(
                session,
                bet,
                matches_map,
                bookmarks_map,
                now,
            ):

                total_bets += 1

        last_id = bets[-1].id

        session.flush()

    # ========================================================
    # 9. BETSLIP CASHOUT
    #
    # IMPORTANT:
    #
    # Every pending slip is evaluated, even if there are no
    # normal Bet rows.
    # ========================================================

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
            .all()
        )

        if not slips:
            break

        for slip in slips:

            if update_betslip_cashout(
                session,
                slip,
                matches_map,
                bookmarks_map,
                now,
            ):

                total_slips += 1

        last_id = slips[-1].id

        session.flush()

    return {
        "bets_updated": total_bets,
        "slips_updated": total_slips,
    }


# ============================================================
# SCHEDULER
# ============================================================

def start_scheduler(
    app,
    interval_seconds=60,
    daemon=True,
    stop_event=None,
):
    """
    Start background betting scheduler.

    Every cycle:

        1. Settle pending normal Bets
        2. Settle pending selections
        3. Settle completed BetSlips
        4. Update normal Bet cashouts
        5. Update accumulator cashouts
        6. Commit

    PostgreSQL:

        No problematic FOR UPDATE queries are used.
    """

    def run_scheduler():

        _missing_match_logged.clear()
        _missing_cashout_logged.clear()

        SessionLocal = None

        # ====================================================
        # CREATE SESSION FACTORY
        # ====================================================

        with app.app_context():

            SessionLocal = sessionmaker(
                bind=db.engine,
                autoflush=False,
                expire_on_commit=False,
            )

        logger.info(
            "Betting scheduler started | interval=%ss",
            interval_seconds,
        )

        # ====================================================
        # MAIN LOOP
        # ====================================================

        while True:

            if (
                stop_event is not None
                and stop_event.is_set()
            ):

                logger.info(
                    "Scheduler stopped."
                )

                break

            cycle_started = _utcnow()

            next_run_at = (
                cycle_started.timestamp()
                + interval_seconds
            )

            session = SessionLocal()

            try:

                # ============================================
                # COUNTS
                # ============================================

                pending_bets_count = (
                    session.query(Bet)
                    .filter(
                        Bet.status == "pending"
                    )
                    .count()
                )

                pending_selections_count = (
                    session.query(BetSelection)
                    .filter(
                        BetSelection.status
                        == "pending"
                    )
                    .count()
                )

                pending_slips_count = (
                    session.query(BetSlip)
                    .filter(
                        BetSlip.status == "pending"
                    )
                    .count()
                )

                # ============================================
                # NOTHING PENDING
                # ============================================

                if (
                    pending_bets_count == 0
                    and pending_selections_count == 0
                    and pending_slips_count == 0
                ):

                    logger.info(
                        "Scheduler idle at %s; "
                        "no pending bets, selections, or slips. "
                        "Next run at %s UTC.",
                        cycle_started.isoformat(),
                        datetime.fromtimestamp(
                            next_run_at,
                            tz=timezone.utc,
                        ).isoformat(),
                    )

                else:

                    logger.info(
                        "Scheduler active at %s; "
                        "pending bets=%d, "
                        "selections=%d, "
                        "slips=%d; "
                        "next run at %s UTC.",
                        cycle_started.isoformat(),
                        pending_bets_count,
                        pending_selections_count,
                        pending_slips_count,
                        datetime.fromtimestamp(
                            next_run_at,
                            tz=timezone.utc,
                        ).isoformat(),
                    )

                    try:

                        # ====================================
                        # SETTLEMENT
                        # ====================================

                        settle_stats = (
                            auto_settle_bets(
                                session
                            )
                        )

                        # ====================================
                        # CASHOUT
                        # ====================================

                        cashout_stats = (
                            auto_update_live_cashouts(
                                session
                            )
                        )

                        # ====================================
                        # COMMIT
                        # ====================================

                        session.commit()

                        logger.info(
                            "Cycle complete at %s UTC: "
                            "bets_settled=%d, "
                            "selections_settled=%d, "
                            "selections_voided=%d, "
                            "slips_settled=%d, "
                            "slips_voided=%d, "
                            "cashout_bets=%d, "
                            "cashout_slips=%d",
                            cycle_started.isoformat(),
                            settle_stats[
                                "bets_settled"
                            ],
                            settle_stats[
                                "selections_settled"
                            ],
                            settle_stats[
                                "selections_voided"
                            ],
                            settle_stats[
                                "slips_settled"
                            ],
                            settle_stats[
                                "slips_voided"
                            ],
                            cashout_stats[
                                "bets_updated"
                            ],
                            cashout_stats[
                                "slips_updated"
                            ],
                        )

                    except Exception as e:

                        session.rollback()

                        logger.exception(
                            "Error during scheduler cycle: %s",
                            e,
                        )

            except Exception as e:

                logger.exception(
                    "Outer scheduler error: %s",
                    e,
                )

                try:
                    session.rollback()
                except Exception:
                    pass

            finally:

                session.close()

            # =================================================
            # WAIT
            # =================================================

            if stop_event is not None:

                stop_event.wait(
                    interval_seconds
                )

            else:

                time.sleep(
                    interval_seconds
                )

    # ========================================================
    # START THREAD
    # ========================================================

    t = threading.Thread(
        target=run_scheduler,
        daemon=daemon,
        name="betting-scheduler",
    )

    t.start()

    return t


# ============================================================
# ASSIGN BETSLIP MATCH ID
# ============================================================

def assign_betslip_match_id(
    betslip,
    selections,
):
    """
    Ensure BetSlip.match_id is set from the first selection
    when missing.
    """

    if (
        not getattr(
            betslip,
            "match_id",
            None,
        )
        and selections
    ):

        betslip.match_id = (
            getattr(
                selections[0],
                "match_id",
                None,
            )
        )
