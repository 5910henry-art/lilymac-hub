import { io } from "socket.io-client";

const SOCKET_URL = "http://127.0.0.1:5002"; 
// ⚠️ change to your phone IP if testing from another device

export const socket = io(SOCKET_URL + "/live", {
  transports: ["websocket"],
  reconnection: true,
});
