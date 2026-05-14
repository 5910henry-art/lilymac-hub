import re
from collections import defaultdict
from pathlib import Path

FIXTURES_FILE = "fixtures.txt"
RESULTS_FILE = "results.txt"
OUTPUT_FILE = "fixtures_results.txt"


# -----------------------------
# TEAM NORMALIZATION
# -----------------------------
def canon(name: str):
    n = name.lower().strip()
    n = n.replace(".", "")
    n = " ".join(n.split())

    mapping = {
        "barca": "barcelona",
        "fc barcelona": "barcelona",
        "barcelona": "barcelona",

        "a madrid": "atletico madrid",
        "atl madrid": "atletico madrid",
        "atletico madrid": "atletico madrid",

        "a bilbao": "athletic bilbao",
        "ath bilbao": "athletic bilbao",
        "athletic bilbao": "athletic bilbao",

        "r sociedad": "real sociedad",
        "real sociedad": "real sociedad",

        "villareal": "villarreal",
        "villarreal": "villarreal",

        "esp": "espanyol",
        "espanyol": "espanyol",

        "gra": "granada",
        "granada": "granada",

        "osa": "osasuna",
        "osasuna": "osasuna",

        "getafe": "getafe",
        "leganes": "leganes",
        "mallorca": "mallorca",
        "sevilla": "sevilla",
        "valencia": "valencia",
        "real madrid": "real madrid",
        "almeria": "almeria",
        "levante": "levante",
        "celta vigo": "celta vigo",
        "valladolid": "valladolid",
        "alaves": "alaves",
        "betis": "betis",
    }

    return mapping.get(n, n)


# -----------------------------
# ORDER-INDEPENDENT KEY
# -----------------------------
def key(a, b):
    return tuple(sorted([a, b]))


# -----------------------------
# PARSE FIXTURES (FIXED)
# -----------------------------
def parse_fixtures(path):
    fixtures = []

    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue

        # -----------------------------
        # FORMAT 1: PIPE FORMAT
        # Home | Away | 1 | X | 2
        # -----------------------------
        if "|" in line and "vs" not in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 5:
                continue

            home = canon(parts[0])
            away = canon(parts[1])
            odds = f"{parts[2]} {parts[3]} {parts[4]}"

            fixtures.append({
                "home": home,
                "away": away,
                "odds": odds
            })
            continue

        # -----------------------------
        # FORMAT 2: VS FORMAT
        # Home vs Away — 1: x | X: y | 2: z
        # -----------------------------
        m = re.match(r"^(.+?)\s+vs\s+(.+?)\s+[—-]\s+(.+)$", line)
        if m:
            home = canon(m.group(1))
            away = canon(m.group(2))

            odds_part = m.group(3)

            # extract odds numbers in order 1, X, 2
            o1 = re.search(r"1:\s*([\d.]+)", odds_part)
            ox = re.search(r"X:\s*([\d.]+)", odds_part)
            o2 = re.search(r"2:\s*([\d.]+)", odds_part)

            if not (o1 and ox and o2):
                continue

            odds = f"{o1.group(1)} {ox.group(1)} {o2.group(1)}"

            fixtures.append({
                "home": home,
                "away": away,
                "odds": odds
            })

    return fixtures
# -----------------------------
# PARSE RESULTS
# -----------------------------
def parse_results(path):
    results = []

    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue

        m = re.match(r"^(.+?)\s+(\d+)-(\d+)\s+(.+)$", line)
        if not m:
            continue

        home = canon(m.group(1))
        away = canon(m.group(4))
        score = f"{m.group(2)}-{m.group(3)}"

        results.append({
            "home": home,
            "away": away,
            "score": score
        })

    return results


# -----------------------------
# LOAD DATA
# -----------------------------
fixtures = parse_fixtures(FIXTURES_FILE)
results = parse_results(RESULTS_FILE)

print(f"Fixtures parsed: {len(fixtures)}")
print(f"Results parsed: {len(results)}")


# -----------------------------
# BUILD LOOKUP MAP
# -----------------------------
fixture_map = defaultdict(list)

for f in fixtures:
    fixture_map[key(f["home"], f["away"])].append(f)


# -----------------------------
# MATCHING (ORDER INDEPENDENT)
# -----------------------------
output = []
matched = 0

for r in results:
    k = key(r["home"], r["away"])

    if fixture_map[k]:
        f = fixture_map[k].pop(0)

        output.append(
            f"{f['home']} vs {f['away']} | {f['odds']} | {r['score']}"
        )
        matched += 1


# -----------------------------
# SAVE OUTPUT
# -----------------------------
Path(OUTPUT_FILE).write_text("\n".join(output) + "\n", encoding="utf-8")

print(f"Done ✔ matched: {matched}")
print(f"Saved: {OUTPUT_FILE}")
