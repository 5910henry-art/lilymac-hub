// src/user/Accumulators.jsx

import React, {
  useEffect,
  useMemo,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import toast from "react-hot-toast";

import api from "../api/api";
import { useBetslip } from "../contexts/BetslipContext";

const STAKE = 200;

/* =========================================================
   MARKET FORMATTING
========================================================= */

function formatMarket(market, selection) {
  const rawMarket = String(market || "").toUpperCase();
  const rawSelection = String(selection || "").toUpperCase();

  if (/3-?WAY/.test(rawMarket)) {
    if (rawSelection === "HOME") return "Home Win";
    if (rawSelection === "AWAY") return "Away Win";
    if (rawSelection === "DRAW") return "Draw";
  }

  if (rawMarket === "BTTS") {
    return rawSelection === "YES"
      ? "BTTS — Yes"
      : "BTTS — No";
  }

  const goalMarket = rawMarket.match(
    /^O(\d+(?:\.\d+)?)$/
  );

  if (goalMarket) {
    const line = goalMarket[1];

    return rawSelection === "OVER"
      ? `Over ${line}`
      : `Under ${line}`;
  }

  return `${market || ""} ${selection || ""}`.trim();
}

function getRawSelection(selection) {
  const value = String(selection || "").toUpperCase();

  if (
    ["HOME", "AWAY", "DRAW", "YES", "NO", "OVER", "UNDER"].includes(
      value
    )
  ) {
    return value;
  }

  return String(selection || "").toUpperCase();
}

/* =========================================================
   FORMATTING
========================================================= */

function formatKickoff(time) {
  if (!time) return "Kickoff TBA";

  const date = new Date(time);

  if (Number.isNaN(date.getTime())) {
    return "Kickoff TBA";
  }

  return date.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDateLabel(dateString) {
  if (!dateString) return "";

  const date = new Date(`${dateString}T00:00:00`);

  if (Number.isNaN(date.getTime())) {
    return dateString;
  }

  return date.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function formatOdds(odds) {
  const value = Number(odds);

  if (!Number.isFinite(value) || value <= 0) {
    return null;
  }

  return value.toFixed(2);
}

function getMatchId(match) {
  const value = Number(match?.match_id ?? match?.id);

  return Number.isInteger(value) && value > 0
    ? value
    : null;
}

/* =========================================================
   DATA HELPERS
========================================================= */

function uniqueSelections(matches) {
  const seen = new Set();

  return matches.filter((match) => {
    const matchId = getMatchId(match);

    const key = [
      matchId,
      match.market,
      match.selection,
    ].join("|");

    if (seen.has(key)) {
      return false;
    }

    seen.add(key);
    return true;
  });
}

function getDateMatches(data, date) {
  if (!data || !date) return [];

  const raw = data[date];

  if (Array.isArray(raw)) {
    return raw;
  }

  if (raw && Array.isArray(raw.matches)) {
    return raw.matches;
  }

  return [];
}

function getResponseDateData(response) {
  let current = response;

  // Unwrap common API response layers safely.
  if (current?.data !== undefined) {
    current = current.data;
  }

  if (current?.data !== undefined) {
    current = current.data;
  }

  // Exact backend structure:
  // { by_date: { "2026-09-20": [...] } }
  if (
    current?.by_date &&
    typeof current.by_date === "object" &&
    !Array.isArray(current.by_date)
  ) {
    return current.by_date;
  }

  // Support nested by_date responses.
  if (
    current?.data?.by_date &&
    typeof current.data.by_date === "object" &&
    !Array.isArray(current.data.by_date)
  ) {
    return current.data.by_date;
  }

  // Support direct date-keyed responses.
  if (
    current &&
    typeof current === "object" &&
    !Array.isArray(current)
  ) {
    return current;
  }

  return {};
}

/* =========================================================
   ACCUMULATOR FOLDS
========================================================= */

function generateFolds(matches) {
  if (!Array.isArray(matches) || matches.length < 2) {
    return [];
  }

  const sorted = [...matches]
    .filter((match) => {
      return (
        match &&
        getMatchId(match) !== null &&
        match.home_team &&
        match.away_team
      );
    })
    .sort((a, b) => {
      const probabilityA = Number(a.probability) || 0;
      const probabilityB = Number(b.probability) || 0;

      return probabilityB - probabilityA;
    });

  function selectUnique(list, maximum) {
    const usedMatches = new Set();
    const selected = [];

    for (const match of list) {
      const matchId = getMatchId(match);

      if (matchId === null) continue;
      if (usedMatches.has(matchId)) continue;

      usedMatches.add(matchId);
      selected.push(match);

      if (selected.length >= maximum) {
        break;
      }
    }

    return selected;
  }

  const folds = [];

  const bestTips = selectUnique(sorted, 10);

  if (bestTips.length >= 2) {
    folds.push({
      id: "best-tips",
      title: "Best Tips",
      subtitle: "Selected from the strongest available predictions",
      matches: bestTips,
    });
  }

  const goalsAndBtts = sorted.filter((match) => {
    const market = String(match.market || "").toUpperCase();

    return (
      market === "BTTS" ||
      /^O\d+(?:\.\d+)?$/.test(market)
    );
  });

  const goalsFold = selectUnique(goalsAndBtts, 8);

  if (goalsFold.length >= 2) {
    folds.push({
      id: "goals-btts",
      title: "Goals & BTTS",
      subtitle: "Goals and both-teams-to-score picks",
      matches: goalsFold,
    });
  }

  return folds;
}

/* =========================================================
   ODDS HELPERS
========================================================= */

function getFoldOdds(matches) {
  const odds = matches.map((match) => {
    const value = Number(match.odds);

    if (!Number.isFinite(value) || value <= 0) {
      return null;
    }

    return value;
  });

  if (odds.some((value) => value === null)) {
    return {
      available: false,
      combined: null,
      returnAmount: null,
    };
  }

  const combined = odds.reduce(
    (total, odd) => total * odd,
    1
  );

  return {
    available: true,
    combined: combined.toFixed(2),
    returnAmount: Math.round(combined * STAKE),
  };
}

/* =========================================================
   COMPONENT
========================================================= */

export default function Accumulators() {
  const navigate = useNavigate();

  const {
    betslip,
    addAccumulator,
  } = useBetslip();

  const [data, setData] = useState({});
  const [dates, setDates] = useState([]);
  const [activeDate, setActiveDate] = useState(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  /* =======================================================
     LOAD ACCUMULATORS
  ======================================================= */

  useEffect(() => {
    let mounted = true;

    async function loadAccumulator() {
      setLoading(true);
      setError("");

      try {
        const response = await api.getAccumulator({
          by_date: true,
          max_games: 20,
        });

        const safeData = getResponseDateData(response);

        console.log(
          "ACCUMULATOR API RESPONSE:",
          response
        );

        console.log(
          "ACCUMULATOR DATE DATA:",
          safeData
        );

        if (!mounted) return;

        const validData =
          safeData &&
          typeof safeData === "object" &&
          !Array.isArray(safeData)
            ? safeData
            : {};

        const availableDates = Object.keys(validData)
          .filter((date) => {
            return getDateMatches(validData, date).length > 0;
          })
          .sort();

        setData(validData);
        setDates(availableDates);

        const dateWithEnoughSelections =
          availableDates.find((date) => {
            return getDateMatches(validData, date).length >= 2;
          });

        setActiveDate(
          dateWithEnoughSelections ||
            availableDates[0] ||
            null
        );
      } catch (err) {
        console.error(
          "Failed to load accumulator tips:",
          err
        );

        if (mounted) {
          setError(
            "Unable to load accumulator tips."
          );

          setData({});
          setDates([]);
          setActiveDate(null);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    loadAccumulator();

    return () => {
      mounted = false;
    };
  }, []);

  /* =======================================================
     CURRENT DATE MATCHES
  ======================================================= */

  const matches = useMemo(() => {
    const currentMatches = getDateMatches(
      data,
      activeDate
    );

    return uniqueSelections(currentMatches);
  }, [data, activeDate]);

  const folds = useMemo(() => {
    return generateFolds(matches);
  }, [matches]);

  /* =======================================================
     AUTO SELECT DATE
  ======================================================= */

  useEffect(() => {
    if (
      loading ||
      !dates.length ||
      !activeDate
    ) {
      return;
    }

    const currentCount = getDateMatches(
      data,
      activeDate
    ).length;

    if (currentCount >= 2) {
      return;
    }

    const alternativeDate = dates.find((date) => {
      return (
        date !== activeDate &&
        getDateMatches(data, date).length >= 2
      );
    });

    if (alternativeDate) {
      setActiveDate(alternativeDate);
    }
  }, [
    loading,
    dates,
    activeDate,
    data,
  ]);

  /* =======================================================
     ADD SINGLE PICK TO BETSLIP
  ======================================================= */

  function handleAddPick(match) {
    const matchId = getMatchId(match);

    if (matchId === null) {
      toast.error("Invalid match.");
      return;
    }

    const selection = {
      match_id: matchId,
      home_team: match.home_team,
      away_team: match.away_team,
      match_time: match.match_time,
      kickoff: match.match_time,
      competition: match.competition || "",
      market: match.market || "",
      selection: getRawSelection(match.selection),
      odds: Number.isFinite(Number(match.odds))
        ? Number(match.odds)
        : null,
    };

    const result = addAccumulator([selection]);

    const added = Number(result?.added || 0);
    const skipped = Number(result?.skipped || 0);

    if (added > 0) {
      toast.success("Pick added to betslip");
    } else if (skipped > 0) {
      toast("Pick already in betslip", {
        icon: "✓",
      });
    } else {
      toast("Pick was not added.");
    }
  }

  /* =======================================================
     ADD ACCUMULATOR TO BETSLIP
  ======================================================= */

  function handleAddAccumulator(
    fold,
    openBetslip = false
  ) {
    if (!fold?.matches?.length) {
      toast.error("No picks available.");
      return;
    }

    const picks = fold.matches
      .map((match) => {
        const matchId = getMatchId(match);

        if (matchId === null) {
          return null;
        }

        return {
          match_id: matchId,
          home_team: match.home_team,
          away_team: match.away_team,
          match_time: match.match_time,
          kickoff: match.match_time,
          competition: match.competition || "",
          market: match.market || "",
          selection: getRawSelection(match.selection),
          odds: Number.isFinite(Number(match.odds))
            ? Number(match.odds)
            : null,
        };
      })
      .filter(Boolean);

    if (!picks.length) {
      toast.error("No valid picks found.");
      return;
    }

    const result = addAccumulator(picks);

    const added = Number(result?.added || 0);
    const skipped = Number(result?.skipped || 0);

    if (added > 0 && skipped > 0) {
      toast.success(
        `${added} added • ${skipped} already in betslip`
      );
    } else if (added > 0) {
      toast.success(
        `${added} picks added`
      );
    } else if (skipped > 0) {
      toast(
        "These picks are already in your betslip",
        {
          icon: "✓",
        }
      );
    } else {
      toast("No new picks were added.");
    }

    if (openBetslip) {
      navigate("/betslip");
    }
  }

  /* =======================================================
     LOADING
  ======================================================= */

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#050807] px-5 text-white">
        <div className="text-center">
          <div className="mx-auto mb-5 h-12 w-12 animate-spin rounded-full border-4 border-white/10 border-t-emerald-400" />

          <p className="text-xs font-bold uppercase tracking-[0.25em] text-emerald-400">
            LilyMac Hub
          </p>

          <h1 className="mt-2 text-xl font-black">
            Loading tips
          </h1>

          <p className="mt-2 text-sm text-gray-500">
            Loading upcoming picks
          </p>
        </div>
      </div>
    );
  }

  /* =======================================================
     ERROR
  ======================================================= */

  if (error) {
    return (
      <div className="min-h-screen bg-[#050807] px-4 py-12 text-white">
        <div className="mx-auto max-w-md rounded-3xl border border-red-500/20 bg-white/[0.03] p-8 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-red-500/10 text-2xl">
            !
          </div>

          <h1 className="mt-5 text-xl font-black">
            Accumulator unavailable
          </h1>

          <p className="mt-2 text-sm leading-6 text-gray-500">
            {error}
          </p>

          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-6 rounded-2xl bg-emerald-400 px-5 py-3 text-xs font-black uppercase tracking-wider text-black"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  /* =======================================================
     EMPTY STATE
  ======================================================= */

  if (!dates.length) {
    return (
      <div className="min-h-screen bg-[#050807] px-4 py-12 text-white">
        <div className="mx-auto max-w-md rounded-3xl border border-white/10 bg-white/[0.03] p-8 text-center">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-emerald-500/10 text-3xl">
            ⚽
          </div>

          <h1 className="mt-5 text-xl font-black">
            No accumulator tips
          </h1>

          <p className="mt-2 text-sm leading-6 text-gray-500">
            There are currently no upcoming picks available.
          </p>
        </div>
      </div>
    );
  }

  /* =======================================================
     PAGE
  ======================================================= */

  return (
    <div className="min-h-screen bg-[#050807] text-white">
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-32 left-1/2 h-72 w-72 -translate-x-1/2 rounded-full bg-emerald-500/10 blur-3xl" />
        <div className="absolute right-0 top-1/3 h-56 w-56 rounded-full bg-emerald-400/5 blur-3xl" />
      </div>

      <div className="relative mx-auto max-w-4xl px-4 pb-10 pt-5 sm:px-6 sm:pt-8">
        {/* HEADER */}

        <header className="mb-7">
          <div className="flex items-end justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-lg shadow-emerald-400/50" />

                <span className="text-[10px] font-black uppercase tracking-[0.3em] text-emerald-400">
                  LilyMac Hub
                </span>
              </div>

              <h1 className="mt-2 text-3xl font-black tracking-tight sm:text-4xl">
                Accumulators
              </h1>

              <p className="mt-1 max-w-lg text-sm text-gray-500">
                Select a date and build your accumulator.
              </p>
            </div>

            <button
              type="button"
              onClick={() => navigate("/betslip")}
              className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.05] text-lg transition hover:border-emerald-400/30 hover:bg-emerald-500/10 active:scale-95"
              aria-label="Open betslip"
            >
              🧾

              {betslip.length > 0 && (
                <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-emerald-400 px-1 text-[9px] font-black text-black">
                  {betslip.length}
                </span>
              )}
            </button>
          </div>

          {/* DATE NAVIGATION */}

          <div className="mt-6">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[10px] font-black uppercase tracking-[0.2em] text-gray-600">
                Dates
              </span>

              <span className="text-[10px] font-bold text-gray-600">
                {dates.length} dates
              </span>
            </div>

            <div className="scrollbar-hide flex gap-2 overflow-x-auto pb-1">
              {dates.map((date) => {
                const count = getDateMatches(
                  data,
                  date
                ).length;

                const active = date === activeDate;

                return (
                  <button
                    key={date}
                    type="button"
                    onClick={() => setActiveDate(date)}
                    className={`min-w-[112px] rounded-2xl border px-3.5 py-3 text-left transition-all ${
                      active
                        ? "border-emerald-400/40 bg-emerald-400 text-black shadow-lg shadow-emerald-500/10"
                        : "border-white/10 bg-white/[0.035] text-gray-300 hover:border-white/20 hover:bg-white/[0.06]"
                    }`}
                  >
                    <div className="text-xs font-black">
                      {formatDateLabel(date)}
                    </div>

                    <div
                      className={`mt-1 text-[9px] font-bold uppercase tracking-wider ${
                        active
                          ? "text-black/60"
                          : "text-gray-600"
                      }`}
                    >
                      {count} picks
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </header>

        {/* DATE SUMMARY */}

        <div className="mb-5 flex items-center justify-between rounded-3xl border border-white/10 bg-white/[0.035] px-4 py-3.5">
          <div>
            <div className="text-[9px] font-black uppercase tracking-[0.2em] text-gray-600">
              Selected date
            </div>

            <div className="mt-1 text-sm font-black">
              {formatDateLabel(activeDate)}
            </div>
          </div>

          <div className="rounded-2xl bg-emerald-400/10 px-4 py-2 text-right">
            <div className="text-lg font-black text-emerald-400">
              {matches.length}
            </div>

            <div className="text-[8px] font-black uppercase tracking-wider text-gray-600">
              picks
            </div>
          </div>
        </div>

        {/* ACCUMULATOR CARDS */}

        <div className="space-y-5">
          {folds.length === 0 && (
            <div className="rounded-3xl border border-white/10 bg-white/[0.035] p-8 text-center">
              <div className="text-3xl">⚽</div>

              <h2 className="mt-4 font-black">
                More picks needed
              </h2>

              <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-gray-500">
                Choose another date.
              </p>
            </div>
          )}

          {folds.map((fold, foldIndex) => {
            const foldOdds = getFoldOdds(fold.matches);

            return (
              <section
                key={fold.id}
                className="overflow-hidden rounded-[28px] border border-white/10 bg-white/[0.035] shadow-2xl shadow-black/20"
              >
                {/* CARD HEADER */}

                <div className="border-b border-white/[0.07] p-5 sm:p-6">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="rounded-lg bg-emerald-400 px-2 py-1 text-[9px] font-black uppercase tracking-wider text-black">
                          ACCA {foldIndex + 1}
                        </span>

                        <span className="text-[10px] font-bold text-gray-600">
                          {fold.matches.length} picks
                        </span>
                      </div>

                      <h2 className="mt-3 text-xl font-black tracking-tight">
                        {fold.title}
                      </h2>

                      <p className="mt-1 text-xs text-gray-500">
                        {fold.subtitle}
                      </p>
                    </div>

                    <div className="rounded-2xl border border-emerald-400/10 bg-emerald-400/[0.06] px-3 py-2 text-right">
                      <div className="text-[8px] font-black uppercase tracking-widest text-gray-600">
                        Combined
                      </div>

                      <div className="mt-0.5 text-xl font-black text-emerald-400">
                        {foldOdds.available
                          ? `@${foldOdds.combined}`
                          : "—"}
                      </div>

                      {!foldOdds.available && (
                        <div className="mt-1 max-w-[90px] text-[8px] font-bold leading-3 text-gray-600">
                          Odds missing
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* PICKS */}

                <div className="divide-y divide-white/[0.06]">
                  {fold.matches.map((match, index) => {
                    const matchOdds = formatOdds(
                      match.odds
                    );

                    return (
                      <div
                        key={[
                          getMatchId(match),
                          match.market,
                          match.selection,
                        ].join("-")}
                        className="p-4 transition hover:bg-white/[0.025] sm:p-5"
                      >
                        <div className="flex gap-3">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-white/[0.06] text-[10px] font-black text-gray-500">
                            {String(index + 1).padStart(2, "0")}
                          </div>

                          <div className="min-w-0 flex-1">
                            {/* TEAMS AND TIP */}

                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="truncate text-sm font-black text-white">
                                  {match.home_team}
                                </div>

                                <div className="my-1 flex items-center gap-2">
                                  <span className="h-px w-4 bg-white/10" />

                                  <span className="text-[8px] font-black uppercase tracking-widest text-gray-700">
                                    vs
                                  </span>

                                  <span className="h-px w-4 bg-white/10" />
                                </div>

                                <div className="truncate text-sm font-black text-white">
                                  {match.away_team}
                                </div>
                              </div>

                              <div className="shrink-0 text-right">
                                <div className="text-[8px] font-bold uppercase tracking-widest text-gray-700">
                                  Tip
                                </div>

                                <div className="mt-1 rounded-lg bg-emerald-400/10 px-2 py-1 text-[10px] font-black text-emerald-400">
                                  {formatMarket(
                                    match.market,
                                    match.selection
                                  )}
                                </div>
                              </div>
                            </div>

                            {/* META */}

                            <div className="mt-3 flex flex-wrap items-center gap-2">
                              <span className="rounded-lg bg-white/[0.04] px-2.5 py-1.5 text-[10px] font-bold text-gray-500">
                                {formatKickoff(
                                  match.match_time
                                )}
                              </span>

                              <span className="rounded-lg bg-white/[0.04] px-2.5 py-1.5 text-[10px] font-bold text-gray-600">
                                {match.competition ||
                                  match.market ||
                                  "Market"}
                              </span>

                              <span
                                className={`rounded-lg px-2.5 py-1.5 text-[10px] font-black ${
                                  matchOdds
                                    ? "bg-emerald-400/10 text-emerald-400"
                                    : "bg-white/[0.04] text-gray-600"
                                }`}
                              >
                                {matchOdds
                                  ? `@${matchOdds}`
                                  : "—"}
                              </span>

                              <button
                                type="button"
                                onClick={() => handleAddPick(match)}
                                className="rounded-lg border border-emerald-400/20 bg-emerald-400/10 px-3 py-1.5 text-[10px] font-black uppercase tracking-wide text-emerald-400 transition hover:bg-emerald-400/20 active:scale-95"
                              >
                                + Add
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* FOOTER */}

                <div className="border-t border-white/[0.07] bg-black/10 p-4 sm:p-5">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="text-[9px] font-black uppercase tracking-widest text-gray-600">
                        Stake reference
                      </div>

                      <div className="mt-1 text-xl font-black">
                        KSh {STAKE.toLocaleString()}
                      </div>
                    </div>

                    <div className="text-right">
                      <div className="text-[9px] font-black uppercase tracking-widest text-gray-600">
                        {fold.matches.length} picks
                      </div>

                      <div className="mt-1 text-sm font-black text-emerald-400">
                        {foldOdds.available
                          ? `@${foldOdds.combined}`
                          : "At placement"}
                      </div>
                    </div>
                  </div>

                  <div className="mt-3 rounded-2xl border border-white/[0.06] bg-white/[0.025] px-3 py-2.5">
                    <p className="text-[10px] leading-4 text-gray-500">
                      Only available bookmaker odds are displayed.
                      Missing odds are not generated or estimated.
                    </p>
                  </div>

                  {/* ACTIONS */}

                  <div className="mt-4 grid grid-cols-[1fr_1.25fr] gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        handleAddAccumulator(
                          fold,
                          false
                        )
                      }
                      className="rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3.5 text-[10px] font-black uppercase tracking-wider text-emerald-400 transition hover:bg-emerald-400/15 active:scale-[0.98]"
                    >
                      Add All
                    </button>

                    <button
                      type="button"
                      onClick={() =>
                        handleAddAccumulator(
                          fold,
                          true
                        )
                      }
                      className="rounded-2xl bg-emerald-400 px-4 py-3.5 text-[10px] font-black uppercase tracking-wider text-black shadow-lg shadow-emerald-500/10 transition hover:bg-emerald-300 active:scale-[0.98]"
                    >
                      Add & Open
                    </button>
                  </div>
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}
