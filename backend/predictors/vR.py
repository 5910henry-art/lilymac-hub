#!/usr/bin/env python3
"""
vR3.py — adaptive ensemble (dynamic agreement boost + trimmed + score-proportional weights + safety)
Compatible with final.py predictor runner: `conn` is required.
Improvements over vR2:
 - dynamic AGREEMENT_BOOST based on majority fraction
 - weight clamping to avoid explosion
 - confidence scaling / clamping
 - volatility-based weighting (prefer stable models)
 - diversity bonus
 - odds sanity check to damp overconfident outputs
 - TOP_PREDICTORS trimmed to best stable models
"""
import asyncio
import importlib.util
import os
import sqlite3
import math
from collections import Counter
from datetime import datetime, timezone

# ==========================================================
# CONFIG
# ==========================================================
BASE_DIR = os.path.dirname(__file__)
PREDICTORS_FOLDER = BASE_DIR
DB_PATH = os.path.join(BASE_DIR, "football.db")
UTC = timezone.utc

# ----------------- Ensemble Configuration -----------------
TOP_PREDICTORS = ["v4a", "v0b", "v0a", "v0", "v4", "v2f"]
ENSEMBLE_MODE = "score"

ENSEMBLE_WEIGHTS_SCORE = {
    "v4a": 0.22,
    "v0b": 0.18,
    "v0a": 0.16,
    "v0":  0.14,
    "v4":  0.15,
    "v2f": 0.15,
}

MODEL_WEIGHTS = {"elo": 1.4, "xg": 1.3, "form": 1.2, "h2h": 1.1}
DEFAULT_MODEL_WEIGHT = 1.0

CONFIDENCE_FLOOR = 0.15
CONFIDENCE_MAX = 0.90

MIN_WEIGHT = 0.01
MAX_WEIGHT = 3.0

# Dynamic agreement boost constants
MIN_AGREEMENT_BOOST = 1.0
MAX_AGREEMENT_BOOST = 1.25

DIVERSITY_BONUS = 1.05
VOLATILITY_MIN_FACTOR = 0.30
ODDS_SANITY_THRESHOLD = 0.15
ODDS_SANITY_PENALTY = 0.85

LEAGUE_MODEL_WEIGHTS = {
    "EPL": {"elo": 1.3, "xg": 1.4},
    "UCL": {"xg": 1.5},
    "Bundesliga": {"form": 1.3},
}

# ==========================================================
# HELPERS
# ==========================================================
def now_iso():
    return datetime.now(UTC).isoformat()

def normalize_probabilities(p):
    h = p.get("home_win", 0.33)
    d = p.get("draw", 0.34)
    a = p.get("away_win", 0.33)
    total = h + d + a
    if total <= 0:
        return {"home_win":0.33, "draw":0.34, "away_win":0.33}
    return {"home_win": h/total, "draw": d/total, "away_win": a/total}

def normalize_label(label):
    label = label.lower() if isinstance(label, str) else ""
    if "home" in label:
        return "Home Win"
    if "away" in label:
        return "Away Win"
    return "Draw"

def get_db():
    return sqlite3.connect(DB_PATH)

def get_model_stats(model_version, competition):
    if not competition:
        return (0.5, 0.5)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT accuracy, volatility FROM model_stats WHERE model_version=? AND competition=?",
            (model_version, competition)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            acc = row[0] if row[0] is not None else 0.5
            vol = row[1] if len(row) > 1 and row[1] is not None else 0.5
            acc = max(0.3, min(1.0, float(acc)))
            vol = max(0.0, min(1.0, float(vol)))
            return (acc, vol)
    except Exception as e:
        print("⚠️ model_stats read failed:", e)
    return (0.5, 0.5)

def _model_key_from_name(model_name):
    if not model_name:
        return None
    mn = model_name.lower()
    for key in TOP_PREDICTORS:
        if key in mn:
            return key
    return None

def _ensemble_weight_for_model(model_name):
    if ENSEMBLE_MODE == "equal":
        return 1.0 / max(len(TOP_PREDICTORS), 1)
    key = _model_key_from_name(model_name)
    if key and key in ENSEMBLE_WEIGHTS_SCORE:
        return ENSEMBLE_WEIGHTS_SCORE[key]
    return 1.0 / max(len(TOP_PREDICTORS), 1)

def get_model_weight(result):
    name = str(result.get("model_name", "")).lower()
    for key, weight in MODEL_WEIGHTS.items():
        if key in name:
            return weight
    return DEFAULT_MODEL_WEIGHT

def get_league_weight(model_name, competition):
    if not competition:
        return 1.0
    if competition not in LEAGUE_MODEL_WEIGHTS:
        return 1.0
    model_name = model_name.lower()
    for key, weight in LEAGUE_MODEL_WEIGHTS[competition].items():
        if key in model_name:
            return weight
    return 1.0

def entropy_penalty(probs):
    entropy = 0.0
    for p in probs.values():
        if p>0: entropy -= p*math.log(p)
    max_entropy = math.log(3)
    return max(0.7, 1.0 - entropy/max_entropy)

def implied_prob_from_odds(odds, outcome_key):
    if not odds or not isinstance(odds, dict):
        return None
    mapping = {
        "home_win": ["home", "home_win", "h"],
        "draw": ["draw", "d"],
        "away_win": ["away", "away_win", "a"]
    }
    for k in mapping.get(outcome_key, []):
        if k in odds and odds[k]:
            try:
                o = float(odds[k])
                if o > 1e-6:
                    return 1.0 / o
            except Exception:
                pass
    return None

