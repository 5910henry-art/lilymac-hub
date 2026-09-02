#!/usr/bin/env python3

"""
BUILD HISTORICAL STANDINGS

Reconstructs historical league standings from:
    henry_schema.matches

Actual matches columns:
    id
    competition
    matchday
    utcdate
    status
    home_team_id
    away_team_id
    home_score
    away_score
    home_team_name
    away_team_name
    season
    generated_at

Creates:
    henry_schema.historical_standings

Then patches g.py so historical standings can be used by
get_rank_from_snapshot(...).

IMPORTANT:
- Only FINISHED matches are used.
- Standings are calculated separately for each competition + season.
- Standings are calculated after each matchday.
- Current database contains seasons 2023-2026.
- 2022 is automatically skipped because there are no 2022 rows.
"""

import os
import re
import sys
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime, timezone

import psycopg2


# ============================================================
# CONFIG
# ============================================================

DB_URL = os.getenv("DATABASE_URL")

SCHEMA = "henry_schema"
TABLE = "historical_standings"

G_PATH = "g.py"

START_SEASON = 2022
END_SEASON = 2026

DOMESTIC_COMPETITIONS = {
    "Premier League",
    "Primera Division",
    "Bundesliga",
    "Ligue 1",
    "Serie A",
}

# Whether to include competitions other than domestic leagues.
# The data is still stored, but g.py position lookups should
# primarily use domestic competitions.
INCLUDE_OTHER_COMPETITIONS = True


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    """
    Connect using DATABASE_URL.

    SQLAlchemy URLs such as:
        postgresql+psycopg://...

    are converted to:
        postgresql://...

    because psycopg2 expects the standard PostgreSQL scheme.
    """

    db_url = os.getenv("DATABASE_URL")

    if not db_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set."
        )

    if db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace(
            "postgresql+psycopg://",
            "postgresql://",
            1,
        )

    elif db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace(
            "postgresql+asyncpg://",
            "postgresql://",
            1,
        )

    return psycopg2.connect(db_url)


# ============================================================
# COMPETITION NORMALIZATION
# ============================================================

def normalize_competition(name):
    if not name:
        return ""

    name = str(name).strip()

    aliases = {
        "Premier League": "PL",
        "Primera Division": "PD",
        "Bundesliga": "BL1",
        "Ligue 1": "FL1",
        "Serie A": "SA",
        "UEFA Champions League": "CL",
    }

    return aliases.get(name, name.upper().replace(" ", "_"))


# ============================================================
# CREATE TABLE
# ============================================================

def create_table(conn):
    print("\n1️⃣ Creating historical_standings table...")

    with conn.cursor() as cur:

        cur.execute(
            f"""
            DROP TABLE IF EXISTS {SCHEMA}.{TABLE};
            """
        )

        cur.execute(
            f"""
            CREATE TABLE {SCHEMA}.{TABLE} (
                id BIGSERIAL PRIMARY KEY,

                competition TEXT NOT NULL,
                league_code TEXT NOT NULL,

                season INTEGER NOT NULL,
                matchday INTEGER NOT NULL,

                snapshot_date TIMESTAMPTZ,

                team_id BIGINT NOT NULL,

                rank INTEGER NOT NULL,

                points INTEGER NOT NULL DEFAULT 0,

                win INTEGER NOT NULL DEFAULT 0,
                draw INTEGER NOT NULL DEFAULT 0,
                lose INTEGER NOT NULL DEFAULT 0,

                goals_for INTEGER NOT NULL DEFAULT 0,
                goals_against INTEGER NOT NULL DEFAULT 0,
                goal_diff INTEGER NOT NULL DEFAULT 0,

                matches_played INTEGER NOT NULL DEFAULT 0,

                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                UNIQUE (
                    competition,
                    season,
                    matchday,
                    team_id
                )
            );
            """
        )

        cur.execute(
            f"""
            CREATE INDEX idx_hist_standings_lookup
            ON {SCHEMA}.{TABLE}
            (
                league_code,
                season,
                team_id,
                matchday
            );
            """
        )

        cur.execute(
            f"""
            CREATE INDEX idx_hist_standings_date
            ON {SCHEMA}.{TABLE}
            (
                league_code,
                season,
                snapshot_date
            );
            """
        )

        cur.execute(
            f"""
            CREATE INDEX idx_hist_standings_team
            ON {SCHEMA}.{TABLE}
            (
                team_id,
                season,
                matchday
            );
            """
        )

        conn.commit()

    print("   ✅ Table ready")


