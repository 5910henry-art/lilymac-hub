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


# ============================================================
# CONFIG
# ============================================================

PREDICTORS_DIR = "predictors"
UTC = timezone.utc
FINAL_MODEL_NAME = "final"

# PostgreSQL pool settings
POOL_MIN_SIZE = 2
POOL_MAX_SIZE = max(2, MAX_CONCURRENT)

# PostgreSQL command timeout
DB_COMMAND_TIMEOUT = 120


# ============================================================
# GLOBALS
# ============================================================

running_tasks: set[asyncio.Task] = set()

_pool: asyncpg.Pool | None = None

_team_cache: dict[int, str] = {}


# ============================================================
# ASYNC-SAFE INPUT
# ============================================================

async def ainput(prompt: str = "") -> str:
    return await asyncio.to_thread(
        input,
        prompt
    )


# ============================================================
# DATABASE POOL
# ============================================================

async def get_pool() -> asyncpg.Pool:
    global _pool

    if _pool is None:

        print(
            f"{Fore.CYAN}"
            f"🔌 Creating PostgreSQL connection pool..."
            f"{Style.RESET_ALL}"
        )

        _pool = await asyncpg.create_pool(
            DATABASE_URL,

            min_size=POOL_MIN_SIZE,

            max_size=POOL_MAX_SIZE,

            command_timeout=DB_COMMAND_TIMEOUT,

            server_settings={
                "search_path": "henry_schema,public"
            },
        )

        print(
            f"{Fore.GREEN}"
            f"✅ PostgreSQL pool ready "
            f"(min={POOL_MIN_SIZE}, max={POOL_MAX_SIZE})"
            f"{Style.RESET_ALL}"
        )

    return _pool


async def close_pool() -> None:
    global _pool

    if _pool is not None:

        try:
            await _pool.close()
        except Exception:
            pass

        _pool = None


# ============================================================
# DATETIME HELPERS
# ============================================================

def to_utc_datetime(dt: Any) -> datetime:
    """
    Convert datetime / ISO string to timezone-aware UTC datetime.
    """

    if dt is None:
        return datetime.now(timezone.utc)

    if isinstance(dt, str):

        try:

            if dt.endswith("Z"):
                dt = datetime.fromisoformat(
                    dt.replace("Z", "+00:00")
                )

            else:
                dt = datetime.fromisoformat(dt)

        except Exception:
            return datetime.now(timezone.utc)

    if isinstance(dt, datetime):

        if dt.tzinfo is None:
            return dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    return datetime.now(timezone.utc)


def to_db_naive(dt: Any) -> datetime:
    """
    Convert datetime to naive UTC datetime.

    Used for PostgreSQL timestamp WITHOUT time zone columns.
    """

    return to_utc_datetime(
        dt
    ).replace(
        tzinfo=None
    )


def json_safe(obj: Any) -> Any:
    """
    Recursively convert datetime/date objects
    to JSON-safe values.
    """

    if isinstance(obj, datetime):
        return to_utc_datetime(
            obj
        ).isoformat()

    if isinstance(obj, date) and not isinstance(obj, datetime):
        return obj.isoformat()

    if isinstance(obj, dict):
        return {
            k: json_safe(v)
            for k, v in obj.items()
        }

    if isinstance(obj, list):
        return [
            json_safe(v)
            for v in obj
        ]

    if isinstance(obj, tuple):
        return [
            json_safe(v)
            for v in obj
        ]

    return obj


# ============================================================
# ARGUMENT PREPARATION
# ============================================================

def _is_simple_type(x: Any) -> bool:
    return isinstance(
        x,
        (
            str,
            int,
            float,
            bool
        )
    )


def _prepare_arg(a: Any) -> Any:

    try:

        if a is None:
            return None

        if isinstance(a, datetime):
            return to_db_naive(a)

        if isinstance(a, date) and not isinstance(a, datetime):
            return a

        if isinstance(
            a,
            (
                dict,
                list,
                tuple
            )
        ):

            if isinstance(a, tuple):
                a = list(a)

            return json.dumps(
                a,
                ensure_ascii=False
            )

        if _is_simple_type(a):
            return a

        return str(a)

    except Exception:

        try:
            return str(a)

        except Exception:
            return None


