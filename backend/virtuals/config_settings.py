import os
import unicodedata
from datetime import timedelta

# ---------------- ENVIRONMENT ----------------
ENV = os.getenv("FLASK_ENV", "development")
DEBUG = ENV == "development"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ---------------- DATABASE ----------------
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

REDIS_URL = os.getenv("REDIS_URL")

DB_SCHEMA = os.getenv("DB_SCHEMA", "public")

USE_SQLITE_FALLBACK = not DATABASE_URL

if USE_SQLITE_FALLBACK:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DB_PATH = os.path.join(BASE_DIR, "football.db")
    DATABASE_URL = f"sqlite:///{DB_PATH}"
SCHEMA = None if USE_SQLITE_FALLBACK else DB_SCHEMA

# ---------------- JWT ----------------
JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET",
    "1223f671617d47d847101ee330653227e3c6241351a3e28baa12dafef84d5c2743802b7a7cd0c36d32260272c79d6c2fc321ed4b4178b3fbe40f577a4c132536",
)
JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)

# ---------------- SIMULATION / BETTING ----------------
BETTING_TIME = int(os.getenv("VIRTUAL_BETTING_TIME", "30"))
SIM_SECOND_PER_MINUTE = float(os.getenv("VIRTUAL_SIM_SECOND_PER_MINUTE", "0.5"))
MATCH_SIM_SECONDS = int(90 * SIM_SECOND_PER_MINUTE)

MAX_ACTIVE_MATCHES = int(os.getenv("VIRTUAL_MAX_ACTIVE_MATCHES", "10"))
MAX_EVENTS_PER_MATCH = int(os.getenv("VIRTUAL_MAX_EVENTS_PER_MATCH", "8"))

MAX_STAKE = float(os.getenv("MAX_STAKE", "10000.0"))
MAX_WIN = float(os.getenv("MAX_WIN", "100000.0"))

ROUND_INTERVAL = int(os.getenv("VIRTUAL_ROUND_INTERVAL", "120"))
MATCHES_PER_ROUND = int(os.getenv("VIRTUAL_MATCHES_PER_ROUND", "10"))
TOTAL_ROUNDS = int(os.getenv("VIRTUAL_TOTAL_ROUNDS", "38"))
UPCOMING_ROUNDS = int(os.getenv("VIRTUAL_UPCOMING_ROUNDS", "6"))

# ---------------- OFFICIAL TEAM LIST (CANONICAL SOURCE) ----------------
# IMPORTANT: MUST MATCH model.json KEYS EXACTLY (ASCII NORMALIZED)

TEAMS = {
    "Alaves",
    "Almeria",
    "Athletic Bilbao",
    "Atletico Madrid",
    "Barcelona",
    "Betis",
    "Celta Vigo",
    "Espanyol",
    "Getafe",
    "Granada",
    "Leganes",
    "Levante",
    "Mallorca",
    "Osasuna",
    "Real Madrid",
    "Real Sociedad",
    "Sevilla",
    "Valencia",
    "Valladolid",
    "Villarreal",
}

# ---------------- TEAM NORMALIZATION ----------------
# Converts any user input → canonical model.json format

TEAM_ALIASES = {
    "Alavés": "Alaves",
    "Almeria": "Almeria",
    "Almería": "Almeria",
    "Betis": "Betis",
    "Celta de Vigo": "Celta Vigo",
    "Celta Vigo": "Celta Vigo",
    "Atletico Madrid": "Atletico Madrid",
    "Atlético Madrid": "Atletico Madrid",
    "Athletic Club": "Athletic Bilbao",
    "Athletic Bilbao": "Athletic Bilbao",
    "Leganes": "Leganes",
    "Leganés": "Leganes",
    "R.sociedad": "Real Sociedad",
    "Real Sociedad": "Real Sociedad",
    "A.madrid": "Atletico Madrid",
    "A.bilbao": "Athletic Bilbao",
    "Barca": "Barcelona",
    "Barcelona": "Barcelona",
    "Valencia": "Valencia",
    "Sevilla": "Sevilla",
    "Getafe": "Getafe",
    "Osasuna": "Osasuna",
    "Villarreal": "Villarreal",
}

def strip_accents(text: str) -> str:
    if not text:
        return text
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

def normalize_team_name(team_name: str) -> str:
    if not team_name:
        return team_name

    cleaned = strip_accents(team_name.strip())
    return TEAM_ALIASES.get(cleaned, cleaned)

def validate_team(team_name: str) -> str:
    return normalize_team_name(team_name)

# ---------------- BETTING CONSTANTS ----------------
ALLOWED_SELECTIONS = {
    "home",
    "away",
    "draw",
}

MAX_SELECTIONS_PER_TICKET = int(os.getenv("MAX_SELECTIONS_PER_TICKET", "20"))
VIRTUAL_RTP_TARGET = 0.92

# ---------------- STATUS CONSTANTS ----------------
STATUS_SCHEDULED = "SCHEDULED"
STATUS_OPEN = "OPEN"
STATUS_RUNNING = "RUNNING"
STATUS_FINISHED = "FINISHED"

# ---------------- TABLE NAMES ----------------
def table_name(name: str) -> str:
    return f"{SCHEMA}.{name}" if SCHEMA else name

T_FIXTURES = table_name("virtual_fixtures")
T_ODDS = table_name("virtual_odds")
T_EVENTS = table_name("virtual_events")
T_VBETS = table_name("virtual_bets")
T_BET_TICKET = table_name("bet_ticket")
T_BET_SELECTION = table_name("bet_selection")
T_USER = table_name("user")
T_TRANSACTIONS = table_name("transactions")
T_BAL_HISTORY = table_name("balance_history")
