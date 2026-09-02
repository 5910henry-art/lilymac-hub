# betting/bets.py

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, InvalidOperation

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import text

from betting.models import (
    db,
    User,
    Bookmark,
    BetSlip,
    BetSelection,
    Bet,
    Transaction,
    Match,
    HouseWallet,
    HouseTransaction,
)
from .utils import (
    to_decimal,
    evaluate_selection_win,
    parse_over_under_threshold,
)

logger = logging.getLogger(__name__)

bet_bp = Blueprint("bets", __name__)


# ============================================================
# DEFAULT CONFIGURATION
# ============================================================

DEFAULTS = {
    "MAX_STAKE": Decimal("10000.00"),
    "MAX_SELECTIONS": 10,
    "ODDS_SLIPPAGE": Decimal("0.02"),
    "IDEMPOTENCY_TABLE": "idempotency_records",
}


# ============================================================
# CUSTOM ERRORS
# ============================================================

class BetRequestError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# ============================================================
# GENERAL HELPERS
# ============================================================

def _now_utc():
    return datetime.now(timezone.utc)


def _d(value, fallback=Decimal("0.00")):
    """
    Safely convert a value to Decimal.
    """
    try:
        result = to_decimal(value)

        if result is None:
            return fallback

        return Decimal(str(result))

    except (InvalidOperation, TypeError, ValueError, ArithmeticError):
        return fallback


def _money(value):
    """
    Normalize money values to 2 decimal places.
    """
    return _d(value).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN,
    )

def _credit_house(stake, reference=None, description=None):
    """
    Credit the house wallet with a normal football bet stake.

    Must run inside the existing database transaction.
    """
    stake = _money(stake)

    if stake <= Decimal("0.00"):
        raise BetRequestError(
            "invalid house credit amount",
            400,
        )

    house = (
        db.session.query(HouseWallet)
        .with_for_update()
        .filter(HouseWallet.id == 1)
        .first()
    )

    if not house:
        raise RuntimeError(
            "House wallet is not initialized"
        )

    house.balance = _money(
        _d(house.balance) + stake
    )

    house_transaction = HouseTransaction(
        type="bet_stake",
        amount=stake,
        balance_after=house.balance,
        reference=(
            str(reference)
            if reference is not None
            else None
        ),
        description=(
            description
            or "Normal football bet stake received"
        ),
    )

    db.session.add(house_transaction)

    return house


