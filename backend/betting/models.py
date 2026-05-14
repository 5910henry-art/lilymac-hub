# models.py
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Numeric, Column, Integer, String, DateTime
from datetime import datetime
from decimal import Decimal

db = SQLAlchemy()


# -------------------------
# User
# -------------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False, index=True)
    password = db.Column(db.String(200), nullable=False)
    balance = db.Column(Numeric(14, 2), default=Decimal("0.00"))
    is_admin = db.Column(db.Boolean, default=False, index=True)
    created = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # relationships
    bets = db.relationship('Bet', backref='user', lazy="selectin")
    transactions = db.relationship('Transaction', backref='user', lazy="selectin")
    betslips = db.relationship('BetSlip', backref='user', lazy="selectin")


# -------------------------
# Match
# -------------------------
class Match(db.Model):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    competition = Column(String(100))
    matchday = Column(Integer)
    utcdate = Column(DateTime)
    status = Column(String(50), index=True)
    home_team_id = Column(Integer)
    away_team_id = Column(Integer)
    home_score = Column(Integer, default=0)
    away_score = Column(Integer, default=0)
    home_team_name = Column(String(100))
    away_team_name = Column(String(100))
    season = Column(String(50))
    generated_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    bookmark = db.relationship("Bookmark", back_populates="match", uselist=False)


# -------------------------
# Bookmark (1:1 with Match)
# -------------------------
class Bookmark(db.Model):
    __tablename__ = "bookmark"

    match_id = db.Column(
        db.Integer,
        db.ForeignKey("matches.id"),
        primary_key=True,
        index=True
    )

    league = db.Column(db.String(100))
    home_team = db.Column(db.String(100))
    away_team = db.Column(db.String(100))
    match_time = db.Column(db.DateTime, index=True)

    # odds
    home_odds = db.Column(Numeric(8, 2))
    draw_odds = db.Column(Numeric(8, 2))
    away_odds = db.Column(Numeric(8, 2))

    over05 = db.Column(Numeric(8, 2))
    under05 = db.Column(Numeric(8, 2))
    over15 = db.Column(Numeric(8, 2))
    under15 = db.Column(Numeric(8, 2))
    over25 = db.Column(Numeric(8, 2))
    under25 = db.Column(Numeric(8, 2))
    over35 = db.Column(Numeric(8, 2))
    under35 = db.Column(Numeric(8, 2))

    gg_odds = db.Column(Numeric(8, 2))
    ng_odds = db.Column(Numeric(8, 2))

    # probabilities
    p_home = db.Column(Numeric(8, 4))
    p_draw = db.Column(Numeric(8, 4))
    p_away = db.Column(Numeric(8, 4))

    # relationship
    match = db.relationship("Match", back_populates="bookmark")


# -------------------------
# Bet (single)
# -------------------------
class Bet(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False,
        index=True
    )

    match_id = db.Column(
        db.Integer,
        db.ForeignKey('matches.id'),
        nullable=False,
        index=True
    )

    selection = db.Column(db.String(100))
    odds = db.Column(Numeric(12, 4))
    amount = db.Column(Numeric(14, 2))
    potential = db.Column(Numeric(14, 2))

    status = db.Column(db.String(50), default="pending", index=True)
    cashed_out = db.Column(db.Boolean, default=False)

    current_cashout = db.Column(Numeric(14, 2), default=Decimal("0.00"))
    cashout_tx_id = db.Column(db.Integer)

    created = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # relationship
    match = db.relationship("Match", backref="bets", lazy="selectin")


# -------------------------
# Transaction
# -------------------------
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False,
        index=True
    )

    type = db.Column(db.String(50), index=True)
    amount = db.Column(Numeric(14, 2))
    balance_after = db.Column(Numeric(14, 2))
    created = db.Column(db.DateTime, default=datetime.utcnow, index=True)


# -------------------------
# BetSelection (for slips)
# -------------------------
class BetSelection(db.Model):
    __tablename__ = "bet_selection"

    id = db.Column(db.Integer, primary_key=True)

    betslip_id = db.Column(
        db.Integer,
        db.ForeignKey('bet_slip.id'),
        nullable=False,
        index=True
    )

    bookmark_id = db.Column(
        db.Integer,
        db.ForeignKey('bookmark.match_id'),
        nullable=False,
        index=True
    )

    selection = db.Column(db.String(100))
    odds = db.Column(Numeric(12, 4))
    status = db.Column(db.String(50), default="pending", index=True)

    league = db.Column(db.String(100))
    home_team = db.Column(db.String(100))
    away_team = db.Column(db.String(100))
    match_time = db.Column(db.DateTime)

    created = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # relationships
    bookmark = db.relationship("Bookmark", lazy="joined")


# -------------------------
# BetSlip (multi-bet)
# -------------------------
class BetSlip(db.Model):
    __tablename__ = "bet_slip"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False,
        index=True
    )

    stake = db.Column(Numeric(14, 2), nullable=False)
    total_odds = db.Column(Numeric(14, 4), nullable=False)
    potential = db.Column(Numeric(14, 2), nullable=False)

    status = db.Column(db.String(50), default="pending", index=True)
    cashed_out = db.Column(db.Boolean, default=False)

    cashout_tx_id = db.Column(db.Integer)
    current_cashout = db.Column(Numeric(14, 2), default=Decimal("0.00"))

    created = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    match_id = db.Column(
        db.Integer,
        db.ForeignKey('matches.id'),
        nullable=True,
        index=True
    )

    # relationships
    match = db.relationship('Match', backref='betslips', lazy='selectin')

    selections = db.relationship(
        "BetSelection",
        backref="betslip",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
