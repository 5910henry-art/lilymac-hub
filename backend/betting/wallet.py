# wallet.py

import logging
import os
from decimal import Decimal, InvalidOperation

from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from betting.models import (
    db,
    User,
    Transaction,
    MpesaWithdrawal,
)

from betting.mpesa import (
    normalize_phone,
    b2c_payment,
)

from uuid import uuid4
from betting.utils import to_decimal


logger = logging.getLogger(__name__)


# ============================================================
# WALLET SETTINGS
# ============================================================

MAX_DEPOSIT = Decimal("5000.00")
MIN_DEPOSIT = Decimal("0.01")
MIN_WITHDRAWAL = Decimal("0.01")


# ============================================================
# MONEY HELPERS
# ============================================================

def _parse_amount(value):
    """
    Safely parse a wallet amount.
    """

    if value is None:
        return None

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None

    if not amount.is_finite():
        return None

    amount = amount.quantize(
        Decimal("0.01")
    )

    if amount <= 0:
        return None

    return amount


def _balance(user):
    """
    Return user's balance as a Decimal.
    """

    return to_decimal(
        getattr(
            user,
            "balance",
            Decimal("0.00"),
        )
    )


def _error(message, status=400):
    return jsonify({
        "success": False,
        "error": message,
    }), status


def _success(balance):
    return jsonify({
        "success": True,
        "balance": float(
            to_decimal(balance)
        ),
    })


# ============================================================
# REGISTER WALLET ROUTES
# ============================================================

def register_wallet_routes(app):

    # ========================================================
    # BALANCE
    # ========================================================

    @app.route(
        "/balance",
        methods=["GET"],
    )
    @jwt_required()
    def get_balance():

        try:
            uid = int(
                get_jwt_identity()
            )
        except (TypeError, ValueError):
            return _error(
                "invalid user identity",
                401,
            )

        user = db.session.get(
            User,
            uid,
        )

        if not user:
            return _error(
                "user not found",
                404,
            )

        return jsonify({
            "success": True,
            "balance": float(
                _balance(user)
            ),
        })


    # ========================================================
    # TRANSACTIONS
    # ========================================================

    @app.route(
        "/transactions",
        methods=["GET"],
    )
    @jwt_required()
    def get_transactions():

        try:
            uid = int(
                get_jwt_identity()
            )
        except (TypeError, ValueError):
            return _error(
                "invalid user identity",
                401,
            )

        try:

            txs = (
                db.session.query(Transaction)
                .filter(
                    Transaction.user_id == uid
                )
                .order_by(
                    Transaction.created.desc()
                )
                .all()
            )

            data = []

            for tx in txs:

                description = getattr(
                    tx,
                    "description",
                    None,
                )

                reference = getattr(
                    tx,
                    "reference",
                    None,
                )

                status = getattr(
                    tx,
                    "status",
                    None,
                )

                created_at = (
                    tx.created.isoformat()
                    if tx.created
                    else None
                )

                data.append({
                    "id": tx.id,

                    "type": (
                        tx.type
                        if tx.type
                        else "transaction"
                    ),

                    "amount": float(
                        to_decimal(
                            tx.amount
                        )
                    ),

                    "balance_after": float(
                        to_decimal(
                            tx.balance_after
                        )
                    ),

                    "created_at": created_at,

                    "created": created_at,

                    "description": (
                        description
                        if description
                        else ""
                    ),

                    "reference": (
                        reference
                        if reference
                        else ""
                    ),

                    "status": (
                        status
                        if status
                        else "completed"
                    ),
                })

            return jsonify({
                "success": True,
                "data": {
                    "transactions": data,
                },
                "count": len(data),
            })

        except Exception as e:

            logger.exception(
                "Error loading transactions for user %s: %s",
                uid,
                e,
            )

            return _error(
                "failed to load transactions",
                500,
            )


    # ========================================================
    # BALANCE HISTORY
    # ========================================================

    @app.route(
        "/balance_history",
        methods=["GET"],
    )
    @jwt_required()
    def get_balance_history():

        try:
            uid = int(
                get_jwt_identity()
            )
        except (TypeError, ValueError):
            return _error(
                "invalid user identity",
                401,
            )

        try:

            txs = (
                db.session.query(Transaction)
                .filter(
                    Transaction.user_id == uid
                )
                .order_by(
                    Transaction.created.asc()
                )
                .all()
            )

            history = []

            for tx in txs:

                history.append({
                    "date": (
                        tx.created.isoformat()
                        if tx.created
                        else None
                    ),

                    "balance": float(
                        to_decimal(
                            tx.balance_after
                        )
                    ),
                })

            return jsonify({
                "success": True,
                "data": history,
                "count": len(history),
            })

        except Exception as e:

            logger.exception(
                "Error loading balance history for user %s: %s",
                uid,
                e,
            )

            return _error(
                "failed to load balance history",
                500,
            )


    # ========================================================
    # DEPOSIT
    # ========================================================
