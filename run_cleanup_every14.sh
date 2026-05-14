#!/bin/bash
# run_cleanup_every14.sh - runs cleanup.sql every 14 days on Termux with notifications

PGUSER="henry"
PGDATABASE="virtualfootball"
PSQL="/data/data/com.termux/files/usr/bin/psql"
SCRIPT_PATH="/data/data/com.termux/files/home/lilymac-hub/cleanup.sql"
LOG_PATH="/data/data/com.termux/files/home/lilymac-hub/cleanup.log"
LAST_RUN_FILE="/data/data/com.termux/files/home/lilymac-hub/.cleanup_last_run"

# Get last run timestamp
LAST_RUN=0
[ -f "$LAST_RUN_FILE" ] && LAST_RUN=$(cat "$LAST_RUN_FILE")

NOW=$(date +%s)
INTERVAL=$((14*24*60*60))

if (( NOW - LAST_RUN >= INTERVAL )); then
    echo "[$(date)] Running cleanup..." >> "$LOG_PATH"

    termux-notification \
        --title "Cleanup Started" \
        --content "Running database cleanup..." \
        --priority high

    $PSQL -U "$PGUSER" -d "$PGDATABASE" -f "$SCRIPT_PATH" >> "$LOG_PATH" 2>&1

    if [ $? -eq 0 ]; then
        echo "[$(date)] Cleanup finished successfully." >> "$LOG_PATH"
        echo $NOW > "$LAST_RUN_FILE"

        termux-notification \
            --title "Cleanup Success ✅" \
            --content "Database cleanup completed successfully." \
            --priority high
    else
        echo "[$(date)] Cleanup encountered errors." >> "$LOG_PATH"

        termux-notification \
            --title "Cleanup Failed ❌" \
            --content "Database cleanup encountered errors. Check logs." \
            --priority high
    fi
else
    REMAIN_DAYS=$(( (INTERVAL - (NOW - LAST_RUN)) / 86400 ))
    REMAIN_HOURS=$(( ((INTERVAL - (NOW - LAST_RUN)) % 86400) / 3600 ))

    echo "[$(date)] Cleanup skipped. Next run in $REMAIN_DAYS days and $REMAIN_HOURS hours." >> "$LOG_PATH"
fi
