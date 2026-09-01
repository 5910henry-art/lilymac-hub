# bet.py

import os
import logging
import atexit
import threading

from flask import Flask
from flask_jwt_extended import JWTManager
from flask_cors import CORS

# -------------------------
# Central database config
# -------------------------
from config2 import SQLALCHEMY_DATABASE_URL, DB_SCHEMA

# -------------------------
# Relative imports
# -------------------------
from .models import db
from .auth import auth_bp
from .scheduler import start_scheduler
from .wallet import register_wallet_routes
from .admin import register_admin_routes
from .bets import bet_bp


# -------------------------
# Flask app setup
# -------------------------
app = Flask(__name__)

# Use the SAME PostgreSQL configuration as the main backend
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URL

app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "connect_args": {
        "options": f"-csearch_path={DB_SCHEMA},public"
    }
}

app.config["JWT_SECRET_KEY"] = os.environ.get(
    "JWT_SECRET",
    "1223f671617d47d847101ee330653227e3c6241351a3e28baa12dafef84d5c2743802b7a7cd0c36d32260272c79d6c2fc321ed4b4178b3fbe40f577a4c132536"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


# -------------------------
# Enable CORS
# -------------------------
CORS(app)


# -------------------------
# Initialize extensions
# -------------------------
db.init_app(app)
jwt = JWTManager(app)


# -------------------------
# Register blueprints/routes
# -------------------------
app.register_blueprint(auth_bp)
app.register_blueprint(bet_bp)

register_wallet_routes(app)
register_admin_routes(app)


# -------------------------
# Debug: list all routes
# -------------------------
print("🔹 Registered routes:")

for rule in app.url_map.iter_rules():
    logging.info("%s -> %s", rule.endpoint, rule)


# -------------------------
# Health check
# -------------------------
@app.route("/health")
def health():
    return {"status": "ok"}


# -------------------------
# Scheduler
# -------------------------
stop_event = threading.Event()
scheduler_thread = None


def init_services():
    global scheduler_thread

    # Prevent duplicate scheduler instances.
    if scheduler_thread is not None and scheduler_thread.is_alive():
        logging.info(
            "Betting scheduler already running."
        )
        return scheduler_thread

    # Verify PostgreSQL before starting scheduler.
    with app.app_context():
        db.session.execute(db.text("SELECT 1"))

        db.create_all()

        print(
            f"✅ PostgreSQL connected | schema={DB_SCHEMA}"
        )

    # Start the scheduler.
    scheduler_thread = start_scheduler(
        app,
        interval_seconds=60,
        stop_event=stop_event,
    )

    print(
        "✅ Betting scheduler started | interval=60s"
    )

    return scheduler_thread


# -------------------------
# Graceful shutdown
# -------------------------
def shutdown_scheduler():
    global scheduler_thread

    if scheduler_thread is not None:
        stop_event.set()

        if scheduler_thread.is_alive():
            scheduler_thread.join(timeout=5)

        scheduler_thread = None

        logging.info(
            "Scheduler stopped gracefully."
        )


atexit.register(shutdown_scheduler)


# -------------------------
# Start application
# -------------------------
if __name__ == "__main__":
    init_services()

    port = int(
        os.environ.get(
            "PORT",
            5005,
        )
    )

    print(
        f"🚀 Starting bet_app on port {port}..."
    )

    app.run(
        debug=True,
        use_reloader=False,
        host="0.0.0.0",
        port=port,
    )
