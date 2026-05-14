// src/api/virtualAPI.js
// Updated version: supports single and multi-bets, safe payloads, polling helpers

import { getAuthToken } from "./core.js";

const BASE_URL = "http://127.0.0.1:5000/virtual";

/* ---------------- GENERIC REQUEST ---------------- */
async function request(path, { method = "GET", body = null, useAuth = true, signal } = {}) {
  const headers = { Accept: "application/json" };               
  if (body !== null) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }

  const token = getAuthToken?.();
  if (useAuth && token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let res;                                                        try {
    res = await fetch(`${BASE_URL}${path}`, { method, headers, body, signal });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new Error(`Network error: ${err.message}`);
  }

  const text = await res.text();

  if (!res.ok) {
    const snippet = text ? text.substring(0, 1000) : "<empty>";
    throw new Error(`API ${res.status} ${res.statusText}: ${snippet}`);
  }

  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/* ---------------- POLLING HELPER ---------------- */
function poll(fn, intervalMs = 1000, callback) {
  let active = true, running = false;

  const execute = async () => {
    if (!active || running) return;
    running = true;
    try {
      const result = await fn();
      callback?.(result);
    } catch (err) {
      console.error("Polling error:", err);
    } finally {
      running = false;
    }
  };

  execute();
  const id = setInterval(execute, intervalMs);

  return () => {
    active = false;
    clearInterval(id);
  };
}

/* ---------------- VIRTUAL API ---------------- */
const VirtualAPI = {

  // BASIC ENDPOINTS
  getHome: () => request("/"),
  getMatches: () => request("/matches"),
  getMatch: (matchId) => request(`/match/${matchId}`),
  getUpcoming: () => request("/upcoming"),
  getRounds: () => request("/rounds"),
  getRoundMatches: (roundId) => request(`/round/${roundId}`),
  getAllRoundsMatches: () => request("/all-rounds-matches"),
  getFinished: () => request("/finished"),
  getLive: () => request("/live"),
  getLeagueTable: () => request("/table"),
  getEvents: (matchId) => request(`/events/${matchId}`),
  getOdds: (matchId) => request(`/odds/${matchId}`),
  getMyBets: () => request("/bets"),

  // SINGLE BET (legacy)
  placeSingleBet: (matchId, selection, stake) =>
    request("/bet", {
      method: "POST",
      body: { match_id: matchId, selection, stake },
    }),

  // MULTI-BET / FLEXIBLE BET
  placeBet: (payload) =>
    request("/bet", {
      method: "POST",
      body: payload, // payload can be {match_id, selection, stake} or {stake, selections:[...]}
    }),

  // POLLING HELPERS
  poll: (fn, interval = 1000, callback) => poll(fn, interval, callback),
  liveMatches: (callback, interval = 1000) => poll(() => VirtualAPI.getMatches(), interval, callback),
  liveUpcoming: (callback, interval = 5000) => poll(() => VirtualAPI.getUpcoming(), interval, callback),
  liveRounds: (callback, interval = 5000) => poll(() => VirtualAPI.getRounds(), interval, callback),
  liveRoundMatches: (roundId, callback, interval = 2000) => poll(() => VirtualAPI.getRoundMatches(roundId), interval, callback),
  liveEvents: (matchId, callback, interval = 1500) => poll(() => VirtualAPI.getEvents(matchId), interval, callback),
  liveBets: (callback, interval = 2000) => poll(() => VirtualAPI.getMyBets(), interval, callback),
  liveFinished: (callback, interval = 3000) => poll(() => VirtualAPI.getFinished(), interval, callback),
  liveLeagueTable: (callback, interval = 5000) => poll(() => VirtualAPI.getLeagueTable(), interval, callback),
};

export default VirtualAPI;