def _prepare_args(
    args: Iterable[Any]
) -> list:

    return [
        _prepare_arg(a)
        for a in args
    ]


# ============================================================
# DATABASE QUERY
# ============================================================

async def qdb(
    sql: str,
    *args: Any,
    one: bool = False
):

    prepared = tuple(
        _prepare_args(args)
    )

    pool = await get_pool()

    async with pool.acquire() as conn:

        rows = await conn.fetch(
            sql,
            *prepared
        )

    if one:
        return rows[0] if rows else None

    return rows


# ============================================================
# DATABASE EXECUTE
# ============================================================

async def execdb(
    sql: str,
    *args: Any,
    conn: asyncpg.Connection | None = None,
):
    """
    Execute SQL.

    If conn is supplied, reuse that connection.

    This is VERY IMPORTANT for predictors that already hold
    a PostgreSQL connection.

    Without this, a predictor could hold one connection and
    save_prediction() could wait for another connection,
    causing pool starvation/deadlock.
    """

    prepared = tuple(
        _prepare_args(args)
    )

    # --------------------------------------------------------
    # Reuse existing connection
    # --------------------------------------------------------

    if conn is not None:

        await conn.execute(
            sql,
            *prepared
        )

        return

    # --------------------------------------------------------
    # Otherwise acquire a connection normally
    # --------------------------------------------------------

    pool = await get_pool()

    async with pool.acquire() as db_conn:

        await db_conn.execute(
            sql,
            *prepared
        )


# ============================================================
# DB OPERATIONS
# ============================================================

async def clear_table(table: str):

    await execdb(
        f"DELETE FROM {table}"
    )


async def delete_prediction(
    table: str,
    model_version: str
):

    await execdb(
        f"""
        DELETE FROM {table}
        WHERE model_version=$1
        """,
        model_version
    )

    print(
        f"{Fore.YELLOW}"
        f"✅ Deleted {table} records for "
        f"{model_version}"
        f"{Style.RESET_ALL}"
    )


async def show_counts(table: str):

    rows = await qdb(
        f"""
        SELECT
            model_version,
            COUNT(*) AS cnt
        FROM {table}
        GROUP BY model_version
        ORDER BY cnt DESC
        """
    )

    if not rows:

        print(
            f"{Fore.RED}"
            f"No records in {table}"
            f"{Style.RESET_ALL}"
        )

        return

    print(
        f"{Fore.CYAN}"
        f"📊 {table} counts:"
        f"{Style.RESET_ALL}"
    )

    for r in rows:

        print(
            f"  • {r['model_version']}: "
            f"{r['cnt']}"
        )


async def show_table_counts():

    for table in (
        "models",
        "predictions"
    ):

        r = await qdb(
            f"""
            SELECT COUNT(*) AS cnt
            FROM {table}
            """,
            one=True
        )

        cnt = r["cnt"] if r else 0

        print(
            f"  {table}: {cnt} rows"
        )


# ============================================================
# PROBABILITY HELPERS
# ============================================================

def normalize_probs(raw_probs):

    probs = {
        "home_win": 0.0,
        "draw": 0.0,
        "away_win": 0.0
    }

    for k, v in (raw_probs or {}).items():

        key = (
            str(k)
            .lower()
            .replace(" ", "_")
        )

        if key in probs:

            try:
                probs[key] = float(v)

            except Exception:
                probs[key] = 0.0

    total = sum(
        probs.values()
    )

    if 0 < total < 0.99:

        missing = 1.0 - total

        zeros = [
            k
            for k, v in probs.items()
            if v == 0.0
        ]

        if zeros:

            share = (
                missing /
                len(zeros)
            )

            for k in zeros:
                probs[k] += share

    if total == 0:

        probs = {
            "home_win": 0.33,
            "draw": 0.34,
            "away_win": 0.33
        }

    s = sum(
        probs.values()
    ) or 1.0

    for k in probs:
        probs[k] /= s

    return probs


