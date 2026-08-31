# wallet.py

import logging
from decimal import Decimal, InvalidOperation

from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from betting.models import db, User, Transaction
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
                "data": data,
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

    @app.route(
        "/deposit",
        methods=["POST"],
    )
    @jwt_required()
    def deposit():

        try:
            uid = int(
                get_jwt_identity()
            )
        except (TypeError, ValueError):
            return _error(
                "invalid user identity",
                401,
            )

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

        if amount < MIN_DEPOSIT:
            return _error(
                f"minimum deposit is {MIN_DEPOSIT:.2f}"
            )

        if amount > MAX_DEPOSIT:
            return _error(
                f"maximum deposit is {MAX_DEPOSIT:.2f}"
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

            current_balance = _balance(
                user
            )

            new_balance = (
                current_balance
                + amount
            )

            user.balance = new_balance

            tx = Transaction(
                user_id=uid,
                type="deposit",
                amount=amount,
                balance_after=new_balance,
            )

            db.session.add(tx)

            db.session.commit()

            logger.info(
                "Deposit successful | user=%s | amount=%s | balance=%s",
                uid,
                amount,
                new_balance,
            )

            return _success(
                new_balance
            )

        except Exception as e:

            db.session.rollback()

            logger.exception(
                "Deposit failed for user %s: %s",
                uid,
                e,
            )

            return _error(
                "deposit failed",
                500,
            )


    # ========================================================
    # WITHDRAW
    # ========================================================

    @app.route(
        "/withdraw",
        methods=["POST"],
    )
    @jwt_required()
    def withdraw():

        try:
            uid = int(
                get_jwt_identity()
            )
        except (TypeError, ValueError):
            return _error(
                "invalid user identity",
                401,
            )

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

        if amount < MIN_WITHDRAWAL:
            return _error(
                f"minimum withdrawal is {MIN_WITHDRAWAL:.2f}"
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

            current_balance = _balance(
                user
            )

            if current_balance < amount:

                db.session.rollback()

                return _error(
                    "insufficient funds"
                )

            new_balance = (
                current_balance
                - amount
            )

            user.balance = new_balance

            tx = Transaction(
                user_id=uid,
                type="withdraw",
                amount=amount,
                balance_after=new_balance,
            )

            db.session.add(tx)

            db.session.commit()

            logger.info(
                "Withdrawal successful | user=%s | amount=%s | balance=%s",
                uid,
                amount,
                new_balance,
            )

            return _success(
                new_balance
            )

        except Exception as e:

            db.session.rollback()

            logger.exception(
                "Withdrawal failed for user %s: %s",
                uid,
                e,
            )

            return _error(
                "withdrawal failed",
                500,
            )
