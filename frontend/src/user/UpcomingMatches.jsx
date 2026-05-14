import React, { useEffect, useState, useRef, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/api";

export default function FixturesPage() {
  const navigate = useNavigate();

  const [fixtures, setFixtures] = useState([]);
  const [selectedDate, setSelectedDate] = useState(
    new Date().toLocaleDateString("en-CA") // ✅ FIX: local date (not UTC)
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const mountedRef = useRef(true);

  const competitionNameMap = {
    "Primera Division": "LaLiga",
    "Premier League": "Premier League",
    "Serie A": "Serie A",
    "Bundesliga": "Bundesliga",
    "Ligue 1": "Ligue 1",
  };

  useEffect(() => {
    mountedRef.current = true;
    loadFixtures();

    const interval = setInterval(loadFixtures, 60000);

    return () => {
      mountedRef.current = false;
      clearInterval(interval);
    };
  }, []);

  async function loadFixtures() {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.getUpcomingMatches();
      if (!mountedRef.current) return;

      if (resp?.success) {
        setFixtures(resp.data?.matches || []);
      } else {
        setFixtures([]);
      }
    } catch (err) {
      if (!mountedRef.current) return;
      setError("Failed to load fixtures");
      setFixtures([]);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }

  // ✅ FIX: Proper timezone-safe parsing
  const getDateObj = (m) => {
    if (m?.timestamp) return new Date(m.timestamp * 1000);

    if (m?.localDate) return new Date(m.localDate);

    if (m?.utcDate || m?.utcdate) {
      const utc = m.utcDate || m.utcdate;
      return new Date(utc); // JS auto converts UTC → local
    }

    return null;
  };

  // ✅ LOCAL date formatter (no UTC bug)
  const formatLocalDate = (date) => {
    if (!date) return null;
    return date.toLocaleDateString("en-CA"); // YYYY-MM-DD (local)
  };

  // ✅ Countdown / status
  const getMatchStatus = (m) => {
    const date = getDateObj(m);
    if (!date) return { label: "--", color: "text-gray-400" };

    const now = Date.now();
    const diff = date.getTime() - now;

    if (diff <= 0) return { label: "LIVE", color: "text-red-600 font-bold" };

    const minutes = Math.floor(diff / 60000);

    if (minutes <= 15) {
      return { label: "Starting Soon", color: "text-orange-500 font-semibold" };
    }

    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;

    return {
      label: `KO in ${hours}h ${mins}m`,
      color: "text-blue-600",
    };
  };

  // ✅ Filter (LOCAL timezone correct)
  const filteredFixtures = useMemo(
    () =>
      fixtures.filter((m) => {
        const d = getDateObj(m);
        if (!d) return false;
        return formatLocalDate(d) === selectedDate;
      }),
    [fixtures, selectedDate]
  );

  // ✅ Group & sort
  const groupedFixtures = useMemo(() => {
    const grouped = filteredFixtures.reduce((acc, m) => {
      if (!acc[m.competition]) acc[m.competition] = [];
      acc[m.competition].push(m);
      return acc;
    }, {});

    Object.keys(grouped).forEach((comp) => {
      grouped[comp].sort((a, b) => {
        const da = getDateObj(a)?.getTime() || 0;
        const db = getDateObj(b)?.getTime() || 0;
        return da - db;
      });
    });

    return grouped;
  }, [filteredFixtures]);

  return (
    <div className="p-4 pt-20 space-y-6">
      {/* Controls */}
      <div className="flex items-center gap-4 mb-4">
        <input
          type="date"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          className="border rounded p-2"
        />
        <button
          onClick={loadFixtures}
          className="bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 transition"
        >
          Refresh
        </button>
      </div>

      {/* Status */}
      {loading && (
        <div className="text-gray-500 flex items-center gap-2">
          <span className="loader h-5 w-5"></span>
          Loading fixtures...
        </div>
      )}
      {error && <div className="text-red-600">{error}</div>}
      {!loading && !error && !filteredFixtures.length && (
        <div className="text-gray-500 text-center py-10">
          No fixtures for this date.
        </div>
      )}

      {/* Fixtures */}
      {Object.entries(groupedFixtures).map(([comp, matches]) => (
        <div key={comp} className="space-y-2">
          <h3 className="text-md font-semibold text-gray-700 border-b pb-1 mb-2">
            {competitionNameMap[comp] || comp}
          </h3>

          {matches.map((m) => {
            const status = getMatchStatus(m);
            const date = getDateObj(m);
            const isSoon =
              date && date.getTime() - Date.now() < 15 * 60 * 1000;

            return (
              <div
                key={m.id}
                role="button"
                tabIndex={0}
                onClick={() => m?.id && navigate(`/matches/${m.id}/overview`)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    m?.id && navigate(`/matches/${m.id}/overview`);
                  }
                }}
                className={`flex items-center justify-between p-3 rounded shadow border transition cursor-pointer hover:shadow-lg hover:scale-[1.01]
                  ${isSoon ? "bg-orange-50 border-orange-300" : "bg-white"}
                `}
              >
                {/* Teams */}
                <div className="flex items-center gap-2">
                  <img src={m.home_logo || "/logo-placeholder.png"} alt="" className="w-6 h-6" />
                  <span className="font-medium">{m.home_team_name}</span>

                  <span className="text-gray-400">vs</span>

                  <img src={m.away_logo || "/logo-placeholder.png"} alt="" className="w-6 h-6" />
                  <span className="font-medium">{m.away_team_name}</span>
                </div>

                {/* Time + Status */}
                <div className="flex flex-col items-end text-sm">
                  <span className={status.color}>{status.label}</span>

                  <span className="text-gray-500">
                    {date
                      ? date.toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "--:--"}
                  </span>

                  <span className="text-gray-400 text-xs">
                    MD {m.matchday}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      ))}

      {/* Loader animation */}
      <style>{`
        .loader {
          border: 3px solid #eee;
          border-top: 3px solid #3498db;
          border-radius: 50%;
          animation: spin 1s linear infinite;
        }
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
