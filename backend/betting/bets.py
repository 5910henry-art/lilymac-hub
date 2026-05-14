# bets.py
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, InvalidOperation

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import text, func

from betting.models import db, User, Bookmark, BetSlip, BetSelection, Bet, Transaction, Match
from betting.utils import to_decimal

logger = logging.getLogger(__name__)
bet_bp = Blueprint("bets", __name__)

DEFAULTS = {
    "MAX_STAKE": Decimal("10000.00"),
    "MAX_SELECTIONS": 10,
    "ODDS_SLIPPAGE": Decimal("0.02"),
    "IDEMPOTENCY_TABLE": "idempotency_records",
}


class BetRequestError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _now_utc():
    return datetime.now(timezone.utc)


def _d(value, fallback=Decimal("0.00")):
    try:
        return to_decimal(value)
    except Exception:
        return fallback


def _get_config_decimal(key: str) -> Decimal:
    val = current_app.config.get(key, DEFAULTS[key])
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return DEFAULTS[key]


def _normalize_selection(selection, team, bookmark):
    """
    Real-football selection normalizer.

    Supports:
      - 1 / X / 2
      - home / away / draw
      - home_odds / away_odds / draw_odds
      - over05 / under05 / over15 / under15 / over25 / under25 / over35 / under35
      - btts_yes / btts_no / gg / ng
      - team name mapped to home/away odds
    """
    sel = (selection or "").strip().lower().replace(" ", "_")

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

    if team and bookmark:
        team = str(team).strip()
        if team == bookmark.home_team:
            return "home_odds"
        if team == bookmark.away_team:
            return "away_odds"

    return sel


