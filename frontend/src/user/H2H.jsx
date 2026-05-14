// src/pages/H2H.jsx
import React, { useEffect, useState, useMemo } from "react";
import { getTeams, getH2H, attachLogosSafe } from "../api/api";
import Loader from "../components/Loader";

const PLACEHOLDER = "/logos/placeholder.png";

const formatDate = (utcDate) =>
  new Date(utcDate).toLocaleDateString("en-KE", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Africa/Nairobi",
  });

export default function H2H() {
  const [teams, setTeams] = useState([]);
  const [homeId, setHomeId] = useState("");
  const [awayId, setAwayId] = useState("");
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);

  const homeTeam = useMemo(() => teams.find((t) => t.id === Number(homeId)), [teams, homeId]);
  const awayTeam = useMemo(() => teams.find((t) => t.id === Number(awayId)), [teams, awayId]);

  // Load teams first (ensures teamMap / crests are available)
  useEffect(() => {
    let mounted = true;
    const fetchTeams = async () => {
      setLoading(true);
      try {
        const res = await getTeams();
        if (res?.success && Array.isArray(res.data?.teams)) {
          if (!mounted) return;
          setTeams(res.data.teams);
          setHomeId(String(res.data.teams[0]?.id || ""));
          setAwayId(String(res.data.teams[1]?.id || ""));
        } else {
          // fallback: empty teams
          if (!mounted) return;
          setTeams([]);
          setHomeId("");
          setAwayId("");
        }
      } catch (err) {
        console.error("Failed to load teams:", err);
        if (mounted) {
          setTeams([]);
          setHomeId("");
          setAwayId("");
        }
      } finally {
        if (mounted) setLoading(false);
      }
    };

    fetchTeams();
    return () => {
      mounted = false;
    };
  }, []);

  // Load H2H matches — attach logos BEFORE setting state to avoid blinking
  useEffect(() => {
    let mounted = true;
    const fetchH2H = async () => {
      if (!homeId || !awayId) return;
      setLoading(true);
      try {
        const res = await getH2H(homeId, awayId, 50);
        if (!res?.success || !Array.isArray(res.data?.matches)) {
          if (mounted) setMatches([]);
          return;
        }

        // Attach logos safely to every match before render
        const processed = res.data.matches.map((m) => {
          // attachLogosSafe returns an object with home_logo/away_logo (defaults handled)
          try {
            const withLogos = attachLogosSafe(m, "home_team_name", "away_team_name", "home_team_id", "away_team_id");
            // ensure keys expected by component exist
            return {
              ...m,
              home_logo: withLogos.home_logo || m.home_logo || PLACEHOLDER,
              away_logo: withLogos.away_logo || m.away_logo || PLACEHOLDER,
              home_team_name: m.home_team_name || m.home_team || m.home || "",
              away_team_name: m.away_team_name || m.away_team || m.away || "",
            };
          } catch (err) {
            // fallback: don't crash if attachLogosSafe misbehaves
            return {
              ...m,
              home_logo: m.home_logo || PLACEHOLDER,
              away_logo: m.away_logo || PLACEHOLDER,
            };
          }
        });

        if (mounted) setMatches(processed);
      } catch (err) {
        console.error("Failed to load H2H:", err);
        if (mounted) setMatches([]);
      } finally {
        if (mounted) setLoading(false);
      }
    };

    fetchH2H();
    return () => {
      mounted = false;
    };
  }, [homeId, awayId]);

  const swapTeams = () => {
    const tmp = homeId;
    setHomeId(awayId);
    setAwayId(tmp);
  };

  const groupedMatches = useMemo(() => {
    return matches.reduce((acc, m) => {
      const key = formatDate(m.date_played || m.match_date || m.date || new Date());
      acc[key] = acc[key] || [];
      acc[key].push(m);
      return acc;
    }, {});
  }, [matches]);

  const getResultType = (m) => {
    if ((m.home_score ?? 0) > (m.away_score ?? 0)) return "Home Win";
    if ((m.home_score ?? 0) < (m.away_score ?? 0)) return "Away Win";
    return "Draw";
  };

  const getBadgeClass = (result, m) => {
    const type = getResultType(m);
    if (type === "Draw") return "bg-gray-100 text-gray-800";
    if (
      (type === "Home Win" && m.home_team_id === Number(homeId)) ||
      (type === "Away Win" && m.away_team_id === Number(homeId))
    )
      return "bg-green-50 text-green-800";
    return "bg-red-50 text-red-800";
  };

  const summary = useMemo(() => {
    let homeWins = 0;
    let awayWins = 0;
    let draws = 0;
    matches.forEach((m) => {
      const type = getResultType(m);
      if (type === "Draw") draws++;
      else if (
        (type === "Home Win" && m.home_team_id === Number(homeId)) ||
        (type === "Away Win" && m.away_team_id === Number(homeId))
      )
        homeWins++;
      else awayWins++;
    });
    return { homeWins, awayWins, draws, total: matches.length };
  }, [matches, homeId]);

  if (loading) return <Loader text="Loading H2H..." />;

  return (
    <div className="h-screen max-h-screen overflow-auto pt-12 px-4 bg-gray-50 space-y-4 pb-24">
      {/* Team selectors */}
      <div className="flex flex-wrap gap-2 items-center mb-2">
        <select
          value={homeId}
          onChange={(e) => setHomeId(e.target.value)}
          className="px-3 py-2 border rounded-md bg-white text-sm"
        >
          {teams.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>

        <button
          onClick={swapTeams}
          className="px-2 py-1 bg-gray-200 rounded hover:bg-gray-300 text-sm"
        >
          ↔ Swap
        </button>

        <select
          value={awayId}
          onChange={(e) => setAwayId(e.target.value)}
          className="px-3 py-2 border rounded-md bg-white text-sm"
        >
          {teams.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </div>

      {/* Matches List */}
      {matches.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-200 p-6 text-center bg-white">
          <p className="text-sm text-gray-500">No head-to-head matches found.</p>
        </div>
      ) : (
        Object.entries(groupedMatches).map(([date, games]) => (
          <section key={date} className="space-y-2">
            <div className="flex justify-between items-center bg-white px-3 py-1 rounded-lg border shadow-sm">
              <h3 className="text-sm font-semibold text-gray-700">{date}</h3>
              <div className="text-xs text-gray-500">
                {games.length} match{games.length > 1 ? "es" : ""}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
              {games.map((m) => (
                <article
                  key={m.match_id ?? m.id}
                  className="flex justify-between items-center p-2 bg-white border rounded-lg shadow-sm hover:shadow-md transition"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <img
                      src={m.home_logo || PLACEHOLDER}
                      alt={m.home_team_name}
                      className="w-6 h-6 object-contain rounded"
                      onError={(e) => (e.target.src = PLACEHOLDER)}
                      loading="lazy"
                    />
                    <div className="truncate text-sm font-medium max-w-[80px]">{m.home_team_name}</div>
                    <span className="text-xs text-gray-400 px-1">-</span>
                    <div className="truncate text-sm font-medium max-w-[80px]">{m.away_team_name}</div>
                    <img
                      src={m.away_logo || PLACEHOLDER}
                      alt={m.away_team_name}
                      className="w-6 h-6 object-contain rounded"
                      onError={(e) => (e.target.src = PLACEHOLDER)}
                      loading="lazy"
                    />
                  </div>

                  <div className="flex flex-col items-end">
                    <div className="text-sm font-bold text-gray-700">
                      {m.home_score ?? 0} - {m.away_score ?? 0}
                    </div>
                    <span
                      className={`mt-1 px-2 py-0.5 rounded-full text-xs font-semibold ${getBadgeClass(
                        getResultType(m),
                        m
                      )}`}
                    >
                      {getResultType(m)}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          </section>
        ))
      )}

      {/* Summary section at the bottom */}
      {matches.length > 0 && (
        <div className="flex flex-wrap gap-4 bg-white p-4 rounded-lg shadow-sm border border-indigo-100 mt-6">
          <div className="text-sm text-gray-700 font-bold">Total Matches: {summary.total}</div>
          <div className="text-sm text-green-700 font-bold">
            {homeTeam?.name || "Home"} Wins: {summary.homeWins}
          </div>
          <div className="text-sm text-red-700 font-bold">
            {awayTeam?.name || "Away"} Wins: {summary.awayWins}
          </div>
          <div className="text-sm text-gray-500 font-bold">Draws: {summary.draws}</div>
        </div>
      )}
    </div>
  );
}
