import os
import re
import asyncio
import asyncpg
import logging
import traceback
import functools

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash

from config2 import (
    DATABASE_URL,
    UTC,
    KENYA,
    DB_SCHEMA,
    _convert_named_to_positional,
)

# ============================================================
# APP CONFIG
# ============================================================

app = Flask(__name__)

CORS(
    app,
    resources={
        r"/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        }
    },
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vipadmin")

JWT_SECRET = os.getenv("VIP_JWT_SECRET", "change-this-secret")
JWT_EXPIRY_HOURS = int(os.getenv("VIP_JWT_EXPIRY_HOURS", "24"))

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").strip()
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "").strip()


# ============================================================
# VIP PLANS
# ============================================================

PLAN_ORDER = [
    "daily",
    "weekly",
    "monthly",
    "yearly",
    "annual",
]

PLAN_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
    "yearly": 365,
    "annual": 365,
}

SUBSCRIPTION_QUOTA = {
    "daily": 3,
    "weekly": 5,
    "monthly": 7,
    "yearly": 10,
    "annual": 10,
}

# ============================================================
# JSON LOGGING
# ============================================================

def log_json(level, **data):
    message = str(data)

    if level == "error":
        logger.error(message)
    elif level == "warning":
        logger.warning(message)
    else:
        logger.info(message)


# ============================================================
# POSTGRES HELPERS
# ============================================================
async def vip_query_db(sql, params=None):
    sql, params = _convert_named_to_positional(sql, params or {})

    conn = await asyncpg.connect(
        dsn=DATABASE_URL,
        command_timeout=60,
    )
    await conn.execute(
        f'SET search_path TO "{DB_SCHEMA}", public'
    )

    try:
        records = await conn.fetch(sql, *params)
        return [dict(row) for row in records]
    finally:
        await conn.close()


async def vip_execute_db(sql, params=None):
    sql, params = _convert_named_to_positional(sql, params or {})

    conn = await asyncpg.connect(
        dsn=DATABASE_URL,
        command_timeout=60,
    )

    try:
        await conn.execute(
            f'SET search_path TO "{DB_SCHEMA}", public'
        )
        return await conn.execute(sql, *params)
    finally:
        await conn.close()


async def db_fetch_one(sql, params=None):
    rows = await vip_query_db(sql, params)
    return rows[0] if rows else None


async def db_fetch_all(sql, params=None):
    return await vip_query_db(sql, params)


async def db_execute(sql, params=None):
    return await vip_execute_db(sql, params)



async def _activate_next_vip_entitlement(conn, vip_id):
    """Activate the oldest queued entitlement if none is currently active."""

    active = await conn.fetchrow(
        """
        SELECT id
        FROM vip_subscription_entitlements
        WHERE vip_id = $1
          AND status = 'active'
        FOR UPDATE
        """,
        vip_id,
    )

    if active:
        return None

    queued = await conn.fetchrow(
        """
        SELECT id, plan, duration_days
        FROM vip_subscription_entitlements
        WHERE vip_id = $1
          AND status = 'queued'
        ORDER BY queued_at ASC, id ASC
        LIMIT 1
        FOR UPDATE
        """,
        vip_id,
    )

    if not queued:
        return None

    activated_at = datetime.now(UTC)
    expires_at = activated_at + timedelta(
        days=int(queued["duration_days"])
    )

    entitlement_update = await conn.execute(
        """
        UPDATE vip_subscription_entitlements
        SET
            status = 'active',
            activated_at = $2,
            expires_at = $3
        WHERE id = $1
          AND status = 'queued'
        """,
        queued["id"],
        activated_at,
        expires_at,
    )

    if entitlement_update != "UPDATE 1":
        raise RuntimeError(
            "Entitlement activation failed for entitlement "
            f"{queued['id']}: {entitlement_update}"
        )

    vip_update = await conn.execute(
        """
        UPDATE vip_users
        SET
            subscription = $2,
            subscription_expiry = $3
        WHERE id = $1
        """,
        vip_id,
        queued["plan"],
        expires_at.isoformat(),
    )

    if vip_update != "UPDATE 1":
        raise RuntimeError(
            f"VIP subscription update failed for VIP {vip_id}: "
            f"{vip_update}"
        )

    return {
        "id": queued["id"],
        "plan": queued["plan"],
        "activated_at": activated_at,
        "expires_at": expires_at,
    }


async def db_approve_initial_vip(vip_id):
    """Approve a new VIP and create their first paid entitlement atomically."""

    conn = await asyncpg.connect(
        dsn=DATABASE_URL,
        command_timeout=60,
    )

    try:
        await conn.execute(
            f'SET search_path TO "{DB_SCHEMA}", public'
        )

        async with conn.transaction():
            vip = await conn.fetchrow(
                """
                SELECT id, subscription, approved
                FROM vip_users
                WHERE id = $1
                FOR UPDATE
                """,
                vip_id,
            )

            if not vip:
                return None

            # Repeated approval must never grant another entitlement.
            if vip["approved"]:
                return {
                    "vip_id": vip_id,
                    "already_approved": True,
                }

            existing_entitlement = await conn.fetchval(
                """
                SELECT id
                FROM vip_subscription_entitlements
                WHERE vip_id = $1
                LIMIT 1
                """,
                vip_id,
            )

            if existing_entitlement:
                return {
                    "vip_id": vip_id,
                    "approval_conflict": (
                        "this VIP already has a subscription entitlement"
                    ),
                }

            plan = str(vip["subscription"]).strip().lower()

            if plan not in PLAN_DAYS:
                raise ValueError(
                    f"Invalid subscription plan for VIP {vip_id}: {plan}"
                )

            approval_update = await conn.execute(
                """
                UPDATE vip_users
                SET approved = TRUE
                WHERE id = $1
                """,
                vip_id,
            )

            if approval_update != "UPDATE 1":
                raise RuntimeError(
                    f"Initial VIP approval failed for VIP {vip_id}: "
                    f"{approval_update}"
                )

            await conn.execute(
                """
                INSERT INTO vip_subscription_entitlements (
                    vip_id,
                    plan,
                    duration_days,
                    daily_quota,
                    total_picks,
                    delivered_picks,
                    status
                )
                VALUES ($1, $2, $3, $4, $5, 0, 'queued')
                """,
                vip_id,
                plan,
                PLAN_DAYS[plan],
                SUBSCRIPTION_QUOTA[plan],
                PLAN_DAYS[plan] * SUBSCRIPTION_QUOTA[plan],
            )

            activated = await _activate_next_vip_entitlement(
                conn,
                vip_id,
            )

            return {
                "vip_id": vip_id,
                "already_approved": False,
                "activated": activated,
            }
    finally:
        await conn.close()


async def db_approve_vip_request(request_id):
    """Approve a paid upgrade/renewal and queue its entitlement atomically."""

    conn = await asyncpg.connect(
        dsn=DATABASE_URL,
        command_timeout=60,
    )

    try:
        await conn.execute(
            f'SET search_path TO "{DB_SCHEMA}", public'
        )

        async with conn.transaction():
            req = await conn.fetchrow(
                """
                SELECT id, vip_id, to_plan, status
                FROM vip_upgrade_requests
                WHERE id = $1
                FOR UPDATE
                """,
                request_id,
            )

            if not req or req["status"] != "pending":
                return None

            vip = await conn.fetchrow(
                """
                SELECT id, approved
                FROM vip_users
                WHERE id = $1
                FOR UPDATE
                """,
                req["vip_id"],
            )

            if not vip or not vip["approved"]:
                raise RuntimeError(
                    "Cannot approve a subscription request for an unapproved VIP."
                )

            # Enforce one queued entitlement even if an admin approval
            # bypasses the customer-facing upgrade/renewal routes.
            queued_entitlement = await conn.fetchval(
                """
                SELECT id
                FROM vip_subscription_entitlements
                WHERE vip_id = $1 AND status = 'queued'
                LIMIT 1
                """,
                req["vip_id"],
            )

            if queued_entitlement:
                return {
                    **dict(req),
                    "approval_conflict": (
                        "this VIP already has a paid subscription "
                        "queued to activate"
                    ),
                }

            plan = str(req["to_plan"]).strip().lower()

            if plan not in PLAN_DAYS:
                raise ValueError(
                    f"Invalid subscription plan on request {request_id}: {plan}"
                )

            entitlement_id = await conn.fetchval(
                """
                INSERT INTO vip_subscription_entitlements (
                    vip_id,
                    request_id,
                    plan,
                    duration_days,
                    daily_quota,
                    total_picks,
                    delivered_picks,
                    status
                )
                VALUES ($1, $2, $3, $4, $5, $6, 0, 'queued')
                RETURNING id
                """,
                req["vip_id"],
                request_id,
                plan,
                PLAN_DAYS[plan],
                SUBSCRIPTION_QUOTA[plan],
                PLAN_DAYS[plan] * SUBSCRIPTION_QUOTA[plan],
            )

            if entitlement_id is None:
                raise RuntimeError(
                    f"Entitlement creation failed for request {request_id}"
                )

            result = await conn.execute(
                """
                UPDATE vip_upgrade_requests
                SET
                    status = 'approved',
                    approved_at = CURRENT_TIMESTAMP
                WHERE id = $1
                  AND status = 'pending'
                """,
                request_id,
            )

            if result != "UPDATE 1":
                raise RuntimeError(
                    f"Request approval failed: {result}"
                )

            activated = await _activate_next_vip_entitlement(
                conn,
                req["vip_id"],
            )

            return {
                **dict(req),
                "entitlement_id": entitlement_id,
                "activated": activated,
            }
    finally:
        await conn.close()


# ============================================================
# JWT HELPERS
# ============================================================

def create_token(payload):
    import jwt

    now = datetime.now(UTC)

    token_payload = dict(payload)
    token_payload.update(
        {
            "iat": now,
            "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
        }
    )

    return jwt.encode(
        token_payload,
        JWT_SECRET,
        algorithm="HS256",
    )


def decode_token(token):
    import jwt

    return jwt.decode(
        token,
        JWT_SECRET,
        algorithms=["HS256"],
    )


def get_bearer_token():
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return None

    return auth_header.split(" ", 1)[1].strip()