# ============================================================
# LOAD MATCHES
# ============================================================

def load_matches(conn):
    print("\n2️⃣ Loading finished matches...")

    with conn.cursor() as cur:

        cur.execute(
            f"""
            SELECT
                id,
                competition,
                matchday,
                utcdate,
                status,
                home_team_id,
                away_team_id,
                home_score,
                away_score,
                home_team_name,
                away_team_name,
                season
            FROM {SCHEMA}.matches
            WHERE season BETWEEN %s AND %s
              AND status = 'FINISHED'
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
              AND home_team_id IS NOT NULL
              AND away_team_id IS NOT NULL
            ORDER BY
                competition,
                season,
                matchday NULLS LAST,
                utcdate,
                id
            """,
            (START_SEASON, END_SEASON),
        )

        rows = cur.fetchall()

    print(f"   Finished matches loaded: {len(rows):,}")

    return rows


# ============================================================
# BUILD STANDINGS
# ============================================================

def build_standings(matches):
    """
    Returns:

        [
            {
                competition,
                league_code,
                season,
                matchday,
                snapshot_date,
                team_id,
                rank,
                points,
                win,
                draw,
                lose,
                goals_for,
                goals_against,
                goal_diff,
                matches_played
            }
        ]
    """

    # --------------------------------------------------------
    # Group matches by competition + season
    # --------------------------------------------------------

    grouped = defaultdict(list)

    for row in matches:

        (
            match_id,
            competition,
            matchday,
            utcdate,
            status,
            home_id,
            away_id,
            home_score,
            away_score,
            home_name,
            away_name,
            season,
        ) = row

        competition = str(competition).strip()

        if not competition:
            continue

        if not INCLUDE_OTHER_COMPETITIONS:
            if competition not in DOMESTIC_COMPETITIONS:
                continue

        # Matchday must exist for true matchweek snapshots.
        if matchday is None:
            continue

        grouped[
            (
                competition,
                int(season),
            )
        ].append(
            {
                "id": match_id,
                "competition": competition,
                "matchday": int(matchday),
                "utcdate": utcdate,
                "home_id": int(home_id),
                "away_id": int(away_id),
                "home_score": int(home_score),
                "away_score": int(away_score),
            }
        )

    print(
        f"   Competition/season groups: {len(grouped)}"
    )

    all_snapshots = []

    # --------------------------------------------------------
    # Process each competition + season
    # --------------------------------------------------------

    for group_no, ((competition, season), games) in enumerate(
        sorted(grouped.items()),
        start=1,
    ):

        league_code = normalize_competition(competition)

        print()
        print(
            f"   [{group_no}/{len(grouped)}] "
            f"{competition} {season}"
        )

        # ----------------------------------------------------
        # Teams
        # ----------------------------------------------------

        teams = set()

        for game in games:
            teams.add(game["home_id"])
            teams.add(game["away_id"])

        # ----------------------------------------------------
        # Determine matchdays
        # ----------------------------------------------------

        matchdays = defaultdict(list)

        for game in games:
            matchdays[game["matchday"]].append(game)

        ordered_matchdays = sorted(matchdays)

        # ----------------------------------------------------
        # Initialize standings
        # ----------------------------------------------------

        table = {}

        for team_id in teams:
            table[team_id] = {
                "team_id": team_id,
                "points": 0,
                "win": 0,
                "draw": 0,
                "lose": 0,
                "goals_for": 0,
                "goals_against": 0,
                "goal_diff": 0,
                "matches_played": 0,
            }

        # ----------------------------------------------------
        # Process each matchday
        # ----------------------------------------------------

        for matchday in ordered_matchdays:

            day_games = matchdays[matchday]

            # ------------------------------------------------
            # Apply ALL matches in this matchday first.
            #
            # This is important.
            #
            # We do NOT rank teams after every individual
            # match because several matches belong to the same
            # matchweek.
            # ------------------------------------------------

            latest_date = None

            for game in day_games:

                home = game["home_id"]
                away = game["away_id"]

                hg = game["home_score"]
                ag = game["away_score"]

                if game["utcdate"] is not None:
                    if latest_date is None or game["utcdate"] > latest_date:
                        latest_date = game["utcdate"]

                h = table[home]
                a = table[away]

                h["matches_played"] += 1
                a["matches_played"] += 1

                h["goals_for"] += hg
                h["goals_against"] += ag

                a["goals_for"] += ag
                a["goals_against"] += hg

                if hg > ag:

                    h["win"] += 1
                    a["lose"] += 1

                    h["points"] += 3

                elif hg < ag:

                    a["win"] += 1
                    h["lose"] += 1

                    a["points"] += 3

                else:

                    h["draw"] += 1
                    a["draw"] += 1

                    h["points"] += 1
                    a["points"] += 1

            # ------------------------------------------------
            # Calculate goal difference
            # ------------------------------------------------

            for team in table.values():

                team["goal_diff"] = (
                    team["goals_for"]
                    - team["goals_against"]
                )

            # ------------------------------------------------
            # Rank table
            #
            # Standard league ordering:
            #
            # 1. Points
            # 2. Goal difference
            # 3. Goals scored
            #
            # team_id is only deterministic fallback.
            # ------------------------------------------------

            ranked = sorted(
                table.values(),
                key=lambda x: (
                    -x["points"],
                    -x["goal_diff"],
                    -x["goals_for"],
                    x["team_id"],
                ),
            )

            # ------------------------------------------------
            # Store snapshot
            # ------------------------------------------------

            for rank, team in enumerate(
                ranked,
                start=1,
            ):

                all_snapshots.append(
                    {
                        "competition": competition,
                        "league_code": league_code,
                        "season": season,
                        "matchday": matchday,
                        "snapshot_date": latest_date,
                        "team_id": team["team_id"],
                        "rank": rank,
                        "points": team["points"],
                        "win": team["win"],
                        "draw": team["draw"],
                        "lose": team["lose"],
                        "goals_for": team["goals_for"],
                        "goals_against": team["goals_against"],
                        "goal_diff": team["goal_diff"],
                        "matches_played": team["matches_played"],
                    }
                )

        print(
            f"      Teams: {len(teams)} | "
            f"Matchdays: {len(ordered_matchdays)} | "
            f"Snapshots: {len(teams) * len(ordered_matchdays)}"
        )

    return all_snapshots


