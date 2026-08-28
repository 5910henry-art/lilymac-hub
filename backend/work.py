#!/usr/bin/env python3
"""
Async Worker with Sequential Script Execution, Graceful Exit, and Auto-Clear

- Uses PostgreSQL through config2.py
- Scripts run sequentially
- Tracks today's matches
- Treats every status EXCEPT FINISHED as active/relevant
- Keeps running while matches are IN_PLAY / PAUSED / SUSPENDED
- Does not exit simply because no future kickoff remains
- Sleeps 15 min between normal update cycles
- Polls active matches more frequently
- Performs final update only after today's non-finished matches are gone
- Clears screen 1 min after each update
- Handles Ctrl+C gracefully
"""

import asyncio
import os
import signal
import sys
from datetime import datetime, timedelta, timezone

from colorama import Fore, Style, init as color_init
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
)

from config2 import query_db, KENYA


# --------------------------------------------------
# Configuration
# --------------------------------------------------

KENYA_OFFSET = 3

SCRIPTS = [
    "update.py",
    "h2h.py",
    "accumulator.py",
    "book.py",
    "dash2.py",
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STOP_WORKER = False

color_init(autoreset=True)


# --------------------------------------------------
# Match status configuration
# --------------------------------------------------

FINISHED_STATUS = "FINISHED"

# How often to check when today's future matches
# have all started but some are still active.
ACTIVE_MATCH_POLL_SECONDS = 60

# Normal worker cycle.
NORMAL_SLEEP_SECONDS = 15 * 60


# --------------------------------------------------
# Time helpers
# --------------------------------------------------

def now_kenya():
    return datetime.now(KENYA)


def now_utc():
    return datetime.now(timezone.utc)


# --------------------------------------------------
# Database / match helpers
# --------------------------------------------------

async def get_today_matches():
    """
    Return ALL today's matches except FINISHED.

    Important:
    We deliberately do NOT filter by kickoff time.

    This means matches that have already started are retained
    while they are IN_PLAY, PAUSED, SUSPENDED, etc.
    """

    kenya_now = now_kenya()

    kenya_start = kenya_now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    kenya_end = kenya_start + timedelta(days=1)

    utc_start = kenya_start.astimezone(timezone.utc)
    utc_end = kenya_end.astimezone(timezone.utc)

    rows = await query_db(
        """
        SELECT
            id,
            home_team_name,
            away_team_name,
            utcdate,
            status
        FROM matches
        WHERE utcdate >= :utc_start
          AND utcdate < :utc_end
          AND COALESCE(UPPER(status), '') <> 'FINISHED'
        ORDER BY utcdate ASC
        """,
        {
            "utc_start": utc_start,
            "utc_end": utc_end,
        },
    )

    result = []

    for row in rows:

        match_utc = row["utcdate"]

        if match_utc is None:
            continue

        if match_utc.tzinfo is None:
            match_utc = match_utc.replace(
                tzinfo=timezone.utc
            )
        else:
            match_utc = match_utc.astimezone(
                timezone.utc
            )

        match_local = match_utc.astimezone(KENYA)

        status = (
            str(row["status"]).strip().upper()
            if row["status"] is not None
            else "UNKNOWN"
        )

        result.append(
            {
                "id": row["id"],
                "home": row["home_team_name"],
                "away": row["away_team_name"],
                "utc": match_utc,
                "local": match_local,
                "status": status,
            }
        )

    return result


def split_matches(matches):
    """
    Separate matches into:

    future:
        kickoff is still ahead

    active:
        kickoff has passed but match is not FINISHED

    Since get_today_matches() already excludes FINISHED,
    an active match is any non-finished match whose kickoff
    has passed.
    """

    current = now_utc()

    future = []
    active = []

    for match in matches:

        if match["utc"] > current:
            future.append(match)
        else:
            active.append(match)

    return future, active


def print_match_summary(matches):
    """Print today's non-finished matches."""

    if not matches:
        print("No non-finished matches today.\n")
        return

    future, active = split_matches(matches)

    print("\nToday's non-finished matches:")

    if future:
        print("\nUPCOMING:")

        for match in future:
            print(
                f"- {match['home']} vs {match['away']} "
                f"at {match['local']:%H:%M} Kenya "
                f"[{match['status']}]"
            )

    if active:
        print("\nACTIVE / STARTED:")

        for match in active:
            print(
                f"- {match['home']} vs {match['away']} "
                f"kickoff {match['local']:%H:%M} Kenya "
                f"[{match['status']}]"
            )

    print("")


# --------------------------------------------------
# Screen helper
# --------------------------------------------------

def clear_screen():
    """Clear terminal screen."""

    os.system(
        "cls" if os.name == "nt" else "clear"
    )


# --------------------------------------------------
# Script execution
# --------------------------------------------------

async def run_script(script, progress, task_id):
    """
    Run one script sequentially using the same Python
    interpreter / virtual environment as work.py.
    """

    script_path = os.path.join(BASE_DIR, script)

    progress.update(
        task_id,
        description=f"[yellow]Running {script}...",
    )

    if not os.path.isfile(script_path):

        progress.console.print(
            f"Script not found: {script_path}",
            style="red",
        )

        progress.update(
            task_id,
            description=f"{script}: [red]Failed",
            completed=1,
        )

        return 1

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        script_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=BASE_DIR,
    )

    try:

        stdout, stderr = await process.communicate()

    except asyncio.CancelledError:

        if process.returncode is None:

            process.kill()

        await process.wait()

        progress.update(
            task_id,
            description=f"{script}: [red]Cancelled",
            completed=1,
        )

        return -1

    retcode = process.returncode

    if stdout:

        output = stdout.decode(
            errors="replace"
        ).strip()

        if output:

            progress.console.print(
                output,
                style="green",
            )

    if stderr:

        error_output = stderr.decode(
            errors="replace"
        ).strip()

        if error_output:

            progress.console.print(
                f"Warning ({script}): {error_output}",
                style="red",
            )

    status_text = (
        "[green]Done"
        if retcode == 0
        else "[red]Failed"
    )

    progress.update(
        task_id,
        description=f"{script}: {status_text}",
        completed=1,
    )

    return retcode