def generate_score_from_probs(probs):

    avg_goals = 2.7

    total_prob = (
        sum(probs.values())
        or 1.0
    )

    home_score = int(
        round(
            (
                probs["home_win"]
                / total_prob
            )
            * avg_goals
        )
    )

    away_score = int(
        round(
            (
                probs["away_win"]
                / total_prob
            )
            * avg_goals
        )
    )

    draw_effect = int(
        round(
            (
                probs["draw"]
                / total_prob
            )
            * 2
        )
    )

    home_score += (
        draw_effect // 2
    )

    away_score += (
        draw_effect // 2
    )

    return {
        "home": max(
            home_score,
            0
        ),
        "away": max(
            away_score,
            0
        )
    }


# ============================================================
# TEAM CACHE
# ============================================================

async def preload_teams():

    global _team_cache

    rows = await qdb(
        """
        SELECT
            id,
            name
        FROM teams
        """
    )

    _team_cache = {
        r["id"]: r["name"]
        for r in rows
    }

    print(
        f"{Fore.CYAN}"
        f"👥 Loaded {len(_team_cache)} teams"
        f"{Style.RESET_ALL}"
    )


def team_name_fast(
    team_id: int
) -> str:

    return _team_cache.get(
        team_id,
        f"Team {team_id}"
    )


# ============================================================
# SAVE PREDICTION
# ============================================================

async def save_prediction(
    match_id,
    prediction,
    table,
    model_version,
    conn: asyncpg.Connection | None = None,
):
    """
    Save prediction using the existing connection when
    possible.
    """

    probs = prediction.get(
        "probabilities",
        {}
    )

    label = (
        str(
            prediction.get(
                "prediction",
                "Draw"
            )
        )
        .lower()
        .replace(
            " ",
            "_"
        )
    )

    confidence = probs.get(
        label,
        max(
            probs.values(),
            default=0.34
        )
    )

    try:
        confidence = float(
            confidence
        )
    except Exception:
        confidence = 0.34

    gen_at = to_db_naive(
        prediction.get(
            "generated_at"
        )
    )

    pred_json = json.dumps(
        json_safe(prediction),
        ensure_ascii=False
    )

    sql = f"""
    INSERT INTO {table}
    (
        match_id,
        model_version,
        prediction_json,
        confidence,
        generated_at
    )
    VALUES
    (
        $1,
        $2,
        $3,
        $4,
        $5
    )

    ON CONFLICT
    (
        match_id,
        model_version
    )

    DO UPDATE SET

        prediction_json =
            EXCLUDED.prediction_json,

        confidence =
            EXCLUDED.confidence,

        generated_at =
            EXCLUDED.generated_at
    """

    # --------------------------------------------------------
    # Reuse predictor connection.
    # --------------------------------------------------------

    await execdb(
        sql,
        match_id,
        model_version,
        pred_json,
        confidence,
        gen_at,
        conn=conn,
    )


# ============================================================
# ACCURACY PER LEAGUE
# ============================================================

async def show_models_accuracy_per_league():

    rows = await qdb(
        """
        SELECT
            m.competition AS league,
            mo.model_version,

            ROUND(
                AVG(
                    CASE
                        WHEN
                        (
                            (
                                m.home_score >
                                m.away_score

                                AND

                                (
                                    mo.prediction_json::jsonb
                                    ->> 'prediction'
                                ) = 'Home Win'
                            )

                            OR

                            (
                                m.home_score <
                                m.away_score

                                AND

                                (
                                    mo.prediction_json::jsonb
                                    ->> 'prediction'
                                ) = 'Away Win'
                            )

                            OR

                            (
                                m.home_score =
                                m.away_score

                                AND

                                (
                                    mo.prediction_json::jsonb
                                    ->> 'prediction'
                                ) = 'Draw'
                            )
                        )

                        THEN 1

                        ELSE 0
                    END
                ) * 100,
                2
            ) AS accuracy,

            COUNT(*) AS matches

        FROM models mo

        JOIN matches m
            ON m.id = mo.match_id

        WHERE
            m.status = 'FINISHED'

        GROUP BY
            m.competition,
            mo.model_version

        ORDER BY
            m.competition,
            accuracy DESC
        """
    )

    if not rows:

        print(
            f"{Fore.RED}"
            f"❌ No finished matches"
            f"{Style.RESET_ALL}"
        )

        return

    league = None

    print(
        "\n"
        f"{Fore.CYAN}"
        f"📊 Model Accuracy per League"
        f"{Style.RESET_ALL}"
        "\n"
    )

    for r in rows:

        if r["league"] != league:

            league = r["league"]

            print(
                f"\n🏟️ {league}"
            )

        print(
            f"  • {r['model_version']}: "
            f"{r['accuracy']}% "
            f"({r['matches']} matches)"
        )