def vip_required(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        token = get_bearer_token()

        if not token:
            return jsonify({
                "error": "authorization token required"
            }), 401

        try:
            payload = decode_token(token)
            vip_id = payload.get("vip_id")

            if not vip_id:
                return jsonify({
                    "error": "invalid VIP token"
                }), 401

            vip = await db_fetch_one(
                """
                SELECT
                    id,
                    name,
                    number,
                    subscription,
                    subscription_expiry,
                    approved
                FROM vip_users
                WHERE id = :id
                """,
                {"id": vip_id},
            )

            if not vip:
                return jsonify({
                    "error": "VIP user not found"
                }), 401

            if not vip["approved"]:
                return jsonify({
                    "error": "VIP account is not approved"
                }), 403

            request.vip_user = vip

            return await fn(*args, **kwargs)

        except Exception as exc:
            log_json(
                "error",
                event="vip_auth_error",
                error=str(exc),
            )

            return jsonify({
                "error": "invalid or expired token"
            }), 401

    return wrapper


# ============================================================
# VIP WEB PUSH
# ============================================================

@app.get("/vip/push/public-key")
async def vip_push_public_key():
    if not VAPID_PUBLIC_KEY:
        return jsonify({
            "error": "Push notifications are not configured"
        }), 503

    return jsonify({
        "success": True,
        "publicKey": VAPID_PUBLIC_KEY,
    })


@app.post("/vip/push/subscribe")
@vip_required
async def vip_push_subscribe():
    vip = request.vip_user
    data = request.get_json(silent=True) or {}
    subscription = data.get("subscription") or data

    endpoint = str(subscription.get("endpoint") or "").strip()
    keys = subscription.get("keys") or {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()

    if (
        not endpoint.startswith("https://")
        or not p256dh
        or not auth
    ):
        return jsonify({
            "error": "Invalid push subscription"
        }), 400

    await db_execute(
        """
        INSERT INTO vip_push_subscriptions (
            endpoint, number, p256dh, auth, updated_at
        )
        VALUES (
            :endpoint, :number, :p256dh, :auth, CURRENT_TIMESTAMP
        )
        ON CONFLICT (endpoint)
        DO UPDATE SET
            number = EXCLUDED.number,
            p256dh = EXCLUDED.p256dh,
            auth = EXCLUDED.auth,
            updated_at = CURRENT_TIMESTAMP
        """,
        {
            "endpoint": endpoint,
            "number": vip["number"],
            "p256dh": p256dh,
            "auth": auth,
        },
    )

    return jsonify({"success": True})


@app.post("/vip/push/unsubscribe")
@vip_required
async def vip_push_unsubscribe():
    vip = request.vip_user
    data = request.get_json(silent=True) or {}
    endpoint = str(data.get("endpoint") or "").strip()

    if not endpoint.startswith("https://"):
        return jsonify({"error": "Invalid endpoint"}), 400

    await db_execute(
        """
        DELETE FROM vip_push_subscriptions
        WHERE endpoint = :endpoint
          AND number = :number
        """,
        {
            "endpoint": endpoint,
            "number": vip["number"],
        },
    )

    return jsonify({"success": True})


async def send_vip_push(number, title, message, link="/vip"):
    if not all((
        VAPID_PUBLIC_KEY,
        VAPID_PRIVATE_KEY,
        VAPID_SUBJECT,
    )):
        logger.warning("VIP push skipped: VAPID environment variables missing")
        return 0

    try:
        import json
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.exception("pywebpush is not installed")
        return 0

    subscriptions = await db_fetch_all(
        """
        SELECT endpoint, p256dh, auth
        FROM vip_push_subscriptions
        WHERE number = :number
        """,
        {"number": number},
    )

    sent = 0

    for item in subscriptions:
        subscription_info = {
            "endpoint": item["endpoint"],
            "keys": {
                "p256dh": item["p256dh"],
                "auth": item["auth"],
            },
        }

        try:
            await asyncio.to_thread(
                webpush,
                subscription_info=subscription_info,
                data=json.dumps({
                    "title": title,
                    "body": message,
                    "url": link or "/vip",
                }),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
            )
            sent += 1

        except WebPushException as exc:
            status = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )

            if status in (404, 410):
                await db_execute(
                    """
                    DELETE FROM vip_push_subscriptions
                    WHERE endpoint = :endpoint
                    """,
                    {"endpoint": item["endpoint"]},
                )
            else:
                logger.warning(
                    "VIP push delivery failed with status %s",
                    status,
                )

        except Exception:
            logger.exception("VIP push delivery failed")

    return sent


async def send_admin_push(title, message, link="/admin"):
    if not all((
        VAPID_PUBLIC_KEY,
        VAPID_PRIVATE_KEY,
        VAPID_SUBJECT,
    )):
        logger.warning("Admin push skipped: VAPID configuration missing")
        return 0

    try:
        import json
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.exception("pywebpush is not installed")
        return 0

    subscriptions = await db_fetch_all(
        """
        SELECT endpoint, p256dh, auth
        FROM admin_push_subscriptions
        """
    )

    sent = 0

    for item in subscriptions:
        subscription_info = {
            "endpoint": item["endpoint"],
            "keys": {
                "p256dh": item["p256dh"],
                "auth": item["auth"],
            },
        }

        try:
            await asyncio.to_thread(
                webpush,
                subscription_info=subscription_info,
                data=json.dumps({
                    "title": title,
                    "body": message,
                    "url": link or "/admin",
                }),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
            )
            sent += 1

        except WebPushException as exc:
            status = getattr(
                getattr(exc, "response", None),
                "status_code",
                None,
            )

            if status in (404, 410):
                await db_execute(
                    """
                    DELETE FROM admin_push_subscriptions
                    WHERE endpoint = :endpoint
                    """,
                    {"endpoint": item["endpoint"]},
                )
            else:
                logger.warning(
                    "Admin push delivery failed with status %s",
                    status,
                )

        except Exception:
            logger.exception("Admin push delivery failed")

    return sent


async def admin_vip_expiry_monitor(interval_seconds=300):
    logger.info("VIP subscription expiry monitor started")

    while True:
        try:
            # Remove picks for all VIPs once their matches are finished.
            deleted = await db_execute(
                """
                DELETE FROM vip_picks vp
                USING matches m
                WHERE vp.match_id = m.id
                  AND UPPER(COALESCE(m.status, '')) = 'FINISHED'
                """
            )
            logger.info("Finished-match VIP picks cleanup: %s", deleted)

            # Keep paid entitlements active beyond their original expiry
            # while picks are still owed. Completed entitlements activate
            # the next queued paid entitlement immediately.
            entitlement_vips = await db_fetch_all(
                """
                SELECT id
                FROM vip_users
                WHERE approved = TRUE
                ORDER BY id
                """
            )

            today = datetime.now(KENYA).date()

            for entitlement_vip in entitlement_vips:
                conn = await asyncpg.connect(
                    dsn=DATABASE_URL,
                    command_timeout=60,
                )
                try:
                    await conn.execute(
                        f'SET search_path TO "{DB_SCHEMA}", public'
                    )

                    async with conn.transaction():
                        vip_row = await conn.fetchrow(
                            """
                            SELECT id, subscription_expiry
                            FROM vip_users
                            WHERE id = $1 AND approved = TRUE
                            FOR UPDATE
                            """,
                            entitlement_vip["id"],
                        )

                        if not vip_row:
                            continue

                        active = await conn.fetchrow(
                            """
                            SELECT id, total_picks, delivered_picks, expires_at
                            FROM vip_subscription_entitlements
                            WHERE vip_id = $1 AND status = 'active'
                            FOR UPDATE
                            """,
                            vip_row["id"],
                        )

                        if not active:
                            await _activate_next_vip_entitlement(
                                conn, vip_row["id"]
                            )
                            active = await conn.fetchrow(
                                """
                                SELECT id, total_picks, delivered_picks, expires_at
                                FROM vip_subscription_entitlements
                                WHERE vip_id = $1 AND status = 'active'
                                FOR UPDATE
                                """,
                                vip_row["id"],
                            )

                        if not active:
                            continue

                        outstanding = max(
                            int(active["total_picks"])
                            - int(active["delivered_picks"]),
                            0,
                        )

                        if outstanding <= 0:
                            completion_update = await conn.execute(
                                """
                                UPDATE vip_subscription_entitlements
                                SET status = 'completed',
                                    completed_at = COALESCE(
                                        completed_at, CURRENT_TIMESTAMP
                                    )
                                WHERE id = $1 AND status = 'active'
                                """,
                                active["id"],
                            )

                            if completion_update != "UPDATE 1":
                                raise RuntimeError(
                                    "Entitlement completion failed for "
                                    f"{active['id']}: {completion_update}"
                                )

                            await _activate_next_vip_entitlement(
                                conn, vip_row["id"]
                            )
                            continue

                        expiry = active["expires_at"]
                        if expiry is None:
                            expiry_text = vip_row["subscription_expiry"]
                            try:
                                expiry = datetime.fromisoformat(
                                    str(expiry_text).replace("Z", "+00:00")
                                )
                                if expiry.tzinfo is None:
                                    expiry = expiry.replace(tzinfo=UTC)
                            except (ValueError, TypeError):
                                logger.error(
                                    "Active VIP entitlement %s has no valid expiry",
                                    active["id"],
                                )
                                continue

                        expiry_date = expiry.astimezone(KENYA).date()

                        if expiry_date < today:
                            days_to_add = (today - expiry_date).days
                            extended_expiry = expiry + timedelta(
                                days=days_to_add
                            )

                            entitlement_expiry_update = await conn.execute(
                                """
                                UPDATE vip_subscription_entitlements
                                SET expires_at = $2
                                WHERE id = $1 AND status = 'active'
                                """,
                                active["id"],
                                extended_expiry,
                            )

                            if entitlement_expiry_update != "UPDATE 1":
                                raise RuntimeError(
                                    "Entitlement expiry extension failed for "
                                    f"{active['id']}: {entitlement_expiry_update}"
                                )

                            vip_expiry_update = await conn.execute(
                                """
                                UPDATE vip_users
                                SET subscription_expiry = $2
                                WHERE id = $1
                                """,
                                vip_row["id"],
                                extended_expiry.isoformat(),
                            )

                            if vip_expiry_update != "UPDATE 1":
                                raise RuntimeError(
                                    "VIP expiry extension failed for "
                                    f"{vip_row['id']}: {vip_expiry_update}"
                                )

                            logger.info(
                                "Extended VIP %s entitlement %s by %s day(s); %s picks outstanding",
                                vip_row["id"],
                                active["id"],
                                days_to_add,
                                outstanding,
                            )
                finally:
                    await conn.close()

            vips = await db_fetch_all(
                """
                SELECT id, name, number, subscription, subscription_expiry
                FROM vip_users
                WHERE approved = TRUE
                  AND subscription_expiry IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM vip_subscription_entitlements e
                      WHERE e.vip_id = vip_users.id
                        AND (
                            e.status = 'queued'
                            OR (
                                e.status = 'active'
                                AND e.delivered_picks < e.total_picks
                            )
                        )
                  )
                """
            )

            for vip in vips:
                expiry_text = str(vip["subscription_expiry"])

                try:
                    expiry = datetime.fromisoformat(
                        expiry_text.replace("Z", "+00:00")
                    )

                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=UTC)

                    expiry_date = expiry.astimezone(KENYA).date()

                    # The expiry date remains an entitled day.
                    if expiry_date >= today:
                        continue

                except (ValueError, TypeError):
                    logger.warning(
                        "Invalid VIP expiry date for VIP ID %s",
                        vip["id"],
                    )
                    continue

                claim = await db_fetch_one(
                    """
                    INSERT INTO admin_vip_expiry_notifications (
                        vip_id,
                        subscription_expiry,
                        claimed_at
                    )
                    VALUES (
                        :vip_id,
                        :expiry,
                        CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (vip_id, subscription_expiry)
                    DO UPDATE SET claimed_at = CURRENT_TIMESTAMP
                    WHERE admin_vip_expiry_notifications.notified_at IS NULL
                      AND admin_vip_expiry_notifications.claimed_at
                          < CURRENT_TIMESTAMP - INTERVAL '10 minutes'
                    RETURNING vip_id
                    """,
                    {
                        "vip_id": vip["id"],
                        "expiry": expiry_text,
                    },
                )

                if not claim:
                    continue

                try:
                    sent = await send_admin_push(
                        "VIP subscription expired",
                        (
                            f'{vip["name"]} ({vip["number"]}) '
                            f'has reached the end of their '
                            f'{vip["subscription"]} subscription.'
                        ),
                        "/admin",
                    )

                    if sent:
                        await db_execute(
                            """
                            UPDATE admin_vip_expiry_notifications
                            SET notified_at = CURRENT_TIMESTAMP
                            WHERE vip_id = :vip_id
                              AND subscription_expiry = :expiry
                            """,
                            {
                                "vip_id": vip["id"],
                                "expiry": expiry_text,
                            },
                        )
                    else:
                        await db_execute(
                            """
                            DELETE FROM admin_vip_expiry_notifications
                            WHERE vip_id = :vip_id
                              AND subscription_expiry = :expiry
                              AND notified_at IS NULL
                            """,
                            {
                                "vip_id": vip["id"],
                                "expiry": expiry_text,
                            },
                        )

                except Exception:
                    logger.exception(
                        "VIP expiry notification failed for VIP ID %s",
                        vip["id"],
                    )
                    await db_execute(
                        """
                        DELETE FROM admin_vip_expiry_notifications
                        WHERE vip_id = :vip_id
                          AND subscription_expiry = :expiry
                          AND notified_at IS NULL
                        """,
                        {
                            "vip_id": vip["id"],
                            "expiry": expiry_text,
                        },
                    )

        except Exception:
            logger.exception("VIP expiry monitor check failed")

        await asyncio.sleep(interval_seconds)


