# config.py

import logging

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_socketio import SocketIO
import redis

import virtuals.config_settings as settings

# ---------------- LOGGING ----------------
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("virtual-engine")
logger.info(f"Starting in {settings.ENV} mode, log level {settings.LOG_LEVEL}")

# ---------------- REDIS ----------------
REDIS_URL = settings.REDIS_URL
redis_client = redis.from_url(REDIS_URL)

# ---------------- FLASK APP ----------------
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = settings.DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = settings.JWT_SECRET_KEY
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = settings.JWT_ACCESS_TOKEN_EXPIRES

if settings.DATABASE_URL.startswith("sqlite:"):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {"check_same_thread": False}
    }
else:
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": 20,
        "max_overflow": 30,
        "pool_timeout": 30,
    }

# ---------------- EXTENSIONS ----------------
db = SQLAlchemy()
jwt = JWTManager()

# ✅ Use threading instead of eventlet
socketio = SocketIO(async_mode="threading")


def init_app():
    """Initialize Flask app, extensions, and database."""
    db.init_app(app)
    jwt.init_app(app)

    socketio.init_app(
        app,
        message_queue=REDIS_URL,
        cors_allowed_origins="*",
    )

    # Import models so SQLAlchemy registers them
    import model  # noqa: F401

    with app.app_context():
        if settings.DATABASE_URL.startswith("sqlite"):
            from sqlalchemy import text

            try:
                db.session.execute(text("PRAGMA journal_mode=WAL;"))
                db.session.execute(text("PRAGMA foreign_keys=ON;"))
                db.session.commit()
                logger.info("SQLite WAL + FK enabled")
            except Exception:
                db.session.rollback()
                logger.exception("SQLite pragma setup failed")

        db.create_all()
        logger.info("Database tables created successfully")

    return app

TEAM_RATINGS = {
    "Barcelona": 95.8,
    "Atletico Madrid": 89.5,
    "Real Madrid": 84.8,
    "Valencia": 80.7,
    "Sevilla": 79.4,
    "Getafe": 79.4,
    "Athletic Bilbao": 75.9,
    "Espanyol": 75.9,
    "Real Sociedad": 74.1,
    "Real Betis": 74.1,
    "Alaves": 74.1,
    "Almeria": 72.3,
    "Leganes": 71.2,
    "Villarreal": 70.6,
    "Levante": 70.6,
    "Mallorca": 68.8,
    "Celta Vigo": 68.7,
    "Osasuna": 66.5,
    "Granada": 64.1,
    "Valladolid": 63.3,
}