def _ensure_idempotency_table():
    tbl = current_app.config.get("IDEMPOTENCY_TABLE", DEFAULTS["IDEMPOTENCY_TABLE"])
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS {tbl} (
        key TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        response_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    try:
        db.session.execute(text(create_sql))
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to ensure idempotency table exists")


def _read_idempotency(key, user_id):
    tbl = current_app.config.get("IDEMPOTENCY_TABLE", DEFAULTS["IDEMPOTENCY_TABLE"])
    select_sql = f"SELECT response_json FROM {tbl} WHERE key = :k AND user_id = :uid"
    try:
        res = db.session.execute(text(select_sql), {"k": key, "uid": user_id}).fetchone()
        if res:
            return json.loads(res[0])
    except Exception:
        logger.exception("Error reading idempotency record")
    return None


def _write_idempotency(key, user_id, payload):
    tbl = current_app.config.get("IDEMPOTENCY_TABLE", DEFAULTS["IDEMPOTENCY_TABLE"])
    dialect = None
    try:
        dialect = db.session.bind.dialect.name if db.session.bind is not None else None
    except Exception:
        dialect = None

    payload_json = json.dumps(payload)

    if dialect == "postgresql":
        insert_sql = f"""
        INSERT INTO {tbl} (key, user_id, response_json)
        VALUES (:k, :uid, :r)
        ON CONFLICT (key) DO NOTHING
        """
    elif dialect == "sqlite":
        insert_sql = f"""
        INSERT OR IGNORE INTO {tbl} (key, user_id, response_json)
        VALUES (:k, :uid, :r)
        """
    else:
        insert_sql = f"""
        INSERT INTO {tbl} (key, user_id, response_json)
        SELECT :k, :uid, :r
        WHERE NOT EXISTS (
            SELECT 1 FROM {tbl} WHERE key = :k AND user_id = :uid
        )
        """

    try:
        db.session.execute(text(insert_sql), {"k": key, "uid": user_id, "r": payload_json})
    except Exception:
        logger.exception("Error writing idempotency record")


def _get_bookmark_by_match_id(match_id):
    try:
        mid = int(match_id)
    except Exception:
        return None

    try:
        return db.session.query(Bookmark).filter_by(match_id=mid).first()
    except Exception:
        logger.exception("Error querying Bookmark for match_id=%s", mid)
        return None


def _match_has_started(bookmark):
    if not bookmark or not getattr(bookmark, "match_time", None):
        return False

    match_time = bookmark.match_time
    try:
        if match_time.tzinfo is None:
            match_time = match_time.replace(tzinfo=timezone.utc)
        return match_time <= _now_utc()
    except Exception:
        return False


def _client_odds_validate(bookmark, selection, client_odds, slippage):
    odds_val = getattr(bookmark, selection, None)
    if odds_val is None:
        return None, False, f"invalid selection: {selection}"

    odds = _d(odds_val)

    if client_odds is None:
        return odds, True, ""

    try:
        client_o = _d(client_odds)
    except Exception:
        return None, False, "client odds not a valid number"

    if odds <= 0:
        return None, False, "live odds are invalid"

    diff = abs(odds - client_o) / odds
    if diff > slippage:
        return odds, False, f"odds changed (live={odds}, client={client_o})"

    return odds, True, ""


def _assign_betslip_match_id(betslip, selections):
    if getattr(betslip, "match_id", None):
        return
    if selections:
        betslip.match_id = selections[0].get("match_id")


def _pending_cashout_amount(stake):
    return (_d(stake) * Decimal("0.95")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _cashout_amount_for_betslip(slip):
    status = (getattr(slip, "status", "") or "").lower()

    if status == "lost":
        return Decimal("0.00")

    if status == "pending":
        return _pending_cashout_amount(slip.stake)

    stored = getattr(slip, "current_cashout", None)
    if stored is None:
        return Decimal("0.00")

    try:
        amount = _d(stored)
    except Exception:
        return Decimal("0.00")

    if amount <= 0:
        return Decimal("0.00")

    return amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _cashout_amount_for_legacy_bet(bet):
    status = (getattr(bet, "status", "") or "").lower()

    if status == "lost":
        return Decimal("0.00")

    if status == "pending":
        return _pending_cashout_amount(bet.amount)

    stored = getattr(bet, "current_cashout", None)
    if stored is None:
        return Decimal("0.00")

    try:
        amount = _d(stored)
    except Exception:
        return Decimal("0.00")

    if amount <= 0:
        return Decimal("0.00")

    return amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _fetch_match_scores(match_ids):
    """
    Returns {match_id: "home-away" or None}
    """
    match_ids = [int(x) for x in set(match_ids) if x is not None]
    if not match_ids:
        return {}

    scores = {}
    try:
        rows = db.session.query(Match.id, Match.home_score, Match.away_score).filter(
            Match.id.in_(match_ids)
        ).all()

        for row in rows:
            mid = int(row[0])
            home_score = row[1]
            away_score = row[2]
            if home_score is not None and away_score is not None:
                scores[mid] = f"{home_score}-{away_score}"
            else:
                scores[mid] = None
    except Exception:
        logger.exception("Error fetching match scores")

    return scores


def _resolve_selection_payload(s, bookmark):
    selection = s.get("selection")
    team = s.get("team")
    client_odds = s.get("client_odds")
    normalized = _normalize_selection(selection, team, bookmark)
    return normalized, client_odds


def _handle_single_bet(user, uid, stake, s, slippage):
    now = _now_utc()
    match_id = s.get("match_id")
    selection = s.get("selection")
    team = s.get("team")
    client_odds = s.get("client_odds")

    if match_id is None or selection is None:
        raise BetRequestError("invalid single bet payload", 400)

    try:
        match_id_int = int(match_id)
    except Exception:
        raise BetRequestError("invalid match_id", 400)

    bookmark = _get_bookmark_by_match_id(match_id_int)
    if not bookmark:
        raise BetRequestError(f"match {match_id_int} not found", 404)

    if _match_has_started(bookmark):
        raise BetRequestError("match already started", 400)

    selection = _normalize_selection(selection, team, bookmark)

    odds, ok, msg = _client_odds_validate(bookmark, selection, client_odds, slippage)
    if not ok:
        raise BetRequestError(msg, 400)

    potential = (stake * odds).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    bet = Bet(
        user_id=uid,
        match_id=match_id_int,
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

    user.balance = _d(user.balance) - stake
    tx = Transaction(
        user_id=uid,
        type="bet",
        amount=stake,
        balance_after=_d(user.balance),
        created=now,
    )
    db.session.add(tx)
    db.session.flush()

    response = {
        "msg": "single bet placed",
        "bet_id": bet.id,
        "stake": str(stake),
        "odds": str(odds),
        "potential_win": str(potential),
        "type": "single",
        "created": now.isoformat(),
    }
    return response, 201


def _handle_accumulator_bet(user, uid, stake, selections, slippage):
    now = _now_utc()
    total_odds = Decimal("1.00")
    validated = []

    for s in selections:
        match_id = s.get("match_id")
        selection = s.get("selection")
        team = s.get("team")
        client_odds = s.get("client_odds")

        if match_id is None or selection is None:
            raise BetRequestError("invalid selection payload", 400)

        try:
            match_id_int = int(match_id)
        except Exception:
            raise BetRequestError("invalid selection payload; match_id must be integer", 400)

        bookmark = _get_bookmark_by_match_id(match_id_int)
        if not bookmark:
            raise BetRequestError(f"match {match_id_int} not found", 404)

        if _match_has_started(bookmark):
            raise BetRequestError(f"match {match_id_int} already started", 400)

        selection = _normalize_selection(selection, team, bookmark)

        odds, ok, msg = _client_odds_validate(bookmark, selection, client_odds, slippage)
        if not ok:
            raise BetRequestError(f"match {match_id_int}: {msg}", 400)

        validated.append(
            {
                "match_id": match_id_int,
                "bookmark": bookmark,
                "selection": selection,
                "odds": odds,
            }
        )
        total_odds = (total_odds * odds).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)

    if not validated:
        raise BetRequestError("no selections", 400)

    betslip = BetSlip(
        user_id=uid,
        stake=stake,
        total_odds=total_odds,
        potential=Decimal("0.00"),
        current_cashout=Decimal("0.00"),
        status="pending",
        match_id=validated[0]["match_id"],
        created=now,
    )
    db.session.add(betslip)
    db.session.flush()

    for item in validated:
        bookmark = item["bookmark"]
        sel = BetSelection(
            betslip_id=betslip.id,
            bookmark_id=item["match_id"],
            selection=item["selection"],
            odds=item["odds"],
            league=bookmark.league,
            home_team=bookmark.home_team,
            away_team=bookmark.away_team,
            match_time=bookmark.match_time,
            created=now,
        )
        db.session.add(sel)

    potential = (stake * total_odds).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    betslip.total_odds = total_odds
    betslip.potential = potential
    _assign_betslip_match_id(betslip, validated)

    user.balance = _d(user.balance) - stake
    tx = Transaction(
        user_id=uid,
        type="bet",
        amount=stake,
        balance_after=_d(user.balance),
        created=now,
    )
    db.session.add(tx)
    db.session.flush()

    response = {
        "msg": "accumulator bet placed",
        "betslip_id": betslip.id,
        "stake": str(stake),
        "total_odds": str(total_odds),
        "potential_win": str(potential),
        "selections": len(validated),
        "type": "accumulator",
        "created": now.isoformat(),
    }
    return response, 201


@bet_bp.route("/place_bet", methods=["POST"])
@jwt_required()
def place_bet():
    uid = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    max_stake = _get_config_decimal("MAX_STAKE")
    max_selections = int(current_app.config.get("MAX_SELECTIONS", DEFAULTS["MAX_SELECTIONS"]))
    slippage = _get_config_decimal("ODDS_SLIPPAGE")

    idempotency_key = request.headers.get("Idempotency-Key") or data.get("idempotency_key")
    if idempotency_key:
        _ensure_idempotency_table()
        prev = _read_idempotency(idempotency_key, uid)
        if prev is not None:
            return jsonify(prev), 200

    try:
        stake = _d(data.get("stake", 0))
    except Exception:
        return jsonify({"error": "invalid stake format"}), 400

    selections = data.get("selections")

    if not selections:
        match_id = data.get("match_id")
        selection = data.get("selection")
        team = data.get("team")

        if team and not selection:
            if match_id is None:
                return jsonify({"error": "match_id required when using team field"}), 400
            bookmark = _get_bookmark_by_match_id(match_id)
            if not bookmark:
                return jsonify({"error": "match not found"}), 404
            if team == bookmark.home_team:
                selection = "home_odds"
            elif team == bookmark.away_team:
                selection = "away_odds"
            else:
                return jsonify({"error": "invalid team"}), 400

        if match_id is None or not selection:
            return jsonify({"error": "invalid single bet payload"}), 400

        try:
            match_id_int = int(match_id)
        except Exception:
            return jsonify({"error": "invalid match_id"}), 400

        selections = [
            {
                "match_id": match_id_int,
                "selection": selection,
                "client_odds": data.get("client_odds"),
                "team": team,
            }
        ]

    if stake <= 0:
        return jsonify({"error": "invalid stake"}), 400

    if stake > max_stake:
        return jsonify({"error": f"stake exceeds maximum limit ({max_stake})"}), 400

    if not isinstance(selections, list) or len(selections) == 0:
        return jsonify({"error": "no selections"}), 400

    if len(selections) > max_selections:
        return jsonify({"error": f"too many selections (max {max_selections})"}), 400

    try:
        for s in selections:
            if "match_id" not in s:
                raise ValueError("invalid selection payload")
            s["match_id"] = int(s.get("match_id"))
    except Exception:
        return jsonify({"error": "invalid selection payload; match_id must be integer"}), 400

    seen = set()
    for s in selections:
        mid = s.get("match_id")
        if mid in seen:
            return jsonify({"error": "duplicate match in betslip"}), 400
        seen.add(mid)

    try:
        with db.session.begin():
            user = db.session.query(User).with_for_update().filter_by(id=uid).first()
            if not user:
                raise BetRequestError("user not found", 404)

            if _d(user.balance) < stake:
                raise BetRequestError("insufficient balance", 400)

            if len(selections) == 1:
                resp, status = _handle_single_bet(user, uid, stake, selections[0], slippage)
            else:
                resp, status = _handle_accumulator_bet(user, uid, stake, selections, slippage)

            if idempotency_key and status in (200, 201):
                _write_idempotency(idempotency_key, uid, resp)

        return jsonify(resp), status

    except BetRequestError as e:
        db.session.rollback()
        return jsonify({"error": e.message}), e.status

    except Exception:
        db.session.rollback()
        logger.exception("unexpected error in place_bet for user=%s", uid)
        return jsonify({"error": "internal server error"}), 500


@bet_bp.route("/my_bets")
@jwt_required()
def my_bets():
    uid = int(get_jwt_identity())
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)

    pagination = BetSlip.query.filter_by(user_id=uid).order_by(BetSlip.created.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    slips = list(pagination.items)
    slip_match_ids = []
    for slip in slips:
        for s in getattr(slip, "selections", []) or []:
            if getattr(s, "bookmark_id", None) is not None:
                slip_match_ids.append(int(s.bookmark_id))

    legacy_bets = Bet.query.filter_by(user_id=uid).order_by(Bet.created.desc()).limit(50).all()
    legacy_match_ids = [
        int(b.match_id)
        for b in legacy_bets
        if getattr(b, "match_id", None) is not None
    ]

    match_scores = _fetch_match_scores(slip_match_ids + legacy_match_ids)

    slips_out = []
    for slip in slips:
        sel_list = []
        for s in slip.selections:
            mid = int(s.bookmark_id) if getattr(s, "bookmark_id", None) is not None else None
            sel_list.append(
                {
                    "id": s.id,
                    "bookmark_id": s.bookmark_id,
                    "selection": s.selection,
                    "odds": str(_d(s.odds)),
                    "status": s.status,
                    "league": s.league,
                    "home_team": s.home_team,
                    "away_team": s.away_team,
                    "match_time": s.match_time.isoformat() if s.match_time else None,
                    "score": match_scores.get(mid),
                }
            )

        slip_data = {
            "id": slip.id,
            "stake": str(_d(slip.stake)),
            "total_odds": str(_d(slip.total_odds)),
            "potential": str(_d(slip.potential)),
            "status": slip.status,
            "selections": sel_list,
            "cashout_id": slip.cashout_tx_id,
            "type": "betslip",
            "created": slip.created.isoformat() if getattr(slip, "created", None) else None,
        }

        if (slip.status or "").lower() == "pending":
            slip_data["current_cashout"] = str(_cashout_amount_for_betslip(slip))

        slips_out.append(slip_data)

    legacy_out = []
    for b in legacy_bets:
        bet_data = {
            "id": b.id,
            "match_id": b.match_id,
            "selection": b.selection,
            "odds": str(_d(b.odds)),
            "amount": str(_d(b.amount)),
            "potential": str(_d(b.potential)),
            "status": b.status,
            "type": "single_bet",
            "created": b.created.isoformat() if getattr(b, "created", None) else None,
            "score": match_scores.get(int(b.match_id)) if getattr(b, "match_id", None) is not None else None,
        }

        if (b.status or "").lower() == "pending":
            bet_data["current_cashout"] = str(_cashout_amount_for_legacy_bet(b))

        legacy_out.append(bet_data)

    return jsonify(
        {
            "page": page,
            "per_page": per_page,
            "total_betslips": pagination.total,
            "betslips": slips_out,
            "single_bets": legacy_out,
        }
    )


@bet_bp.route("/cashout/<int:bet_id>", methods=["POST"])
@jwt_required()
def cashout(bet_id):
    uid = int(get_jwt_identity())

    try:
        with db.session.begin():
            slip = db.session.query(BetSlip).with_for_update().filter_by(id=bet_id).first()

            if not slip:
                bet = db.session.query(Bet).with_for_update().filter_by(id=bet_id).first()
                if not bet or int(bet.user_id) != int(uid):
                    return jsonify({"error": "bet not found"}), 404

                if bet.cashed_out or (bet.status or "").lower() != "pending":
                    return jsonify({"error": "cannot cashout"}), 400

                user = db.session.query(User).with_for_update().filter_by(id=uid).first()
                amount = _cashout_amount_for_legacy_bet(bet)

                if amount <= 0:
                    return jsonify({"error": "cashout unavailable"}), 400

                bet.cashed_out = True
                bet.status = "cashed_out"
                user.balance = _d(user.balance) + amount

                tx = Transaction(
                    user_id=uid,
                    type="cashout",
                    amount=amount,
                    balance_after=_d(user.balance),
                    created=_now_utc(),
                )
                db.session.add(tx)
                db.session.flush()
                bet.cashout_tx_id = tx.id
                db.session.add(bet)

                return jsonify(
                    {
                        "msg": "cashed out",
                        "amount": str(amount),
                        "balance": str(_d(user.balance)),
                        "cashout_id": tx.id,
                        "created": tx.created.isoformat(),
                    }
                )

            if slip.user_id != int(uid):
                return jsonify({"error": "bet not found"}), 404

            if slip.cashed_out or (slip.status or "").lower() != "pending":
                return jsonify({"error": "cannot cashout"}), 400

            user = db.session.query(User).with_for_update().filter_by(id=uid).first()
            amount = _cashout_amount_for_betslip(slip)

            if amount <= 0:
                return jsonify({"error": "cashout unavailable"}), 400

            slip.cashed_out = True
            slip.status = "cashed_out"
            user.balance = _d(user.balance) + amount

            tx = Transaction(
                user_id=uid,
                type="cashout",
                amount=amount,
                balance_after=_d(user.balance),
                created=_now_utc(),
            )
            db.session.add(tx)
            db.session.flush()
            slip.cashout_tx_id = tx.id
            slip.current_cashout = amount
            db.session.add(slip)

            return jsonify(
                {
                    "msg": "cashed out",
                    "amount": str(amount),
                    "balance": str(_d(user.balance)),
                    "cashout_id": tx.id,
                    "created": tx.created.isoformat(),
                }
            )

    except Exception:
        db.session.rollback()
        logger.exception("cashout failed for user=%s bet_id=%s", uid, bet_id)
        return jsonify({"error": "internal server error"}), 500


@bet_bp.route("/profit_history", methods=["GET"])
@jwt_required()
def profit_history():
    """
    Returns realized/unrealized profit history across singles and slips.
    Profit convention:
      won      -> payout - stake
      lost     -> -stake
      pending  -> 0
      cashed_out -> cashout_amount - stake
    """
    uid = int(get_jwt_identity())
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 200)

    try:
        singles = Bet.query.filter_by(user_id=uid).order_by(Bet.created.desc()).all()
        slips = BetSlip.query.filter_by(user_id=uid).order_by(BetSlip.created.desc()).all()

        entries = []

        for b in singles:
            status = (b.status or "").lower()
            stake = _d(b.amount)
            payout = _d(b.potential)
            current_cashout = _cashout_amount_for_legacy_bet(b)

            if status == "won":
                profit = payout - stake
            elif status == "lost":
                profit = Decimal("0.00") - stake
            elif status == "cashed_out":
                profit = current_cashout - stake
            else:
                profit = Decimal("0.00")

            entries.append(
                {
                    "type": "single_bet",
                    "id": b.id,
                    "match_id": b.match_id,
                    "selection": b.selection,
                    "stake": str(stake),
                    "potential": str(payout),
                    "status": b.status,
                    "profit": str(profit.quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
                    "current_cashout": str(current_cashout),
                    "created": b.created.isoformat() if b.created else None,
                }
            )

        for s in slips:
            status = (s.status or "").lower()
            stake = _d(s.stake)
            payout = _d(s.potential)
            current_cashout = _cashout_amount_for_betslip(s)

            if status == "won":
                profit = payout - stake
            elif status == "lost":
                profit = Decimal("0.00") - stake
            elif status == "cashed_out":
                profit = current_cashout - stake
            else:
                profit = Decimal("0.00")

            entries.append(
                {
                    "type": "betslip",
                    "id": s.id,
                    "match_id": s.match_id,
                    "stake": str(stake),
                    "potential": str(payout),
                    "status": s.status,
                    "profit": str(profit.quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
                    "current_cashout": str(current_cashout),
                    "created": s.created.isoformat() if s.created else None,
                }
            )

        entries.sort(key=lambda x: x.get("created") or "", reverse=True)

        total = len(entries)
        start = max(0, (page - 1) * per_page)
        end = start + per_page
        page_entries = entries[start:end]

        realized_profit = Decimal("0.00")
        total_stake = Decimal("0.00")
        total_won = Decimal("0.00")
        total_lost = Decimal("0.00")

        for e in entries:
            profit = _d(e["profit"])
            stake = _d(e["stake"])
            total_stake += stake
            if (e["status"] or "").lower() == "won":
                total_won += profit
            elif (e["status"] or "").lower() == "lost":
                total_lost += stake
            elif (e["status"] or "").lower() == "cashed_out":
                realized_profit += profit
            elif (e["status"] or "").lower() == "pending":
                pass
            else:
                realized_profit += profit

        realized_profit = (total_won + realized_profit - total_lost).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

        return jsonify(
            {
                "page": page,
                "per_page": per_page,
                "total_records": total,
                "realized_profit": str(realized_profit),
                "total_stake": str(total_stake.quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
                "entries": page_entries,
            }
        )

    except Exception:
        logger.exception("Error fetching profit history for user=%s", uid)
        return jsonify({"error": "internal server error"}), 500


@bet_bp.route("/stats", methods=["GET"])
@jwt_required()
def stats():
    """
    Returns high-level betting stats for the user.
    """
    uid = int(get_jwt_identity())

    try:
        single_bets = Bet.query.filter_by(user_id=uid).all()
        slips = BetSlip.query.filter_by(user_id=uid).all()

        total_bets = len(single_bets) + len(slips)
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

        for b in single_bets:
            status = (b.status or "").lower()
            stake = _d(b.amount)
            potential = _d(b.potential)
            odds = _d(b.odds)

            total_stake += stake
            total_potential += potential

            if odds > 0:
                odds_sum += odds
                odds_count += 1

            if status == "won":
                win_count += 1
                total_won += (potential - stake)
            elif status == "lost":
                loss_count += 1
                total_lost += stake
            elif status == "cashed_out":
                cashed_out_count += 1
                total_cashed_out += (_cashout_amount_for_legacy_bet(b) - stake)
            else:
                pending_count += 1
                total_pending += stake

        for s in slips:
            status = (s.status or "").lower()
            stake = _d(s.stake)
            potential = _d(s.potential)
            odds = _d(s.total_odds)

            total_stake += stake
            total_potential += potential

            if odds > 0:
                odds_sum += odds
                odds_count += 1

            if status == "won":
                win_count += 1
                total_won += (potential - stake)
            elif status == "lost":
                loss_count += 1
                total_lost += stake
            elif status == "cashed_out":
                cashed_out_count += 1
                total_cashed_out += (_cashout_amount_for_betslip(s) - stake)
            else:
                pending_count += 1
                total_pending += stake

        settled_count = win_count + loss_count + cashed_out_count
        avg_odds = (odds_sum / odds_count).quantize(Decimal("0.01"), rounding=ROUND_DOWN) if odds_count else Decimal("0.00")

        net_profit = (total_won + total_cashed_out - total_lost).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        win_rate = (
            (Decimal(win_count) / Decimal(settled_count) * Decimal("100"))
            if settled_count > 0
            else Decimal("0.00")
        ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

        return jsonify(
            {
                "total_bets": total_bets,
                "single_bets": len(single_bets),
                "betslips": len(slips),
                "settled_bets": settled_count,
                "pending_bets": pending_count,
                "won_bets": win_count,
                "lost_bets": loss_count,
                "cashed_out_bets": cashed_out_count,
                "total_stake": str(total_stake.quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
                "total_potential": str(total_potential.quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
                "total_pending_stake": str(total_pending.quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
                "net_profit": str(net_profit),
                "average_odds": str(avg_odds),
                "win_rate_percent": str(win_rate),
            }
        )

    except Exception:
        logger.exception("Error fetching stats for user=%s", uid)
        return jsonify({"error": "internal server error"}), 500
