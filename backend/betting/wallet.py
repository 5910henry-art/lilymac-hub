# wallet.py
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from betting.models import db, User, Transaction
from betting.utils import to_decimal
from decimal import Decimal

MAX_DEPOSIT = Decimal("5000")

def register_wallet_routes(app):

    @app.route("/balance", methods=["GET"])
    @jwt_required()
    def get_balance():
        uid = int(get_jwt_identity())
        user = db.session.get(User, uid)
        if not user:
            return jsonify({"success": False, "error": "user not found"}), 404
        return jsonify({"success": True, "balance": float(user.balance or 0)})

    @app.route("/transactions", methods=["GET"])
    @jwt_required()
    def get_transactions():
        uid = int(get_jwt_identity())
        txs = db.session.query(Transaction).filter_by(user_id=uid).order_by(Transaction.created.desc()).all()
        data = [{
            "id": tx.id,
            "type": tx.type,
            "amount": float(tx.amount),
            "balance_after": float(tx.balance_after),
            "created": tx.created.isoformat() if tx.created else None
        } for tx in txs]
        return jsonify({"success": True, "data": data})

    @app.route("/balance_history", methods=["GET"])
    @jwt_required()
    def get_balance_history():
        uid = int(get_jwt_identity())
        txs = db.session.query(Transaction).filter_by(user_id=uid).order_by(Transaction.created.asc()).all()
        history = [{
            "date": tx.created.isoformat() if tx.created else None,
            "balance": float(tx.balance_after)
        } for tx in txs]
        return jsonify({"success": True, "data": history})

    @app.route("/deposit", methods=["POST"])
    @jwt_required()
    def deposit():
        uid = int(get_jwt_identity())
        data = request.json or {}
        amount = to_decimal(data.get("amount", 0))

        if amount <= 0 or amount > MAX_DEPOSIT:
            return jsonify({"success": False, "error": "invalid deposit amount"}), 400

        with db.session.begin():
            user = db.session.query(User).with_for_update().filter_by(id=uid).first()
            if not user:
                return jsonify({"success": False, "error": "user not found"}), 404

            user.balance = to_decimal(user.balance) + amount

            tx = Transaction(
                user_id=uid,
                type="deposit",
                amount=amount,
                balance_after=user.balance
            )
            db.session.add(tx)

        return jsonify({"success": True, "balance": float(user.balance)})

    @app.route("/withdraw", methods=["POST"])
    @jwt_required()
    def withdraw():
        uid = int(get_jwt_identity())
        data = request.json or {}
        amount = to_decimal(data.get("amount", 0))

        if amount <= 0:
            return jsonify({"success": False, "error": "invalid amount"}), 400

        with db.session.begin():
            user = db.session.query(User).with_for_update().filter_by(id=uid).first()
            if not user:
                return jsonify({"success": False, "error": "user not found"}), 404

            if to_decimal(user.balance) < amount:
                return jsonify({"success": False, "error": "insufficient funds"}), 400

            user.balance = to_decimal(user.balance) - amount

            tx = Transaction(
                user_id=uid,
                type="withdraw",
                amount=amount,
                balance_after=user.balance
            )
            db.session.add(tx)

        return jsonify({"success": True, "balance": float(user.balance)})
