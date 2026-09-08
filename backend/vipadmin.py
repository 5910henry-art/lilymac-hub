# vipadmin.py
import os
import jwt

from functools import wraps
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

from config2 import (
    query_db,
    execute_db,
    UTC,
    KENYA,
    DB_SCHEMA,
)


# ============================================================
# CONFIG / CONSTANTS
# ============================================================

JWT_SECRET = os.getenv(
    "JWT_SECRET",
    "4195f04c7739136d1c06124761c3fe26826808339c676bec3c8ce3c621b5f87e",
)

JWT_EXP_HOURS = int(
    os.getenv("JWT_EXP_HOURS", "12")
)

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
# APP INIT
# ============================================================

app = Flask(__name__)
CORS(app)


# ============================================================
# DATABASE WRAPPERS
# ============================================================

async def db_fetch_one(sql, params=None):
    rows = await query_db(
        sql,
        params or {},
    )
    return rows[0] if rows else None


async def db_fetch_all(sql, params=None):
    return await query_db(
        sql,
        params or {},
    )


async def db_execute(sql, params=None):
    return await execute_db(
        sql,
        params or {},
    )


# ============================================================
# JWT HELPERS
# ============================================================

def create_token(payload):
    payload = dict(payload)

    if "exp" not in payload:
        payload["exp"] = int(
            (
                datetime.now(UTC)
                + timedelta(hours=JWT_EXP_HOURS)
            ).timestamp()
        )

    token = jwt.encode(
        payload,
        JWT_SECRET,
        algorithm="HS256",
    )

    if isinstance(token, bytes):
        token = token.decode("utf-8")

    return token


def decode_token(token):
    return jwt.decode(
        token,
        JWT_SECRET,
        algorithms=["HS256"],
    )


# ============================================================
# DATE HELPERS
# ============================================================

def today_utc_date():
    return datetime.now(UTC).date()


def today_utc_iso():
    return today_utc_date().isoformat()


def today_kenya_date():
    return datetime.now(KENYA).date()


def today_kenya_iso():
    return today_kenya_date().isoformat()


def get_quota(subscription):
    return SUBSCRIPTION_QUOTA.get(
        (subscription or "").lower(),
        0,
    )


def parse_expiry(value):
    """
    Parse VIP subscription expiry.

    Stored VIP expiry is normally YYYY-MM-DD.
    Supports datetime values as well.
    """

    if value is None:
        return None

    if hasattr(value, "date"):
        try:
            return value.date()
        except Exception:
            pass

    value = str(value).strip()

    if not value:
        return None

    # Date only
    try:
        return datetime.strptime(
            value[:10],
            "%Y-%m-%d",
        ).date()
    except Exception:
        pass

    # ISO datetime
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).date()
    except Exception:
        return None


def is_active_row(row):
    try:
        expiry = parse_expiry(
            row.get("subscription_expiry")
        )

        approved = row.get("approved")

        if isinstance(approved, bool):
            approved_ok = approved
        else:
            approved_ok = int(approved or 0) == 1

        return (
            approved_ok
            and expiry is not None
            and expiry >= today_kenya_date()
        )

    except Exception:
        return False


# ============================================================
# LOGGING
# ============================================================

def log_admin(username, action, data=None):
    print(
        f"[ADMIN LOG] "
        f"{datetime.now(UTC).isoformat()} | "
        f"{username} | "
        f"{action} | "
        f"{data}"
    )


def log_json(level, **kwargs):
    print(
        f"[{level.upper()}] "
        f"{datetime.now(UTC).isoformat()} | "
        f"{kwargs}"
    )


# ============================================================
# AUTH DECORATORS
# ============================================================

def vip_required(f):

    @wraps(f)
    async def decorated(*args, **kwargs):

        auth = request.headers.get(
            "Authorization",
            "",
        )

        token = auth.replace(
            "Bearer ",
            "",
        ).strip()

        if not token:
            return jsonify({
                "error": "Token required"
            }), 401

        try:
            payload = decode_token(token)

            vip_id = payload.get("vip_id")

            if not vip_id:
                return jsonify({
                    "error": "Invalid token"
                }), 401

            vip = await db_fetch_one(
                """
                SELECT *
                FROM vip_users
                WHERE id = :vip_id
                """,
                {
                    "vip_id": vip_id,
                },
            )

            if not vip:
                return jsonify({
                    "error": "VIP not found"
                }), 404

            request.vip = vip

        except jwt.ExpiredSignatureError:
            return jsonify({
                "error": "Token expired"
            }), 401

        except Exception as exc:
            print(
                f"[VIP AUTH ERROR] {exc}"
            )

            return jsonify({
                "error": "Invalid token"
            }), 401

        return await f(
            *args,
            **kwargs,
        )

    return decorated


