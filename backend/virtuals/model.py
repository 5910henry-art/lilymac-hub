# model.py

from virtuals.config import db
from virtuals.config_settings import SCHEMA

# ---------------- STATUS CONSTANTS ----------------
STATUS_SCHEDULED = "SCHEDULED"
STATUS_OPEN = "OPEN"
STATUS_RUNNING = "RUNNING"
STATUS_FINISHED = "FINISHED"

# ---------------- TABLE ARGS ----------------
_table_args = {"schema": SCHEMA} if SCHEMA else {}


# ---------------- FIXTURE ----------------
class Fixture(db.Model):
    __tablename__ = "virtual_fixtures"
    __table_args__ = _table_args

    id = db.Column(db.Integer, primary_key=True)

    home = db.Column(db.String, nullable=False)
    away = db.Column(db.String, nullable=False)

    status = db.Column(db.String, index=True, default=STATUS_SCHEDULED)

    home_score = db.Column(db.Integer, default=0)
    away_score = db.Column(db.Integer, default=0)

    open_time = db.Column(db.DateTime(timezone=True))
    start_time = db.Column(db.DateTime(timezone=True))
    end_time = db.Column(db.DateTime(timezone=True))

    event_count = db.Column(db.Integer, default=0)
    round = db.Column(db.Integer, index=True, default=0)

    # ✅ concurrency protection
    version_id = db.Column(db.Integer, nullable=False, default=0)

    __mapper_args__ = {
        "version_id_col": version_id
    }

    # ✅ season tracking (simple & effective)
    season = db.Column(db.Integer, nullable=False, index=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.current_timestamp()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp()
    )

    is_settled = db.Column(db.Boolean, default=False, nullable=False)
    is_simulating = db.Column(db.Boolean, default=False)


# ---------------- ODDS ----------------
class Odds(db.Model):
    __tablename__ = "virtual_odds"
    __table_args__ = _table_args

    id = db.Column(db.Integer, primary_key=True)

    match_id = db.Column(db.Integer, index=True, nullable=False)

    home = db.Column(db.Float)
    draw = db.Column(db.Float)
    away = db.Column(db.Float)

    over15 = db.Column(db.Float)
    under15 = db.Column(db.Float)

    over25 = db.Column(db.Float)
    under25 = db.Column(db.Float)

    btts_yes = db.Column(db.Float)
    btts_no = db.Column(db.Float)

    created_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.current_timestamp()
    )


# ---------------- EVENTS ----------------
class Event(db.Model):
    __tablename__ = "virtual_events"
    __table_args__ = _table_args

    id = db.Column(db.Integer, primary_key=True)

    match_id = db.Column(db.Integer, index=True, nullable=False)

    minute = db.Column(db.Integer)
    team = db.Column(db.String)
    type = db.Column(db.String)
    description = db.Column(db.String)

    created_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.current_timestamp()
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp()
    )


# ---------------- VIRTUAL BET ----------------
class VirtualBet(db.Model):
    __tablename__ = "virtual_bets"
    __table_args__ = _table_args

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, index=True, nullable=False)
    match_id = db.Column(db.Integer, nullable=False)

    selection = db.Column(db.String, nullable=False)
    stake = db.Column(db.Float, nullable=False)
    odds = db.Column(db.Float, nullable=False)

    status = db.Column(db.String, default="OPEN")
    ticket_id = db.Column(db.String, index=True, nullable=False)

    created_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.current_timestamp()
    )
