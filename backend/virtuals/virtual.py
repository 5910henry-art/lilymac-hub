import os
import signal
import logging
from flask_cors import CORS

from .config import app, init_app, db
from .routes import bp as routes_bp
from .engine import start_virtual_engine, stop_engine

logger = logging.getLogger("virtual-engine")

# ---------------- INITIALIZATION ----------------
init_app()
CORS(app, resources={r"/*": {"origins": "*"}})
app.register_blueprint(routes_bp)

# ---------------- SIGNAL HANDLER ----------------
def _signal_handler(signum, frame):
    logger.info("Received shutdown signal (%s). Stopping engine...", signum)
    stop_engine()
    logger.info("Shutdown complete")
    os._exit(0)

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# ---------------- ENGINE CALLBACK ----------------
def emit_fixture_update(fixture):
    """
    Previously used for Socket.IO.
    Now disabled (use API polling instead).
    """
    pass  # no-op

# ---------------- MAIN ----------------
if __name__ == "__main__":
    logger.info("⚽ Virtual PRO+ Engine starting...")

    # Start engine WITHOUT socket events
    start_virtual_engine(emit_update_callback=None)

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 5002))

    logger.info("🚀 Starting Flask server on %s:%s", host, port)

    try:
        app.run(
            host=host,
            port=port,
            debug=False,
        )
    except Exception:
        logger.exception("Exception while running server")
    finally:
        logger.info("🛑 Server shutting down, stopping virtual engine...")
        stop_engine()
        logger.info("✅ Server shut down cleanly.")