# ============================================================
# SAVE SNAPSHOTS
# ============================================================

def save_snapshots(conn, snapshots):
    """
    Fast PostgreSQL bulk insert using COPY.

    Much faster than executemany() for thousands
    of historical standings rows.
    """

    print("\n3️⃣ Saving historical standings with PostgreSQL COPY...")

    if not snapshots:
        print("   ⚠️ No snapshots generated.")
        return

    import io
    import csv

    buffer = io.StringIO()

    writer = csv.writer(
        buffer,
        lineterminator="\n",
    )

    for s in snapshots:

        snapshot_date = s["snapshot_date"]

        if snapshot_date is not None:
            snapshot_date = snapshot_date.isoformat()
        else:
            snapshot_date = ""

        writer.writerow([
            s["competition"],
            s["league_code"],
            s["season"],
            s["matchday"],
            snapshot_date,
            s["team_id"],
            s["rank"],
            s["points"],
            s["win"],
            s["draw"],
            s["lose"],
            s["goals_for"],
            s["goals_against"],
            s["goal_diff"],
            s["matches_played"],
        ])

    buffer.seek(0)

    try:

        with conn.cursor() as cur:

            cur.copy_expert(
                f"""
                COPY {SCHEMA}.{TABLE} (
                    competition,
                    league_code,
                    season,
                    matchday,
                    snapshot_date,
                    team_id,
                    rank,
                    points,
                    win,
                    draw,
                    lose,
                    goals_for,
                    goals_against,
                    goal_diff,
                    matches_played
                )
                FROM STDIN
                WITH (
                    FORMAT CSV,
                    NULL ''
                )
                """,
                buffer,
            )

        conn.commit()

    except Exception:

        conn.rollback()
        raise

    print(
        f"   ✅ Bulk saved {len(snapshots):,} rows"
    )


# ============================================================
# SUMMARY
# ============================================================

def print_summary(conn):
    print("\n4️⃣ Historical standings summary...")

    with conn.cursor() as cur:

        cur.execute(
            f"""
            SELECT
                competition,
                season,
                COUNT(DISTINCT matchday) AS matchdays,
                COUNT(DISTINCT team_id) AS teams,
                COUNT(*) AS rows
            FROM {SCHEMA}.{TABLE}
            GROUP BY competition, season
            ORDER BY competition, season
            """
        )

        rows = cur.fetchall()

    print()

    for row in rows:

        competition, season, matchdays, teams, count = row

        print(
            f"   {competition:<25} "
            f"{season} | "
            f"{matchdays:>3} matchdays | "
            f"{teams:>2} teams | "
            f"{count:>5} rows"
        )

    print(
        f"\n   Total competition/seasons: {len(rows)}"
    )


