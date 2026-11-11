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


# ============================================================
# CONFIG
# ============================================================

# Evaluate predictions from this recent period.
RECENT_DAYS = 60

# Minimum number of predictions required before a model can
# compete for "best model".
MIN_MATCHES = 20

# Cache duration.
_CACHE_TTL_MINUTES = 10

# Wilson confidence level.
WILSON_Z = 1.96

# Recency half-life.
#
# A prediction at HALF_LIFE_DAYS ago receives roughly 50%
# of the weight of a prediction made today.
RECENCY_HALF_LIFE_DAYS = 30.0

# Minimum probability allowed after normalization.
MIN_PROBABILITY = 0.000001

# Weighting used in final model-selection score.
#
# Wilson is deliberately the strongest component because
# it protects against tiny samples.
WILSON_WEIGHT = 0.55

# Recency-adjusted accuracy contribution.
RECENCY_WEIGHT = 0.30

# Raw accuracy contribution.
ACCURACY_WEIGHT = 0.15


# ============================================================
# CACHE
# ============================================================

_best_per_league_cache = {}

_cache_timestamp = None

_cache_lock = asyncio.Lock()


# ============================================================
# TIME
# ============================================================

def _now():
    return datetime.now(UTC)


# ============================================================
# SAFE DEFAULT
# ============================================================

def safe_default_result(version_tag="recent_best"):
    return {
        "prediction": "Draw",
        "probabilities": {
            "home_win": 0.33,
            "draw": 0.34,
            "away_win": 0.33,
        },
        "predicted_goals": {
            "home": 1,
            "away": 1,
        },
        "confidence": 0.34,
        "ensemble_version": version_tag,
        "generated_at": _now().isoformat(),
        "extra": {},
    }


# ============================================================
# PROBABILITY NORMALIZATION
# ============================================================

def normalize_probs(raw_probs):
    probs = {
        "home_win": 0.0,
        "draw": 0.0,
        "away_win": 0.0,
    }

    if isinstance(raw_probs, dict):
        for key, value in raw_probs.items():
            normalized_key = str(key).lower().replace(" ", "_")

            if normalized_key not in probs:
                continue

            try:
                value = float(value)

                if not math.isfinite(value):
                    value = 0.0

                # Probabilities must never be negative.
                value = max(0.0, value)

                probs[normalized_key] = value

            except Exception:
                probs[normalized_key] = 0.0

    total = sum(probs.values())

    if not math.isfinite(total) or total <= 0:
        return {
            "home_win": 0.33,
            "draw": 0.34,
            "away_win": 0.33,
        }

    normalized = {
        key: max(MIN_PROBABILITY, value / total)
        for key, value in probs.items()
    }

    # Re-normalize after minimum probability protection.
    total = sum(normalized.values())

    return {
        key: value / total
        for key, value in normalized.items()
    }


# ============================================================
# PREDICTION LABEL
# ============================================================

def prediction_from_probs(probs):
    ph = probs["home_win"]
    pd = probs["draw"]
    pa = probs["away_win"]

    if ph >= pd and ph >= pa:
        return "Home Win"

    if pa >= ph and pa >= pd:
        return "Away Win"

    return "Draw"


# ============================================================
# WILSON SCORE
# ============================================================

def wilson_lower_bound(
    correct: int,
    total: int,
    z: float = WILSON_Z,
) -> float:

    if total <= 0:
        return 0.0

    phat = correct / total

    z2 = z * z

    denominator = 1 + z2 / total

    numerator = (
        phat
        + z2 / (2 * total)
        - z
        * math.sqrt(
            (
                phat * (1 - phat)
                + z2 / (4 * total)
            )
            / total
        )
    )

    return numerator / denominator


# ============================================================
# RECENCY WEIGHT
# ============================================================