# ==========================================================
# ENSEMBLE
# ==========================================================
def weighted_combine(results):
    if not results:
        return {
            "prediction": "Draw",
            "probabilities": {"home_win":0.33, "draw":0.34, "away_win":0.33},
            "predicted_goals": {"home":1,"away":1},
            "confidence":0.34,
            "ensemble_version":"vR3",
            "generated_at": now_iso(),
        }

    labels = []
    model_top_probs = []
    for r in results:
        probs = normalize_probabilities(r.get("probabilities", {}))
        top_key = max(probs, key=probs.get)
        label = {"home_win":"Home Win", "draw":"Draw", "away_win":"Away Win"}.get(top_key, "Draw")
        labels.append(label)
        model_top_probs.append((r, top_key, probs[top_key]))

    label_counts = Counter(labels)
    majority_label, majority_count = label_counts.most_common(1)[0]
    majority_fraction = majority_count / max(len(labels), 1)
    dynamic_agreement_boost = MIN_AGREEMENT_BOOST + majority_fraction * (MAX_AGREEMENT_BOOST - MIN_AGREEMENT_BOOST)

    hp = dp = ap = 0.0
    gh = ga = 0.0
    weight_sum = 0.0
    conf_accum = 0.0
    used_models = 0

    for r, top_key, top_prob in model_top_probs:
        probs = normalize_probabilities(r.get("probabilities", {}))
        model_name = r.get("model_name", "unknown")
        competition = r.get("competition") or r.get("league")
        base_weight = get_model_weight(r)

        confidence = float(r.get("confidence", 0.5))
        confidence = max(CONFIDENCE_FLOOR, min(confidence, CONFIDENCE_MAX))

        accuracy, volatility = get_model_stats(model_name, competition)
        volatility_factor = max(VOLATILITY_MIN_FACTOR, 1.0 - volatility)

        entropy_factor = entropy_penalty(probs)
        league_factor = get_league_weight(model_name, competition)
        ensemble_w = _ensemble_weight_for_model(model_name)

        mn = model_name.lower()
        diversity = 1.0
        for key in MODEL_WEIGHTS.keys():
            if key in mn:
                diversity = DIVERSITY_BONUS
                break

        odds = r.get("odds") or r.get("bookmaker_odds")
        if odds and isinstance(odds, dict):
            implied = implied_prob_from_odds(odds, top_key)
            if implied is not None and abs(top_prob - implied) > ODDS_SANITY_THRESHOLD:
                confidence *= ODDS_SANITY_PENALTY

        weight = ensemble_w * base_weight * confidence * accuracy * entropy_factor * league_factor * volatility_factor * diversity

        model_label = normalize_label(r.get("prediction", "") if isinstance(r.get("prediction"), str) else r.get("prediction",""))
        if model_label == "":
            model_label = {"home_win":"Home Win", "draw":"Draw", "away_win":"Away Win"}.get(top_key, "Draw")
        if model_label == majority_label:
            weight *= dynamic_agreement_boost

        weight = max(MIN_WEIGHT, min(weight, MAX_WEIGHT))

        hp += probs["home_win"] * weight
        dp += probs["draw"] * weight
        ap += probs["away_win"] * weight

        g = r.get("predicted_goals", {})
        gh += g.get("home", 1) * weight
        ga += g.get("away", 1) * weight

        conf_accum += confidence * accuracy
        weight_sum += weight
        used_models += 1

    if weight_sum <= 0:
        weight_sum = 1.0

    hp /= weight_sum
    dp /= weight_sum
    ap /= weight_sum
    gh /= weight_sum
    ga /= weight_sum

    if hp > max(dp, ap):
        label = "Home Win"
    elif ap > max(hp, dp):
        label = "Away Win"
    else:
        label = "Draw"

    avg_conf = round(conf_accum / max(used_models, 1), 3)

    return {
        "prediction": normalize_label(label),
        "probabilities": {"home_win": round(hp, 4), "draw": round(dp, 4), "away_win": round(ap, 4)},
        "predicted_goals": {"home": round(gh), "away": round(ga)},
        "confidence": avg_conf,
        "ensemble_version": "vR3",
        "generated_at": now_iso(),
    }

# ==========================================================
# PREDICTOR LOADING
# ==========================================================
async def load_predictors():
    predictors = []
    for fname in os.listdir(PREDICTORS_FOLDER):
        if not fname.endswith(".py"):
            continue
        mod_name = fname[:-3]
        if mod_name not in TOP_PREDICTORS:
            continue
        path = os.path.join(PREDICTORS_FOLDER, fname)
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            if hasattr(mod, "predict_home_away"):
                predictors.append(mod.predict_home_away)
        except Exception as e:
            print(f"❌ Failed to load {mod_name}: {e}")
    return predictors

# ==========================================================
# MAIN ENTRY POINT
# ==========================================================
async def predict_home_away(match_id, home_id, away_id, conn, league=None, **kwargs):
    predictors = await load_predictors()
    results = []

    for pred_fn in predictors:
        try:
            if asyncio.iscoroutinefunction(pred_fn):
                res = await pred_fn(match_id=match_id, home_id=home_id, away_id=away_id, conn=conn, **kwargs)
            else:
                res = pred_fn(match_id=match_id, home_id=home_id, away_id=away_id, conn=conn, **kwargs)
            if res:
                results.append(res)
        except Exception as e:
            print(f"❌ Predictor failed: {e}")

    return weighted_combine(results)