def admin_required(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        token = get_bearer_token()

        if not token:
            return jsonify({
                "error": "authorization token required"
            }), 401

        try:
            payload = decode_token(token)
            admin_id = payload.get("admin_id")

            if not admin_id:
                return jsonify({
                    "error": "invalid admin token"
                }), 401

            admin = await db_fetch_one(
                """
                SELECT
                    id,
                    username,
                    failed_attempts
                FROM admins
                WHERE id = :id
                """,
                {"id": admin_id},
            )

            if not admin:
                return jsonify({
                    "error": "admin not found"
                }), 401

            request.admin_user = admin

            return await fn(*args, **kwargs)

        except Exception as exc:
            log_json(
                "error",
                event="admin_auth_error",
                error=str(exc),
            )

            return jsonify({
                "error": "invalid or expired token"
            }), 401

    return wrapper


@app.post("/admin/push/subscribe")
@admin_required
async def admin_push_subscribe():
    data = request.get_json(silent=True) or {}
    subscription = data.get("subscription") or data

    endpoint = str(subscription.get("endpoint") or "").strip()
    keys = subscription.get("keys") or {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()

    if not endpoint.startswith("https://") or not p256dh or not auth:
        return jsonify({"error": "Invalid push subscription"}), 400

    await db_execute(
        """
        INSERT INTO admin_push_subscriptions (
            endpoint, p256dh, auth, updated_at
        )
        VALUES (:endpoint, :p256dh, :auth, CURRENT_TIMESTAMP)
        ON CONFLICT (endpoint)
        DO UPDATE SET
            p256dh = EXCLUDED.p256dh,
            auth = EXCLUDED.auth,
            updated_at = CURRENT_TIMESTAMP
        """,
        {"endpoint": endpoint, "p256dh": p256dh, "auth": auth},
    )

    return jsonify({"success": True})


@app.post("/admin/push/unsubscribe")
@admin_required
async def admin_push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = str(data.get("endpoint") or "").strip()

    if not endpoint.startswith("https://"):
        return jsonify({"error": "Invalid endpoint"}), 400

    await db_execute(
        """
        DELETE FROM admin_push_subscriptions
        WHERE endpoint = :endpoint
        """,
        {"endpoint": endpoint},
    )

    return jsonify({"success": True})


# ============================================================
# ADMIN: SEND VIP PUSH TEST
# ============================================================

@app.post("/admin/vips/<int:vip_id>/push-test")
@admin_required
async def admin_test_vip_push(vip_id):
    if not all((
        VAPID_PUBLIC_KEY,
        VAPID_PRIVATE_KEY,
        VAPID_SUBJECT,
    )):
        return jsonify({
            "success": False,
            "error": "Push notification configuration is incomplete.",
        }), 503

    try:
        from pywebpush import webpush
    except ImportError:
        return jsonify({
            "success": False,
            "error": "pywebpush is not installed on the backend.",
        }), 503

    vip = await db_fetch_one(
        """
        SELECT id, name, number
        FROM vip_users
        WHERE id = :id
          AND approved = TRUE
        """,
        {"id": vip_id},
    )

    if not vip:
        return jsonify({
            "success": False,
            "error": "Approved VIP account not found.",
        }), 404

    subscriptions = await db_fetch_all(
        """
        SELECT endpoint
        FROM vip_push_subscriptions
        WHERE number = :number
        """,
        {"number": vip["number"]},
    )

    if not subscriptions:
        return jsonify({
            "success": False,
            "error": "This VIP has no registered push devices.",
        }), 404

    sent = await send_vip_push(
        vip["number"],
        "LilyMac VIP test notification",
        "Push notifications are working on this device, even when you are logged out.",
        "/vip",
    )

    if sent < 1:
        return jsonify({
            "success": False,
            "sent": 0,
            "subscriptions": len(subscriptions),
            "error": "No push notification was delivered. Check backend logs.",
        }), 502

    return jsonify({
        "success": True,
        "sent": sent,
        "subscriptions": len(subscriptions),
        "message": "Test notification sent.",
    })


# ============================================================
# MATCH HELPERS
# ============================================================

async def get_matches_for_next_days(days=3):
    rows = await db_fetch_all(
        """
        SELECT
            m.id AS match_id,
            m.home_team_name AS home,
            m.away_team_name AS away,
            m.utcdate AS utc
        FROM matches m
        WHERE m.status IN ('TIMED', 'SCHEDULED')
          AND m.utcdate >= CURRENT_TIMESTAMP
          AND m.utcdate <= (
              CURRENT_TIMESTAMP
              + (:days * INTERVAL '1 day')
          )
          AND NOT EXISTS (
              SELECT 1
              FROM vip_picks vp
              WHERE vp.match_id = m.id
          )
        ORDER BY m.utcdate ASC
        """,
        {"days": days},
    )

    output = []

    for row in rows:
        utc_dt = row["utc"]

        if utc_dt is not None:
            if utc_dt.tzinfo is None:
                utc_dt = utc_dt.replace(tzinfo=UTC)

            kenya_dt = utc_dt.astimezone(KENYA)
            kenya_time = kenya_dt.isoformat()
        else:
            kenya_time = None

        output.append(
            {
                "match_id": row["match_id"],
                "home": row["home"],
                "away": row["away"],
                "utc": utc_dt.isoformat() if utc_dt else None,
                "match_time": kenya_time,
            }
        )

    return output


# ============================================================
# INITIALIZE TABLES
# ============================================================

async def init_db_async():
    print(f"[VIP DB] Initializing PostgreSQL schema: {DB_SCHEMA}")

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id BIGSERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            failed_attempts INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS vip_users (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            number TEXT UNIQUE NOT NULL,
            subscription TEXT NOT NULL,
            subscription_expiry TEXT,
            approved BOOLEAN NOT NULL DEFAULT FALSE,
            password_hash TEXT
        )
        """
    )

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS admin_vip_expiry_notifications (
            vip_id BIGINT NOT NULL,
            subscription_expiry TEXT NOT NULL,
            claimed_at TIMESTAMPTZ,
            notified_at TIMESTAMPTZ,
            PRIMARY KEY (vip_id, subscription_expiry)
        )
        """
    )

    await db_execute(
        """
        ALTER TABLE vip_users
        ADD COLUMN IF NOT EXISTS password_hash TEXT
        """
    )

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS vip_picks (
            id BIGSERIAL PRIMARY KEY,
            number TEXT NOT NULL,
            match_id BIGINT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            match_time TIMESTAMPTZ,
            pick TEXT NOT NULL,
            odds DOUBLE PRECISION,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS vip_notifications (
            id BIGSERIAL PRIMARY KEY,
            number TEXT NOT NULL,
            event_key TEXT NOT NULL,
            notification_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            link TEXT NOT NULL DEFAULT '/vip',
            is_read BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(number, event_key)
        )
        """
    )

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS vip_notification_state (
            number TEXT PRIMARY KEY,
            last_quota_date DATE NOT NULL
        )
        """
    )

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS vip_daily_quota_usage (
            number TEXT NOT NULL,
            quota_date DATE NOT NULL,
            plan TEXT NOT NULL,
            quota INTEGER NOT NULL DEFAULT 0,
            used INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (number, quota_date),
            CHECK (quota >= 0),
            CHECK (used >= 0)
        )
        """
    )

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS vip_push_subscriptions (
            endpoint TEXT PRIMARY KEY,
            number TEXT NOT NULL,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS admin_push_subscriptions (
            endpoint TEXT PRIMARY KEY,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    await db_execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vip_push_subscriptions_number
        ON vip_push_subscriptions(number)
        """
    )

    await db_execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vip_notifications_number_created
        ON vip_notifications(number, created_at DESC)
        """
    )

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS vip_upgrade_requests (
            id BIGSERIAL PRIMARY KEY,
            vip_id BIGINT NOT NULL,
            from_plan TEXT NOT NULL,
            to_plan TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMPTZ
        )
        """
    )

    await db_execute(
        """
        ALTER TABLE vip_upgrade_requests
        ADD COLUMN IF NOT EXISTS request_type TEXT NOT NULL DEFAULT 'upgrade'
        """
    )

    # ========================================================
    # VIP SUBSCRIPTION ENTITLEMENTS
    # ========================================================

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS vip_subscription_entitlements (
            id BIGSERIAL PRIMARY KEY,
            vip_id BIGINT NOT NULL
                REFERENCES vip_users(id) ON DELETE CASCADE,
            request_id BIGINT UNIQUE
                REFERENCES vip_upgrade_requests(id) ON DELETE SET NULL,
            migration_key TEXT UNIQUE,
            plan TEXT NOT NULL,
            duration_days INTEGER NOT NULL CHECK (duration_days > 0),
            daily_quota INTEGER NOT NULL CHECK (daily_quota > 0),
            total_picks BIGINT NOT NULL CHECK (total_picks > 0),
            delivered_picks BIGINT NOT NULL DEFAULT 0
                CHECK (delivered_picks >= 0),
            status TEXT NOT NULL
                CHECK (status IN ('queued', 'active', 'completed')),
            queued_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            activated_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        )
        """
    )

    await db_execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vip_entitlements_queue
        ON vip_subscription_entitlements(vip_id, status, queued_at, id)
        """
    )

    await db_execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_vip_one_active_entitlement
        ON vip_subscription_entitlements(vip_id)
        WHERE status = 'active'
        """
    )

    # ========================================================
    # ONE-TIME LEGACY SUBSCRIBER MIGRATION
    #
    # Historical delivered baseline:
    # GREATEST(total daily-ledger usage, surviving VIP picks).
    # These sources may overlap, so they must never be added.
    # ========================================================

    await db_execute(
        """
        WITH plan_config(plan, duration_days, daily_quota) AS (
            VALUES
                ('daily', 1, 3),
                ('weekly', 7, 5),
                ('monthly', 30, 7),
                ('yearly', 365, 10),
                ('annual', 365, 10)
        ),
        ledger AS (
            SELECT
                number,
                COALESCE(SUM(used), 0)::BIGINT AS ledger_total
            FROM vip_daily_quota_usage
            GROUP BY number
        ),
        surviving AS (
            SELECT
                number,
                COUNT(*)::BIGINT AS surviving_picks
            FROM vip_picks
            GROUP BY number
        ),
        legacy AS (
            SELECT
                vu.id AS vip_id,
                LOWER(BTRIM(vu.subscription)) AS plan,
                pc.duration_days,
                pc.daily_quota,
                pc.duration_days::BIGINT
                    * pc.daily_quota::BIGINT AS total_picks,
                GREATEST(
                    COALESCE(l.ledger_total, 0),
                    COALESCE(s.surviving_picks, 0)
                )::BIGINT AS delivered_picks,
                CASE
                    WHEN pg_input_is_valid(
                        NULLIF(BTRIM(vu.subscription_expiry), ''),
                        'timestamptz'
                    )
                    THEN NULLIF(
                        BTRIM(vu.subscription_expiry), ''
                    )::timestamptz
                    ELSE NULL
                END AS existing_expiry
            FROM vip_users vu
            JOIN plan_config pc
              ON pc.plan = LOWER(BTRIM(vu.subscription))
            LEFT JOIN ledger l
              ON l.number = vu.number
            LEFT JOIN surviving s
              ON s.number = vu.number
            WHERE vu.approved IS TRUE
        )
        INSERT INTO vip_subscription_entitlements (
            vip_id,
            migration_key,
            plan,
            duration_days,
            daily_quota,
            total_picks,
            delivered_picks,
            status,
            queued_at,
            activated_at,
            expires_at,
            completed_at
        )
        SELECT
            legacy.vip_id,
            'legacy-vip-' || legacy.vip_id::TEXT,
            legacy.plan,
            legacy.duration_days,
            legacy.daily_quota,
            legacy.total_picks,
            legacy.delivered_picks,
            CASE
                WHEN legacy.delivered_picks >= legacy.total_picks
                    THEN 'completed'
                ELSE 'active'
            END,
            CURRENT_TIMESTAMP,
            COALESCE(
                legacy.existing_expiry
                    - make_interval(days => legacy.duration_days),
                CURRENT_TIMESTAMP
            ),
            legacy.existing_expiry,
            CASE
                WHEN legacy.delivered_picks >= legacy.total_picks
                    THEN CURRENT_TIMESTAMP
                ELSE NULL
            END
        FROM legacy
        ON CONFLICT (migration_key) DO NOTHING
        """
    )

    await db_execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vip_users_number
        ON vip_users(number)
        """
    )

    await db_execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vip_picks_number
        ON vip_picks(number)
        """
    )

    await db_execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vip_picks_match_id
        ON vip_picks(match_id)
        """
    )

    print("[VIP DB] PostgreSQL initialization complete.")


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
async def health():
    try:
        row = await db_fetch_one(
            """
            SELECT
                current_database() AS database,
                current_schema() AS schema
            """
        )

        return jsonify({
            "status": "ok",
            "database": row["database"] if row else None,
            "schema": row["schema"] if row else None,
        })

    except Exception as exc:
        log_json(
            "error",
            event="health_check_failed",
            error=str(exc),
        )

        return jsonify({
            "status": "error"
        }), 500


