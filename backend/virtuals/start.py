import os

from virtuals.virtual import (
    app,
    socketio,
    emit_fixture_update,
)

from virtuals.engine import (
    start_virtual_engine,
    stop_engine,
)


def main():

    host = "0.0.0.0"
    port = int(
        os.environ.get(
            "PORT",
            "5002",
        )
    )

    print(
        f"🚀 Virtual Socket.IO service "
        f"starting on {host}:{port}"
    )

    start_virtual_engine(
        emit_update_callback=emit_fixture_update
    )

    try:

        socketio.run(
            app,
            host=host,
            port=port,
            debug=False,
            allow_unsafe_werkzeug=True,
        )

    except Exception:

        raise

    finally:

        print(
            "🛑 Virtual service shutting down..."
        )

        stop_engine()


if __name__ == "__main__":
    main()
