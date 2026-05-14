#!/usr/bin/env python3
"""
Async Worker with Sequential Script Execution, Graceful Exit, and Auto-Clear
- Scripts run in order
- Tracks today's matches
- Sleeps 15 min between cycles during day
- Final run 2h15 after last match
- Clears screen 1 min after each update
- Handles Ctrl+C gracefully
"""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
import os
import signal
from colorama import Fore, Style, init as color_init
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn

DB_FILE = "football.db"
KENYA_OFFSET = 3
SCRIPTS = [
    "update.py",
    "h2h.py",
    "model.py",
    "accumulator.py",
    "book.py",
    "dash2.py"
]

color_init(autoreset=True)

STOP_WORKER = False  # global flag for graceful exit

# -------------------------
# Helpers
# -------------------------
def now_kenya():
    return datetime.now(timezone.utc) + timedelta(hours=KENYA_OFFSET)

def get_upcoming_matches():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        today_str = now_kenya().strftime("%Y-%m-%d")
        cursor.execute("""
            SELECT id, home_team_name, away_team_name, utcDate
            FROM matches
            WHERE substr(utcDate,1,10)=?
            ORDER BY utcDate ASC
        """, (today_str,))
        rows = cursor.fetchall()

    now_utc = datetime.now(timezone.utc)
    upcoming = []
    for m in rows:
        match_utc = datetime.fromisoformat(m[3].replace("Z", "+00:00"))
        if match_utc > now_utc:
            match_local = match_utc + timedelta(hours=KENYA_OFFSET)
            upcoming.append((m[1], m[2], match_utc, match_local))
    return upcoming

def print_match_summary(matches):
    if not matches:
        print("No upcoming matches today.\n")
        return
    print("\nToday's upcoming matches:")
    for m in matches:
        print(f"- {m[0]} vs {m[1]} at {m[3].strftime('%H:%M')} Kenya time")
    print("")

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

# -------------------------
# Run a single script sequentially
# -------------------------
async def run_script(script, progress, task_id):
    progress.update(task_id, description=f"[yellow]Running {script}...")
    process = await asyncio.create_subprocess_exec(
        "python3", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await process.communicate()
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        progress.update(task_id, description=f"{script}: [red]Cancelled", completed=1)
        return -1

    retcode = process.returncode
    if stdout:
        progress.console.print(stdout.decode().strip(), style="green")
    if stderr:
        progress.console.print(f"Warning ({script}): {stderr.decode().strip()}", style="red")
    status_text = "[green]Done" if retcode == 0 else "[red]Failed"
    progress.update(task_id, description=f"{script}: {status_text}", completed=1)
    return retcode

async def run_all_scripts_sequential(progress):
    for s in SCRIPTS:
        if STOP_WORKER:
            break
        task_id = progress.add_task(f"{s}: pending", total=1)
        await run_script(s, progress, task_id)

# -------------------------
# Async sleep until target
# -------------------------
async def sleep_until(target_time):
    now = datetime.now(timezone.utc)
    wait_sec = (target_time - now).total_seconds()
    if wait_sec > 0:
        mins = wait_sec / 60
        print(f"\nSleeping until {target_time + timedelta(hours=KENYA_OFFSET):%H:%M} Kenya time ({mins:.1f} mins)\n")
        try:
            await asyncio.sleep(wait_sec)
        except asyncio.CancelledError:
            print(f"\n{Fore.RED}[Sleep cancelled]{Style.RESET_ALL}")
            raise

# -------------------------
# Clear screen after delay
# -------------------------
async def clear_screen_after_delay(seconds=60):
    try:
        await asyncio.sleep(seconds)
        clear_screen()
    except asyncio.CancelledError:
        pass

# -------------------------
# Graceful exit handler
# -------------------------
def handle_exit(signum, frame):
    global STOP_WORKER
    print(f"\n{Fore.RED}[CTRL+C] Received, stopping worker gracefully...{Style.RESET_ALL}")
    STOP_WORKER = True
    # Cancel all running tasks
    for task in asyncio.all_tasks():
        task.cancel()

signal.signal(signal.SIGINT, handle_exit)

# -------------------------
# Worker loop
# -------------------------
async def main():
    try:
        print("Worker started...\n")
        matches = get_upcoming_matches()
        print_match_summary(matches)
        if not matches:
            return

        first_match_utc = matches[0][2]
        last_match_utc = matches[-1][2]
        first_cycle_time = first_match_utc + timedelta(minutes=45)
        final_cycle_time = last_match_utc + timedelta(hours=2, minutes=15)

        choice = input("Press [Enter] to start now, or type 'wait' to wait until first match+45min: ").strip().lower()
        if choice == "wait":
            await sleep_until(first_cycle_time)

        while not STOP_WORKER:
            matches = get_upcoming_matches()
            if not matches:
                print("No more upcoming matches today. Worker exiting.\n")
                break

            print_match_summary(matches)

            # Run scripts with progress
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TimeRemainingColumn(),
                transient=True
            ) as progress:
                await run_all_scripts_sequential(progress)

            # Schedule clear screen 1 min after update
            asyncio.create_task(clear_screen_after_delay(60))

            now = datetime.now(timezone.utc)
            if now >= last_match_utc:
                # final run 2h15 after last match
                print(f"Last match has started. Sleeping until {final_cycle_time + timedelta(hours=KENYA_OFFSET):%H:%M} Kenya time for final update...\n")
                await sleep_until(final_cycle_time)
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TimeRemainingColumn(),
                    transient=True
                ) as progress:
                    await run_all_scripts_sequential(progress)
                asyncio.create_task(clear_screen_after_delay(60))
                print("Final update done. Worker exiting.\n")
                break

            if not STOP_WORKER:
                print("Sleeping 15 minutes before next update...\n")
                await asyncio.sleep(15*60)

    except asyncio.CancelledError:
        print(f"\n{Fore.RED}[Worker cancelled] Exiting gracefully...{Style.RESET_ALL}")
        return

# -------------------------
# Entry point
# -------------------------
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print(f"\n{Fore.RED}[CTRL+C] Worker terminated immediately.{Style.RESET_ALL}")
