import React, { useEffect, useState, useMemo } from "react";
import VirtualAPI from "../api/virtualAPI";

export default function FinishedMatches() {
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [drawer, setDrawer] = useState(false);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    const loadNow = async () => {
      try {
        const data = await VirtualAPI.getFinished();
        setMatches(data);
        setLoading(false);
      } catch (err) {
        console.error("Initial load failed:", err);
      }
    };

    loadNow();

    const stopPolling = VirtualAPI.liveFinished((data) => {
      setMatches(prev =>
        JSON.stringify(prev) === JSON.stringify(data) ? prev : data
      );
      setLoading(false);
    }, 3000);

    return () => stopPolling();
  }, []);

  const grouped = useMemo(() => {
    const map = {};
    matches
      .filter(m => 
        m.home.toLowerCase().includes(filter.toLowerCase()) ||
        m.away.toLowerCase().includes(filter.toLowerCase())
      )
      .forEach(m => {
        const date = new Date(m.start_time);
        const key = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        if (!map[key]) map[key] = { time: date, games: [] };
        map[key].games.push(m);
      });
    return Object.values(map).sort((a, b) => b.time - a.time);
  }, [matches, filter]);

  const teamClass = (type, match) => {
    if (match.home_score === match.away_score) return "text-gray-400 font-semibold";
    if (type === "home" && match.home_score > match.away_score) return "text-green-400 font-bold";
    if (type === "away" && match.away_score > match.home_score) return "text-green-400 font-bold";
    return "text-gray-500";
  };

  if (loading) {
    return (
      <div className="p-2 space-y-2">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-10 bg-gray-700 animate-pulse rounded"></div>
        ))}
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-2 bg-gray-900 text-gray-200 rounded-xl border border-gray-700">
      {/* Drawer toggle */}
      <button
        onClick={() => setDrawer(!drawer)}
        className="w-full bg-gray-800 border border-gray-700 rounded p-2 text-sm font-semibold shadow-sm mb-2 hover:bg-gray-700 transition"
      >
        {drawer ? "Hide Finished Matches" : "Show Finished Matches"}
      </button>

      {/* Filter */}
      {drawer && (
        <div className="mb-2">
          <input
            type="text"
            placeholder="Filter by team..."
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="w-full p-1 rounded border border-gray-600 bg-gray-800 text-gray-200 text-sm focus:outline-none focus:border-blue-400"
          />
        </div>
      )}

      {/* Drawer */}
      {drawer && (
        <div className="space-y-2 max-h-[60vh] overflow-y-auto">
          {grouped.length === 0 && (
            <div className="text-gray-400 text-center py-2">No matches found</div>
          )}

          {grouped.map(group => (
            <div key={group.time} className="border border-gray-700 rounded">
              <div className="bg-gray-800 px-2 py-1 text-xs font-semibold text-gray-300">
                {group.time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} • {group.games.length} matches
              </div>

              {group.games.map(match => (
                <div
                  key={match.id}
                  className="flex justify-between items-center px-2 py-1 text-sm border-t border-gray-700"
                >
                  <div className="flex flex-col">
                    <span className={teamClass("home", match)}>
                      {match.home} {match.home_score}
                    </span>
                    <span className={teamClass("away", match)}>
                      {match.away} {match.away_score}
                    </span>
                  </div>
                  <div className="font-semibold">{match.home_score}-{match.away_score}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
