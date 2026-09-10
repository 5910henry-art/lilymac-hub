# backend/betting/wallet.py

import logging
import os
from decimal import Decimal, InvalidOperation
from uuid import uuid4

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
    B2CSubmissionError,
)

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

        except Exception as exc:

            logger.exception(
                "Error loading transactions for user %s: %s",
                uid,
                exc,
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

        except Exception as exc:

            logger.exception(
                "Error loading balance history for user %s: %s",
                uid,
                exc,
            )

            return _error(
                "failed to load balance history",
                500,
            )


    # ========================================================
    # DEPOSIT
    # ========================================================
    #
    # Direct wallet crediting is disabled.
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
    # M-PESA WITHDRAWAL REFUND HELPER
    # ========================================================

    def _refund_withdrawal(
        withdrawal_id,
        uid,
        failure_description,
    ):
        """
        Refund a reserved withdrawal.

        This function is deliberately idempotent.

        It locks both the withdrawal and user, verifies that the
        withdrawal has not already been finalized, finds the
        original pending transaction, refunds the wallet, marks
        the original transaction failed, and creates a separate
        refund transaction.

        Returns:
            (success, balance, message)
        """

        try:

            current = (
                db.session.query(
                    MpesaWithdrawal
                )
                .with_for_update()
                .filter(
                    MpesaWithdrawal.id
                    == withdrawal_id
                )
                .first()
            )

            if not current:
                raise RuntimeError(
                    "withdrawal record not found"
                )

            # ------------------------------------------------
            # If callback already finalized this withdrawal,
            # NEVER refund it again.
            # ------------------------------------------------

            if current.status in (
                "success",
                "failed",
                "timeout",
            ):
                locked_user = (
                    db.session.query(User)
                    .filter(
                        User.id == uid
                    )
                    .first()
                )

                balance = (
                    _balance(locked_user)
                    if locked_user
                    else Decimal("0.00")
                )

                db.session.rollback()

                return (
                    True,
                    balance,
                    "withdrawal already finalized",
                )

            # ------------------------------------------------
            # Lock user.
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Find original withdrawal transaction.
            #
            # Correlation is:
            #
            # user_id
            # reference
            # type = mpesa_withdrawal
            # ------------------------------------------------

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

            # ------------------------------------------------
            # If transaction was already finalized, do not
            # create another refund.
            # ------------------------------------------------

            if original_tx.status != "pending":

                balance = _balance(
                    locked_user
                )

                db.session.rollback()

                return (
                    True,
                    balance,
                    "withdrawal transaction already finalized",
                )

            # ------------------------------------------------
            # Validate refund amount.
            # ------------------------------------------------

            refund_amount = _parse_amount(
                current.amount
            )

            if refund_amount is None:
                raise RuntimeError(
                    "invalid withdrawal amount during refund"
                )

            # ------------------------------------------------
            # Refund reserved wallet money.
            # ------------------------------------------------

            locked_user.balance = (
                _balance(locked_user)
                + refund_amount
            )

            # ------------------------------------------------
            # Mark original withdrawal transaction failed.
            # ------------------------------------------------

            original_tx.status = "failed"

            original_tx.description = (
                "M-PESA withdrawal submission failed"
            )

            # ------------------------------------------------
            # Create explicit refund transaction.
            # ------------------------------------------------

            refund_tx = Transaction(
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

            db.session.add(
                refund_tx
            )

            # ------------------------------------------------
            # Mark withdrawal failed.
            # ------------------------------------------------

            current.status = "failed"

            current.result_description = str(
                failure_description
            )[:255]

            db.session.commit()

            return (
                True,
                _balance(locked_user),
                "withdrawal refunded",
            )

        except Exception as exc:

            db.session.rollback()

            logger.exception(
                "M-PESA withdrawal refund failed | "
                "withdrawal=%s | user=%s | error=%s",
                withdrawal_id,
                uid,
                exc,
            )

            return (
                False,
                Decimal("0.00"),
                str(exc),
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
        # Identify authenticated user.
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
        # Read request.
        #
        # Frontend sends:
        #
        # {
        #     "amount": 100
        # }
        #
        # Phone comes from User.phone in production.
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
        # B2C limits.
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
        # Generate correlation identifiers BEFORE reservation.
        # ----------------------------------------------------

        reference = (
            f"mpesa-withdraw-{uuid4().hex}"
        )

        originator_conversation_id = (
            f"LILYMAC-USER-{uuid4().hex}"
        )

        # Keep this outside the DB transaction so it is
        # available for later logging/error handling.
        withdrawal_id = None

        # ----------------------------------------------------
        # RESERVE USER MONEY FIRST.
        #
        # User row is locked to prevent two simultaneous
        # withdrawals from spending the same balance.
        # ----------------------------------------------------

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
            # Use configured Safaricom test recipient.
            #
            # PRODUCTION:
            # Use authenticated user's registered phone.
            #
            # Never trust a phone supplied by frontend.
            # ------------------------------------------------

            if (
                os.getenv(
                    "MPESA_ENV",
                    ""
                ).lower()
                == "sandbox"
            ):

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
            # Check balance while user row is locked.
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
            # Reserve money.
            # ------------------------------------------------

            new_balance = (
                current_balance
                - amount
            )

            user.balance = new_balance

            # ------------------------------------------------
            # Create wallet transaction.
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
            # Create B2C withdrawal tracking record.
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
            # Flush so withdrawal.id exists before commit.
            # ------------------------------------------------

            db.session.flush()

            withdrawal_id = withdrawal.id

            # ------------------------------------------------
            # COMMIT BEFORE CONTACTING SAFARICOM.
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

        # ====================================================
        # SUBMIT B2C REQUEST
        # ====================================================

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

        # ====================================================
        # EXPLICIT B2C SUBMISSION ERROR
        # ====================================================

        except B2CSubmissionError as exc:

            logger.exception(
                "M-PESA B2C submission error | "
                "withdrawal=%s | user=%s | "
                "ambiguous=%s | error=%s",
                withdrawal_id,
                uid,
                exc.ambiguous,
                exc,
            )

            # ------------------------------------------------
            # AMBIGUOUS:
            #
            # The request may have reached Safaricom.
            #
            # NEVER refund automatically.
            #
            # Keep funds reserved until callback/timeout
            # resolves the transaction.
            # ------------------------------------------------

            if exc.ambiguous:

                try:

                    current = (
                        db.session.query(
                            MpesaWithdrawal
                        )
                        .with_for_update()
                        .filter(
                            MpesaWithdrawal.id
                            == withdrawal_id
                        )
                        .first()
                    )

                    if not current:
                        raise RuntimeError(
                            "withdrawal record disappeared"
                        )

                    if current.status not in (
                        "success",
                        "failed",
                        "timeout",
                    ):

                        current.status = (
                            "submission_unknown"
                        )

                        current.result_description = (
                            str(exc)[:255]
                        )

                        db.session.commit()

                    else:
                        db.session.rollback()

                    locked_user = (
                        db.session.query(User)
                        .filter(
                            User.id == uid
                        )
                        .first()
                    )

                    balance = (
                        _balance(locked_user)
                        if locked_user
                        else Decimal("0.00")
                    )

                    return jsonify({
                        "success": True,
                        "withdrawal_id": current.id,
                        "reference": current.reference,
                        "status": current.status,
                        "message": (
                            "M-PESA submission status is "
                            "unknown. Funds remain reserved "
                            "pending Safaricom callback."
                        ),
                        "balance": str(
                            balance
                        ),
                    }), 202

                except Exception as mark_exc:

                    db.session.rollback()

                    logger.exception(
                        "Failed to mark ambiguous M-PESA "
                        "withdrawal | withdrawal=%s | "
                        "user=%s | error=%s",
                        withdrawal_id,
                        uid,
                        mark_exc,
                    )

                    return jsonify({
                        "success": False,
                        "error": (
                            "M-PESA submission status is "
                            "unknown; withdrawal remains "
                            "reserved"
                        ),
                        "withdrawal_id": withdrawal_id,
                    }), 202

            # ------------------------------------------------
            # DEFINITE FAILURE:
            #
            # Safaricom definitely did not accept the request.
            #
            # Safe to refund the reservation.
            # ------------------------------------------------

            refund_ok, balance, refund_message = (
                _refund_withdrawal(
                    withdrawal_id=withdrawal_id,
                    uid=uid,
                    failure_description=str(exc),
                )
            )

            if not refund_ok:

                return jsonify({
                    "success": False,
                    "error": (
                        "M-PESA submission failed and "
                        "automatic refund could not be "
                        "completed"
                    ),
                    "withdrawal_id": withdrawal_id,
                }), 500

            return jsonify({
                "success": False,
                "error": (
                    "M-PESA withdrawal request failed"
                ),
                "withdrawal_id": withdrawal_id,
                "status": "failed",
                "balance": str(balance),
                "message": refund_message,
            }), 502

        # ====================================================
        # UNEXPECTED SUBMISSION ERROR
        # ====================================================

        except Exception as exc:

            logger.exception(
                "Unexpected M-PESA B2C submission failure | "
                "withdrawal=%s | user=%s | error=%s",
                withdrawal_id,
                uid,
                exc,
            )

            # ------------------------------------------------
            # IMPORTANT:
            #
            # We cannot automatically know whether an unknown
            # exception happened before or after Safaricom
            # received the request.
            #
            # Therefore this remains a conservative/ambiguous
            # state.
            # ------------------------------------------------

            try:

                current = (
                    db.session.query(
                        MpesaWithdrawal
                    )
                    .with_for_update()
                    .filter(
                        MpesaWithdrawal.id
                        == withdrawal_id
                    )
                    .first()
                )

                if not current:
                    raise RuntimeError(
                        "withdrawal record disappeared"
                    )

                if current.status not in (
                    "success",
                    "failed",
                    "timeout",
                ):

                    current.status = (
                        "submission_unknown"
                    )

                    current.result_description = (
                        str(exc)[:255]
                    )

                    db.session.commit()

                else:
                    db.session.rollback()

                return jsonify({
                    "success": True,
                    "withdrawal_id": current.id,
                    "reference": current.reference,
                    "status": current.status,
                    "message": (
                        "M-PESA submission status is "
                        "unknown. Funds remain reserved "
                        "pending Safaricom callback."
                    ),
                }), 202

            except Exception as mark_exc:

                db.session.rollback()

                logger.exception(
                    "Failed to mark unexpected B2C "
                    "submission error | withdrawal=%s | "
                    "user=%s | error=%s",
                    withdrawal_id,
                    uid,
                    mark_exc,
                )

                return jsonify({
                    "success": False,
                    "error": (
                        "M-PESA submission status is "
                        "unknown; withdrawal remains "
                        "reserved"
                    ),
                    "withdrawal_id": withdrawal_id,
                }), 202

        # ====================================================
        # SAFARICOM ACCEPTED THE B2C SUBMISSION
        # ====================================================
        #
        # IMPORTANT:
        #
        # ResponseCode 0 here means the B2C request was accepted
        # for processing. It does NOT mean the user has received
        # the money.
        #
        # Final success comes from:
        #
        #     POST /mpesa/b2c/result
        #
        # ====================================================

        try:

            current = (
                db.session.query(
                    MpesaWithdrawal
                )
                .with_for_update()
                .filter(
                    MpesaWithdrawal.id
                    == withdrawal_id
                )
                .first()
            )

            if not current:
                raise RuntimeError(
                    "withdrawal record disappeared"
                )

            # ------------------------------------------------
            # A callback could theoretically have arrived
            # between submission and this database update.
            #
            # Do not overwrite a finalized status.
            # ------------------------------------------------

            if current.status not in (
                "success",
                "failed",
                "timeout",
            ):

                current.status = "submitted"

                # --------------------------------------------
                # Save ConversationID.
                # --------------------------------------------

                conversation_id = response.get(
                    "ConversationID"
                )

                if conversation_id:
                    current.conversation_id = str(
                        conversation_id
                    )

                # --------------------------------------------
                # Save ResponseCode.
                # --------------------------------------------

                response_code = response.get(
                    "ResponseCode"
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

                # --------------------------------------------
                # Save ResponseDescription.
                # --------------------------------------------

                current.result_description = str(
                    response.get(
                        "ResponseDescription",
                        "B2C request submitted",
                    )
                )[:255]

                db.session.commit()

            else:

                db.session.rollback()

        except Exception as exc:

            db.session.rollback()

            logger.exception(
                "B2C submitted but response could not "
                "be saved | withdrawal=%s | user=%s | "
                "error=%s",
                withdrawal_id,
                uid,
                exc,
            )

            # ------------------------------------------------
            # DO NOT refund here.
            #
            # The request was already submitted to Safaricom.
            # We must wait for callback/timeout.
            # ------------------------------------------------

            return jsonify({
                "success": True,
                "error": (
                    "B2C request was submitted, "
                    "but response could not be saved. "
                    "Funds remain reserved pending "
                    "Safaricom callback."
                ),
                "withdrawal_id": withdrawal_id,
                "reference": reference,
            }), 202

        # ====================================================
        # FINAL RESPONSE
        # ====================================================

        logger.info(
            "User M-PESA B2C withdrawal submitted | "
            "withdrawal=%s | user=%s | phone=%s | "
            "amount=%s | conversation=%s | originator=%s",
            current.id,
            uid,
            phone,
            amount,
            current.conversation_id,
            current.originator_conversation_id,
        )

        return jsonify({
            "success": True,
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