def admin_required(f):

    @wraps(f)
    async def decorated(*args, **kwargs):

        auth = request.headers.get(
            "Authorization",
            "",
        )

        token = auth.replace(
            "Bearer ",
            "",
        ).strip()

        if not token:
            return jsonify({
                "error": "Token required"
            }), 401

        try:
            payload = decode_token(token)

            admin_id = payload.get("admin_id")

            if not admin_id:
                return jsonify({
                    "error": "Invalid token"
                }), 403

            admin = await db_fetch_one(
                """
                SELECT *
                FROM admins
                WHERE id = :admin_id
                """,
                {
                    "admin_id": admin_id,
                },
            )

            if not admin:
                return jsonify({
                    "error": "Admin not found"
                }), 403

            request.admin_id = admin["id"]
            request.admin_username = admin["username"]

        except jwt.ExpiredSignatureError:
            return jsonify({
                "error": "Token expired"
            }), 401

        except Exception as exc:
            print(
                f"[ADMIN AUTH ERROR] {exc}"
            )

            return jsonify({
                "error": "Invalid token"
            }), 401

        return await f(
            *args,
            **kwargs,
        )

    return decorated


# ============================================================
# MATCH HELPERS
# ============================================================

async def get_matches_for_next_days(days=3):

    days = max(
        1,
        min(int(days), 30),
    )

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
        {
            "days": days,
        },
    )

    out = []

    for r in rows:

        utc_value = r.get("utc")

        utc_dt = None

        try:
            if isinstance(
                utc_value,
                datetime,
            ):
                utc_dt = utc_value

            elif utc_value:
                utc_dt = datetime.fromisoformat(
                    str(utc_value).replace(
                        "Z",
                        "+00:00",
                    )
                )

        except Exception:
            utc_dt = None

        local = None

        if utc_dt:

            if utc_dt.tzinfo is None:
                utc_dt = utc_dt.replace(
                    tzinfo=UTC
                )

            local = utc_dt.astimezone(
                KENYA
            ).strftime(
                "%Y-%m-%d %H:%M"
            )

        out.append({
            "match_id": r["match_id"],
            "home": r["home"],
            "away": r["away"],
            "utc": (
                utc_value.isoformat()
                if isinstance(
                    utc_value,
                    datetime,
                )
                else utc_value
            ),
            "local": local,
        })

    return out


