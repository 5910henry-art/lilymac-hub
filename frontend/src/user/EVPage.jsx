// src/user/EVPage.jsx

import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/api";

export default function EVPage() {
  const navigate = useNavigate();

  const [bookmarks, setBookmarks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // =========================================================
  // LOAD EV DATA
  // =========================================================

  useEffect(() => {
    let mounted = true;

    async function loadEV() {
      try {
        setLoading(true);
        setError("");

        const resp = await api.getAllBookmarks();

        if (!mounted) return;

        if (resp?.success) {
          const data = resp?.data?.bookmarks || [];

          setBookmarks(data);
        } else {
          setBookmarks([]);
          setError("Unable to load EV opportunities.");
        }
      } catch (err) {
        console.error("EVPage load error:", err);

        if (mounted) {
          setBookmarks([]);
          setError("Unable to load EV opportunities.");
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    loadEV();

    return () => {
      mounted = false;
    };
  }, []);

  // =========================================================
  // POSITIVE EV MATCHES
  // =========================================================

  const evMatches = useMemo(() => {
    return bookmarks
      .filter((match) => {
        const evHome = Number(match.EV_home);
        const evDraw = Number(match.EV_draw);
        const evAway = Number(match.EV_away);

        const mainEV = Number(match.EV);

        return (
          (Number.isFinite(mainEV) && mainEV > 0) ||
          (Number.isFinite(evHome) && evHome > 0) ||
          (Number.isFinite(evDraw) && evDraw > 0) ||
          (Number.isFinite(evAway) && evAway > 0)
        );
      })
      .sort((a, b) => {
        return Number(b.EV || 0) - Number(a.EV || 0);
      });
  }, [bookmarks]);

  // =========================================================
  // STATISTICS
  // =========================================================

  const highestEV = useMemo(() => {
    if (!evMatches.length) return 0;

    return Math.max(
      ...evMatches.map((m) =>
        Number(m.EV || 0)
      )
    );
  }, [evMatches]);

  const averageEV = useMemo(() => {
    if (!evMatches.length) return 0;

    const total = evMatches.reduce(
      (sum, m) => sum + Number(m.EV || 0),
      0
    );

    return total / evMatches.length;
  }, [evMatches]);

  // =========================================================
  // FORMATTERS
  // =========================================================

  const formatEV = (value) => {
    const n = Number(value);

    if (!Number.isFinite(n)) {
      return "—";
    }

    return `${n >= 0 ? "+" : ""}${(
      n * 100
    ).toFixed(2)}%`;
  };

  const formatOdds = (value) => {
    const n = Number(value);

    return Number.isFinite(n)
      ? n.toFixed(2)
      : "—";
  };

  const formatProbability = (value) => {
    const n = Number(value);

    if (!Number.isFinite(n)) {
      return "—";
    }

    return `${(n * 100).toFixed(1)}%`;
  };

  const formatDate = (value) => {
    if (!value) return "—";

    const d = new Date(value);

    if (Number.isNaN(d.getTime())) {
      return "—";
    }

    return d.toLocaleString([], {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  // =========================================================
  // BEST SELECTION
  // =========================================================

  const getBestSelection = (match) => {
    const values = [
      {
        name: "HOME",
        ev: Number(
          match.EV_home ?? -Infinity
        ),
      },
      {
        name: "DRAW",
        ev: Number(
          match.EV_draw ?? -Infinity
        ),
      },
      {
        name: "AWAY",
        ev: Number(
          match.EV_away ?? -Infinity
        ),
      },
    ];

    values.sort((a, b) => b.ev - a.ev);

    if (!Number.isFinite(values[0].ev)) {
      return {
        name: match.Best || "—",
        ev: Number(match.EV || 0),
      };
    }

    return values[0];
  };

  // =========================================================
  // RENDER
  // =========================================================

  return (
    <div className="min-h-screen bg-slate-950 text-white">

      {/* HEADER */}
      <div
        className="
          sticky
          top-0
          z-50
          bg-slate-950/95
          backdrop-blur
          border-b
          border-slate-800
        "
      >
        <div className="flex items-center gap-3 px-4 py-3">

          <button
            onClick={() => navigate(-1)}
            className="
              w-9
              h-9
              rounded-full
              bg-slate-800
              flex
              items-center
              justify-center
              text-lg
              active:scale-95
            "
          >
            ←
          </button>

          <div className="flex-1">
            <h1 className="font-bold text-lg">
              EV+ Value
            </h1>

            <p className="text-[11px] text-gray-400">
              Positive expected-value opportunities
            </p>
          </div>

          <button
            onClick={() => window.location.reload()}
            className="
              text-xs
              bg-slate-800
              px-3
              py-2
              rounded-full
              text-gray-300
            "
          >
            Refresh
          </button>
        </div>
      </div>

      {/* CONTENT */}
      <div className="p-3 sm:p-4">

        {/* SUMMARY */}
        <div className="grid grid-cols-2 gap-2 mb-4">

          <div
            className="
              bg-slate-900
              border
              border-green-500/20
              rounded-2xl
              p-3
            "
          >
            <div className="text-[10px] text-gray-500 uppercase">
              EV Opportunities
            </div>

            <div className="text-2xl font-bold text-green-400 mt-1">
              {loading ? "—" : evMatches.length}
            </div>
          </div>

          <div
            className="
              bg-slate-900
              border
              border-green-500/20
              rounded-2xl
              p-3
            "
          >
            <div className="text-[10px] text-gray-500 uppercase">
              Highest EV
            </div>

            <div className="text-2xl font-bold text-green-400 mt-1">
              {loading
                ? "—"
                : formatEV(highestEV)}
            </div>
          </div>

          <div
            className="
              bg-slate-900
              border
              border-slate-800
              rounded-2xl
              p-3
            "
          >
            <div className="text-[10px] text-gray-500 uppercase">
              Average EV
            </div>

            <div className="text-lg font-bold text-white mt-1">
              {loading
                ? "—"
                : formatEV(averageEV)}
            </div>
          </div>

          <div
            className="
              bg-slate-900
              border
              border-slate-800
              rounded-2xl
              p-3
            "
          >
            <div className="text-[10px] text-gray-500 uppercase">
              Source
            </div>

            <div className="text-lg font-bold text-white mt-1">
              Live
            </div>
          </div>
        </div>

        {/* DESCRIPTION */}
        <div
          className="
            bg-green-500/10
            border
            border-green-500/20
            rounded-2xl
            p-3
            mb-4
          "
        >
          <div className="flex items-center gap-2">
            <span className="text-green-400 text-lg">
              ⚡
            </span>

            <div>
              <div className="text-sm font-semibold text-green-400">
                Value Opportunities
              </div>

              <div className="text-[11px] text-gray-400 mt-0.5">
                Matches are ranked by expected value.
              </div>
            </div>
          </div>
        </div>

        {/* LOADING */}
        {loading && (
          <div className="py-12 text-center">
            <div className="text-green-400 text-2xl animate-pulse">
              ⚡
            </div>

            <p className="text-sm text-gray-400 mt-2">
              Loading EV opportunities...
            </p>
          </div>
        )}

        {/* ERROR */}
        {!loading && error && (
          <div
            className="
              bg-red-500/10
              border
              border-red-500/20
              rounded-2xl
              p-4
              text-center
            "
          >
            <div className="text-red-400 font-semibold">
              Unable to load EV data
            </div>

            <p className="text-xs text-gray-500 mt-1">
              {error}
            </p>
          </div>
        )}

        {/* EMPTY */}
        {!loading &&
          !error &&
          evMatches.length === 0 && (
            <div className="py-12 text-center">
              <div className="text-3xl mb-2">
                📊
              </div>

              <p className="text-gray-400 text-sm">
                No positive EV opportunities available.
              </p>
            </div>
          )}

        {/* MATCHES */}
        {!loading &&
          !error &&
          evMatches.length > 0 && (
            <div className="space-y-3">

              {evMatches.map((match, index) => {
                const best =
                  getBestSelection(match);

                return (
                  <div
                    key={
                      match.match_id ||
                      match.id ||
                      index
                    }
                    className="
                      bg-slate-900
                      border
                      border-slate-800
                      rounded-2xl
                      overflow-hidden
                    "
                  >

                    {/* MATCH HEADER */}
                    <div className="px-3 py-2 border-b border-slate-800">

                      <div className="flex justify-between items-center gap-2">

                        <div className="text-[10px] text-gray-500 truncate">
                          {match.league || "Football"}
                        </div>

                        <div className="text-[10px] text-gray-500 shrink-0">
                          {formatDate(
                            match.match_time ||
                            match.localDate
                          )}
                        </div>

                      </div>

                    </div>

                    {/* TEAMS */}
                    <div className="p-3">

                      <div className="flex items-center justify-between gap-3">

                        <div className="flex-1 min-w-0">

                          <div className="font-semibold text-sm truncate">
                            {match.home_team ||
                              "Home"}
                          </div>

                          <div className="text-[11px] text-gray-500 my-1">
                            vs
                          </div>

                          <div className="font-semibold text-sm truncate">
                            {match.away_team ||
                              "Away"}
                          </div>

                        </div>

                        {/* BEST EV */}
                        <div className="text-right">

                          <div className="text-[9px] text-gray-500 uppercase">
                            Best EV
                          </div>

                          <div className="text-xl font-bold text-green-400">
                            {formatEV(
                              match.EV
                            )}
                          </div>

                          <div className="text-[10px] text-green-300 font-semibold">
                            {match.Best ||
                              best.name}
                          </div>

                        </div>

                      </div>

                      {/* ODDS */}
                      <div className="grid grid-cols-3 gap-2 mt-4">

                        <div
                          className={`
                            rounded-xl
                            p-2
                            text-center
                            ${
                              best.name ===
                              "HOME"
                                ? "bg-green-500/15 border border-green-500/30"
                                : "bg-slate-800"
                            }
                          `}
                        >
                          <div className="text-[9px] text-gray-500">
                            HOME
                          </div>

                          <div className="font-bold text-sm">
                            {formatOdds(
                              match.home_odds
                            )}
                          </div>

                          <div className="text-[9px] text-green-400 mt-1">
                            {formatEV(
                              match.EV_home
                            )}
                          </div>
                        </div>

                        <div
                          className={`
                            rounded-xl
                            p-2
                            text-center
                            ${
                              best.name ===
                              "DRAW"
                                ? "bg-green-500/15 border border-green-500/30"
                                : "bg-slate-800"
                            }
                          `}
                        >
                          <div className="text-[9px] text-gray-500">
                            DRAW
                          </div>

                          <div className="font-bold text-sm">
                            {formatOdds(
                              match.draw_odds
                            )}
                          </div>

                          <div className="text-[9px] text-green-400 mt-1">
                            {formatEV(
                              match.EV_draw
                            )}
                          </div>
                        </div>

                        <div
                          className={`
                            rounded-xl
                            p-2
                            text-center
                            ${
                              best.name ===
                              "AWAY"
                                ? "bg-green-500/15 border border-green-500/30"
                                : "bg-slate-800"
                            }
                          `}
                        >
                          <div className="text-[9px] text-gray-500">
                            AWAY
                          </div>

                          <div className="font-bold text-sm">
                            {formatOdds(
                              match.away_odds
                            )}
                          </div>

                          <div className="text-[9px] text-green-400 mt-1">
                            {formatEV(
                              match.EV_away
                            )}
                          </div>
                        </div>

                      </div>

                      {/* MODEL PROBABILITY */}
                      <div className="mt-3 pt-3 border-t border-slate-800">

                        <div className="text-[9px] text-gray-500 uppercase mb-2">
                          Model Probability
                        </div>

                        <div className="grid grid-cols-3 gap-2 text-center">

                          <div>
                            <div className="text-[9px] text-gray-500">
                              Home
                            </div>

                            <div className="text-xs font-semibold">
                              {formatProbability(
                                match.p_home
                              )}
                            </div>
                          </div>

                          <div>
                            <div className="text-[9px] text-gray-500">
                              Draw
                            </div>

                            <div className="text-xs font-semibold">
                              {formatProbability(
                                match.p_draw
                              )}
                            </div>
                          </div>

                          <div>
                            <div className="text-[9px] text-gray-500">
                              Away
                            </div>

                            <div className="text-xs font-semibold">
                              {formatProbability(
                                match.p_away
                              )}
                            </div>
                          </div>

                        </div>

                      </div>

                    </div>
                  </div>
                );
              })}

            </div>
          )}
      </div>
    </div>
  );
}
