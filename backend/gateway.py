import os
import logging
import threading
import atexit

import redis

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from flask_compress import Compress
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.dispatcher import DispatcherMiddleware


# ============================================================
# Backend apps
# ============================================================

from app import app as main_app
from vipadmin import app as vipadmin_app
from betting.bet import app as bet_app
from virtuals.virtual import app as virtual_app


# ============================================================
# Configuration
# ============================================================

FLASK_HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.environ.get("FLASK_PORT", 5000))

REDIS_URL = os.environ.get("REDIS_URL")

FRONTEND_BUILD = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "../frontend/build",
    )
)


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)

logger = logging.getLogger("gateway")

logging.getLogger("virtual-engine").setLevel(logging.INFO)


# ============================================================
# Gateway Flask application
# ============================================================

gateway = Flask(
    "gateway",
    static_folder=FRONTEND_BUILD,
    static_url_path="",
)

CORS(
    gateway,
    resources={
        r"/*": {
            "origins": "*",
        }
    },
)

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
    get_remote_address,
    app=gateway,
    default_limits=["200 per minute"],
    storage_uri=REDIS_URL or "memory://",
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
# React frontend
# ============================================================

@gateway.route("/", defaults={"path": ""})
@gateway.route("/<path:path>")
def serve(path):

    full_path = os.path.join(
        FRONTEND_BUILD,
        path,
    )

    if path and os.path.exists(full_path):
        return send_from_directory(
            FRONTEND_BUILD,
            path,
        )

    return send_from_directory(
        FRONTEND_BUILD,
        "index.html",
    )


# ============================================================
# Multi-application dispatcher
# ============================================================

application = DispatcherMiddleware(
    gateway,
    {
        "/app": main_app,
        "/bet": bet_app,
        "/vipadmin": vipadmin_app,
        "/vip": vipadmin_app,
        "/virtual": virtual_app,
    },
)


# ============================================================
# Production WSGI entry
# ============================================================

app = application


# ============================================================
# Virtual engine
# ============================================================

try:
    from virtuals.engine import (
        start_virtual_engine,
        stop_engine,
    )

except Exception:
    logger.exception(
        "Failed to import virtual engine"
    )

    start_virtual_engine = None
    stop_engine = None


# ============================================================
# Engine configuration
# ============================================================

RUN_VIRTUAL_ENGINE = os.getenv(
    "RUN_VIRTUAL_ENGINE",
    "1",
).lower() in (
    "1",
    "true",
    "yes",
    "on",
)


_engine_thread = None
_engine_start_lock = threading.Lock()


# ============================================================
# Start virtual engine
# ============================================================

def start_production_virtual_engine():
    global _engine_thread

    if not RUN_VIRTUAL_ENGINE:
        logger.info(
            "Virtual engine disabled by RUN_VIRTUAL_ENGINE"
        )
        return False

    if start_virtual_engine is None:
        logger.warning(
            "Virtual engine unavailable"
        )
        return False

    with _engine_start_lock:

        if (
            _engine_thread is not None
            and _engine_thread.is_alive()
        ):
            logger.info(
                "Virtual engine already running"
            )
            return True

        try:

            logger.info(
                "Starting virtual engine..."
            )

            _engine_thread = start_virtual_engine()

            logger.info(
                "Engine thread alive: %s",
                (
                    _engine_thread.is_alive()
                    if _engine_thread
                    else False
                ),
            )

            return _engine_thread is not None

        except Exception:

            logger.exception(
                "Engine startup failed"
            )

            return False


# ============================================================
# Delayed engine bootstrap
# ============================================================

def _engine_bootstrap():

    logger.info(
        "Waiting for Gunicorn application startup..."
    )

    # Give Gunicorn time to finish importing the WSGI
    # application and bind Render's assigned PORT.
    #
    # This prevents expensive virtual-engine recovery
    # from blocking Render's port detection.

    import time

    time.sleep(3)

    start_production_virtual_engine()


# ============================================================
# Start engine AFTER module import
# ============================================================

if RUN_VIRTUAL_ENGINE:

    threading.Thread(
        target=_engine_bootstrap,
        name="virtual-engine-bootstrap",
        daemon=True,
    ).start()


# ============================================================
# Shutdown
# ============================================================

def _shutdown_engine():

    if stop_engine is None:
        return

    try:

        logger.info(
            "Stopping virtual engine..."
        )

        stop_engine()

    except Exception:

        logger.exception(
            "Error stopping virtual engine"
        )


atexit.register(_shutdown_engine)


# ============================================================
# Local development
# ============================================================

if __name__ == "__main__":

    logger.info(
        "Running in local mode"
    )

    from werkzeug.serving import run_simple

    logger.info(
        "Starting gateway on %s:%s",
        FLASK_HOST,
        FLASK_PORT,
    )

    run_simple(
        FLASK_HOST,
        FLASK_PORT,
        application,
        threaded=True,
        use_reloader=False,
        use_debugger=True,
    )
