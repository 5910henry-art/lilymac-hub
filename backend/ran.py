#!/usr/bin/env python3

import asyncio
import importlib
import importlib.util
import inspect
import json
import os
import sys
import traceback
from datetime import date, datetime, timezone
from typing import Any, Iterable

import asyncpg
from colorama import Fore, Style, init

from config2 import DATABASE_URL

try:
    import config  # optional, only for non-DB settings like MAX_CONCURRENT
    MAX_CONCURRENT = getattr(config, "MAX_CONCURRENT", 10)
except Exception:
    MAX_CONCURRENT = 10

init(autoreset=True)

# -------------------------------
# Config
# -------------------------------
PREDICTORS_DIR = "predictors"
UTC = timezone.utc
FINAL_MODEL_NAME = "final"

# -------------------------------
# Globals
# -------------------------------
running_tasks: set[asyncio.Task] = set()
_pool: asyncpg.Pool | None = None
_team_cache: dict[int, str] = {}

# -------------------------------
# Async-safe input
# -------------------------------
async def ainput(prompt: str = "") -> str:
    return await asyncio.to_thread(input, prompt)

# -------------------------------
# DB pool / wrappers
# -------------------------------
async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=max(1, MAX_CONCURRENT),
            command_timeout=120,
        )
    return _pool

async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

# -------------------------------
# Datetime helpers
# -------------------------------
def to_utc_datetime(dt: Any) -> datetime:
    """
    Convert any datetime / ISO string to timezone-aware UTC datetime.
    """
    if dt is None:
        return datetime.now(timezone.utc)

    if isinstance(dt, str):
        try:
            if dt.endswith("Z"):
                dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(dt)
        except Exception:
            return datetime.now(timezone.utc)

    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    return datetime.now(timezone.utc)

def to_db_naive(dt: Any) -> datetime:
    """
    Convert any datetime / ISO string to naive UTC datetime for PostgreSQL
    timestamp WITHOUT time zone columns.
    """
    return to_utc_datetime(dt).replace(tzinfo=None)

def json_safe(obj: Any) -> Any:
    """
    Recursively convert datetime/date objects to JSON-safe ISO strings.
    """
    if isinstance(obj, datetime):
        return to_utc_datetime(obj).isoformat()
    if isinstance(obj, date) and not isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [json_safe(v) for v in obj]
    return obj

# -------------------------------
# Arg preparation
# -------------------------------
def _is_simple_type(x: Any) -> bool:
    return isinstance(x, (str, int, float, bool))

def _prepare_arg(a: Any) -> Any:
    try:
        if a is None:
            return None
        if isinstance(a, datetime):
            return to_db_naive(a)
        if isinstance(a, date) and not isinstance(a, datetime):
            return a
        if isinstance(a, (dict, list, tuple)):
            return json.dumps(list(a) if isinstance(a, tuple) else a, ensure_ascii=False)
        if _is_simple_type(a):
            return a
        return str(a)
    except Exception:
        try:
            return str(a)
        except Exception:
            return None

def _prepare_args(args: Iterable[Any]) -> list:
    return [_prepare_arg(a) for a in args]

async def qdb(sql: str, *args: Any, one: bool = False):
    prepared = tuple(_prepare_args(args))
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *prepared)
    if one:
        return rows[0] if rows else None
    return rows

async def execdb(sql: str, *args: Any):
    prepared = tuple(_prepare_args(args))
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(sql, *prepared)

# -------------------------------
# DB operations
# -------------------------------
async def clear_table(table: str):
    await execdb(f"DELETE FROM {table}")

async def delete_prediction(table: str, model_version: str):
    await execdb(f"DELETE FROM {table} WHERE model_version=$1", model_version)
    print(f"{Fore.YELLOW}✅ Deleted {table} records for {model_version}{Style.RESET_ALL}")

async def show_counts(table: str):
    rows = await qdb(
        f"""
        SELECT model_version, COUNT(*) AS cnt
        FROM {table}
        GROUP BY model_version
        ORDER BY cnt DESC
        """
    )
    if not rows:
        print(f"{Fore.RED}No records in {table}{Style.RESET_ALL}")
        return
    print(f"{Fore.CYAN}📊 {table} counts:{Style.RESET_ALL}")
    for r in rows:
        print(f"  • {r['model_version']}: {r['cnt']}")

