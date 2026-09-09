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
from werkzeug.security import check_password_hash

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
        server_settings={
            "search_path": f"{DB_SCHEMA},public"
        },
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
        server_settings={
            "search_path": f"{DB_SCHEMA},public"
        },
    )

    try:
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
            approved BOOLEAN NOT NULL DEFAULT FALSE
        )
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

    if subscription not in PLAN_ORDER:
        return jsonify({
            "error": "invalid subscription plan",
            "plans": PLAN_ORDER,
        }), 400

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

        expiry = (
            datetime.now(UTC)
            + timedelta(days=PLAN_DAYS[subscription])
        ).isoformat()

        row = await db_fetch_one(
            """
            INSERT INTO vip_users (
                name,
                number,
                subscription,
                subscription_expiry,
                approved
            )
            VALUES (
                :name,
                :number,
                :subscription,
                :expiry,
                FALSE
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
                "expiry": expiry,
            },
        )

        return jsonify({
            "message": "registration successful. waiting for admin approval.",
            "user": row,
        }), 201

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

    if not number:
        return jsonify({
            "error": "number is required"
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
                approved
            FROM vip_users
            WHERE number = :number
            """,
            {"number": number},
        )

        if not user:
            return jsonify({
                "error": "VIP account not found"
            }), 404

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

        return jsonify({
            "message": "login successful",
            "token": token,
            "user": user,
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
            id,
            number,
            match_id,
            home_team,
            away_team,
            match_time,
            pick,
            odds,
            created_at
        FROM vip_picks
        WHERE number = :number
        ORDER BY created_at DESC
        """,
        {
            "number": vip["number"]
        },
    )

    return jsonify({
        "picks": rows
    })


# ============================================================
# VIP QUOTA
# ============================================================

@app.get("/vip/quota")
@vip_required
async def vip_quota():
    vip = request.vip_user

    plan = vip["subscription"]
    quota = SUBSCRIPTION_QUOTA.get(plan, 0)

    row = await db_fetch_one(
        """
        SELECT COUNT(*) AS count
        FROM vip_picks
        WHERE number = :number
          AND created_at >= CURRENT_DATE
        """,
        {
            "number": vip["number"]
        },
    )

    used = int(row["count"]) if row else 0

    return jsonify({
        "plan": plan,
        "quota": quota,
        "used": used,
        "remaining": max(quota - used, 0),
    })


# ============================================================
# VIP UPGRADE REQUEST
# ============================================================

@app.post("/vip/upgrade")
@vip_required
async def vip_upgrade():
    data = request.get_json(silent=True) or {}

    to_plan = str(
        data.get("subscription", "")
    ).strip().lower()

    if to_plan not in PLAN_ORDER:
        return jsonify({
            "error": "invalid subscription plan"
        }), 400

    vip = request.vip_user

    current_plan = vip["subscription"]

    if PLAN_ORDER.index(to_plan) <= PLAN_ORDER.index(current_plan):
        return jsonify({
            "error": "upgrade plan must be higher than current plan"
        }), 400

    existing = await db_fetch_one(
        """
        SELECT id
        FROM vip_upgrade_requests
        WHERE vip_id = :vip_id
          AND status = 'pending'
        LIMIT 1
        """,
        {
            "vip_id": vip["id"]
        },
    )

    if existing:
        return jsonify({
            "error": "you already have a pending upgrade request"
        }), 409

    row = await db_fetch_one(
        """
        INSERT INTO vip_upgrade_requests (
            vip_id,
            from_plan,
            to_plan,
            status
        )
        VALUES (
            :vip_id,
            :from_plan,
            :to_plan,
            'pending'
        )
        RETURNING
            id,
            vip_id,
            from_plan,
            to_plan,
            status,
            created_at
        """,
        {
            "vip_id": vip["id"],
            "from_plan": current_plan,
            "to_plan": to_plan,
        },
    )

    return jsonify({
        "message": "upgrade request submitted",
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
            approved
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

    await db_execute(
        """
        UPDATE vip_users
        SET approved = TRUE
        WHERE id = :id
        """,
        {
            "id": vip_id
        },
    )

    return jsonify({
        "message": "VIP approved successfully"
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
        SELECT
            id,
            vip_id,
            from_plan,
            to_plan,
            status
        FROM vip_upgrade_requests
        WHERE id = :id
        """,
        {
            "id": request_id
        },
    )

    if not req:
        return jsonify({
            "error": "upgrade request not found"
        }), 404

    if req["status"] != "pending":
        return jsonify({
            "error": "upgrade request is not pending"
        }), 400

    expiry = (
        datetime.now(UTC)
        + timedelta(days=PLAN_DAYS[req["to_plan"]])
    ).isoformat()

    await db_execute(
        """
        UPDATE vip_users
        SET
            subscription = :subscription,
            subscription_expiry = :expiry
        WHERE id = :vip_id
        """,
        {
            "subscription": req["to_plan"],
            "expiry": expiry,
            "vip_id": req["vip_id"],
        },
    )

    await db_execute(
        """
        UPDATE vip_upgrade_requests
        SET
            status = 'approved',
            approved_at = CURRENT_TIMESTAMP
        WHERE id = :id
        """,
        {
            "id": request_id
        },
    )

    return jsonify({
        "message": "upgrade approved successfully"
    })


# ============================================================
# ADMIN DECLINE UPGRADE
# ============================================================

@app.post("/admin/upgrade-requests/<int:request_id>/decline")
@admin_required
async def admin_decline_upgrade(request_id):
    req = await db_fetch_one(
        """
        SELECT id, status
        FROM vip_upgrade_requests
        WHERE id = :id
        """,
        {
            "id": request_id
        },
    )

    if not req:
        return jsonify({
            "error": "upgrade request not found"
        }), 404

    await db_execute(
        """
        UPDATE vip_upgrade_requests
        SET status = 'declined'
        WHERE id = :id
        """,
        {
            "id": request_id
        },
    )

    return jsonify({
        "message": "upgrade request declined"
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

    number = str(
        data.get("number", "")
    ).strip()

    picks = data.get("picks", [])

    if not number:
        return jsonify({
            "error": "number is required"
        }), 400

    if not isinstance(picks, list):
        return jsonify({
            "error": "picks must be a list"
        }), 400

    vip = await db_fetch_one(
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
        {
            "number": number
        },
    )

    if not vip:
        return jsonify({
            "error": "VIP user not found"
        }), 404

    if not vip["approved"]:
        return jsonify({
            "error": "VIP user is not approved"
        }), 403

    quota = SUBSCRIPTION_QUOTA.get(
        vip["subscription"],
        0,
    )

    existing = await db_fetch_one(
        """
        SELECT COUNT(*) AS count
        FROM vip_picks
        WHERE number = :number
          AND created_at >= CURRENT_DATE
        """,
        {
            "number": number
        },
    )

    used = int(existing["count"]) if existing else 0

    remaining = max(quota - used, 0)

    if len(picks) > remaining:
        return jsonify({
            "error": "VIP quota exceeded",
            "quota": quota,
            "used": used,
            "remaining": remaining,
        }), 400

    created = []

    for item in picks:
        match_id = item.get("match_id")
        pick = str(
            item.get("pick", "")
        ).strip().upper()

        odds = item.get("odds")

        if not match_id or not pick:
            continue

        match = await db_fetch_one(
            """
            SELECT
                id,
                home_team_name,
                away_team_name,
                utcdate,
                status
            FROM matches
            WHERE id = :id
            """,
            {
                "id": match_id
            },
        )

        if not match:
            continue

        existing_pick = await db_fetch_one(
            """
            SELECT id
            FROM vip_picks
            WHERE number = :number
              AND match_id = :match_id
            LIMIT 1
            """,
            {
                "number": number,
                "match_id": match_id,
            },
        )

        if existing_pick:
            continue

        row = await db_fetch_one(
            """
            INSERT INTO vip_picks (
                number,
                match_id,
                home_team,
                away_team,
                match_time,
                pick,
                odds
            )
            VALUES (
                :number,
                :match_id,
                :home_team,
                :away_team,
                :match_time,
                :pick,
                :odds
            )
            RETURNING
                id,
                number,
                match_id,
                home_team,
                away_team,
                match_time,
                pick,
                odds,
                created_at
            """,
            {
                "number": number,
                "match_id": match_id,
                "home_team": match["home_team_name"],
                "away_team": match["away_team_name"],
                "match_time": match["utcdate"],
                "pick": pick,
                "odds": odds,
            },
        )

        created.append(row)

    return jsonify({
        "message": "VIP picks distributed successfully",
        "count": len(created),
        "picks": created,
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
