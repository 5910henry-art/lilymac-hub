#!/usr/bin/env python3
"""
Cleaned run.py for Lilymac Prediction Hub
- Removes dependency on config.get_db()
- Uses config.query_db / config.execute_db wrappers
- Provides safe per-call DB `conn` for predictors that request it (supports both async aiosqlite and sync sqlite3 predictors)
- Keeps the original menu and prediction orchestration logic
"""
import asyncio
import json
import importlib
import importlib.util
import os
import sys
import inspect
import traceback
from datetime import datetime, date, timezone
from math import ceil
from colorama import Fore, Style, init
from typing import Any, Iterable

import aiosqlite
import sqlite3

import config
from config import query_db as cfg_query_db, execute_db as cfg_execute_db, DB_FILE

init(autoreset=True)

# -------------------------------
# Config
# -------------------------------
PREDICTORS_DIR = "predictors"
MAX_CONCURRENT = getattr(config, "MAX_CONCURRENT", 10)
UTC = timezone.utc
FINAL_MODEL_NAME = "final"

# -------------------------------
# Globals
# -------------------------------
running_tasks: set[asyncio.Task] = set()

# -------------------------------
# Async-safe input
# -------------------------------
async def ainput(prompt: str = "") -> str:
    return await asyncio.to_thread(input, prompt)

# -------------------------------
# Arg preparation (sqlite-friendly)
# -------------------------------
def _is_simple_type(x: Any) -> bool:
    return isinstance(x, (str, int, float, bool))


def _prepare_arg(a: Any) -> Any:
    try:
        if a is None:
            return None
        if isinstance(a, datetime):
            if a.tzinfo:
                return a.astimezone(UTC).isoformat()
            return a.replace(tzinfo=UTC).isoformat()
        if isinstance(a, date) and not isinstance(a, datetime):
            return a.isoformat()
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

# -------------------------------
# Thin wrappers around config DB helpers
# -------------------------------
async def qdb(sql: str, *args: Any, one: bool = False):
    prepared = tuple(_prepare_args(args))
    rows = await cfg_query_db(sql, prepared)
    if one:
        return rows[0] if rows else None
    return rows


async def execdb(sql: str, *args: Any):
    prepared = tuple(_prepare_args(args))
    await cfg_execute_db(sql, prepared)

# -------------------------------
# DB operations
# -------------------------------
async def clear_table(table: str):
    await execdb(f"DELETE FROM {table}")


async def delete_prediction(table: str, model_version: str):
    await execdb(f"DELETE FROM {table} WHERE model_version=?", model_version)
    print(f"{Fore.YELLOW}✅ Deleted {table} records for {model_version}{Style.RESET_ALL}")


async def show_counts(table: str):
    rows = await qdb(f"""
        SELECT model_version, COUNT(*) AS cnt
        FROM {table}
        GROUP BY model_version
        ORDER BY cnt DESC
    """)
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
        key = k.lower().replace(" ", "_")
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
    home_score = ceil(probs["home_win"] / total_prob * avg_goals)
    away_score = ceil(probs["away_win"] / total_prob * avg_goals)
    draw_effect = ceil(probs["draw"] / total_prob * 2)
    home_score += draw_effect // 2
    away_score += draw_effect // 2
    return {"home": max(home_score, 0), "away": max(away_score, 0)}

# -------------------------------
# Save prediction (SQLite upsert)
# -------------------------------
async def save_prediction(match_id: int, prediction: dict, table: str, model_version: str):
    probs = prediction.get("probabilities", {})
    label = prediction.get("prediction", "Draw").lower().replace(" ", "_")
    confidence = probs.get(label, max(probs.values(), default=0.34))
    gen_at = prediction.get("generated_at") or datetime.now(UTC).isoformat()
    pred_json = json.dumps(prediction, ensure_ascii=False)

    sql = f"""
    INSERT INTO {table} (match_id, model_version, prediction_json, confidence, generated_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(match_id, model_version) DO UPDATE SET
        prediction_json=excluded.prediction_json,
        confidence=excluded.confidence,
        generated_at=excluded.generated_at
    """
    await execdb(sql, match_id, model_version, pred_json, float(confidence), gen_at)

# -------------------------------
# Accuracy per league (SQLite JSON)
# -------------------------------
async def show_models_accuracy_per_league():
    rows = await qdb("""
        SELECT m.competition AS league, mo.model_version,
        ROUND(AVG(
            CASE
                WHEN (m.home_score>m.away_score AND json_extract(mo.prediction_json,'$.prediction')='Home Win')
                  OR (m.home_score<m.away_score AND json_extract(mo.prediction_json,'$.prediction')='Away Win')
                  OR (m.home_score=m.away_score AND json_extract(mo.prediction_json,'$.prediction')='Draw')
                THEN 1 ELSE 0 END
        )*100,2) AS accuracy,
        COUNT(*) AS matches
        FROM models mo
        JOIN matches m ON m.id=mo.match_id
        WHERE m.status='FINISHED'
        GROUP BY league, mo.model_version
        ORDER BY league, accuracy DESC
    """)
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
    return await qdb("SELECT * FROM matches WHERE home_team_id IS NOT NULL AND away_team_id IS NOT NULL")