async def run_all_scripts_sequential(progress):
    """
    Run all scripts in order.
    """

    for script in SCRIPTS:

        if STOP_WORKER:
            break

        task_id = progress.add_task(
            f"{script}: pending",
            total=1,
        )

        retcode = await run_script(
            script,
            progress,
            task_id,
        )

        if retcode != 0:

            progress.console.print(
                f"\n{Fore.RED}"
                f"[Worker] {script} failed. "
                f"Stopping this cycle."
                f"{Style.RESET_ALL}"
            )

            break


# --------------------------------------------------
# Async sleep
# --------------------------------------------------

async def sleep_until(target_time):
    """Sleep until a specified UTC time."""

    current = now_utc()

    wait_sec = (
        target_time - current
    ).total_seconds()

    if wait_sec <= 0:
        return

    mins = wait_sec / 60

    target_kenya = (
        target_time.astimezone(KENYA)
    )

    print(
        f"\nSleeping until "
        f"{target_kenya:%H:%M} Kenya time "
        f"({mins:.1f} mins)\n"
    )

    try:

        await asyncio.sleep(wait_sec)

    except asyncio.CancelledError:

        print(
            f"\n{Fore.RED}"
            f"[Sleep cancelled]"
            f"{Style.RESET_ALL}"
        )

        raise


# --------------------------------------------------
# Clear screen after delay
# --------------------------------------------------

async def clear_screen_after_delay(seconds=60):

    try:

        await asyncio.sleep(seconds)

        clear_screen()

    except asyncio.CancelledError:

        pass


# --------------------------------------------------
# Graceful exit
# --------------------------------------------------

def handle_exit(signum, frame):

    global STOP_WORKER

    print(
        f"\n{Fore.RED}"
        f"[CTRL+C] Received, stopping worker gracefully..."
        f"{Style.RESET_ALL}"
    )

    STOP_WORKER = True

    try:

        current_task = asyncio.current_task()

        for task in asyncio.all_tasks():

            if task is not current_task:

                task.cancel()

    except RuntimeError:

        pass


signal.signal(
    signal.SIGINT,
    handle_exit,
)


# --------------------------------------------------
# Progress factory
# --------------------------------------------------

def create_progress():

    return Progress(
        SpinnerColumn(),
        TextColumn(
            "[progress.description]{task.description}"
        ),
        BarColumn(),
        TimeRemainingColumn(),
        transient=True,
    )


# --------------------------------------------------
# Worker loop
# --------------------------------------------------

