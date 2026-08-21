import os
import time
import logging
import redis

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_compress import Compress
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.dispatcher import DispatcherMiddleware

# ----------------------------
# Import backend apps
# ----------------------------
from app import app as main_app
from vipadmin import app as vipadmin_app
from betting.bet import app as bet_app
from virtuals.virtual import app as virtual_app

# ----------------------------
# Config
# ----------------------------
FLASK_HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.environ.get("FLASK_PORT", 5000))

REDIS_URL = os.environ.get("REDIS_URL")

FRONTEND_BUILD = os.path.join(
    os.path.dirname(__file__),
    "../frontend/build"
)

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)

logger = logging.getLogger("gateway")

# Force virtual engine logs to be visible
logging.getLogger("virtual-engine").setLevel(logging.INFO)
# ----------------------------
# Flask Gateway
# ----------------------------
gateway = Flask(
    "gateway",
    static_folder=FRONTEND_BUILD,
    static_url_path=""
)

CORS(gateway, resources={r"/*": {"origins": "*"}})
Compress(gateway)

# ----------------------------
# Redis (SAFE INIT)
# ----------------------------
redis_client = None

if REDIS_URL:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        logger.info("Connected to Redis")
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        redis_client = None
else:
    logger.warning("No Redis URL provided (running without Redis)")

# ----------------------------
# Rate limiter
# ----------------------------
limiter = Limiter(
    get_remote_address,
    app=gateway,
    default_limits=["200 per minute"],
    storage_uri=REDIS_URL or "memory://"
)

# ----------------------------
# Health routes
# ----------------------------
@gateway.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "gateway"
    })


@gateway.route("/health/redis")
def redis_health():
    if not redis_client:
        return jsonify({"redis": "disabled"})
    try:
        redis_client.ping()
        return jsonify({"redis": "ok"})
    except Exception as e:
        return jsonify({"redis": "error", "message": str(e)}), 500

# ----------------------------
# Serve React build
# ----------------------------
@gateway.route("/", defaults={"path": ""})
@gateway.route("/<path:path>")
def serve(path):
    full_path = os.path.join(FRONTEND_BUILD, path)

    if path and os.path.exists(full_path):
        return send_from_directory(FRONTEND_BUILD, path)

    return send_from_directory(FRONTEND_BUILD, "index.html")

# ----------------------------
# Dispatcher (multi apps)
# ----------------------------
application = DispatcherMiddleware(
    gateway,
    {
        "/app": main_app,
        "/bet": bet_app,
        "/vipadmin": vipadmin_app,
        "/vip": vipadmin_app,
        "/virtual": virtual_app,
    }
)

# ----------------------------
# Production WSGI entry
# ----------------------------
app = application

# ----------------------------
# Optional engine import
# ----------------------------
try:
    from virtuals.engine import start_virtual_engine
except Exception as e:
    print(f"❌ Failed to import virtual engine: {e}")
    start_virtual_engine = None

# ----------------------------
# Local development only
# ----------------------------
if __name__ == "__main__":
    logger.info("Running in local mode")

    if start_virtual_engine is not None:
        try:
            logger.info("Starting virtual engine...")

            start_virtual_engine()

            import virtuals.engine as eng

            logger.info(
                "Engine thread alive: %s",
                eng.engine_thread.is_alive()
                if eng.engine_thread
                else False
            )

        except Exception:
            logger.exception("Engine startup failed")
    else:
        logger.warning("Virtual engine unavailable")

    from werkzeug.serving import run_simple

    logger.info(
        "Starting gateway on %s:%s",
        FLASK_HOST,
        FLASK_PORT
    )

    run_simple(
        FLASK_HOST,
        FLASK_PORT,
        application,
        threaded=True,
        use_reloader=False,
        use_debugger=True,
    )

