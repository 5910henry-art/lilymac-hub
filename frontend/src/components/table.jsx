// src/components/table.jsx

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import VirtualAPI from "../api/virtualAPI";
import VirtualSocket from "../api/virtualSocket";

export default function LiveLeagueTable() {
  const [teams, setTeams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError] = useState(null);
  const [flashRows, setFlashRows] = useState({});

  const prevData = useRef({});
  const flashTimers = useRef({});
  const mountedRef = useRef(false);

  const loadingRef = useRef(false);
  const refreshTimerRef = useRef(null);

  // ============================================================
  // FLASH CLEANUP
  // ============================================================

  const clearFlashTimers = useCallback(() => {
    Object.values(flashTimers.current).forEach(
      (timer) => clearTimeout(timer)
    );

    flashTimers.current = {};
  }, []);

  const flashTeam = useCallback((teamName) => {
    if (!teamName) return;

    if (flashTimers.current[teamName]) {
      clearTimeout(
        flashTimers.current[teamName]
      );
    }

    setFlashRows((current) => ({
      ...current,
      [teamName]: true,
    }));

    flashTimers.current[teamName] =
      setTimeout(() => {
        if (!mountedRef.current) return;

        setFlashRows((current) => {
          const next = { ...current };
          delete next[teamName];
          return next;
        });

        delete flashTimers.current[teamName];
      }, 900);
  }, []);

  // ============================================================
  // APPLY TABLE DATA
  // ============================================================

  const applyTableData = useCallback(
    (data) => {
      if (!mountedRef.current) return;

      const safeData = Array.isArray(data)
        ? data
        : [];

      const nextPreviousData = {};
      const movementData = [];

      safeData.forEach((team) => {
        if (!team || !team.team) return;

        const teamName = team.team;
        const previousTeam =
          prevData.current[teamName];

        let movement = 0;

        if (previousTeam) {
          movement =
            Number(previousTeam.rank || 0) -
            Number(team.rank || 0);

          const changed =
            Number(previousTeam.points || 0) !==
              Number(team.points || 0) ||
            Number(previousTeam.rank || 0) !==
              Number(team.rank || 0) ||
            Number(previousTeam.played || 0) !==
              Number(team.played || 0) ||
            Number(previousTeam.wins || 0) !==
              Number(team.wins || 0) ||
            Number(previousTeam.draws || 0) !==
              Number(team.draws || 0) ||
            Number(previousTeam.losses || 0) !==
              Number(team.losses || 0) ||
            Number(previousTeam.gf || 0) !==
              Number(team.gf || 0) ||
            Number(previousTeam.ga || 0) !==
              Number(team.ga || 0);

          if (changed) {
            flashTeam(teamName);
          }
        }

        nextPreviousData[teamName] = {
          ...team,
        };

        movementData.push({
          ...team,
          movement,
        });
      });

      prevData.current =
        nextPreviousData;

      setTeams(movementData);
      setLoading(false);
      setError(null);
      setLastUpdated(new Date());
    },
    [flashTeam]
  );

  // ============================================================
  // LOAD TABLE
  // ============================================================

  const loadTable = useCallback(
    async (force = false) => {
      if (
        loadingRef.current &&
        !force
      ) {
        return;
      }

      loadingRef.current = true;

      try {
        const response =
          await VirtualAPI.getLeagueTable();

        if (!mountedRef.current) {
          return;
        }

        const tableData =
          Array.isArray(response)
            ? response
            : response?.table;

        if (!Array.isArray(tableData)) {
          throw new Error(
            "Invalid league table response"
          );
        }

        applyTableData(tableData);
      } catch (err) {
        console.error(
          "Failed to load league table:",
          err
        );

        if (!mountedRef.current) {
          return;
        }

        setError(
          "Unable to load the league table."
        );

        setLoading(false);
      } finally {
        loadingRef.current = false;
      }
    },
    [applyTableData]
  );

  // ============================================================
  // DEBOUNCED LIVE REFRESH
  // ============================================================

  const scheduleTableRefresh =
    useCallback(() => {
      if (!mountedRef.current) {
        return;
      }

      if (refreshTimerRef.current) {
        clearTimeout(
          refreshTimerRef.current
        );
      }

      refreshTimerRef.current =
        setTimeout(() => {
          if (!mountedRef.current) {
            return;
          }

          loadTable();
        }, 250);
    }, [loadTable]);

  // ============================================================
  // FORM
  // ============================================================

  const renderForm = useCallback(
    (formArray) => {
      if (
        !Array.isArray(formArray) ||
        formArray.length === 0
      ) {
        return (
          <span className="text-gray-500 text-[10px]">
            —
          </span>
        );
      }

      return (
        <div
          className="flex items-center justify-center gap-1"
          aria-label={`Recent form: ${formArray.join(
            ", "
          )}`}
        >
          {formArray.map(
            (result, index) => {
              const value = String(
                result || ""
              ).toUpperCase();

              let className =
                "bg-gray-500 text-gray-100";

              if (value === "W") {
                className =
                  "bg-green-500 text-white";
              } else if (value === "D") {
                className =
                  "bg-yellow-400 text-gray-900";
              } else if (value === "L") {
                className =
                  "bg-red-500 text-white";
              }

              return (
                <span
                  key={`${value}-${index}`}
                  className={`inline-flex h-3 w-3 items-center justify-center rounded-full text-[7px] font-bold ${className}`}
                  title={value}
                  aria-label={value}
                >
                  {value}
                </span>
              );
            }
          )}
        </div>
      );
    },
    []
  );

  // ============================================================
  // TABLE ROWS
  // ============================================================

  const tableRows = useMemo(() => {
    return teams.map(
      (team, index) => {
        let rowClass =
          "border-b border-gray-800 transition-all duration-300";

        if (index === 0) {
          rowClass +=
            " bg-yellow-900/30 font-bold";
        } else if (index === 1) {
          rowClass +=
            " bg-gray-800/80 font-semibold";
        } else if (index === 2) {
          rowClass +=
            " bg-orange-900/30 font-semibold";
        }

        if (
          index >=
          Math.max(teams.length - 3, 0)
        ) {
          rowClass +=
            " bg-red-900/25";
        }

        if (flashRows[team.team]) {
          rowClass +=
            " animate-pulse ring-1 ring-green-400/40";
        }

        let trendArrow = "→";
        let arrowColor =
          "text-gray-500";

        if (team.movement > 0) {
          trendArrow = "⬆";
          arrowColor =
            "text-green-400";
        } else if (
          team.movement < 0
        ) {
          trendArrow = "⬇";
          arrowColor =
            "text-red-400";
        }

        return {
          ...team,
          rowClass,
          trendArrow,
          arrowColor,
        };
      }
    );
  }, [teams, flashRows]);

  // ============================================================
  // INITIAL LOAD
  // ============================================================

  useEffect(() => {
    mountedRef.current = true;

    loadTable();

    return () => {
      mountedRef.current = false;

      clearFlashTimers();

      if (refreshTimerRef.current) {
        clearTimeout(
          refreshTimerRef.current
        );
      }
    };
  }, [
    loadTable,
    clearFlashTimers,
  ]);

  // ============================================================
  // SOCKET LIVE UPDATES
  // ============================================================

  useEffect(() => {
    try {
      VirtualSocket.connect();
    } catch (error) {
      console.error(
        "Table socket error:",
        error
      );
    }

    // ----------------------------------------------------------
    // CURRENT EVENT NAMES
    // ----------------------------------------------------------

    const cleanupVirtualUpdate =
      VirtualSocket.on(
        "virtual_match_update",
        () => {
          scheduleTableRefresh();
        }
      );

    // ----------------------------------------------------------
    // LEGACY EVENT NAME
    // ----------------------------------------------------------
    //
    // Virtual.js already listens for this event.
    // The table must listen too.
    //

    const cleanupMatchUpdate =
      VirtualSocket.on(
        "match_update",
        () => {
          scheduleTableRefresh();
        }
      );

    // ----------------------------------------------------------
    // MATCH FINISHED
    // ----------------------------------------------------------

    const cleanupVirtualFinished =
      VirtualSocket.on(
        "virtual_match_finished",
        () => {
          scheduleTableRefresh();
        }
      );

    const cleanupMatchFinished =
      VirtualSocket.on(
        "match_finished",
        () => {
          scheduleTableRefresh();
        }
      );

    // ----------------------------------------------------------
    // MATCH EVENTS
    // ----------------------------------------------------------

    const cleanupVirtualEvent =
      VirtualSocket.on(
        "virtual_match_event",
        () => {
          scheduleTableRefresh();
        }
      );

    const cleanupMatchEvent =
      VirtualSocket.on(
        "match_event",
        () => {
          scheduleTableRefresh();
        }
      );

    // ----------------------------------------------------------
    // DIRECT TABLE UPDATE
    // ----------------------------------------------------------

    const cleanupTableUpdate =
      VirtualSocket.on(
        "table_update",
        (data) => {
          if (
            Array.isArray(data)
          ) {
            applyTableData(data);
            return;
          }

          if (
            data?.table &&
            Array.isArray(
              data.table
            )
          ) {
            applyTableData(
              data.table
            );
            return;
          }

          scheduleTableRefresh();
        }
      );

    return () => {
      cleanupVirtualUpdate?.();
      cleanupMatchUpdate?.();
      cleanupVirtualFinished?.();
      cleanupMatchFinished?.();
      cleanupVirtualEvent?.();
      cleanupMatchEvent?.();
      cleanupTableUpdate?.();
    };
  }, [
    applyTableData,
    scheduleTableRefresh,
  ]);

  // ============================================================
  // LOADING
  // ============================================================

  if (
    loading &&
    teams.length === 0
  ) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center px-4">
        <div className="text-center">
          <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-gray-600 border-t-green-400" />

          <p className="text-sm text-gray-300">
            Loading league table...
          </p>
        </div>
      </div>
    );
  }

  // ============================================================
  // UI
  // ============================================================

  return (
    <div className="min-h-screen w-full bg-gray-900 px-1 py-2 text-sm text-gray-200 sm:px-2">
      <div className="mx-auto w-full max-w-5xl rounded-xl border border-gray-700 bg-gray-900 p-2 shadow-lg sm:p-3">

        <div className="mb-2">
          <h2 className="text-center text-lg font-bold text-white">
            Live League Table
          </h2>

          {lastUpdated && (
            <p className="mt-1 text-center text-[10px] text-gray-500 sm:text-xs">
              Live • Updated{" "}
              {lastUpdated.toLocaleTimeString()}
            </p>
          )}
        </div>

        {error && (
          <div className="mb-2 rounded-lg border border-red-800 bg-red-900/20 px-3 py-2 text-center text-xs text-red-300">
            {error}
          </div>
        )}

        {loading &&
          teams.length > 0 && (
            <div className="mb-2 flex items-center justify-center gap-2 text-[10px] text-gray-500">
              <span className="h-2 w-2 animate-pulse rounded-full bg-green-400" />
              Updating...
            </div>
          )}

        <div className="w-full overflow-x-auto rounded-lg border border-gray-700 overscroll-x-contain">
          <table className="w-full min-w-[650px] table-auto border-collapse bg-gray-900 text-[11px] text-gray-200 sm:text-xs">

            <thead className="sticky top-0 z-10 bg-gray-800 text-gray-100">
              <tr>
                <th className="whitespace-nowrap border-b border-gray-700 px-2 py-2 text-center">
                  #
                </th>

                <th className="min-w-[125px] whitespace-nowrap border-b border-gray-700 px-2 py-2 text-left">
                  Team
                </th>

                <th className="whitespace-nowrap border-b border-gray-700 px-2 py-2 text-center">
                  P
                </th>

                <th className="whitespace-nowrap border-b border-gray-700 px-2 py-2 text-center">
                  W
                </th>

                <th className="whitespace-nowrap border-b border-gray-700 px-2 py-2 text-center">
                  D
                </th>

                <th className="whitespace-nowrap border-b border-gray-700 px-2 py-2 text-center">
                  L
                </th>

                <th className="whitespace-nowrap border-b border-gray-700 px-2 py-2 text-center">
                  GF
                </th>

                <th className="whitespace-nowrap border-b border-gray-700 px-2 py-2 text-center">
                  GA
                </th>

                <th className="whitespace-nowrap border-b border-gray-700 px-2 py-2 text-center">
                  GD
                </th>

                <th className="whitespace-nowrap border-b border-gray-700 px-2 py-2 text-center">
                  Pts
                </th>

                <th className="whitespace-nowrap border-b border-gray-700 px-2 py-2 text-center">
                  Form
                </th>
              </tr>
            </thead>

            <tbody>
              {tableRows.length === 0 ? (
                <tr>
                  <td
                    colSpan={11}
                    className="px-3 py-8 text-center text-gray-500"
                  >
                    No teams to display
                  </td>
                </tr>
              ) : (
                tableRows.map(
                  (team) => (
                    <tr
                      key={team.team}
                      className={`${team.rowClass} hover:bg-gray-800/70`}
                    >
                      <td className="whitespace-nowrap px-2 py-1.5 text-center">
                        <span>
                          {team.rank}
                        </span>

                        <span
                          className={`ml-1 ${team.arrowColor}`}
                          title={
                            team.movement > 0
                              ? `Moved up ${team.movement}`
                              : team.movement < 0
                              ? `Moved down ${Math.abs(
                                  team.movement
                                )}`
                              : "No movement"
                          }
                        >
                          {
                            team.trendArrow
                          }
                        </span>
                      </td>

                      <td className="max-w-[180px] truncate px-2 py-1.5 font-medium text-gray-100">
                        {team.team}
                      </td>

                      <td className="px-2 py-1.5 text-center">
                        {team.played ??
                          0}
                      </td>

                      <td className="px-2 py-1.5 text-center">
                        {team.wins ?? 0}
                      </td>

                      <td className="px-2 py-1.5 text-center">
                        {team.draws ?? 0}
                      </td>

                      <td className="px-2 py-1.5 text-center">
                        {team.losses ?? 0}
                      </td>

                      <td className="px-2 py-1.5 text-center">
                        {team.gf ?? 0}
                      </td>

                      <td className="px-2 py-1.5 text-center">
                        {team.ga ?? 0}
                      </td>

                      <td className="px-2 py-1.5 text-center">
                        {Number(
                          team.goal_difference ||
                            0
                        ) > 0
                          ? `+${team.goal_difference}`
                          : team.goal_difference ??
                            0}
                      </td>

                      <td className="px-2 py-1.5 text-center font-bold text-white">
                        {team.points ?? 0}
                      </td>

                      <td className="px-2 py-1.5">
                        {renderForm(
                          team.form
                        )}
                      </td>
                    </tr>
                  )
                )
              )}
            </tbody>
          </table>
        </div>

        {teams.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[9px] text-gray-500 sm:text-[10px]">
            <span>⬆ Up</span>
            <span>⬇ Down</span>
            <span>→ Same</span>
            <span>🟢 Win</span>
            <span>🟡 Draw</span>
            <span>🔴 Loss</span>
          </div>
        )}

      </div>
    </div>
  );
}
