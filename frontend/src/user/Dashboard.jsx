// src/user/Dashboard.jsx
import React, { useEffect, useState, memo, useRef, useLayoutEffect } from "react";
import { Card } from "../components/ui/card";
import { fetchDashboard } from "../api/api";

// Confidence card glow styles
const CONF_COLORS = {
  High: "shadow-lg shadow-green-400/60 border-green-400",
  Medium: "shadow-md shadow-yellow-400/60 border-yellow-400",
  Low: "shadow-md shadow-red-500/70 border-red-500",
};

// Odds text color
const ODDS_COLORS = (odds) => (odds <= 1.5 ? "text-green-600" : "text-red-600");

// Helpers
function getMatchDateStrings(raw) {
  if (!raw) return { utc: null, local: null };
  try {
    const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
    const d = new Date(normalized);
    if (isNaN(d)) return { utc: null, local: null };
    return { utc: d.toISOString().slice(0, 10), local: d.toLocaleDateString("en-CA") };
  } catch {
    return { utc: null, local: null };
  }
}

function getCountdown(matchTime, status, now) {
  if (!matchTime || status === "FINISHED") return "—";
  const normalized = matchTime.includes("T") ? matchTime : matchTime.replace(" ", "T");
  const diff = new Date(normalized).getTime() - now;
  if (isNaN(diff)) return "—";
  if (diff <= 0) return "LIVE";
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  const s = Math.floor((diff % 60000) / 1000);
  return `${String(h).padStart(2, "0")}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
}

// ---------------- Prediction Card ----------------
const PredictionCard = memo(({ match, now, isVIP }) => {
  const countdown = getCountdown(match.match_time, match.status, now);
  const matchTime = match.match_time
    ? new Date(match.match_time.replace(" ", "T")).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "-";

  return (
    <Card
      className={`min-w-[240px] max-w-[260px] p-4 rounded-xl border flex-shrink-0 relative
        ${isVIP ? "border-yellow-400 bg-yellow-50" : "border-gray-200 bg-white"}
        ${CONF_COLORS[match.confidence] || ""}`}
    >
      <div className="flex justify-between items-center mb-2">
        <div className="font-semibold text-sm truncate">
          {match.home_team} vs {match.away_team}
        </div>
        {isVIP && (
          <span className="text-yellow-700 font-bold text-xs px-2 py-0.5 rounded bg-yellow-200">
            VIP
          </span>
        )}
      </div>

      <div className="flex justify-between items-center text-xs text-gray-500 mb-2">
        <span>🕒 {matchTime}</span>
        <span className="font-mono">{countdown}</span>
      </div>

      <div className="flex justify-between items-center bg-gray-50 rounded p-2 mb-2">
        <div className="flex-1 text-sm">
          <div className="font-semibold">
            {match.prediction} {match.threshold || ""}
          </div>
          <div className={`text-xs ${ODDS_COLORS(match.odds)}`}>
            Odds: {match.odds ? Number(match.odds).toFixed(2) : "-"}
          </div>
        </div>
      </div>

      <div className="flex justify-between items-center text-xs text-gray-500">
        <span>Status: {match.status}</span>
        <span
          className={`font-semibold ${
            match.result === "won"
              ? "text-green-600"
              : match.result === "lost"
              ? "text-red-600"
              : "text-gray-600"
          }`}
        >
          {match.result?.toUpperCase() || "PENDING"}
        </span>
      </div>
    </Card>
  );
});

// ---------------- Dashboard ----------------
export default function Dashboard() {
  const [predictions, setPredictions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(Date.now());
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().slice(0, 10));
  const [stats, setStats] = useState({
    totalMatches: 0,
    HOME: { rate: 0, count: 0 },
    AWAY: { rate: 0, count: 0 },
    DRAW: { rate: 0, count: 0 },
    YES: { rate: 0, count: 0 },
    OVER: { rate: 0, count: 0 },
    GENERAL: { rate: 0, count: 0 },
    liveGames: 0,
  });

  const topRef = useRef(null);
  const titleRef = useRef(null);
  const scrollRef = useRef(null);
  const [scrollMaxHeight, setScrollMaxHeight] = useState("300px");

  // Update now every second
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // Fetch dashboard
  const loadDashboard = async () => {
    setLoading(true);
    try {
      const res = await fetchDashboard();
      const filtered = (res.data.matches || []).filter((row) => {
        const { utc, local } = getMatchDateStrings(row.match_time);
        return utc === selectedDate || local === selectedDate;
      });
      setPredictions(filtered);
      setStats({
        totalMatches: filtered.length,
        HOME: { rate: res.data.match_outcome_win_rate?.HOME || 0, count: res.data.match_outcome_counts?.HOME || 0 },
        AWAY: { rate: res.data.match_outcome_win_rate?.AWAY || 0, count: res.data.match_outcome_counts?.AWAY || 0 },
        DRAW: { rate: res.data.match_outcome_win_rate?.DRAW || 0, count: res.data.match_outcome_counts?.DRAW || 0 },
        YES: { rate: res.data.yes_win_rate || 0, count: res.data.yes_count || 0 },
        OVER: { rate: res.data.over_win_rate || 0, count: res.data.over_count || 0 },
        GENERAL: { rate: res.data.general_win_rate || 0, count: res.data.general_count || 0 },
        liveGames: filtered.filter((m) => !["TIMED", "FINISHED", "SCHEDULED"].includes(m.status)).length,
      });
    } catch (err) {
      console.error("Failed to fetch dashboard:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDashboard();
  }, [selectedDate]);

  useLayoutEffect(() => {
    function recalcHeight() {
      const topHeight = topRef.current?.getBoundingClientRect().height || 0;
      const bottomHeight = document.querySelector(".bottom-nav")?.getBoundingClientRect().height || 0;
      const padding = 80;
      const maxH = Math.max(120, window.innerHeight - topHeight - bottomHeight - padding);
      setScrollMaxHeight(`${maxH}px`);
    }
    recalcHeight();
    window.addEventListener("resize", recalcHeight);
    return () => window.removeEventListener("resize", recalcHeight);
  }, [loading, predictions.length]);

  const STATS_COLORS = [
    "bg-pink-100 text-pink-700",
    "bg-green-100 text-green-700",
    "bg-yellow-100 text-yellow-700",
    "bg-blue-100 text-blue-700",
    "bg-purple-100 text-purple-700",
    "bg-red-100 text-red-700",
    "bg-indigo-100 text-indigo-700",
    "bg-teal-100 text-teal-700",
  ];

  return (
    <div className="min-h-screen w-full flex flex-col bg-transparent p-4 md:p-6">
      {/* Top Stats & Date Selector */}
      <div ref={topRef} className="flex-shrink-0 z-20">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl md:text-3xl font-bold bg-gradient-to-r from-purple-600 via-pink-500 to-indigo-500 bg-clip-text text-transparent">
            Smart Predictions • Better Wins
          </h1>
          <button
            onClick={loadDashboard}
            className="px-3 py-1 rounded bg-blue-500 text-white hover:bg-blue-600 text-sm"
          >
            🔄 Refresh
          </button>
        </div>

        <div className="mt-3 mb-4">
          <label className="mr-2 font-semibold">Select Date:</label>
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="border rounded p-1"
          />
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3 mb-4">
          {[
            { label: "Matches", value: stats.totalMatches },
            { label: "HOME %", value: stats.HOME.rate },
            { label: "AWAY %", value: stats.AWAY.rate },
            { label: "DRAW %", value: stats.DRAW.rate },
            { label: "YES %", value: stats.YES.rate },
            { label: "OVER %", value: stats.OVER.rate },
            { label: "General %", value: stats.GENERAL.rate },
            { label: "Live", value: stats.liveGames },
          ].map((item, i) => (
            <Card key={i} className={`rounded-xl shadow-sm ${STATS_COLORS[i]}`}>
              <div className="p-3 text-center">
                <div className="text-xs font-semibold">{item.label}</div>
                <div className="font-bold text-lg">{item.label.includes("%") ? Math.round(item.value) + "%" : item.value}</div>
              </div>
            </Card>
          ))}
        </div>

        {/* Lilymac Betting Hub description */}
        <div className="mb-4 p-4 bg-purple-50 rounded-lg text-gray-700">
          <h2 className="font-semibold text-lg mb-2"></h2>
          <p>
            Welcome to Lilymac Predictions Hub, your trusted platform for accurate and smart betting insights. 
            We provide daily top predictions, live updates, and VIP tips to help you make informed decisions 
            and enjoy smarter wins every day. Join our community and elevate your betting strategy with confidence.
          </p>
        </div>
      </div>

      {/* Predictions Scroll (Horizontal) */}
      <div className="flex-1 relative">
        <Card className="h-full rounded-2xl shadow-lg border border-transparent flex flex-col p-4 relative">
          <h3 ref={titleRef} className="text-lg font-bold mb-3 text-red-600">
            🔥 Top Predictions
          </h3>

          <div
            ref={scrollRef}
            className="overflow-x-auto overflow-y-hidden flex flex-row space-x-3 pb-4 scroll-smooth snap-x snap-mandatory"
            style={{ maxHeight: scrollMaxHeight }}
          >
            {loading ? (
              <div className="flex items-center justify-center w-full py-8 text-gray-500">Loading...</div>
            ) : predictions.length === 0 ? (
              <div className="flex items-center justify-center w-full py-8 text-gray-500">
                No predictions for this date.
              </div>
            ) : (
              predictions.map((match) => (
                <div key={match.id} className="snap-start">
                  <PredictionCard match={match} now={now} isVIP={match.is_vip} />
                </div>
              ))
            )}
          </div>

          <div className="pointer-events-none absolute bottom-0 left-0 w-full h-6 bg-gradient-to-t from-white to-transparent" />
        </Card>
      </div>
    </div>
  );
}
