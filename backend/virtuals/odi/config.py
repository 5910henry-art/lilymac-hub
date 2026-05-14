# config.py
# ==============================
# FOOTBALL SIMULATION CONFIG
# ==============================

# ------------------------------
# CORE ELO SETTINGS
# ------------------------------
ELO_START_RATING = 1500
ELO_K_FACTOR = 20
HOME_ADVANTAGE_ELO = 65

# ------------------------------
# GOAL MODEL SETTINGS
# ------------------------------
BASE_HOME_GOALS = 1.25
BASE_AWAY_GOALS = 1.05
ATTACK_DEFENSE_WEIGHT = 0.04
MATCH_NOISE_STD = 0.80
MAX_GOALS_PER_TEAM = 6

# ------------------------------
# MATCH BEHAVIOR
# ------------------------------
HOME_WIN_BONUS = 0.30
DRAW_BASE_RATE = 0.26
GOAL_CORRELATION = 0.12

# ------------------------------
# STYLE MULTIPLIERS
# ------------------------------
STYLE_MULTIPLIERS = {
    "control": {
        "goal_modifier": 0.96,
        "attack_boost": 0.98,
        "defense_boost": 1.08,
        "variance": 0.80,
    },
    "balanced": {
        "goal_modifier": 1.00,
        "attack_boost": 1.00,
        "defense_boost": 1.00,
        "variance": 1.00,
    },
    "attacking": {
        "goal_modifier": 1.08,
        "attack_boost": 1.10,
        "defense_boost": 0.96,
        "variance": 1.15,
    },
    "defensive": {
        "goal_modifier": 0.92,
        "attack_boost": 0.95,
        "defense_boost": 1.12,
        "variance": 0.85,
    },
    "chaos": {
        "goal_modifier": 1.06,
        "attack_boost": 1.08,
        "defense_boost": 0.93,
        "variance": 1.35,
    },
}

# ------------------------------
# CANONICAL TEAM LIST
# Use these names everywhere internally
# ------------------------------
TEAMS = [
    "Real Madrid",
    "Barca",
    "A. Madrid",
    "A. Bilbao",
    "R. Sociedad",
    "Villareal",
    "Valencia",
    "Sevilla",
    "Getafe",
    "Osa",
    "Mallorca",
    "Alaves",
    "Gra",
    "Leganes",
    "Levante",
    "Esp",
    "Celta Vigo",
    "Betis",
    "Almeria",
    "Valladolid",
]

# ------------------------------
# TEAM STYLES
# ------------------------------
TEAM_STYLE = {
    "Real Madrid": "control",
    "Barca": "chaos",
    "A. Madrid": "defensive",
    "A. Bilbao": "balanced",
    "R. Sociedad": "control",
    "Villareal": "chaos",
    "Valencia": "balanced",
    "Sevilla": "chaos",
    "Getafe": "defensive",
    "Osa": "defensive",
    "Mallorca": "balanced",
    "Alaves": "defensive",
    "Gra": "chaos",
    "Leganes": "defensive",
    "Levante": "chaos",
    "Esp": "balanced",
    "Celta Vigo": "attacking",
    "Betis": "attacking",
    "Almeria": "chaos",
    "Valladolid": "balanced",
}

# ------------------------------
# TEAM ALIASES
# Accepts common full names and abbreviations
# ------------------------------
TEAM_ALIASES = {
    "realmadrid": "Real Madrid",
    "madrid": "Real Madrid",

    "barca": "Barca",
    "barcelona": "Barca",

    "amadrid": "A. Madrid",
    "atleticomadrid": "A. Madrid",
    "atleticomadrid": "A. Madrid",
    "atletico": "A. Madrid",

    "abilbao": "A. Bilbao",
    "athleticbilbao": "A. Bilbao",
    "athleticclub": "A. Bilbao",

    "rsociedad": "R. Sociedad",
    "realsociedad": "R. Sociedad",

    "villareal": "Villareal",
    "villarreal": "Villareal",

    "valencia": "Valencia",
    "sevilla": "Sevilla",
    "getafe": "Getafe",

    "osa": "Osa",
    "osasuna": "Osa",

    "mallorca": "Mallorca",
    "alaves": "Alaves",

    "gra": "Gra",
    "granada": "Gra",

    "leganes": "Leganes",
    "levante": "Levante",

    "esp": "Esp",
    "espanyol": "Esp",

    "celtavigo": "Celta Vigo",
    "celta": "Celta Vigo",

    "betis": "Betis",
    "almeria": "Almeria",
    "valladolid": "Valladolid",
}