async def insert_vip_pick(
    number,
    match,
    pick,
    odds,
):

    match_id = match.get("match_id")
    home = match.get("home")
    away = match.get("away")
    utc = match.get("utc")

    if not all([
        number,
        match_id,
        home,
        away,
        utc,
        pick,
    ]):
        return False

    exists = await db_fetch_one(
        """
        SELECT 1
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

    if exists:
        return False

    created_at = datetime.now(UTC)

    await db_execute(
        """
        INSERT INTO vip_picks (
            number,
            match_id,
            home_team,
            away_team,
            match_time,
            pick,
            odds,
            created_at
        )
        VALUES (
            :number,
            :match_id,
            :home_team,
            :away_team,
            :match_time,
            :pick,
            :odds,
            :created_at
        )
        """,
        {
            "number": number,
            "match_id": match_id,
            "home_team": home,
            "away_team": away,
            "match_time": utc,
            "pick": pick,
            "odds": odds,
            "created_at": created_at,
        },
    )

    return True


# ============================================================
# UPGRADE BUSINESS LOGIC
# ============================================================

async def handle_upgrade_request(
    req_id,
    approve=True,
):

    req = await db_fetch_one(
        """
        SELECT *
        FROM vip_upgrade_requests
        WHERE id = :req_id
        """,
        {
            "req_id": req_id,
        },
    )

    if not req or req["status"] != "pending":
        return (
            None,
            "Upgrade request not pending or not found",
        )

    vip_id = req["vip_id"]
    requested_plan = req["to_plan"]
    current_plan = req["from_plan"]

    if approve:

        if (
            requested_plan not in PLAN_ORDER
            or current_plan not in PLAN_ORDER
        ):
            return (
                None,
                "Invalid subscription plan",
            )

        if (
            PLAN_ORDER.index(requested_plan)
            <= PLAN_ORDER.index(current_plan)
        ):
            return (
                None,
                f"Cannot approve same or lower plan "
                f"(current: {current_plan})",
            )

        vip = await db_fetch_one(
            """
            SELECT subscription_expiry
            FROM vip_users
            WHERE id = :vip_id
            """,
            {
                "vip_id": vip_id,
            },
        )

        if not vip:
            return (
                None,
                "VIP not found",
            )

        today = today_kenya_date()

        current_expiry = parse_expiry(
            vip.get("subscription_expiry")
        )

        if current_expiry is None:
            current_expiry = today

        start_date = max(
            today,
            current_expiry,
        )

        days = PLAN_DAYS.get(
            requested_plan,
            0,
        )

        new_expiry = (
            start_date
            + timedelta(days=days)
        ).strftime("%Y-%m-%d")

        await db_execute(
            """
            UPDATE vip_users
            SET
                subscription = :subscription,
                subscription_expiry = :subscription_expiry,
                approved = TRUE
            WHERE id = :vip_id
            """,
            {
                "subscription": requested_plan,
                "subscription_expiry": new_expiry,
                "vip_id": vip_id,
            },
        )

        await db_execute(
            """
            UPDATE vip_upgrade_requests
            SET
                status = 'approved',
                approved_at = :approved_at
            WHERE id = :req_id
            """,
            {
                "approved_at": datetime.now(UTC),
                "req_id": req_id,
            },
        )

        status = "approved"

    else:

        await db_execute(
            """
            UPDATE vip_upgrade_requests
            SET
                status = 'declined',
                approved_at = NULL
            WHERE id = :req_id
            """,
            {
                "req_id": req_id,
            },
        )

        status = "declined"

    log_admin(
        getattr(
            request,
            "admin_username",
            "system",
        ),
        f"{status}_upgrade",
        {
            "vip_id": vip_id,
            "from_plan": current_plan,
            "to_plan": requested_plan,
        },
    )

    return {
        "vip_id": vip_id,
        "from_plan": current_plan,
        "to_plan": requested_plan,
        "status": status,
    }, None


# ============================================================
# VIP REGISTRATION
# ============================================================

@app.route(
    "/vip/register",
    methods=["POST"],
)
async def vip_register():

    data = request.get_json() or {}

    name = str(
        data.get("name")
        or data.get("full_name")
        or ""
    ).strip()

    number = (
        data.get("number")
        or data.get("phone")
        or ""
    )

    if isinstance(number, dict):
        number = str(
            number.get("value")
            or number.get("number")
            or ""
        )

    number = str(number).strip()

    subscription = str(
        data.get("subscription")
        or data.get("plan")
        or ""
    ).lower()

    if (
        not name
        or not number
        or subscription not in PLAN_ORDER
    ):
        return jsonify({
            "error": "Invalid registration data"
        }), 400

    existing = await db_fetch_one(
        """
        SELECT id
        FROM vip_users
        WHERE number = :number
        """,
        {
            "number": number,
        },
    )

    if existing:
        return jsonify({
            "error": "Phone number already registered"
        }), 400

    await db_execute(
        """
        INSERT INTO vip_users (
            name,
            number,
            subscription,
            approved
        )
        VALUES (
            :name,
            :number,
            :subscription,
            FALSE
        )
        """,
        {
            "name": name,
            "number": number,
            "subscription": subscription,
        },
    )

    return jsonify({
        "success": True,
        "message": (
            "Account created successfully. "
            "Waiting for admin approval."
        ),
    })


# ============================================================
# VIP LOGIN
# ============================================================

@app.route(
    "/vip/login",
    methods=["POST"],
)
async def vip_login():

    data = request.get_json() or {}

    number = (
        data.get("number")
        or data.get("phone")
        or ""
    )

    if isinstance(number, dict):
        number = str(
            number.get("value")
            or number.get("number")
            or ""
        )

    number = str(number).strip()

    if not number:
        return jsonify({
            "error": "Phone number required"
        }), 400

    vip = await db_fetch_one(
        """
        SELECT *
        FROM vip_users
        WHERE number = :number
        """,
        {
            "number": number,
        },
    )

    if not vip:
        return jsonify({
            "error": "User not found"
        }), 404

    approved = vip.get("approved")

    if not (
        approved is True
        or approved == 1
        or str(approved).lower() == "true"
    ):
        return jsonify({
            "error": "Account pending admin approval"
        }), 403

    subscription_expiry = (
        vip.get("subscription_expiry")
    )

    expiry_date = parse_expiry(
        subscription_expiry
    )

    expired = (
        expiry_date is not None
        and expiry_date < today_kenya_date()
    )

    token = create_token({
        "vip_id": vip["id"],
        "number": vip["number"],
    })

    return jsonify({
        "success": True,
        "message": "Login successful",
        "token": token,
        "expired": expired,
        "user": {
            "id": vip["id"],
            "name": vip["name"],
            "number": vip["number"],
            "subscription": vip["subscription"],
            "approved": vip["approved"],
            "subscription_expiry": subscription_expiry,
        },
    })


# ============================================================
# VIP DEREGISTER
# ============================================================

@app.route(
    "/vip/deregister",
    methods=["POST"],
)
async def vip_deregister():

    data = request.get_json() or {}

    number = (
        data.get("number")
        or data.get("phone")
        or ""
    )

    if isinstance(number, dict):
        number = str(
            number.get("value")
            or number.get("number")
            or ""
        )

    number = str(number).strip()

    if not number:
        return jsonify({
            "error": "Phone number required"
        }), 400

    vip = await db_fetch_one(
        """
        SELECT *
        FROM vip_users
        WHERE number = :number
        """,
        {
            "number": number,
        },
    )

    if not vip:
        return jsonify({
            "error": "User not found"
        }), 404

    await db_execute(
        """
        DELETE FROM vip_users
        WHERE number = :number
        """,
        {
            "number": number,
        },
    )

    return jsonify({
        "success": True,
        "message": (
            "VIP account deregistered successfully"
        ),
    })


# ============================================================
# VIP PROFILE
# ============================================================

@app.route(
    "/vip/me",
    methods=["GET"],
)
@vip_required
async def vip_me():

    vip = request.vip

    pending = await db_fetch_one(
        """
        SELECT to_plan
        FROM vip_upgrade_requests
        WHERE vip_id = :vip_id
          AND status = 'pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        {
            "vip_id": vip["id"],
        },
    )

    pending_plan = (
        pending["to_plan"]
        if pending
        else None
    )

    try:
        current_index = PLAN_ORDER.index(
            vip["subscription"]
        )
    except Exception:
        current_index = -1

    available_plans = [
        p
        for p in PLAN_ORDER
        if PLAN_ORDER.index(p) > current_index
    ]

    today = today_kenya_iso()

    used_row = await db_fetch_one(
        """
        SELECT COUNT(*) AS c
        FROM vip_picks
        WHERE number = :number
          AND (created_at AT TIME ZONE 'Africa/Nairobi')::date = :today::date
        """,
        {
            "number": vip["number"],
            "today": today,
        },
    )

    used = int(
        used_row["c"]
        if used_row
        else 0
    )

    quota = get_quota(
        vip["subscription"]
    )

    remaining = max(
        0,
        quota - used,
    )

    return jsonify({
        "id": vip["id"],
        "name": vip["name"],
        "number": vip["number"],
        "subscription": vip["subscription"],
        "subscription_expiry": vip["subscription_expiry"],
        "is_active": is_active_row(vip),
        "daily_quota": quota,
        "used_today": used,
        "remaining_today": remaining,
        "pending_upgrade": pending_plan,
        "available_plans": available_plans,
    })


