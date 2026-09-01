# backend/betting/auth.py

import logging
import os

from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity,
)
from passlib.hash import pbkdf2_sha256

from betting.models import (
    db,
    User,
    BetSlip,
    BetSelection,
    Bet,
    Transaction,
    Bookmark,
)


# ============================================================
# BLUEPRINT
# ============================================================

auth_bp = Blueprint("auth", __name__)

logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

# ADMIN_SECRET must be configured in the production environment.
# Never hard-code the real secret in this file.
ADMIN_SECRET = os.environ.get("ADMIN_SECRET")

if not ADMIN_SECRET:
    logger.warning(
        "ADMIN_SECRET is not configured. "
        "Administrative password-reset functionality is disabled."
    )


# ============================================================
# PASSWORD POLICY
# ============================================================

MIN_PASSWORD_LENGTH = 8


def validate_password(password):
    """
    Validate password before hashing.

    Returns:
        None if valid.
        Error message string if invalid.
    """

    if not isinstance(password, str):
        return "password must be a string"

    if not password:
        return "password is required"

    if len(password) < MIN_PASSWORD_LENGTH:
        return (
            f"password must be at least "
            f"{MIN_PASSWORD_LENGTH} characters"
        )

    if len(password) > 128:
        return "password is too long"

    return None


# ============================================================
# PHONE NORMALIZATION
# ============================================================

def normalize_phone(phone):
    """
    Normalize the phone number used as the account identifier.
    """

    if phone is None:
        return None

    if not isinstance(phone, str):
        phone = str(phone)

    phone = phone.strip()

    return phone if phone else None


# ============================================================
# SIGNUP
# ============================================================

@auth_bp.route("/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}

    phone = normalize_phone(data.get("phone"))
    password = data.get("password")
    admin_token = data.get("admin_token")

    # --------------------------------------------------------
    # Validate required fields
    # --------------------------------------------------------

    if not phone or not password:
        return jsonify({
            "success": False,
            "error": "phone and password required",
        }), 400

    password_error = validate_password(password)

    if password_error:
        return jsonify({
            "success": False,
            "error": password_error,
        }), 400

    # --------------------------------------------------------
    # Check existing account
    # --------------------------------------------------------

    existing_user = (
        db.session
        .query(User)
        .filter_by(phone=phone)
        .first()
    )

    if existing_user:
        return jsonify({
            "success": False,
            "error": "phone exists",
        }), 400

    # --------------------------------------------------------
    # Determine admin status
    # --------------------------------------------------------

    is_admin = bool(
        ADMIN_SECRET
        and admin_token
        and admin_token == ADMIN_SECRET
    )

    # --------------------------------------------------------
    # Create user
    # --------------------------------------------------------

    try:
        hashed_password = pbkdf2_sha256.hash(password)

        user = User(
            phone=phone,
            password=hashed_password,
            is_admin=is_admin,
        )

        db.session.add(user)
        db.session.commit()

        # ----------------------------------------------------
        # Create JWT
        # ----------------------------------------------------

        token = create_access_token(
            identity=str(user.id)
        )

        return jsonify({
            "success": True,
            "data": {
                "token": token,
            },
        }), 201

    except Exception:
        db.session.rollback()

        logger.exception(
            "Failed to create user account"
        )

        return jsonify({
            "success": False,
            "error": "unable to create account",
        }), 500


# ============================================================
# LOGIN
# ============================================================

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}

    phone = normalize_phone(data.get("phone"))
    password = data.get("password")

    if not phone or not password:
        return jsonify({
            "success": False,
            "error": "phone and password required",
        }), 400

    user = (
        db.session
        .query(User)
        .filter_by(phone=phone)
        .first()
    )

    # Do not reveal whether a phone number exists.
    if not user:
        return jsonify({
            "success": False,
            "error": "invalid credentials",
        }), 401

    try:
        password_valid = pbkdf2_sha256.verify(
            password,
            user.password,
        )
    except Exception:
        password_valid = False

    if not password_valid:
        return jsonify({
            "success": False,
            "error": "invalid credentials",
        }), 401

    # --------------------------------------------------------
    # Create JWT
    # --------------------------------------------------------

    token = create_access_token(
        identity=str(user.id)
    )

    return jsonify({
        "success": True,
        "data": {
            "token": token,
        },
    })