# ============================================================
# PATCH g.py
# ============================================================

HISTORICAL_CODE = r'''
# ============================================================
# HISTORICAL STANDINGS SUPPORT
# Added automatically by build_historical_standings.py
# ============================================================

ACTIVE_HISTORICAL_STANDINGS_INDEX = {}


def _normalize_historical_league(league):
    """Normalize competition names/codes for historical lookup."""

    if league is None:
        return ""

    value = str(league).strip()

    aliases = {
        "Premier League": "PL",
        "Primera Division": "PD",
        "Bundesliga": "BL1",
        "Ligue 1": "FL1",
        "Serie A": "SA",
        "UEFA Champions League": "CL",
    }

    return aliases.get(
        value,
        value.upper().replace(" ", "_")
    )


def build_historical_standings_index(rows):
    """
    Build a fast lookup:

        (league_code, season, team_id, matchday)
            -> standings row
    """

    index = {}

    for row in rows:

        try:
            league_code = str(
                row["league_code"]
            ).strip()

            season = int(row["season"])
            team_id = int(row["team_id"])
            matchday = int(row["matchday"])

        except Exception:
            continue

        index[
            (
                league_code,
                season,
                team_id,
                matchday,
            )
        ] = row

    return index


def historical_rank_before_match(
    league,
    season,
    team_id,
    matchday=None,
):
    """
    Return the team's historical rank BEFORE the requested
    matchday.

    This deliberately uses the previous completed matchday
    to avoid giving the model information from the match it
    is trying to predict.

    Example:

        Fixture = Matchday 10

        Use standings after Matchday 9.
    """

    index = ACTIVE_HISTORICAL_STANDINGS_INDEX

    if not index:
        return None

    try:
        league_code = _normalize_historical_league(
            league
        )

        season = int(season)
        team_id = int(team_id)

    except Exception:
        return None

    if matchday is None:
        return None

    try:
        matchday = int(matchday)
    except Exception:
        return None

    # Previous completed matchday.
    previous_matchday = matchday - 1

    if previous_matchday < 1:
        return None

    key = (
        league_code,
        season,
        team_id,
        previous_matchday,
    )

    row = index.get(key)

    if row is None:
        return None

    try:
        return int(row["rank"])
    except Exception:
        return None
'''


def backup_file(path):
    if not os.path.exists(path):
        return None

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    backup = f"{path}.backup_{timestamp}"

    shutil.copy2(
        path,
        backup,
    )

    return backup


def patch_g():
    print("\n5️⃣ Patching g.py...")

    if not os.path.exists(G_PATH):
        print(
            f"   ⚠️ {G_PATH} not found."
        )
        print(
            "   Historical standings table was still built."
        )
        return

    with open(
        G_PATH,
        "r",
        encoding="utf-8",
    ) as f:
        source = f.read()

    # --------------------------------------------------------
    # Already patched?
    # --------------------------------------------------------

    if "ACTIVE_HISTORICAL_STANDINGS_INDEX" in source:
        print(
            "   ℹ️ Historical standings code already exists."
        )
        return

    # --------------------------------------------------------
    # Backup
    # --------------------------------------------------------

    backup = backup_file(G_PATH)

    if backup:
        print(
            f"   Backup created: {backup}"
        )

    # --------------------------------------------------------
    # Insert helper code near imports.
    # --------------------------------------------------------

    marker = None

    # Prefer inserting after imports before first major code.
    #
    # We simply append the helper functions to the module.
    # This is safe because functions can be defined anywhere
    # before they are called at runtime.
    # --------------------------------------------------------

    source = source.rstrip() + "\n\n" + HISTORICAL_CODE + "\n"

    # --------------------------------------------------------
    # Patch existing get_rank_from_snapshot function.
    #
    # Expected historical function from the current V2 model:
    #
    # get_rank_from_snapshot(
    #     index,
    #     league,
    #     season,
    #     team_id,
    #     before_date=None
    # )
    #
    # We do NOT replace the original function.
    #
    # Instead we insert historical lookup at the beginning.
    # --------------------------------------------------------

    pattern = re.compile(
        r"(def\s+get_rank_from_snapshot\s*\([^)]*\)\s*:\s*\n)"
    )

    match = pattern.search(source)

    if not match:

        print(
            "   ⚠️ Could not automatically locate "
            "get_rank_from_snapshot()."
        )

        print(
            "   Historical table was created successfully, "
            "but g.py was not modified."
        )

        with open(
            G_PATH,
            "w",
            encoding="utf-8",
        ) as f:
            f.write(source)

        return

    function_header_end = match.end()

    historical_override = r'''
    # --------------------------------------------------------
    # Historical standings override
    # --------------------------------------------------------

    try:
        historical_rank = historical_rank_before_match(
            league,
            season,
            team_id,
            locals().get("matchday"),
        )

        if historical_rank is not None:
            return historical_rank

    except Exception:
        pass

'''

    source = (
        source[:function_header_end]
        + historical_override
        + source[function_header_end:]
    )

    # --------------------------------------------------------
    # Save patched source
    # --------------------------------------------------------

    with open(
        G_PATH,
        "w",
        encoding="utf-8",
    ) as f:
        f.write(source)

    print(
        "   ✅ Historical helper code added to g.py"
    )

    print(
        "   ⚠️ IMPORTANT:"
    )

    print(
        "      g.py still needs to load the historical rows "
        "into ACTIVE_HISTORICAL_STANDINGS_INDEX."
    )

    print(
        "      The next section attempts to add that loader."
    )

    patch_loader()


