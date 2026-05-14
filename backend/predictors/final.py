#!/usr/bin/env python3
import asyncio
import importlib
import inspect
import json
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from ran import get_pool, qdb

UTC = timezone.utc

# ---------------- Config ----------------
RECENT_DAYS = 60
MIN_MATCHES = 5
_CACHE_TTL_MINUTES = 10
WILSON_Z = 1.96  # 95% confidence

# ---------------- Cache ----------------
_best_per_league_cache = {}
_cache_timestamp = None
_cache_lock = asyncio.Lock()


def _now():
    return datetime.now(UTC)


def safe_default_result(version_tag="recent_best"):
    return {
        "prediction": "Draw",
        "probabilities": {"home_win": 0.33, "draw": 0.34, "away_win": 0.33},
        "predicted_goals": {"home": 1, "away": 1},
        "confidence": 0.34,
        "ensemble_version": version_tag,
        "generated_at": _now().isoformat(),
        "extra": {},
    }


def normalize_probs(raw_probs):
    probs = {
        "home_win": 0.0,
        "draw": 0.0,
        "away_win": 0.0,
    }

    if isinstance(raw_probs, dict):
        for k, v in raw_probs.items():
            key = str(k).lower().replace(" ", "_")
            if key in probs:
                try:
                    probs[key] = float(v)
                except Exception:
                    probs[key] = 0.0

    total = sum(probs.values())
    if total <= 0:
        return {"home_win": 0.33, "draw": 0.34, "away_win": 0.33}

    return {k: v / total for k, v in probs.items()}


# ---------------- Wilson score ----------------
def wilson_lower_bound(correct: int, total: int, z: float = WILSON_Z) -> float:
    if total <= 0:
        return 0.0
    phat = correct / total
    z2 = z * z
    return (
        phat
        + z2 / (2 * total)
        - z * math.sqrt((phat * (1 - phat) + z2 / (4 * total)) / total)
    ) / (1 + z2 / total)


# ---------------- BEST MODEL COMPUTATION ----------------
async def compute_recent_best_per_league(
    min_matches: int = MIN_MATCHES,
    force_refresh: bool = False,
):
    global _best_per_league_cache, _cache_timestamp

    async with _cache_lock:
        now = _now()
        cache_key = min_matches

        if (
            not force_refresh
            and cache_key in _best_per_league_cache
            and _cache_timestamp
            and now - _cache_timestamp < timedelta(minutes=_CACHE_TTL_MINUTES)
        ):
            return _best_per_league_cache[cache_key]

        best_per_league = {}

        try:
            matches = await qdb(
                f"""
                SELECT id, competition, home_score, away_score
                FROM matches
                WHERE status = 'FINISHED'
                  AND utcdate >= NOW() - INTERVAL '{RECENT_DAYS} days'
                """
            )

            if not matches:
                _best_per_league_cache[cache_key] = {}
                _cache_timestamp = now
                return {}

            match_ids = [m["id"] for m in matches]

            if not match_ids:
                _best_per_league_cache[cache_key] = {}
                _cache_timestamp = now
                return {}

            placeholders = ", ".join(f"${i}" for i in range(1, len(match_ids) + 1))

            model_rows = await qdb(
                f"""
                SELECT match_id, model_version, prediction_json
                FROM models
                WHERE match_id IN ({placeholders})
                """,
                *match_ids,
            )

            preds_by_match = defaultdict(list)
            for r in model_rows:
                preds_by_match[r["match_id"]].append(r)

            perf = defaultdict(lambda: defaultdict(lambda: {"correct": 0, "total": 0}))

            for m in matches:
                if m["home_score"] is None or m["away_score"] is None:
                    continue

                actual = (
                    "Home Win"
                    if m["home_score"] > m["away_score"]
                    else "Away Win"
                    if m["home_score"] < m["away_score"]
                    else "Draw"
                )

                league = m["competition"] or "_global"

                for r in preds_by_match.get(m["id"], []):
                    version = r["model_version"]

                    try:
                        raw_pj = r["prediction_json"]
                        pj = raw_pj if isinstance(raw_pj, dict) else json.loads(raw_pj or "{}")
                        probs = normalize_probs(pj.get("probabilities", {}))

                        ph = probs["home_win"]
                        pd = probs["draw"]
                        pa = probs["away_win"]

                        if ph >= pd and ph >= pa:
                            predicted = "Home Win"
                        elif pa >= ph and pa >= pd:
                            predicted = "Away Win"
                        else:
                            predicted = "Draw"
                    except Exception:
                        predicted = "Draw"

                    perf[league][version]["total"] += 1
                    if predicted == actual:
                        perf[league][version]["correct"] += 1

            for league, models in perf.items():
                best = None
                best_score = -1.0

                for version, stats in models.items():
                    if stats["total"] < min_matches:
                        continue

                    score = wilson_lower_bound(stats["correct"], stats["total"])
                    if score > best_score:
                        best_score = score
                        best = (version, stats)

                if best:
                    version, stats = best
                    best_per_league[league] = {
                        "model_version": version,
                        "correct": stats["correct"],
                        "accuracy": stats["correct"] / stats["total"],
                        "total": stats["total"],
                        "wilson": wilson_lower_bound(stats["correct"], stats["total"]),
                    }

            global_agg = defaultdict(lambda: {"correct": 0, "total": 0})

            for models in perf.values():
                for version, stats in models.items():
                    global_agg[version]["correct"] += stats["correct"]
                    global_agg[version]["total"] += stats["total"]

            best_global = None
            best_score = -1.0

            for version, stats in global_agg.items():
                if stats["total"] < min_matches:
                    continue

                score = wilson_lower_bound(stats["correct"], stats["total"])
                if score > best_score:
                    best_score = score
                    best_global = (version, stats)

            if best_global:
                version, stats = best_global
                best_per_league["_global"] = {
                    "model_version": version,
                    "correct": stats["correct"],
                    "accuracy": stats["correct"] / stats["total"],
                    "total": stats["total"],
                    "wilson": wilson_lower_bound(stats["correct"], stats["total"]),
                }

            _best_per_league_cache[cache_key] = best_per_league
            _cache_timestamp = now
            return best_per_league

        except Exception as e:
            print("⚠️ compute_recent_best_per_league failed:", e)
            return {}