# ============================================================
# VIP UPGRADE
# ============================================================

@app.route(
    "/vip/upgrade",
    methods=["POST"],
)
@vip_required
async def vip_upgrade():

    vip = request.vip

    data = request.get_json() or {}

    new_plan = str(
        data.get("plan")
        or ""
    ).lower()

    if new_plan not in PLAN_ORDER:
        return jsonify({
            "error": "Invalid plan"
        }), 400

    if (
        PLAN_ORDER.index(new_plan)
        <= PLAN_ORDER.index(vip["subscription"])
    ):
        return jsonify({
            "error": (
                "Upgrade must be higher "
                "than current plan"
            )
        }), 400

    existing_pending = await db_fetch_one(
        """
        SELECT 1
        FROM vip_upgrade_requests
        WHERE vip_id = :vip_id
          AND status = 'pending'
        LIMIT 1
        """,
        {
            "vip_id": vip["id"],
        },
    )

    if existing_pending:
        return jsonify({
            "error": (
                "Upgrade already pending approval"
            )
        }), 409

    await db_execute(
        """
        INSERT INTO vip_upgrade_requests (
            vip_id,
            from_plan,
            to_plan,
            status,
            created_at
        )
        VALUES (
            :vip_id,
            :from_plan,
            :to_plan,
            'pending',
            :created_at
        )
        """,
        {
            "vip_id": vip["id"],
            "from_plan": vip["subscription"],
            "to_plan": new_plan,
            "created_at": datetime.now(UTC),
        },
    )

    return jsonify({
        "success": True,
        "message": (
            "Upgrade request sent. "
            "Awaiting admin approval."
        ),
    })


# ============================================================
# VIP PICKS
# ============================================================

