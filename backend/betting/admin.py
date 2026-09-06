# admin.py
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from betting.models import (
    db,
    User,
    Transaction,
    Match,
    HouseWallet,
    HouseTransaction,
    HouseMpesaWithdrawal,
    MpesaWithdrawal,
)
import logging

logger = logging.getLogger(__name__)
from betting.mpesa import (
    normalize_phone,
    b2c_payment,
)
def _money(value):
    try:
        return Decimal(str(value)).quantize(
            Decimal("0.01")
        )
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid monetary value")


def _reserved_house_withdrawals():
    """
    Amount currently reserved for B2C withdrawals
    that have not reached a final state.
    """
    rows = (
        db.session.query(HouseMpesaWithdrawal.amount)
        .filter(
            HouseMpesaWithdrawal.status.in_(
                [
                    "pending",
                    "submitted",
                    "processing",
                ]
            )
        )
        .all()
    )

    total = Decimal("0.00")

    for row in rows:
        total += _money(row[0])

    return total

def register_admin_routes(app):

    # -------------------------
    # Update match route
    # -------------------------
    @app.route("/admin/update-match", methods=["POST"])
    @jwt_required()
    def update_match():
        uid = int(get_jwt_identity())
        user = db.session.get(User, uid)
        if not user or not user.is_admin:
            return jsonify({"error": "forbidden"}), 403

        data = request.json or {}
        match = db.session.get(Match, data.get("match_id"))
        if not match:
            return jsonify({"error": "not found"}), 404

        home = data.get("home", match.home_score)
        away = data.get("away", match.away_score)

        # validation
        try:
            if int(home) < 0 or int(away) < 0:
                return jsonify({"error": "invalid score"}), 400
        except Exception:
            return jsonify({"error": "invalid score"}), 400

        match.home_score = home
        match.away_score = away
        match.status = data.get("status", match.status)

        db.session.commit()
        return jsonify({"msg": "updated"})


    # -------------------------
    # Create match route
    # -------------------------
    @app.route("/admin/create-match", methods=["POST"])
    @jwt_required()
    def create_match():
        uid = int(get_jwt_identity())
        user = db.session.get(User, uid)
        if not user or not user.is_admin:
            return jsonify({"error": "forbidden"}), 403

        data = request.json or {}
        team_a = data.get("team_a")
        team_b = data.get("team_b")
        if not team_a or not team_b:
            return jsonify({"error": "team_a and team_b required"}), 400

        # Use proper field names from your model
        match = Match(home_team=team_a, away_team=team_b)
        db.session.add(match)
        db.session.commit()

        return jsonify({
            "msg": "match created",
            "match_id": match.id
        }), 201
    # -------------------------
    # Admin M-PESA withdrawals
    # -------------------------
    @app.route("/admin/mpesa/withdrawals", methods=["GET"])
    @jwt_required()
    def admin_mpesa_withdrawals():

        uid = int(get_jwt_identity())

        admin = db.session.get(User, uid)

        if not admin or not admin.is_admin:
            return jsonify({
                "error": "forbidden"
            }), 403

        # -------------------------
        # Pagination
        # -------------------------

        try:
            limit = int(
                request.args.get("limit", 50)
            )
        except (TypeError, ValueError):
            return jsonify({
                "error": "invalid limit"
            }), 400

        try:
            offset = int(
                request.args.get("offset", 0)
            )
        except (TypeError, ValueError):
            return jsonify({
                "error": "invalid offset"
            }), 400

        if limit < 1:
            return jsonify({
                "error": "limit must be at least 1"
            }), 400

        if limit > 100:
            limit = 100

        if offset < 0:
            return jsonify({
                "error": "offset cannot be negative"
            }), 400

        # -------------------------
        # Optional status filter
        # -------------------------

        status = request.args.get("status")

        query = (
            db.session.query(
                MpesaWithdrawal,
                User.phone.label("user_phone"),
            )
            .join(
                User,
                User.id == MpesaWithdrawal.user_id,
            )
        )

        if status:
            status = status.strip().lower()

            allowed_statuses = {
                "pending",
                "submitted",
                "processing",
                "timeout",
                "success",
                "failed",
            }

            if status not in allowed_statuses:
                return jsonify({
                    "error": "invalid status",
                    "allowed_statuses": sorted(
                        allowed_statuses
                    ),
                }), 400

            query = query.filter(
                MpesaWithdrawal.status == status
            )

        total = query.count()

        rows = (
            query
            .order_by(
                MpesaWithdrawal.created.desc(),
                MpesaWithdrawal.id.desc(),
            )
            .offset(offset)
            .limit(limit)
            .all()
        )

        withdrawals = []

        for withdrawal, user_phone in rows:

            withdrawals.append({
                "id": withdrawal.id,
                "user_id": withdrawal.user_id,
                "user_phone": user_phone,
                "amount": str(
                    _money(withdrawal.amount)
                ),
                "phone": withdrawal.phone,
                "status": withdrawal.status,
                "originator_conversation_id": (
                    withdrawal.originator_conversation_id
                ),
                "conversation_id": (
                    withdrawal.conversation_id
                ),
                "mpesa_receipt": (
                    withdrawal.mpesa_receipt
                ),
                "result_code": (
                    withdrawal.result_code
                ),
                "result_description": (
                    withdrawal.result_description
                ),
                "reference": withdrawal.reference,
                "description": withdrawal.description,
                "created": (
                    withdrawal.created.isoformat()
                    if withdrawal.created
                    else None
                ),
                "updated": (
                    withdrawal.updated.isoformat()
                    if withdrawal.updated
                    else None
                ),
            })

        return jsonify({
            "withdrawals": withdrawals,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "returned": len(withdrawals),
                "has_more": (
                    offset + len(withdrawals) < total
                ),
            },
        }), 200

    # -------------------------
    # House M-PESA B2C payout
    # -------------------------
    @app.route("/admin/house-mpesa/payout", methods=["POST"])
    @jwt_required()
    def house_mpesa_payout():

        uid = int(get_jwt_identity())

        admin = db.session.get(User, uid)

        if not admin or not admin.is_admin:
            return jsonify({
                "error": "forbidden"
            }), 403

        data = request.json or {}

        phone = data.get("phone")
        amount_raw = data.get("amount")

        if not phone:
            return jsonify({
                "error": "phone is required"
            }), 400

        if amount_raw is None:
            return jsonify({
                "error": "amount is required"
            }), 400

        try:
            phone = normalize_phone(phone)
        except ValueError as exc:
            return jsonify({
                "error": str(exc)
            }), 400

        try:
            amount = _money(amount_raw)
        except ValueError:
            return jsonify({
                "error": "invalid amount"
            }), 400

        if amount < Decimal("10.00"):
            return jsonify({
                "error": "minimum B2C payout is KES 10"
            }), 400

        if amount != amount.to_integral_value():
            return jsonify({
                "error": "B2C payout amount must be a whole KES amount"
            }), 400

        if amount > Decimal("250000.00"):
            return jsonify({
                "error": "maximum B2C payout is KES 250,000"
            }), 400

        reference = (
            f"house-b2c-{uuid4().hex}"
        )

        originator_conversation_id = (
            f"LILYMAC-{uuid4().hex}"
        )

        # ------------------------------------------------
        # Reserve the house funds.
        # ------------------------------------------------

        try:
            house = (
                db.session.query(HouseWallet)
                .with_for_update()
                .filter(HouseWallet.id == 1)
                .first()
            )

            if not house:
                return jsonify({
                    "error": "house wallet is not initialized"
                }), 500


            balance = _money(
                house.balance
            )

            if balance < amount:
                db.session.rollback()

                return jsonify({
                    "error": "insufficient house funds",
                    "house_balance": str(balance),
                }), 503

            house.balance = _money(
                balance - amount
            )

            db.session.add(
                HouseTransaction(
                    type="mpesa_payout_pending",
                    amount=amount,
                    balance_after=house.balance,
                    reference=reference,
                    description="House M-PESA B2C payout reserved",
                )
            )

            withdrawal = HouseMpesaWithdrawal(
                amount=amount,
                phone=phone,
                status="pending",
                originator_conversation_id=(
                    originator_conversation_id
                ),
                reference=reference,
                description=(
                    "Admin house M-PESA B2C payout"
                ),
            )

            db.session.add(withdrawal)

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise

        # ------------------------------------------------
        # Submit to Safaricom AFTER reservation commit.
        # ------------------------------------------------

        try:
            response = b2c_payment(
                phone=phone,
                amount=amount,
                originator_conversation_id=(
                    originator_conversation_id
                ),
                remarks=(
                    "Lilymac house payout"
                ),
                occasion="Lilymac",
            )

        except Exception as exc:

            logger.exception(
                "House B2C submission failed | "
                "withdrawal=%s",
                withdrawal.id,
            )

            try:
                current = (
                    db.session.query(
                        HouseMpesaWithdrawal
                    )
                    .with_for_update()
                    .filter(
                        HouseMpesaWithdrawal.id
                        == withdrawal.id
                    )
                    .first()
                )

                if current and current.status not in (
                    "success",
                    "failed",
                    "timeout",
                ):
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

                    refund_amount = _money(
                        current.amount
                    )

                    house.balance = _money(
                        house.balance
                        + refund_amount
                    )

                    db.session.add(
                        HouseTransaction(
                            type="mpesa_payout_refund",
                            amount=refund_amount,
                            balance_after=house.balance,
                            reference=current.reference,
                            description=(
                                "Refund for failed house "
                                "M-PESA B2C payout submission"
                            ),
                        )
                    )

                    current.status = "failed"
                    current.result_description = str(
                        exc
                    )[:255]

                    db.session.commit()

            except Exception:
                db.session.rollback()
                logger.exception(
                    "Failed to refund failed house B2C "
                    "withdrawal"
                )

            return jsonify({
                "error": "M-PESA B2C request failed",
                "withdrawal_id": withdrawal.id,
            }), 502

        # ------------------------------------------------
        # Save Safaricom response.
        # ------------------------------------------------

        try:
            current = (
                db.session.query(
                    HouseMpesaWithdrawal
                )
                .filter(
                    HouseMpesaWithdrawal.id
                    == withdrawal.id
                )
                .with_for_update()
                .first()
            )

            if not current:
                raise RuntimeError(
                    "withdrawal record disappeared"
                )

            current.status = "submitted"

            conversation_id = (
                response.get("ConversationID")
            )

            if conversation_id:
                current.conversation_id = str(
                    conversation_id
                )

            response_code = response.get(
                "ResponseCode"
            )

            if response_code is not None:
                try:
                    current.result_code = int(
                        response_code
                    )
                except (TypeError, ValueError):
                    pass

            current.result_description = str(
                response.get(
                    "ResponseDescription",
                    "B2C request submitted",
                )
            )[:255]

            db.session.commit()

        except Exception:
            db.session.rollback()
            logger.exception(
                "Failed to save house B2C "
                "Safaricom response | withdrawal=%s",
                withdrawal.id,
            )

            return jsonify({
                "error": (
                    "B2C request was submitted, "
                    "but response could not be saved"
                ),
                "withdrawal_id": withdrawal.id,
            }), 500

        return jsonify({
            "message": "B2C payout submitted",
            "withdrawal_id": withdrawal.id,
            "reference": reference,
            "phone": phone,
            "amount": str(amount),
            "status": current.status,
            "conversation_id": (
                current.conversation_id
            ),
            "originator_conversation_id": (
                current.originator_conversation_id
            ),
        }), 202
    # -------------------------
        # ============================================================
    # M-PESA B2C callbacks
    # ============================================================

    def _extract_b2c_transaction_id(result):
        """
        Safaricom normally places the final M-PESA transaction ID
        inside ResultParameters.ResultParameter.
        """
        try:
            parameters = result.get("ResultParameters") or {}
            items = parameters.get("ResultParameter") or []

            for item in items:
                if item.get("Key") == "TransactionID":
                    value = item.get("Value")
                    if value:
                        return str(value)
        except Exception:
            logger.exception("Failed to extract B2C TransactionID")

        return None


    def _find_house_b2c_withdrawal(originator_id, conversation_id):
        """
        Find a house payout using Safaricom's callback identifiers.
        OriginatorConversationID is preferred because we generate it ourselves.
        """
        withdrawal = None

        if originator_id:
            withdrawal = (
                db.session.query(HouseMpesaWithdrawal)
                .with_for_update()
                .filter(
                    HouseMpesaWithdrawal.originator_conversation_id
                    == str(originator_id)
                )
                .first()
            )

        if not withdrawal and conversation_id:
            withdrawal = (
                db.session.query(HouseMpesaWithdrawal)
                .with_for_update()
                .filter(
                    HouseMpesaWithdrawal.conversation_id
                    == str(conversation_id)
                )
                .first()
            )

        return withdrawal


    def _find_user_b2c_withdrawal(originator_id, conversation_id):
        """
        Find a normal user M-PESA withdrawal.
        """
        withdrawal = None

        if originator_id:
            withdrawal = (
                db.session.query(MpesaWithdrawal)
                .with_for_update()
                .filter(
                    MpesaWithdrawal.originator_conversation_id
                    == str(originator_id)
                )
                .first()
            )

        if not withdrawal and conversation_id:
            withdrawal = (
                db.session.query(MpesaWithdrawal)
                .with_for_update()
                .filter(
                    MpesaWithdrawal.conversation_id
                    == str(conversation_id)
                )
                .first()
            )

        return withdrawal


    def _refund_house_payout(withdrawal, reason):
        """
        Refund the reserved house funds exactly once.

        The withdrawal is locked by the caller.
        """
        if withdrawal.status in ("success", "failed", "timeout"):
            return False

        house_wallet = (
            db.session.query(HouseWallet)
            .with_for_update()
            .first()
        )

        if not house_wallet:
            raise RuntimeError("House wallet was not found")

        house_wallet.balance = (
            house_wallet.balance or 0
        ) + withdrawal.amount

        db.session.add(
            HouseTransaction(
                type="mpesa_payout_refund",
                amount=withdrawal.amount,
                balance_after=house_wallet.balance,
                reference=withdrawal.reference,
                description=reason,
            )
        )

        return True


    def _refund_user_withdrawal(withdrawal, reason):
        """
        Refund a failed/timed-out user withdrawal exactly once.
        """
        if withdrawal.status in ("success", "failed", "timeout"):
            return False

        transaction = (
            db.session.query(Transaction)
            .with_for_update()
            .filter(
                Transaction.user_id == withdrawal.user_id,
                Transaction.reference == withdrawal.reference,
                Transaction.type == "mpesa_withdrawal",
            )
            .first()
        )

        if not transaction:
            raise RuntimeError(
                "User M-PESA withdrawal transaction was not found"
            )

        user = (
            db.session.query(User)
            .with_for_update()
            .filter(User.id == withdrawal.user_id)
            .first()
        )

        if not user:
            raise RuntimeError(
                f"User {withdrawal.user_id} was not found"
            )

        user.balance = (user.balance or 0) + withdrawal.amount
        transaction.status = "failed"
        transaction.balance_after = user.balance

        return True


    @app.route("/mpesa/b2c/result", methods=["POST"])
    def house_mpesa_b2c_result():
        """
        Shared Safaricom B2C result callback.

        Handles:
          1. HouseMpesaWithdrawal
          2. Normal MpesaWithdrawal

        The same ResultURL is intentionally shared by both flows.
        """
        data = request.get_json(silent=True) or {}

        logger.info("RAW B2C CALLBACK PAYLOAD: %s", data)

        result = data.get("Result") or {}

        originator_id = result.get("OriginatorConversationID")
        conversation_id = result.get("ConversationID")
        result_code_raw = result.get("ResultCode")
        result_description = result.get("ResultDesc")

        # Some probes/empty callbacks contain no ResultCode.
        # Safaricom expects an HTTP 200 acknowledgement.
        if result_code_raw is None:
            logger.warning(
                "B2C callback received without ResultCode | "
                "originator=%s | conversation=%s",
                originator_id,
                conversation_id,
            )

            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Accepted",
            }), 200

        try:
            result_code = int(result_code_raw)
        except (TypeError, ValueError):
            result_code = -1

        transaction_id = _extract_b2c_transaction_id(result)

        logger.info(
            "B2C CALLBACK | originator=%s | conversation=%s | "
            "result_code=%s | result_desc=%s | transaction_id=%s",
            originator_id,
            conversation_id,
            result_code,
            result_description,
            transaction_id,
        )

        try:
            # --------------------------------------------------------
            # FIRST: HOUSE M-PESA PAYOUT
            # --------------------------------------------------------
            house_withdrawal = _find_house_b2c_withdrawal(
                originator_id,
                conversation_id,
            )

            if house_withdrawal:
                logger.info(
                    "Matched HOUSE B2C payout | id=%s | reference=%s | "
                    "status=%s",
                    house_withdrawal.id,
                    house_withdrawal.reference,
                    house_withdrawal.status,
                )

                # Idempotency: never process a final payout twice.
                if house_withdrawal.status in (
                    "success",
                    "failed",
                    "timeout",
                ):
                    logger.info(
                        "HOUSE B2C callback already processed | id=%s | status=%s",
                        house_withdrawal.id,
                        house_withdrawal.status,
                    )

                    return jsonify({
                        "ResultCode": 0,
                        "ResultDesc": "Already processed",
                    }), 200

                house_withdrawal.result_code = result_code
                house_withdrawal.result_description = str(
                    result_description or ""
                )[:255]

                if conversation_id:
                    house_withdrawal.conversation_id = str(
                        conversation_id
                    )

                if transaction_id and hasattr(
                    house_withdrawal,
                    "mpesa_receipt",
                ):
                    house_withdrawal.mpesa_receipt = transaction_id

                if result_code == 0:
                    # ----------------------------------------------
                    # HOUSE PAYOUT SUCCESS
                    # ----------------------------------------------
                    house_withdrawal.status = "success"

                    logger.info(
                        "HOUSE B2C PAYOUT SUCCESS | id=%s | amount=%s | "
                        "phone=%s | transaction_id=%s",
                        house_withdrawal.id,
                        house_withdrawal.amount,
                        house_withdrawal.phone,
                        transaction_id,
                    )

                else:
                    # ----------------------------------------------
                    # HOUSE PAYOUT FAILURE
                    # ----------------------------------------------
                    refunded = _refund_house_payout(
                        house_withdrawal,
                        reason=(
                            "Refund for failed M-PESA B2C house payout "
                            f"(ResultCode={result_code})"
                        ),
                    )

                    house_withdrawal.status = "failed"

                    logger.warning(
                        "HOUSE B2C PAYOUT FAILED | id=%s | amount=%s | "
                        "result_code=%s | refunded=%s",
                        house_withdrawal.id,
                        house_withdrawal.amount,
                        result_code,
                        refunded,
                    )

                db.session.commit()

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Processed successfully",
                }), 200

            # --------------------------------------------------------
            # SECOND: NORMAL USER M-PESA WITHDRAWAL
            # --------------------------------------------------------
            user_withdrawal = _find_user_b2c_withdrawal(
                originator_id,
                conversation_id,
            )

            if user_withdrawal:
                logger.info(
                    "Matched USER B2C withdrawal | id=%s | user_id=%s | "
                    "reference=%s | status=%s",
                    user_withdrawal.id,
                    user_withdrawal.user_id,
                    user_withdrawal.reference,
                    user_withdrawal.status,
                )

                # Idempotency
                if user_withdrawal.status in (
                    "success",
                    "failed",
                    "timeout",
                ):
                    logger.info(
                        "USER B2C callback already processed | id=%s | status=%s",
                        user_withdrawal.id,
                        user_withdrawal.status,
                    )

                    return jsonify({
                        "ResultCode": 0,
                        "ResultDesc": "Already processed",
                    }), 200

                user_withdrawal.result_code = result_code
                user_withdrawal.result_description = str(
                    result_description or ""
                )[:255]

                if conversation_id:
                    user_withdrawal.conversation_id = str(
                        conversation_id
                    )

                if transaction_id and hasattr(
                    user_withdrawal,
                    "mpesa_receipt",
                ):
                    user_withdrawal.mpesa_receipt = transaction_id

                transaction = (
                    db.session.query(Transaction)
                    .with_for_update()
                    .filter(
                        Transaction.user_id == user_withdrawal.user_id,
                        Transaction.reference == user_withdrawal.reference,
                        Transaction.type == "mpesa_withdrawal",
                    )
                    .first()
                )

                if not transaction:
                    raise RuntimeError(
                        "User M-PESA withdrawal transaction was not found"
                    )

                if result_code == 0:
                    # ----------------------------------------------
                    # USER PAYOUT SUCCESS
                    # ----------------------------------------------
                    user_withdrawal.status = "success"
                    transaction.status = "completed"

                    if transaction_id:
                        transaction.reference = transaction_id

                    logger.info(
                        "USER B2C PAYOUT SUCCESS | id=%s | user_id=%s | "
                        "transaction_id=%s",
                        user_withdrawal.id,
                        user_withdrawal.user_id,
                        transaction_id,
                    )

                else:
                    # ----------------------------------------------
                    # USER PAYOUT FAILURE
                    # ----------------------------------------------
                    user = (
                        db.session.query(User)
                        .with_for_update()
                        .filter(
                            User.id == user_withdrawal.user_id
                        )
                        .first()
                    )

                    if not user:
                        raise RuntimeError(
                            f"User {user_withdrawal.user_id} was not found"
                        )

                    user.balance = (
                        user.balance or 0
                    ) + user_withdrawal.amount

                    user_withdrawal.status = "failed"
                    transaction.status = "failed"
                    transaction.balance_after = user.balance

                    logger.warning(
                        "USER B2C PAYOUT FAILED | id=%s | user_id=%s | "
                        "result_code=%s | amount_refunded=%s",
                        user_withdrawal.id,
                        user_withdrawal.user_id,
                        result_code,
                        user_withdrawal.amount,
                    )

                db.session.commit()

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Processed successfully",
                }), 200

            # --------------------------------------------------------
            # UNKNOWN CALLBACK
            # --------------------------------------------------------
            logger.warning(
                "UNKNOWN B2C CALLBACK | originator=%s | conversation=%s | "
                "result_code=%s | result_desc=%s",
                originator_id,
                conversation_id,
                result_code,
                result_description,
            )

            # Always acknowledge Safaricom.
            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Accepted",
            }), 200

        except Exception:
            db.session.rollback()

            logger.exception(
                "B2C callback processing failed | originator=%s | "
                "conversation=%s",
                originator_id,
                conversation_id,
            )

            # Safaricom should still receive HTTP 200 so it does not
            # repeatedly hammer the callback endpoint.
            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Accepted",
            }), 200


    @app.route("/mpesa/b2c/timeout", methods=["POST"])
    def house_mpesa_b2c_timeout():
        """
        Shared Safaricom B2C timeout callback.

        A timeout is treated as a non-completed payout and the reserved
        funds are returned to the appropriate balance.
        """
        data = request.get_json(silent=True) or {}

        logger.warning(
            "RAW B2C TIMEOUT CALLBACK PAYLOAD: %s",
            data,
        )

        result = data.get("Result") or {}

        originator_id = result.get("OriginatorConversationID")
        conversation_id = result.get("ConversationID")
        result_code_raw = result.get("ResultCode")
        result_description = result.get("ResultDesc")

        try:
            result_code = (
                int(result_code_raw)
                if result_code_raw is not None
                else -1
            )
        except (TypeError, ValueError):
            result_code = -1

        try:
            # --------------------------------------------------------
            # FIRST: HOUSE PAYOUT
            # --------------------------------------------------------
            house_withdrawal = _find_house_b2c_withdrawal(
                originator_id,
                conversation_id,
            )

            if house_withdrawal:
                if house_withdrawal.status in (
                    "success",
                    "failed",
                    "timeout",
                ):
                    return jsonify({
                        "ResultCode": 0,
                        "ResultDesc": "Already processed",
                    }), 200

                house_withdrawal.status = "timeout"
                house_withdrawal.result_code = result_code
                house_withdrawal.result_description = str(
                    result_description
                    or "M-PESA B2C timeout"
                )[:255]

                if conversation_id:
                    house_withdrawal.conversation_id = str(
                        conversation_id
                    )

                refunded = _refund_house_payout(
                    house_withdrawal,
                    reason="Refund for M-PESA B2C house payout timeout",
                )

                db.session.commit()

                logger.warning(
                    "HOUSE B2C PAYOUT TIMEOUT | id=%s | amount=%s | "
                    "refunded=%s",
                    house_withdrawal.id,
                    house_withdrawal.amount,
                    refunded,
                )

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Processed successfully",
                }), 200

            # --------------------------------------------------------
            # SECOND: USER PAYOUT
            # --------------------------------------------------------
            user_withdrawal = _find_user_b2c_withdrawal(
                originator_id,
                conversation_id,
            )

            if user_withdrawal:
                if user_withdrawal.status in (
                    "success",
                    "failed",
                    "timeout",
                ):
                    return jsonify({
                        "ResultCode": 0,
                        "ResultDesc": "Already processed",
                    }), 200

                user_withdrawal.status = "timeout"
                user_withdrawal.result_code = result_code
                user_withdrawal.result_description = str(
                    result_description
                    or "M-PESA B2C timeout"
                )[:255]

                if conversation_id:
                    user_withdrawal.conversation_id = str(
                        conversation_id
                    )

                _refund_user_withdrawal(
                    user_withdrawal,
                    reason="Refund for M-PESA B2C user withdrawal timeout",
                )

                db.session.commit()

                logger.warning(
                    "USER B2C PAYOUT TIMEOUT | id=%s | user_id=%s | "
                    "amount=%s",
                    user_withdrawal.id,
                    user_withdrawal.user_id,
                    user_withdrawal.amount,
                )

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Processed successfully",
                }), 200

            # --------------------------------------------------------
            # UNKNOWN TIMEOUT
            # --------------------------------------------------------
            logger.warning(
                "UNKNOWN B2C TIMEOUT | originator=%s | conversation=%s",
                originator_id,
                conversation_id,
            )

            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Accepted",
            }), 200

        except Exception:
            db.session.rollback()

            logger.exception(
                "B2C timeout callback processing failed | "
                "originator=%s | conversation=%s",
                originator_id,
                conversation_id,
            )

            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Accepted",
            }), 200
