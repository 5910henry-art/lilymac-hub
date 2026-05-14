# utils.py
import logging
from decimal import Decimal, ROUND_DOWN
from passlib.hash import bcrypt

logger = logging.getLogger(__name__)

# -------------------------
# Decimal helpers
# -------------------------
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
            return d.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        except Exception:
            return d

    return d


# -------------------------
# Probability helpers
# -------------------------
def normalize_probability(raw_prob):
    if raw_prob is None:
        return None

    p = to_decimal(raw_prob, quantize=False)

    try:
        if p > 1:
            p = p / Decimal(100)
    except Exception:
        return None

    return max(Decimal(0), min(Decimal(1), p))


def implied_probability_from_odds(odds_val):
    try:
        odds = to_decimal(odds_val, quantize=False)
        if odds <= 0:
            return None
        return Decimal(1) / odds
    except Exception:
        return None


def parse_over_under_threshold(selection: str):
    if not selection:
        return None

    sel = selection.lower()
    num = ''.join(ch for ch in sel if ch.isdigit() or ch == '.')

    if not num:
        digits = ''.join(ch for ch in sel if ch.isdigit())
        if not digits:
            return None
        try:
            return int(digits) / 10.0
        except Exception:
            return None

    try:
        if '.' in num:
            return float(num)
        if len(num) >= 2:
            return int(num) / 10.0
        return float(num)
    except Exception:
        return None


# -------------------------
# Bet evaluation
# -------------------------
def evaluate_selection_win(home_score, away_score, selection):
    home = home_score or 0
    away = away_score or 0
    total = home + away
    sel = (selection or "").lower()

    if sel in ("home_odds", "home"):
        return home > away

    if sel in ("draw_odds", "draw"):
        return home == away

    if sel in ("away_odds", "away"):
        return away > home

    if sel.startswith("over") or sel.startswith("under"):
        threshold = parse_over_under_threshold(sel)
        if threshold is None:
            return None
        return total > threshold if sel.startswith("over") else total < threshold

    if sel in ("gg_odds", "btts"):
        return home > 0 and away > 0

    if sel in ("ng_odds", "no_btts"):
        return home == 0 or away == 0

    return None


# -------------------------
# Advanced Cashout Engine
# -------------------------
def calculate_live_cashout(bet, match, bookmark=None):
    """
    Advanced bookmaker-style cashout:
    - Probability
    - Time decay
    - Margin
    - Risk control
    """
    try:
        if bet is None:
            return Decimal("0.00")

        if getattr(bet, "status", "pending") != "pending" or getattr(bet, "cashed_out", False):
            return Decimal("0.00")

        potential = to_decimal(getattr(bet, "potential", Decimal("0.00")))
        stake = to_decimal(getattr(bet, "stake", potential))
        sel = (getattr(bet, "selection", "") or "").lower()

        status = (getattr(match, "status", "") or "").lower()
        minute = getattr(match, "minute", 0) or 0

        # -------------------------
        # Pre-match (house margin)
        # -------------------------
        if status in {"pending", "not_started", "scheduled", "upcoming", ""}:
            return (potential * Decimal("0.90")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

        # -------------------------
        # Base probability
        # -------------------------
        base_prob = None

        if bookmark:
            try:
                if sel in ("home_odds", "home"):
                    base_prob = normalize_probability(getattr(bookmark, "p_home", None))
                elif sel in ("draw_odds", "draw"):
                    base_prob = normalize_probability(getattr(bookmark, "p_draw", None))
                elif sel in ("away_odds", "away"):
                    base_prob = normalize_probability(getattr(bookmark, "p_away", None))
            except Exception:
                base_prob = None

        if base_prob is None:
            odds = getattr(bet, "odds", None)
            base_prob = implied_probability_from_odds(odds) or Decimal("0.50")

        base_prob = max(Decimal("0.01"), min(Decimal("0.99"), to_decimal(base_prob, False)))

        # -------------------------
        # Score impact
        # -------------------------
        home = getattr(match, "home_score", 0) or 0
        away = getattr(match, "away_score", 0) or 0
        diff = home - away

        if sel in ("home_odds", "home") and diff > 0:
            base_prob += Decimal("0.15")
        elif sel in ("away_odds", "away") and diff < 0:
            base_prob += Decimal("0.15")
        elif sel in ("draw_odds", "draw") and diff == 0:
            base_prob += Decimal("0.10")

        # Losing penalty
        if sel in ("home_odds", "home") and diff < 0:
            base_prob *= Decimal("0.40")
        elif sel in ("away_odds", "away") and diff > 0:
            base_prob *= Decimal("0.40")

        # -------------------------
        # Time decay
        # -------------------------
        time_factor = Decimal(min(minute / 90, 1))

        if base_prob > Decimal("0.5"):
            base_prob += time_factor * Decimal("0.20")
        else:
            base_prob -= time_factor * Decimal("0.25")

        base_prob = max(Decimal("0.01"), min(Decimal("0.99"), base_prob))

        # -------------------------
        # Fair value
        # -------------------------
        fair_cashout = potential * base_prob

        # -------------------------
        # Bookmaker margin
        # -------------------------
        margin = Decimal("0.08")
        cashout = fair_cashout * (Decimal("1.0") - margin)

        # -------------------------
        # Risk controls
        # -------------------------
        cashout = min(cashout, potential * Decimal("0.95"))  # max cap
        cashout = max(cashout, stake * Decimal("0.10"))      # min floor

        return cashout.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    except Exception as e:
        logger.exception("Cashout error: %s", e)
        return Decimal("0.00")