# ---------------- SAFE PREDICTOR CALLER ----------------
async def _call_predictor_fn(fn, match_id, home_id, away_id, call_kwargs):
    sig = inspect.signature(fn)
    params = sig.parameters
    is_coro = asyncio.iscoroutinefunction(fn)
    final_kwargs = {}

    if "match_id" in params:
        final_kwargs["match_id"] = match_id
    if "home_id" in params:
        final_kwargs["home_id"] = home_id
    if "away_id" in params:
        final_kwargs["away_id"] = away_id

    for k, v in call_kwargs.items():
        if k in params:
            final_kwargs[k] = v

    if "conn" in params:
        if not is_coro:
            raise RuntimeError("Sync predictors must not accept async DB connections")
        pool = await get_pool()
        async with pool.acquire() as conn:
            final_kwargs["conn"] = conn
            return await fn(**final_kwargs)

    if is_coro:
        return await fn(**final_kwargs)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(**final_kwargs))


# ---------------- PUBLIC ENTRY ----------------
async def predict_home_away(
    match_id,
    home_id,
    away_id,
    league=None,
    season=None,
    match_date=None,
    force_refresh=False,
):
    try:
        bests = await compute_recent_best_per_league(force_refresh=force_refresh)
        if not bests:
            return safe_default_result("recent_best")

        model_info = bests.get(league) or bests.get("_global")
        if not model_info:
            return safe_default_result("recent_best")

        version = model_info["model_version"]

        try:
            predictor_module = importlib.import_module(f"predictors.{version}")
        except Exception as e:
            print(f"⚠️ Failed to load predictor {version}: {e}")
            return safe_default_result(f"recent_best:{version}:missing")

        fn = getattr(predictor_module, "predict_home_away", None)
        if not fn:
            return safe_default_result(f"recent_best:{version}:no_fn")

        sig = inspect.signature(fn)
        call_kwargs = {}

        if "league" in sig.parameters and league is not None:
            call_kwargs["league"] = league
        if "season" in sig.parameters and season is not None:
            call_kwargs["season"] = season
        if "match_date" in sig.parameters and match_date is not None:
            call_kwargs["match_date"] = match_date

        raw = await _call_predictor_fn(fn, match_id, home_id, away_id, call_kwargs)

        if not isinstance(raw, dict):
            return safe_default_result(f"recent_best:{version}")

        raw["probabilities"] = normalize_probs(raw.get("probabilities", {}))

        raw.setdefault("extra", {})
        raw["extra"]["best_model_accuracy"] = model_info["accuracy"]
        raw["extra"]["best_model_wilson"] = model_info["wilson"]
        raw["extra"]["best_model_total"] = model_info["total"]

        raw.setdefault("ensemble_version", f"recent_best:{version}")
        raw.setdefault("generated_at", _now().isoformat())

        return raw

    except Exception as e:
        print(f"❌ recent_best predictor failed: {e}")
        return safe_default_result("recent_best:error")
