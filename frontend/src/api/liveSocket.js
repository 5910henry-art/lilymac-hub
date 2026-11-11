/* src/api/liveSocket.js */

import { io } from "socket.io-client";
import { BACKEND_BASE } from "./core.js";

let socket = null;

/*
 * ------------------------------------------------------------
 * CREATE SINGLE LIVE SOCKET CONNECTION
 * ------------------------------------------------------------
 */

function getSocket() {
  if (socket) {
    return socket;
  }

  console.log(
    "[Live Socket] creating connection:",
    BACKEND_BASE
  );

  socket = io(BACKEND_BASE, {
    path: "/socket.io",

    /*
     * Prefer websocket, but allow polling fallback.
     */
    transports: [
      "websocket",
      "polling",
    ],

    autoConnect: true,

    /*
     * Keep reconnecting indefinitely.
     */
    reconnection: true,
    reconnectionAttempts: Infinity,

    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,

    timeout: 10000,

    /*
     * Helps keep the connection alive.
     */
    forceNew: false,
  });

  /*
   * ----------------------------------------------------------
   * CONNECT
   * ----------------------------------------------------------
   */

  socket.on("connect", () => {
    console.log(
      "[Live Socket] connected:",
      socket.id
    );
  });

  /*
   * ----------------------------------------------------------
   * LIVE SNAPSHOT
   * ----------------------------------------------------------
   */

  socket.on(
    "live_snapshot",
    (snapshot) => {
      console.log(
        "[Live Socket] snapshot received:",
        {
          count:
            snapshot?.count,

          matches:
            snapshot?.matches?.length ??
            0,

          socketId:
            socket?.id,

          connected:
            socket?.connected,
        }
      );
    }
  );

  /*
   * ----------------------------------------------------------
   * DISCONNECT
   * ----------------------------------------------------------
   */

  socket.on(
    "disconnect",
    (reason) => {
      console.warn(
        "[Live Socket] disconnected:",
        {
          reason,
          socketId:
            socket?.id,
          connected:
            socket?.connected,
        }
      );

      /*
       * Important:
       *
       * Do NOT manually call connect() here.
       *
       * Socket.IO's reconnection system handles
       * automatic reconnection.
       */
    }
  );

  /*
   * ----------------------------------------------------------
   * CONNECTION ERROR
   * ----------------------------------------------------------
   */

  socket.on(
    "connect_error",
    (error) => {
      console.error(
        "[Live Socket] connection error:",
        {
          message:
            error?.message ||
            String(error),

          description:
            error?.description,

          context:
            error?.context,
        }
      );
    }
  );

  /*
   * ----------------------------------------------------------
   * RECONNECT ATTEMPT
   * ----------------------------------------------------------
   */

  socket.io.on(
    "reconnect_attempt",
    (attempt) => {
      console.log(
        "[Live Socket] reconnect attempt:",
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
        "[Live Socket] reconnected:",
        {
          attempt,
          socketId:
            socket?.id,
        }
      );
    }
  );

  /*
   * ----------------------------------------------------------
   * RECONNECT ERROR
   * ----------------------------------------------------------
   */

  socket.io.on(
    "reconnect_error",
    (error) => {
      console.error(
        "[Live Socket] reconnect error:",
        error?.message ||
          error
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
        "[Live Socket] reconnect failed"
      );
    }
  );

  return socket;
}

/*
 * ------------------------------------------------------------
 * PUBLIC API
 * ------------------------------------------------------------
 */

const LiveSocket = {
  /*
   * ----------------------------------------------------------
   * CONNECT
   * ----------------------------------------------------------
   */

  connect() {
    const s = getSocket();

    if (!s.connected) {
      console.log(
        "[Live Socket] opening connection..."
      );

      s.connect();
    }

    return s;
  },

  /*
   * ----------------------------------------------------------
   * GENERIC EVENT LISTENER
   * ----------------------------------------------------------
   */

  on(eventName, callback) {
    const s = this.connect();

    s.on(
      eventName,
      callback
    );

    return () => {
      if (!socket) {
        return;
      }

      s.off(
        eventName,
        callback
      );
    };
  },

  /*
   * ----------------------------------------------------------
   * LIVE SNAPSHOT LISTENER
   * ----------------------------------------------------------
   */

  onLiveSnapshot(callback) {
    return this.on(
      "live_snapshot",
      callback
    );
  },

  /*
   * ----------------------------------------------------------
   * DISCONNECT
   * ----------------------------------------------------------
   *
   * Intentionally kept as a controlled operation.
   *
   * Normal component cleanup should NOT call this.
   */

  disconnect() {
    if (!socket) {
      return;
    }

    console.warn(
      "[Live Socket] explicit manual disconnect"
    );

    socket.disconnect();

    /*
     * Do not destroy the singleton reference.
     *
     * This allows connect() to reuse the same
     * Socket.IO instance if needed.
     */
  },

  /*
   * ----------------------------------------------------------
   * CONNECTION STATUS
   * ----------------------------------------------------------
   */

  isConnected() {
    return Boolean(
      socket?.connected
    );
  },

  /*
   * ----------------------------------------------------------
   * SOCKET ID
   * ----------------------------------------------------------
   */

  getSocketId() {
    return socket?.id ?? null;
  },

  /*
   * ----------------------------------------------------------
   * UNDERLYING SOCKET
   * ----------------------------------------------------------
   */

  getSocket() {
    return socket;
  },
};

export default LiveSocket;