@app.route(
    "/vip/picks",
    methods=["GET"],
)
@vip_required
async def vip_picks():

    vip = request.vip

    today = today_kenya_iso()

    picks = await db_fetch_all(
        """
        SELECT
            match_id,
            home_team,
            away_team,
            match_time,
            pick,
            odds,
            created_at
        FROM vip_picks
        WHERE number = :number
          AND (created_at AT TIME ZONE 'Africa/Nairobi')::date = :today::date
        ORDER BY match_time ASC
        """,
        {
            "number": vip["number"],
            "today": today,
        },
    )

    return jsonify([
        dict(p)
        for p in picks
    ])


# ============================================================
# VIP QUOTA
# ============================================================

@app.route(
    "/vip/quota",
    methods=["GET"],
)
@vip_required
async def vip_quota():

    vip = request.vip

    today = today_kenya_iso()

    used_row = await db_fetch_one(
        """
        SELECT COUNT(*) AS c
        FROM vip_picks
        WHERE number = :number
          AND (created_at AT TIME ZONE 'Africa/Nairobi')::date = :today::date
        """,
        {
            "number": vip["number"],
            "today": today,
        },
    )

    used = int(
        used_row["c"]
        if used_row
        else 0
    )

    quota = get_quota(
        vip["subscription"]
    )

    return jsonify({
        "daily_quota": quota,
        "used_today": used,
        "remaining_today": max(
            0,
            quota - used,
        ),
    })


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.route(
    "/admin/login",
    methods=["POST"],
)
async def admin_login():

    data = request.get_json() or {}

    username = (
        data.get("username")
        or ""
    ).strip()

    password = data.get("password")

    if not username or not password:
        return jsonify({
            "error": (
                "Username and password required"
            )
        }), 400

    admin = await db_fetch_one(
        """
        SELECT
            id,
            username,
            password
        FROM admins
        WHERE username = :username
        """,
        {
            "username": username,
        },
    )

    if not admin:
        return jsonify({
            "error": "Invalid credentials"
        }), 401

    try:
        ok = check_password_hash(
            admin["password"],
            password,
        )
    except Exception:
        ok = (
            admin["password"]
            == password
        )

    if not ok:

        await db_execute(
            """
            UPDATE admins
            SET failed_attempts =
                COALESCE(failed_attempts, 0) + 1
            WHERE username = :username
            """,
            {
                "username": username,
            },
        )

        return jsonify({
            "error": "Invalid credentials"
        }), 401

    await db_execute(
        """
        UPDATE admins
        SET failed_attempts = 0
        WHERE username = :username
        """,
        {
            "username": username,
        },
    )

    payload = {
        "admin_id": admin["id"],
        "username": admin["username"],
        "exp": int(
            (
                datetime.now(UTC)
                + timedelta(
                    hours=JWT_EXP_HOURS
                )
            ).timestamp()
        ),
    }

    token = jwt.encode(
        payload,
        JWT_SECRET,
        algorithm="HS256",
    )

    if isinstance(token, bytes):
        token = token.decode("utf-8")

    log_admin(
        admin["username"],
        "login",
    )

    return jsonify({
        "message": "Login successful",
        "token": token,
        "admin": {
            "username": admin["username"],
        },
    })


# ============================================================
# ADMIN VIP APPROVAL
# ============================================================

async def approve_vip_user(vip_id):

    vip = await db_fetch_one(
        """
        SELECT subscription
        FROM vip_users
        WHERE id = :vip_id
        """,
        {
            "vip_id": vip_id,
        },
    )

    if not vip:
        return None

    days = PLAN_DAYS.get(
        (
            vip["subscription"]
            or ""
        ).lower(),
        0,
    )

    expiry = (
        today_kenya_date()
        + timedelta(days=days)
    ).strftime("%Y-%m-%d")

    await db_execute(
        """
        UPDATE vip_users
        SET
            approved = TRUE,
            subscription_expiry = :expiry
        WHERE id = :vip_id
        """,
        {
            "expiry": expiry,
            "vip_id": vip_id,
        },
    )

    return expiry


async def decline_vip_user(vip_id):

    await db_execute(
        """
        DELETE FROM vip_users
        WHERE id = :vip_id
        """,
        {
            "vip_id": vip_id,
        },
    )

    return True


# ============================================================
# ADMIN VIP LIST
# ============================================================

@app.route(
    "/admin/vips",
    methods=["GET"],
)
@admin_required
async def list_vips():

    rows = await db_fetch_all(
        """
        SELECT
            id,
            name,
            number,
            subscription,
            approved,
            subscription_expiry
        FROM vip_users
        ORDER BY id DESC
        """
    )

    log_admin(
        request.admin_username,
        "list_vips",
        len(rows),
    )

    return jsonify([
        dict(r)
        for r in rows
    ])


