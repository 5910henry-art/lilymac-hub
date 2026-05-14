#!/data/data/com.termux/files/usr/bin/python3
# daily_season_cleanup.py
import sys
import os
from datetime import datetime
import pytz
import logging

# ------------------ PATH SETUP ------------------
# Add backend folder to PYTHONPATH so virtuals package is found
sys.path.insert(0, os.path.expanduser("~/lilymac-hub/backend"))

# ------------------ IMPORTS ------------------
from virtuals.config import app, db, logger as config_logger
from virtuals.season import generate_full_season
from sqlalchemy import text

# ------------------ LOGGING ------------------
LOG_FILE = os.path.expanduser("~/lilymac-hub/cleanup.log")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("daily-cleanup")

# ------------------ TIME HELPERS ------------------
def now_local():
    """Current time in Africa/Nairobi timezone."""
    tz = pytz.timezone("Africa/Nairobi")
    return datetime.now(tz)

def is_3am():
    """Return True if current time is 3 AM."""
    return now_local().hour == 3

# ------------------ CLEANUP ------------------
def run_cleanup():
    logger.info("Running daily season cleanup...")

    if not is_3am():
        logger.info("Not 3 AM yet. Cleanup skipped.")
        return

    with app.app_context():
        try:
            logger.info("🌙 3 AM detected — clearing old fixtures and virtual tables...")

            # Clear only virtual season tables (fixtures, virtual bets, events, odds)
            TABLES_TO_CLEAR = ["virtual_fixtures", "virtual_vbets", "virtual_events", "virtual_odds"]
            for tbl in TABLES_TO_CLEAR:
                db.session.execute(text(f"DELETE FROM {tbl}"))
            db.session.commit()

            logger.info("✅ Virtual tables cleared successfully.")

            # Generate new season
            generate_full_season()
            logger.info("🎉 New season generated successfully.")

        except Exception as e:
            logger.exception("Error during daily season cleanup: %s", e)
            db.session.rollback()

# ------------------ MAIN ------------------
if __name__ == "__main__":
    run_cleanup()