def _debit_house(amount, reference=None, description=None, transaction_type="bet_payout"):
    """
    Debit the house wallet for a payout or refund.

    Must run inside the existing database transaction.
    The house wallet row is locked to prevent concurrent
    payouts from using the same balance.
    """
    amount = _money(amount)

    if amount <= Decimal("0.00"):
        raise BetRequestError(
            "invalid house debit amount",
            400,
        )

    house = (
        db.session.query(HouseWallet)
        .with_for_update()
        .filter(HouseWallet.id == 1)
        .first()
    )

    if not house:
        raise RuntimeError(
            "House wallet is not initialized"
        )

    current_balance = _money(
        _d(house.balance)
    )

    if current_balance < amount:
        raise BetRequestError(
            "house wallet has insufficient funds",
            503,
        )

    house.balance = _money(
        current_balance - amount
    )

    house_transaction = HouseTransaction(
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

    db.session.add(house_transaction)

    return house

def _get_config_decimal(key):
    value = current_app.config.get(
        key,
        DEFAULTS.get(key, Decimal("0.00")),
    )

    if isinstance(value, Decimal):
        return value

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return DEFAULTS[key]


def _get_max_selections():
    try:
        return int(
            current_app.config.get(
                "MAX_SELECTIONS",
                DEFAULTS["MAX_SELECTIONS"],
            )
        )
    except (TypeError, ValueError):
        return DEFAULTS["MAX_SELECTIONS"]


# ============================================================
# SELECTION NORMALIZATION
# ============================================================

def _normalize_selection(selection, team=None, bookmark=None):
    """
    Normalize frontend selection names into database odds fields.

    Supported:
        1 / X / 2
        home / away / draw
        home_odds / away_odds / draw_odds
        over05 / under05
        over15 / under15
        over25 / under25
        over35 / under35
        btts_yes / btts_no
        gg / ng
        exact home/away team name
    """

    sel = str(selection or "").strip().lower()

    sel = sel.replace(" ", "_")
    sel = sel.replace("-", "_")

    aliases = {
        "1": "home_odds",
        "x": "draw_odds",
        "2": "away_odds",

        "home": "home_odds",
        "away": "away_odds",
        "draw": "draw_odds",

        "home_odds": "home_odds",
        "away_odds": "away_odds",
        "draw_odds": "draw_odds",

        "over_05": "over05",
        "under_05": "under05",
        "over_15": "over15",
        "under_15": "under15",
        "over_25": "over25",
        "under_25": "under25",
        "over_35": "over35",
        "under_35": "under35",

        "btts_yes": "gg_odds",
        "btts_no": "ng_odds",
        "gg": "gg_odds",
        "ng": "ng_odds",
    }

    sel = aliases.get(sel, sel)

    valid = {
        "home_odds",
        "away_odds",
        "draw_odds",

        "over05",
        "under05",
        "over15",
        "under15",
        "over25",
        "under25",
        "over35",
        "under35",

        "gg_odds",
        "ng_odds",
    }

    if sel in valid:
        return sel

    # Allow frontend to send the actual team name.
    if team and bookmark:
        team = str(team).strip()

        home_team = str(getattr(bookmark, "home_team", "") or "").strip()
        away_team = str(getattr(bookmark, "away_team", "") or "").strip()

        if team.casefold() == home_team.casefold():
            return "home_odds"

        if team.casefold() == away_team.casefold():
            return "away_odds"

    return sel


# ============================================================
# IDEMPOTENCY
# ============================================================

def _ensure_idempotency_table():
    """
    Ensure idempotency table exists.

    PostgreSQL and SQLite are supported.
    """

    table_name = current_app.config.get(
        "IDEMPOTENCY_TABLE",
        DEFAULTS["IDEMPOTENCY_TABLE"],
    )

    # Keep table name controlled by application config.
    create_sql = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            key TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            response_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """

    try:
        db.session.execute(text(create_sql))
        db.session.commit()

    except Exception:
        db.session.rollback()
        logger.exception(
            "Failed to create idempotency table"
        )


def _read_idempotency(key, user_id):
    table_name = current_app.config.get(
        "IDEMPOTENCY_TABLE",
        DEFAULTS["IDEMPOTENCY_TABLE"],
    )

    query = text(
        f"""
        SELECT response_json
        FROM {table_name}
        WHERE key = :key
          AND user_id = :user_id
        """
    )

    try:
        row = db.session.execute(
            query,
            {
                "key": key,
                "user_id": user_id,
            },
        ).fetchone()

        if not row:
            return None

        return json.loads(row[0])

    except Exception:
        logger.exception(
            "Failed reading idempotency key=%s user=%s",
            key,
            user_id,
        )

        return None


def _write_idempotency(key, user_id, payload):
    table_name = current_app.config.get(
        "IDEMPOTENCY_TABLE",
        DEFAULTS["IDEMPOTENCY_TABLE"],
    )

    payload_json = json.dumps(
        payload,
        separators=(",", ":"),
    )

    try:
        dialect = db.session.bind.dialect.name

    except Exception:
        dialect = None

    if dialect == "postgresql":
        query = text(
            f"""
            INSERT INTO {table_name}
                (key, user_id, response_json)
            VALUES
                (:key, :user_id, :response_json)
            ON CONFLICT (key) DO NOTHING
            """
        )

    elif dialect == "sqlite":
        query = text(
            f"""
            INSERT OR IGNORE INTO {table_name}
                (key, user_id, response_json)
            VALUES
                (:key, :user_id, :response_json)
            """
        )

    else:
        query = text(
            f"""
            INSERT INTO {table_name}
                (key, user_id, response_json)
            SELECT
                :key,
                :user_id,
                :response_json
            WHERE NOT EXISTS (
                SELECT 1
                FROM {table_name}
                WHERE key = :key
            )
            """
        )

    try:
        db.session.execute(
            query,
            {
                "key": key,
                "user_id": user_id,
                "response_json": payload_json,
            },
        )

    except Exception:
        logger.exception(
            "Failed writing idempotency key=%s user=%s",
            key,
            user_id,
        )

        raise


# ============================================================
# BOOKMARK / MATCH HELPERS
# ============================================================

def _get_bookmark_by_match_id(match_id):
    try:
        match_id = int(match_id)
    except (TypeError, ValueError):
        return None

    try:
        return (
            db.session.query(Bookmark)
            .filter_by(match_id=match_id)
            .first()
        )

    except Exception:
        logger.exception(
            "Error loading bookmark for match_id=%s",
            match_id,
        )
        return None


def _match_has_started(bookmark):
    if not bookmark:
        return False

    match_time = getattr(
        bookmark,
        "match_time",
        None,
    )

    if not match_time:
        return False

    try:
        if match_time.tzinfo is None:
            match_time = match_time.replace(
                tzinfo=timezone.utc
            )

        return match_time <= _now_utc()

    except Exception:
        logger.exception(
            "Failed checking match start time"
        )
        return False


# ============================================================
# ODDS VALIDATION
# ============================================================

def _client_odds_validate(
    bookmark,
    selection,
    client_odds,
    slippage,
):
    """
    Validate that:
      1. The selected odds field exists.
      2. Odds are positive.
      3. Client odds have not moved beyond allowed slippage.
    """

    odds_value = getattr(
        bookmark,
        selection,
        None,
    )

    if odds_value is None:
        return (
            None,
            False,
            f"invalid selection: {selection}",
        )

    odds = _d(odds_value)

    if odds <= 0:
        return (
            None,
            False,
            "selected odds are invalid",
        )

    if client_odds is None:
        return odds, True, ""

    try:
        client_value = Decimal(
            str(client_odds)
        )

    except (InvalidOperation, TypeError, ValueError):
        return (
            None,
            False,
            "client odds not a valid number",
        )

    if client_value <= 0:
        return (
            None,
            False,
            "client odds must be greater than zero",
        )

    difference = abs(
        odds - client_value
    ) / odds

    if difference > slippage:
        return (
            odds,
            False,
            (
                f"odds changed "
                f"(live={odds}, client={client_value})"
            ),
        )

    return odds, True, ""


# ============================================================
# CASHOUT HELPERS
# ============================================================
# ============================================================
# BETSLIP CASHOUT VALIDATION
# ============================================================

def _validate_betslip_cashout(slip):
    """
    Final server-side validation before paying accumulator
    cashout.

    Returns:

        (True, "")
        (False, reason)

    A single definitively lost selection makes the entire
    accumulator unavailable for cashout.
    """

    selections = list(
        getattr(
            slip,
            "selections",
            [],
        )
        or []
    )

    if not selections:
        return False, "no selections"

    for sel in selections:

        sel_status = (
            getattr(
                sel,
                "status",
                "",
            )
            or ""
        ).lower()

        # Already known lost
        if sel_status in (
            "lost",
            "voided",
        ):
            return (
                False,
                "selection already lost",
            )

        # Already won is fine
        if sel_status == "won":
            continue

        bookmark = getattr(
            sel,
            "bookmark",
            None,
        )

        match = None

        if bookmark:
            match = getattr(
                bookmark,
                "match",
                None,
            )

        # Fallback through Bookmark.match_id
        if not match and bookmark:

            match_id = getattr(
                bookmark,
                "match_id",
                None,
            )

            if match_id:

                match = (
                    db.session.query(Match)
                    .filter_by(id=match_id)
                    .first()
                )

        # Final fallback
        if not match and getattr(
            sel,
            "bookmark_id",
            None,
        ):

            match = (
                db.session.query(Match)
                .filter_by(
                    id=sel.bookmark_id
                )
                .first()
            )

        if not match:
            return (
                False,
                "match unavailable",
            )

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

        selection = (
            getattr(
                sel,
                "selection",
                "",
            )
            or ""
        )

        # ----------------------------------------------------
        # FINISHED
        # ----------------------------------------------------

        if match_status == "finished":

            result = evaluate_selection_win(
                home,
                away,
                selection,
            )

            if result is False:

                sel.status = "lost"

                return (
                    False,
                    "selection lost",
                )

            if result is True:

                sel.status = "won"

                continue

            return (
                False,
                "selection result unavailable",
            )

        # ----------------------------------------------------
        # LIVE — check markets that can already be
        # mathematically dead.
        # ----------------------------------------------------

        if match_status == "in_play":

            sel_lower = selection.lower()

            # OVER
            if sel_lower.startswith("over"):

                threshold = parse_over_under_threshold(
                    sel_lower
                )

                if threshold is not None:

                    total = home + away

                    # Over is already impossible only if
                    # the match has actually finished.
                    #
                    # While IN_PLAY, do NOT mark it lost.
                    pass

            # UNDER
            elif sel_lower.startswith("under"):

                threshold = parse_over_under_threshold(
                    sel_lower
                )

                if threshold is not None:

                    total = home + away

                    # Under is definitely lost once the
                    # score reaches the line.
                    if Decimal(str(total)) >= Decimal(
                        str(threshold)
                    ):

                        sel.status = "lost"

                        return (
                            False,
                            "under selection already lost",
                        )

            # BTTS
            elif sel_lower in (
                "gg_odds",
                "btts",
            ):

                # If the match is still in-play and one side
                # has not scored, BTTS is still alive.
                pass

            # NO BTTS
            elif sel_lower in (
                "ng_odds",
                "no_btts",
            ):

                if home > 0 and away > 0:

                    sel.status = "lost"

                    return (
                        False,
                        "no-btts already lost",
                    )

            # 1X2
            #
            # Being behind does NOT mean lost while IN_PLAY.
            # The match can still change.
            #
            # Therefore do nothing here.

    return True, ""

def _pending_cashout_amount(stake):
    """
    Default pending cashout value.

    Current business rule:
        95% of original stake.
    """

    return _money(
        _d(stake) * Decimal("0.95")
    )


def _cashout_amount_for_betslip(slip):
    """
    Return the scheduler-calculated cashout.

    IMPORTANT:
    A pending BetSlip does NOT automatically receive 95%
    of its stake.

    The current_cashout value must have been calculated by
    the cashout engine.
    """

    status = (
        getattr(
            slip,
            "status",
            "",
        )
        or ""
    ).lower()

    if status in (
        "lost",
        "voided",
        "settled",
        "cancelled",
        "cashed_out",
    ):
        return Decimal("0.00")

    stored = getattr(
        slip,
        "current_cashout",
        None,
    )

    if stored is None:
        return Decimal("0.00")

    amount = _d(stored)

    if amount <= 0:
        return Decimal("0.00")

    return _money(amount)


def _cashout_amount_for_legacy_bet(bet):
    status = (
        getattr(bet, "status", "") or ""
    ).lower()

    if status == "lost":
        return Decimal("0.00")

    if status == "pending":
        return _pending_cashout_amount(
            bet.amount
        )

    stored = getattr(
        bet,
        "current_cashout",
        None,
    )

    if stored is None:
        return Decimal("0.00")

    amount = _d(stored)

    if amount <= 0:
        return Decimal("0.00")

    return _money(amount)


# ============================================================
# SCORE HELPERS
# ============================================================

def _fetch_match_scores(match_ids):
    """
    Return:

        {
            match_id: "home-away"
        }

    """

    cleaned_ids = set()

    for value in match_ids or []:
        try:
            cleaned_ids.add(int(value))
        except (TypeError, ValueError):
            continue

    if not cleaned_ids:
        return {}

    scores = {}

    try:
        rows = (
            db.session.query(
                Match.id,
                Match.home_score,
                Match.away_score,
            )
            .filter(
                Match.id.in_(cleaned_ids)
            )
            .all()
        )

        for row in rows:
            match_id = int(row[0])
            home_score = row[1]
            away_score = row[2]

            if (
                home_score is not None
                and away_score is not None
            ):
                scores[match_id] = (
                    f"{home_score}-{away_score}"
                )
            else:
                scores[match_id] = None

    except Exception:
        logger.exception(
            "Failed fetching match scores"
        )

    return scores


# ============================================================
# SINGLE BET
# ============================================================

def _handle_single_bet(
    user,
    uid,
    stake,
    selection_data,
    slippage,
):
    now = _now_utc()

    match_id = selection_data.get(
        "match_id"
    )
    selection = selection_data.get(
        "selection"
    )
    team = selection_data.get("team")
    client_odds = selection_data.get(
        "client_odds"
    )

    if match_id is None or not selection:
        raise BetRequestError(
            "invalid single bet payload",
            400,
        )

    try:
        match_id = int(match_id)

    except (TypeError, ValueError):
        raise BetRequestError(
            "invalid match_id",
            400,
        )

    bookmark = _get_bookmark_by_match_id(
        match_id
    )

    if not bookmark:
        raise BetRequestError(
            f"match {match_id} not found",
            404,
        )

    if _match_has_started(bookmark):
        raise BetRequestError(
            "match already started",
            400,
        )

    selection = _normalize_selection(
        selection,
        team,
        bookmark,
    )

    odds, valid, message = _client_odds_validate(
        bookmark,
        selection,
        client_odds,
        slippage,
    )

    if not valid:
        raise BetRequestError(
            message,
            400,
        )

    potential = _money(
        stake * odds
    )

    bet = Bet(
        user_id=uid,
        match_id=match_id,
        selection=selection,
        odds=odds,
        amount=stake,
        potential=potential,
        status="pending",
        cashed_out=False,
        current_cashout=Decimal("0.00"),
        created=now,
    )

    db.session.add(bet)
    db.session.flush()

    user.balance = _money(
        _d(user.balance) - stake
    )

    transaction = Transaction(
        user_id=uid,
        type="bet",
        amount=stake,
        balance_after=user.balance,
        created=now,
    )

    db.session.add(transaction)

    _credit_house(
       stake,
       reference=f"bet:{bet.id}",
       description="Normal football single bet stake",
    )

    db.session.flush()

    return {
        "msg": "single bet placed",
        "bet_id": bet.id,
        "stake": str(stake),
        "odds": str(odds),
        "potential_win": str(potential),
        "type": "single",
        "created": now.isoformat(),
    }, 201


# ============================================================
# ACCUMULATOR BET
# ============================================================

def _handle_accumulator_bet(
    user,
    uid,
    stake,
    selections,
    slippage,
):
    now = _now_utc()

    total_odds = Decimal("1.0000")
    validated = []

    for item in selections:
        match_id = item.get("match_id")
        selection = item.get("selection")
        team = item.get("team")
        client_odds = item.get(
            "client_odds"
        )

        if match_id is None or not selection:
            raise BetRequestError(
                "invalid selection payload",
                400,
            )

        try:
            match_id = int(match_id)

        except (TypeError, ValueError):
            raise BetRequestError(
                "match_id must be an integer",
                400,
            )

        bookmark = _get_bookmark_by_match_id(
            match_id
        )

        if not bookmark:
            raise BetRequestError(
                f"match {match_id} not found",
                404,
            )

        if _match_has_started(bookmark):
            raise BetRequestError(
                f"match {match_id} already started",
                400,
            )

        selection = _normalize_selection(
            selection,
            team,
            bookmark,
        )

        odds, valid, message = (
            _client_odds_validate(
                bookmark,
                selection,
                client_odds,
                slippage,
            )
        )

        if not valid:
            raise BetRequestError(
                f"match {match_id}: {message}",
                400,
            )

        validated.append(
            {
                "match_id": match_id,
                "bookmark": bookmark,
                "selection": selection,
                "odds": odds,
            }
        )

        total_odds = (
            total_odds * odds
        ).quantize(
            Decimal("0.0001"),
            rounding=ROUND_DOWN,
        )

    if not validated:
        raise BetRequestError(
            "no selections",
            400,
        )

    potential = _money(
        stake * total_odds
    )

    betslip = BetSlip(
        user_id=uid,
        stake=stake,
        total_odds=total_odds,
        potential=potential,
        current_cashout=Decimal("0.00"),
        status="pending",
        match_id=validated[0]["match_id"],
        created=now,
    )

    db.session.add(betslip)
    db.session.flush()

    for item in validated:
        bookmark = item["bookmark"]

        selection = BetSelection(
            betslip_id=betslip.id,

            # Existing schema appears to use
            # bookmark_id as the actual match id.
            bookmark_id=item["match_id"],

            selection=item["selection"],
            odds=item["odds"],
            league=getattr(
                bookmark,
                "league",
                None,
            ),
            home_team=getattr(
                bookmark,
                "home_team",
                None,
            ),
            away_team=getattr(
                bookmark,
                "away_team",
                None,
            ),
            match_time=getattr(
                bookmark,
                "match_time",
                None,
            ),
            created=now,
        )

        db.session.add(selection)

    user.balance = _money(
        _d(user.balance) - stake
    )

    transaction = Transaction(
        user_id=uid,
        type="bet",
        amount=stake,
        balance_after=user.balance,
        created=now,
    )

    db.session.add(transaction)
    _credit_house(
       stake,
       reference=f"betslip:{betslip.id}",
       description="Normal football accumulator bet stake",
    )

    db.session.flush()

    return {
        "msg": "accumulator bet placed",
        "betslip_id": betslip.id,
        "stake": str(stake),
        "total_odds": str(total_odds),
        "potential_win": str(potential),
        "selections": len(validated),
        "type": "accumulator",
        "created": now.isoformat(),
    }, 201


# ============================================================
# PLACE BET
# ============================================================

@bet_bp.route(
    "/place_bet",
    methods=["POST"],
)
@jwt_required()
def place_bet():

    try:
        uid = int(
            get_jwt_identity()
        )

    except (TypeError, ValueError):
        return jsonify({
            "error": "invalid user identity"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    max_stake = _get_config_decimal(
        "MAX_STAKE"
    )

    max_selections = (
        _get_max_selections()
    )

    slippage = _get_config_decimal(
        "ODDS_SLIPPAGE"
    )

    # --------------------------------------------------------
    # IDEMPOTENCY
    # --------------------------------------------------------

    idempotency_key = (
        request.headers.get(
            "Idempotency-Key"
        )
        or data.get("idempotency_key")
    )

    if idempotency_key:
        idempotency_key = str(
            idempotency_key
        ).strip()

        if len(idempotency_key) > 255:
            return jsonify({
                "error": "idempotency key too long"
            }), 400

        _ensure_idempotency_table()

        previous = _read_idempotency(
            idempotency_key,
            uid,
        )

        if previous is not None:
            return jsonify(previous), 200

        # _read_idempotency() performs a SELECT, which starts
        # an SQLAlchemy transaction. End that read-only transaction
        # before starting the atomic bet transaction below.
        db.session.rollback()

    # --------------------------------------------------------
    # STAKE
    # --------------------------------------------------------

    try:
        stake = Decimal(
            str(data.get("stake", "0"))
        )

    except (InvalidOperation, TypeError, ValueError):
        return jsonify({
            "error": "invalid stake format"
        }), 400

    stake = _money(stake)

    if stake <= 0:
        return jsonify({
            "error": "invalid stake"
        }), 400

    if stake > max_stake:
        return jsonify({
            "error": (
                f"stake exceeds maximum limit "
                f"({max_stake})"
            )
        }), 400

    # --------------------------------------------------------
    # BUILD SELECTION LIST
    # --------------------------------------------------------

    selections = data.get(
        "selections"
    )

    if not selections:

        match_id = data.get(
            "match_id"
        )

        selection = data.get(
            "selection"
        )

        team = data.get("team")

        # Support team-only selection.
        if team and not selection:

            if match_id is None:
                return jsonify({
                    "error": (
                        "match_id required "
                        "when using team field"
                    )
                }), 400

            bookmark = (
                _get_bookmark_by_match_id(
                    match_id
                )
            )

            if not bookmark:
                return jsonify({
                    "error": "match not found"
                }), 404

            home_team = str(
                getattr(
                    bookmark,
                    "home_team",
                    "",
                ) or ""
            )

            away_team = str(
                getattr(
                    bookmark,
                    "away_team",
                    "",
                ) or ""
            )

            if (
                str(team).strip().casefold()
                == home_team.strip().casefold()
            ):
                selection = "home_odds"

            elif (
                str(team).strip().casefold()
                == away_team.strip().casefold()
            ):
                selection = "away_odds"

            else:
                return jsonify({
                    "error": "invalid team"
                }), 400

        if match_id is None or not selection:
            return jsonify({
                "error": (
                    "invalid single bet payload"
                )
            }), 400

        try:
            match_id = int(match_id)

        except (TypeError, ValueError):
            return jsonify({
                "error": "invalid match_id"
            }), 400

        selections = [
            {
                "match_id": match_id,
                "selection": selection,
                "client_odds": data.get(
                    "client_odds"
                ),
                "team": team,
            }
        ]

    # --------------------------------------------------------
    # VALIDATE SELECTION ARRAY
    # --------------------------------------------------------

    if not isinstance(
        selections,
        list,
    ):
        return jsonify({
            "error": "selections must be a list"
        }), 400

    if not selections:
        return jsonify({
            "error": "no selections"
        }), 400

    if len(selections) > max_selections:
        return jsonify({
            "error": (
                f"too many selections "
                f"(max {max_selections})"
            )
        }), 400

    normalized_selections = []

    for item in selections:

        if not isinstance(item, dict):
            return jsonify({
                "error": (
                    "each selection must "
                    "be an object"
                )
            }), 400

        if "match_id" not in item:
            return jsonify({
                "error": "match_id required"
            }), 400

        try:
            item = dict(item)
            item["match_id"] = int(
                item["match_id"]
            )

        except (TypeError, ValueError):
            return jsonify({
                "error": (
                    "match_id must be integer"
                )
            }), 400

        if not item.get("selection"):
            return jsonify({
                "error": (
                    "selection is required"
                )
            }), 400

        normalized_selections.append(
            item
        )

    selections = normalized_selections

    # --------------------------------------------------------
    # DUPLICATE MATCH PROTECTION
    # --------------------------------------------------------

    seen = set()

    for item in selections:

        match_id = item["match_id"]

        if match_id in seen:
            return jsonify({
                "error": (
                    "duplicate match "
                    "in betslip"
                )
            }), 400

        seen.add(match_id)

    # --------------------------------------------------------
    # DATABASE TRANSACTION
    # --------------------------------------------------------

    try:

        with db.session.begin():

            # Lock user row so two simultaneous
            # bets cannot spend the same balance.
            user = (
                db.session.query(User)
                .with_for_update()
                .filter_by(id=uid)
                .first()
            )

            if not user:
                raise BetRequestError(
                    "user not found",
                    404,
                )

            balance = _money(
                user.balance
            )

            if balance < stake:
                raise BetRequestError(
                    "insufficient balance",
                    400,
                )

            if len(selections) == 1:

                response, status = (
                    _handle_single_bet(
                        user,
                        uid,
                        stake,
                        selections[0],
                        slippage,
                    )
                )

            else:

                response, status = (
                    _handle_accumulator_bet(
                        user,
                        uid,
                        stake,
                        selections,
                        slippage,
                    )
                )

            if (
                idempotency_key
                and status in (200, 201)
            ):
                _write_idempotency(
                    idempotency_key,
                    uid,
                    response,
                )

        return jsonify(
            response
        ), status

    except BetRequestError as exc:

        db.session.rollback()

        return jsonify({
            "error": exc.message
        }), exc.status

    except Exception:

        db.session.rollback()

        logger.exception(
            "Unexpected error placing bet "
            "for user=%s",
            uid,
        )

        return jsonify({
            "error": "internal server error"
        }), 500


# ============================================================
# MY BETS
# ============================================================

@bet_bp.route(
    "/my_bets",
    methods=["GET"],
)
@jwt_required()
def my_bets():

    try:
        uid = int(
            get_jwt_identity()
        )

    except (TypeError, ValueError):
        return jsonify({
            "error": "invalid user identity"
        }), 401

    try:
        page = max(
            int(
                request.args.get(
                    "page",
                    1,
                )
            ),
            1,
        )

    except (TypeError, ValueError):
        page = 1

    try:
        per_page = int(
            request.args.get(
                "per_page",
                20,
            )
        )

    except (TypeError, ValueError):
        per_page = 20

    per_page = max(
        1,
        min(per_page, 100),
    )

    pagination = (
        BetSlip.query
        .filter_by(user_id=uid)
        .order_by(
            BetSlip.created.desc()
        )
        .paginate(
            page=page,
            per_page=per_page,
            error_out=False,
        )
    )

    slips = list(
        pagination.items
    )

    slip_match_ids = []

    for slip in slips:

        for selection in (
            getattr(
                slip,
                "selections",
                []
            ) or []
        ):

            match_id = getattr(
                selection,
                "bookmark_id",
                None,
            )

            if match_id is not None:
                try:
                    slip_match_ids.append(
                        int(match_id)
                    )
                except (TypeError, ValueError):
                    pass

    # Legacy single bets.
    legacy_bets = (
        Bet.query
        .filter_by(user_id=uid)
        .order_by(
            Bet.created.desc()
        )
        .limit(50)
        .all()
    )

    legacy_match_ids = []

    for bet in legacy_bets:

        if getattr(
            bet,
            "match_id",
            None,
        ) is not None:

            try:
                legacy_match_ids.append(
                    int(bet.match_id)
                )
            except (TypeError, ValueError):
                pass

    match_scores = _fetch_match_scores(
        slip_match_ids
        + legacy_match_ids
    )

    # --------------------------------------------------------
    # BETSLIPS
    # --------------------------------------------------------

    slips_out = []

    for slip in slips:

        selection_list = []

        for selection in (
            getattr(
                slip,
                "selections",
                []
            ) or []
        ):

            match_id = getattr(
                selection,
                "bookmark_id",
                None,
            )

            try:
                match_id = (
                    int(match_id)
                    if match_id is not None
                    else None
                )
            except (TypeError, ValueError):
                match_id = None

            selection_list.append({
                "id": selection.id,
                "bookmark_id": selection.bookmark_id,
                "selection": selection.selection,
                "odds": str(
                    _d(selection.odds)
                ),
                "status": selection.status,
                "league": selection.league,
                "home_team": selection.home_team,
                "away_team": selection.away_team,
                "match_time": (
                    selection.match_time.isoformat()
                    if selection.match_time
                    else None
                ),
                "score": match_scores.get(
                    match_id
                ),
            })

        slip_data = {
            "id": slip.id,
            "stake": str(
                _d(slip.stake)
            ),
            "total_odds": str(
                _d(slip.total_odds)
            ),
            "potential": str(
                _d(slip.potential)
            ),
            "status": slip.status,
            "selections": selection_list,
            "cashout_id": getattr(
                slip,
                "cashout_tx_id",
                None,
            ),
            "type": "betslip",
            "created": (
                slip.created.isoformat()
                if getattr(
                    slip,
                    "created",
                    None,
                )
                else None
            ),
        }

        if (
            (slip.status or "").lower()
            == "pending"
        ):
            slip_data[
                "current_cashout"
            ] = str(
                _cashout_amount_for_betslip(
                    slip
                )
            )

        slips_out.append(
            slip_data
        )

    # --------------------------------------------------------
    # LEGACY SINGLE BETS
    # --------------------------------------------------------

    legacy_out = []

    for bet in legacy_bets:

        match_id = getattr(
            bet,
            "match_id",
            None,
        )

        try:
            score_match_id = (
                int(match_id)
                if match_id is not None
                else None
            )
        except (TypeError, ValueError):
            score_match_id = None

        bet_data = {
            "id": bet.id,
            "match_id": bet.match_id,
            "selection": bet.selection,
            "odds": str(
                _d(bet.odds)
            ),
            "amount": str(
                _d(bet.amount)
            ),
            "potential": str(
                _d(bet.potential)
            ),
            "status": bet.status,
            "type": "single_bet",
            "created": (
                bet.created.isoformat()
                if getattr(
                    bet,
                    "created",
                    None,
                )
                else None
            ),
            "score": match_scores.get(
                score_match_id
            ),
        }

        if (
            (bet.status or "").lower()
            == "pending"
        ):
            bet_data[
                "current_cashout"
            ] = str(
                _cashout_amount_for_legacy_bet(
                    bet
                )
            )

        legacy_out.append(
            bet_data
        )

    return jsonify({
        "page": page,
        "per_page": per_page,
        "total_betslips": pagination.total,
        "betslips": slips_out,
        "single_bets": legacy_out,
    })


# ============================================================
# CASHOUT
# ============================================================

@bet_bp.route(
    "/cashout/<int:bet_id>",
    methods=["POST"],
)
@jwt_required()
def cashout(bet_id):

    try:
        uid = int(
            get_jwt_identity()
        )

    except (TypeError, ValueError):
        return jsonify({
            "error": "invalid user identity"
        }), 401

    try:

        with db.session.begin():

            # ------------------------------------------------
            # TRY BETSLIP FIRST
            # ------------------------------------------------

            slip = (
                db.session.query(BetSlip)
                .with_for_update()
                .filter_by(id=bet_id)
                .first()
            )

            if slip:

                if int(slip.user_id) != int(uid):
                    raise BetRequestError(
                        "bet not found",
                        404,
                    )

                status = (
                    slip.status or ""
                ).lower()

                if (
                    getattr(
                        slip,
                        "cashed_out",
                        False,
                    )
                    or status != "pending"
                ):
                    raise BetRequestError(
                        "cannot cashout",
                        400,
                    )
                # ------------------------------------------------
                # FINAL SERVER-SIDE VALIDATION
                # ------------------------------------------------

                valid, reason = _validate_betslip_cashout(
                    slip
                )

                if not valid:

                    slip.current_cashout = (
                        Decimal("0.00")
                    )

                    db.session.add(slip)

                    raise BetRequestError(
                        "cashout unavailable: " + reason,
                        400,
                    )

                user = (
                    db.session.query(User)
                    .with_for_update()
                    .filter_by(id=uid)
                    .first()
                )

                if not user:
                    raise BetRequestError(
                        "user not found",
                        404,
                    )

                amount = (
                    _cashout_amount_for_betslip(
                        slip
                    )
                )

                if amount <= 0:
                    raise BetRequestError(
                        "cashout unavailable",
                        400,
                    )

                slip.cashed_out = True
                slip.status = "cashed_out"
                slip.current_cashout = amount

                user.balance = _money(
                    _d(user.balance)
                    + amount
                )

                transaction = Transaction(
                    user_id=uid,
                    type="cashout",
                    amount=amount,
                    balance_after=user.balance,
                    created=_now_utc(),
                )

                db.session.add(
                    transaction
                )

                _debit_house(
                    amount,
                    reference=f"cashout:slip:{slip.id}",
                    description="Normal football accumulator cashout",
                    transaction_type="cashout",
                )

                db.session.flush()

                slip.cashout_tx_id = (
                    transaction.id
                )

                return jsonify({
                    "msg": "cashed out",
                    "amount": str(amount),
                    "balance": str(
                        user.balance
                    ),
                    "cashout_id": (
                        transaction.id
                    ),
                    "created": (
                        transaction.created.isoformat()
                    ),
                })

            # ------------------------------------------------
            # LEGACY SINGLE BET
            # ------------------------------------------------

            bet = (
                db.session.query(Bet)
                .with_for_update()
                .filter_by(id=bet_id)
                .first()
            )

            if not bet:
                raise BetRequestError(
                    "bet not found",
                    404,
                )

            if int(bet.user_id) != int(uid):
                raise BetRequestError(
                    "bet not found",
                    404,
                )

            status = (
                bet.status or ""
            ).lower()

            if (
                getattr(
                    bet,
                    "cashed_out",
                    False,
                )
                or status != "pending"
            ):
                raise BetRequestError(
                    "cannot cashout",
                    400,
                )

            user = (
                db.session.query(User)
                .with_for_update()
                .filter_by(id=uid)
                .first()
            )

            if not user:
                raise BetRequestError(
                    "user not found",
                    404,
                )

            amount = (
                _cashout_amount_for_legacy_bet(
                    bet
                )
            )

            if amount <= 0:
                raise BetRequestError(
                    "cashout unavailable",
                    400,
                )

            bet.cashed_out = True
            bet.status = "cashed_out"
            bet.current_cashout = amount

            user.balance = _money(
                _d(user.balance)
                + amount
            )

            transaction = Transaction(
                user_id=uid,
                type="cashout",
                amount=amount,
                balance_after=user.balance,
                created=_now_utc(),
            )

            db.session.add(
                transaction
            )

            _debit_house(
                amount,
                reference=f"cashout:bet:{bet.id}",
                description="Normal football single bet cashout",
                transaction_type="cashout",
            )

            db.session.flush()

            bet.cashout_tx_id = (
                transaction.id
            )

            return jsonify({
                "msg": "cashed out",
                "amount": str(amount),
                "balance": str(
                    user.balance
                ),
                "cashout_id": (
                    transaction.id
                ),
                "created": (
                    transaction.created.isoformat()
                ),
            })

    except BetRequestError as exc:

        db.session.rollback()

        return jsonify({
            "error": exc.message
        }), exc.status

    except Exception:

        db.session.rollback()

        logger.exception(
            "Cashout failed "
            "user=%s bet_id=%s",
            uid,
            bet_id,
        )

        return jsonify({
            "error": "internal server error"
        }), 500


# ============================================================
# PROFIT HISTORY
# ============================================================

@bet_bp.route(
    "/profit_history",
    methods=["GET"],
)
@jwt_required()
def profit_history():

    try:
        uid = int(
            get_jwt_identity()
        )

    except (TypeError, ValueError):
        return jsonify({
            "error": "invalid user identity"
        }), 401

    try:
        page = max(
            int(
                request.args.get(
                    "page",
                    1,
                )
            ),
            1,
        )

    except (TypeError, ValueError):
        page = 1

    try:
        per_page = int(
            request.args.get(
                "per_page",
                50,
            )
        )

    except (TypeError, ValueError):
        per_page = 50

    per_page = max(
        1,
        min(per_page, 200),
    )

    try:

        singles = (
            Bet.query
            .filter_by(user_id=uid)
            .order_by(
                Bet.created.desc()
            )
            .all()
        )

        slips = (
            BetSlip.query
            .filter_by(user_id=uid)
            .order_by(
                BetSlip.created.desc()
            )
            .all()
        )

        entries = []

        # ----------------------------------------------------
        # SINGLE BETS
        # ----------------------------------------------------

        for bet in singles:

            status = (
                bet.status or ""
            ).lower()

            stake = _d(
                bet.amount
            )

            payout = _d(
                bet.potential
            )

            cashout = (
                _cashout_amount_for_legacy_bet(
                    bet
                )
            )

            if status == "won":
                profit = payout - stake

            elif status == "lost":
                profit = -stake

            elif status == "cashed_out":
                profit = cashout - stake

            else:
                profit = Decimal("0.00")

            entries.append({
                "type": "single_bet",
                "id": bet.id,
                "match_id": bet.match_id,
                "selection": bet.selection,
                "stake": str(
                    _money(stake)
                ),
                "potential": str(
                    _money(payout)
                ),
                "status": bet.status,
                "profit": str(
                    _money(profit)
                ),
                "current_cashout": str(
                    cashout
                ),
                "created": (
                    bet.created.isoformat()
                    if bet.created
                    else None
                ),
            })

        # ----------------------------------------------------
        # BETSLIPS
        # ----------------------------------------------------

        for slip in slips:

            status = (
                slip.status or ""
            ).lower()

            stake = _d(
                slip.stake
            )

            payout = _d(
                slip.potential
            )

            cashout = (
                _cashout_amount_for_betslip(
                    slip
                )
            )

            if status == "won":
                profit = payout - stake

            elif status == "lost":
                profit = -stake

            elif status == "cashed_out":
                profit = cashout - stake

            else:
                profit = Decimal("0.00")

            entries.append({
                "type": "betslip",
                "id": slip.id,
                "match_id": slip.match_id,
                "stake": str(
                    _money(stake)
                ),
                "potential": str(
                    _money(payout)
                ),
                "status": slip.status,
                "profit": str(
                    _money(profit)
                ),
                "current_cashout": str(
                    cashout
                ),
                "created": (
                    slip.created.isoformat()
                    if slip.created
                    else None
                ),
            })

        entries.sort(
            key=lambda item:
                item.get("created") or "",
            reverse=True,
        )

        # ----------------------------------------------------
        # TOTALS
        # ----------------------------------------------------

        total_stake = Decimal("0.00")
        realized_profit = Decimal("0.00")

        for entry in entries:

            stake = _d(
                entry["stake"]
            )

            profit = _d(
                entry["profit"]
            )

            total_stake += stake

            status = (
                entry["status"] or ""
            ).lower()

            if status in {
                "won",
                "lost",
                "cashed_out",
            }:
                realized_profit += profit

        total = len(entries)

        start = (
            (page - 1)
            * per_page
        )

        end = start + per_page

        page_entries = entries[
            start:end
        ]

        return jsonify({
            "page": page,
            "per_page": per_page,
            "total_records": total,
            "realized_profit": str(
                _money(realized_profit)
            ),
            "total_stake": str(
                _money(total_stake)
            ),
            "entries": page_entries,
        })

    except Exception:

        logger.exception(
            "Error fetching profit history "
            "for user=%s",
            uid,
        )

        return jsonify({
            "error": "internal server error"
        }), 500


# ============================================================
# BETTING STATS
# ============================================================

@bet_bp.route(
    "/stats",
    methods=["GET"],
)
@jwt_required()
def stats():

    try:
        uid = int(
            get_jwt_identity()
        )

    except (TypeError, ValueError):
        return jsonify({
            "error": "invalid user identity"
        }), 401

    try:

        single_bets = (
            Bet.query
            .filter_by(user_id=uid)
            .all()
        )

        slips = (
            BetSlip.query
            .filter_by(user_id=uid)
            .all()
        )

        total_bets = (
            len(single_bets)
            + len(slips)
        )

        total_stake = Decimal("0.00")
        total_potential = Decimal("0.00")
        total_won = Decimal("0.00")
        total_lost = Decimal("0.00")
        total_pending = Decimal("0.00")
        total_cashed_out = Decimal("0.00")

        odds_sum = Decimal("0.00")
        odds_count = 0

        win_count = 0
        loss_count = 0
        pending_count = 0
        cashed_out_count = 0

        # ----------------------------------------------------
        # SINGLE BETS
        # ----------------------------------------------------

        for bet in single_bets:

            status = (
                bet.status or ""
            ).lower()

            stake = _d(
                bet.amount
            )

            potential = _d(
                bet.potential
            )

            odds = _d(
                bet.odds
            )

            total_stake += stake
            total_potential += potential

            if odds > 0:
                odds_sum += odds
                odds_count += 1

            if status == "won":

                win_count += 1

                total_won += (
                    potential - stake
                )

            elif status == "lost":

                loss_count += 1

                total_lost += stake

            elif status == "cashed_out":

                cashed_out_count += 1

                total_cashed_out += (
                    _cashout_amount_for_legacy_bet(
                        bet
                    )
                    - stake
                )

            else:

                pending_count += 1

                total_pending += stake

        # ----------------------------------------------------
        # BETSLIPS
        # ----------------------------------------------------

        for slip in slips:

            status = (
                slip.status or ""
            ).lower()

            stake = _d(
                slip.stake
            )

            potential = _d(
                slip.potential
            )

            odds = _d(
                slip.total_odds
            )

            total_stake += stake
            total_potential += potential

            if odds > 0:
                odds_sum += odds
                odds_count += 1

            if status == "won":

                win_count += 1

                total_won += (
                    potential - stake
                )

            elif status == "lost":

                loss_count += 1

                total_lost += stake

            elif status == "cashed_out":

                cashed_out_count += 1

                total_cashed_out += (
                    _cashout_amount_for_betslip(
                        slip
                    )
                    - stake
                )

            else:

                pending_count += 1

                total_pending += stake

        # ----------------------------------------------------
        # CALCULATIONS
        # ----------------------------------------------------

        settled_count = (
            win_count
            + loss_count
            + cashed_out_count
        )

        if odds_count:
            average_odds = (
                odds_sum
                / Decimal(odds_count)
            )

        else:
            average_odds = Decimal(
                "0.00"
            )

        net_profit = (
            total_won
            + total_cashed_out
            - total_lost
        )

        if settled_count:

            win_rate = (
                Decimal(win_count)
                / Decimal(settled_count)
                * Decimal("100")
            )

        else:
            win_rate = Decimal(
                "0.00"
            )

        return jsonify({
            "total_bets": total_bets,

            "single_bets": len(
                single_bets
            ),

            "betslips": len(
                slips
            ),

            "settled_bets": settled_count,

            "pending_bets": pending_count,

            "won_bets": win_count,

            "lost_bets": loss_count,

            "cashed_out_bets": (
                cashed_out_count
            ),

            "total_stake": str(
                _money(total_stake)
            ),

            "total_potential": str(
                _money(total_potential)
            ),

            "total_pending_stake": str(
                _money(total_pending)
            ),

            "net_profit": str(
                _money(net_profit)
            ),

            "average_odds": str(
                _money(average_odds)
            ),

            "win_rate_percent": str(
                _money(win_rate)
            ),
        })

    except Exception:

        logger.exception(
            "Error fetching betting stats "
            "for user=%s",
            uid,
        )

        return jsonify({
            "error": "internal server error"
        }), 500
