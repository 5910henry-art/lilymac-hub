// src/components/TeamMatchOverview.jsx
import React, { useEffect, useState, useRef } from "react";
import { useParams } from "react-router-dom";
import api from "../api/api";

/**
 * TeamMatchOverview
 * - Unified helpers at top-level (clamp, normalizePct)
 * - Prediction card: no logos, no H2H bars
 * - Match History: shows a single H2H summary above the finished matches list
 * - Responsive bars, loading spinner, gradient hint for history
 */

/* -------------------
   Top-level helpers
   ------------------- */
function clamp(n, lo = 0, hi = 100) {
  return Math.max(lo, Math.min(n, hi));
}

// Accepts 0-1 or 0-100 values and returns 0-100 number
function normalizePct(v) {
  const n = Number(v);
  if (!isFinite(n)) return 0;
  return n >= 0 && n <= 1 ? clamp(n * 100) : clamp(n);
}

/* ====================
   Main component
   ==================== */
export default function TeamMatchOverview() {
  const { matchId: paramId } = useParams();

  const [matches, setMatches] = useState([]);
  const [matchId, setMatchId] = useState(null);
  const [data, setData] = useState(null);
  const [recentMatches, setRecentMatches] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    loadMatches();
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (paramId) {
      const id = Number(paramId);
      if (!Number.isNaN(id)) {
        setMatchId(id);
      }
    }
  }, [paramId]);

  useEffect(() => {
    if (matchId != null) loadOverview(matchId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [matchId]);

  async function loadMatches() {
    try {
      setError(null);
      const r = await api.getUpcomingMatches();
      if (!mountedRef.current) return;

      if (r?.success) {
        const list = r.data?.matches || [];
        setMatches(list);

        if (list.length > 0 && !paramId) {
          setMatchId(Number(list[0].id));
        }
      } else {
        setMatches([]);
      }
    } catch (err) {
      if (!mountedRef.current) return;
      setError("Failed to load matches");
      setMatches([]);
    }
  }

  async function loadOverview(id) {
    if (!id) return;
    setLoading(true);
    setError(null);

    try {
      const [overviewResp, recentResp] = await Promise.all([
        api.getTeamMatchOverview(Number(id)),
        api.getRecentMatches({ limit: 200 }),
      ]);

      if (!mountedRef.current) return;

      setData(overviewResp?.success ? overviewResp.data || null : null);
      setRecentMatches(recentResp?.success ? recentResp.data?.matches || [] : []);
    } catch (err) {
      if (!mountedRef.current) return;
      setError("Failed to load match data");
      setData(null);
      setRecentMatches([]);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }

  // -------------------
  // Helper utilities used by this component
  // -------------------
  function getTeamForm(allMatches = [], teamName, max = 5) {
    if (!teamName) return [];
    return (allMatches || [])
      .filter((m) => [m.home_team_name, m.away_team_name].includes(teamName))
      .sort(
        (a, b) =>
          new Date(b.match_time || b.kickoff || b.date || 0) -
          new Date(a.match_time || a.kickoff || a.date || 0)
      )
      .slice(0, max)
      .map((m) => {
        if (m.home_score == null || m.away_score == null) return null;
        const isHome = m.home_team_name === teamName;
        const tScore = isHome ? Number(m.home_score) : Number(m.away_score);
        const oScore = isHome ? Number(m.away_score) : Number(m.home_score);
        return tScore > oScore ? "W" : tScore < oScore ? "L" : "D";
      })
      .filter(Boolean);
  }

  function calculateStats(team1, team2) {
    if (!recentMatches?.length || !team1 || !team2) {
      return {
        over25: 0,
        btts: 0,
        avgGoals: 0,
        attackHome: 1,
        defenseHome: 1,
        attackAway: 1,
        defenseAway: 1,
      };
    }

    const matches = (recentMatches || [])
      .filter(
        (m) =>
          [m.home_team_name, m.away_team_name].includes(team1) ||
          [m.home_team_name, m.away_team_name].includes(team2)
      )
      .slice(0, 10);

    if (!matches.length) {
      return {
        over25: 0,
        btts: 0,
        avgGoals: 0,
        attackHome: 1,
        defenseHome: 1,
        attackAway: 1,
        defenseAway: 1,
      };
    }

    let over25Count = 0,
      bttsCount = 0,
      totalGoals = 0,
      team1GF = 0,
      team1GA = 0,
      team2GF = 0,
      team2GA = 0;

    matches.forEach((m) => {
      if (m.home_score == null || m.away_score == null) return;
      const h = Number(m.home_score);
      const a = Number(m.away_score);
      totalGoals += h + a;
      if (h + a > 2.5) over25Count++;
      if (h > 0 && a > 0) bttsCount++;

      if (m.home_team_name === team1) {
        team1GF += h;
        team1GA += a;
      } else if (m.away_team_name === team1) {
        team1GF += a;
        team1GA += h;
      }

      if (m.home_team_name === team2) {
        team2GF += h;
        team2GA += a;
      } else if (m.away_team_name === team2) {
        team2GF += a;
        team2GA += h;
      }
    });

    const count = matches.length || 1;
    return {
      over25: Number(((over25Count / count) * 100).toFixed(2)),
      btts: Number(((bttsCount / count) * 100).toFixed(2)),
      avgGoals: Number((totalGoals / count).toFixed(1)),
      attackHome: Number((team1GF / count).toFixed(1)),
      defenseHome: Number((team1GA / count).toFixed(1)),
      attackAway: Number((team2GF / count).toFixed(1)),
      defenseAway: Number((team2GA / count).toFixed(1)),
    };
  }

  function formColor(c) {
    return c === "W"
      ? "bg-green-500 text-white"
      : c === "L"
      ? "bg-red-500 text-white"
      : "bg-yellow-400 text-black";
  }

  // -------------------
  // Derived values
  // -------------------
  const h2h = data?.h2h_stats || null;
  const past = data?.past_predictions || [];
  const next = data?.next_match_prediction || null;

  const finishedMatches =
    (h2h?.matches || []).filter((m) => m.home_score != null && m.away_score != null) || [];

  const homeForm = next ? getTeamForm(recentMatches, next.home_team) : [];
  const awayForm = next ? getTeamForm(recentMatches, next.away_team) : [];

  const stats = next
    ? calculateStats(next.home_team, next.away_team)
    : {
        over25: 0,
        btts: 0,
        avgGoals: 0,
        attackHome: 1,
        defenseHome: 1,
        attackAway: 1,
        defenseAway: 1,
      };

  // -------------------
  // Render
  // -------------------
  if (!loading && !data && !error && !matches.length) {
    return <div className="p-6 text-gray-500">No match analysis available</div>;
  }

  if (!matchId && paramId) {
    return <div className="p-6 text-gray-500">Invalid match ID</div>;
  }

  return (
    <div className="space-y-6 p-4">
      {/* Top controls */}
      <div className="bg-gray-50 p-4 rounded-xl shadow border">
        <h2 className="text-gray-800 font-semibold mb-3">Select Upcoming Match</h2>

        <select
          aria-label="Select match"
          value={matchId ?? ""}
          onChange={(e) => setMatchId(Number(e.target.value))}
          className="w-full p-2 rounded border bg-white"
        >
          {matches.map((m) => (
            <option key={m.id} value={m.id}>
              {m.home_team_name} vs {m.away_team_name}
            </option>
          ))}
        </select>

        {error && <div className="mt-2 text-red-600 text-sm">{error}</div>}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-gray-500">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-500" />
          Loading analysis...
        </div>
      )}

      {/* Prediction - logos removed and H2H bars removed from here */}
      {next && (
        <div className="bg-gradient-to-r from-green-50 to-green-100 p-4 rounded-xl shadow border border-green-300">
          <h2 className="text-green-800 font-semibold mb-4">Match Prediction</h2>

          <div className="flex items-center gap-3 mb-4">
            <span className="text-gray-800 font-medium">{next.home_team}</span>
            <span className="text-gray-500">vs</span>
            <span className="text-gray-800 font-medium">{next.away_team}</span>
          </div>

          <div className="flex items-center justify-between mb-4">
            <div className="text-lg font-bold text-green-700">{next.prediction || "-"}</div>

            <div className="text-gray-600 text-sm">
              Confidence:{" "}
              {next.confidence != null
                ? `${normalizePct(Number(next.confidence)).toFixed(0)}%`
                : "-"}
            </div>
          </div>
        </div>
      )}

      {/* Recent Form & Stats */}
      <div className="bg-gray-50 p-4 rounded-xl shadow border">
        <h2 className="text-gray-800 font-semibold mb-3">Recent Form & Stats</h2>

        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            {homeForm.length > 0 ? (
              homeForm.map((c, i) => (
                <span
                  key={`hform-${i}`}
                  title={c === "W" ? "Win" : c === "L" ? "Loss" : "Draw"}
                  className={`w-7 h-7 flex items-center justify-center rounded text-xs font-bold ${formColor(
                    c
                  )}`}
                >
                  {c}
                </span>
              ))
            ) : (
              <span className="text-gray-400">No recent results</span>
            )}

            <span className="text-gray-500 px-2">vs</span>

            {awayForm.length > 0 ? (
              awayForm.map((c, i) => (
                <span
                  key={`aform-${i}`}
                  title={c === "W" ? "Win" : c === "L" ? "Loss" : "Draw"}
                  className={`w-7 h-7 flex items-center justify-center rounded text-xs font-bold ${formColor(
                    c
                  )}`}
                >
                  {c}
                </span>
              ))
            ) : (
              <span className="text-gray-400">No recent results</span>
            )}
          </div>

          <div className="flex flex-col gap-2 ml-auto w-full max-w-lg">
            <div className="flex gap-4 flex-wrap">
              <HorizontalStat label="Over 2.5" rawValue={stats.over25} color="bg-green-500" />
              <HorizontalStat label="BTTS" rawValue={stats.btts} color="bg-blue-500" />
              <HorizontalStat label="Avg Goals" rawValue={stats.avgGoals} color="bg-purple-500" />
            </div>

            <HorizontalStrength label="Attack Home" value={stats.attackHome} color="bg-green-500" />
            <HorizontalStrength label="Defense Home" value={stats.defenseHome} color="bg-red-500" />
            <HorizontalStrength label="Attack Away" value={stats.attackAway} color="bg-blue-500" />
            <HorizontalStrength label="Defense Away" value={stats.defenseAway} color="bg-red-700" />
          </div>
        </div>
      </div>

      {/* Match History */}
      {finishedMatches.length > 0 && (
        <div className="bg-gray-50 p-4 rounded-xl shadow border relative overflow-y-auto max-h-96">
          <div className="absolute bottom-0 left-0 right-0 h-10 bg-gradient-to-t from-gray-50 pointer-events-none" />
          <h2 className="text-gray-800 font-semibold mb-2">Match History & Model Performance</h2>

          {/* General H2H summary displayed once above the list */}
          {h2h && (
            <div className="flex gap-3 text-sm text-gray-700 mb-3">
              <span>Home Win {normalizePct(h2h.home_win_rate).toFixed(2)}%</span>
              <span>Draw {normalizePct(h2h.draw_rate).toFixed(2)}%</span>
              <span>Away Win {normalizePct(h2h.away_win_rate).toFixed(2)}%</span>
            </div>
          )}

          <div className="space-y-3">
            {finishedMatches.map((m) => {
              const pred = past.find((p) => p.match_id === m.match_id);

              return (
                <div key={m.match_id} className="bg-white p-3 rounded border flex flex-col gap-1">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <img
                        src={m.home_logo || "/logo-placeholder.png"}
                        alt={`${m.home_team_name} logo`}
                        className="w-5 h-5 object-contain"
                      />
                      <span className="text-gray-800">{m.home_team_name}</span>
                      <span className="text-gray-400">vs</span>
                      <img
                        src={m.away_logo || "/logo-placeholder.png"}
                        alt={`${m.away_team_name} logo`}
                        className="w-5 h-5 object-contain"
                      />
                      <span className="text-gray-800">{m.away_team_name}</span>
                    </div>

                    <div className="font-bold text-gray-900">{m.home_score}-{m.away_score}</div>
                  </div>

                  {pred && (
                    <div className="flex justify-between text-sm mt-1">
                      <span className="text-gray-500">Prediction: {pred.prediction}</span>
                      <span
                        className={
                          pred.correct ? "text-green-600 font-semibold" : "text-red-600 font-semibold"
                        }
                      >
                        {pred.correct ? "✔ Correct" : "✖ Wrong"}
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/* ====================
   Reusable sub-components
   ==================== */

function Bar({ label, rawValue, color = "bg-purple-500", title }) {
  const pct = normalizePct(rawValue);
  return (
    <div className="flex flex-col items-center" title={title}>
      <div className="flex justify-between text-sm text-gray-600 mb-1 w-28">
        <span>{label}</span>
        <span className="font-semibold text-gray-800">{pct.toFixed(2)}%</span>
      </div>
      <div className="w-28 bg-gray-200 h-3 rounded">
        <div className={`${color} h-3 rounded`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function HorizontalStat({ label, rawValue, color = "bg-purple-500" }) {
  if (label === "Avg Goals") {
    const num = Number(rawValue) || 0;
    const pct = Math.min((num / 5) * 100, 100);
    return (
      <div className="flex flex-col items-start w-28">
        <div className="flex justify-between text-xs text-gray-600 mb-1 w-full">
          <span>{label}</span>
          <span className="font-semibold text-gray-800">{num.toFixed(1)}</span>
        </div>
        <div className="w-full bg-gray-200 h-3 rounded">
          <div className={`${color} h-3 rounded`} style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  }

  const pct = normalizePct(rawValue);
  return (
    <div className="flex flex-col items-start w-28">
      <div className="flex justify-between text-xs text-gray-600 mb-1 w-full">
        <span>{label}</span>
        <span className="font-semibold text-gray-800">{pct.toFixed(2)}%</span>
      </div>
      <div className="w-full bg-gray-200 h-3 rounded">
        <div className={`${color} h-3 rounded`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function HorizontalStrength({ label, value, color = "bg-purple-500" }) {
  const num = Number(value) || 0;
  const percent = Math.min((num / 5) * 100, 100);
  return (
    <div className="flex flex-col w-full">
      <div className="flex justify-between text-xs text-gray-600 mb-1">
        <span>{label}</span>
        <span>{num}</span>
      </div>
      <div className="w-full bg-gray-200 h-3 rounded">
        <div className={`${color} h-3 rounded`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
