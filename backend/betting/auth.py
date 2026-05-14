# auth.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from betting.models import db, User, BetSlip, BetSelection, Bet, Transaction, Bookmark
from passlib.hash import pbkdf2_sha256
import os

auth_bp = Blueprint("auth", __name__)

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "adminsecret_fallback_do_not_use_in_production")


@auth_bp.route("/signup", methods=["POST"])
def signup():
    data = request.json or {}
    phone = data.get("phone")
    password = data.get("password")
    admin_token = data.get("admin_token")

    if not phone or not password:
        return jsonify({"success": False, "error": "phone and password required"}), 400

    if db.session.query(User).filter_by(phone=phone).first():
        return jsonify({"success": False, "error": "phone exists"}), 400

    is_admin = admin_token == ADMIN_SECRET

    hashed_password = pbkdf2_sha256.hash(password)
    user = User(phone=phone, password=hashed_password, is_admin=is_admin)
    db.session.add(user)
    db.session.commit()

    # Create JWT token for the new user
    token = create_access_token(identity=str(user.id))
    return jsonify({"success": True, "data": {"token": token}}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.json or {}
    phone = data.get("phone")
    password = data.get("password")

    if not phone or not password:
        return jsonify({"success": False, "error": "phone and password required"}), 400

    user = db.session.query(User).filter_by(phone=phone).first()
    if not user or not pbkdf2_sha256.verify(password, user.password):
        return jsonify({"success": False, "error": "invalid credentials"}), 401

    token = create_access_token(identity=str(user.id))
    return jsonify({"success": True, "data": {"token": token}})


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    uid = int(get_jwt_identity())
    user = db.session.get(User, uid)
    if not user:
        return jsonify({"success": False, "error": "user not found"}), 404

    total_bets = db.session.query(BetSlip).filter_by(user_id=uid).count()
    balance = float(user.balance or 0)
    transactions_count = db.session.query(Transaction).filter_by(user_id=uid).count()

    return jsonify({
        "success": True,
        "data": {
            "user": {
                "id": user.id,
                "phone": user.phone,
                "created_at": user.created.isoformat() if hasattr(user, "created") else None
            },
            "total_bets": total_bets,
            "balance": balance,
            "transactions": transactions_count
        }
    })


@auth_bp.route("/change_password", methods=["POST"])
@jwt_required()
def change_password():
    uid = int(get_jwt_identity())
    data = request.json or {}
    user = db.session.get(User, uid)
    if not user:
        return jsonify({"success": False, "error": "user not found"}), 404

    if not pbkdf2_sha256.verify(data.get("old_password", ""), user.password):
        return jsonify({"success": False, "error": "wrong password"}), 400

    user.password = pbkdf2_sha256.hash(data.get("new_password"))
    db.session.commit()
    return jsonify({"success": True, "msg": "password changed"})


@auth_bp.route("/reset_password", methods=["POST"])
def reset_password():
    data = request.json or {}
    phone = data.get("phone")
    new_password = data.get("new_password")

    if not phone or not new_password:
        return jsonify({"success": False, "error": "phone and new_password required"}), 400

    user = db.session.query(User).filter_by(phone=phone).first()
    if not user:
        return jsonify({"success": False, "error": "user not found"}), 404

    user.password = pbkdf2_sha256.hash(new_password)
    db.session.commit()
    return jsonify({"success": True, "msg": "password reset"})


@auth_bp.route("/delete_account", methods=["DELETE"])
@jwt_required()
def delete_account():
    uid = int(get_jwt_identity())
    user = db.session.get(User, uid)
    if not user:
        return jsonify({"success": False, "error": "user not found"}), 404

    try:
        bookmark_ids = set()
        user_betslips = list(user.betslips)
        for slip in user_betslips:
            for sel in list(slip.selections):
                try:
                    bookmark_ids.add(sel.bookmark_id)
                except Exception:
                    pass

        for slip in user_betslips:
            db.session.delete(slip)

        for bet in list(user.bets):
            db.session.delete(bet)

        for tx in list(user.transactions):
            db.session.delete(tx)

        db.session.flush()

        for bid in bookmark_ids:
            remaining = db.session.query(BetSelection).filter_by(bookmark_id=bid).count()
            if remaining == 0:
                db.session.query(Bookmark).filter_by(match_id=bid).delete(synchronize_session=False)

        db.session.delete(user)
        db.session.commit()

        return jsonify({"success": True, "msg": "user and all related data deleted"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
