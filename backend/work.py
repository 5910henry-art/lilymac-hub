#!/usr/bin/env python3
"""
Async Worker with Sequential Script Execution, Graceful Exit, and Auto-Clear

- Uses PostgreSQL through config2.py
- Scripts run sequentially
- Tracks today's upcoming matches
- Sleeps 15 min between cycles during the day
- Final run 2h15 after the last match
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
    "Odds.py",
    "accumulator.py",
    "book.py",
    "dash2.py",
]

# Resolve paths relative to this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Graceful stop flag
STOP_WORKER = False

color_init(autoreset=True)


# --------------------------------------------------
# Time helpers
# --------------------------------------------------
def now_kenya():
    return datetime.now(KENYA)
# --------------------------------------------------
# Database / match helpers
# --------------------------------------------------
async def get_upcoming_matches():
    """
    Get today's upcoming matches based on Kenya calendar date.

    utcdate is stored as a timezone-aware UTC timestamp in PostgreSQL.
    """

    kenya_now = now_kenya()

    # Kenya start/end of today
    kenya_start = kenya_now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    kenya_end = kenya_start + timedelta(days=1)

    # Convert Kenya boundaries to UTC.
    # Keep them timezone-aware because PostgreSQL utcdate is timestamptz.
    utc_start = kenya_start.astimezone(timezone.utc)
    utc_end = kenya_end.astimezone(timezone.utc)

    rows = await query_db(
        """
        SELECT
            id,
            home_team_name,
            away_team_name,
            utcdate
        FROM matches
        WHERE utcdate >= :utc_start
          AND utcdate < :utc_end
        ORDER BY utcdate ASC
        """,
        {
            "utc_start": utc_start,
            "utc_end": utc_end,
        }
    )

    now_utc = datetime.now(timezone.utc)

    upcoming = []

    for row in rows:

        match_utc = row["utcdate"]

        if match_utc is None:
            continue

        # PostgreSQL normally returns timestamptz as aware datetime.
        if match_utc.tzinfo is None:
            match_utc = match_utc.replace(
                tzinfo=timezone.utc
            )
        else:
            match_utc = match_utc.astimezone(
                timezone.utc
            )

        # Only future matches
        if match_utc > now_utc:

            # Convert UTC -> Kenya using the actual timezone
            match_local = match_utc.astimezone(KENYA)

            upcoming.append(
                (
                    row["home_team_name"],
                    row["away_team_name"],
                    match_utc,
                    match_local,
                )
            )

    return upcoming

def print_match_summary(matches):
    """Print today's upcoming matches."""
    if not matches:
        print("No upcoming matches today.\n")
        return

    print("\nToday's upcoming matches:")

    for home, away, match_utc, match_local in matches:
        print(
            f"- {home} vs {away} "
            f"at {match_local.strftime('%H:%M')} Kenya time"
        )

    print("")


# --------------------------------------------------
# Screen helper
# --------------------------------------------------

def clear_screen():
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


# --------------------------------------------------
# Script execution
# --------------------------------------------------

async def run_script(script, progress, task_id):
    """
    Run one script sequentially using the same Python
    interpreter/virtual environment as work.py.
    """

    script_path = os.path.join(BASE_DIR, script)

    progress.update(
        task_id,
        description=f"[yellow]Running {script}..."
    )

    # Verify script exists
    if not os.path.isfile(script_path):
        progress.console.print(
            f"Script not found: {script_path}",
            style="red"
        )

        progress.update(
            task_id,
            description=f"{script}: [red]Failed",
            completed=1
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
            completed=1
        )

        return -1

    retcode = process.returncode

    if stdout:
        output = stdout.decode(errors="replace").strip()

        if output:
            progress.console.print(
                output,
                style="green"
            )

    if stderr:
        error_output = stderr.decode(errors="replace").strip()

        if error_output:
            progress.console.print(
                f"Warning ({script}): {error_output}",
                style="red"
            )

    status_text = (
        "[green]Done"
        if retcode == 0
        else "[red]Failed"
    )

    progress.update(
        task_id,
        description=f"{script}: {status_text}",
        completed=1
    )

    return retcode


async def run_all_scripts_sequential(progress):
    """
    Run all scripts in order.
    Stops when Ctrl+C has been received.
    """

    for script in SCRIPTS:

        if STOP_WORKER:
            break

        task_id = progress.add_task(
            f"{script}: pending",
            total=1
        )

        retcode = await run_script(
            script,
            progress,
            task_id
        )

        # Stop pipeline if a script fails
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

    now = datetime.now(timezone.utc)
    wait_sec = (target_time - now).total_seconds()

    if wait_sec <= 0:
        return

    mins = wait_sec / 60

    target_kenya = target_time + timedelta(hours=KENYA_OFFSET)

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
    """Clear terminal after a delay."""

    try:
        await asyncio.sleep(seconds)
        clear_screen()

    except asyncio.CancelledError:
        pass