# ============================================================
# VIP REGISTRATION
# ============================================================

@app.post("/vip/register")
async def vip_register():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip()
    number = str(data.get("number", "")).strip()
    password = str(data.get("password", ""))
    subscription = str(
        data.get("subscription", "")
    ).strip().lower()

    if not name:
        return jsonify({
            "error": "name is required"
        }), 400

    if not number:
        return jsonify({
            "error": "number is required"
        }), 400

    if len(password) < 8:
        return jsonify({
            "error": "password must be at least 8 characters"
        }), 400

    if subscription not in PLAN_ORDER:
        return jsonify({
            "error": "invalid subscription plan",
            "plans": PLAN_ORDER,
        }), 400

    password_hash = generate_password_hash(password)

    try:
        existing = await db_fetch_one(
            """
            SELECT
                id,
                name,
                number,
                subscription,
                approved
            FROM vip_users
            WHERE number = :number
            """,
            {"number": number},
        )

        if existing:
            return jsonify({
                "error": "phone number already registered"
            }), 409

        row = await db_fetch_one(
            """
            INSERT INTO vip_users (
                name,
                number,
                subscription,
                subscription_expiry,
                approved,
                password_hash
            )
            VALUES (
                :name,
                :number,
                :subscription,
                NULL,
                FALSE,
                :password_hash
            )
            RETURNING
                id,
                name,
                number,
                subscription,
                subscription_expiry,
                approved
            """,
            {
                "name": name,
                "number": number,
                "subscription": subscription,
                "password_hash": password_hash,
            },
        )

        try:
            await send_admin_push(
                "New VIP registration request",
                f"{name} ({number}) requested the {subscription} plan.",
                "/admin",
            )
        except Exception as push_error:
            log_json(
                "error",
                event="admin_vip_registration_push_failed",
                error=str(push_error),
            )

        return jsonify({
            "message": "registration successful. waiting for admin approval.",
            "user": row,
        }), 201

    except asyncpg.UniqueViolationError as exc:
        log_json(
            "warning",
            event="vip_registration_duplicate_number",
            error=str(exc),
        )

        return jsonify({
            "error": "phone number already registered"
        }), 409

    except Exception as exc:
        log_json(
            "error",
            event="vip_register_failed",
            error=str(exc),
        )

        return jsonify({
            "error": "internal server error"
        }), 500


# ============================================================
# VIP LOGIN
# ============================================================

@app.post("/vip/login")
async def vip_login():
    data = request.get_json(silent=True) or {}

    number = str(data.get("number", "")).strip()
    password = str(data.get("password", ""))

    if not number:
        return jsonify({
            "error": "number is required"
        }), 400

    if not password:
        return jsonify({
            "error": "password is required"
        }), 400

    try:
        user = await db_fetch_one(
            """
            SELECT
                id,
                name,
                number,
                subscription,
                subscription_expiry,
                approved,
                password_hash
            FROM vip_users
            WHERE number = :number
            """,
            {"number": number},
        )

        if not user:
            return jsonify({
                "error": "VIP account not found"
            }), 404

        stored_hash = user["password_hash"]
        if not stored_hash:
            return jsonify({
                "error": "Your account needs an initial password. Contact the administrator."
            }), 403

        if not check_password_hash(stored_hash, password):
            return jsonify({
                "error": "invalid phone number or password"
            }), 401

        if not user["approved"]:
            return jsonify({
                "error": "VIP account is pending admin approval"
            }), 403

        token = create_token(
            {
                "vip_id": user["id"],
                "number": user["number"],
            }
        )

        safe_user = {
            "id": user["id"],
            "name": user["name"],
            "number": user["number"],
            "subscription": user["subscription"],
            "subscription_expiry": user["subscription_expiry"],
            "approved": user["approved"],
        }

        return jsonify({
            "message": "login successful",
            "token": token,
            "user": safe_user,
        })

    except Exception as exc:
        log_json(
            "error",
            event="vip_login_failed",
            error=str(exc),
        )

        return jsonify({
            "error": "internal server error"
        }), 500


