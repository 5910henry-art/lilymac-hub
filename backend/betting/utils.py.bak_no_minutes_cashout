# utils.py

import logging
from decimal import Decimal, ROUND_DOWN

from passlib.hash import bcrypt


logger = logging.getLogger(__name__)


# ============================================================
# DECIMAL HELPERS
# ============================================================

def to_decimal(value, quantize=True):
    """Convert a value safely to Decimal."""

    try:
        if isinstance(value, Decimal):
            d = value
        else:
            d = Decimal(str(value))
    except Exception:
        d = Decimal("0")

    if quantize:
        try:
            return d.quantize(
                Decimal("0.01"),
                rounding=ROUND_DOWN,
            )
        except Exception:
            return d

    return d


# ============================================================
# PROBABILITY HELPERS
# ============================================================

def normalize_probability(raw_prob):
    """
    Normalize probability to the range 0.0 - 1.0.

    Accepts either:
        0.65
        65
        65.0
    """

    if raw_prob is None:
        return None

    try:
        p = to_decimal(
            raw_prob,
            quantize=False,
        )

        if p > 1:
            p = p / Decimal("100")

        return max(
            Decimal("0"),
            min(
                Decimal("1"),
                p,
            ),
        )

    except Exception:
        return None


def implied_probability_from_odds(odds_val):
    """Calculate implied probability from decimal odds."""

    try:
        odds = to_decimal(
            odds_val,
            quantize=False,
        )

        if odds <= 0:
            return None

        return Decimal("1") / odds

    except Exception:
        return None


# ============================================================
# OVER / UNDER
# ============================================================

def parse_over_under_threshold(selection: str):
    """
    Extract threshold from selections such as:

        over15
        over25
        over35
        under25
        under35
    """

    if not selection:
        return None

    sel = selection.lower()

    number = ""

    for ch in sel:
        if ch.isdigit() or ch == ".":
            number += ch

    if not number:
        return None

    try:
        if "." in number:
            return float(number)

        if len(number) >= 2:
            return int(number) / 10.0

        return float(number)

    except Exception:
        return None


# ============================================================
# BET EVALUATION
# ============================================================

def evaluate_selection_win(
    home_score,
    away_score,
    selection,
):
    """
    Determine whether a selection has WON.

    Returns:

        True
        False
        None
    """

    home = home_score or 0
    away = away_score or 0

    total = home + away

    sel = (
        selection or ""
    ).lower()

    # --------------------------------------------------------
    # 1X2
    # --------------------------------------------------------

    if sel in (
        "home_odds",
        "home",
    ):
        return home > away

    if sel in (
        "draw_odds",
        "draw",
    ):
        return home == away

    if sel in (
        "away_odds",
        "away",
    ):
        return away > home

    # --------------------------------------------------------
    # OVER / UNDER
    # --------------------------------------------------------

    if (
        sel.startswith("over")
        or sel.startswith("under")
    ):

        threshold = parse_over_under_threshold(
            sel
        )

        if threshold is None:
            return None

        if sel.startswith("over"):
            return total > threshold

        return total < threshold

    # --------------------------------------------------------
    # BTTS
    # --------------------------------------------------------

    if sel in (
        "gg_odds",
        "btts",
    ):
        return (
            home > 0
            and away > 0
        )

    # --------------------------------------------------------
    # NO BTTS
    # --------------------------------------------------------

    if sel in (
        "ng_odds",
        "no_btts",
    ):
        return (
            home == 0
            or away == 0
        )

    return None


# ============================================================
# MATCH STATE
# ============================================================

def _match_status(match):
    return (
        getattr(
            match,
            "status",
            "",
        )
        or ""
    ).lower()


def _match_minute(match):
    """
    Safely obtain the current football minute.

    Supports values such as:

        0
        12
        45
        67
        90
        90+
    """

    minute = getattr(
        match,
        "minute",
        0,
    )

    if minute is None:
        return Decimal("0")

    try:
        if isinstance(
            minute,
            str,
        ):

            value = ""

            for ch in minute:
                if ch.isdigit():
                    value += ch
                elif value:
                    break

            if not value:
                return Decimal("0")

            minute = value

        minute_decimal = Decimal(
            str(minute)
        )

        return max(
            Decimal("0"),
            min(
                Decimal("120"),
                minute_decimal,
            ),
        )

    except Exception:
        return Decimal("0")


# ============================================================
# SELECTION STATE
# ============================================================