# ========================================================
# DEPOSIT
# ========================================================
#
# IMPORTANT:
# Direct wallet crediting has been removed.
#
# All real deposits must go through:
#
#     POST /mpesa/stkpush
#
# The wallet is credited only after the M-PESA callback
# confirms a successful payment.
# ========================================================

    @app.route(
        "/deposit",
        methods=["POST"],
   )
    @jwt_required()
    def deposit():

     return _error(
        "Direct wallet deposits are disabled. "
        "Use M-PESA STK Push.",
        410,
    )

    # ========================================================
    # M-PESA B2C WITHDRAW
    # ========================================================

    @app.route(
        "/withdraw",
        methods=["POST"],
    )
    @jwt_required()
    def withdraw():

        # ----------------------------------------------------
        # Identify authenticated user
        # ----------------------------------------------------

        try:
            uid = int(
                get_jwt_identity()
            )
        except (TypeError, ValueError):
            return _error(
                "invalid user identity",
                401,
            )

        # ----------------------------------------------------
        # Read request
        #
        # Frontend only needs:
        #
        # {
        #     "amount": 100
        # }
        #
        # Phone comes from User.phone.
        # ----------------------------------------------------

        data = request.get_json(
            silent=True
        ) or {}

        amount = _parse_amount(
            data.get("amount")
        )

        if amount is None:
            return _error(
                "invalid withdrawal amount"
            )

        # ----------------------------------------------------
        # B2C requires whole KES.
        # ----------------------------------------------------

        if amount != amount.to_integral_value():
            return _error(
                "withdrawal amount must be a whole KES amount"
            )

        # ----------------------------------------------------
        # Same limits enforced by b2c_payment()
        # ----------------------------------------------------

        if amount < Decimal("10.00"):
            return _error(
                "minimum withdrawal is KES 10"
            )

        if amount > Decimal("250000.00"):
            return _error(
                "maximum withdrawal is KES 250,000"
            )

        # ----------------------------------------------------
        # Reserve user's money FIRST.
        #
        # We commit the reservation before contacting
        # Safaricom so the wallet transaction exists before
        # the asynchronous B2C callback arrives.
        # ----------------------------------------------------

        reference = f"mpesa-withdraw-{uuid4().hex}"

        originator_conversation_id = (
            f"LILYMAC-USER-{uuid4().hex}"
        )

        try:

            user = (
                db.session.query(User)
                .with_for_update()
                .filter(
                    User.id == uid
                )
                .first()
            )

            if not user:
                db.session.rollback()

                return _error(
                    "user not found",
                    404,
                )

            # ------------------------------------------------
            # Determine B2C payout phone.
            #
            # SANDBOX:
            # Use Safaricom's configured B2C test recipient.
            #
            # PRODUCTION:
            # Use the authenticated user's registered phone.
            #
            # Never trust a phone supplied by the frontend.
            # ------------------------------------------------

            if os.getenv("MPESA_ENV", "").lower() == "sandbox":

                test_phone = os.getenv(
                    "MPESA_B2C_TEST_PHONE"
                )

                if not test_phone:
                    db.session.rollback()

                    return _error(
                        "M-PESA B2C sandbox test phone is not configured",
                        500,
                    )

                try:
                    phone = normalize_phone(
                        test_phone
                    )
                except ValueError as exc:
                    db.session.rollback()

                    return _error(
                        str(exc),
                        500,
                    )

            else:

                if not user.phone:
                    db.session.rollback()

                    return _error(
                        "no M-PESA phone number is registered"
                    )

                try:
                    phone = normalize_phone(
                        user.phone
                    )
                except ValueError as exc:
                    db.session.rollback()

                    return _error(
                        str(exc)
                    )

            # ------------------------------------------------
            # Check wallet balance while user row is locked.
            # ------------------------------------------------

            current_balance = _balance(
                user
            )

            if current_balance < amount:
                db.session.rollback()

                return _error(
                    "insufficient funds"
                )

            # ------------------------------------------------
            # Reserve the money.
            # ------------------------------------------------

            new_balance = (
                current_balance
                - amount
            )

            user.balance = new_balance

            # ------------------------------------------------
            # Wallet transaction.
            #
            # IMPORTANT:
            # Callback searches for this exact:
            #
            # user_id
            # reference
            # type = "mpesa_withdrawal"
            # ------------------------------------------------

            tx = Transaction(
                user_id=uid,
                type="mpesa_withdrawal",
                amount=amount,
                balance_after=new_balance,
                description="M-PESA withdrawal pending",
                reference=reference,
                status="pending",
            )

            db.session.add(tx)

            # ------------------------------------------------
            # B2C withdrawal tracking record.
            # ------------------------------------------------

            withdrawal = MpesaWithdrawal(
                user_id=uid,
                amount=amount,
                phone=phone,
                status="pending",
                originator_conversation_id=(
                    originator_conversation_id
                ),
                reference=reference,
                description="User M-PESA B2C withdrawal",
            )

            db.session.add(
                withdrawal
            )

            # ------------------------------------------------
            # COMMIT BEFORE B2C REQUEST
            # ------------------------------------------------

            db.session.commit()

        except Exception as exc:

            db.session.rollback()

            logger.exception(
                "Failed to reserve M-PESA withdrawal | "
                "user=%s | amount=%s | error=%s",
                uid,
                amount,
                exc,
            )

            return _error(
                "could not create withdrawal",
                500,
            )

        # ----------------------------------------------------
        # Submit B2C request to Safaricom.
        #
        # This is asynchronous. A successful response here
        # means Safaricom accepted the request for processing,
        # NOT that the user has already received the money.
        # ----------------------------------------------------

        try:

            response = b2c_payment(
                phone=phone,
                amount=amount,
                originator_conversation_id=(
                    originator_conversation_id
                ),
                remarks="Lilymac user withdrawal",
                occasion="Lilymac",
            )

        except Exception as exc:

            logger.exception(
                "M-PESA B2C submission failed | "
                "withdrawal=%s | user=%s | error=%s",
                withdrawal.id,
                uid,
                exc,
            )

            # ------------------------------------------------
            # Submission failed.
            #
            # Lock withdrawal again before refunding.
            # ------------------------------------------------

            try:

                current = (
                    db.session.query(
                        MpesaWithdrawal
                    )
                    .with_for_update()
                    .filter(
                        MpesaWithdrawal.id
                        == withdrawal.id
                    )
                    .first()
                )

                if not current:
                    raise RuntimeError(
                        "withdrawal record disappeared"
                    )

                # --------------------------------------------
                # Do not refund if a callback already finalized
                # or timed out the transaction.
                # --------------------------------------------

                if current.status not in (
                    "success",
                    "failed",
                    "timeout",
                ):

                    locked_user = (
                        db.session.query(User)
                        .with_for_update()
                        .filter(
                            User.id == uid
                        )
                        .first()
                    )

                    if not locked_user:
                        raise RuntimeError(
                            "user for withdrawal refund was not found"
                        )

                    original_tx = (
                        db.session.query(
                            Transaction
                        )
                        .with_for_update()
                        .filter(
                            Transaction.user_id == uid,
                            Transaction.reference
                            == current.reference,
                            Transaction.type
                            == "mpesa_withdrawal",
                        )
                        .first()
                    )

                    if not original_tx:
                        raise RuntimeError(
                            "original withdrawal transaction "
                            "was not found"
                        )

                    refund_amount = _parse_amount(
                        current.amount
                    )

                    if refund_amount is None:
                        raise RuntimeError(
                            "invalid withdrawal amount during refund"
                        )

                    # ----------------------------------------
                    # Refund reserved wallet money.
                    # ----------------------------------------

                    locked_user.balance = (
                        _balance(locked_user)
                        + refund_amount
                    )

                    original_tx.status = "failed"
                    original_tx.description = (
                        "M-PESA withdrawal submission failed"
                    )

                    db.session.add(
                        Transaction(
                            user_id=uid,
                            type="mpesa_withdrawal_refund",
                            amount=refund_amount,
                            balance_after=(
                                locked_user.balance
                            ),
                            reference=current.reference,
                            description=(
                                "Refund for failed M-PESA "
                                "withdrawal submission"
                            ),
                            status="completed",
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
                    "M-PESA withdrawal refund failed | "
                    "withdrawal=%s | user=%s",
                    withdrawal.id,
                    uid,
                )

            return jsonify({
                "error": "M-PESA withdrawal request failed",
                "withdrawal_id": withdrawal.id,
            }), 502

        # ----------------------------------------------------
        # Safaricom accepted the B2C submission.
        #
        # Save the ConversationID and response details.
        # ----------------------------------------------------

        try:

            current = (
                db.session.query(
                    MpesaWithdrawal
                )
                .with_for_update()
                .filter(
                    MpesaWithdrawal.id
                    == withdrawal.id
                )
                .first()
            )

            if not current:
                raise RuntimeError(
                    "withdrawal record disappeared"
                )

            current.status = "submitted"

            conversation_id = (
                response.get(
                    "ConversationID"
                )
            )

            if conversation_id:
                current.conversation_id = str(
                    conversation_id
                )

            response_code = (
                response.get(
                    "ResponseCode"
                )
            )

            if response_code is not None:
                try:
                    current.result_code = int(
                        response_code
                    )
                except (
                    TypeError,
                    ValueError,
                ):
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
                "B2C submitted but response could not "
                "be saved | withdrawal=%s | user=%s",
                withdrawal.id,
                uid,
            )

            return jsonify({
                "error": (
                    "B2C request was submitted, "
                    "but response could not be saved"
                ),
                "withdrawal_id": withdrawal.id,
            }), 500

        # ----------------------------------------------------
        # DO NOT mark the transaction completed here.
        #
        # The asynchronous /mpesa/b2c/result callback does
        # that after Safaricom gives the actual result.
        # ----------------------------------------------------

        logger.info(
            "User M-PESA B2C withdrawal submitted | "
            "withdrawal=%s | user=%s | phone=%s | "
            "amount=%s | conversation=%s",
            current.id,
            uid,
            phone,
            amount,
            current.conversation_id,
        )

        return jsonify({
            "message": "M-PESA withdrawal submitted",
            "withdrawal_id": current.id,
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
            "balance": str(
                new_balance
            ),
        }), 202
