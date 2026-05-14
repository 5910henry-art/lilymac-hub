# bookmarks.py
# ==============================
# PERSISTENT TEAM SNAPSHOT LAYER
# ==============================

BOOKMARKS = {}


def _safe_played(team):
    return max(1, getattr(team, "played", 0))


def build_bookmarks(teams):
    """
    Build stable cached ratings from current team state.
    `teams` should be the engine's teams dict.
    """
    global BOOKMARKS
    BOOKMARKS = {}

    for name, team in teams.items():
        played = _safe_played(team)
        gf_pg = team.goals_for / played
        ga_pg = team.goals_against / played
        elo = team.elo

        attack = 1.0 + (gf_pg / 1.8) + ((elo - 1500) / 900.0)
        defense = 1.20 - (ga_pg / 2.2) + ((elo - 1500) / 1200.0)
        strength = (attack + defense) / 2.0

        BOOKMARKS[name] = {
            "attack": max(0.60, attack),
            "defense": max(0.60, defense),
            "strength": max(0.60, strength),
            "elo": elo,
        }


def refresh_bookmarks(teams):
    build_bookmarks(teams)


def get_bookmark(team_name):
    return BOOKMARKS.get(team_name, {
        "attack": 1.0,
        "defense": 1.0,
        "strength": 1.0,
        "elo": 1500,
    })
