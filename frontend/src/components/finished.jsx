// src/components/finished.jsx

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import VirtualAPI from "../api/virtualAPI";

const MAX_ROUNDS = 15;
const REFRESH_INTERVAL = 5000;
const MATCHES_PER_ROUND = 10;

export default function FinishedMatches() {
  const [matches, setMatches] = useState([]);
  const [backendRounds, setBackendRounds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState(null);
  const [expandedRounds, setExpandedRounds] = useState({});

  // ============================================================
  // LOAD RESULTS + ROUNDS
  // ============================================================

  const loadResults = useCallback(async () => {
    try {
      const [finishedResponse, roundsResponse] =
        await Promise.all([
          VirtualAPI.getFinished(),
          VirtualAPI.getRounds(),
        ]);

      const finishedData = Array.isArray(
        finishedResponse
      )
        ? finishedResponse
        : Array.isArray(
            finishedResponse?.matches
          )
          ? finishedResponse.matches
          : [];

      const roundsData = Array.isArray(
        roundsResponse
      )
        ? roundsResponse
        : Array.isArray(
            roundsResponse?.rounds
          )
          ? roundsResponse.rounds
          : [];

      setMatches((previous) => {
        if (
          JSON.stringify(previous) ===
          JSON.stringify(finishedData)
        ) {
          return previous;
        }

        return finishedData;
      });

      setBackendRounds(roundsData);
      setError(null);
    } catch (err) {
      console.error(
        "Failed loading finished results:",
        err
      );

      setError(
        "Unable to load results."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  // ============================================================
  // INITIAL LOAD + AUTO REFRESH
  // ============================================================

  useEffect(() => {
    loadResults();

    const timer = setInterval(
      loadResults,
      REFRESH_INTERVAL
    );

    return () => {
      clearInterval(timer);
    };
  }, [loadResults]);

  // ============================================================
  // FILTER
  // ============================================================

  const filteredMatches = useMemo(() => {
    const search =
      filter.trim().toLowerCase();

    if (!search) {
      return matches;
    }

    return matches.filter((match) => {
      const home = String(
        match?.home || ""
      ).toLowerCase();

      const away = String(
        match?.away || ""
      ).toLowerCase();

      return (
        home.includes(search) ||
        away.includes(search)
      );
    });
  }, [matches, filter]);

  // ============================================================
  // GET MATCH ID
  // ============================================================

  const getMatchId = useCallback(
    (match) => {
      const id = Number(match?.id);

      return Number.isFinite(id)
        ? id
        : null;
    },
    []
  );

  // ============================================================
  // DETERMINE LATEST FINISHED ROUND
  // ============================================================

  const latestFinishedRound = useMemo(() => {
    if (!matches.length) {
      return null;
    }

    /*
     * Find the highest match ID.
     */
    const highestMatchId =
      Math.max(
        ...matches
          .map((match) =>
            getMatchId(match)
          )
          .filter((id) => id !== null)
      );

    if (
      !Number.isFinite(
        highestMatchId
      )
    ) {
      return null;
    }

    /*
     * The current scheduled round is the
     * first round returned by /rounds.
     */
    const currentRound =
      backendRounds
        .map((round) =>
          Number(
            round?.round ??
              round?.id
          )
        )
        .filter((round) =>
          Number.isFinite(round)
        )
        .sort(
          (a, b) => b - a
        )[0];

    if (
      !Number.isFinite(
        currentRound
      )
    ) {
      return null;
    }

    /*
     * Determine which 10-match block the
     * highest finished match belongs to.
     *
     * Example:
     *
     * 2221-2230 = one round
     * 2211-2220 = previous round
     * 2201-2210 = previous round
     */
    const highestBlock =
      Math.floor(
        highestMatchId /
          MATCHES_PER_ROUND
      );

    /*
     * Determine the block occupied by
     * the first match of the current round.
     *
     * If current round 34 is next and
     * 2221-2230 was the latest finished
     * block, then latest finished is
     * Round 33.
     */
    const latestFinished =
      currentRound -
      1;

    return {
      round:
        latestFinished,
      matchBlock:
        highestBlock,
    };
  }, [
    backendRounds,
    getMatchId,
    matches,
  ]);

  // ============================================================
  // GROUP MATCHES INTO ACTUAL ROUNDS
  // ============================================================

  const rounds = useMemo(() => {
    if (!filteredMatches.length) {
      return [];
    }

    /*
     * Sort all matches by ID.
     */
    const sorted = [
      ...filteredMatches,
    ].sort(
      (a, b) =>
        Number(a?.id || 0) -
        Number(b?.id || 0)
    );

    /*
     * If we know the latest finished round,
     * use it as the anchor.
     */
    let latestRound =
      latestFinishedRound?.round;

    /*
     * Fallback:
     * if /rounds is unavailable, determine
     * rounds purely from 10-match blocks.
     */
    if (
      !Number.isFinite(
        latestRound
      )
    ) {
      latestRound = 1;
    }

    const highestId =
      Number(
        sorted[
          sorted.length - 1
        ]?.id
      );

    const highestBlock =
      Math.floor(
        highestId /
          MATCHES_PER_ROUND
      );

    const grouped = new Map();

    sorted.forEach((match) => {
      const id = Number(
        match?.id
      );

      if (
        !Number.isFinite(id)
      ) {
        return;
      }

      const block =
        Math.floor(
          id /
            MATCHES_PER_ROUND
        );

      /*
       * Difference between the latest block
       * and this match's block.
       */
      const blockDifference =
        highestBlock - block;

      const roundNumber =
        latestRound -
        blockDifference;

      if (
        !Number.isFinite(
          roundNumber
        ) ||
        roundNumber <= 0
      ) {
        return;
      }

      const key =
        `round-${roundNumber}`;

      if (!grouped.has(key)) {
        grouped.set(key, {
          key,
          round:
            roundNumber,
          matches: [],
          latestTime:
            new Date(0),
        });
      }

      const group =
        grouped.get(key);

      group.matches.push(match);

      const timeValue =
        match?.end_time ||
        match?.start_time;

      if (timeValue) {
        const date =
          new Date(timeValue);

        if (
          !Number.isNaN(
            date.getTime()
          ) &&
          date > group.latestTime
        ) {
          group.latestTime = date;
        }
      }
    });

    return Array.from(
      grouped.values()
    )
      .sort(
        (a, b) =>
          b.round - a.round
      )
      .slice(
        0,
        MAX_ROUNDS
      );
  }, [
    filteredMatches,
    latestFinishedRound,
  ]);

  // ============================================================
  // ROUND TOGGLE
  // ============================================================

  const toggleRound = useCallback(
    (key) => {
      setExpandedRounds(
        (previous) => ({
          ...previous,
          [key]:
            !previous[key],
        })
      );
    },
    []
  );

  // ============================================================
  // SCORE
  // ============================================================

  const getScore = useCallback(
    (match) => {
      const home = Number(
        match?.home_score ??
          match?.homeScore ??
          0
      );

      const away = Number(
        match?.away_score ??
          match?.awayScore ??
          0
      );

      return {
        home:
          Number.isFinite(home)
            ? home
            : 0,

        away:
          Number.isFinite(away)
            ? away
            : 0,
      };
    },
    []
  );

  // ============================================================
  // TEAM STYLE
  // ============================================================

  const getTeamClass =
    useCallback(
      (side, match) => {
        const {
          home,
          away,
        } = getScore(match);

        if (
          home === away
        ) {
          return "text-gray-300";
        }

        const winner =
          side === "home"
            ? home > away
            : away > home;

        return winner
          ? "font-bold text-green-400"
          : "text-gray-500";
      },
      [getScore]
    );

  // ============================================================
  // DATE / TIME
  // ============================================================

  const formatRoundDate =
    useCallback(
      (date) => {
        if (!date) {
          return "";
        }

        return date.toLocaleDateString(
          [],
          {
            weekday: "short",
            day: "numeric",
            month: "short",
          }
        );
      },
      []
    );

  const formatRoundTime =
    useCallback(
      (date) => {
        if (!date) {
          return "";
        }

        return date.toLocaleTimeString(
          [],
          {
            hour: "2-digit",
            minute: "2-digit",
          }
        );
      },
      []
    );

  // ============================================================
  // LOADING
  // ============================================================

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-4xl p-2">

        <div className="mb-3 rounded-2xl border border-gray-700 bg-gray-900 p-3">

          <div className="h-5 w-32 animate-pulse rounded bg-gray-700" />

          <div className="mt-2 h-3 w-48 animate-pulse rounded bg-gray-800" />

        </div>

        <div className="space-y-2">

          {[...Array(5)].map(
            (_, index) => (
              <div
                key={index}
                className="h-16 animate-pulse rounded-xl border border-gray-800 bg-gray-900"
              />
            )
          )}

        </div>

      </div>
    );
  }

  // ============================================================
  // UI
  // ============================================================

  return (
    <div className="mx-auto w-full max-w-4xl px-2 py-2 text-gray-200 sm:px-3">

      {/* HEADER */}

      <div className="mb-3 overflow-hidden rounded-2xl border border-gray-700 bg-gray-900 shadow-lg">

        <div className="flex items-center justify-between px-3 py-3">

          <div>

            <h2 className="text-base font-bold text-white sm:text-lg">
              Results
            </h2>

            <p className="mt-0.5 text-[10px] text-gray-500 sm:text-xs">
              Latest {MAX_ROUNDS} completed rounds
            </p>

          </div>

          <div className="flex items-center gap-1.5 rounded-full border border-gray-700 bg-gray-800 px-2.5 py-1">

            <span className="h-2 w-2 animate-pulse rounded-full bg-green-400" />

            <span className="text-[10px] font-medium text-gray-400">
              LIVE
            </span>

          </div>

        </div>

        {/* SEARCH */}

        <div className="border-t border-gray-800 px-3 py-2">

          <input
            type="text"
            value={filter}
            onChange={(event) =>
              setFilter(
                event.target.value
              )
            }
            placeholder="Search team..."
            className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-xs text-gray-200 outline-none transition placeholder:text-gray-500 focus:border-green-500"
          />

        </div>

      </div>

      {/* ERROR */}

      {error && (
        <div className="mb-3 rounded-xl border border-red-800 bg-red-900/20 px-3 py-2 text-center text-xs text-red-300">
          {error}
        </div>
      )}

      {/* EMPTY */}

      {rounds.length === 0 && (
        <div className="rounded-xl border border-gray-700 bg-gray-900 px-3 py-8 text-center">

          <div className="mb-2 text-2xl">
            🏆
          </div>

          <p className="text-sm text-gray-400">
            {filter
              ? "No results found for this team."
              : "No finished matches yet."}
          </p>

        </div>
      )}

      {/* ROUNDS */}

      <div className="space-y-2">

        {rounds.map(
          (round, roundIndex) => {
            const isExpanded =
              expandedRounds[
                round.key
              ] ??
              roundIndex === 0;

            const sortedMatches =
              [...round.matches].sort(
                (a, b) =>
                  Number(
                    a?.id || 0
                  ) -
                  Number(
                    b?.id || 0
                  )
              );

            return (
              <div
                key={round.key}
                className="overflow-hidden rounded-xl border border-gray-700 bg-gray-900 shadow-sm"
              >

                {/* ROUND HEADER */}

                <button
                  type="button"
                  onClick={() =>
                    toggleRound(
                      round.key
                    )
                  }
                  className="flex w-full items-center justify-between gap-2 bg-gray-800 px-3 py-3 text-left transition hover:bg-gray-700"
                >

                  <div className="min-w-0">

                    <div className="flex items-center gap-2">

                      <span className="text-xs font-bold text-white sm:text-sm">
                        Round{" "}
                        {round.round}
                      </span>

                      {roundIndex === 0 && (
                        <span className="rounded-full bg-green-500/15 px-1.5 py-0.5 text-[8px] font-bold text-green-400">
                          LATEST
                        </span>
                      )}

                    </div>

                    <div className="mt-0.5 text-[10px] text-gray-500">

                      {formatRoundDate(
                        round.latestTime
                      )}

                      {" • "}

                      {formatRoundTime(
                        round.latestTime
                      )}

                      {" • "}

                      {round.matches.length}{" "}

                      {round.matches.length ===
                      1
                        ? "match"
                        : "matches"}

                    </div>

                  </div>

                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-700 text-xs text-gray-300">

                    {isExpanded
                      ? "▲"
                      : "▼"}

                  </span>

                </button>

                {/* MATCHES */}

                {isExpanded && (
                  <div className="divide-y divide-gray-800">

                    {sortedMatches.map(
                      (
                        match,
                        index
                      ) => {
                        const {
                          home,
                          away,
                        } =
                          getScore(
                            match
                          );

                        const matchId =
                          match?.id ??
                          `${round.key}-${index}`;

                        return (
                          <div
                            key={
                              matchId
                            }
                            className="flex items-center gap-2 px-3 py-2.5 transition hover:bg-gray-800/50"
                          >

                            {/* TEAMS */}

                            <div className="min-w-0 flex-1">

                              <div
                                className={`flex items-center justify-between gap-2 ${getTeamClass(
                                  "home",
                                  match
                                )}`}
                              >

                                <span className="min-w-0 truncate text-xs">
                                  {match?.home ||
                                    "Home"}
                                </span>

                                <span className="w-5 text-right text-xs font-bold">
                                  {
                                    home
                                  }
                                </span>

                              </div>

                              <div
                                className={`mt-1 flex items-center justify-between gap-2 ${getTeamClass(
                                  "away",
                                  match
                                )}`}
                              >

                                <span className="min-w-0 truncate text-xs">
                                  {match?.away ||
                                    "Away"}
                                </span>

                                <span className="w-5 text-right text-xs font-bold">
                                  {
                                    away
                                  }
                                </span>

                              </div>

                            </div>

                            {/* FINAL SCORE */}

                            <div className="flex w-14 shrink-0 flex-col items-center justify-center rounded-lg border border-gray-700 bg-gray-800 py-1">

                              <span className="text-[8px] uppercase tracking-wide text-gray-500">
                                FT
                              </span>

                              <span className="mt-0.5 text-sm font-black text-white">
                                {home}-{away}
                              </span>

                            </div>

                          </div>
                        );
                      }
                    )}

                  </div>
                )}

              </div>
            );
          }
        )}

      </div>

      {/* FOOTER */}

      {rounds.length > 0 && (
        <div className="mt-3 flex items-center justify-center gap-2 text-[9px] text-gray-600">

          <span>
            Showing{" "}
            {rounds.length}{" "}
            of {MAX_ROUNDS}{" "}
            rounds
          </span>

          <span>•</span>

          <span>
            Updates automatically
          </span>

        </div>
      )}

    </div>
  );
}
