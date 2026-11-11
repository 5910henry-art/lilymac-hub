import React, {
  useEffect,
  useState,
} from "react";

import VirtualAPI from "../api/virtualAPI";

export default function LeagueTable() {
  const [table, setTable] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let mounted = true;

    const loadTable = async () => {
      try {
        const data =
          await VirtualAPI.getLeagueTable();

        if (!mounted) return;

        const tableData = Array.isArray(data)
          ? data
          : Array.isArray(data?.table)
            ? data.table
            : [];

        setTable(tableData);
        setError(null);
      } catch (err) {
        console.error(
          "Failed to load league table:",
          err
        );

        if (!mounted) return;

        setError(
          "Unable to load league table."
        );
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    loadTable();

    const stopPolling =
      VirtualAPI.liveLeagueTable(
        (data) => {
          if (!mounted) return;

          const tableData =
            Array.isArray(data)
              ? data
              : Array.isArray(data?.table)
                ? data.table
                : [];

          setTable(tableData);
          setError(null);
          setLoading(false);
        },
        5000
      );

    return () => {
      mounted = false;
      stopPolling?.();
    };
  }, []);

  if (loading) {
    return (
      <div className="league-table rounded-lg border border-gray-700 bg-gray-900 p-4 text-gray-200">
        <h3 className="mb-3 text-lg font-bold">
          League Table
        </h3>

        <div className="animate-pulse space-y-2">
          {[1, 2, 3, 4, 5].map((item) => (
            <div
              key={item}
              className="h-8 rounded bg-gray-800"
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="league-table rounded-lg border border-gray-700 bg-gray-900 p-3 text-gray-200">
      <h3 className="mb-3 text-lg font-bold text-white">
        League Table
      </h3>

      {error && (
        <div className="mb-3 rounded border border-red-800 bg-red-900/20 p-2 text-center text-xs text-red-300">
          {error}
        </div>
      )}

      {table.length === 0 ? (
        <div className="py-4 text-center text-sm text-gray-500">
          No league table data available.
        </div>
      ) : (
        <div className="w-full overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-gray-700 bg-gray-800">
                <th className="px-2 py-2 text-center">
                  #
                </th>

                <th className="px-2 py-2 text-left">
                  Team
                </th>

                <th className="px-2 py-2 text-center">
                  P
                </th>

                <th className="px-2 py-2 text-center">
                  W
                </th>

                <th className="px-2 py-2 text-center">
                  D
                </th>

                <th className="px-2 py-2 text-center">
                  L
                </th>

                <th className="px-2 py-2 text-center">
                  Pts
                </th>
              </tr>
            </thead>

            <tbody>
              {table.map((team, index) => (
                <tr
                  key={
                    team.id ??
                    team.team ??
                    index
                  }
                  className="border-b border-gray-800 transition hover:bg-gray-800/60"
                >
                  <td className="px-2 py-2 text-center font-semibold">
                    {team.rank ?? index + 1}
                  </td>

                  <td className="px-2 py-2 font-medium text-white">
                    {team.team || "Unknown"}
                  </td>

                  <td className="px-2 py-2 text-center">
                    {team.played ?? 0}
                  </td>

                  <td className="px-2 py-2 text-center">
                    {team.wins ?? 0}
                  </td>

                  <td className="px-2 py-2 text-center">
                    {team.draws ?? 0}
                  </td>

                  <td className="px-2 py-2 text-center">
                    {team.losses ?? 0}
                  </td>

                  <td className="px-2 py-2 text-center font-bold text-white">
                    {team.points ?? 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