# ============================================================
# PATCH HISTORICAL LOADER
# ============================================================

def patch_loader():
    """
    Add historical standings query to g.py.

    We look for the existing standings query and insert
    a second query immediately afterwards.

    Because g.py has evolved over time, several patterns
    are supported.
    """

    with open(
        G_PATH,
        "r",
        encoding="utf-8",
    ) as f:
        source = f.read()

    # --------------------------------------------------------
    # If loader already exists, stop.
    # --------------------------------------------------------

    if "historical_standings_rows" in source:
        print(
            "   ℹ️ Historical standings loader already exists."
        )
        return

    # --------------------------------------------------------
    # Find common standings query patterns.
    # --------------------------------------------------------

    injection = r'''
        # ====================================================
        # LOAD HISTORICAL STANDINGS
        # ====================================================

        historical_standings_rows = await query_db(
            """
            SELECT
                competition,
                league_code,
                season,
                matchday,
                snapshot_date,
                team_id,
                rank,
                points,
                win,
                draw,
                lose,
                goals_for,
                goals_against,
                goal_diff,
                matches_played
            FROM henry_schema.historical_standings
            """
        )

        global ACTIVE_HISTORICAL_STANDINGS_INDEX

        ACTIVE_HISTORICAL_STANDINGS_INDEX = (
            build_historical_standings_index(
                historical_standings_rows
            )
        )

        print(
            f"Historical standings rows: "
            f"{len(historical_standings_rows):,}"
        )

'''

    # --------------------------------------------------------
    # Case 1:
    # standings_rows = await query_db(...)
    # --------------------------------------------------------

    pattern1 = re.compile(
        r"(?P<indent>^[ \t]*)"
        r"standings_rows\s*=\s*await\s+query_db\s*\(",
        re.MULTILINE,
    )

    match = pattern1.search(source)

    if match:

        # Find closing parenthesis of query_db call.
        start = match.start()

        pos = match.end()
        depth = 1

        while pos < len(source) and depth > 0:

            if source[pos] == "(":
                depth += 1

            elif source[pos] == ")":
                depth -= 1

            pos += 1

        indent = match.group("indent")

        indented = "\n".join(
            indent + line if line.strip() else line
            for line in injection.strip("\n").splitlines()
        )

        source = (
            source[:pos]
            + "\n\n"
            + indented
            + source[pos:]
        )

        with open(
            G_PATH,
            "w",
            encoding="utf-8",
        ) as f:
            f.write(source)

        print(
            "   ✅ Historical standings loader inserted."
        )

        return

    # --------------------------------------------------------
    # Case 2:
    # build_standings_index(standings_rows)
    # --------------------------------------------------------

    pattern2 = re.compile(
        r"(?P<indent>^[ \t]*)"
        r"standings_index\s*=\s*build_standings_index\s*\(\s*"
        r"standings_rows\s*\)",
        re.MULTILINE,
    )

    match = pattern2.search(source)

    if match:

        indent = match.group("indent")

        indented = "\n".join(
            indent + line if line.strip() else line
            for line in injection.strip("\n").splitlines()
        )

        pos = match.end()

        source = (
            source[:pos]
            + "\n\n"
            + indented
            + source[pos:]
        )

        with open(
            G_PATH,
            "w",
            encoding="utf-8",
        ) as f:
            f.write(source)

        print(
            "   ✅ Historical standings loader inserted "
            "after standings index."
        )

        return

    # --------------------------------------------------------
    # Could not find insertion point.
    # --------------------------------------------------------

    print(
        "   ⚠️ Could not locate standings loader in g.py."
    )

    print(
        "   Historical table is complete."
    )

    print(
        "   g.py helper functions were added, but "
        "the database loader must be wired manually."
    )


