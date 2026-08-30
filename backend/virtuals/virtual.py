# virtuals/virtual.py

import logging
import os
import signal

from flask_cors import CORS

from .config import app, init_app, db, socketio
from .routes import bp as routes_bp
from .engine import start_virtual_engine, stop_engine

logger = logging.getLogger("virtual-engine")


# --------------------------------------------------
# INITIALIZATION
# --------------------------------------------------

init_app()

CORS(
    app,
    resources={r"/*": {"origins": "*"}},
)

app.register_blueprint(routes_bp)


# --------------------------------------------------
# SOCKET.IO CONNECTION EVENTS
# --------------------------------------------------

@socketio.on("connect")
def handle_connect():
    logger.info("🔌 Virtual client connected")


@socketio.on("disconnect")
def handle_disconnect():
    logger.info("🔌 Virtual client disconnected")


# --------------------------------------------------
# SOCKET.IO MATCH ROOMS
# --------------------------------------------------

@socketio.on("join_virtual_match")
def handle_join_virtual_match(data):
    """
    Join a room for one specific virtual match.
    """

    from flask_socketio import join_room

    try:
        match_id = int(data.get("match_id"))
    except (TypeError, ValueError, AttributeError):
        logger.warning(
            "Invalid virtual match room request: %s",
            data,
        )
        return {
            "success": False,
            "error": "Invalid match_id",
        }

    room = f"virtual:match:{match_id}"

    join_room(room)

    logger.info(
        "Client joined virtual match room %s",
        room,
    )

    return {
        "success": True,
        "match_id": match_id,
        "room": room,
    }


@socketio.on("leave_virtual_match")
def handle_leave_virtual_match(data):
    """
    Leave a room for one specific virtual match.
    """

    from flask_socketio import leave_room

    try:
        match_id = int(data.get("match_id"))
    except (TypeError, ValueError, AttributeError):
        return {
            "success": False,
            "error": "Invalid match_id",
        }

    room = f"virtual:match:{match_id}"

    leave_room(room)

    return {
        "success": True,
        "match_id": match_id,
        "room": room,
    }


@socketio.on("join_virtual_lobby")
def handle_join_virtual_lobby():
    """
    Join the global virtual sportsbook lobby.
    """

    from flask_socketio import join_room

    room = "virtual:lobby"

    join_room(room)

    logger.info(
        "Client joined virtual lobby"
    )

    return {
        "success": True,
        "room": room,
    }


@socketio.on("leave_virtual_lobby")
def handle_leave_virtual_lobby():
    """
    Leave the global virtual sportsbook lobby.
    """

    from flask_socketio import leave_room

    room = "virtual:lobby"

    leave_room(room)

    return {
        "success": True,
        "room": room,
    }


# --------------------------------------------------
# MATCH UPDATE CALLBACK
# --------------------------------------------------

def emit_fixture_update(fixture, event=None):
    """
    Broadcast a live virtual fixture update.

    This callback is called by the simulation engine after
    events/score changes.

    Two destinations are used:

    1. virtual:lobby
       -> users viewing the virtual sportsbook

    2. virtual:match:<id>
       -> users watching this specific match
    """
    logger.info(
        "📡 EMIT FIXTURE UPDATE | match=%s | status=%s | event=%s",
        getattr(fixture, "id", None),
        getattr(fixture, "status", None),
        getattr(event, "type", None) if event else None,
    )
    if fixture is None:
        return

    try:

        match_id = int(fixture.id)

        payload = {
            "match_id": match_id,

            "home": fixture.home,
            "away": fixture.away,

            "home_score": int(
                fixture.home_score or 0
            ),

            "away_score": int(
                fixture.away_score or 0
            ),

            "status": fixture.status,

            "event_count": int(
                fixture.event_count or 0
            ),

            "round": fixture.round,
            "season": fixture.season,

            "open_time": (
                fixture.open_time.isoformat()
                if fixture.open_time
                else None
            ),

            "start_time": (
                fixture.start_time.isoformat()
                if fixture.start_time
                else None
            ),

            "end_time": (
                fixture.end_time.isoformat()
                if fixture.end_time
                else None
            ),
        }

        # ------------------------------------------
        # Attach event information if available
        # ------------------------------------------

        if event is not None:

            payload["event"] = {
                "id": getattr(event, "id", None),
                "match_id": match_id,
                "minute": getattr(event, "minute", None),
                "team": getattr(event, "team", None),
                "type": getattr(event, "type", None),
                "description": getattr(
                    event,
                    "description",
                    None,
                ),
                "created_at": (
                    event.created_at.isoformat()
                    if getattr(event, "created_at", None)
                    else None
                ),
            }

        # ------------------------------------------
        # Broadcast general match update
        # ------------------------------------------

        socketio.emit(
            "virtual_match_update",
            payload,
            room="virtual:lobby",
        )

        # ------------------------------------------
        # Broadcast to match viewers
        # ------------------------------------------

        socketio.emit(
            "virtual_match_update",
            payload,
            room=f"virtual:match:{match_id}",
        )

        # ------------------------------------------
        # Specialized event
        # ------------------------------------------

        if event is not None:

            socketio.emit(
                "virtual_match_event",
                payload,
                room=f"virtual:match:{match_id}",
            )

            socketio.emit(
                "virtual_match_event",
                payload,
                room="virtual:lobby",
            )

        # ------------------------------------------
        # Specialized finish event
        # ------------------------------------------

        if fixture.status == "FINISHED":

            socketio.emit(
                "virtual_match_finished",
                payload,
                room=f"virtual:match:{match_id}",
            )

            socketio.emit(
                "virtual_match_finished",
                payload,
                room="virtual:lobby",
            )

    except Exception:
        logger.exception(
            "Failed broadcasting fixture update"
        )


# --------------------------------------------------
# SIGNAL HANDLER
# --------------------------------------------------

def _signal_handler(signum, frame):

    logger.info(
        "Received shutdown signal (%s). "
        "Stopping engine...",
        signum,
    )

    stop_engine()

    logger.info(
        "Shutdown complete"
    )


# --------------------------------------------------
# MAIN
# --------------------------------------------------

if __name__ == "__main__":

    signal.signal(
        signal.SIGINT,
        _signal_handler,
    )

    signal.signal(
        signal.SIGTERM,
        _signal_handler,
    )

    logger.info(
        "⚽ Virtual PRO+ Engine starting..."
    )

    # IMPORTANT:
    # Pass the Socket.IO callback to the engine.
    start_virtual_engine(
        emit_update_callback=emit_fixture_update
    )

    host = os.getenv(
        "HOST",
        "0.0.0.0",
    )

    port = int(
        os.getenv(
            "PORT",
            5002,
        )
    )

    logger.info(
        "🚀 Starting Socket.IO server on %s:%s",
        host,
        port,
    )

    try:

        # IMPORTANT:
        # Use socketio.run(), NOT app.run().
        socketio.run(
            app,
            host=host,
            port=port,
            debug=False,
            allow_unsafe_werkzeug=True,
        )

    except Exception:

        logger.exception(
            "Exception while running Socket.IO server"
        )

    finally:

        logger.info(
            "🛑 Server shutting down, "
            "stopping virtual engine..."
        )

        stop_engine()

        logger.info(
            "✅ Server shut down cleanly."
        )