# ============================================================
# VIP PROFILE
# ============================================================

@app.get("/vip/me")
@vip_required
async def vip_me():
    return jsonify({
        "user": request.vip_user
    })


# ============================================================
# VIP PICKS
# ============================================================

@app.get("/vip/picks")
@vip_required
async def vip_picks():
    vip = request.vip_user

    rows = await db_fetch_all(
        """
        SELECT
            vp.id, vp.number, vp.match_id,
            vp.home_team, vp.away_team, vp.match_time,
            vp.pick, vp.odds, vp.created_at
        FROM vip_picks vp
        LEFT JOIN matches m ON m.id = vp.match_id
        WHERE vp.number = :number
          AND UPPER(COALESCE(m.status, '')) <> 'FINISHED'
        ORDER BY vp.created_at DESC
        """,
        {"number": vip["number"]},
    )

    return jsonify({"picks": rows})


# ============================================================
# VIP QUOTA
# ============================================================

@app.get("/vip/quota")
@vip_required
async def vip_quota():
    vip = request.vip_user
    today = datetime.now(KENYA).date()

    entitlement = await db_fetch_one(
        """
        SELECT
            (
                SELECT id
                FROM vip_subscription_entitlements
                WHERE vip_id = :vip_id
                  AND status = 'active'
                ORDER BY id DESC
                LIMIT 1
            ) AS active_id,
            (
                SELECT plan
                FROM vip_subscription_entitlements
                WHERE vip_id = :vip_id
                  AND status = 'active'
                ORDER BY id DESC
                LIMIT 1
            ) AS active_plan,
            (
                SELECT daily_quota
                FROM vip_subscription_entitlements
                WHERE vip_id = :vip_id
                  AND status = 'active'
                ORDER BY id DESC
                LIMIT 1
            ) AS active_quota,
            (
                SELECT total_picks
                FROM vip_subscription_entitlements
                WHERE vip_id = :vip_id
                  AND status = 'active'
                ORDER BY id DESC
                LIMIT 1
            ) AS active_total_picks,
            (
                SELECT delivered_picks
                FROM vip_subscription_entitlements
                WHERE vip_id = :vip_id
                  AND status = 'active'
                ORDER BY id DESC
                LIMIT 1
            ) AS active_delivered_picks,
            (
                SELECT expires_at
                FROM vip_subscription_entitlements
                WHERE vip_id = :vip_id
                  AND status = 'active'
                ORDER BY id DESC
                LIMIT 1
            ) AS active_expires_at,
            COALESCE((
                SELECT SUM(total_picks)
                FROM vip_subscription_entitlements
                WHERE vip_id = :vip_id
            ), 0)::BIGINT AS lifetime_total_picks,
            COALESCE((
                SELECT SUM(delivered_picks)
                FROM vip_subscription_entitlements
                WHERE vip_id = :vip_id
            ), 0)::BIGINT AS lifetime_delivered_picks,
            COALESCE((
                SELECT SUM(GREATEST(total_picks - delivered_picks, 0))
                FROM vip_subscription_entitlements
                WHERE vip_id = :vip_id
            ), 0)::BIGINT AS lifetime_outstanding_picks,
            (
                SELECT COUNT(*)
                FROM vip_subscription_entitlements
                WHERE vip_id = :vip_id
                  AND status = 'queued'
            )::INTEGER AS queued_entitlements,
            EXISTS (
                SELECT 1
                FROM vip_subscription_entitlements
                WHERE vip_id = :vip_id
                  AND status = 'queued'
            ) AS has_queued
        """,
        {"vip_id": vip["id"]},
    )

    plan = (
        str(entitlement["active_plan"]).lower()
        if entitlement and entitlement["active_plan"]
        else str(vip["subscription"] or "").lower()
    )

    # No active entitlement means no new daily picks can be distributed.
    quota = (
        int(entitlement["active_quota"])
        if entitlement and entitlement["active_quota"] is not None
        else 0
    )

    usage = await db_fetch_one(
        """
        SELECT GREATEST(
            COALESCE((
                SELECT used
                FROM vip_daily_quota_usage
                WHERE number = :number
                  AND quota_date =
                      (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Nairobi')::date
            ), 0),
            COALESCE((
                SELECT COUNT(*)::INTEGER
                FROM vip_picks
                WHERE number = :number
                  AND (created_at AT TIME ZONE 'Africa/Nairobi')::date =
                      (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Nairobi')::date
            ), 0)
        ) AS used
        """,
        {"number": vip["number"]},
    )

    used = int(usage["used"]) if usage else 0

    active_total = (
        int(entitlement["active_total_picks"])
        if entitlement and entitlement["active_total_picks"] is not None
        else 0
    )
    active_delivered = (
        int(entitlement["active_delivered_picks"])
        if entitlement and entitlement["active_delivered_picks"] is not None
        else 0
    )
    active_outstanding = max(active_total - active_delivered, 0)

    has_queued = bool(entitlement and entitlement["has_queued"])
    has_active_outstanding = bool(
        entitlement
        and entitlement["active_id"] is not None
        and active_outstanding > 0
    )

    expiry_value = (
        entitlement["active_expires_at"]
        if entitlement and entitlement["active_expires_at"] is not None
        else vip["subscription_expiry"]
    )

    try:
        if isinstance(expiry_value, datetime):
            expiry = expiry_value
        else:
            expiry = datetime.fromisoformat(
                str(expiry_value).replace("Z", "+00:00")
            )

        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)

        expiry_date = expiry.astimezone(KENYA).date()
        calendar_expired = expiry_date < today
    except (ValueError, TypeError, OverflowError):
        calendar_expired = True

    # Outstanding or queued paid entitlements preserve access.
    expired = (
        calendar_expired
        and not has_active_outstanding
        and not has_queued
    )

    remaining = (
        min(max(quota - used, 0), active_outstanding)
        if not expired and entitlement and entitlement["active_id"] is not None
        else 0
    )

    extension_active = bool(
        has_active_outstanding and calendar_expired
    )

    return jsonify({
        # Existing response fields retained for frontend compatibility.
        "plan": plan,
        "quota": quota,
        "used": used,
        "remaining": remaining,
        "expired": expired,

        # Entitlement and cumulative delivery details.
        "total_picks": int(entitlement["lifetime_total_picks"]) if entitlement else 0,
        "delivered_picks": int(entitlement["lifetime_delivered_picks"]) if entitlement else 0,
        "outstanding_picks": int(entitlement["lifetime_outstanding_picks"]) if entitlement else 0,
        "active_entitlement_total": active_total,
        "active_entitlement_delivered": active_delivered,
        "active_entitlement_outstanding": active_outstanding,
        "entitlement_expires_at": (
            expiry.isoformat() if "expiry" in locals() else None
        ),
        "extension_active": extension_active,
        "queued_entitlements": (
            int(entitlement["queued_entitlements"]) if entitlement else 0
        ),
    })


# ============================================================
# VIP NOTIFICATIONS
# ============================================================

@app.get("/vip/notifications")
@vip_required
async def vip_notifications():
    vip = request.vip_user
    number = vip["number"]

    today_row = await db_fetch_one(
        "SELECT CURRENT_DATE AS today"
    )
    today = today_row["today"]

    state = await db_fetch_one(
        """
        SELECT last_quota_date
        FROM vip_notification_state
        WHERE number = :number
        """,
        {"number": number},
    )

    # First visit establishes a baseline without a false renewal alert.
    if not state:
        await db_execute(
            """
            INSERT INTO vip_notification_state (
                number,
                last_quota_date
            )
            VALUES (:number, :today)
            ON CONFLICT (number) DO NOTHING
            """,
            {
                "number": number,
                "today": today,
            },
        )

    elif state["last_quota_date"] < today:
        renewal_notification = await db_fetch_one(
            """
            INSERT INTO vip_notifications (
                number, event_key, notification_type, title, message, link
            )
            VALUES (
                :number, :event_key, 'quota_renewal',
                'Your VIP quota has renewed',
                'Your daily VIP pick quota is available again. Open your VIP picks to see your available picks.',
                '/vip'
            )
            ON CONFLICT (number, event_key) DO NOTHING
            RETURNING id
            """,
            {
                "number": number,
                "event_key": "quota-renewal-" + today.isoformat(),
            },
        )

        if renewal_notification:
            await send_vip_push(
                number,
                "Your VIP quota has renewed",
                "Your daily VIP pick quota is available again. Open your VIP picks to see your available picks.",
                "/vip",
            )

        await db_execute(
            """
            UPDATE vip_notification_state
            SET last_quota_date = :today
            WHERE number = :number
              AND last_quota_date < :today
            """,
            {
                "number": number,
                "today": today,
            },
        )

    rows = await db_fetch_all(
        """
        SELECT
            id,
            notification_type,
            title,
            message,
            link,
            is_read,
            created_at
        FROM vip_notifications
        WHERE number = :number
        ORDER BY created_at DESC
        LIMIT 50
        """,
        {"number": number},
    )

    unread = sum(1 for row in rows if not row["is_read"])

    return jsonify({
        "notifications": rows,
        "unread_count": unread,
    })


@app.post("/vip/notifications/<int:notification_id>/read")
@vip_required
async def vip_notification_mark_read(notification_id):
    vip = request.vip_user

    row = await db_fetch_one(
        """
        UPDATE vip_notifications
        SET is_read = TRUE
        WHERE id = :id
          AND number = :number
        RETURNING id
        """,
        {
            "id": notification_id,
            "number": vip["number"],
        },
    )

    if not row:
        return jsonify({"error": "Notification not found"}), 404

    return jsonify({"success": True, "id": notification_id})


