import sqlite3
import pandas as pd
from datetime import datetime, UTC

DB_PATH = "football.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


# -------------------------------------------------
# Insert base rows for scheduled matches
# -------------------------------------------------
def insert_base_features(conn):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO features (match_id, home_team_id, away_team_id, generated_at)
        SELECT id, home_team_id, away_team_id, ?
        FROM matches
        WHERE status = 'SCHEDULED'
        AND id NOT IN (SELECT match_id FROM features)
    """, (datetime.now(UTC).isoformat(),))
    conn.commit()


# -------------------------------------------------
# Helper queries
# -------------------------------------------------
def last_n_matches(conn, team_id, n=5):
    return pd.read_sql("""
        SELECT *
        FROM matches
        WHERE status = 'FINISHED'
        AND (home_team_id = ? OR away_team_id = ?)
        ORDER BY utcDate DESC
        LIMIT ?
    """, conn, params=(team_id, team_id, n))


def average_goals(team_id, df, scored=True):
    values = []
    for _, m in df.iterrows():
        if m.home_team_id == team_id:
            values.append(m.home_score if scored else m.away_score)
        else:
            values.append(m.away_score if scored else m.home_score)
    return sum(values) / len(values) if values else 0.0


def team_form(team_id, df):
    points = []
    for _, m in df.iterrows():
        if m.home_score == m.away_score:
            points.append(1)
        elif (m.home_team_id == team_id and m.home_score > m.away_score) or \
             (m.away_team_id == team_id and m.away_score > m.home_score):
            points.append(3)
        else:
            points.append(0)
    return sum(points) / len(points) if points else 0.0


def h2h_win_percentage(conn, home_id, away_id):
    df = pd.read_sql("""
        SELECT home_score, away_score
        FROM h2h
        WHERE home_team_id = ? AND away_team_id = ?
    """, conn, params=(home_id, away_id))

    if df.empty:
        return 0.5  # neutral if no history

    wins = (df.home_score > df.away_score).sum()
    return wins / len(df)


def key_player_missing(conn, team_id):
    df = pd.read_sql("""
        SELECT 1
        FROM injuries i
        JOIN players p ON p.id = i.player_id
        WHERE p.key_player = 1
        AND i.team_id = ?
        AND i.end_date IS NULL
    """, conn, params=(team_id,))
    return 1 if not df.empty else 0


# -------------------------------------------------
# Main feature builder
# -------------------------------------------------
def build_features():
    conn = get_connection()
    insert_base_features(conn)

    features_df = pd.read_sql("SELECT * FROM features", conn)
    cursor = conn.cursor()

    for _, f in features_df.iterrows():
        home_id = f.home_team_id
        away_id = f.away_team_id

        home_matches = last_n_matches(conn, home_id)
        away_matches = last_n_matches(conn, away_id)

        home_gf = average_goals(home_id, home_matches, scored=True)
        home_ga = average_goals(home_id, home_matches, scored=False)
        away_gf = average_goals(away_id, away_matches, scored=True)
        away_ga = average_goals(away_id, away_matches, scored=False)

        home_form = team_form(home_id, home_matches)
        away_form = team_form(away_id, away_matches)

        h2h_pct = h2h_win_percentage(conn, home_id, away_id)

        key_missing = max(
            key_player_missing(conn, home_id),
            key_player_missing(conn, away_id)
        )

        predicted_home_goals = (home_gf + away_ga) / 2
        predicted_away_goals = (away_gf + home_ga) / 2

        cursor.execute("""
            UPDATE features
            SET
                avg_goals_for_last_5_home = ?,
                avg_goals_against_last_5_home = ?,
                avg_goals_for_last_5_away = ?,
                avg_goals_against_last_5_away = ?,
                home_form = ?,
                away_form = ?,
                h2h_win_pct = ?,
                key_player_missing = ?,
                predicted_home_goals = ?,
                predicted_away_goals = ?,
                generated_at = ?
            WHERE match_id = ?
        """, (
            home_gf, home_ga,
            away_gf, away_ga,
            home_form, away_form,
            h2h_pct,
            key_missing,
            predicted_home_goals,
            predicted_away_goals,
            datetime.now(UTC).isoformat(),
            f.match_id
        ))

    conn.commit()
    conn.close()
    print("✅ Features table built successfully.")


# -------------------------------------------------
# Entry point
# -------------------------------------------------
if __name__ == "__main__":
    build_features()
