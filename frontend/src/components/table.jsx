import React, { useEffect, useState, useRef, useCallback } from "react";
import VirtualAPI from "../api/virtualAPI";
import { socket } from "../lib/socket";

export default function LiveLeagueTable() {
  const [teams, setTeams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);
  const prevData = useRef({});
  const [flashRows, setFlashRows] = useState({});

  // Apply table data with movement and flash effect
  const applyTableData = useCallback((data) => {
    if (!Array.isArray(data)) data = []; // safety fallback
    const newFlashRows = {};

    const movementData = data.map((team) => {
      const prevTeam = prevData.current[team.team];
      let movement = 0;

      if (prevTeam) {
        movement = prevTeam.rank - team.rank;

        if (prevTeam.points !== team.points || prevTeam.rank !== team.rank) {
          newFlashRows[team.team] = true;
          setTimeout(() => {
            setFlashRows((f) => ({ ...f, [team.team]: false }));
          }, 800);
        }
      }

      prevData.current[team.team] = { ...team };
      return { ...team, movement };
    });

    setTeams(movementData);
    setFlashRows(newFlashRows);
    setLoading(false);
    setLastUpdated(new Date());
    console.log("Applied table data:", movementData); // DEBUG
  }, []);

  // Load table from API
  const loadTable = useCallback(async () => {
    setLoading(true);
    try {
      const data = await VirtualAPI.getLeagueTable();
      console.log("Fetched table data:", data); // DEBUG
      applyTableData(data.table || []); // ✅ FIX: use table array
    } catch (err) {
      console.error("Failed to load league table:", err);
      setTeams([]);
      setLoading(false);
    }
  }, [applyTableData]);

  // Render recent form as colored dots
  const renderForm = (formArray) => {
    if (!Array.isArray(formArray)) return null;
    return (
      <div className="flex gap-1 justify-center">
        {formArray.map((f, i) => {
          let bg = "bg-gray-500";
          if (f === "W") bg = "bg-green-500";
          else if (f === "D") bg = "bg-yellow-400";
          else if (f === "L") bg = "bg-red-500";

          return <span key={i} className={`${bg} w-3 h-3 rounded-full`} title={f}></span>;
        })}
      </div>
    );
  };

  // Initial load
  useEffect(() => {
    loadTable();
  }, [loadTable]);

  // Socket updates
  useEffect(() => {
    socket.on("match_update", loadTable);
    socket.on("match_finished", loadTable);
    socket.on("table_update", (data) => {
      if (Array.isArray(data)) applyTableData(data);
      else loadTable();
    });

    return () => {
      socket.off("match_update", loadTable);
      socket.off("match_finished", loadTable);
      socket.off("table_update");
    };
  }, [applyTableData, loadTable]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center text-gray-300 text-sm">
        Loading...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900 p-2 max-w-5xl mx-auto text-sm text-gray-200">
      <div className="bg-gray-900 rounded-xl shadow-lg border border-gray-700 p-3">
        <h2 className="text-lg font-bold mb-1 text-center text-white">
          Live League Table
        </h2>

        {lastUpdated && (
          <p className="text-xs text-gray-400 text-center mb-2">
            Last updated: {lastUpdated.toLocaleTimeString()}
          </p>
        )}

        <div className="overflow-x-auto rounded-lg border border-gray-700">
          <table className="min-w-full table-auto border-collapse text-xs bg-gray-900 text-gray-200">
            <thead className="bg-gray-800 text-gray-100">
              <tr>
                {["#", "Team", "P", "W", "D", "L", "GF", "GA", "GD", "Pts", "Form"].map(
                  (col) => (
                    <th key={col} className="px-2 py-1 border-b border-gray-700">
                      {col}
                    </th>
                  )
                )}
              </tr>
            </thead>

            <tbody>
              {teams.length === 0 ? (
                <tr>
                  <td colSpan={11} className="text-center py-2 text-gray-400">
                    No teams to display
                  </td>
                </tr>
              ) : (
                teams.map((team, idx) => {
                  let rowClass = "border-b border-gray-700";

                  if (idx === 0) rowClass += " bg-yellow-900/35 font-bold";
                  else if (idx === 1) rowClass += " bg-gray-800 font-semibold";
                  else if (idx === 2) rowClass += " bg-orange-900/35 font-semibold";
                  if (idx >= teams.length - 3) rowClass += " bg-red-900/30 font-semibold";
                  if (flashRows[team.team]) rowClass += " animate-pulse";

                  let trendArrow = "→";
                  let arrowColor = "text-gray-400";

                  if (team.movement > 0) {
                    trendArrow = "⬆";
                    arrowColor = "text-green-400";
                  } else if (team.movement < 0) {
                    trendArrow = "⬇";
                    arrowColor = "text-red-400";
                  }

                  return (
                    <tr
                      key={team.team}
                      className={`${rowClass} transition-all duration-300 hover:bg-gray-800`}
                    >
                      <td className="px-1 py-0.5 text-center">
                        {team.rank}
                        <span className={`ml-1 ${arrowColor}`}>{trendArrow}</span>
                      </td>
                      <td className="px-1 py-0.5">{team.team}</td>
                      <td className="px-1 py-0.5 text-center">{team.played}</td>
                      <td className="px-1 py-0.5 text-center">{team.wins}</td>
                      <td className="px-1 py-0.5 text-center">{team.draws}</td>
                      <td className="px-1 py-0.5 text-center">{team.losses}</td>
                      <td className="px-1 py-0.5 text-center">{team.gf}</td>
                      <td className="px-1 py-0.5 text-center">{team.ga}</td>
                      <td className="px-1 py-0.5 text-center">{team.goal_difference}</td>
                      <td className="px-1 py-0.5 text-center font-bold">{team.points}</td>
                      <td className="px-1 py-0.5">{renderForm(team.form)}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