def recency_weight(match_date):
    """
    Newer predictions receive more weight.

    Uses exponential decay with a configurable half-life.
    """

    if not match_date:
        return 1.0

    try:
        if isinstance(match_date, str):
            match_date = match_date.replace("Z", "+00:00")
            match_date = datetime.fromisoformat(match_date)

        if match_date.tzinfo is None:
            match_date = match_date.replace(tzinfo=UTC)

        age_days = max(
            0.0,
            (_now() - match_date).total_seconds() / 86400.0,
        )

        return math.pow(
            0.5,
            age_days / RECENCY_HALF_LIFE_DAYS,
        )

    except Exception:
        return 1.0


# ============================================================
# MODEL SCORE
# ============================================================

def calculate_model_score(stats):
    """
    Combines:

        55% Wilson lower bound
        30% recency-weighted accuracy
        15% raw accuracy

    This prevents a tiny sample from easily beating a model
    with substantial evidence.
    """

    total = stats["total"]

    if total <= 0:
        return 0.0

    accuracy = stats["correct"] / total

    weighted_total = stats.get("weighted_total", 0.0)
    weighted_correct = stats.get("weighted_correct", 0.0)

    if weighted_total > 0:
        recency_accuracy = (
            weighted_correct / weighted_total
        )
    else:
        recency_accuracy = accuracy

    wilson = wilson_lower_bound(
        stats["correct"],
        total,
    )

    score = (
        WILSON_WEIGHT * wilson
        + RECENCY_WEIGHT * recency_accuracy
        + ACCURACY_WEIGHT * accuracy
    )

    return max(0.0, min(1.0, score))


# ============================================================
# CACHE VALIDATION
# ============================================================

def _cache_valid(cache_key):
    if cache_key not in _best_per_league_cache:
        return False

    if not _cache_timestamp:
        return False

    return (
        _now() - _cache_timestamp
        < timedelta(minutes=_CACHE_TTL_MINUTES)
    )


# ============================================================
# BEST MODEL COMPUTATION
# ============================================================

