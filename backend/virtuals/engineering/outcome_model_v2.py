import sys
import math
from collections import defaultdict, Counter

# -----------------------------
# Helpers
# -----------------------------

def parse_line(line):
    parts = line.strip().split("|")
    if len(parts) != 3:
        return None

    fixture = parts[0].strip().lower()
    odds = parts[1].strip().split()
    result = parts[2].strip()

    if len(odds) != 3:
        return None

    try:
        oh, od, oa = map(float, odds)
    except:
        return None

    try:
        hg, ag = result.split("-")
        hg = int(hg)
        ag = int(ag)
    except:
        return None

    if hg > ag:
        label = "H"
    elif hg < ag:
        label = "A"
    else:
        label = "D"

    home, away = fixture.split("vs")
    home = home.strip()
    away = away.strip()

    return home, away, oh, od, oa, label


# -----------------------------
# Bucketing odds (important)
# -----------------------------

def bucket(x):
    # coarse market structure bucket
    if x < 1.50:
        return "A"
    elif x < 2.10:
        return "B"
    elif x < 2.80:
        return "C"
    elif x < 3.60:
        return "D"
    else:
        return "E"


def state(home, away, oh, od, oa):
    # FIXTURE + ODDS STRUCTURE
    return (
        home + "_" + away,
        bucket(oh),
        bucket(od),
        bucket(oa),
    )


# -----------------------------
# Model
# -----------------------------

class OutcomeModel:
    def __init__(self):
        self.counts = defaultdict(Counter)
        self.total = Counter()

    def fit(self, path):
        rows = 0

        with open(path) as f:
            for line in f:
                parsed = parse_line(line)
                if not parsed:
                    continue

                home, away, oh, od, oa, label = parsed
                s = state(home, away, oh, od, oa)

                self.counts[s][label] += 1
                self.total[s] += 1
                rows += 1

        print(f"Trained on {rows} rows")

    def predict(self, home, away, oh, od, oa):
        s = state(home.lower(), away.lower(), oh, od, oa)

        c = self.counts.get(s, None)

        if not c:
            # fallback: pure odds shape only
            c = Counter({"H": 1, "D": 1, "A": 1})

        total = sum(c.values())

        probs = {
            "H": c["H"] / total,
            "D": c["D"] / total,
            "A": c["A"] / total,
        }

        return max(probs, key=probs.get), probs


# -----------------------------
# CLI
# -----------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python outcome_model_v2.py fixtures_results.txt")
        sys.exit()

    model = OutcomeModel()
    model.fit(sys.argv[1])

    # quick test sample
    print("\nSample prediction:")

    # take first usable line
    with open(sys.argv[1]) as f:
        for line in f:
            p = parse_line(line)
            if p:
                home, away, oh, od, oa, label = p
                pred, probs = model.predict(home, away, oh, od, oa)
                print(f"{home} vs {away}")
                print("Pred:", pred, "Actual:", label)
                print("Probs:", probs)
                break