async def main():

    global STOP_WORKER

    try:

        print("Worker started...\n")

        # ------------------------------------------
        # Initial detection
        # ------------------------------------------

        matches = await get_today_matches()

        print_match_summary(matches)

        if not matches:

            print(
                "No non-finished matches found today. "
                "Worker exiting.\n"
            )

            return

        # ------------------------------------------
        # First match
        # ------------------------------------------

        future, active = split_matches(matches)

        if future:

            first_match_utc = future[0]["utc"]

        else:

            # All matches already started.
            # Keep worker alive instead of exiting.
            first_match_utc = now_utc()

        first_cycle_time = (
            first_match_utc
            + timedelta(minutes=45)
        )

        choice = input(
            "Press [Enter] to start now, "
            "or type 'wait' to wait until "
            "first match +45min: "
        ).strip().lower()

        if choice == "wait":

            if first_cycle_time > now_utc():

                await sleep_until(
                    first_cycle_time
                )

        # ------------------------------------------
        # Main loop
        # ------------------------------------------

        while not STOP_WORKER:

            # --------------------------------------
            # Refresh database
            # --------------------------------------

            matches = await get_today_matches()

            future, active = split_matches(matches)

            # --------------------------------------
            # Absolutely nothing non-finished
            # --------------------------------------

            if not matches:

                print(
                    "\nAll today's matches are FINISHED.\n"
                )

                print(
                    "Running final update...\n"
                )

                with create_progress() as progress:

                    await run_all_scripts_sequential(
                        progress
                    )

                asyncio.create_task(
                    clear_screen_after_delay(60)
                )

                print(
                    "\nFinal update done. "
                    "Worker exiting.\n"
                )

                break

            # --------------------------------------
            # Display current state
            # --------------------------------------

            print_match_summary(matches)

            # --------------------------------------
            # IMPORTANT:
            #
            # Future matches still exist.
            # --------------------------------------

            if future:

                last_future = future[-1]

                print(
                    f"Latest upcoming match: "
                    f"{last_future['home']} vs "
                    f"{last_future['away']} "
                    f"at {last_future['local']:%H:%M} "
                    f"Kenya [{last_future['status']}]\n"
                )

            # --------------------------------------
            # Run normal update
            # --------------------------------------

            with create_progress() as progress:

                await run_all_scripts_sequential(
                    progress
                )

            asyncio.create_task(
                clear_screen_after_delay(60)
            )

            # --------------------------------------
            # Refresh immediately after scripts
            # --------------------------------------

            matches_after_update = (
                await get_today_matches()
            )

            future_after, active_after = (
                split_matches(
                    matches_after_update
                )
            )


            if not future_after and active_after:

                print(
                    "\n⚽ No more future matches, "
                    "but active matches still exist.\n"
                )

                for match in active_after:

                    print(
                        f"  ACTIVE: "
                        f"{match['home']} vs "
                        f"{match['away']} "
                        f"[{match['status']}]\n"
                    )

                print(
                    "Worker will keep checking until "
                    "these matches become FINISHED.\n"
                )

                try:

                    await asyncio.sleep(
                        ACTIVE_MATCH_POLL_SECONDS
                    )

                except asyncio.CancelledError:

                    break

                continue

            # --------------------------------------
            # Future matches exist
            # --------------------------------------

            if future_after:

                print(
                    f"\n{len(future_after)} "
                    f"future match(es) remain.\n"
                )

                print(
                    "Sleeping 15 minutes before "
                    "next update...\n"
                )

                try:

                    await asyncio.sleep(
                        NORMAL_SLEEP_SECONDS
                    )

                except asyncio.CancelledError:

                    break

                continue

            # --------------------------------------
            # Safety fallback:
            #
            # There are non-finished records but
            # classification produced nothing.
            # Never exit unexpectedly.
            # --------------------------------------

            print(
                "\nNon-finished matches still exist, "
                "but no future kickoff was found.\n"
            )

            print(
                "Worker will continue monitoring "
                "the database.\n"
            )

            try:

                await asyncio.sleep(
                    ACTIVE_MATCH_POLL_SECONDS
                )

            except asyncio.CancelledError:

                break

    except asyncio.CancelledError:

        print(
            f"\n{Fore.RED}"
            f"[Worker cancelled] "
            f"Exiting gracefully..."
            f"{Style.RESET_ALL}"
        )

    except Exception as exc:

        print(
            f"\n{Fore.RED}"
            f"[Worker error] "
            f"{type(exc).__name__}: {exc}"
            f"{Style.RESET_ALL}"
        )

        raise


# --------------------------------------------------
# Entry point
# --------------------------------------------------

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            f"\n{Fore.RED}"
            f"[Worker terminated]"
            f"{Style.RESET_ALL}"
        )
