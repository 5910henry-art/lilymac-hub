// src/api/virtualSocket.js

import { io } from "socket.io-client";
import { BACKEND_VIRTUAL } from "./core.js";

let socket = null;

/*
 * ------------------------------------------------------------
 * CREATE SINGLE SOCKET CONNECTION
 * ------------------------------------------------------------
 */

function getSocket() {
  if (socket) {
    return socket;
  }

  console.log(
    "[Virtual Socket] connecting to:",
    BACKEND_VIRTUAL
  );

  socket = io(BACKEND_VIRTUAL, {
    path: "/socket.io",

    // Prefer WebSocket, with polling as fallback.
    transports: ["websocket", "polling"],

    autoConnect: true,

    reconnection: true,
    reconnectionAttempts: Infinity,

    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,

    timeout: 10000,
  });

  /*
   * ----------------------------------------------------------
   * CONNECT
   * ----------------------------------------------------------
   */

  socket.on("connect", () => {
    console.log(
      "[Virtual Socket] connected:",
      socket.id
    );

    // Automatically join the virtual lobby.
    socket.emit(
      "join_virtual_lobby",
      (response) => {
        console.log(
          "[Virtual Socket] lobby joined:",
          response
        );
      }
    );
  });

  /*
   * ----------------------------------------------------------
   * DISCONNECT
   * ----------------------------------------------------------
   */

  socket.on("disconnect", (reason) => {
    console.warn(
      "[Virtual Socket] disconnected:",
      reason
    );
  });

  /*
   * ----------------------------------------------------------
   * CONNECTION ERROR
   * ----------------------------------------------------------
   */

  socket.on("connect_error", (error) => {
    console.error(
      "[Virtual Socket] connection error:",
      error?.message || error
    );
  });

  /*
   * ----------------------------------------------------------
   * RECONNECT ATTEMPT
   * ----------------------------------------------------------
   */

  socket.io.on(
    "reconnect_attempt",
    (attempt) => {
      console.log(
        "[Virtual Socket] reconnect attempt:",
        attempt
      );
    }
  );

  /*
   * ----------------------------------------------------------
   * RECONNECTED
   * ----------------------------------------------------------
   */

  socket.io.on(
    "reconnect",
    (attempt) => {
      console.log(
        "[Virtual Socket] reconnected after attempt:",
        attempt,
        "socket:",
        socket.id
      );
    }
  );

  /*
   * ----------------------------------------------------------
   * RECONNECT FAILED
   * ----------------------------------------------------------
   */

  socket.io.on(
    "reconnect_failed",
    () => {
      console.error(
        "[Virtual Socket] reconnection failed"
      );
    }
  );

  return socket;
}

/*
 * ------------------------------------------------------------
 * PUBLIC SOCKET API
 * ------------------------------------------------------------
 */

const VirtualSocket = {
  /*
   * Connect and return the singleton socket.
   */
  connect() {
    const s = getSocket();

    if (!s.connected) {
      s.connect();
    }

    return s;
  },

  /*
   * Completely disconnect and destroy the socket.
   */
  disconnect() {
    if (!socket) {
      return;
    }

    console.log(
      "[Virtual Socket] manual disconnect"
    );

    socket.removeAllListeners();
    socket.disconnect();

    socket = null;
  },

  /*
   * Join the virtual lobby.
   *
   * The socket normally joins automatically after connect.
   * This method is kept for compatibility.
   */
  joinLobby() {
    const s = this.connect();

    return new Promise((resolve) => {
      if (s.connected) {
        s.emit(
          "join_virtual_lobby",
          (response) => {
            console.log(
              "[Virtual Socket] lobby joined manually:",
              response
            );

            resolve(response);
          }
        );

        return;
      }

      const handleConnect = () => {
        s.off(
          "connect",
          handleConnect
        );

        s.emit(
          "join_virtual_lobby",
          (response) => {
            console.log(
              "[Virtual Socket] lobby joined:",
              response
            );

            resolve(response);
          }
        );
      };

      s.once(
        "connect",
        handleConnect
      );
    });
  },

  /*
   * Leave the virtual lobby.
   */
  leaveLobby() {
    if (
      !socket ||
      !socket.connected
    ) {
      return;
    }

    socket.emit(
      "leave_virtual_lobby"
    );

    console.log(
      "[Virtual Socket] left virtual lobby"
    );
  },

  /*
   * Join an individual match room.
   */
  joinMatch(matchId) {
    const s = this.connect();

    return new Promise((resolve) => {
      const payload = {
        match_id: matchId,
      };

      if (s.connected) {
        s.emit(
          "join_virtual_match",
          payload,
          (response) => {
            resolve(response);
          }
        );

        return;
      }

      const handleConnect = () => {
        s.off(
          "connect",
          handleConnect
        );

        s.emit(
          "join_virtual_match",
          payload,
          (response) => {
            resolve(response);
          }
        );
      };

      s.once(
        "connect",
        handleConnect
      );
    });
  },

  /*
   * Leave an individual match room.
   */
  leaveMatch(matchId) {
    if (
      !socket ||
      !socket.connected
    ) {
      return;
    }

    socket.emit(
      "leave_virtual_match",
      {
        match_id: matchId,
      }
    );
  },

  /*
   * Subscribe to a Socket.IO event.
   *
   * Returns a cleanup function.
   */
  on(eventName, callback) {
    const s = getSocket();

    s.on(
      eventName,
      callback
    );

    return () => {
      s.off(
        eventName,
        callback
      );
    };
  },

  /*
   * Check connection status.
   */
  isConnected() {
    return Boolean(
      socket?.connected
    );
  },

  /*
   * Access the underlying socket for debugging.
   */
  getSocket() {
    return socket;
  },
};

export default VirtualSocket;
