// src/pages/Predictions.jsx
import React, { useEffect, useMemo, useState } from "react";
import { getPredictionsLatest, loadTeams } from "../api/domain";
import Loader from "../components/Loader";
import { motion, AnimatePresence } from "framer-motion";

const PLACEHOLDER = "/logos/placeholder.png";

/* 🔁 Competition name normalization */
const COMPETITION_LABELS = {
  "Primera Division": "LaLiga",
};

export default function Predictions() {
  const [predictions, setPredictions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [competitions, setCompetitions] = useState([]);
  const [selectedCompetition, setSelectedCompetition] = useState("All");
  const [selectedDateFilter, setSelectedDateFilter] = useState("All");
  const [searchTerm, setSearchTerm] = useState("");
  const [sortOrder, setSortOrder] = useState("asc");
  const [showTopPredictions, setShowTopPredictions] = useState(false);
  const [nowUtc, setNowUtc] = useState(new Date());

  /* ---------------- Time updater ---------------- */
  useEffect(() => {
    const timer = setInterval(() => setNowUtc(new Date()), 60 * 1000);
    return () => clearInterval(timer);
  }, []);

  /* ---------------- Utils ---------------- */
  const toEAT = (utcDate) => {
    if (!utcDate) return "TBA";
    try {
      return (
        new Date(utcDate).toLocaleString("en-KE", {
          weekday: "short",
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
          hour12: true,
          timeZone: "Africa/Nairobi",
        }) + " EAT"
      );
    } catch {
      return "Invalid Date";
    }
  };

  const formatPercent = (num) => `${((num ?? 0) * 100).toFixed(1)}%`;

  const predictionBadge = (pred) => {
    switch (pred) {
      case "Home Win":
        return "bg-emerald-100 text-emerald-700";
      case "Draw":
        return "bg-amber-100 text-amber-700";
      case "Away Win":
        return "bg-rose-100 text-rose-700";
      default:
        return "bg-gray-100 text-gray-600";
    }
  };

  /* ---------------- Fetch ---------------- */
  useEffect(() => {
    const fetchData = async () => {
      try {
        // 🚀 parallel loading
        const [_, res] = await Promise.all([
          loadTeams(),
          getPredictionsLatest(),
        ]);

        if (res.success && Array.isArray(res.data.predictions)) {
          const clean = res.data.predictions.map((p) => ({
            ...p,
            competition_name:
              COMPETITION_LABELS[p.competition_name] || p.competition_name,
            home_logo: p.home_logo || PLACEHOLDER,
            away_logo: p.away_logo || PLACEHOLDER,
            home_team_name: p.home_team_name || "Home",
            away_team_name: p.away_team_name || "Away",
          }));

          setPredictions(clean);

          setCompetitions(
            Array.from(
              new Set(clean.map((p) => p.competition_name).filter(Boolean))
            )
          );
        } else {
          console.error("Invalid response:", res);
          setError("Invalid data received.");
        }
      } catch (err) {
        console.error(err);
        setError("Failed to load predictions.");
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  /* ---------------- Filters ---------------- */
  const filtered = useMemo(() => {
    // ⏱ small buffer to prevent missing matches
    const now = new Date(nowUtc.getTime() - 5 * 60 * 1000);

    let list = predictions.filter(
      (p) => p.utcDate && new Date(p.utcDate) >= now
    );

    if (selectedCompetition !== "All") {
      list = list.filter((p) => p.competition_name === selectedCompetition);
    }

    if (searchTerm.trim()) {
      const q = searchTerm.toLowerCase();
      list = list.filter(
        (p) =>
          p.home_team_name.toLowerCase().includes(q) ||
          p.away_team_name.toLowerCase().includes(q)
      );
    }

    // Date ranges
    const today = new Date(nowUtc);
    today.setHours(0, 0, 0, 0);

    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);

    const dayAfterTomorrow = new Date(today);
    dayAfterTomorrow.setDate(today.getDate() + 2);

    const endOfWeek = new Date(today);
    endOfWeek.setDate(today.getDate() + 7);

    const endOfMonth = new Date(
      today.getFullYear(),
      today.getMonth() + 1,
      0,
      23,
      59,
      59
    );

    if (selectedDateFilter !== "All") {
      list = list.filter((p) => {
        const d = new Date(p.utcDate);
        switch (selectedDateFilter) {
          case "Today":
            return d >= today && d < tomorrow;
          case "Tomorrow":
            return d >= tomorrow && d < dayAfterTomorrow;
          case "This Week":
            return d >= today && d <= endOfWeek;
          case "This Month":
            return d >= today && d <= endOfMonth;
          default:
            return true;
        }
      });
    }

    // ⭐ improved top prediction logic
    if (showTopPredictions) {
      list = list.filter((p) => {
        const probs = p.prediction?.probabilities ?? {};
        const maxProb = Math.max(
          probs.home_win || 0,
          probs.draw || 0,
          probs.away_win || 0
        );
        return maxProb >= 0.6;
      });
    }

    return list.sort((a, b) =>
      sortOrder === "asc"
        ? new Date(a.utcDate) - new Date(b.utcDate)
        : new Date(b.utcDate) - new Date(a.utcDate)
    );
  }, [
    predictions,
    selectedCompetition,
    selectedDateFilter,
    searchTerm,
    sortOrder,
    showTopPredictions,
    nowUtc,
  ]);

  const groupedByDate = useMemo(() => {
    return filtered.reduce((acc, p) => {
      const key = new Date(p.utcDate).toLocaleDateString("en-KE", {
        weekday: "long",
        day: "numeric",
        month: "short",
      });
      acc[key] = acc[key] || [];
      acc[key].push(p);
      return acc;
    }, {});
  }, [filtered]);

  /* ---------------- Render ---------------- */
  if (loading) return <Loader text="Loading predictions..." />;
  if (error) return <p className="text-red-500">{error}</p>;

  return (
    <div className="space-y-6 pt-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <input
          placeholder="Search team"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="px-3 py-1.5 border rounded-md text-sm"
        />

        <select
          value={selectedCompetition}
          onChange={(e) => setSelectedCompetition(e.target.value)}
          className="px-3 py-1.5 border rounded-md text-sm"
        >
          <option value="All">All Competitions</option>
          {competitions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>

        <select
          value={selectedDateFilter}
          onChange={(e) => setSelectedDateFilter(e.target.value)}
          className="px-3 py-1.5 border rounded-md text-sm"
        >
          {["All", "Today", "Tomorrow", "This Week", "This Month"].map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>

        <button
          onClick={() => setShowTopPredictions((v) => !v)}
          className="px-3 py-1.5 border rounded-md text-sm"
        >
          {showTopPredictions ? "Top 60% Only" : "Filter Top 60%"}
        </button>

        <button
          onClick={() =>
            setSortOrder(sortOrder === "asc" ? "desc" : "asc")
          }
          className="px-3 py-1.5 border rounded-md text-sm"
        >
          {sortOrder === "asc" ? "Earliest → Latest" : "Latest → Earliest"}
        </button>
      </div>

      {/* Results */}
      {Object.keys(groupedByDate).length === 0 ? (
        <p className="text-center text-gray-500">No predictions found.</p>
      ) : (
        Object.entries(groupedByDate).map(([date, preds]) => (
          <div key={date} className="space-y-3">
            <h3 className="text-sm font-semibold text-gray-600">{date}</h3>

            <AnimatePresence>
              {preds.map((p) => {
                const probs = p.prediction?.probabilities ?? {
                  home_win: 0,
                  draw: 0,
                  away_win: 0,
                };

                return (
                  <motion.div
                    key={p.match_id ?? `${p.utcDate}-${p.home_team_name}`}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className="p-4 rounded-xl border bg-white shadow-md"
                  >
                    <div className="flex justify-between items-center">
                      <div className="flex items-center gap-2">
                        <img src={p.home_logo} className="w-6 h-6" />
                        <span>{p.home_team_name}</span>
                        <span>vs</span>
                        <span>{p.away_team_name}</span>
                        <img src={p.away_logo} className="w-6 h-6" />
                      </div>

                      <span className={`text-xs px-2 py-0.5 rounded ${predictionBadge(p.prediction?.prediction)}`}>
                        {p.prediction?.prediction || "-"}
                      </span>
                    </div>

                    <div className="text-xs text-gray-500 mt-1">
                      🕒 {toEAT(p.utcDate)}
                    </div>

                    <div className="mt-2 flex gap-2">
                      {["home_win", "draw", "away_win"].map((key) => {
                        const prob = probs[key] ?? 0;
                        const label = key === "home_win" ? "H" : key === "draw" ? "D" : "A";

                        return (
                          <div key={key} className="flex-1 text-xs">
                            <div className="flex justify-between">
                              <span>{label}</span>
                              <span>{formatPercent(prob)}</span>
                            </div>
                            <div className="h-2 bg-gray-200 rounded">
                              <div
                                className="h-2 rounded bg-blue-500"
                                style={{ width: `${prob * 100}%` }}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>
        ))
      )}
    </div>
  );
}
