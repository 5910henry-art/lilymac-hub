#!/usr/bin/env python3
"""
Backfill model_stats with per-competition accuracy
using models.prediction_json and matches.competition
"""

import sqlite3
import json
from config import DB_FILE

def backfill_model_stats():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Ensure model_stats table exists with competition column
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_stats (
            model_version TEXT NOT NULL,
            competition TEXT NOT NULL,
            total_predictions INTEGER DEFAULT 0,
            correct_predictions INTEGER DEFAULT 0,
            accuracy REAL DEFAULT 0.5,
            PRIMARY KEY (model_version, competition)
        )
    """)
    conn.commit()

    # Fetch all finished matches
    cursor.execute("""
        SELECT id, competition, home_score, away_score
        FROM matches
        WHERE status = 'FINISHED'
    """)
    finished_matches = cursor.fetchall()
    print(f"Found {len(finished_matches)} finished matches.")

    for match_id, competition, home_score, away_score in finished_matches:
        # Determine actual outcome
        if home_score > away_score:
            actual = "Home Win"
        elif home_score < away_score:
            actual = "Away Win"
        else:
            actual = "Draw"

        # Get all model predictions for this match
        cursor.execute("""
            SELECT model_version, prediction_json
            FROM models
            WHERE match_id = ?
        """, (match_id,))
        model_rows = cursor.fetchall()

        for model_version, prediction_json in model_rows:
            try:
                p = json.loads(prediction_json)
                probs = p.get("probabilities", {})
                predicted_probs = {
                    "Home Win": probs.get("home_win", 0.0),
                    "Draw": probs.get("draw", 0.0),
                    "Away Win": probs.get("away_win", 0.0)
                }
                predicted = max(predicted_probs, key=predicted_probs.get)
                is_correct = 1 if predicted == actual else 0

                # Insert or update model_stats per competition
                cursor.execute("""
                    INSERT INTO model_stats (
                        model_version, competition, total_predictions, correct_predictions, accuracy
                    ) VALUES (?, ?, 1, ?, ?)
                    ON CONFLICT(model_version, competition) DO UPDATE SET
                        total_predictions = total_predictions + 1,
                        correct_predictions = correct_predictions + ?,
                        accuracy = CAST(correct_predictions + ? AS REAL) / (total_predictions + 1)
                """, (
                    model_version,
                    competition,
                    is_correct,
                    is_correct,
                    is_correct,
                    is_correct
                ))

            except Exception as e:
                print(f"Error parsing prediction for model {model_version}, match {match_id}: {e}")
                continue

    conn.commit()
    conn.close()
    print("✅ Backfill complete. model_stats table is now populated with competition info.")

if __name__ == "__main__":
    backfill_model_stats()