async def show_table_counts():
    for table in ("models", "predictions"):
        r = await qdb(f"SELECT COUNT(*) AS cnt FROM {table}", one=True)
        cnt = r["cnt"] if r else 0
        print(f"  {table}: {cnt} rows")

# -------------------------------
# Probability helpers
# -------------------------------
def normalize_probs(raw_probs):
    probs = {"home_win": 0.0, "draw": 0.0, "away_win": 0.0}
    for k, v in (raw_probs or {}).items():
        key = str(k).lower().replace(" ", "_")
        if key in probs:
            try:
                probs[key] = float(v)
            except Exception:
                probs[key] = 0.0

    total = sum(probs.values())
    if 0 < total < 0.99:
        missing = 1.0 - total
        zeros = [k for k, v in probs.items() if v == 0.0]
        if zeros:
            share = missing / len(zeros)
            for k in zeros:
                probs[k] += share

    if total == 0:
        probs = {"home_win": 0.33, "draw": 0.34, "away_win": 0.33}

    s = sum(probs.values()) or 1.0
    for k in probs:
        probs[k] /= s
    return probs

def generate_score_from_probs(probs):
    avg_goals = 2.7
    total_prob = sum(probs.values()) or 1.0
    home_score = int(round((probs["home_win"] / total_prob) * avg_goals))
    away_score = int(round((probs["away_win"] / total_prob) * avg_goals))
    draw_effect = int(round((probs["draw"] / total_prob) * 2))
    home_score += draw_effect // 2
    away_score += draw_effect // 2
    return {"home": max(home_score, 0), "away": max(away_score, 0)}

# -------------------------------
# Team cache
# -------------------------------
async def preload_teams():
    global _team_cache
    rows = await qdb("SELECT id, name FROM teams")
    _team_cache = {r["id"]: r["name"] for r in rows}

def team_name_fast(team_id: int) -> str:
    return _team_cache.get(team_id, f"Team {team_id}")

# -------------------------------
# Save prediction (Postgres upsert)
# -------------------------------
async def save_prediction(match_id, prediction, table, model_version):
    probs = prediction.get("probabilities", {})
    label = str(prediction.get("prediction", "Draw")).lower().replace(" ", "_")
    confidence = probs.get(label, max(probs.values(), default=0.34))

    gen_at = to_db_naive(prediction.get("generated_at"))
    pred_json = json.dumps(json_safe(prediction), ensure_ascii=False)

    sql = f"""
    INSERT INTO {table} (match_id, model_version, prediction_json, confidence, generated_at)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (match_id, model_version) DO UPDATE SET
        prediction_json = EXCLUDED.prediction_json,
        confidence = EXCLUDED.confidence,
        generated_at = EXCLUDED.generated_at
    """
    await execdb(sql, match_id, model_version, pred_json, float(confidence), gen_at)

# -------------------------------
# Accuracy per league (Postgres JSON)
# -------------------------------
async def show_models_accuracy_per_league():
    rows = await qdb(
        """
        SELECT
            m.competition AS league,
            mo.model_version,
            ROUND(
                AVG(
                    CASE
                        WHEN (
                            (m.home_score > m.away_score AND (mo.prediction_json::jsonb ->> 'prediction') = 'Home Win')
                            OR
                            (m.home_score < m.away_score AND (mo.prediction_json::jsonb ->> 'prediction') = 'Away Win')
                            OR
                            (m.home_score = m.away_score AND (mo.prediction_json::jsonb ->> 'prediction') = 'Draw')
                        ) THEN 1 ELSE 0
                    END
                ) * 100,
                2
            ) AS accuracy,
            COUNT(*) AS matches
        FROM models mo
        JOIN matches m ON m.id = mo.match_id
        WHERE m.status = 'FINISHED'
        GROUP BY m.competition, mo.model_version
        ORDER BY m.competition, accuracy DESC
        """
    )
    if not rows:
        print("❌ No finished matches")
        return

    league = None
    print("\n📊 Model Accuracy per League\n")
    for r in rows:
        if r["league"] != league:
            league = r["league"]
            print(f"\n🏟️ {league}")
        print(f"  • {r['model_version']}: {r['accuracy']}% ({r['matches']} matches)")

