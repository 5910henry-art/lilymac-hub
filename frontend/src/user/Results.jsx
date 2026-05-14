// src/pages/Results.jsx
import React, { useEffect, useMemo, useState } from "react";
import {
  getFinishedMatchesWithPredictions,
  loadTeams,
  attachLogosSafe,
} from "../api/api";
import Loader from "../components/Loader";

const PLACEHOLDER = "/logos/placeholder.png";

/* Competition name normalisation mapping */
const COMPETITION_LABELS = {
  "Primera Division": "LaLiga",
};

/* A simple palette for competition chips (pick deterministic colors per league) */
const COMP_COLORS = {
  premierleague: "from-blue-50 to-blue-100 text-blue-800 border-blue-200",
  laliga: "from-red-50 to-red-100 text-red-800 border-red-200",
  seriea: "from-yellow-50 to-yellow-100 text-yellow-800 border-yellow-200",
  bundesliga: "from-green-50 to-green-100 text-green-800 border-green-200",
  default: "from-gray-50 to-gray-100 text-gray-800 border-gray-200",
};

const normalizeCompetitionKey = (name = "") =>
  String(name || "")
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace(/[^\w]/g, "");

const getCompetitionChipClass = (name = "") => {
  const key = normalizeCompetitionKey(COMPETITION_LABELS[name] || name);
  return COMP_COLORS[key] || COMP_COLORS["default"];
};

const formatDateGroup = (utcDate) =>
  new Date(utcDate).toLocaleDateString("en-KE", {
    weekday: "long",
    day: "numeric",
    month: "short",
    timeZone: "Africa/Nairobi",
  });

const formatTime = (utcDate) =>
  new Date(utcDate).toLocaleTimeString("en-KE", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
    timeZone: "Africa/Nairobi",
  });

