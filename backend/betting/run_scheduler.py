# run_scheduler.py
import logging
import threading
import time
from betting.models import db
from betting.scheduler import start_scheduler
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import os

logging.basicConfig(level=logging.INFO)

# -------------------------
# Database setup
# -------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://henry:kyu@localhost:5432/virtualfootball"
)

engine = create_engine(DATABASE_URL, echo=False, future=True)

# Use a dedicated session for the scheduler
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# -------------------------
# Start scheduler
# -------------------------
stop_event = threading.Event()

def start_standalone_scheduler():
    """
    Starts the scheduler loop using a dedicated SQLAlchemy session,
    completely independent of Flask.
    """
    from types import SimpleNamespace
    fake_app = SimpleNamespace(engine=engine)
    start_scheduler(fake_app, interval_seconds=60, stop_event=stop_event)

scheduler_thread = threading.Thread(target=start_standalone_scheduler, daemon=True)
scheduler_thread.start()

# -------------------------
# Keep main thread alive
# -------------------------
try:
    logging.info("Standalone scheduler started. Press Ctrl+C to stop.")
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logging.info("Stopping scheduler...")
    stop_event.set()
    scheduler_thread.join(timeout=5)
    logging.info("Scheduler stopped gracefully.")
