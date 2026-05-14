# model.py
# -------------------------------------------------------
# Handles training, saving, loading, and metadata
# for Lilymac Prediction Hub models.
# Now supports auto retraining every 24 hours.
# -------------------------------------------------------

import os
import json
import joblib
import sqlite3
from datetime import datetime, timezone, timedelta
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from apscheduler.schedulers.background import BackgroundScheduler
import threading
import time

DB_FILE = "football.db"
MODEL_DIR = "models"
os.makedirs(MODEL_DIR, exist_ok=True)

# -------------------------------------------------------
# Helper: East Africa Time (EAT)
# -------------------------------------------------------
def now_eat():
    return datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")

# -------------------------------------------------------
# DB connection
# -------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# -------------------------------------------------------
# Save metadata
# -------------------------------------------------------
def save_model_metadata(model_name, version, accuracy, notes=""):
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT,
            version TEXT,
            accuracy REAL,
            notes TEXT,
            trained_on TEXT,
            file_path TEXT
        )
    """)
    file_path = f"{MODEL_DIR}/{model_name}_v{version}.pkl"
    conn.execute("""
        INSERT INTO model_info (model_name, version, accuracy, notes, trained_on, file_path)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (model_name, version, accuracy, notes, now_eat(), file_path))
    conn.commit()
    conn.close()

# -------------------------------------------------------
# Save model
# -------------------------------------------------------
def save_model(model, model_name="ensemble_predictor", version="1.0"):
    file_path = f"{MODEL_DIR}/{model_name}_v{version}.pkl"
    joblib.dump(model, file_path)
    print(f"[MODEL] Saved {model_name} v{version} at {file_path}")
    return file_path

# -------------------------------------------------------
# Load latest model
# -------------------------------------------------------
def load_latest_model(model_name="ensemble_predictor"):
    conn = get_db()
    cursor = conn.execute("""
        SELECT file_path FROM model_info
        WHERE model_name = ?
        ORDER BY trained_on DESC
        LIMIT 1
    """, (model_name,))
    row = cursor.fetchone()
    conn.close()

    if row:
        model_path = row["file_path"]
        if os.path.exists(model_path):
            print(f"[MODEL] Loaded latest {model_name} from {model_path}")
            return joblib.load(model_path)
        else:
            raise FileNotFoundError(f"Model file not found: {model_path}")
    else:
        raise ValueError(f"No model found for {model_name}")

# -------------------------------------------------------
# Training logic
# -------------------------------------------------------
def fetch_training_data():
    conn = get_db()
    query = """
        SELECT avg_goals_for_last_5, avg_goals_against_last_5, home_form, away_form, h2h_win_pct,
               key_player_missing, predicted_home_goals, predicted_away_goals,
               CASE
                   WHEN home_form > away_form THEN 1
                   WHEN home_form = away_form THEN 0
                   ELSE -1
               END AS label
        FROM features
        WHERE avg_goals_for_last_5 IS NOT NULL
          AND home_form IS NOT NULL
          AND away_form IS NOT NULL
    """
    data = conn.execute(query).fetchall()
    conn.close()

    if not data:
        print("[DATA] No sufficient feature data available yet.")
        return None, None

    X = [[
        d["avg_goals_for_last_5"], d["avg_goals_against_last_5"],
        d["home_form"], d["away_form"], d["h2h_win_pct"],
        d["key_player_missing"], d["predicted_home_goals"], d["predicted_away_goals"]
    ] for d in data]
    y = [d["label"] for d in data]
    return X, y

def train_new_model(model_name="ensemble_predictor", version=None):
    X, y = fetch_training_data()
    if not X or not y:
        print("[TRAIN] Skipping training — not enough data.")
        return None

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    rf = RandomForestClassifier(n_estimators=150, random_state=42)
    logreg = LogisticRegression(max_iter=500)
    xgb = XGBClassifier(n_estimators=120, learning_rate=0.05, random_state=42)

    rf.fit(X_train, y_train)
    logreg.fit(X_train, y_train)
    xgb.fit(X_train, y_train)

    # Evaluate
    preds = rf.predict(X_test)
    acc = accuracy_score(y_test, preds)
    acc = round(acc, 3)

    ensemble_model = {
        "random_forest": rf,
        "logistic_regression": logreg,
        "xgboost": xgb
    }

    if not version:
        version = datetime.now().strftime("%Y%m%d%H%M")

    save_model(ensemble_model, model_name, version)
    save_model_metadata(model_name, version, acc, "Auto retrained model")
    print(f"[MODEL] {model_name} v{version} retrained successfully ({acc*100:.1f}% acc)")
    return ensemble_model

# -------------------------------------------------------
# Scheduler (retrain every 24 hours)
# -------------------------------------------------------
def start_auto_retrainer():
    scheduler = BackgroundScheduler(timezone="Africa/Nairobi")
    scheduler.add_job(train_new_model, "interval", hours=24, id="daily_model_retrain")
    scheduler.start()
    print("[SCHEDULER] Auto retrainer active (every 24h)")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("[SCHEDULER] Shutdown complete")

# -------------------------------------------------------
# Model info utilities
# -------------------------------------------------------
def list_models():
    conn = get_db()
    cursor = conn.execute("""
        SELECT model_name, version, accuracy, trained_on, file_path
        FROM model_info
        ORDER BY trained_on DESC
    """)
    models = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return models

def get_model_info():
    models = list_models()
    if not models:
        return {"message": "No models found"}
    return {
        "latest_model": models[0],
        "total_models": len(models),
        "generated_at": now_eat()
    }

# -------------------------------------------------------
# Run standalone (start background training)
# -------------------------------------------------------
if __name__ == "__main__":
    print("[INIT] Lilymac Auto Model Manager started.")
    threading.Thread(target=start_auto_retrainer, daemon=True).start()
    # Initial train if no model exists
    if not list_models():
        train_new_model()
    while True:
        time.sleep(3600)
