import numpy as np
import pandas as pd

# =========================
# 1. CONFIG
# =========================

K = 20
HOME_ADVANTAGE = 0.30
BASE_GOALS_HOME = 1.25
BASE_GOALS_AWAY = 1.05
ATTACK_WEIGHT = 0.045
DEFENSE_WEIGHT = 0.040
NOISE_STD = 0.80

np.random.seed(42)

# =========================
# 2. TEAMS
# =========================

teams = [
    "Real Madrid", "Barcelona", "Atletico Madrid",
    "Athletic Bilbao", "Real Sociedad", "Villarreal",
    "Real Betis", "Valencia", "Sevilla", "Celta Vigo",
    "Getafe", "Osasuna", "Mallorca", "Alaves",
    "Granada", "Espanyol", "Leganes", "Almeria",
    "Valladolid", "Levante"
]

# Initial Elo ratings (centered around 75–92 scale)
ratings = {team: 80 + np.random.randn()*3 for team in teams}


# =========================
# 3. HELPER FUNCTIONS
# =========================

def attack_rating(r):
    return r / 10

def defense_rating(r):
    return r / 10


def expected_goals(home, away):
    rh, ra = ratings[home], ratings[away]

    att_h = attack_rating(rh)
    att_a = attack_rating(ra)
    def_h = defense_rating(rh)
    def_a = defense_rating(ra)

    xg_home = (
        BASE_GOALS_HOME
        + (att_h - def_a) * ATTACK_WEIGHT
        + HOME_ADVANTAGE
    )

    xg_away = (
        BASE_GOALS_AWAY
        + (att_a - def_h) * DEFENSE_WEIGHT
    )

    # Upset / randomness injection
    xg_home += np.random.normal(0, NOISE_STD)
    xg_away += np.random.normal(0, NOISE_STD)

    return max(0.05, xg_home), max(0.05, xg_away)


def play_match(home, away):
    xg_h, xg_a = expected_goals(home, away)

    goals_h = np.random.poisson(xg_h)
    goals_a = np.random.poisson(xg_a)

    return goals_h, goals_a


def update_elo(home, away, gh, ga):
    rh, ra = ratings[home], ratings[away]

    expected_home = 1 / (1 + 10 ** ((ra - rh) / 400))

    result_home = 1 if gh > ga else 0 if gh < ga else 0.5

    ratings[home] += K * (result_home - expected_home)
    ratings[away] += K * ((1 - result_home) - (1 - expected_home))


# =========================
# 4. SIMULATE MATCHDAY
# =========================

def simulate_week(fixtures):
    results = []

    for home, away in fixtures:
        gh, ga = play_match(home, away)
        update_elo(home, away, gh, ga)

        results.append({
            "home": home,
            "away": away,
            "score": f"{gh}-{ga}"
        })

    return pd.DataFrame(results)


# =========================
# 5. EXAMPLE FIXTURE GENERATOR
# =========================

def generate_fixtures():
    shuffled = teams.copy()
    np.random.shuffle(shuffled)

    return [(shuffled[i], shuffled[i+1]) for i in range(0, len(shuffled), 2)]


# =========================
# 6. RUN SIMULATION
# =========================

if __name__ == "__main__":
    for week in range(1, 11):
        print(f"\n=== WEEK {week} ===")
        fixtures = generate_fixtures()
        df = simulate_week(fixtures)
        print(df)