# ============================================================
# CURRENT USER
# ============================================================

@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    try:
        uid = int(get_jwt_identity())
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "invalid authentication identity",
        }), 401

    user = db.session.get(User, uid)

    if not user:
        return jsonify({
            "success": False,
            "error": "user not found",
        }), 404

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    total_bets = (
        db.session
        .query(BetSlip)
        .filter_by(user_id=uid)
        .count()
    )

    transactions_count = (
        db.session
        .query(Transaction)
        .filter_by(user_id=uid)
        .count()
    )

    balance = float(user.balance or 0)

    # --------------------------------------------------------
    # Created timestamp
    # --------------------------------------------------------

    created_at = None

    if hasattr(user, "created") and user.created:
        try:
            created_at = user.created.isoformat()
        except Exception:
            created_at = None

    return jsonify({
        "success": True,
        "data": {
            "user": {
                "id": user.id,
                "phone": user.phone,
                "created_at": created_at,
            },
            "total_bets": total_bets,
            "balance": balance,
            "transactions": transactions_count,
        },
    })


# ============================================================
# CHANGE PASSWORD
# ============================================================

@auth_bp.route("/change_password", methods=["POST"])
@jwt_required()
def change_password():

    try:
        uid = int(get_jwt_identity())
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "invalid authentication identity",
        }), 401

    user = db.session.get(User, uid)

    if not user:
        return jsonify({
            "success": False,
            "error": "user not found",
        }), 404

    data = request.get_json(silent=True) or {}

    old_password = data.get("old_password")
    new_password = data.get("new_password")

    # --------------------------------------------------------
    # Validate passwords
    # --------------------------------------------------------

    if not old_password or not new_password:
        return jsonify({
            "success": False,
            "error": "old_password and new_password required",
        }), 400

    password_error = validate_password(new_password)

    if password_error:
        return jsonify({
            "success": False,
            "error": password_error,
        }), 400

    # --------------------------------------------------------
    # Verify old password
    # --------------------------------------------------------

    try:
        old_password_valid = pbkdf2_sha256.verify(
            old_password,
            user.password,
        )
    except Exception:
        old_password_valid = False

    if not old_password_valid:
        return jsonify({
            "success": False,
            "error": "wrong password",
        }), 400

    # --------------------------------------------------------
    # Prevent reusing the same password
    # --------------------------------------------------------

    try:
        same_password = pbkdf2_sha256.verify(
            new_password,
            user.password,
        )
    except Exception:
        same_password = False

    if same_password:
        return jsonify({
            "success": False,
            "error": "new password must be different",
        }), 400

    # --------------------------------------------------------
    # Update password
    # --------------------------------------------------------

    try:
        user.password = pbkdf2_sha256.hash(
            new_password
        )

        db.session.commit()

        return jsonify({
            "success": True,
            "msg": "password changed",
        })

    except Exception:
        db.session.rollback()

        logger.exception(
            "Failed to change password for user %s",
            uid,
        )

        return jsonify({
            "success": False,
            "error": "unable to change password",
        }), 500


# ============================================================
# RESET PASSWORD
# ============================================================
#
# IMPORTANT:
#
# The old implementation allowed anyone who knew a phone
# number to reset that user's password.
#
# Until a proper OTP / SMS / email reset-token system exists,
# this endpoint requires the ADMIN_SECRET.
#
# Required JSON:
#
# {
#     "phone": "07XXXXXXXX",
#     "new_password": "newpassword123",
#     "admin_token": "ADMIN_SECRET"
# }
#
# Never expose ADMIN_SECRET in the frontend.
#
# ============================================================

