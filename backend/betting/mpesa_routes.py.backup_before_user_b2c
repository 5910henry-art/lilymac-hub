# mpesa_routes.py

import logging
from decimal import Decimal, InvalidOperation

from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from betting.models import (
    db,
    User,
    Transaction,
    MpesaTransaction,
)

from betting.mpesa import (
    normalize_phone,
    stk_push,
)


logger = logging.getLogger(__name__)


# ============================================================
# SETTINGS
# ============================================================

MIN_MPESA_DEPOSIT = Decimal("1.00")
MAX_MPESA_DEPOSIT = Decimal("5000.00")


# ============================================================
# HELPERS
# ============================================================

def _parse_amount(value):
    try:
        amount = Decimal(str(value))
    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):
        return None

    if not amount.is_finite():
        return None

    amount = amount.quantize(
        Decimal("0.01")
    )

    if amount <= 0:
        return None

    return amount


def _error(message, status=400):
    return jsonify({
        "success": False,
        "error": message,
    }), status


# ============================================================
# REGISTER ROUTES
# ============================================================

def register_mpesa_routes(app):

    # ========================================================
    # STK PUSH
    # ========================================================

    @app.route(
        "/mpesa/stkpush",
        methods=["POST"],
    )
    @jwt_required()
    def mpesa_stkpush():

        # ----------------------------------------------------
        # USER
        # ----------------------------------------------------

        try:
            uid = int(
                get_jwt_identity()
            )
        except (
            TypeError,
            ValueError,
        ):
            return _error(
                "invalid user identity",
                401,
            )

        # ----------------------------------------------------
        # REQUEST
        # ----------------------------------------------------

        data = request.get_json(
            silent=True
        ) or {}

        amount = _parse_amount(
            data.get("amount")
        )

        if amount is None:
            return _error(
                "invalid deposit amount"
            )

        if amount < MIN_MPESA_DEPOSIT:
            return _error(
                f"minimum M-PESA deposit is "
                f"{MIN_MPESA_DEPOSIT:.2f}"
            )

        if amount > MAX_MPESA_DEPOSIT:
            return _error(
                f"maximum M-PESA deposit is "
                f"{MAX_MPESA_DEPOSIT:.2f}"
            )

        # ----------------------------------------------------
        # VERIFY USER
        # ----------------------------------------------------

        user = db.session.get(
            User,
            uid,
        )

        if not user:
            return _error(
                "user not found",
                404,
            )

        # ----------------------------------------------------
        # USE REGISTERED ACCOUNT PHONE
        # ----------------------------------------------------

        try:
            phone = normalize_phone(
                user.phone
            )
        except ValueError:
            return _error(
                "account has an invalid phone number",
                400,
            )

        # ----------------------------------------------------
        # CREATE PENDING M-PESA TRANSACTION
        # ----------------------------------------------------

        mpesa_tx = MpesaTransaction(
            user_id=uid,
            amount=amount,
            phone=phone,
            status="pending",
            credited=False,
        )

        try:
            db.session.add(
                mpesa_tx
            )

            db.session.flush()

            # Internal reference.
            account_reference = (
                f"LM{mpesa_tx.id}"
            )

            # ------------------------------------------------
            # SEND STK PUSH
            # ------------------------------------------------

            response = stk_push(
                phone=phone,
                amount=amount,
                account_reference=account_reference,
                transaction_description=(
                    "Lilymac wallet deposit"
                ),
            )

            merchant_request_id = response.get(
                "MerchantRequestID"
            )

            checkout_request_id = response.get(
                "CheckoutRequestID"
            )

            response_code = response.get(
                "ResponseCode"
            )

            response_description = response.get(
                "ResponseDescription"
            )

            # Safaricom accepted the request only
            # if we received the request IDs.
            if not checkout_request_id:
                mpesa_tx.status = "failed"

                mpesa_tx.result_description = (
                    response_description
                    or response.get(
                        "errorMessage"
                    )
                    or "STK request was not accepted"
                )

                mpesa_tx.result_code = (
                    int(response_code)
                    if str(response_code).isdigit()
                    else None
                )

                db.session.commit()

                return _error(
                    mpesa_tx.result_description,
                    502,
                )

            mpesa_tx.merchant_request_id = (
                merchant_request_id
            )

            mpesa_tx.checkout_request_id = (
                checkout_request_id
            )

            mpesa_tx.result_description = (
                response_description
            )

            if (
                response_code is not None
                and str(response_code).isdigit()
            ):
                mpesa_tx.result_code = int(
                    response_code
                )

            db.session.commit()

            logger.info(
                "M-PESA STK initiated | "
                "user=%s | amount=%s | "
                "checkout=%s",
                uid,
                amount,
                checkout_request_id,
            )

            return jsonify({
                "success": True,
                "message": (
                    "M-PESA payment request sent. "
                    "Enter your M-PESA PIN."
                ),
                "data": {
                    "transaction_id": mpesa_tx.id,
                    "checkout_request_id": (
                        checkout_request_id
                    ),
                    "merchant_request_id": (
                        merchant_request_id
                    ),
                    "amount": float(amount),
                    "phone": phone,
                    "status": "pending",
                },
            })

        except Exception as exc:

            db.session.rollback()

            logger.exception(
                "M-PESA STK initiation failed "
                "| user=%s | amount=%s | error=%s",
                uid,
                amount,
                exc,
            )

            return _error(
                "unable to initiate M-PESA payment",
                502,
            )

    # ========================================================
    # M-PESA CALLBACK
    # ========================================================

    @app.route(
        "/mpesa/callback",
        methods=["POST"],
    )
    def mpesa_callback():

        data = request.get_json(
            silent=True
        ) or {}

        logger.info(
            "M-PESA callback received: %s",
            data,
        )

        try:

            body = data.get(
                "Body",
                {},
            )

            callback = body.get(
                "stkCallback",
                {},
            )

            merchant_request_id = callback.get(
                "MerchantRequestID"
            )

            checkout_request_id = callback.get(
                "CheckoutRequestID"
            )

            result_code = callback.get(
                "ResultCode"
            )

            result_description = callback.get(
                "ResultDesc"
            )

            if not checkout_request_id:
                logger.warning(
                    "M-PESA callback missing "
                    "CheckoutRequestID"
                )

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted",
                })

            # ------------------------------------------------
            # LOCK M-PESA TRANSACTION
            # ------------------------------------------------

            mpesa_tx = (
                db.session.query(
                    MpesaTransaction
                )
                .with_for_update()
                .filter(
                    MpesaTransaction.checkout_request_id
                    == checkout_request_id
                )
                .first()
            )

            if not mpesa_tx:

                logger.warning(
                    "Unknown M-PESA CheckoutRequestID: %s",
                    checkout_request_id,
                )

                # Return success to Safaricom so the
                # callback is not repeatedly retried.
                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted",
                })

            # ------------------------------------------------
            # IDEMPOTENCY CHECK
            # ------------------------------------------------

            if mpesa_tx.credited:

                logger.warning(
                    "Duplicate M-PESA callback ignored | "
                    "transaction=%s | checkout=%s",
                    mpesa_tx.id,
                    checkout_request_id,
                )

                db.session.commit()

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted",
                })

            # ------------------------------------------------
            # STORE CALLBACK RESULT
            # ------------------------------------------------

            try:
                mpesa_tx.result_code = int(
                    result_code
                )
            except (
                TypeError,
                ValueError,
            ):
                mpesa_tx.result_code = None

            mpesa_tx.result_description = (
                result_description
            )

            if merchant_request_id:
                mpesa_tx.merchant_request_id = (
                    merchant_request_id
                )

            # ------------------------------------------------
            # FAILED / CANCELLED PAYMENT
            # ------------------------------------------------

            if result_code != 0:

                mpesa_tx.status = (
                    "cancelled"
                    if result_code == 1032
                    else "failed"
                )

                db.session.commit()

                logger.info(
                    "M-PESA payment failed | "
                    "transaction=%s | code=%s",
                    mpesa_tx.id,
                    result_code,
                )

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted",
                })

            # ------------------------------------------------
            # SUCCESSFUL PAYMENT
            # ------------------------------------------------

            callback_items = (
                callback.get(
                    "CallbackMetadata",
                    {},
                )
                .get("Item", [])
            )

            metadata = {}

            for item in callback_items:

                name = item.get("Name")

                if name:
                    metadata[name] = item.get(
                        "Value"
                    )

            mpesa_receipt = metadata.get(
                "MpesaReceiptNumber"
            )

            callback_amount = metadata.get(
                "Amount"
            )

            callback_phone = metadata.get(
                "PhoneNumber"
            )

            # ------------------------------------------------
            # RECEIPT IS REQUIRED
            # ------------------------------------------------

            if not mpesa_receipt:

                logger.error(
                    "Successful M-PESA callback "
                    "without receipt | transaction=%s",
                    mpesa_tx.id,
                )

                mpesa_tx.status = "failed"
                mpesa_tx.result_description = (
                    "Successful callback missing "
                    "M-PESA receipt"
                )

                db.session.commit()

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted",
                })

            # ------------------------------------------------
            # DUPLICATE RECEIPT PROTECTION
            # ------------------------------------------------

            existing_receipt = (
                db.session.query(
                    MpesaTransaction
                )
                .filter(
                    MpesaTransaction.mpesa_receipt
                    == str(mpesa_receipt),
                    MpesaTransaction.id
                    != mpesa_tx.id,
                )
                .first()
            )

            if existing_receipt:

                logger.error(
                    "Duplicate M-PESA receipt detected | "
                    "receipt=%s | transaction=%s | "
                    "existing=%s",
                    mpesa_receipt,
                    mpesa_tx.id,
                    existing_receipt.id,
                )

                mpesa_tx.status = "failed"
                mpesa_tx.result_description = (
                    "Duplicate M-PESA receipt"
                )

                db.session.commit()

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted",
                })

            # ------------------------------------------------
            # AMOUNT VERIFICATION
            # ------------------------------------------------

            try:
                callback_amount_decimal = (
                    Decimal(str(callback_amount))
                    .quantize(Decimal("0.01"))
                )
            except (
                InvalidOperation,
                ValueError,
                TypeError,
            ):
                callback_amount_decimal = None

            if (
                callback_amount_decimal is None
                or callback_amount_decimal
                != Decimal(mpesa_tx.amount)
            ):

                logger.error(
                    "M-PESA amount mismatch | "
                    "transaction=%s | expected=%s | "
                    "received=%s",
                    mpesa_tx.id,
                    mpesa_tx.amount,
                    callback_amount,
                )

                mpesa_tx.status = "failed"
                mpesa_tx.result_description = (
                    "M-PESA amount mismatch"
                )

                db.session.commit()

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted",
                })

            # ------------------------------------------------
            # PHONE VERIFICATION
            # ------------------------------------------------

            if callback_phone:

                try:
                    normalized_callback_phone = (
                        normalize_phone(
                            callback_phone
                        )
                    )
                except ValueError:
                    normalized_callback_phone = None

                if (
                    normalized_callback_phone
                    and normalized_callback_phone
                    != mpesa_tx.phone
                ):

                    logger.error(
                        "M-PESA phone mismatch | "
                        "transaction=%s | expected=%s | "
                        "received=%s",
                        mpesa_tx.id,
                        mpesa_tx.phone,
                        normalized_callback_phone,
                    )

                    mpesa_tx.status = "failed"
                    mpesa_tx.result_description = (
                        "M-PESA phone mismatch"
                    )

                    db.session.commit()

                    return jsonify({
                        "ResultCode": 0,
                        "ResultDesc": "Accepted",
                    })

            # ------------------------------------------------
            # LOCK USER
            # ------------------------------------------------

            user = (
                db.session.query(User)
                .with_for_update()
                .filter(
                    User.id
                    == mpesa_tx.user_id
                )
                .first()
            )

            if not user:

                logger.error(
                    "M-PESA user missing | "
                    "transaction=%s | user=%s",
                    mpesa_tx.id,
                    mpesa_tx.user_id,
                )

                mpesa_tx.status = "failed"
                mpesa_tx.result_description = (
                    "Wallet user not found"
                )

                db.session.commit()

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Accepted",
                })

            # ------------------------------------------------
            # CREDIT WALLET
            # ------------------------------------------------

            current_balance = Decimal(
                user.balance or 0
            ).quantize(
                Decimal("0.01")
            )

            amount = Decimal(
                mpesa_tx.amount
            ).quantize(
                Decimal("0.01")
            )

            new_balance = (
                current_balance + amount
            )

            user.balance = new_balance

            # ------------------------------------------------
            # CREATE WALLET TRANSACTION
            # ------------------------------------------------

            wallet_tx = Transaction(
                user_id=user.id,
                type="mpesa_deposit",
                amount=amount,
                balance_after=new_balance,
                description=(
                    "M-PESA wallet deposit"
                ),
                reference=str(
                    mpesa_receipt
                ),
                status="completed",
            )

            db.session.add(
                wallet_tx
            )

            # ------------------------------------------------
            # MARK M-PESA TRANSACTION CREDITED
            # ------------------------------------------------

            mpesa_tx.mpesa_receipt = str(
                mpesa_receipt
            )

            mpesa_tx.status = "success"
            mpesa_tx.credited = True

            db.session.commit()

            logger.info(
                "M-PESA wallet credit SUCCESS | "
                "transaction=%s | user=%s | "
                "amount=%s | receipt=%s | "
                "balance=%s",
                mpesa_tx.id,
                user.id,
                amount,
                mpesa_receipt,
                new_balance,
            )

            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Accepted",
            })

        except Exception as exc:

            db.session.rollback()

            logger.exception(
                "M-PESA callback processing failed: %s",
                exc,
            )

            # Important:
            # Safaricom should receive a valid response.
            return jsonify({
                "ResultCode": 0,
                "ResultDesc": "Accepted",
            })