# --------------------------------------------------
# Graceful exit
# --------------------------------------------------

def handle_exit(signum, frame):
    """
    Handle Ctrl+C gracefully.
    """

    global STOP_WORKER

    print(
        f"\n{Fore.RED}"
        f"[CTRL+C] Received, stopping worker gracefully..."
        f"{Style.RESET_ALL}"
    )

    STOP_WORKER = True

    # Cancel currently running asyncio tasks
    try:
        current_task = asyncio.current_task()

        for task in asyncio.all_tasks():
            if task is not current_task:
                task.cancel()

    except RuntimeError:
        # Event loop may already be shutting down
        pass


signal.signal(signal.SIGINT, handle_exit)


# --------------------------------------------------
# Progress factory
# --------------------------------------------------

def create_progress():
    """Create Rich progress display."""

    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
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
        # Initial match detection
        # ------------------------------------------

        matches = await get_upcoming_matches()

        print_match_summary(matches)

        if not matches:
            print(
                "No upcoming matches found. "
                "Worker exiting.\n"
            )
            return

        # ------------------------------------------
        # Start / wait choice
        # ------------------------------------------

        first_match_utc = matches[0][2]

        first_cycle_time = (
            first_match_utc + timedelta(minutes=45)
        )

        choice = input(
            "Press [Enter] to start now, "
            "or type 'wait' to wait until "
            "first match +45min: "
        ).strip().lower()

        if choice == "wait":

            await sleep_until(
                first_cycle_time
            )

        # ------------------------------------------
        # Main update loop
        # ------------------------------------------

        while not STOP_WORKER:

            # --------------------------------------
            # Refresh today's upcoming matches
            # --------------------------------------

            matches = await get_upcoming_matches()

            if not matches:

                print(
                    "No more upcoming matches today. "
                    "Worker exiting.\n"
                )

                break

            print_match_summary(matches)

            # --------------------------------------
            # IMPORTANT:
            # Recalculate latest last match every
            # cycle from the database.
            # --------------------------------------

            last_match_utc = matches[-1][2]

            final_cycle_time = (
                last_match_utc
                + timedelta(hours=2, minutes=15)
            )

            # --------------------------------------
            # Run pipeline
            # --------------------------------------

            with create_progress() as progress:

                await run_all_scripts_sequential(
                    progress
                )

            # --------------------------------------
            # Schedule screen clearing
            # --------------------------------------

            asyncio.create_task(
                clear_screen_after_delay(60)
            )

            # --------------------------------------
            # Refresh matches again after update
            #
            # This catches:
            # - new matches
            # - postponed matches
            # - cancelled matches
            # - matches that have started
            # --------------------------------------

            matches_after_update = (
                await get_upcoming_matches()
            )

            # --------------------------------------
            # No future matches remain
            # --------------------------------------

            if not matches_after_update:

                print(
                    "\nNo more upcoming matches today.\n"
                )

                # If we had a known last match, wait
                # for the final update time.
                now = datetime.now(timezone.utc)

                if now < final_cycle_time:

                    print(
                        "All today's matches have started.\n"
                        f"Final update scheduled for "
                        f"{final_cycle_time.astimezone(KENYA):%H:%M} "
                        "Kenya time.\n"
                    )

                    await sleep_until(
                        final_cycle_time
                    )

                    if STOP_WORKER:
                        break

                    # ----------------------------------
                    # Final update
                    # ----------------------------------

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
            # Recalculate last match after refresh
            # --------------------------------------

            last_match_utc = (
                matches_after_update[-1][2]
            )

            final_cycle_time = (
                last_match_utc
                + timedelta(hours=2, minutes=15)
            )

            now = datetime.now(timezone.utc)

            # --------------------------------------
            # Last match has started
            # --------------------------------------

            if now >= last_match_utc:

                print(
                    "\nLast known match has started.\n"
                    f"Sleeping until "
                    f"{final_cycle_time.astimezone(KENYA):%H:%M} "
                    "Kenya time for final update...\n"
                )

                await sleep_until(
                    final_cycle_time
                )

                if STOP_WORKER:
                    break

                # ----------------------------------
                # Final update
                # ----------------------------------

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
            # Wait 15 minutes
            # --------------------------------------

            if not STOP_WORKER:

                print(
                    "Sleeping 15 minutes before "
                    "next update...\n"
                )

                try:

                    await asyncio.sleep(
                        15 * 60
                    )

                except asyncio.CancelledError:

                    break

    except asyncio.CancelledError:

        print(
            f"\n{Fore.RED}"
            f"[Worker cancelled] Exiting gracefully..."
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
            f"[CTRL+C] Worker terminated."
            f"{Style.RESET_ALL}"
        )