@auth_bp.route("/reset_password", methods=["POST"])
def reset_password():
    data = request.get_json(silent=True) or {}

    phone = normalize_phone(data.get("phone"))
    new_password = data.get("new_password")
    admin_token = data.get("admin_token")

    # --------------------------------------------------------
    # Validate required fields
    # --------------------------------------------------------

    if not phone or not new_password:
        return jsonify({
            "success": False,
            "error": "phone and new_password required",
        }), 400

    password_error = validate_password(new_password)

    if password_error:
        return jsonify({
            "success": False,
            "error": password_error,
        }), 400

    # --------------------------------------------------------
    # ADMIN_SECRET must exist
    # --------------------------------------------------------

    if not ADMIN_SECRET:
        logger.error(
            "Password reset attempted but ADMIN_SECRET "
            "is not configured."
        )

        return jsonify({
            "success": False,
            "error": "password reset is unavailable",
        }), 503

    # --------------------------------------------------------
    # Verify admin token
    # --------------------------------------------------------

    if not admin_token or admin_token != ADMIN_SECRET:
        return jsonify({
            "success": False,
            "error": "unauthorized",
        }), 401

    # --------------------------------------------------------
    # Find user
    # --------------------------------------------------------

    user = (
        db.session
        .query(User)
        .filter_by(phone=phone)
        .first()
    )

    if not user:
        return jsonify({
            "success": False,
            "error": "user not found",
        }), 404

    # --------------------------------------------------------
    # Prevent same password
    # --------------------------------------------------------

    try:
        if pbkdf2_sha256.verify(
            new_password,
            user.password,
        ):
            return jsonify({
                "success": False,
                "error": "new password must be different",
            }), 400
    except Exception:
        pass

    # --------------------------------------------------------
    # Reset password
    # --------------------------------------------------------

    try:
        user.password = pbkdf2_sha256.hash(
            new_password
        )

        db.session.commit()

        logger.warning(
            "Password reset performed for user %s",
            user.id,
        )

        return jsonify({
            "success": True,
            "msg": "password reset",
        })

    except Exception:
        db.session.rollback()

        logger.exception(
            "Failed to reset password for user %s",
            user.id,
        )

        return jsonify({
            "success": False,
            "error": "unable to reset password",
        }), 500


# ============================================================
# DELETE ACCOUNT
# ============================================================

@auth_bp.route("/delete_account", methods=["DELETE"])
@jwt_required()
def delete_account():

    # --------------------------------------------------------
    # Get authenticated user
    # --------------------------------------------------------

    try:
        uid = int(get_jwt_identity())
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "invalid authentication identity",
        }), 401

    user = db.session.get(User, uid)

    if not user:
        return jsonify({
            "success": False,
            "error": "user not found",
        }), 404

    try:

        # ----------------------------------------------------
        # Collect bookmark IDs before deleting bet slips.
        # ----------------------------------------------------

        bookmark_ids = set()

        user_betslips = list(user.betslips)

        for slip in user_betslips:

            for selection in list(slip.selections):

                bookmark_id = getattr(
                    selection,
                    "bookmark_id",
                    None,
                )

                if bookmark_id is not None:
                    bookmark_ids.add(bookmark_id)

        # ----------------------------------------------------
        # Delete bet slips
        # ----------------------------------------------------

        for slip in user_betslips:
            db.session.delete(slip)

        # ----------------------------------------------------
        # Delete direct bets
        # ----------------------------------------------------

        for bet in list(user.bets):
            db.session.delete(bet)

        # ----------------------------------------------------
        # Delete transactions
        # ----------------------------------------------------

        for transaction in list(user.transactions):
            db.session.delete(transaction)

        # ----------------------------------------------------
        # Flush changes
        # ----------------------------------------------------

        db.session.flush()

        # ----------------------------------------------------
        # Delete orphaned bookmarks.
        #
        # bookmark_id refers to Bookmark.id, so delete using
        # the Bookmark primary key rather than match_id.
        # ----------------------------------------------------

        for bookmark_id in bookmark_ids:

            remaining = (
                db.session
                .query(BetSelection)
                .filter_by(bookmark_id=bookmark_id)
                .count()
            )

            if remaining == 0:

                (
                    db.session
                    .query(Bookmark)
                    .filter_by(id=bookmark_id)
                    .delete(
                        synchronize_session=False
                    )
                )

        # ----------------------------------------------------
        # Delete user
        # ----------------------------------------------------

        db.session.delete(user)

        db.session.commit()

        logger.info(
            "Deleted user account %s and related data",
            uid,
        )

        return jsonify({
            "success": True,
            "msg": "user and all related data deleted",
        })

    except Exception:

        db.session.rollback()

        logger.exception(
            "Failed to delete account for user %s",
            uid,
        )

        return jsonify({
            "success": False,
            "error": "unable to delete account",
        }), 500
