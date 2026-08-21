#!/usr/bin/env python3
"""
One-shot Async Worker with Countdown Clear
- Runs a list of scripts sequentially once
- Shows progress using rich
- Displays a 30-second countdown before clearing the screen
- Exits after clearing
"""

import asyncio
import os
from pathlib import Path
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
)

# -------------------------
# Base directory
# -------------------------
BASE_DIR = Path(__file__).resolve().parent

# -------------------------
# Scripts to run in order
# -------------------------
SCRIPTS = [
    BASE_DIR / "fetchers" / "fecha.py",
    BASE_DIR / "goals.py",
    BASE_DIR / "build_features.py",
    BASE_DIR / "odds.py",
]

# -------------------------
# Run a single script sequentially
# -------------------------
async def run_script(script, progress, task_id):
    script = Path(script)

    progress.update(
        task_id,
        description=f"[yellow]Running {script.name}..."
    )

    if not script.exists():
        progress.console.print(
            f"Warning: {script} does not exist",
            style="red"
        )
        progress.update(
            task_id,
            description=f"{script.name}: [red]Failed",
            completed=1
        )
        return 1

    process = await asyncio.create_subprocess_exec(
        "python3",
        str(script),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(BASE_DIR),
    )

    stdout, stderr = await process.communicate()

    retcode = process.returncode

    if stdout:
        progress.console.print(
            stdout.decode(errors="replace"),
            style="green"
        )

    if stderr:
        progress.console.print(
            f"Warning ({script.name}): {stderr.decode(errors='replace')}",
            style="red"
        )

    status_text = "[green]Done" if retcode == 0 else "[red]Failed"

    progress.update(
        task_id,
        description=f"{script.name}: {status_text}",
        completed=1
    )

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
        transient=True,
    ) as progress:

        for script in SCRIPTS:
            task_id = progress.add_task(
                f"{Path(script).name}: pending",
                total=1
            )

            retcode = await run_script(
                script,
                progress,
                task_id
            )

            # Stop if a script fails
            if retcode != 0:
                progress.console.print(
                    f"\n❌ {Path(script).name} failed. "
                    "Stopping worker.",
                    style="red"
                )
                return False

    return True


# -------------------------
# Countdown clear screen
# -------------------------
async def countdown_clear(seconds=30):
    for i in range(seconds, 0, -1):
        print(
            f"\rClearing screen in {i} seconds...",
            end="",
            flush=True
        )
        await asyncio.sleep(1)

    os.system("clear")
    print("Screen cleared. Worker exiting.")


# -------------------------
# Entry
# -------------------------
async def main():
    print("One-shot worker started...\n")

    success = await run_all_scripts()

    if success:
        print("\n✅ All scripts finished.")
    else:
        print("\n❌ Worker stopped because a script failed.")

    await countdown_clear(30)


if __name__ == "__main__":
    asyncio.run(main())