# -------------------------------
# Match helpers
# -------------------------------
async def get_matches():
    rows = await qdb(
        """
        SELECT *
        FROM matches
        WHERE home_team_id IS NOT NULL
          AND away_team_id IS NOT NULL
        """
    )
    return [dict(r) for r in rows]

# -------------------------------
# Prediction runner
# -------------------------------
async def predict_match(match: dict, predictor, table: str, version: str):
    home = team_name_fast(match["home_team_id"])
    away = team_name_fast(match["away_team_id"])

    try:
        fn = getattr(predictor, "predict_home_away", None)
        if fn is None:
            raise RuntimeError(f"{version} has no predict_home_away()")

        sig = inspect.signature(fn)
        is_coro = inspect.iscoroutinefunction(fn)
        allowed_params = set(sig.parameters.keys())

        base_kwargs = {
            "match_id": match["id"],
            "home_id": match["home_team_id"],
            "away_id": match["away_team_id"],
            "league": match.get("competition"),
        }

        date_val = match.get("match_date") or match.get("utcdate") or match.get("utcDate")
        safe_date = to_utc_datetime(date_val)

        if "match_date" in allowed_params:
            base_kwargs["match_date"] = safe_date

        kwargs = {k: v for k, v in base_kwargs.items() if k in allowed_params}
        result = None
        loop = asyncio.get_running_loop()

        if "conn" in allowed_params:
            if not is_coro:
                raise RuntimeError(
                    f"{version} requests conn but is not async. Convert the predictor to asyncpg/Postgres."
                )
            pool = await get_pool()
            async with pool.acquire() as conn:
                kwargs["conn"] = conn
                result = await fn(**kwargs)
        else:
            if is_coro:
                result = await fn(**kwargs)
            else:
                result = await loop.run_in_executor(None, lambda: fn(**kwargs))

        if result:
            result["probabilities"] = normalize_probs(result.get("probabilities", {}))

            if "prediction" not in result or not result["prediction"]:
                result["prediction"] = (
                    max(result["probabilities"], key=result["probabilities"].get)
                    .replace("_", " ")
                    .title()
                )

            if "predicted_goals" not in result:
                result["predicted_goals"] = generate_score_from_probs(result["probabilities"])

            result["generated_at"] = to_utc_datetime(result.get("generated_at"))
            mv = result.get("ensemble_version", version)
            await save_prediction(match["id"], result, table, mv)

            p = result["probabilities"]
            g = result["predicted_goals"]

            print(
                f"{Fore.GREEN}{home}{Style.RESET_ALL} vs {Fore.YELLOW}{away}{Style.RESET_ALL} → {Fore.CYAN}{result['prediction']}{Style.RESET_ALL}"
            )
            print(f"  Probabilities: H:{p['home_win']*100:.1f}% D:{p['draw']*100:.1f}% A:{p['away_win']*100:.1f}%")
            print(f"  Score: {g['home']} - {g['away']}")

    except Exception as e:
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {home} vs {away}: {e}")
        traceback.print_exc()

# -------------------------------
# Predictor runner
# -------------------------------
async def run_predictor(version: str):
    predictor = None
    module_name = f"{PREDICTORS_DIR}.{version}"
    file_path = os.path.join(PREDICTORS_DIR, f"{version}.py")

    try:
        if not os.path.exists(file_path):
            print(f"{Fore.RED}❌ Predictor file not found: {file_path}{Style.RESET_ALL}")
            return
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        predictor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(predictor)
    except Exception as e:
        print(f"{Fore.RED}❌ Failed to load predictor {version}: {e}{Style.RESET_ALL}")
        traceback.print_exc()
        return

    table = "predictions" if version == FINAL_MODEL_NAME else "models"

    await preload_teams()
    matches = await get_matches()
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    try:
        tasks = []

        async def worker(m):
            async with sem:
                await asyncio.wait_for(
                    predict_match(m, predictor, table, version),
                    timeout=30,
                )

        for m in matches:
            t = asyncio.create_task(worker(m))
            running_tasks.add(t)
            t.add_done_callback(lambda tt: running_tasks.discard(tt))
            tasks.append(t)

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            print(f"{Fore.RED}❌ Prediction cancelled{Style.RESET_ALL}")
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            for t in tasks:
                running_tasks.discard(t)
            pending = [t for t in running_tasks if not t.done()]
            if pending:
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for t in pending:
                    running_tasks.discard(t)

    finally:
        try:
            if module_name in sys.modules:
                del sys.modules[module_name]
            del predictor
        except Exception:
            pass
        importlib.invalidate_caches()

    print(f"{Fore.GREEN}[DONE]{Style.RESET_ALL}")

