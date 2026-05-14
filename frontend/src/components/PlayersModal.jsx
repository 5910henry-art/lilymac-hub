// src/components/PlayersModal.jsx
import React, { useEffect, useMemo, useState } from "react";
import { getPlayers } from "../api/api";
import Loader from "./Loader";

export default function PlayersModal({ team, onClose }) {
  const [players, setPlayers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [positionFilter, setPositionFilter] = useState("Goalkeeper");
  const [positions, setPositions] = useState(["All", "Goalkeeper"]);

  const getInitials = (name = "") =>
    name
      .split(" ")
      .map((n) => n[0])
      .slice(0, 2)
      .join("")
      .toUpperCase();

  const getPositionClass = (pos) => {
    if (!pos) return "bg-gray-300 text-gray-800";
    const lower = pos.toLowerCase();
    if (lower.includes("goal")) return "bg-yellow-300 text-yellow-800";
    if (lower.includes("def")) return "bg-blue-300 text-blue-800";
    if (lower.includes("mid")) return "bg-green-300 text-green-800";
    if (lower.includes("for") || lower.includes("off")) return "bg-red-300 text-red-800";
    return "bg-gray-300 text-gray-800";
  };

  // Fetch players
  useEffect(() => {
    const fetchPlayers = async () => {
      setLoading(true);
      try {
        const res = await getPlayers({ team_id: team.id });
        const list = res.data?.players || res.data?.data || res.data || [];
        const playerList = Array.isArray(list) ? list : [];
        setPlayers(playerList);

        // Dynamically extract positions
        const posSet = new Set(playerList.map((p) => p.position).filter(Boolean));
        setPositions(["All", "Goalkeeper", ...Array.from(posSet).filter(p => p !== "Goalkeeper")]);
      } catch (err) {
        console.error("Error fetching players:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchPlayers();
  }, [team.id]);

  // Close modal on ESC
  useEffect(() => {
    const handleEsc = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [onClose]);

  // Filter players
  const filteredPlayers = useMemo(() => {
    return players.filter(
      (p) =>
        p.name?.toLowerCase().includes(search.toLowerCase()) &&
        (positionFilter === "All" ||
          p.position?.toLowerCase().includes(positionFilter.toLowerCase()))
    );
  }, [players, search, positionFilter]);

  const topPlayers = filteredPlayers.slice(0, 6);
  const restPlayers = filteredPlayers.slice(6);

  const PlayerCard = ({ player }) => (
    <div className="bg-gray-50 dark:bg-gray-800 rounded-xl p-4 text-center shadow-sm hover:shadow-lg transition-all duration-200 hover:-translate-y-1">
      <div className="w-16 h-16 mx-auto rounded-full overflow-hidden mb-2">
        {player.photo ? (
          <img src={player.photo} alt={player.name} className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 flex items-center justify-center text-lg font-bold">
            {getInitials(player.name)}
          </div>
        )}
      </div>
      <h4 className="text-sm font-semibold text-gray-800 dark:text-gray-100 truncate">{player.name}</h4>
      <span
        className={`inline-block px-2 py-1 text-xs font-semibold rounded ${getPositionClass(player.position)}`}
      >
        {player.position || "—"}
      </span>
      <p className="text-xs text-gray-400 mt-1">Age: {player.age || "—"}</p>
      <div className="flex justify-center gap-2 mt-2 text-xs text-gray-500 dark:text-gray-400">
        {player.goals !== undefined && <span>⚽ {player.goals}</span>}
        {player.assists !== undefined && <span>🅰️ {player.assists}</span>}
        {player.key_player && <span>⭐</span>}
        {player.is_injured && <span>🩹</span>}
      </div>
    </div>
  );

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex justify-center items-center p-2" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-900 w-full max-w-4xl h-[90vh] rounded-2xl shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Sticky header */}
        <div className="sticky top-0 z-10 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 p-4 flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <button onClick={onClose} className="text-sm font-medium text-blue-600 hover:text-blue-800 transition">← Back</button>
            <h2 className="text-base sm:text-lg font-semibold text-gray-800 dark:text-gray-100 text-center flex-1">{team.name} Players</h2>
            <div className="w-12" />
          </div>

          {/* Search and position filter */}
          <div className="flex flex-wrap gap-2">
            <input
              type="text"
              placeholder="Search player..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <select
              value={positionFilter}
              onChange={(e) => setPositionFilter(e.target.value)}
              className="px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {positions.map((pos) => (
                <option key={pos} value={pos}>
                  {pos}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Scrollable content */}
        {loading ? (
          <Loader text="Loading players..." />
        ) : filteredPlayers.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400 text-center mt-4">No players found.</p>
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
            {/* Top 6 players */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-4">
              {topPlayers.map((p) => (
                <PlayerCard key={p.id} player={p} />
              ))}
            </div>

            {/* Rest of players */}
            {restPlayers.length > 0 && (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
                {restPlayers.map((p) => (
                  <PlayerCard key={p.id} player={p} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