# ============================================================
# MATCHES
# ============================================================

async def get_matches():

    rows = await qdb(
        """
        SELECT *
        FROM matches

        WHERE
            home_team_id IS NOT NULL

            AND

            away_team_id IS NOT NULL
        """
    )

    return [
        dict(r)
        for r in rows
    ]


# ============================================================
# PREDICT ONE MATCH
# ============================================================

async def predict_match(
    match: dict,
    predictor,
    table: str,
    version: str
):

    home = team_name_fast(
        match["home_team_id"]
    )

    away = team_name_fast(
        match["away_team_id"]
    )

    try:

        fn = getattr(
            predictor,
            "predict_home_away",
            None
        )

        if fn is None:

            raise RuntimeError(
                f"{version} has no "
                f"predict_home_away()"
            )

        sig = inspect.signature(
            fn
        )

        is_coro = (
            inspect.iscoroutinefunction(fn)
        )

        allowed_params = set(
            sig.parameters.keys()
        )

        # ----------------------------------------------------
        # Arguments
        # ----------------------------------------------------

        base_kwargs = {
            "match_id":
                match["id"],

            "home_id":
                match["home_team_id"],

            "away_id":
                match["away_team_id"],

            "league":
                match.get("competition"),
        }

        date_val = (
            match.get("match_date")
            or match.get("utcdate")
            or match.get("utcDate")
        )

        safe_date = to_utc_datetime(
            date_val
        )

        if "match_date" in allowed_params:

            base_kwargs[
                "match_date"
            ] = safe_date

        kwargs = {
            k: v

            for k, v
            in base_kwargs.items()

            if k in allowed_params
        }

        result = None

        loop = asyncio.get_running_loop()

        # ====================================================
        # ASYNC PREDICTOR THAT REQUESTS conn
        # ====================================================

        if "conn" in allowed_params:

            if not is_coro:

                raise RuntimeError(
                    f"{version} requests conn "
                    f"but is not async. "
                    f"Convert predictor to "
                    f"asyncpg/Postgres."
                )

            pool = await get_pool()

            # ------------------------------------------------
            # HOLD ONE connection.
            #
            # Predictor and save_prediction() use THIS SAME
            # connection.
            # ------------------------------------------------

            async with pool.acquire() as conn:

                kwargs["conn"] = conn

                result = await fn(
                    **kwargs
                )

                if result:

                    result[
                        "probabilities"
                    ] = normalize_probs(
                        result.get(
                            "probabilities",
                            {}
                        )
                    )

                    if (
                        "prediction"
                        not in result

                        or not result[
                            "prediction"
                        ]
                    ):

                        result[
                            "prediction"
                        ] = (
                            max(
                                result[
                                    "probabilities"
                                ],
                                key=result[
                                    "probabilities"
                                ].get
                            )
                            .replace(
                                "_",
                                " "
                            )
                            .title()
                        )

                    if (
                        "predicted_goals"
                        not in result
                    ):

                        result[
                            "predicted_goals"
                        ] = (
                            generate_score_from_probs(
                                result[
                                    "probabilities"
                                ]
                            )
                        )

                    result[
                        "generated_at"
                    ] = to_utc_datetime(
                        result.get(
                            "generated_at"
                        )
                    )

                    mv = result.get(
                        "ensemble_version",
                        version
                    )

                    # ----------------------------------------
                    # CRITICAL FIX:
                    # Reuse SAME connection.
                    # ----------------------------------------

                    await save_prediction(
                        match["id"],
                        result,
                        table,
                        mv,
                        conn=conn,
                    )

        # ====================================================
        # ASYNC PREDICTOR WITHOUT conn
        # ====================================================

        else:

            if is_coro:

                result = await fn(
                    **kwargs
                )

            else:

                result = await loop.run_in_executor(
                    None,
                    lambda: fn(**kwargs)
                )

            if result:

                result[
                    "probabilities"
                ] = normalize_probs(
                    result.get(
                        "probabilities",
                        {}
                    )
                )

                if (
                    "prediction"
                    not in result

                    or not result[
                        "prediction"
                    ]
                ):

                    result[
                        "prediction"
                    ] = (
                        max(
                            result[
                                "probabilities"
                            ],
                            key=result[
                                "probabilities"
                            ].get
                        )
                        .replace(
                            "_",
                            " "
                        )
                        .title()
                    )

                if (
                    "predicted_goals"
                    not in result
                ):

                    result[
                        "predicted_goals"
                    ] = (
                        generate_score_from_probs(
                            result[
                                "probabilities"
                            ]
                        )
                    )

                result[
                    "generated_at"
                ] = to_utc_datetime(
                    result.get(
                        "generated_at"
                    )
                )

                mv = result.get(
                    "ensemble_version",
                    version
                )

                await save_prediction(
                    match["id"],
                    result,
                    table,
                    mv,
                )

        # ====================================================
        # PRINT RESULT
        # ====================================================

        if result:

            p = result[
                "probabilities"
            ]

            g = result[
                "predicted_goals"
            ]

            print(
                f"{Fore.GREEN}"
                f"{home}"
                f"{Style.RESET_ALL}"

                f" vs "

                f"{Fore.YELLOW}"
                f"{away}"
                f"{Style.RESET_ALL}"

                f" → "

                f"{Fore.CYAN}"
                f"{result['prediction']}"
                f"{Style.RESET_ALL}"
            )

            print(
                f"  Probabilities: "
                f"H:{p['home_win'] * 100:.1f}% "
                f"D:{p['draw'] * 100:.1f}% "
                f"A:{p['away_win'] * 100:.1f}%"
            )

            print(
                f"  Score: "
                f"{g['home']} - "
                f"{g['away']}"
            )

    # --------------------------------------------------------
    # IMPORTANT:
    # asyncio.CancelledError must NOT be swallowed.
    # --------------------------------------------------------

    except asyncio.CancelledError:
        raise

    except Exception as e:

        print(
            f"{Fore.RED}"
            f"[ERROR]"
            f"{Style.RESET_ALL}"
            f" {home} vs {away}: {e}"
        )

        traceback.print_exc()