@app.post("/vip/notifications/read-all")
@vip_required
async def vip_notifications_mark_all_read():
    vip = request.vip_user

    await db_execute(
        """
        UPDATE vip_notifications
        SET is_read = TRUE
        WHERE number = :number
          AND is_read = FALSE
        """,
        {"number": vip["number"]},
    )

    return jsonify({"success": True})


# ============================================================
# VIP UPGRADE REQUEST
# ============================================================

@app.post("/vip/upgrade")
@vip_required
async def vip_upgrade():
    data = request.get_json(silent=True) or {}
    to_plan = str(data.get("subscription", "")).strip().lower()

    if to_plan not in PLAN_ORDER:
        return jsonify({"error": "invalid subscription plan"}), 400

    vip = request.vip_user
    conn = await asyncpg.connect(dsn=DATABASE_URL, command_timeout=60)

    failure = None
    row = None
    upgrade_from_plan = None
    vip_name = vip.get("name") or "VIP member"

    try:
        await conn.execute(f'SET search_path TO "{DB_SCHEMA}", public')

        async with conn.transaction():
            # Serialize upgrade and renewal submissions for this VIP.
            locked_vip = await conn.fetchrow(
                """
                SELECT id, name, number, subscription, approved
                FROM vip_users
                WHERE id = $1
                FOR UPDATE
                """,
                vip["id"],
            )

            if not locked_vip:
                failure = ({"error": "VIP account not found"}, 404)

            elif not locked_vip["approved"]:
                failure = ({"error": "VIP account is not approved"}, 403)

            else:
                vip_name = locked_vip["name"] or "VIP member"
                existing = await conn.fetchval(
                    """
                    SELECT id
                    FROM vip_upgrade_requests
                    WHERE vip_id = $1 AND status = 'pending'
                    LIMIT 1
                    """,
                    locked_vip["id"],
                )

                if existing:
                    failure = ({
                        "error": "you already have a pending subscription request"
                    }, 409)

                else:
                    queued = await conn.fetchval(
                        """
                        SELECT id
                        FROM vip_subscription_entitlements
                        WHERE vip_id = $1 AND status = 'queued'
                        LIMIT 1
                        """,
                        locked_vip["id"],
                    )

                    if queued:
                        failure = ({
                            "error": (
                                "you already have a paid subscription "
                                "queued to activate"
                            )
                        }, 409)

                    else:
                        upgrade_from_plan = locked_vip["subscription"]

                        if (
                            upgrade_from_plan not in PLAN_ORDER
                            or PLAN_ORDER.index(to_plan)
                            <= PLAN_ORDER.index(upgrade_from_plan)
                        ):
                            failure = ({
                                "error": (
                                    "upgrade plan must be higher than "
                                    "your current plan"
                                )
                            }, 400)

                        else:
                            inserted = await conn.fetchrow(
                                """
                                INSERT INTO vip_upgrade_requests (
                                    vip_id, from_plan, to_plan,
                                    status, request_type
                                )
                                VALUES ($1, $2, $3, 'pending', 'upgrade')
                                RETURNING id, vip_id, from_plan, to_plan,
                                          status, created_at
                                """,
                                locked_vip["id"],
                                upgrade_from_plan,
                                to_plan,
                            )
                            row = dict(inserted)

    finally:
        await conn.close()

    if failure:
        return jsonify(failure[0]), failure[1]

    try:
        await send_admin_push(
            "VIP upgrade request",
            (
                f"{vip_name} ({vip['number']}) requested an upgrade "
                f"from {upgrade_from_plan} to {to_plan}."
            ),
            "/admin",
        )
    except Exception as push_error:
        log_json(
            "error",
            event="admin_vip_upgrade_push_failed",
            error=str(push_error),
        )

    return jsonify({
        "message": "upgrade request submitted",
        "request": row,
    }), 201


# ============================================================
# VIP SUBSCRIPTION RENEWAL REQUEST
# ============================================================

@app.post("/vip/renew")
@vip_required
async def vip_renew():
    data = request.get_json(silent=True) or {}
    to_plan = str(data.get("subscription", "")).strip().lower()

    if to_plan not in PLAN_ORDER:
        return jsonify({"error": "invalid subscription plan"}), 400

    vip = request.vip_user
    conn = await asyncpg.connect(dsn=DATABASE_URL, command_timeout=60)

    failure = None
    row = None

    try:
        await conn.execute(f'SET search_path TO "{DB_SCHEMA}", public')

        async with conn.transaction():
            # Use the same account lock as the upgrade route.
            locked_vip = await conn.fetchrow(
                """
                SELECT id, subscription, approved
                FROM vip_users
                WHERE id = $1
                FOR UPDATE
                """,
                vip["id"],
            )

            if not locked_vip:
                failure = ({"error": "VIP account not found"}, 404)

            elif not locked_vip["approved"]:
                failure = ({"error": "VIP account is not approved"}, 403)

            else:
                existing = await conn.fetchval(
                    """
                    SELECT id
                    FROM vip_upgrade_requests
                    WHERE vip_id = $1 AND status = 'pending'
                    LIMIT 1
                    """,
                    locked_vip["id"],
                )

                if existing:
                    failure = ({
                        "error": (
                            "you already have a pending subscription request"
                        )
                    }, 409)

                else:
                    queued = await conn.fetchval(
                        """
                        SELECT id
                        FROM vip_subscription_entitlements
                        WHERE vip_id = $1 AND status = 'queued'
                        LIMIT 1
                        """,
                        locked_vip["id"],
                    )

                    if queued:
                        failure = ({
                            "error": (
                                "you already have a paid subscription "
                                "queued to activate"
                            )
                        }, 409)

                    else:
                        inserted = await conn.fetchrow(
                            """
                            INSERT INTO vip_upgrade_requests (
                                vip_id, from_plan, to_plan,
                                status, request_type
                            )
                            VALUES ($1, $2, $3, 'pending', 'renewal')
                            RETURNING id, vip_id, from_plan, to_plan,
                                      status, created_at
                            """,
                            locked_vip["id"],
                            locked_vip["subscription"],
                            to_plan,
                        )
                        row = dict(inserted)

    finally:
        await conn.close()

    if failure:
        return jsonify(failure[0]), failure[1]

    try:
        await send_admin_push(
            "VIP renewal request",
            (
                f'{vip["name"]} ({vip["number"]}) '
                f'requested to renew their subscription '
                f'on the {to_plan} plan.'
            ),
            "/admin",
        )
    except Exception as push_error:
        log_json(
            "error",
            event="admin_vip_renewal_push_failed",
            error=str(push_error),
        )

    return jsonify({
        "message": "subscription renewal request submitted",
        "request": row,
    }), 201


# ============================================================
# VIP DEREGISTER
# ============================================================

@app.post("/vip/deregister")
@vip_required
async def vip_deregister():
    vip = request.vip_user

    await db_execute(
        """
        DELETE FROM vip_picks
        WHERE number = :number
        """,
        {
            "number": vip["number"]
        },
    )

    await db_execute(
        """
        DELETE FROM vip_upgrade_requests
        WHERE vip_id = :vip_id
        """,
        {
            "vip_id": vip["id"]
        },
    )

    await db_execute(
        """
        DELETE FROM vip_users
        WHERE id = :id
        """,
        {
            "id": vip["id"]
        },
    )

    return jsonify({
        "message": "VIP account deleted successfully"
    })


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.post("/admin/login")
async def admin_login():
    data = request.get_json(silent=True) or {}

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    if not username or not password:
        return jsonify({
            "error": "username and password are required"
        }), 400

    try:
        admin = await db_fetch_one(
            """
            SELECT
                id,
                username,
                password,
                failed_attempts
            FROM admins
            WHERE username = :username
            """,
            {
                "username": username
            },
        )

        if not admin:
            return jsonify({
                "error": "invalid username or password"
            }), 401

        password_valid = check_password_hash(
            admin["password"],
            password,
        )

        if not password_valid:
            await db_execute(
                """
                UPDATE admins
                SET failed_attempts = COALESCE(failed_attempts, 0) + 1
                WHERE id = :id
                """,
                {
                    "id": admin["id"]
                },
            )

            return jsonify({
                "error": "invalid username or password"
            }), 401

        await db_execute(
            """
            UPDATE admins
            SET failed_attempts = 0
            WHERE id = :id
            """,
            {
                "id": admin["id"]
            },
        )

        token = create_token(
            {
                "admin_id": admin["id"],
                "username": admin["username"],
            }
        )

        return jsonify({
            "message": "login successful",
            "token": token,
            "admin": {
                "id": admin["id"],
                "username": admin["username"],
            },
        })

    except Exception as exc:
        log_json(
            "error",
            event="admin_login_failed",
            error=str(exc),
        )

        return jsonify({
            "error": "internal server error"
        }), 500


# ============================================================
# ADMIN VIP LIST
# ============================================================

@app.get("/admin/vips")
@admin_required
async def admin_vips():
    rows = await db_fetch_all(
        """
        SELECT
            id,
            name,
            number,
            subscription,
            subscription_expiry,
            approved,
            (password_hash IS NOT NULL) AS has_password
        FROM vip_users
        ORDER BY id DESC
        """
    )

    return jsonify({
        "vips": rows
    })


# ============================================================
# ADMIN PENDING VIPS
# ============================================================

@app.get("/admin/vips/pending")
@admin_required
async def admin_pending_vips():
    rows = await db_fetch_all(
        """
        SELECT
            id,
            name,
            number,
            subscription,
            subscription_expiry,
            approved
        FROM vip_users
        WHERE approved = FALSE
        ORDER BY id DESC
        """
    )

    return jsonify({
        "vips": rows
    })


# ============================================================
# ADMIN APPROVE VIP
# ============================================================