async def compute_recent_best_per_league(
    min_matches: int = MIN_MATCHES,
    force_refresh: bool = False,
):

    global _best_per_league_cache
    global _cache_timestamp

    async with _cache_lock:

        cache_key = int(min_matches)

        if (
            not force_refresh
            and _cache_valid(cache_key)
        ):
            return _best_per_league_cache[cache_key]

        best_per_league = {}

        try:

            # ------------------------------------------------
            # LOAD RECENT FINISHED MATCHES
            # ------------------------------------------------

            matches = await qdb(
                f"""
                SELECT
                    id,
                    competition,
                    home_score,
                    away_score,
                    utcdate
                FROM matches
                WHERE status = 'FINISHED'
                  AND utcdate >= NOW()
                    - INTERVAL '{RECENT_DAYS} days'
                """
            )

            if not matches:
                _best_per_league_cache[cache_key] = {}
                _cache_timestamp = _now()
                return {}

            match_ids = [
                m["id"]
                for m in matches
                if m.get("id") is not None
            ]

            if not match_ids:
                _best_per_league_cache[cache_key] = {}
                _cache_timestamp = _now()
                return {}

            # ------------------------------------------------
            # LOAD MODEL PREDICTIONS
            # ------------------------------------------------

            placeholders = ", ".join(
                f"${i}"
                for i in range(
                    1,
                    len(match_ids) + 1,
                )
            )

            model_rows = await qdb(
                f"""
                SELECT
                    match_id,
                    model_version,
                    prediction_json
                FROM models
                WHERE match_id IN ({placeholders})
                  AND LOWER(model_version) NOT LIKE 'final%'
                  AND LOWER(model_version) NOT LIKE 'recent_best%'
                """,
                *match_ids,
            )

            preds_by_match = defaultdict(list)

            for row in model_rows:
                preds_by_match[
                    row["match_id"]
                ].append(row)

            # ------------------------------------------------
            # PERFORMANCE STORAGE
            # ------------------------------------------------

            perf = defaultdict(
                lambda: defaultdict(
                    lambda: {
                        "correct": 0,
                        "total": 0,
                        "weighted_correct": 0.0,
                        "weighted_total": 0.0,
                    }
                )
            )

            # ------------------------------------------------
            # EVALUATE MODELS
            # ------------------------------------------------

            for match in matches:

                home_score = match.get("home_score")
                away_score = match.get("away_score")

                if (
                    home_score is None
                    or away_score is None
                ):
                    continue

                # --------------------------------------------
                # ACTUAL RESULT
                # --------------------------------------------

                if home_score > away_score:
                    actual = "Home Win"

                elif home_score < away_score:
                    actual = "Away Win"

                else:
                    actual = "Draw"

                league = (
                    match.get("competition")
                    or "_global"
                )

                match_date = match.get("utcdate")

                weight = recency_weight(match_date)

                # --------------------------------------------
                # MODEL RESULTS
                # --------------------------------------------

                for row in preds_by_match.get(
                    match["id"],
                    [],
                ):

                    version = row.get("model_version")

                    if not version:
                        continue

                    try:

                        raw_prediction = row.get(
                            "prediction_json"
                        )

                        if isinstance(
                            raw_prediction,
                            dict,
                        ):
                            prediction_json = (
                                raw_prediction
                            )
                        else:
                            prediction_json = json.loads(
                                raw_prediction or "{}"
                            )

                        probabilities = normalize_probs(
                            prediction_json.get(
                                "probabilities",
                                {},
                            )
                        )

                        predicted = prediction_from_probs(
                            probabilities
                        )

                    except Exception:
                        predicted = "Draw"

                    stats = perf[league][version]

                    stats["total"] += 1

                    stats["weighted_total"] += weight

                    if predicted == actual:

                        stats["correct"] += 1

                        stats[
                            "weighted_correct"
                        ] += weight

            # ------------------------------------------------
            # SELECT BEST MODEL PER LEAGUE
            # ------------------------------------------------

            for league, models in perf.items():

                best = None
                best_score = -1.0

                for version, stats in models.items():

                    if stats["total"] < min_matches:
                        continue

                    score = calculate_model_score(
                        stats
                    )

                    if score > best_score:

                        best_score = score

                        best = (
                            version,
                            stats,
                            score,
                        )

                if best:

                    version, stats, score = best

                    accuracy = (
                        stats["correct"]
                        / stats["total"]
                    )

                    wilson = wilson_lower_bound(
                        stats["correct"],
                        stats["total"],
                    )

                    weighted_accuracy = (
                        stats["weighted_correct"]
                        / stats["weighted_total"]
                        if stats["weighted_total"] > 0
                        else accuracy
                    )

                    best_per_league[league] = {
                        "model_version": version,
                        "correct": stats["correct"],
                        "accuracy": accuracy,
                        "weighted_accuracy": (
                            weighted_accuracy
                        ),
                        "total": stats["total"],
                        "wilson": wilson,
                        "score": score,
                    }

            # ------------------------------------------------
            # GLOBAL MODEL PERFORMANCE
            # ------------------------------------------------

            global_agg = defaultdict(
                lambda: {
                    "correct": 0,
                    "total": 0,
                    "weighted_correct": 0.0,
                    "weighted_total": 0.0,
                }
            )

            for models in perf.values():

                for version, stats in models.items():

                    global_stats = global_agg[
                        version
                    ]

                    global_stats[
                        "correct"
                    ] += stats["correct"]

                    global_stats[
                        "total"
                    ] += stats["total"]

                    global_stats[
                        "weighted_correct"
                    ] += stats[
                        "weighted_correct"
                    ]

                    global_stats[
                        "weighted_total"
                    ] += stats[
                        "weighted_total"
                    ]

            # ------------------------------------------------
            # SELECT GLOBAL BEST
            # ------------------------------------------------

            best_global = None
            best_global_score = -1.0

            for version, stats in global_agg.items():

                if stats["total"] < min_matches:
                    continue

                score = calculate_model_score(
                    stats
                )

                if score > best_global_score:

                    best_global_score = score

                    best_global = (
                        version,
                        stats,
                        score,
                    )

            if best_global:

                version, stats, score = best_global

                accuracy = (
                    stats["correct"]
                    / stats["total"]
                )

                wilson = wilson_lower_bound(
                    stats["correct"],
                    stats["total"],
                )

                weighted_accuracy = (
                    stats["weighted_correct"]
                    / stats["weighted_total"]
                    if stats["weighted_total"] > 0
                    else accuracy
                )

                best_per_league["_global"] = {
                    "model_version": version,
                    "correct": stats["correct"],
                    "accuracy": accuracy,
                    "weighted_accuracy": (
                        weighted_accuracy
                    ),
                    "total": stats["total"],
                    "wilson": wilson,
                    "score": score,
                }

            # ------------------------------------------------
            # CACHE
            # ------------------------------------------------

            _best_per_league_cache[
                cache_key
            ] = best_per_league

            _cache_timestamp = _now()

            return best_per_league

        except Exception as e:

            print(
                "⚠️ compute_recent_best_per_league failed:",
                e,
            )

            return {}


