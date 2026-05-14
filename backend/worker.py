#!/usr/bin/env python3
"""
One-shot Async Worker with Countdown Clear
- Runs a list of scripts sequentially once
- Shows progress using rich
- Displays a 30-second countdown before clearing the screen
- Exits after clearing
"""

import asyncio
import asyncio.subprocess
import os
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn

# -------------------------
# Scripts to run in order
# -------------------------
SCRIPTS = [
    "fecha2.py",
    "Goals.py",
    "build_features.py",
    "odds.py"
]

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
    stdout, stderr = await process.communicate()
    retcode = process.returncode
    if stdout:
        progress.console.print(stdout.decode(), style="green")
    if stderr:
        progress.console.print(f"Warning ({script}): {stderr.decode()}", style="red")
    status_text = "[green]Done" if retcode == 0 else "[red]Failed"
    progress.update(task_id, description=f"{script}: {status_text}", completed=1)
    return retcode

# -------------------------
# Run all scripts sequentially
# -------------------------
async def run_all_scripts():
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeRemainingColumn(),
        transient=True
    ) as progress:
        for script in SCRIPTS:
            task_id = progress.add_task(f"{script}: pending", total=1)
            await run_script(script, progress, task_id)

# -------------------------
# Countdown clear screen
# -------------------------
async def countdown_clear(seconds=30):
    for i in range(seconds, 0, -1):
        print(f"\rClearing screen in {i} seconds...", end="", flush=True)
        await asyncio.sleep(1)
    os.system("clear")
    print("Screen cleared. Worker exiting.")

# -------------------------
# Entry
# -------------------------
async def main():
    print("One-shot worker started...\n")
    await run_all_scripts()
    print("\n✅ All scripts finished.")
    await countdown_clear(30)

if __name__ == "__main__":
    asyncio.run(main())
