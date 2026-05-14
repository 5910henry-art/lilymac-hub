# clean_result.py
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

TEAM_ALIASES = {
    "barca": "Barcelona",
    "barcelona": "Barcelona",
    "a.madrid": "Atletico Madrid",
    "atmadrid": "Atletico Madrid",
    "atleticomadrid": "Atletico Madrid",
    "atletico madrid": "Atletico Madrid",
    "a.bilbao": "Athletic Bilbao",
    "abilbao": "Athletic Bilbao",
    "athleticbilbao": "Athletic Bilbao",
    "athletic bilbao": "Athletic Bilbao",
    "r.sociedad": "Real Sociedad",
    "rsociedad": "Real Sociedad",
    "real sociedad": "Real Sociedad",
    "realmadrid": "Real Madrid",
    "real madrid": "Real Madrid",
    "villareal": "Villarreal",
    "villarreal": "Villarreal",
    "esp": "Espanyol",
    "espanyol": "Espanyol",
    "osa": "Osasuna",
    "osasuna": "Osasuna",
    "gra": "Granada",
    "granada": "Granada",
    "levante": "Levante",
    "getafe": "Getafe",
    "valladolid": "Valladolid",
    "valencia": "Valencia",
    "alaves": "Alaves",
    "almeria": "Almeria",
    "betis": "Real Betis",
    "real betis": "Real Betis",
    "sevilla": "Sevilla",
    "leganes": "Leganes",
    "mallorca": "Mallorca",
    "celta vigo": "Celta Vigo",
    "celtavigo": "Celta Vigo",
    "celta": "Celta Vigo",
}

VALID_RESULTS = {"H", "D", "A"}


def normalize_team(name: str) -> str:
    raw = str(name).strip()
    raw = raw.split("(")[0].strip()  # fixes Barcelona (Barca and similar broken text

    key = raw.lower().replace(".", "").replace("-", " ").replace("_", " ")
    key = " ".join(key.split())
    key_compact = key.replace(" ", "")

    mapped = TEAM_ALIASES.get(key) or TEAM_ALIASES.get(key_compact)
    if mapped:
        return mapped

    return key.title()


def is_data_row(line: str) -> bool:
    line = line.strip()
    if not line:
        return False
    if line.startswith(("u0_", "~/", "$", "python ", "cat ", "=== ")):
        return False
    return True


def parse_row(line: str):
    row = next(csv.reader([line]))
    if len(row) < 6:
        return None

    week, home, away, hg, ag, result = row[:6]

    try:
        week_i = int(str(week).strip())
        hg_i = int(str(hg).strip())
        ag_i = int(str(ag).strip())
    except ValueError:
        return None

    result = str(result).strip().upper()
    if result not in VALID_RESULTS:
        result = "H" if hg_i > ag_i else ("A" if hg_i < ag_i else "D")

    home = normalize_team(home)
    away = normalize_team(away)

    return week_i, home, away, hg_i, ag_i, result


def clean_file(input_path: Path, output_path: Path) -> None:
    rows = []
    seen = set()

    with input_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not is_data_row(line):
                continue
            if line.lower().startswith("week,home_team,away_team"):
                continue

            parsed = parse_row(line)
            if not parsed:
                continue

            key = parsed
            if key in seen:
                continue
            seen.add(key)
            rows.append(parsed)

    rows.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]))

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["week", "home_team", "away_team", "home_goals", "away_goals", "result"])
        writer.writerows(rows)

    print(f"Cleaned {len(rows)} rows -> {output_path}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python clean_result.py result.txt result_clean.csv")
        raise SystemExit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    clean_file(input_path, output_path)


if __name__ == "__main__":
    main()