# ============================================================
# SAFE PREDICTOR CALLER
# ============================================================

async def _call_predictor_fn(
    fn,
    match_id,
    home_id,
    away_id,
    call_kwargs,
):

    sig = inspect.signature(fn)

    params = sig.parameters

    is_coro = asyncio.iscoroutinefunction(fn)

    final_kwargs = {}

    # --------------------------------------------------------
    # STANDARD ARGUMENTS
    # --------------------------------------------------------

    if "match_id" in params:
        final_kwargs["match_id"] = match_id

    if "home_id" in params:
        final_kwargs["home_id"] = home_id

    if "away_id" in params:
        final_kwargs["away_id"] = away_id

    # --------------------------------------------------------
    # OPTIONAL ARGUMENTS
    # --------------------------------------------------------

    for key, value in call_kwargs.items():

        if key in params:
            final_kwargs[key] = value

    # --------------------------------------------------------
    # ASYNC DB CONNECTION
    # --------------------------------------------------------

    if "conn" in params:

        if not is_coro:
            raise RuntimeError(
                "Sync predictors must not accept "
                "async DB connections"
            )

        pool = await get_pool()

        async with pool.acquire() as conn:

            final_kwargs["conn"] = conn

            return await fn(
                **final_kwargs
            )

    # --------------------------------------------------------
    # ASYNC PREDICTOR
    # --------------------------------------------------------

    if is_coro:

        return await fn(
            **final_kwargs
        )

    # --------------------------------------------------------
    # SYNC PREDICTOR
    # --------------------------------------------------------

    loop = asyncio.get_running_loop()

    return await loop.run_in_executor(
        None,
        lambda: fn(**final_kwargs),
    )


