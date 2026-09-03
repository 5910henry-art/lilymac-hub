# scheduler.py

import logging
import threading
import time
from datetime import datetime, timezone, timedelta
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
    MpesaWithdrawal,
    Transaction,
    HouseWallet,
    HouseTransaction,
)

from betting.utils import (
    to_decimal,
    evaluate_selection_win,
    calculate_live_cashout,
    implied_probability_from_odds,
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


def _debit_house(session, amount, reference=None, description=None, transaction_type="bet_payout"):
    """
    Debit the house wallet for a normal football payout/refund.

    Uses the existing scheduler database session so the house
    debit remains part of the same settlement transaction.
    """
    amount = to_decimal(amount)

    if amount is None:
        raise ValueError("invalid house debit amount")

    amount = Decimal(str(amount)).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )

    if amount <= Decimal("0.00"):
        raise ValueError("invalid house debit amount")

    house = (
        session.query(HouseWallet)
        .with_for_update()
        .filter(HouseWallet.id == 1)
        .first()
    )

    if not house:
        raise RuntimeError(
            "House wallet is not initialized"
        )

    current_balance = Decimal(
        str(to_decimal(house.balance))
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )

    if current_balance < amount:
        raise RuntimeError(
            "house wallet has insufficient funds"
        )

    house.balance = (
        current_balance - amount
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )

    session.add(
        HouseTransaction(
            type=transaction_type,
            amount=amount,
            balance_after=house.balance,
            reference=(
                str(reference)
                if reference is not None
                else None
            ),
            description=(
                description
                or "Normal football bet payout"
            ),
        )
    )

    return house


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

        _debit_house(
            session,
            bet.potential,
            reference=f"bet:{bet.id}",
            description="Normal football single bet payout",
        )

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

                    raise

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

                _debit_house(
                    session,
                    stake,
                    reference=f"betslip:{slip.id}",
                    description="Normal football accumulator stake refund",
                    transaction_type="bet_refund",
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

                _debit_house(
                    session,
                    potential,
                    reference=f"betslip:{slip.id}",
                    description="Normal football accumulator payout",
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
            raise
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

    IMPORTANT:
    - WON      -> 1.00
    - LOST     -> 0.00
    - VOIDED   -> 0.00
    - FINISHED -> evaluate final result
    - IN_PLAY  -> live probability
    - PREMATCH -> pre-match probability

    A selection that is merely losing while a match is still
    in play is NOT considered lost.
    """

    selection = (
        getattr(
            sel,
            "selection",
            "",
        )
        or ""
    ).lower()

    selection_status = (
        getattr(
            sel,
            "status",
            "",
        )
        or ""
    ).lower()

    match_status = (
        getattr(
            match,
            "status",
            "",
        )
        or ""
    ).lower()

    home = int(
        getattr(
            match,
            "home_score",
            0,
        )
        or 0
    )

    away = int(
        getattr(
            match,
            "away_score",
            0,
        )
        or 0
    )

    # ========================================================
    # DATABASE SELECTION STATUS
    # ========================================================

    if selection_status == "won":
        return Decimal("1.00")

    if selection_status in (
        "lost",
        "voided",
    ):
        return Decimal("0.00")

    # ========================================================
    # FINISHED MATCH
    # ========================================================

    if match_status == "finished":

        result = evaluate_selection_win(
            home,
            away,
            selection,
        )

        if result is True:

            sel.status = "won"

            return Decimal("1.00")

        if result is False:

            sel.status = "lost"

            return Decimal("0.00")

        # Unknown market/result should NOT be given
        # a positive cashout probability.
        return Decimal("0.00")

    # ========================================================
    # PRE-MATCH
    # ========================================================

    if match_status in (
        "timed",
        "scheduled",
        "upcoming",
        "pending",
        "not_started",
        "",
    ):

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

                probability = normalize_probability(
                    value
                )

                if probability is not None:

                    return max(
                        Decimal("0.01"),
                        min(
                            Decimal("0.99"),
                            probability,
                        ),
                    )

            except Exception:
                pass

        # Odds fallback
        odds = getattr(
            sel,
            "odds",
            None,
        )

        if odds is None and bookmark:

            try:

                if selection in (
                    "home_odds",
                    "home",
                ):
                    odds = bookmark.home_odds

                elif selection in (
                    "draw_odds",
                    "draw",
                ):
                    odds = bookmark.draw_odds

                elif selection in (
                    "away_odds",
                    "away",
                ):
                    odds = bookmark.away_odds

                elif selection == "over05":
                    odds = bookmark.over05

                elif selection == "under05":
                    odds = bookmark.under05

                elif selection == "over15":
                    odds = bookmark.over15

                elif selection == "under15":
                    odds = bookmark.under15

                elif selection == "over25":
                    odds = bookmark.over25

                elif selection == "under25":
                    odds = bookmark.under25

                elif selection == "over35":
                    odds = bookmark.over35

                elif selection == "under35":
                    odds = bookmark.under35

                elif selection in (
                    "gg_odds",
                    "btts",
                ):
                    odds = bookmark.gg_odds

                elif selection in (
                    "ng_odds",
                    "no_btts",
                ):
                    odds = bookmark.ng_odds

            except Exception:
                pass

        probability = implied_probability_from_odds(
            odds
        )

        if probability is None:
            probability = Decimal("0.50")

        return max(
            Decimal("0.01"),
            min(
                Decimal("0.99"),
                probability,
            ),
        )

    # ========================================================
    # LIVE MATCH
    # ========================================================

    if match_status == "in_play":

        # ----------------------------------------------------
        # 1X2
        # ----------------------------------------------------

        if selection in (
            "home_odds",
            "home",
            "draw_odds",
            "draw",
            "away_odds",
            "away",
        ):

            diff = home - away

            # HOME WIN
            if selection in (
                "home_odds",
                "home",
            ):

                if diff > 0:

                    probability = Decimal("0.60")

                    if diff >= 2:
                        probability = Decimal("0.85")

                    if _match_minute(match) >= 75:
                        probability += Decimal("0.08")

                elif diff < 0:

                    probability = Decimal("0.20")

                    if diff <= -2:
                        probability = Decimal("0.05")

                    if _match_minute(match) >= 75:
                        probability *= Decimal("0.65")

                else:

                    probability = Decimal("0.35")

            # DRAW
            elif selection in (
                "draw_odds",
                "draw",
            ):

                if diff == 0:

                    probability = Decimal("0.35")

                    if _match_minute(match) >= 75:
                        probability = Decimal("0.55")

                else:

                    probability = Decimal("0.15")

                    if _match_minute(match) >= 75:
                        probability = Decimal("0.08")

            # AWAY WIN
            else:

                if diff < 0:

                    probability = Decimal("0.60")

                    if diff <= -2:
                        probability = Decimal("0.85")

                    if _match_minute(match) >= 75:
                        probability += Decimal("0.08")

                elif diff > 0:

                    probability = Decimal("0.20")

                    if diff >= 2:
                        probability = Decimal("0.05")

                    if _match_minute(match) >= 75:
                        probability *= Decimal("0.65")

                else:

                    probability = Decimal("0.35")

            return max(
                Decimal("0.01"),
                min(
                    Decimal("0.99"),
                    probability,
                ),
            )

        # ----------------------------------------------------
        # OVER / UNDER
        # ----------------------------------------------------

        if (
            selection.startswith("over")
            or selection.startswith("under")
        ):

            threshold = parse_over_under_threshold(
                selection
            )

            if threshold is None:
                return Decimal("0.00")

            total = home + away
            minute = _match_minute(match)

            # OVER
            if selection.startswith("over"):

                if total > threshold:
                    return Decimal("1.00")

                goals_needed = (
                    Decimal(str(threshold))
                    - Decimal(str(total))
                )

                if goals_needed <= 1:

                    if minute >= 75:
                        return Decimal("0.30")

                    if minute >= 60:
                        return Decimal("0.45")

                    return Decimal("0.65")

                if goals_needed <= 2:

                    if minute >= 75:
                        return Decimal("0.08")

                    if minute >= 60:
                        return Decimal("0.20")

                    return Decimal("0.40")

                if minute >= 75:
                    return Decimal("0.02")

                return Decimal("0.15")

            # UNDER
            else:

                # Under has definitively lost if the total
                # has reached/passed the line.
                if Decimal(str(total)) >= Decimal(
                    str(threshold)
                ):
                    return Decimal("0.00")

                remaining = (
                    Decimal(str(threshold))
                    - Decimal(str(total))
                )

                if minute >= 75:
                    return Decimal("0.85")

                if minute >= 60:
                    return Decimal("0.70")

                if remaining >= 2:
                    return Decimal("0.65")

                return Decimal("0.45")

        # ----------------------------------------------------
        # BTTS
        # ----------------------------------------------------

        if selection in (
            "gg_odds",
            "btts",
        ):

            if home > 0 and away > 0:
                return Decimal("1.00")

            minute = _match_minute(match)

            if minute >= 75:
                return Decimal("0.20")

            if minute >= 60:
                return Decimal("0.35")

            return Decimal("0.55")

        # ----------------------------------------------------
        # NO BTTS
        # ----------------------------------------------------

        if selection in (
            "ng_odds",
            "no_btts",
        ):

            if home > 0 and away > 0:
                return Decimal("0.00")

            minute = _match_minute(match)

            if minute >= 75:
                return Decimal("0.85")

            if minute >= 60:
                return Decimal("0.70")

            return Decimal("0.55")

        # Unknown live market
        return Decimal("0.00")

    # ========================================================
    # UNKNOWN MATCH STATE
    # ========================================================

    return Decimal("0.00")

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
                Match.status.in_(
                    [
                       "TIMED",
                       "SCHEDULED",
                       "UPCOMING",
                       "PENDING",
                    ]
              ),
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
# M-PESA WITHDRAWAL MONITOR
# ============================================================

MPESA_STALE_PENDING_MINUTES = 5
MPESA_MONITOR_INTERVAL_SECONDS = 60

_mpesa_monitor_last_run = None
_mpesa_stale_logged = set()


def monitor_stale_mpesa_withdrawals(session):
    """
    Detect user M-PESA B2C withdrawals that have remained pending
    for an unusually long time.

    IMPORTANT:
    - Monitoring only.
    - NEVER refunds automatically.
    - NEVER resubmits automatically.
    - NEVER changes withdrawal status.
    - NEVER changes user balance.

    A pending withdrawal may mean that Safaricom received the
    request even if our application did not receive/save the
    response. Automatic recovery could therefore cause a
    duplicate payout or an incorrect refund.
    """

    global _mpesa_monitor_last_run

    now = datetime.utcnow()

    if (
        _mpesa_monitor_last_run is not None
        and (
            now - _mpesa_monitor_last_run
        ).total_seconds()
        < MPESA_MONITOR_INTERVAL_SECONDS
    ):
        return 0

    _mpesa_monitor_last_run = now

    cutoff = (
        now
        - timedelta(
            minutes=MPESA_STALE_PENDING_MINUTES
        )
    )

    stale_withdrawals = (
        session.query(MpesaWithdrawal)
        .filter(
            MpesaWithdrawal.status == "pending",
            MpesaWithdrawal.created <= cutoff,
        )
        .order_by(
            MpesaWithdrawal.created.asc()
        )
        .all()
    )

    for withdrawal in stale_withdrawals:

        if withdrawal.id in _mpesa_stale_logged:
            continue

        age_seconds = (
            now - withdrawal.created
        ).total_seconds()

        logger.warning(
            "STALE M-PESA USER WITHDRAWAL | "
            "withdrawal=%s | user=%s | amount=%s | "
            "age=%ss | reference=%s | "
            "NO AUTOMATIC REFUND OR RESUBMISSION",
            withdrawal.id,
            withdrawal.user_id,
            withdrawal.amount,
            int(age_seconds),
            withdrawal.reference,
        )

        _mpesa_stale_logged.add(
            withdrawal.id
        )

    # Prevent the in-memory set from growing forever.
    if len(_mpesa_stale_logged) > 10000:
        _mpesa_stale_logged.clear()

    return len(stale_withdrawals)


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
                # M-PESA MONITOR
                # ============================================

                monitor_stale_mpesa_withdrawals(
                    session
                )

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