# ============================================================
# SYNTAX CHECK
# ============================================================

def syntax_check():
    print("\n6️⃣ Checking g.py syntax...")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            G_PATH,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:

        print(
            "   ✅ g.py syntax OK"
        )

        return True

    print(
        "   ❌ g.py syntax error:"
    )

    print(
        result.stderr
    )

    return False


# ============================================================
# VERIFY
# ============================================================

def verify(conn):
    print("\n7️⃣ Verifying historical standings...")

    with conn.cursor() as cur:

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM {SCHEMA}.{TABLE}
            """
        )

        total = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT
                COUNT(DISTINCT competition),
                COUNT(DISTINCT season),
                COUNT(DISTINCT team_id),
                COUNT(DISTINCT matchday)
            FROM {SCHEMA}.{TABLE}
            """
        )

        competitions, seasons, teams, matchdays = (
            cur.fetchone()
        )

    print(
        f"   Rows:          {total:,}"
    )

    print(
        f"   Competitions:  {competitions}"
    )

    print(
        f"   Seasons:       {seasons}"
    )

    print(
        f"   Teams:         {teams}"
    )

    print(
        f"   Matchdays:     {matchdays}"
    )

    if total == 0:

        print(
            "\n   ❌ No historical standings were created."
        )

        return False

    print(
        "\n   ✅ Historical standings verified."
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("HISTORICAL STANDINGS BUILDER")
    print("=" * 70)

    conn = None

    try:

        # ----------------------------------------------------
        # Connect
        # ----------------------------------------------------

        print("\n🔌 Connecting to PostgreSQL...")

        conn = get_connection()

        print(
            "   ✅ PostgreSQL connection successful"
        )

        # ----------------------------------------------------
        # Create table
        # ----------------------------------------------------

        create_table(conn)

        # ----------------------------------------------------
        # Load matches
        # ----------------------------------------------------

        matches = load_matches(conn)

        if not matches:

            raise RuntimeError(
                "No FINISHED matches found for "
                f"seasons {START_SEASON}-{END_SEASON}."
            )

        # ----------------------------------------------------
        # Build standings
        # ----------------------------------------------------

        print(
            "\n3️⃣ Reconstructing standings "
            "matchday by matchday..."
        )

        snapshots = build_standings(matches)

        print(
            f"\n   Total snapshots generated: "
            f"{len(snapshots):,}"
        )

        # ----------------------------------------------------
        # Save
        # ----------------------------------------------------

        save_snapshots(
            conn,
            snapshots,
        )

        # ----------------------------------------------------
        # Summary
        # ----------------------------------------------------

        print_summary(conn)

        # ----------------------------------------------------
        # Verify
        # ----------------------------------------------------

        verify(conn)

        # ----------------------------------------------------
        # Patch g.py
        # ----------------------------------------------------

        patch_g()

        # ----------------------------------------------------
        # Syntax
        # ----------------------------------------------------

        syntax_ok = syntax_check()

        print("\n" + "=" * 70)

        if syntax_ok:
            print(
                "✅ HISTORICAL STANDINGS BUILD COMPLETE"
            )
        else:
            print(
                "⚠️ STANDINGS BUILT, BUT g.py NEEDS REVIEW"
            )

        print("=" * 70)

        print(
            "\nNOTE:"
        )

        print(
            "Your database contains seasons 2023–2026."
        )

        print(
            "There are no 2022 matches in the current database, "
            "so 2022 cannot be reconstructed until those matches "
            "are imported."
        )

    except Exception as exc:

        print("\n" + "=" * 70)
        print("❌ SCRIPT FAILED")
        print("=" * 70)

        print(
            f"\n{type(exc).__name__}: {exc}"
        )

        if conn:
            conn.rollback()

        sys.exit(1)

    finally:

        if conn:
            conn.close()


if __name__ == "__main__":
    main()