@app.route(
    "/admin/vips/pending",
    methods=["GET"],
)
@admin_required
async def list_pending():

    rows = await db_fetch_all(
        """
        SELECT
            id,
            name,
            number,
            subscription
        FROM vip_users
        WHERE approved = FALSE
        ORDER BY id DESC
        """
    )

    log_admin(
        request.admin_username,
        "list_pending",
        len(rows),
    )

    return jsonify([
        dict(r)
        for r in rows
    ])


@app.route(
    "/admin/vips/approve/<int:vip_id>",
    methods=["POST"],
)
@admin_required
async def approve(vip_id):

    expiry = await approve_vip_user(
        vip_id
    )

    if not expiry:
        return jsonify({
            "error": "VIP not found"
        }), 404

    log_admin(
        request.admin_username,
        "approve_vip",
        vip_id,
    )

    return jsonify({
        "message": "VIP approved",
        "expiry": expiry,
    })


@app.route(
    "/admin/vips/decline/<int:vip_id>",
    methods=["POST"],
)
@admin_required
async def decline(vip_id):

    await decline_vip_user(
        vip_id
    )

    log_admin(
        request.admin_username,
        "decline_vip",
        vip_id,
    )

    return jsonify({
        "message": "VIP declined"
    })


# ============================================================
# ADMIN VIP UPGRADES
# ============================================================

@app.route(
    "/admin/vip-upgrades",
    methods=["GET"],
)
@admin_required
async def list_upgrade_requests_vs_style():

    rows = await db_fetch_all(
        """
        SELECT
            id,
            vip_id,
            from_plan,
            to_plan,
            status,
            created_at
        FROM vip_upgrade_requests
        WHERE status = 'pending'
        ORDER BY created_at ASC
        """
    )

    return jsonify([
        dict(r)
        for r in rows
    ])


@app.route(
    "/admin/vip-upgrades/pending",
    methods=["GET"],
)
@admin_required
async def list_upgrade_requests_vip_style():

    rows = await db_fetch_all(
        """
        SELECT
            r.id,
            r.vip_id,
            u.name,
            u.number,
            r.to_plan AS new_plan,
            r.from_plan,
            r.status,
            r.created_at
        FROM vip_upgrade_requests r
        JOIN vip_users u
          ON u.id = r.vip_id
        WHERE r.status = 'pending'
        ORDER BY r.created_at DESC
        """
    )

    return jsonify([
        dict(r)
        for r in rows
    ])


@app.route(
    "/admin/vip-upgrades/approve/<int:req_id>",
    methods=["POST"],
)
@admin_required
async def approve_upgrade(req_id):

    result, error = await handle_upgrade_request(
        req_id,
        approve=True,
    )

    if error:
        return jsonify({
            "error": error
        }), 400

    return jsonify({
        "success": True,
        **result,
    })


@app.route(
    "/admin/vip-upgrades/decline/<int:req_id>",
    methods=["POST"],
)
@admin_required
async def decline_upgrade(req_id):

    result, error = await handle_upgrade_request(
        req_id,
        approve=False,
    )

    if error:
        return jsonify({
            "error": error
        }), 400

    return jsonify({
        "success": True,
        **result,
    })


# ============================================================
# ADMIN VIP PICK PREVIEW
# ============================================================

@app.route(
    "/admin/vip-picks/preview",
    methods=["GET"],
)
@admin_required
async def preview_matches():

    try:
        days = int(
            request.args.get(
                "days",
                3,
            )
        )
    except Exception:
        days = 3

    matches = await get_matches_for_next_days(
        days
    )

    return jsonify(matches)


# ============================================================
# ADMIN VIP PICK DISTRIBUTION
# ============================================================