@app.post("/admin/vips/<int:vip_id>/approve")
@admin_required
async def admin_approve_vip(vip_id):
    vip = await db_fetch_one(
        """
        SELECT
            id,
            name,
            number,
            subscription,
            subscription_expiry,
            approved
        FROM vip_users
        WHERE id = :id
        """,
        {
            "id": vip_id
        },
    )

    if not vip:
        return jsonify({
            "error": "VIP user not found"
        }), 404

    try:
        approved = await db_approve_initial_vip(vip_id)

        if not approved:
            return jsonify({
                "error": "VIP user not found"
            }), 404

        if approved.get("approval_conflict"):
            return jsonify({
                "error": approved["approval_conflict"]
            }), 409

        return jsonify({
            "message": "VIP approved successfully",
            "already_approved": approved["already_approved"],
        })

    except Exception as exc:
        log_json(
            "error",
            event="admin_vip_approval_failed",
            vip_id=vip_id,
            error=str(exc),
        )
        return jsonify({
            "error": "unable to approve VIP account"
        }), 500


# ============================================================
# ADMIN SET OR RESET VIP PASSWORD
# ============================================================

@app.post("/admin/vips/<int:vip_id>/password")
@admin_required
async def admin_set_vip_password(vip_id):
    data = request.get_json(silent=True) or {}
    password = str(data.get("password", ""))

    if len(password) < 8:
        return jsonify({
            "error": "password must be at least 8 characters"
        }), 400

    vip = await db_fetch_one(
        "SELECT id FROM vip_users WHERE id = :id",
        {"id": vip_id},
    )

    if not vip:
        return jsonify({
            "error": "VIP user not found"
        }), 404

    await db_execute(
        """
        UPDATE vip_users
        SET password_hash = :password_hash
        WHERE id = :id
        """,
        {
            "id": vip_id,
            "password_hash": generate_password_hash(password),
        },
    )

    return jsonify({
        "message": "VIP password assigned successfully"
    })


# ============================================================
# ADMIN DECLINE VIP
# ============================================================

@app.post("/admin/vips/<int:vip_id>/decline")
@admin_required
async def admin_decline_vip(vip_id):
    vip = await db_fetch_one(
        """
        SELECT id
        FROM vip_users
        WHERE id = :id
        """,
        {
            "id": vip_id
        },
    )

    if not vip:
        return jsonify({
            "error": "VIP user not found"
        }), 404

    await db_execute(
        """
        DELETE FROM vip_picks
        WHERE number = (
            SELECT number
            FROM vip_users
            WHERE id = :id
        )
        """,
        {
            "id": vip_id
        },
    )

    await db_execute(
        """
        DELETE FROM vip_upgrade_requests
        WHERE vip_id = :id
        """,
        {
            "id": vip_id
        },
    )

    await db_execute(
        """
        DELETE FROM vip_users
        WHERE id = :id
        """,
        {
            "id": vip_id
        },
    )

    return jsonify({
        "message": "VIP registration declined"
    })


# ============================================================
# ADMIN DELETE VIP
# ============================================================
@app.post("/admin/vips/<int:vip_id>/delete")
@admin_required
async def admin_delete_vip(vip_id):
    vip = await db_fetch_one(
        """
        SELECT id, number
        FROM vip_users
        WHERE id = :id
        """,
        {
            "id": vip_id
        },
    )

    if not vip:
        return jsonify({
            "error": "VIP user not found"
        }), 404

    # Delete all VIP picks first
    await db_execute(
        """
        DELETE FROM vip_picks
        WHERE number = :number
        """,
        {
            "number": vip["number"]
        },
    )

    # Delete pending/historical upgrade requests
    await db_execute(
        """
        DELETE FROM vip_upgrade_requests
        WHERE vip_id = :id
        """,
        {
            "id": vip_id
        },
    )

    # Finally delete the VIP account
    await db_execute(
        """
        DELETE FROM vip_users
        WHERE id = :id
        """,
        {
            "id": vip_id
        },
    )

    return jsonify({
        "success": True,
        "message": "VIP account deleted successfully"
    })


# ============================================================
# ADMIN UPGRADE REQUESTS
# ============================================================

@app.get("/admin/upgrade-requests")
@admin_required
async def admin_upgrade_requests():
    rows = await db_fetch_all(
        """
        SELECT
            ur.id,
            ur.vip_id,
            ur.from_plan,
            ur.to_plan,
            ur.status,
            ur.request_type,
            ur.created_at,
            ur.approved_at,
            vu.name,
            vu.number
        FROM vip_upgrade_requests ur
        LEFT JOIN vip_users vu
            ON vu.id = ur.vip_id
        ORDER BY ur.created_at DESC
        """
    )

    return jsonify({
        "requests": rows
    })


# ============================================================
# ADMIN APPROVE UPGRADE
# ============================================================

@app.post("/admin/upgrade-requests/<int:request_id>/approve")
@admin_required
async def admin_approve_upgrade(request_id):
    req = await db_fetch_one(
        """
        SELECT id, to_plan, status
        FROM vip_upgrade_requests
        WHERE id = :id
        """,
        {"id": request_id},
    )

    if not req:
        return jsonify({
            "error": "subscription request not found"
        }), 404

    if req["status"] != "pending":
        return jsonify({
            "error": "subscription request is not pending"
        }), 400

    if req["to_plan"] not in PLAN_DAYS:
        return jsonify({
            "error": "invalid subscription plan on request"
        }), 400

    approved = await db_approve_vip_request(request_id)

    if not approved:
        return jsonify({
            "error": "subscription request is no longer pending"
        }), 409

    if approved.get("approval_conflict"):
        return jsonify({
            "error": approved["approval_conflict"]
        }), 409

    return jsonify({
        "message": "subscription request approved successfully"
    })


# ============================================================
# ADMIN DECLINE UPGRADE
# ============================================================

@app.post("/admin/upgrade-requests/<int:request_id>/decline")
@admin_required
async def admin_decline_upgrade(request_id):
    req = await db_fetch_one(
        """
        UPDATE vip_upgrade_requests
        SET status = 'declined'
        WHERE id = :id
          AND status = 'pending'
        RETURNING id
        """,
        {"id": request_id},
    )

    if not req:
        existing = await db_fetch_one(
            """
            SELECT id
            FROM vip_upgrade_requests
            WHERE id = :id
            """,
            {"id": request_id},
        )

        if not existing:
            return jsonify({
                "error": "subscription request not found"
            }), 404

        return jsonify({
            "error": "subscription request is not pending"
        }), 400

    return jsonify({
        "message": "subscription request declined"
    })


# ============================================================
# ADMIN VIP PICKS PREVIEW
# ============================================================

@app.get("/admin/vip-picks/preview")
@admin_required
async def admin_vip_picks_preview():
    days = request.args.get(
        "days",
        default=3,
        type=int,
    )

    days = max(1, min(days, 30))

    try:
        matches = await get_matches_for_next_days(days)

        return jsonify({
            "days": days,
            "matches": matches,
            "count": len(matches),
        })

    except Exception as exc:
        log_json(
            "error",
            event="vip_preview_failed",
            error=str(exc),
        )

        return jsonify({
            "error": "internal server error"
        }), 500


# ============================================================
# ADMIN DISTRIBUTE VIP PICKS
# ============================================================

