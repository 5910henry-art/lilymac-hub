# gateway.py

import os
import logging

import redis

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_compress import Compress
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from socketio import WSGIApp


# ============================================================
# Backend apps
# ============================================================

from app import app as main_app, socketio
from vipadmin import app as vipadmin_app
from betting.bet import app as bet_app, init_services


# ============================================================
# Configuration
# ============================================================

FLASK_HOST = os.environ.get(
    "FLASK_HOST",
    "0.0.0.0",
)

# Render provides PORT automatically.
# FLASK_PORT can still be used for local development.
FLASK_PORT = int(
    os.environ.get(
        "PORT",
        os.environ.get("FLASK_PORT", 5000),
    )
)

REDIS_URL = os.environ.get("REDIS_URL")


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)

logger = logging.getLogger("gateway")


# ============================================================
# Gateway Flask application
# ============================================================

gateway = Flask("gateway")


# ============================================================
# CORS
# ============================================================

CORS(
    gateway,
    resources={
        r"/*": {
            "origins": "*",
        }
    },
)


# ============================================================
# Compression
# ============================================================

Compress(gateway)


# ============================================================
# Redis
# ============================================================

redis_client = None

if REDIS_URL:
    try:
        redis_client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
        )

        redis_client.ping()

        logger.info("Connected to Redis")

    except Exception as exc:
        logger.warning(
            "Redis connection failed: %s",
            exc,
        )

        redis_client = None

else:
    logger.warning(
        "No Redis URL provided (running without Redis)"
    )


# ============================================================
# Rate limiter
# ============================================================

limiter = Limiter(
    key_func=get_remote_address,
    app=gateway,
    default_limits=[
        "200 per minute",
    ],
    storage_uri=(
        REDIS_URL
        or "memory://"
    ),
)


# ============================================================
# Betting scheduler
#
# The scheduler is started by the gateway so Render does not
# need a separate scheduler process.
# ============================================================

try:
    init_services()

    logger.info(
        "✅ Betting scheduler initialized from gateway"
    )

except Exception:
    logger.exception(
        "❌ Failed to initialize betting scheduler"
    )


# ============================================================
# Health
# ============================================================

@gateway.route("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "gateway",
        }
    )


@gateway.route("/health/redis")
def redis_health():
    if not redis_client:
        return jsonify(
            {
                "redis": "disabled",
            }
        )

    try:
        redis_client.ping()

        return jsonify(
            {
                "redis": "ok",
            }
        )

    except Exception as exc:
        return jsonify(
            {
                "redis": "error",
                "message": str(exc),
            }
        ), 500


# ============================================================
# REAL FOOTBALL LIVE BRIDGE
#
# /live belongs to main_app (app.py), while the gateway itself
# is the Render production entrypoint.
#
# Re-enter main_app's Flask request context so the existing
# /live route executes exactly as it does when accessed directly.
# ============================================================

@gateway.route("/live", methods=["GET"])
def gateway_live():
    environ = request.environ.copy()

    with main_app.request_context(environ):
        adapter = main_app.url_map.bind_to_environ(environ)

        endpoint, values = adapter.match(
            path_info="/live",
            method=environ.get("REQUEST_METHOD", "GET"),
        )

        view = main_app.view_functions[endpoint]

        return view(**values)


# ============================================================
# Multi-application dispatcher
#
# Gateway serves the main backend applications.
#
# Virtual is intentionally NOT mounted here.
# Virtual runs as a separate Render service.
#
# Routes:
#   /app       -> main application
#   /bet       -> betting application
#   /vipadmin  -> VIP admin application
#   /vip       -> VIP admin application
# ============================================================

http_application = DispatcherMiddleware(
    gateway,
    {
        "/app": main_app,
        "/bet": bet_app,
        "/vipadmin": vipadmin_app,
        "/vip": vipadmin_app,
    },
)


# ============================================================
# Socket.IO production WSGI entry
#
# Socket.IO handles:
#     /socket.io/*
#
# All ordinary HTTP requests fall through to the existing
# gateway dispatcher:
#     /app/*
#     /bet/*
#     /vipadmin/*
#     /vip/*
#     /live
#     /health
# ============================================================

application = WSGIApp(
    socketio.server,
    http_application,
)


# ============================================================
# Production WSGI entry
# ============================================================

app = application


# ============================================================
# Local development
# ============================================================

if __name__ == "__main__":
    logger.info(
        "Running gateway in local mode"
    )

    logger.info(
        "Starting gateway on %s:%s",
        FLASK_HOST,
        FLASK_PORT,
    )

    from werkzeug.serving import run_simple

    run_simple(
        FLASK_HOST,
        FLASK_PORT,
        application,
        threaded=True,
        use_reloader=False,
        use_debugger=False,
    )