def _selection_is_already_won(
    home,
    away,
    selection,
):
    """
    Detect whether the current score already guarantees
    the selection.

    This is deliberately different from evaluate_selection_win().

    evaluate_selection_win() answers:
        "Would this score be a winning final result?"

    This function answers:
        "Has the current score already guaranteed the selection?"
    """

    sel = (
        selection or ""
    ).lower()

    total = home + away

    # --------------------------------------------------------
    # HOME
    #
    # A home selection is NOT guaranteed merely because home
    # is leading. The opponent could still equalize.
    # --------------------------------------------------------

    # No guaranteed state for normal 1X2 before FINISHED.

    # --------------------------------------------------------
    # AWAY
    # --------------------------------------------------------

    # Same logic as home.

    # --------------------------------------------------------
    # OVER
    # --------------------------------------------------------

    if sel.startswith("over"):

        threshold = parse_over_under_threshold(
            sel
        )

        if threshold is None:
            return False

        # Once the score is already above the line,
        # the selection cannot lose.
        return total > threshold

    # --------------------------------------------------------
    # UNDER
    # --------------------------------------------------------

    if sel.startswith("under"):

        threshold = parse_over_under_threshold(
            sel
        )

        if threshold is None:
            return False

        # Under is not guaranteed until the match is finished,
        # because more goals can still be scored.
        return False

    # --------------------------------------------------------
    # BTTS
    # --------------------------------------------------------

    if sel in (
        "gg_odds",
        "btts",
    ):

        # If both teams have already scored, BTTS cannot lose.
        return (
            home > 0
            and away > 0
        )

    # --------------------------------------------------------
    # NO BTTS
    # --------------------------------------------------------

    if sel in (
        "ng_odds",
        "no_btts",
    ):

        # Not guaranteed until match finishes.
        return False

    return False


# ============================================================
# LIVE PROBABILITY
# ============================================================

def _base_selection_probability(
    bet,
    match,
    bookmark,
):
    """
    Obtain the best available starting probability.
    """

    selection = (
        getattr(
            bet,
            "selection",
            "",
        )
        or ""
    ).lower()

    # --------------------------------------------------------
    # Bookmark model probabilities
    # --------------------------------------------------------

    if bookmark:

        try:

            if selection in (
                "home_odds",
                "home",
            ):

                probability = normalize_probability(
                    getattr(
                        bookmark,
                        "p_home",
                        None,
                    )
                )

                if probability is not None:
                    return probability

            elif selection in (
                "draw_odds",
                "draw",
            ):

                probability = normalize_probability(
                    getattr(
                        bookmark,
                        "p_draw",
                        None,
                    )
                )

                if probability is not None:
                    return probability

            elif selection in (
                "away_odds",
                "away",
            ):

                probability = normalize_probability(
                    getattr(
                        bookmark,
                        "p_away",
                        None,
                    )
                )

                if probability is not None:
                    return probability

        except Exception:
            pass

    # --------------------------------------------------------
    # Odds fallback
    # --------------------------------------------------------

    odds = getattr(
        bet,
        "odds",
        None,
    )

    probability = implied_probability_from_odds(
        odds
    )

    if probability is not None:
        return probability

    return Decimal("0.50")


# ============================================================
# LIVE SELECTION PROBABILITY
# ============================================================