@app.post("/admin/vip-picks/distribute")
@admin_required
async def admin_distribute_vip_picks():
    data = request.get_json(silent=True) or {}
    number = str(data.get("number", "")).strip()
    picks = data.get("picks", [])

    if not number:
        return jsonify({"error": "number is required"}), 400

    if not isinstance(picks, list):
        return jsonify({"error": "picks must be a list"}), 400

    if not picks:
        return jsonify({"error": "At least one pick is required"}), 400

    conn = await asyncpg.connect(dsn=DATABASE_URL, command_timeout=60)
    created = []
    failure = None
    quota = 0
    used = 0
    remaining_after = 0

    try:
        await conn.execute(f'SET search_path TO "{DB_SCHEMA}", public')

        async with conn.transaction():
            # Serialize all distributions for this VIP.
            vip = await conn.fetchrow(
                """
                SELECT id, name, number, subscription,
                       subscription_expiry, approved
                FROM vip_users
                WHERE number = $1
                FOR UPDATE
                """,
                number,
            )

            if not vip:
                failure = ({"error": "VIP user not found"}, 404)

            elif not vip["approved"]:
                failure = ({"error": "VIP user is not approved"}, 403)

            else:
                today = datetime.now(KENYA).date()

                # Lock the active paid entitlement for this VIP.
                entitlement = await conn.fetchrow(
                    """
                    SELECT id, plan, daily_quota, total_picks,
                           delivered_picks, expires_at
                    FROM vip_subscription_entitlements
                    WHERE vip_id = $1 AND status = 'active'
                    FOR UPDATE
                    """,
                    vip["id"],
                )

                # If no entitlement is active, activate the oldest queued one.
                if not entitlement:
                    await _activate_next_vip_entitlement(conn, vip["id"])
                    entitlement = await conn.fetchrow(
                        """
                        SELECT id, plan, daily_quota, total_picks,
                               delivered_picks, expires_at
                        FROM vip_subscription_entitlements
                        WHERE vip_id = $1 AND status = 'active'
                        FOR UPDATE
                        """,
                        vip["id"],
                    )

                # Recover safely if an active entitlement was already fulfilled.
                if entitlement and int(entitlement["delivered_picks"]) >= int(entitlement["total_picks"]):
                    completion_update = await conn.execute(
                        """
                        UPDATE vip_subscription_entitlements
                        SET status = 'completed',
                            completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
                        WHERE id = $1 AND status = 'active'
                        """,
                        entitlement["id"],
                    )

                    if completion_update != "UPDATE 1":
                        raise RuntimeError(
                            "Entitlement completion failed for "
                            f"{entitlement['id']}: {completion_update}"
                        )
                    await _activate_next_vip_entitlement(conn, vip["id"])
                    entitlement = await conn.fetchrow(
                        """
                        SELECT id, plan, daily_quota, total_picks,
                               delivered_picks, expires_at
                        FROM vip_subscription_entitlements
                        WHERE vip_id = $1 AND status = 'active'
                        FOR UPDATE
                        """,
                        vip["id"],
                    )

                if not entitlement:
                    failure = ({
                        "error": "No active paid entitlement is available"
                    }, 403)

                else:
                    entitlement_id = int(entitlement["id"])
                    plan = str(entitlement["plan"]).lower()
                    quota = int(entitlement["daily_quota"])
                    total_picks = int(entitlement["total_picks"])
                    delivered_picks = int(entitlement["delivered_picks"])
                    entitlement_remaining = max(
                        total_picks - delivered_picks, 0
                    )

                    if quota <= 0:
                        failure = ({
                            "error": "Active entitlement has no daily pick quota"
                        }, 400)

                    elif entitlement_remaining <= 0:
                        failure = ({
                            "error": "This paid entitlement has been fully delivered"
                        }, 403)

                    else:
                        # Outstanding paid picks remain distributable after
                        # the original expiry date. The expiry monitor handles
                        # the automatic extension.
                        #
                        # Create today's ledger row if this is the first distribution.
                        await conn.execute(
                            """
                            INSERT INTO vip_daily_quota_usage
                                (number, quota_date, plan, quota, used)
                            VALUES ($1, $2, $3, $4, 0)
                            ON CONFLICT (number, quota_date) DO NOTHING
                            """,
                            number, today, plan, quota,
                        )

                        ledger = await conn.fetchrow(
                            """
                            SELECT used
                            FROM vip_daily_quota_usage
                            WHERE number = $1 AND quota_date = $2
                            FOR UPDATE
                            """,
                            number, today,
                        )

                        used = int(ledger["used"]) if ledger else 0

                        # Reconcile legacy picks created today in Kenya time.
                        # GREATEST prevents double-counting picks already in the ledger.
                        existing_today = await conn.fetchval(
                            """
                            SELECT COUNT(*)::int
                            FROM vip_picks
                            WHERE number = $1
                              AND (created_at AT TIME ZONE 'Africa/Nairobi')::date = $2
                            """,
                            number, today,
                        )
                        used = max(used, int(existing_today or 0))

                        # Persist reconciled usage before checking remaining quota.
                        await conn.execute(
                            """
                            UPDATE vip_daily_quota_usage
                            SET plan = $3,
                                quota = $4,
                                used = $5,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE number = $1 AND quota_date = $2
                            """,
                            number, today, plan, quota, used,
                        )

                        candidates = []
                        seen_match_ids = set()

                        for item in picks:
                            if not isinstance(item, dict):
                                continue

                            try:
                                match_id = int(item.get("match_id"))
                            except (TypeError, ValueError):
                                continue

                            pick = str(item.get("pick", "")).strip().upper()

                            if not pick or match_id in seen_match_ids:
                                continue

                            seen_match_ids.add(match_id)

                            match = await conn.fetchrow(
                                """
                                SELECT id, home_team_name, away_team_name,
                                       utcdate, status
                                FROM matches
                                WHERE id = $1
                                """,
                                match_id,
                            )

                            if not match:
                                continue

                            if str(match["status"] or "").upper() == "FINISHED":
                                continue

                            duplicate = await conn.fetchval(
                                """
                                SELECT EXISTS(
                                    SELECT 1
                                    FROM vip_picks
                                    WHERE number = $1 AND match_id = $2
                                )
                                """,
                                number, match_id,
                            )

                            if duplicate:
                                continue

                            odds = item.get("odds")
                            if odds is not None:
                                try:
                                    odds = float(odds)
                                except (TypeError, ValueError):
                                    continue

                            candidates.append((match, pick, odds))

                        if not candidates:
                            failure = ({
                                "error": "No eligible new picks to distribute"
                            }, 400)

                        remaining = min(
                            max(quota - used, 0),
                            entitlement_remaining,
                        )

                        if failure:
                            pass
                        elif len(candidates) > remaining:
                            failure = ({
                                "error": "VIP entitlement or daily quota exceeded",
                                "quota": quota,
                                "used": used,
                                "remaining": remaining,
                                "entitlement_remaining": entitlement_remaining,
                            }, 400)

                        else:
                            for match, pick, odds in candidates:
                                row = await conn.fetchrow(
                                    """
                                    INSERT INTO vip_picks (
                                        number, match_id, home_team, away_team,
                                        match_time, pick, odds
                                    )
                                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                                    RETURNING id, number, match_id, home_team,
                                              away_team, match_time, pick, odds,
                                              created_at
                                    """,
                                    number,
                                    match["id"],
                                    match["home_team_name"],
                                    match["away_team_name"],
                                    match["utcdate"],
                                    pick,
                                    odds,
                                )
                                created.append(dict(row))

                            if created:
                                used += len(created)

                                await conn.execute(
                                    """
                                    UPDATE vip_daily_quota_usage
                                    SET used = $3,
                                        updated_at = CURRENT_TIMESTAMP
                                    WHERE number = $1 AND quota_date = $2
                                    """,
                                    number, today, used,
                                )

                            # Persist cumulative delivery independently of
                        # vip_picks, whose finished-match rows may be cleaned up.
                        if created:
                            delivery = await conn.fetchrow(
                                """
                                UPDATE vip_subscription_entitlements
                                SET delivered_picks = delivered_picks + $2
                                WHERE id = $1 AND status = 'active'
                                RETURNING delivered_picks, total_picks
                                """,
                                entitlement_id,
                                len(created),
                            )

                            if not delivery:
                                raise RuntimeError(
                                    "Active entitlement disappeared during distribution"
                                )

                            delivered_picks = int(delivery["delivered_picks"])
                            total_picks = int(delivery["total_picks"])

                            if delivered_picks >= total_picks:
                                completion_update = await conn.execute(
                                    """
                                    UPDATE vip_subscription_entitlements
                                    SET status = 'completed',
                                        completed_at = CURRENT_TIMESTAMP
                                    WHERE id = $1 AND status = 'active'
                                    """,
                                    entitlement_id,
                                )

                                if completion_update != "UPDATE 1":
                                    raise RuntimeError(
                                        "Entitlement completion failed for "
                                        f"{entitlement_id}: {completion_update}"
                                    )

                                # Activate the next paid entitlement immediately.
                                # Do not reset today's Kenya-time quota ledger.
                                await _activate_next_vip_entitlement(
                                    conn, vip["id"]
                                )

                            # Re-read the active entitlement so the response and
                            # daily ledger reflect the plan now in force.
                            current_entitlement = await conn.fetchrow(
                                """
                                SELECT plan, daily_quota, total_picks,
                                       delivered_picks
                                FROM vip_subscription_entitlements
                                WHERE vip_id = $1 AND status = 'active'
                                FOR UPDATE
                                """,
                                vip["id"],
                            )

                            if current_entitlement:
                                current_plan = str(current_entitlement["plan"]).lower()
                                current_quota = int(current_entitlement["daily_quota"])
                                current_outstanding = max(
                                    int(current_entitlement["total_picks"])
                                    - int(current_entitlement["delivered_picks"]),
                                    0,
                                )

                                # Preserve today's used count while recording the
                                # newly active plan and its daily quota.
                                await conn.execute(
                                    """
                                    UPDATE vip_daily_quota_usage
                                    SET plan = $3,
                                        quota = $4,
                                        used = $5,
                                        updated_at = CURRENT_TIMESTAMP
                                    WHERE number = $1 AND quota_date = $2
                                    """,
                                    number, today, current_plan, current_quota, used,
                                )

                                quota = current_quota
                                remaining_after = min(
                                    max(current_quota - used, 0),
                                    current_outstanding,
                                )
                            else:
                                quota = 0
                                remaining_after = 0

    finally:
        await conn.close()

    if failure:
        return jsonify(failure[0]), failure[1]

    if created:
        first_id = created[0]["id"]
        last_id = created[-1]["id"]

        message = (
            f"{len(created)} new VIP pick(s) have been added "
            f"to your account. You have {remaining_after} "
            f"pick(s) remaining in today's quota."
        )

        try:
            notification = await db_fetch_one(
                """
                INSERT INTO vip_notifications (
                    number, event_key, notification_type,
                    title, message, link
                )
                VALUES (
                    :number, :event_key, 'new_picks',
                    'New VIP picks are available', :message, '/vip'
                )
                ON CONFLICT (number, event_key) DO NOTHING
                RETURNING id
                """,
                {
                    "number": number,
                    "event_key": f"new-picks-{first_id}-{last_id}",
                    "message": message,
                },
            )

            if notification:
                await send_vip_push(
                    number,
                    "New VIP picks are available",
                    message,
                    "/vip",
                )

        except Exception:
            logger.exception(
                "VIP picks were saved, but notification delivery failed for %s",
                number,
            )

    return jsonify({
        "message": "VIP picks distributed successfully",
        "count": len(created),
        "picks": created,
        "quota": quota,
        "used": used,
        "remaining": remaining_after,
    })


# ============================================================
# CLEAR ALL VIP PICKS
# ============================================================

@app.delete("/admin/vip-picks/clear-all")
@admin_required
async def admin_clear_all_vip_picks():
    result = await db_execute(
        """
        DELETE FROM vip_picks
        """
    )

    return jsonify({
        "message": "all VIP picks cleared",
        "result": result,
    })


# ============================================================
# CLEAR VIP PICKS BY NUMBER
# ============================================================

@app.delete("/admin/vip-picks/<number>")
@admin_required
async def admin_clear_vip_picks(number):
    result = await db_execute(
        """
        DELETE FROM vip_picks
        WHERE number = :number
        """,
        {
            "number": number
        },
    )

    return jsonify({
        "message": "VIP picks cleared",
        "number": number,
        "result": result,
    })


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "endpoint not found"
    }), 404


@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({
        "error": "method not allowed"
    }), 405

@app.errorhandler(500)
def internal_error(error):
    log_json(
        "error",
        event="internal_server_error",
        error=str(error),
    )

    return jsonify({
        "error": "internal server error"
    }), 500
# ============================================================
# STARTUP
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(init_db_async())
    except Exception as exc:
        print("[VIP DB] Initialization failed:")
        traceback.print_exc()
        raise

    log_json(
        "info",
        event="api_start",
        port=5004,
        schema=DB_SCHEMA,
    )

    app.run(
        host="0.0.0.0",
        port=5004,
        debug=False,
    )