# ============================================================
# PUBLIC ENTRY
# ============================================================

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

        # ----------------------------------------------------
        # FIND BEST MODEL
        # ----------------------------------------------------

        bests = (
            await compute_recent_best_per_league(
                force_refresh=force_refresh
            )
        )

        if not bests:
            return safe_default_result(
                "recent_best"
            )

        # ----------------------------------------------------
        # LEAGUE MODEL → GLOBAL FALLBACK
        # ----------------------------------------------------

        model_info = (
            bests.get(league)
            or bests.get("_global")
        )

        if not model_info:

            return safe_default_result(
                "recent_best"
            )

        version = model_info.get(
            "model_version"
        )

        if version and (
            version.lower().startswith("final")
            or version.lower().startswith("recent_best")
        ):
            return safe_default_result(
                "recent_best:invalid_selected_model"
            )

        if not version:

            return safe_default_result(
                "recent_best:no_model"
            )

        # ----------------------------------------------------
        # LOAD SELECTED PREDICTOR
        # ----------------------------------------------------

        try:

            predictor_module = (
                importlib.import_module(
                    f"predictors.{version}"
                )
            )

        except Exception as e:

            print(
                f"⚠️ Failed to load predictor "
                f"{version}: {e}"
            )

            return safe_default_result(
                f"recent_best:{version}:missing"
            )

        # ----------------------------------------------------
        # FIND PREDICT FUNCTION
        # ----------------------------------------------------

        fn = getattr(
            predictor_module,
            "predict_home_away",
            None,
        )

        if not fn:

            return safe_default_result(
                f"recent_best:{version}:no_fn"
            )

        # ----------------------------------------------------
        # PREPARE OPTIONAL ARGUMENTS
        # ----------------------------------------------------

        sig = inspect.signature(fn)

        call_kwargs = {}

        if (
            "league" in sig.parameters
            and league is not None
        ):
            call_kwargs["league"] = league

        if (
            "season" in sig.parameters
            and season is not None
        ):
            call_kwargs["season"] = season

        if (
            "match_date" in sig.parameters
            and match_date is not None
        ):
            call_kwargs[
                "match_date"
            ] = match_date

        # ----------------------------------------------------
        # CALL PREDICTOR
        # ----------------------------------------------------

        raw = await _call_predictor_fn(
            fn,
            match_id,
            home_id,
            away_id,
            call_kwargs,
        )

        if not isinstance(raw, dict):

            return safe_default_result(
                f"recent_best:{version}"
            )

        # ----------------------------------------------------
        # NORMALIZE OUTPUT
        # ----------------------------------------------------

        raw["probabilities"] = normalize_probs(
            raw.get(
                "probabilities",
                {},
            )
        )

        # ----------------------------------------------------
        # ENSURE PREDICTION EXISTS
        # ----------------------------------------------------

        if not raw.get("prediction"):

            raw["prediction"] = (
                prediction_from_probs(
                    raw["probabilities"]
                )
            )

        # ----------------------------------------------------
        # ENSURE EXTRA
        # ----------------------------------------------------

        if not isinstance(
            raw.get("extra"),
            dict,
        ):
            raw["extra"] = {}

        # ----------------------------------------------------
        # MODEL QUALITY METADATA
        # ----------------------------------------------------

        raw["extra"][
            "best_model_accuracy"
        ] = model_info.get(
            "accuracy",
            0.0,
        )

        raw["extra"][
            "best_model_weighted_accuracy"
        ] = model_info.get(
            "weighted_accuracy",
            model_info.get(
                "accuracy",
                0.0,
            ),
        )

        raw["extra"][
            "best_model_wilson"
        ] = model_info.get(
            "wilson",
            0.0,
        )

        raw["extra"][
            "best_model_score"
        ] = model_info.get(
            "score",
            0.0,
        )

        raw["extra"][
            "best_model_total"
        ] = model_info.get(
            "total",
            0,
        )

        raw["extra"][
            "best_model_version"
        ] = version

        raw["extra"][
            "best_model_league"
        ] = league or "_global"

        # ----------------------------------------------------
        # ENSEMBLE VERSION
        # ----------------------------------------------------

        raw.setdefault(
            "ensemble_version",
            f"recent_best:{version}",
        )

        # ----------------------------------------------------
        # GENERATED TIME
        # ----------------------------------------------------

        raw.setdefault(
            "generated_at",
            _now().isoformat(),
        )

        return raw

    except Exception as e:

        print(
            f"❌ recent_best predictor failed: {e}"
        )

        return safe_default_result(
            "recent_best:error"
        )


# ============================================================
# OPTIONAL CACHE CONTROL
# ============================================================

def clear_model_cache():
    """
    Clears the recent-best model cache.

    Useful after inserting a new batch of model predictions.
    """

    global _best_per_league_cache
    global _cache_timestamp

    _best_per_league_cache = {}

    _cache_timestamp = None