export default function Results() {
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);

  const [competitions, setCompetitions] = useState(["All"]);
  const [selectedCompetition, setSelectedCompetition] = useState("All");
  const [selectedDateFilter, setSelectedDateFilter] = useState("All");
  const [search, setSearch] = useState("");

  /* ---------------- Fetch ---------------- */
  useEffect(() => {
    const fetchData = async () => {
      try {
        await loadTeams(); // ensure teamMap is loaded
        const res = await getFinishedMatchesWithPredictions({ months: 2 });
        if (res.success !== false && Array.isArray(res.data?.matches)) {
          const clean = res.data.matches.slice(0, 200).map((m) =>
            attachLogosSafe({
              ...m,
              competition_name:
                COMPETITION_LABELS[m.competition] ||
                COMPETITION_LABELS[m.competition_name] ||
                m.competition ||
                m.competition_name ||
                "Unknown",
            })
          );

          setMatches(clean);

          const comps = Array.from(
            new Set(
              clean
                .map((m) => m.competition_name)
                .filter(Boolean)
                .slice(0, 100)
            )
          );

          // sort so dropdown is predictable
          setCompetitions(["All", ...comps.sort()]);
        }
      } catch (err) {
        console.error("Results fetch error:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  /* ---------------- Prediction correctness ---------------- */
  const isPredictionCorrect = (m) => {
    if (!m.prediction_json || m.home_score == null || m.away_score == null)
      return null;

    const actual =
      m.home_score > m.away_score
        ? "Home Win"
        : m.home_score < m.away_score
        ? "Away Win"
        : "Draw";

    return m.prediction_json.prediction === actual;
  };

  /* ---------------- Filters & Search ---------------- */
  const filtered = useMemo(() => {
    let list = [...matches];

    if (selectedCompetition !== "All") {
      list = list.filter((m) => m.competition_name === selectedCompetition);
    }

    if (search.trim()) {
      const s = search.trim().toLowerCase();
      list = list.filter(
        (m) =>
          (m.home_team_name || "").toLowerCase().includes(s) ||
          (m.away_team_name || "").toLowerCase().includes(s) ||
          (m.competition_name || "").toLowerCase().includes(s)
      );
    }

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);

    if (selectedDateFilter === "Today")
      list = list.filter((m) => new Date(m.utcDate) >= today);
    if (selectedDateFilter === "Yesterday")
      list = list.filter(
        (m) => new Date(m.utcDate) >= yesterday && new Date(m.utcDate) < today
      );
    if (selectedDateFilter === "This Month")
      list = list.filter((m) => new Date(m.utcDate) >= monthStart);

    return list.sort((a, b) => new Date(b.utcDate) - new Date(a.utcDate));
  }, [matches, selectedCompetition, selectedDateFilter, search]);

  /* ---------------- Group by Date ---------------- */
  const grouped = useMemo(() => {
    return filtered.reduce((acc, m) => {
      const key = formatDateGroup(m.utcDate);
      acc[key] = acc[key] || [];
      acc[key].push(m);
      return acc;
    }, {});
  }, [filtered]);

  /* ---------------- Daily summary (now stores correct + total + pct) ---------------- */
  const dailySummary = useMemo(() => {
    const summary = {};
    Object.entries(grouped).forEach(([date, games]) => {
      const total = games.length;
      const correct = games.filter((m) => isPredictionCorrect(m)).length;
      const pct = total ? Math.round((correct / total) * 100) : 0;
      summary[date] = { correct, total, pct };
    });
    return summary;
  }, [grouped]);

  /* ---------------- Rendering ---------------- */
  if (loading) return <Loader text="Loading results..." />;

  return (
    // make the component fit the viewport, add padding, and allow internal scrolling
    <div className="h-screen max-h-screen overflow-auto p-4 space-y-4 bg-gradient-to-b from-slate-50 via-gray-50 to-slate-100">
      {/* (Header removed as requested) */}

      {/* Controls (kept compact and floated) */}
      <div className="flex flex-wrap gap-2 items-center mb-2">
        <input
          type="text"
          placeholder="Search team or competition..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-2 text-sm border rounded-md w-44 focus:outline-none focus:ring-1 focus:ring-blue-300"
          aria-label="Search matches"
        />

        <select
          value={selectedCompetition}
          onChange={(e) => setSelectedCompetition(e.target.value)}
          className="px-3 py-2 text-sm border rounded-md bg-white"
          aria-label="Competition filter"
        >
          {competitions.map((c) => (
            <option key={c} value={c} title={c}>
              {c}
            </option>
          ))}
        </select>

        <select
          value={selectedDateFilter}
          onChange={(e) => setSelectedDateFilter(e.target.value)}
          className="px-3 py-2 text-sm border rounded-md bg-white"
          aria-label="Date filter"
        >
          {["All", "Today", "Yesterday", "This Month"].map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </div>

      {/* Empty state */}
      {Object.keys(grouped).length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-200 p-6 text-center bg-white">
          <p className="text-sm text-gray-500">No results found for the selected filters.</p>
        </div>
      ) : (
        /* Date groups */
        Object.entries(grouped).map(([date, games]) => (
          <section key={date} className="space-y-3">
            {/* Header for the date group */}
            <div className="flex items-center justify-between rounded-lg overflow-hidden bg-white px-3 py-2" style={{ borderBottom: "1px solid rgba(0,0,0,0.04)" }}>
              <div className="flex items-center gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-gray-700">{date}</h3>
                  <div className="text-xs text-gray-500 mt-0.5">
                    {games.length} match{games.length > 1 ? "es" : ""} —{" "}
                    <span className="font-medium text-gray-700">
                      {dailySummary[date].correct}/{dailySummary[date].total} (
                      {dailySummary[date].pct}%)
                    </span>{" "}
                    correct
                  </div>
                </div>

                {/* Show distinct competition chips in the group (max 3) */}
                <div className="flex gap-2 ml-3">
                  {Array.from(
                    new Set(
                      games
                        .map((g) => g.competition_name)
                        .filter(Boolean)
                        .slice(0, 3)
                    )
                  ).map((comp) => (
                    <div
                      key={comp}
                      className={`flex items-center gap-2 px-2 py-0.5 rounded-full text-xs border ${getCompetitionChipClass(
                        comp
                      )}`}
                      aria-hidden
                    >
                      <span className="font-semibold truncate max-w-[90px]">
                        {comp}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="text-xs text-gray-400 hidden sm:block">
                {formatTime(games[0]?.utcDate)} • Latest
              </div>
            </div>

            {/* Cards grid (denser) */}
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
              {games.map((m) => {
                const correct = isPredictionCorrect(m);
                const predText = m.prediction_json?.prediction || "";
                return (
                  <article
                    key={m.match_id || `${m.home_team_name}-${m.away_team_name}-${m.utcDate}`}
                    className="group p-2 rounded-lg border bg-white shadow-sm hover:shadow-md transition flex justify-between items-center gap-2"
                    aria-label={`${m.home_team_name} vs ${m.away_team_name} — ${m.home_score} to ${m.away_score}`}
                  >
                    {/* Left: Teams + logos */}
                    <div className="flex items-center gap-2 min-w-0">
                      <img
                        src={m.home_logo || PLACEHOLDER}
                        onError={(e) => (e.target.src = PLACEHOLDER)}
                        alt={`${m.home_team_name} logo`}
                        className="w-6 h-6 object-contain rounded"
                        loading="lazy"
                      />

                      <div className="min-w-0">
                        <div className="text-[11px] text-gray-500">Home</div>
                        <div className="text-sm font-medium truncate max-w-[110px]">
                          {m.home_team_name}
                        </div>
                      </div>

                      <div className="text-xs text-gray-300 px-1">—</div>

                      <div className="min-w-0">
                        <div className="text-[11px] text-gray-500">Away</div>
                        <div className="text-sm font-medium truncate max-w-[110px]">
                          {m.away_team_name}
                        </div>
                      </div>

                      <img
                        src={m.away_logo || PLACEHOLDER}
                        onError={(e) => (e.target.src = PLACEHOLDER)}
                        alt={`${m.away_team_name} logo`}
                        className="w-6 h-6 object-contain rounded"
                        loading="lazy"
                      />
                    </div>

                    {/* Right: Score + prediction */}
                    <div className="flex flex-col items-end text-xs">
                      <div className="font-bold text-sm">
                        {m.home_score} <span className="text-gray-300">-</span>{" "}
                        {m.away_score}
                      </div>

                      <div className="mt-1 flex items-center gap-2">
                        {/* Prediction badge: green if aligned, red otherwise */}
                        {predText && (
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${
                              correct
                                ? "bg-green-50 text-green-800"
                                : "bg-red-50 text-red-800"
                            }`}
                            aria-label={`Prediction: ${predText} — ${
                              correct ? "Correct" : "Incorrect"
                            }`}
                            title={`Prediction: ${predText}`}
                          >
                            {predText}
                          </span>
                        )}

                        {/* Confidence (if available) */}
                        {typeof m.prediction_json?.confidence === "number" && (
                          <span className="text-[11px] text-gray-400">
                            {Math.round(m.prediction_json.confidence * 100)}%
                          </span>
                        )}
                      </div>

                      <div className="text-gray-400 text-[11px] mt-1">
                        {formatTime(m.utcDate)}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        ))
      )}
    </div>
  );
}