# -------------------------------
# Menu
# -------------------------------
async def menu():
    while True:
        print("\n=== Lilymac Prediction Hub ===")
        print("1. Run predictor")
        print("2. Clear models OR predictions")
        print("3. Show models accuracy per league")
        print("4. Delete predictions by model version")
        print("5. Show prediction counts")
        print("0. Exit")
        try:
            choice = (await ainput("Choice: ")).strip()
        except KeyboardInterrupt:
            print("\n❎ Interrupted — returning to menu")
            continue

        if choice == "1":
            files = [f for f in os.listdir(PREDICTORS_DIR) if f.endswith(".py") and f != "__init__.py"]
            versions = sorted([f[:-3] for f in files])
            if not versions:
                print(f"{Fore.RED}No predictors found in {PREDICTORS_DIR}{Style.RESET_ALL}")
                continue

            for i, v in enumerate(versions, 1):
                print(f"{i}. {v}")

            try:
                sel = (await ainput("Select (number or name): ")).strip()
            except KeyboardInterrupt:
                print("\n❎ Selection interrupted — returning to menu")
                continue

            if not sel:
                print("❌ No selection entered")
                continue

            chosen = None
            if sel.isdigit():
                try:
                    idx = int(sel) - 1
                    if 0 <= idx < len(versions):
                        chosen = versions[idx]
                    else:
                        print(f"❌ Invalid selection: number out of range (1-{len(versions)})")
                        continue
                except ValueError:
                    print("❌ Invalid number")
                    continue
            else:
                normalized = sel[:-3] if sel.endswith(".py") else sel
                if normalized in versions:
                    chosen = normalized
                else:
                    print("❌ Invalid selection: not a known predictor name")
                    continue

            try:
                await run_predictor(chosen)
            except Exception as e:
                print(f"{Fore.RED}❌ Error while running predictor {chosen}: {e}{Style.RESET_ALL}")
                traceback.print_exc()

        elif choice == "2":
            print("\n⚠️ Select table to clear:")
            print("1. models")
            print("2. predictions")
            print("0. cancel")
            try:
                c = (await ainput("Choice: ")).strip()
            except KeyboardInterrupt:
                print("\n❎ Interrupted — returning to menu")
                continue
            if c == "1":
                await clear_table("models")
                print(f"{Fore.YELLOW}✅ Cleared models{Style.RESET_ALL}")
            elif c == "2":
                await clear_table("predictions")
                print(f"{Fore.YELLOW}✅ Cleared predictions{Style.RESET_ALL}")
            else:
                print("❎ Cancelled")
        elif choice == "3":
            await show_models_accuracy_per_league()
        elif choice == "4":
            try:
                mv = (await ainput("Model version: ")).strip()
            except KeyboardInterrupt:
                print("\n❎ Interrupted — returning to menu")
                continue
            if mv:
                await delete_prediction("models", mv)
                await delete_prediction("predictions", mv)
        elif choice == "5":
            print("📊 Counts summary:")
            await show_table_counts()
            print("📊 Counts per model version:")
            await show_counts("models")
            await show_counts("predictions")
        elif choice == "0":
            print("Bye 👋")
            for t in list(running_tasks):
                t.cancel()
            await asyncio.gather(*list(running_tasks), return_exceptions=True)
            running_tasks.clear()
            break
        else:
            print("❌ Invalid choice")

# -------------------------------
# Entrypoint
# -------------------------------
async def main():
    try:
        await menu()
    finally:
        await close_pool()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Fore.RED}❌ Exiting...{Style.RESET_ALL}")
        for t in list(running_tasks):
            t.cancel()
        sys.exit(0)