async def team_name(team_id: int) -> str:
    r = await qdb("SELECT name FROM teams WHERE id=?", team_id, one=True)
    return r["name"] if r else f"Team {team_id}"

# -------------------------------
# Prediction runner
# -------------------------------
async def predict_match(match: dict, predictor, table: str, version: str):
    home = await team_name(match["home_team_id"])
    away = await team_name(match["away_team_id"])
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
        safe_date = None
        if date_val is not None:
            if isinstance(date_val, str):
                try:
                    safe_date = datetime.fromisoformat(date_val).astimezone(UTC)
                except Exception:
                    safe_date = datetime.now(UTC)
            elif isinstance(date_val, datetime):
                safe_date = date_val.astimezone(UTC)
        if safe_date is None:
            safe_date = datetime.now(UTC)

        if "match_date" in allowed_params:
            base_kwargs["match_date"] = safe_date

        # Only include parameters the predictor asked for
        kwargs = {k: v for k, v in base_kwargs.items() if k in allowed_params}

        result = None
        loop = asyncio.get_running_loop()

        # If predictor wants a DB connection and supports it, provide a safe per-call connection.
        if "conn" in allowed_params:
            if is_coro:
                # async predictor: provide an aiosqlite connection
                async with aiosqlite.connect(DB_FILE) as conn:
                    # apply pragmas similar to config._init_pragmas
                    await conn.execute("PRAGMA journal_mode=WAL;")
                    await conn.execute("PRAGMA synchronous=NORMAL;")
                    await conn.execute("PRAGMA temp_store=MEMORY;")
                    await conn.execute("PRAGMA foreign_keys=ON;")
                    kwargs["conn"] = conn
                    result = await fn(**kwargs)
            else:
                # sync predictor: provide a sqlite3 connection executed inside a thread
                def call_sync_with_conn():
                    conn = sqlite3.connect(DB_FILE)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute("PRAGMA journal_mode=WAL;")
                    cur.execute("PRAGMA synchronous=NORMAL;")
                    cur.execute("PRAGMA temp_store=MEMORY;")
                    cur.execute("PRAGMA foreign_keys=ON;")
                    conn.commit()
                    try:
                        kwargs["conn"] = conn
                        return fn(**kwargs)
                    finally:
                        conn.close()

                result = await loop.run_in_executor(None, call_sync_with_conn)

        else:
            # predictor does not request conn — call normally (async or sync)
            if is_coro:
                result = await fn(**kwargs)
            else:
                result = await loop.run_in_executor(None, lambda: fn(**kwargs))

        if result:
            result["probabilities"] = normalize_probs(result.get("probabilities", {}))
            if "prediction" not in result or not result["prediction"]:
                result["prediction"] = max(result["probabilities"], key=result["probabilities"].get).replace("_", " ").title()
            result["predicted_goals"] = generate_score_from_probs(result["probabilities"])
            result["generated_at"] = result.get("generated_at") or datetime.now(UTC).isoformat()
            mv = result.get("ensemble_version", version)
            await save_prediction(match["id"], result, table, mv)

            p = result["probabilities"]
            g = result["predicted_goals"]

            print(f"{Fore.GREEN}{home}{Style.RESET_ALL} vs {Fore.YELLOW}{away}{Style.RESET_ALL} → {Fore.CYAN}{result['prediction']}{Style.RESET_ALL}")
            print(f"  Probabilities: H:{p['home_win']*100:.1f}% D:{p['draw']*100:.1f}% A:{p['away_win']*100:.1f}%")
            print(f"  Score: {g['home']} - {g['away']}")

    except Exception as e:
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {home} vs {away}: {e}")
        traceback.print_exc()

# -------------------------------
# Predictor runner (fresh imports & safer DB ordering)
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

    # Now that predictor is loaded, fetch matches
    table = "predictions" if version == FINAL_MODEL_NAME else "models"
    matches = await get_matches()
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    try:
        tasks = []

        async def worker(m):
            async with sem:
                await predict_match(m, predictor, table, version)

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
# Menu (robust)
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
    await menu()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Fore.RED}❌ Exiting...{Style.RESET_ALL}")
        for t in list(running_tasks):
            t.cancel()
        sys.exit(0)