@app.route(
    "/admin/vip-picks/distribute",
    methods=["POST"],
)
@admin_required
async def distribute_picks():

    data = request.get_json() or {}

    vip_numbers = data.get(
        "vip_numbers",
        [],
    )

    matches = data.get(
        "matches",
        [],
    )

    if not vip_numbers or not matches:
        return jsonify({
            "error": (
                "vip_numbers and matches required"
            )
        }), 400

    today = today_kenya_iso()

    summary = []
    received_vips = []
    skipped_vips = []

    # --------------------------------------------------------
    # Find VIPs with available quota
    # --------------------------------------------------------

    eligible_vips = []

    for number in vip_numbers:

        vip = await db_fetch_one(
            """
            SELECT
                subscription,
                subscription_expiry
            FROM vip_users
            WHERE number = :number
              AND approved = TRUE
            """,
            {
                "number": number,
            },
        )

        if not vip:
            continue

        expiry = parse_expiry(
            vip.get("subscription_expiry")
        )

        if (
            expiry is not None
            and expiry < today_kenya_date()
        ):
            continue

        quota = get_quota(
            vip["subscription"]
        )

        used_row = await db_fetch_one(
            """
            SELECT COUNT(*) AS c
            FROM vip_picks
            WHERE number = :number
              AND (created_at AT TIME ZONE 'Africa/Nairobi')::date = :today::date
            """,
            {
                "number": number,
                "today": today,
            },
        )

        used = int(
            used_row["c"]
            if used_row
            else 0
        )

        remaining = max(
            0,
            quota - used,
        )

        if remaining > 0:
            eligible_vips.append(
                number
            )

    if not eligible_vips:

        return jsonify({
            "error": (
                "No VIPs with available "
                "quota today. "
                "Distribution aborted."
            )
        }), 400

    # --------------------------------------------------------
    # Distribute picks
    # --------------------------------------------------------

    for number in vip_numbers:

        vip = await db_fetch_one(
            """
            SELECT
                subscription,
                subscription_expiry
            FROM vip_users
            WHERE number = :number
              AND approved = TRUE
            """,
            {
                "number": number,
            },
        )

        vip_summary = {
            "vip_number": number,
            "added": 0,
            "received_matches": [],
            "skipped_matches": [],
            "status": "",
        }

        if not vip:

            vip_summary["status"] = (
                "Skipped: Expired/Not approved"
            )

            skipped_vips.append(number)
            summary.append(vip_summary)

            continue

        expiry = parse_expiry(
            vip.get("subscription_expiry")
        )

        if (
            expiry is not None
            and expiry < today_kenya_date()
        ):

            vip_summary["status"] = (
                "Skipped: Expired/Not approved"
            )

            skipped_vips.append(number)
            summary.append(vip_summary)

            continue

        quota = get_quota(
            vip["subscription"]
        )

        used_row = await db_fetch_one(
            """
            SELECT COUNT(*) AS c
            FROM vip_picks
            WHERE number = :number
              AND (created_at AT TIME ZONE 'Africa/Nairobi')::date = :today::date
            """,
            {
                "number": number,
                "today": today,
            },
        )

        used = int(
            used_row["c"]
            if used_row
            else 0
        )

        remaining = max(
            0,
            quota - used,
        )

        added = 0

        for m in matches:

            if added >= remaining:

                vip_summary[
                    "skipped_matches"
                ].append({
                    "match_id": m.get(
                        "match_id"
                    ),
                    "reason": "Quota full",
                })

                break

            if "match_id" not in m:

                vip_summary[
                    "skipped_matches"
                ].append({
                    "match_id": None,
                    "reason": (
                        "Missing match_id"
                    ),
                })

                continue

            match_id = m["match_id"]

            exists = await db_fetch_one(
                """
                SELECT 1
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

            if exists:

                vip_summary[
                    "skipped_matches"
                ].append({
                    "match_id": match_id,
                    "reason": "Already picked",
                })

                continue

            match = await db_fetch_one(
                """
                SELECT
                    id AS match_id,
                    home_team_name AS home,
                    away_team_name AS away,
                    utcdate AS utc
                FROM matches
                WHERE id = :match_id
                """,
                {
                    "match_id": match_id,
                },
            )

            if not match:

                vip_summary[
                    "skipped_matches"
                ].append({
                    "match_id": match_id,
                    "reason": (
                        "Match not found"
                    ),
                })

                continue

            try:
                odds = float(
                    m.get(
                        "odds",
                        1.5,
                    )
                )
            except Exception:
                odds = 1.5

            pick = str(
                m.get(
                    "pick",
                    "1X2",
                )
            )

            if await insert_vip_pick(
                number,
                dict(match),
                pick,
                odds,
            ):

                added += 1

                vip_summary[
                    "received_matches"
                ].append(
                    match["match_id"]
                )

        vip_summary["added"] = added

        vip_summary["status"] = (
            "Received"
            if added > 0
            else "Skipped: Quota full or invalid"
        )

        if added > 0:
            received_vips.append(number)
        else:
            skipped_vips.append(number)

        summary.append(vip_summary)

    log_admin(
        request.admin_username,
        "distribute_picks",
        {
            "vip_count": len(vip_numbers),
            "match_count": len(matches),
            "received_vips": received_vips,
            "skipped_vips": skipped_vips,
        },
    )

    return jsonify({
        "summary": summary,
        "received_vips": received_vips,
        "skipped_vips": skipped_vips,
    })


# ============================================================
# ADMIN CLEAR ALL VIP PICKS
# ============================================================

@app.route(
    "/admin/vip-picks/clear",
    methods=["POST"],
)
@admin_required
async def clear_all_vip_picks():

    row = await db_fetch_one(
        """
        SELECT COUNT(*) AS c
        FROM vip_picks
        """
    )

    count = int(
        row["c"]
        if row
        else 0
    )

    await db_execute(
        """
        DELETE FROM vip_picks
        """
    )

    log_admin(
        request.admin_username,
        "clear_vip_picks",
        count,
    )

    return jsonify({
        "success": True,
        "message": "All VIP picks cleared",
        "deleted_rows": count,
    })


# ============================================================
# ADMIN CLEAR VIP PICKS FOR NUMBER
# ============================================================

@app.route(
    "/admin/vip-picks/clear/<string:number>",
    methods=["POST"],
)
@admin_required
async def clear_vip_picks_for_number(
    number
):

    row = await db_fetch_one(
        """
        SELECT COUNT(*) AS c
        FROM vip_picks
        WHERE number = :number
        """,
        {
            "number": number,
        },
    )

    count = int(
        row["c"]
        if row
        else 0
    )

    if count == 0:
        return jsonify({
            "success": False,
            "message": (
                "No picks found for this VIP"
            ),
        }), 404

    await db_execute(
        """
        DELETE FROM vip_picks
        WHERE number = :number
        """,
        {
            "number": number,
        },
    )

    log_admin(
        request.admin_username,
        "clear_vip_picks_for_vip",
        {
            "vip_number": number,
            "deleted": count,
        },
    )

    return jsonify({
        "success": True,
        "vip_number": number,
        "deleted_rows": count,
    })


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(e):

    return jsonify({
        "error": "endpoint not found"
    }), 404


@app.errorhandler(500)
def internal_error(e):

    log_json(
        "error",
        event="internal_server_error",
        error=str(e),
    )

    return jsonify({
        "error": "internal server error"
    }), 500


# ============================================================
# POSTGRESQL DB INIT
# ============================================================

async def init_db_async():

    print(
        f"[VIP DB] Initializing PostgreSQL "
        f"schema: {DB_SCHEMA}"
    )

    # --------------------------------------------------------
    # VIP USERS
    # --------------------------------------------------------

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS vip_users (
            id BIGSERIAL PRIMARY KEY,
            name TEXT,
            number TEXT UNIQUE,
            subscription TEXT,
            subscription_expiry TEXT,
            approved BOOLEAN DEFAULT FALSE
        )
        """
    )

    # --------------------------------------------------------
    # VIP PICKS
    # --------------------------------------------------------

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS vip_picks (
            id BIGSERIAL PRIMARY KEY,
            number TEXT NOT NULL,
            match_id BIGINT NOT NULL,
            home_team TEXT,
            away_team TEXT,
            match_time TIMESTAMPTZ,
            pick TEXT,
            odds DOUBLE PRECISION,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # --------------------------------------------------------
    # ADMINS
    # --------------------------------------------------------

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id BIGSERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            failed_attempts INTEGER DEFAULT 0
        )
        """
    )

    # --------------------------------------------------------
    # VIP UPGRADE REQUESTS
    # --------------------------------------------------------

    await db_execute(
        """
        CREATE TABLE IF NOT EXISTS vip_upgrade_requests (
            id BIGSERIAL PRIMARY KEY,
            vip_id BIGINT,
            from_plan TEXT,
            to_plan TEXT,
            status TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMPTZ
        )
        """
    )

    # --------------------------------------------------------
    # INDEXES
    # --------------------------------------------------------

    await db_execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_vip_picks_number_created
        ON vip_picks(number, created_at)
        """
    )

    await db_execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_vip_picks_match_id
        ON vip_picks(match_id)
        """
    )

    await db_execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_vip_upgrade_status
        ON vip_upgrade_requests(status)
        """
    )

    print(
        "[VIP DB] PostgreSQL initialization complete."
    )


# ============================================================
# APP RUNNER
# ============================================================

if __name__ == "__main__":

    import asyncio

    asyncio.run(
        init_db_async()
    )

    port = int(
        os.environ.get(
            "PORT",
            5004,
        )
    )

    log_json(
        "info",
        event="api_start",
        port=port,
        schema=DB_SCHEMA,
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=(
            os.getenv(
                "FLASK_DEBUG",
                "0",
            )
            == "1"
        ),
    )
