# bet.py
import os
import logging
import atexit
from flask import Flask
from flask_jwt_extended import JWTManager
from flask_cors import CORS
import threading

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

db_url = os.environ.get("DATABASE_URL")

if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url or "sqlite:///fallback.db"
app.config["JWT_SECRET_KEY"] = os.environ.get(
    "JWT_SECRET",
    "1223f671617d47d847101ee330653227e3c6241351a3e28baa12dafef84d5c2743802b7a7cd0c36d32260272c79d6c2fc321ed4b4178b3fbe40f577a4c132536"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Enable CORS
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
    logging.info(f"{rule.endpoint} -> {rule}")

# -------------------------
# Health check
# -------------------------
@app.route("/health")
def health():
    return {"status": "ok"}

# -------------------------
# Initialize database & scheduler
# -------------------------
stop_event = threading.Event()
scheduler_thread = None


def init_services():
    global scheduler_thread

    with app.app_context():
        db.create_all()

    if scheduler_thread is None:
        scheduler_thread = start_scheduler(
            app,
            interval_seconds=60,
            stop_event=stop_event
        )


def shutdown_scheduler():
    global scheduler_thread

    if scheduler_thread:
        stop_event.set()
        scheduler_thread.join(timeout=5)
        logging.info("Scheduler stopped gracefully.")


atexit.register(shutdown_scheduler)

if __name__ == "__main__":
    init_services()

    port = int(os.environ.get("PORT", 5005))
    print(f"🚀 Starting bet_app on port {port}...")
    app.run(debug=True, host="0.0.0.0", port=port)
