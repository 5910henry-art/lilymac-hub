import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from "react";

import { getLiveMatches } from "../api/domain";
import LiveSocket from "../api/liveSocket";

const LiveContext = createContext(null);

const LIVE_STATUSES = new Set([
  "IN_PLAY",
  "PAUSED",
  "LIVE",
]);

function normalizeMatch(match) {
  return {
    ...match,

    match_id:
      match?.match_id ??
      match?.id,

    home_team_name:
      match?.home_team_name ??
      match?.home_team ??
      "",

    away_team_name:
      match?.away_team_name ??
      match?.away_team ??
      "",

    home_score:
      match?.home_score ?? 0,

    away_score:
      match?.away_score ?? 0,

    status: String(
      match?.status ?? ""
    )
      .trim()
      .toUpperCase(),
  };
}

function normalizeMatches(snapshot) {
  const matches =
    Array.isArray(snapshot)
      ? snapshot
      : Array.isArray(snapshot?.matches)
        ? snapshot.matches
        : Array.isArray(snapshot?.data?.matches)
          ? snapshot.data.matches
          : [];

  return matches
    .map(normalizeMatch)
    .filter((match) =>
      LIVE_STATUSES.has(match.status)
    );
}

export function LiveProvider({ children }) {
  const [matches, setMatches] = useState([]);
  const [connected, setConnected] = useState(false);

  /*
   * ==========================================================
   * INITIAL / MANUAL REST LOAD
   * ==========================================================
   *
   * REST is NOT polled continuously.
   *
   * It is used:
   *   1. On initial page load
   *   2. When the user manually refreshes
   *
   * Socket.IO handles live updates afterward.
   */
  const loadLiveMatches = useCallback(async () => {
    try {
      console.log(
        "[LiveContext] Loading live matches from REST..."
      );

      const response = await getLiveMatches();

      const apiMatches =
        normalizeMatches(response);

      console.log(
        "[LiveContext] REST LIVE MATCHES:",
        {
          raw: response,
          count: apiMatches.length,
          matches: apiMatches,
        }
      );

      setMatches((currentMatches) => {
        console.log(
          "[LiveContext] REST STATE UPDATE:",
          {
            previousCount: currentMatches.length,
            nextCount: apiMatches.length,
          }
        );

        return apiMatches;
      });

      setConnected(
        LiveSocket.isConnected()
      );

      return apiMatches;
    } catch (err) {
      console.error(
        "[LiveContext] API load failed:",
        err
      );

      return [];
    }
  }, []);

  useEffect(() => {
    let alive = true;

    /*
     * ========================================================
     * INITIAL REST LOAD
     * ========================================================
     */
    loadLiveMatches();

    /*
     * ========================================================
     * SOCKET.IO LIVE SNAPSHOTS
     * ========================================================
     */
    const unsubscribe =
      LiveSocket.onLiveSnapshot(
        (snapshot) => {
          if (!alive) {
            return;
          }

          const liveMatches =
            normalizeMatches(snapshot);

          /*
           * Detailed diagnostic information.
           */
          console.log(
            "[LiveContext] SOCKET SNAPSHOT:",
            {
              raw: snapshot,
              normalizedCount:
                liveMatches.length,
              normalizedMatches:
                liveMatches,
              socketConnected:
                LiveSocket.isConnected(),
            }
          );

          /*
           * Show statuses received BEFORE filtering.
           */
          const rawMatches =
            Array.isArray(snapshot)
              ? snapshot
              : Array.isArray(snapshot?.matches)
                ? snapshot.matches
                : Array.isArray(
                    snapshot?.data?.matches
                  )
                  ? snapshot.data.matches
                  : [];

          console.log(
            "[LiveContext] SOCKET RAW STATUSES:",
            rawMatches.map((match) => ({
              match_id:
                match?.match_id ??
                match?.id,

              status:
                match?.status,

              home:
                match?.home_team_name ??
                match?.home_team,

              away:
                match?.away_team_name ??
                match?.away_team,
            }))
          );

          /*
           * ====================================================
           * SOCKET IS THE LIVE SOURCE
           * ====================================================
           */
          setMatches((currentMatches) => {
            console.log(
              "[LiveContext] SOCKET STATE UPDATE:",
              {
                previousCount:
                  currentMatches.length,

                nextCount:
                  liveMatches.length,

                previousMatches:
                  currentMatches,

                nextMatches:
                  liveMatches,
              }
            );

            return liveMatches;
          });

          setConnected(
            LiveSocket.isConnected()
          );
        }
      );

    /*
     * ========================================================
     * INITIAL CONNECTION STATE
     * ========================================================
     */
    setConnected(
      LiveSocket.isConnected()
    );

    /*
     * ========================================================
     * CLEANUP
     * ========================================================
     */
    return () => {
      alive = false;

      unsubscribe?.();

      console.log(
        "[LiveContext] Provider cleanup"
      );
    };
  }, [loadLiveMatches]);

  const value = {
    matches,
    liveCount: matches.length,
    connected,
    refresh: loadLiveMatches,
  };

  return (
    <LiveContext.Provider value={value}>
      {children}
    </LiveContext.Provider>
  );
}

export function useLive() {
  const context =
    useContext(LiveContext);

  if (!context) {
    throw new Error(
      "useLive must be used inside LiveProvider"
    );
  }

  return context;
}