# ============================================================
# PREDICTOR RUNNER
# ============================================================

async def run_predictor(
    version: str
):

    predictor = None

    module_name = (
        f"{PREDICTORS_DIR}.{version}"
    )

    file_path = os.path.join(
        PREDICTORS_DIR,
        f"{version}.py"
    )

    # ========================================================
    # LOAD PREDICTOR
    # ========================================================

    try:

        if not os.path.exists(
            file_path
        ):

            print(
                f"{Fore.RED}"
                f"❌ Predictor file not found: "
                f"{file_path}"
                f"{Style.RESET_ALL}"
            )

            return

        spec = (
            importlib.util
            .spec_from_file_location(
                module_name,
                file_path
            )
        )

        if (
            spec is None
            or spec.loader is None
        ):

            raise RuntimeError(
                f"Could not load predictor "
                f"spec for {version}"
            )

        predictor = (
            importlib.util
            .module_from_spec(spec)
        )

        spec.loader.exec_module(
            predictor
        )

    except Exception as e:

        print(
            f"{Fore.RED}"
            f"❌ Failed to load predictor "
            f"{version}: {e}"
            f"{Style.RESET_ALL}"
        )

        traceback.print_exc()

        return

    # ========================================================
    # SELECT TABLE
    # ========================================================

    table = (
        "predictions"
        if version == FINAL_MODEL_NAME
        else "models"
    )

    # ========================================================
    # LOAD DATA
    # ========================================================

    await preload_teams()

    matches = await get_matches()

    print(
        f"{Fore.CYAN}"
        f"📋 Matches loaded: "
        f"{len(matches)}"
        f"{Style.RESET_ALL}"
    )

    print(
        f"{Fore.CYAN}"
        f"⚡ Concurrent workers: "
        f"{MAX_CONCURRENT}"
        f"{Style.RESET_ALL}"
    )

    # ========================================================
    # SEMAPHORE
    # ========================================================

    sem = asyncio.Semaphore(
        MAX_CONCURRENT
    )

    try:

        tasks = []

        # ====================================================
        # WORKER
        # ====================================================

        async def worker(m):

            async with sem:

                try:

                    # ------------------------------------------------
                    # IMPORTANT FIX:
                    #
                    # Removed:
                    #
                    # await asyncio.wait_for(
                    #     predict_match(...),
                    #     timeout=30
                    # )
                    #
                    # That timeout was cancelling predictions while
                    # they were waiting on PostgreSQL.
                    # ------------------------------------------------

                    await predict_match(
                        m,
                        predictor,
                        table,
                        version,
                    )

                except asyncio.CancelledError:

                    raise

                except Exception as e:

                    print(
                        f"{Fore.RED}"
                        f"❌ Worker error for "
                        f"match {m.get('id')}: "
                        f"{e}"
                        f"{Style.RESET_ALL}"
                    )

                    traceback.print_exc()

        # ====================================================
        # CREATE TASKS
        # ====================================================

        for m in matches:

            task = asyncio.create_task(
                worker(m)
            )

            running_tasks.add(
                task
            )

            task.add_done_callback(
                lambda tt:
                running_tasks.discard(tt)
            )

            tasks.append(
                task
            )

        # ====================================================
        # WAIT FOR ALL
        # ====================================================

        try:

            await asyncio.gather(
                *tasks
            )

        except asyncio.CancelledError:

            print(
                f"{Fore.RED}"
                f"❌ Prediction cancelled"
                f"{Style.RESET_ALL}"
            )

            for task in tasks:

                if not task.done():
                    task.cancel()

            await asyncio.gather(
                *tasks,
                return_exceptions=True
            )

            raise

        finally:

            for task in tasks:

                running_tasks.discard(
                    task
                )

    finally:

        # ====================================================
        # CLEANUP PREDICTOR MODULE
        # ====================================================

        try:

            if module_name in sys.modules:

                del sys.modules[
                    module_name
                ]

            if predictor is not None:

                del predictor

        except Exception:
            pass

        importlib.invalidate_caches()

    print(
        f"{Fore.GREEN}"
        f"[DONE]"
        f"{Style.RESET_ALL}"
    )


