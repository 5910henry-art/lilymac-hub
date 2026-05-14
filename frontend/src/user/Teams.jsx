// src/pages/Team.jsx
import React, { useEffect, useState, useMemo } from "react";
import { getTeams } from "../api/api";
import Loader from "../components/Loader";
import PlayersModal from "../components/PlayersModal";

const PLACEHOLDER = "/logos/placeholder.png";

export default function Team() {
  const [teams, setTeams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [competitionFilter, setCompetitionFilter] = useState("All");
  const [competitions, setCompetitions] = useState(["All"]);
  const [selectedTeam, setSelectedTeam] = useState(null);

  // Prevent background scroll when modal is open
  useEffect(() => {
    if (selectedTeam) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "auto";
    }
  }, [selectedTeam]);

  // Fetch teams
  useEffect(() => {
    const fetchTeams = async () => {
      setLoading(true);
      try {
        const res = await getTeams();
        if (res.success && Array.isArray(res.data.teams)) {
          setTeams(res.data.teams);

          const compsSet = new Set();
          res.data.teams.forEach((t) =>
            (t.competitions || []).forEach((c) => compsSet.add(c))
          );

          setCompetitions(["All", ...Array.from(compsSet).sort()]);
        }
      } catch (err) {
        console.error("Error fetching teams:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchTeams();
  }, []);

  const filteredTeams = useMemo(() => {
    return teams.filter((t) => {
      const matchName = t.name
        .toLowerCase()
        .includes(search.toLowerCase());

      const matchCompetition =
        competitionFilter === "All" ||
        (t.competitions || []).includes(competitionFilter);

      return matchName && matchCompetition;
    });
  }, [teams, search, competitionFilter]);

  if (loading) return <Loader text="Loading teams..." />;

  return (
    <div className="p-6 min-h-screen bg-gray-50">
      {/* Page Title */}
      <h1 className="text-xl font-semibold mb-6 text-gray-800">
        Teams
      </h1>

      {/* Search & Filter */}
      <div className="flex flex-wrap gap-3 mb-8">
        <input
          type="text"
          placeholder="Search team..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-4 py-2 text-sm border rounded-lg w-52 focus:outline-none focus:ring-2 focus:ring-blue-400"
        />

        <select
          value={competitionFilter}
          onChange={(e) => setCompetitionFilter(e.target.value)}
          className="px-4 py-2 text-sm border rounded-lg bg-white"
        >
          {competitions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      {/* Teams Grid */}
      {filteredTeams.length === 0 ? (
        <div className="bg-white p-8 rounded-xl border text-center shadow-sm">
          <p className="text-gray-500 text-sm">
            No teams found for selected filters.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-6">
          {filteredTeams.map((t) => (
            <div
              key={t.id}
              onClick={() => setSelectedTeam(t)}
              className="flex items-center gap-4 p-5 bg-white rounded-2xl shadow-sm hover:shadow-lg hover:-translate-y-1 cursor-pointer transition-all duration-200"
            >
              <img
                src={t.crest || PLACEHOLDER}
                onError={(e) => (e.target.src = PLACEHOLDER)}
                alt={t.name}
                className="w-16 h-16 object-contain rounded"
              />

              <div className="flex-1">
                <h3 className="text-sm font-semibold text-gray-800">
                  {t.name}
                </h3>
                <p className="text-xs text-gray-500 mt-1">
                  {t.venue}
                </p>
                <p className="text-xs text-gray-400">
                  Founded: {t.founded}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Players Modal */}
      {selectedTeam && (
        <PlayersModal
          team={selectedTeam}
          onClose={() => setSelectedTeam(null)}
        />
      )}
    </div>
  );
}
