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
    # M-PESA B2C result
    # callback
    # -------------------------
    @app.route("/mpesa/b2c/result", methods=["POST"])
    def house_mpesa_b2c_result():

        data = request.get_json(
            silent=True
        ) or {}

        result = data.get("Result") or {}

        originator_id = result.get(
            "OriginatorConversationID"
        )

        conversation_id = result.get(
            "ConversationID"
        )

        result_code_raw = result.get(
            "ResultCode"
        )

        result_description = result.get(
            "ResultDesc"
        )

        if result_code_raw is None:
            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Accepted",
            }), 200

        try:
            result_code = int(
                result_code_raw
            )
        except (TypeError, ValueError):
            result_code = -1

        try:
            # ====================================================
            # DETERMINE USER VS HOUSE B2C
            # ====================================================

            is_user_withdrawal = bool(
                originator_id
                and str(originator_id).startswith(
                    "LILYMAC-USER-"
                )
            )

            # ====================================================
            # USER M-PESA B2C
            # ====================================================

            if is_user_withdrawal:

                withdrawal = None

                if originator_id:
                    withdrawal = (
                        db.session.query(
                            MpesaWithdrawal
                        )
                        .with_for_update()
                        .filter(
                            MpesaWithdrawal
                            .originator_conversation_id
                            == str(originator_id)
                        )
                        .first()
                    )

                if not withdrawal and conversation_id:
                    withdrawal = (
                        db.session.query(
                            MpesaWithdrawal
                        )
                        .with_for_update()
                        .filter(
                            MpesaWithdrawal
                            .conversation_id
                            == str(conversation_id)
                        )
                        .first()
                    )

                if not withdrawal:
                    logger.warning(
                        "Unknown user B2C callback | "
                        "originator=%s | conversation=%s",
                        originator_id,
                        conversation_id,
                    )

                    return jsonify({
                        "ResultCode": 0,
                        "ResultDesc": "Accepted",
                    }), 200

                # ------------------------------------------------
                # Idempotency
                # ------------------------------------------------

                if withdrawal.status in (
                    "success",
                    "failed",
                ):
                    return jsonify({
                        "ResultCode": 0,
                        "ResultDesc": "Already processed",
                    }), 200

                withdrawal.result_code = result_code
                withdrawal.result_description = str(
                    result_description or ""
                )[:255]

                if conversation_id:
                    withdrawal.conversation_id = str(
                        conversation_id
                    )

                # ------------------------------------------------
                # Find the original pending wallet transaction
                # ------------------------------------------------

                transaction = (
                    db.session.query(Transaction)
                    .with_for_update()
                    .filter(
                        Transaction.user_id
                        == withdrawal.user_id,
                        Transaction.reference
                        == withdrawal.reference,
                        Transaction.type
                        == "mpesa_withdrawal",
                    )
                    .first()
                )

                if not transaction:
                    raise RuntimeError(
                        "User M-PESA withdrawal transaction "
                        "was not found"
                    )

                # =================================================
                # USER B2C FAILED
                # =================================================

                if result_code != 0:

                    user = (
                        db.session.query(User)
                        .with_for_update()
                        .filter(
                            User.id
                            == withdrawal.user_id
                        )
                        .first()
                    )

                    if not user:
                        raise RuntimeError(
                            "User for M-PESA withdrawal "
                            "was not found"
                        )

                    refund_amount = _money(
                        withdrawal.amount
                    )

                    user.balance = _money(
                        user.balance
                        + refund_amount
                    )

                    transaction.status = "failed"
                    transaction.description = (
                        "Failed M-PESA withdrawal"
                    )

                    db.session.add(
                        Transaction(
                            user_id=user.id,
                            type="mpesa_withdrawal_refund",
                            amount=refund_amount,
                            balance_after=user.balance,
                            reference=withdrawal.reference,
                            description=(
                                "Refund for failed "
                                "M-PESA withdrawal"
                            ),
                            status="completed",
                        )
                    )

                    withdrawal.status = "failed"

                    db.session.commit()

                    logger.warning(
                        "User B2C withdrawal failed | "
                        "withdrawal=%s | user=%s | "
                        "code=%s | amount_refunded=%s",
                        withdrawal.id,
                        user.id,
                        result_code,
                        refund_amount,
                    )

                    return jsonify({
                        "ResultCode": 0,
                        "ResultDesc": "Accepted",
                    }), 200

                # =================================================
                # USER B2C SUCCESS
                # =================================================

                transaction_id = None

                result_parameters = (
                    result.get(
                        "ResultParameters"
                    )
                    or {}
                )

                parameters = (
                    result_parameters.get(
                        "ResultParameter"
                    )
                    or []
                )

                for parameter in parameters:

                    if parameter.get(
                        "Key"
                    ) == "TransactionReceipt":

                        transaction_id = (
                            parameter.get("Value")
                        )

                        break

                if transaction_id:
                    withdrawal.mpesa_receipt = str(
                        transaction_id
                    )

                transaction.status = "completed"
                transaction.description = (
                    "M-PESA withdrawal completed"
                )

                withdrawal.status = "success"

                db.session.commit()

                logger.info(
                    "User B2C withdrawal successful | "
                    "withdrawal=%s | user=%s | "
                    "amount=%s | receipt=%s",
                    withdrawal.id,
                    withdrawal.user_id,
                    withdrawal.amount,
                    withdrawal.mpesa_receipt,
                )

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted",
                }), 200

            # ====================================================
            # HOUSE M-PESA B2C
            # ====================================================

            withdrawal = None

            if originator_id:
                withdrawal = (
                    db.session.query(
                        HouseMpesaWithdrawal
                    )
                    .with_for_update()
                    .filter(
                        HouseMpesaWithdrawal
                        .originator_conversation_id
                        == str(originator_id)
                    )
                    .first()
                )

            if not withdrawal and conversation_id:
                withdrawal = (
                    db.session.query(
                        HouseMpesaWithdrawal
                    )
                    .with_for_update()
                    .filter(
                        HouseMpesaWithdrawal
                        .conversation_id
                        == str(conversation_id)
                    )
                    .first()
                )

            if not withdrawal:
                logger.warning(
                    "Unknown house B2C callback | "
                    "originator=%s | conversation=%s",
                    originator_id,
                    conversation_id,
                )

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted",
                }), 200

            # ----------------------------------------
            # Idempotency
            # ----------------------------------------

            if withdrawal.status in (
                "success",
                "failed",
                "timeout",
            ):
                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Already processed",
                }), 200

            withdrawal.result_code = result_code
            withdrawal.result_description = str(
                result_description or ""
            )[:255]

            if conversation_id:
                withdrawal.conversation_id = str(
                    conversation_id
                )

            # ----------------------------------------
            # FAILED HOUSE B2C
            # ----------------------------------------

            if result_code != 0:

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
                    withdrawal.amount
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
                        reference=withdrawal.reference,
                        description=(
                            "Refund for failed house "
                            "M-PESA B2C payout"
                        ),
                    )
                )

                withdrawal.status = "failed"

                db.session.commit()

                logger.warning(
                    "House B2C payout failed | "
                    "withdrawal=%s | code=%s | "
                    "description=%s | amount_refunded=%s",
                    withdrawal.id,
                    result_code,
                    result_description,
                    refund_amount,
                )

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted",
                }), 200

            # ----------------------------------------
            # SUCCESSFUL HOUSE B2C
            # ----------------------------------------

            transaction_id = None

            result_parameters = (
                result.get("ResultParameters")
                or {}
            )

            parameters = (
                result_parameters.get(
                    "ResultParameter"
                )
                or []
            )

            for parameter in parameters:

                if parameter.get(
                    "Key"
                ) == "TransactionReceipt":

                    transaction_id = (
                        parameter.get("Value")
                    )

                    break

            if transaction_id:
                withdrawal.mpesa_receipt = str(
                    transaction_id
                )

            withdrawal.status = "success"

            db.session.commit()

            logger.info(
                "House B2C payout successful | "
                "withdrawal=%s | amount=%s | receipt=%s",
                withdrawal.id,
                withdrawal.amount,
                withdrawal.mpesa_receipt,
            )

            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Accepted",
            }), 200

        except Exception:

            db.session.rollback()

            logger.exception(
                "M-PESA B2C result callback failed"
            )

            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Accepted",
            }), 200

    # -------------------------
    # M-PESA B2C timeout
    # callback
    # -------------------------
    @app.route("/mpesa/b2c/timeout", methods=["POST"])
    def house_mpesa_b2c_timeout():

        data = request.get_json(
            silent=True
        ) or {}

        result = data.get("Result") or {}

        originator_id = result.get(
            "OriginatorConversationID"
        )

        conversation_id = result.get(
            "ConversationID"
        )

        try:

            # ====================================================
            # USER M-PESA B2C TIMEOUT
            # ====================================================

            is_user_withdrawal = bool(
                originator_id
                and str(originator_id).startswith(
                    "LILYMAC-USER-"
                )
            )

            if is_user_withdrawal:

                withdrawal = None

                if originator_id:
                    withdrawal = (
                        db.session.query(
                            MpesaWithdrawal
                        )
                        .with_for_update()
                        .filter(
                            MpesaWithdrawal
                            .originator_conversation_id
                            == str(originator_id)
                        )
                        .first()
                    )

                if not withdrawal and conversation_id:
                    withdrawal = (
                        db.session.query(
                            MpesaWithdrawal
                        )
                        .with_for_update()
                        .filter(
                            MpesaWithdrawal
                            .conversation_id
                            == str(conversation_id)
                        )
                        .first()
                    )

                if withdrawal:

                    if withdrawal.status not in (
                        "success",
                        "failed",
                        "timeout",
                    ):

                        user = (
                            db.session.query(User)
                            .with_for_update()
                            .filter(
                                User.id
                                == withdrawal.user_id
                            )
                            .first()
                        )

                        if not user:
                            raise RuntimeError(
                                "User for timed-out "
                                "M-PESA withdrawal "
                                "was not found"
                            )

                        transaction = (
                            db.session.query(Transaction)
                            .with_for_update()
                            .filter(
                                Transaction.user_id
                                == withdrawal.user_id,
                                Transaction.reference
                                == withdrawal.reference,
                                Transaction.type
                                == "mpesa_withdrawal",
                            )
                            .first()
                        )

                        if not transaction:
                            raise RuntimeError(
                                "User M-PESA withdrawal "
                                "transaction was not found"
                            )

                        withdrawal.status = "timeout"

                        withdrawal.result_description = (
                            "B2C request timed out"
                        )

                        db.session.commit()


                        logger.warning(
                            "User B2C withdrawal timed out | "
                            "withdrawal=%s | user=%s | "
                            "amount=%s | awaiting final result",
                            withdrawal.id,
                            user.id,
                            withdrawal.amount,
                        )

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted",
                }), 200

            # ====================================================
            # HOUSE M-PESA B2C TIMEOUT
            # ====================================================

            withdrawal = None

            if originator_id:
                withdrawal = (
                    db.session.query(
                        HouseMpesaWithdrawal
                    )
                    .with_for_update()
                    .filter(
                        HouseMpesaWithdrawal
                        .originator_conversation_id
                        == str(originator_id)
                    )
                    .first()
                )

            if not withdrawal and conversation_id:
                withdrawal = (
                    db.session.query(
                        HouseMpesaWithdrawal
                    )
                    .with_for_update()
                    .filter(
                        HouseMpesaWithdrawal
                        .conversation_id
                        == str(conversation_id)
                    )
                    .first()
                )

            if withdrawal:

                if withdrawal.status not in (
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


                    withdrawal.status = "timeout"

                    withdrawal.result_description = (
                        "B2C request timed out"
                    )

                    db.session.commit()

                    logger.warning(
                        "House B2C payout timed out | "
                        "withdrawal=%s | awaiting final result",
                        withdrawal.id,
                    )

            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Accepted",
            }), 200

        except Exception:

            db.session.rollback()

            logger.exception(
                "M-PESA B2C timeout callback failed"
            )

            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Accepted",
            }), 200