# ============================================================
# MENU
# ============================================================

async def menu():

    while True:

        print(
            "\n=== Lilymac Prediction Hub ==="
        )

        print(
            "1. Run predictor"
        )

        print(
            "2. Clear models OR predictions"
        )

        print(
            "3. Show models accuracy per league"
        )

        print(
            "4. Delete predictions by model version"
        )

        print(
            "5. Show prediction counts"
        )

        print(
            "0. Exit"
        )

        try:

            choice = (
                await ainput(
                    "Choice: "
                )
            ).strip()

        except KeyboardInterrupt:

            print(
                "\n❎ Interrupted — "
                "returning to menu"
            )

            continue

        # ========================================================
        # RUN PREDICTOR
        # ========================================================

        if choice == "1":

            files = [
                f

                for f in os.listdir(
                    PREDICTORS_DIR
                )

                if (
                    f.endswith(".py")
                    and f != "__init__.py"
                )
            ]

            versions = sorted(
                [
                    f[:-3]
                    for f in files
                ]
            )

            if not versions:

                print(
                    f"{Fore.RED}"
                    f"No predictors found in "
                    f"{PREDICTORS_DIR}"
                    f"{Style.RESET_ALL}"
                )

                continue

            for i, v in enumerate(
                versions,
                1
            ):

                print(
                    f"{i}. {v}"
                )

            try:

                sel = (
                    await ainput(
                        "Select (number or name): "
                    )
                ).strip()

            except KeyboardInterrupt:

                print(
                    "\n❎ Selection interrupted — "
                    "returning to menu"
                )

                continue

            if not sel:

                print(
                    "❌ No selection entered"
                )

                continue

            chosen = None

            # ====================================================
            # SELECT BY NUMBER
            # ====================================================

            if sel.isdigit():

                try:

                    idx = int(sel) - 1

                    if (
                        0 <= idx
                        < len(versions)
                    ):

                        chosen = versions[
                            idx
                        ]

                    else:

                        print(
                            f"❌ Invalid selection: "
                            f"number out of range "
                            f"(1-{len(versions)})"
                        )

                        continue

                except ValueError:

                    print(
                        "❌ Invalid number"
                    )

                    continue

            # ====================================================
            # SELECT BY NAME
            # ====================================================

            else:

                normalized = (
                    sel[:-3]
                    if sel.endswith(".py")
                    else sel
                )

                if normalized in versions:

                    chosen = normalized

                else:

                    print(
                        "❌ Invalid selection: "
                        "not a known predictor name"
                    )

                    continue

            # ====================================================
            # RUN
            # ====================================================

            try:

                await run_predictor(
                    chosen
                )

            except asyncio.CancelledError:

                print(
                    f"{Fore.YELLOW}"
                    f"⚠️ Predictor cancelled"
                    f"{Style.RESET_ALL}"
                )

            except Exception as e:

                print(
                    f"{Fore.RED}"
                    f"❌ Error while running "
                    f"predictor {chosen}: {e}"
                    f"{Style.RESET_ALL}"
                )

                traceback.print_exc()

        # ========================================================
        # CLEAR TABLE
        # ========================================================

        elif choice == "2":

            print(
                "\n⚠️ Select table to clear:"
            )

            print(
                "1. models"
            )

            print(
                "2. predictions"
            )

            print(
                "0. cancel"
            )

            try:

                c = (
                    await ainput(
                        "Choice: "
                    )
                ).strip()

            except KeyboardInterrupt:

                print(
                    "\n❎ Interrupted — "
                    "returning to menu"
                )

                continue

            if c == "1":

                await clear_table(
                    "models"
                )

                print(
                    f"{Fore.YELLOW}"
                    f"✅ Cleared models"
                    f"{Style.RESET_ALL}"
                )

            elif c == "2":

                await clear_table(
                    "predictions"
                )

                print(
                    f"{Fore.YELLOW}"
                    f"✅ Cleared predictions"
                    f"{Style.RESET_ALL}"
                )

            else:

                print(
                    "❎ Cancelled"
                )

        # ========================================================
        # ACCURACY
        # ========================================================

        elif choice == "3":

            await show_models_accuracy_per_league()

        # ========================================================
        # DELETE MODEL VERSION
        # ========================================================

        elif choice == "4":

            try:

                mv = (
                    await ainput(
                        "Model version: "
                    )
                ).strip()

            except KeyboardInterrupt:

                print(
                    "\n❎ Interrupted — "
                    "returning to menu"
                )

                continue

            if mv:

                await delete_prediction(
                    "models",
                    mv
                )

                await delete_prediction(
                    "predictions",
                    mv
                )

        # ========================================================
        # COUNTS
        # ========================================================

        elif choice == "5":

            print(
                "📊 Counts summary:"
            )

            await show_table_counts()

            print(
                "📊 Counts per model version:"
            )

            await show_counts(
                "models"
            )

            await show_counts(
                "predictions"
            )

        # ========================================================
        # EXIT
        # ========================================================

        elif choice == "0":

            print(
                "Bye 👋"
            )

            for task in list(
                running_tasks
            ):

                task.cancel()

            await asyncio.gather(
                *list(running_tasks),
                return_exceptions=True
            )

            running_tasks.clear()

            break

        else:

            print(
                "❌ Invalid choice"
            )


# ============================================================
# ENTRYPOINT
# ============================================================

async def main():

    try:

        await menu()

    finally:

        await close_pool()


if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            f"\n"
            f"{Fore.RED}"
            f"❌ Exiting..."
            f"{Style.RESET_ALL}"
        )

        for task in list(
            running_tasks
        ):

            task.cancel()

        sys.exit(0)
