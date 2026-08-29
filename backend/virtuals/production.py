import logging

from virtuals.virtual import app, emit_fixture_update
from virtuals.engine import start_virtual_engine

logging.basicConfig(level=logging.INFO)

# Start the engine and explicitly connect its Socket.IO callback.
start_virtual_engine(
    emit_update_callback=emit_fixture_update
)

application = app