def _calculate_live_probability(
    bet,
    match,
    bookmark=None,
):
    """
    Calculate the current probability of a selection.

    The probability changes according to:

        - current score
        - match minute
        - market
        - original probability
        - whether the selection is already guaranteed
    """

    selection = (
        getattr(
            bet,
            "selection",
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

    minute = _match_minute(
        match
    )

    status = _match_status(
        match
    )

    # --------------------------------------------------------
    # FINISHED
    # --------------------------------------------------------

    if status == "finished":

        result = evaluate_selection_win(
            home,
            away,
            selection,
        )

        if result is True:
            return Decimal("1.00")

        if result is False:
            return Decimal("0.00")

        return Decimal("0.00")

    # --------------------------------------------------------
    # Already guaranteed
    # --------------------------------------------------------

    if _selection_is_already_won(
        home,
        away,
        selection,
    ):

        return Decimal("1.00")

    # --------------------------------------------------------
    # Starting probability
    # --------------------------------------------------------

    probability = _base_selection_probability(
        bet,
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

    # ========================================================
    # MARKET-SPECIFIC LIVE ADJUSTMENTS
    # ========================================================

    # --------------------------------------------------------
    # 1X2
    # --------------------------------------------------------

    if selection in (
        "home_odds",
        "home",
        "draw_odds",
        "draw",
        "away_odds",
        "away",
    ):

        diff = home - away

        # HOME
        if selection in (
            "home_odds",
            "home",
        ):

            if diff > 0:
                probability += Decimal("0.20")

                # Stronger adjustment later in match
                if minute >= 60:
                    probability += Decimal("0.10")

            elif diff < 0:

                probability *= Decimal("0.35")

                if minute >= 60:
                    probability *= Decimal("0.60")

            elif diff == 0 and minute >= 70:

                # A home selection in a late-level match
                # is not as valuable as a lead.
                probability *= Decimal("0.80")

        # AWAY
        elif selection in (
            "away_odds",
            "away",
        ):

            if diff < 0:
                probability += Decimal("0.20")

                if minute >= 60:
                    probability += Decimal("0.10")

            elif diff > 0:

                probability *= Decimal("0.35")

                if minute >= 60:
                    probability *= Decimal("0.60")

            elif diff == 0 and minute >= 70:

                probability *= Decimal("0.80")

        # DRAW
        elif selection in (
            "draw_odds",
            "draw",
        ):

            if diff == 0:

                if minute >= 70:
                    probability += Decimal("0.20")
                elif minute >= 50:
                    probability += Decimal("0.10")

            else:

                # A draw selection becomes less likely when
                # one team has a lead.
                probability *= Decimal("0.45")

                if minute >= 70:
                    probability *= Decimal("0.65")

    # --------------------------------------------------------
    # OVER
    # --------------------------------------------------------

    elif selection.startswith("over"):

        threshold = parse_over_under_threshold(
            selection
        )

        if threshold is not None:

            goals_needed = (
                Decimal(str(threshold))
                - Decimal(str(home + away))
            )

            # Already guaranteed was handled above.

            if goals_needed <= 1:

                # One goal needed late in the match:
                # still possible, but increasingly valuable
                # if time remains.
                if minute < 30:
                    probability += Decimal("0.05")
                elif minute < 60:
                    probability += Decimal("0.15")
                elif minute < 75:
                    probability += Decimal("0.20")
                else:
                    probability += Decimal("0.10")

            elif goals_needed >= 2:

                # Multiple goals still required.
                if minute >= 70:
                    probability *= Decimal("0.65")
                elif minute >= 55:
                    probability *= Decimal("0.80")

    # --------------------------------------------------------
    # UNDER
    # --------------------------------------------------------

    elif selection.startswith("under"):

        threshold = parse_over_under_threshold(
            selection
        )

        if threshold is not None:

            remaining_goals_allowed = (
                Decimal(str(threshold))
                - Decimal(str(home + away))
            )

            if remaining_goals_allowed <= 0:

                # The under has already lost.
                return Decimal("0.01")

            # Under becomes more valuable as time disappears.
            if minute >= 75:
                probability += Decimal("0.20")
            elif minute >= 60:
                probability += Decimal("0.12")
            elif minute >= 45:
                probability += Decimal("0.07")

    # --------------------------------------------------------
    # BTTS
    # --------------------------------------------------------

    elif selection in (
        "gg_odds",
        "btts",
    ):

        if home > 0 and away > 0:

            return Decimal("1.00")

        if home > 0 or away > 0:

            # One team has scored. BTTS now depends on
            # the other team scoring.
            if minute >= 75:
                probability *= Decimal("0.55")
            elif minute >= 60:
                probability *= Decimal("0.75")
            else:
                probability += Decimal("0.05")

        else:

            if minute >= 75:
                probability *= Decimal("0.45")
            elif minute >= 60:
                probability *= Decimal("0.65")

    # --------------------------------------------------------
    # NO BTTS
    # --------------------------------------------------------

    elif selection in (
        "ng_odds",
        "no_btts",
    ):

        if home > 0 and away > 0:

            # No BTTS has already lost.
            return Decimal("0.01")

        if minute >= 75:
            probability += Decimal("0.20")
        elif minute >= 60:
            probability += Decimal("0.12")

    # ========================================================
    # TIME VALUE
    # ========================================================

    time_factor = min(
        minute / Decimal("90"),
        Decimal("1"),
    )

    # Small general adjustment.
    #
    # This is intentionally much smaller than the market-
    # specific adjustments above.
    if probability > Decimal("0.50"):

        probability += (
            time_factor
            * Decimal("0.08")
        )

    else:

        probability -= (
            time_factor
            * Decimal("0.10")
        )

    return max(
        Decimal("0.01"),
        min(
            Decimal("0.99"),
            probability,
        ),
    )


# ============================================================
# CASHOUT ENGINE
# ============================================================

def calculate_live_cashout(
    bet,
    match,
    bookmark=None,
):
    """
    Calculate live cashout for an individual Bet.

    IMPORTANT:

    The returned value represents the CURRENT value of the
    bet, not a fixed percentage of the original stake.

    Examples:

        Original 4-leg accumulator:
            potential = 10,000

        Three legs already won:
            those legs are effectively probability = 1.00

        Final leg not started:
            its current probability is used

        Therefore:

            cashout =
                potential
                × probability_of_remaining_leg
                × bookmaker_margin

    This means the cashout changes as the accumulator progresses.
    """

    try:

        if bet is None:
            return Decimal("0.00")

        status = (
            getattr(
                bet,
                "status",
                "pending",
            )
            or "pending"
        ).lower()

        if status != "pending":
            return Decimal("0.00")

        if getattr(
            bet,
            "cashed_out",
            False,
        ):
            return Decimal("0.00")

        potential = to_decimal(
            getattr(
                bet,
                "potential",
                Decimal("0.00"),
            )
        )

        stake = to_decimal(
            getattr(
                bet,
                "stake",
                potential,
            )
        )

        if potential <= 0:
            return Decimal("0.00")

        status = _match_status(
            match
        )

        # ====================================================
        # FINISHED
        # ====================================================

        if status == "finished":

            result = evaluate_selection_win(
                getattr(
                    match,
                    "home_score",
                    0,
                ),
                getattr(
                    match,
                    "away_score",
                    0,
                ),
                getattr(
                    bet,
                    "selection",
                    "",
                ),
            )

            if result is True:
                return potential.quantize(
                    Decimal("0.01"),
                    rounding=ROUND_DOWN,
                )

            return Decimal("0.00")

        # ====================================================
        # PRE-MATCH
        # ====================================================

        if status in (
            "pending",
            "not_started",
            "scheduled",
            "upcoming",
            "timed",
            "",
        ):

            probability = _base_selection_probability(
                bet,
                match,
                bookmark,
            )

            # Pre-match cashout is deliberately below potential.
            cashout = (
                potential
                * probability
                * Decimal("0.90")
            )

            # Never return the original potential merely
            # because the match has not started.
            cashout = min(
                cashout,
                potential * Decimal("0.90"),
            )

            # Keep a small floor.
            if stake > 0:
                cashout = max(
                    cashout,
                    stake * Decimal("0.10"),
                )

            return cashout.quantize(
                Decimal("0.01"),
                rounding=ROUND_DOWN,
            )

        # ====================================================
        # LIVE
        # ====================================================

        probability = _calculate_live_probability(
            bet,
            match,
            bookmark,
        )

        probability = max(
            Decimal("0.01"),
            min(
                Decimal("1.00"),
                probability,
            ),
        )

        # ----------------------------------------------------
        # Current fair value
        # ----------------------------------------------------

        fair_value = (
            potential
            * probability
        )

        # ----------------------------------------------------
        # Bookmaker margin
        # ----------------------------------------------------

        # Lower than the old 8% margin when the bet is strongly
        # established, but still protects the bookmaker.
        margin = Decimal("0.07")

        cashout = (
            fair_value
            * (Decimal("1.00") - margin)
        )

        # ----------------------------------------------------
        # Maximum cashout
        # ----------------------------------------------------

        # Don't allow the user to cash out above the potential
        # payout.
        cashout = min(
            cashout,
            potential * Decimal("0.98"),
        )

        # ----------------------------------------------------
        # Minimum cashout
        # ----------------------------------------------------

        if stake > 0:

            minimum = (
                stake
                * Decimal("0.05")
            )

            cashout = max(
                cashout,
                minimum,
            )

        return cashout.quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )

    except Exception as e:

        logger.exception(
            "Cashout error: %s",
            e,
        )

        return Decimal("0.00")


# ============================================================
# OPTIONAL: ACCUMULATOR CASHOUT HELPER
# ============================================================

def calculate_accumulator_cashout(
    potential,
    legs,
):
    """
    Calculate cashout for an accumulator.

    Each leg must contain:

        probability

    A leg that has already won should have:

        probability = 1.00

    A future/live leg should have its current probability.

    Example:

        Leg 1 = 1.00
        Leg 2 = 1.00
        Leg 3 = 1.00
        Leg 4 = 0.55

        combined = 0.55

    This prevents already-won legs from being treated as though
    they are still at their original pre-match probabilities.
    """

    try:

        potential = to_decimal(
            potential
        )

        if potential <= 0:
            return Decimal("0.00")

        if not legs:
            return Decimal("0.00")

        combined_probability = Decimal("1.00")

        for leg in legs:

            probability = normalize_probability(
                leg.get(
                    "probability",
                    leg.get(
                        "prob",
                        0,
                    ),
                )
            )

            if probability is None:
                probability = Decimal("0.01")

            combined_probability *= probability

        # Bookmaker margin
        cashout = (
            potential
            * combined_probability
            * Decimal("0.93")
        )

        cashout = min(
            cashout,
            potential * Decimal("0.98"),
        )

        return cashout.quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN,
        )

    except Exception as e:

        logger.exception(
            "Accumulator cashout error: %s",
            e,
        )

        return Decimal("0.00")
