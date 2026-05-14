# sim.py
import argparse

from engine import play_match, play_round, get_table, reset, teams


# ==============================
# FIXTURE GENERATOR
# ==============================

def generate_fixtures(team_list):
    fixtures = []
    n = len(team_list)

    for i in range(n):
        for j in range(i + 1, n):
            home = team_list[i]
            away = team_list[j]
            fixtures.append((home, away))
            fixtures.append((away, home))

    return fixtures


# ==============================
# SEASON SIMULATION
# ==============================

def simulate_season():
    print("\n⚽ Starting Season Simulation...\n")

    team_list = list(teams.keys())
    fixtures = generate_fixtures(team_list)

    week = 1
    week_size = len(team_list) // 2

    for i in range(0, len(fixtures), week_size):
        round_fixtures = fixtures[i:i + week_size]

        print("\n====================")
        print(f" WEEK {week}")
        print("====================")

        play_round(round_fixtures)

        table = get_table()
        print("\n--- TOP 5 ---")
        for t in table[:5]:
            print(f"{t['team']:15} | Pts: {t['points']:3} | GD: {t['gd']:3} | ELO: {t['elo']}")

        week += 1

    print("\n🏁 SEASON COMPLETE\n")

    final_table = get_table()

    print("FINAL TABLE (TOP 10)")
    print("=====================")
    for i, t in enumerate(final_table[:10], 1):
        print(
            f"{i}. {t['team']:15} "
            f"| Pts: {t['points']:3} "
            f"| GD: {t['gd']:3} "
            f"| GF: {t['gf']:3} "
            f"| GA: {t['ga']:3} "
            f"| ELO: {t['elo']}"
        )


# ==============================
# SINGLE MATCH TEST MODE
# ==============================

def quick_test():
    print("\n⚽ Quick Match Test\n")

    play_match("Real Madrid", "Barca")
    play_match("A. Madrid", "Sevilla")
    play_match("Valencia", "Villareal")

    print("\nTABLE SNAPSHOT")
    table = get_table()

    for t in table[:8]:
        print(f"{t['team']:15} | Pts: {t['points']:3} | ELO: {t['elo']}")


# ==============================
# RESET + RUN
# ==============================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", default="season", choices=["season", "test"])
    args = parser.parse_args()

    reset()

    if args.mode == "season":
        simulate_season()
    else:
        quick_test()
