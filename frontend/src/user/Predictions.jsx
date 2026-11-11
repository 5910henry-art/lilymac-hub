// src/pages/Predictions.jsx

import React, { useEffect, useMemo, useState } from "react";
import { getPredictionsLatest, loadTeams } from "../api/domain";
import Loader from "../components/Loader";
import { motion, AnimatePresence } from "framer-motion";

/* =========================================================
   CONSTANTS
   ========================================================= */

const PLACEHOLDER = "/logos/placeholder.png";

const COMPETITION_LABELS = {
  "Primera Division": "LaLiga",
};

const DATE_FILTERS = [
  "All",
  "Today",
  "Tomorrow",
  "This Week",
  "This Month",
];

const PROBABILITY_KEYS = [
  ["home_win", "H"],
  ["draw", "D"],
  ["away_win", "A"],
];

/* =========================================================
   HELPERS
   ========================================================= */

const normalizeCompetitionName = (name) =>
  COMPETITION_LABELS[name] || name;

const formatPercent = (value) =>
  `${((Number(value) || 0) * 100).toFixed(1)}%`;

const getProbability = (probabilities, key) =>
  Number(probabilities?.[key]) || 0;

const getPredictionBadgeClass = (prediction) => {
  switch (prediction) {
    case "Home Win":
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300";

    case "Draw":
      return "bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300";

    case "Away Win":
      return "bg-rose-100 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300";

    default:
      return "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300";
  }
};

const formatEAT = (utcDate) => {
  if (!utcDate) return "TBA";

  const date = new Date(utcDate);

  if (Number.isNaN(date.getTime())) {
    return "Invalid Date";
  }

  return (
    date.toLocaleString("en-KE", {
      weekday: "short",
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
      timeZone: "Africa/Nairobi",
    }) + " EAT"
  );
};

const getDateKey = (utcDate) => {
  const date = new Date(utcDate);

  return date.toLocaleDateString("en-KE", {
    weekday: "long",
    day: "numeric",
    month: "short",
  });
};

/* =========================================================
   COMPONENT
   ========================================================= */

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
  const [nowUtc, setNowUtc] = useState(() => new Date());

  /* =======================================================
     CURRENT TIME
     ======================================================= */

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNowUtc(new Date());
    }, 60 * 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, []);

  /* =======================================================
     FETCH PREDICTIONS
     ======================================================= */

  useEffect(() => {
    let mounted = true;

    const fetchData = async () => {
      try {
        setLoading(true);
        setError(null);

        const [, response] = await Promise.all([
          loadTeams(),
          getPredictionsLatest(),
        ]);

        if (!mounted) return;

        if (
          response?.success &&
          Array.isArray(response?.data?.predictions)
        ) {
          const cleanPredictions = response.data.predictions
            .map((prediction) => ({
              ...prediction,

              competition_name: normalizeCompetitionName(
                prediction.competition
              ),

              home_logo:
                prediction.home_logo || PLACEHOLDER,

              away_logo:
                prediction.away_logo || PLACEHOLDER,

              home_team_name:
                prediction.home_team_name || "Home",

              away_team_name:
                prediction.away_team_name || "Away",
            }))
            .filter((prediction) => prediction.utcDate);

          setPredictions(cleanPredictions);

          setCompetitions(
            Array.from(
              new Set(
                cleanPredictions
                  .map(
                    (prediction) =>
                      prediction.competition_name
                  )
                  .filter(Boolean)
              )
            ).sort()
          );
        } else {
          console.error(
            "Invalid predictions response:",
            response
          );

          setError("Invalid prediction data received.");
        }
      } catch (err) {
        if (!mounted) return;

        console.error(
          "Failed to load predictions:",
          err
        );

        setError("Failed to load predictions.");
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    fetchData();

    return () => {
      mounted = false;
    };
  }, []);

  /* =======================================================
     FILTER + SORT
     ======================================================= */

  const filtered = useMemo(() => {
    /*
     * Five-minute tolerance prevents matches from disappearing
     * exactly at kickoff because of small clock/API differences.
     */
    const now = new Date(
      nowUtc.getTime() - 5 * 60 * 1000
    );

    let list = predictions.filter((prediction) => {
      const date = new Date(prediction.utcDate);

      return (
        !Number.isNaN(date.getTime()) &&
        date >= now
      );
    });

    /* Competition */
    if (selectedCompetition !== "All") {
      list = list.filter(
        (prediction) =>
          prediction.competition_name ===
          selectedCompetition
      );
    }

    /* Team search */
    const query = searchTerm.trim().toLowerCase();

    if (query) {
      list = list.filter((prediction) => {
        const home =
          prediction.home_team_name?.toLowerCase() || "";

        const away =
          prediction.away_team_name?.toLowerCase() || "";

        return (
          home.includes(query) ||
          away.includes(query)
        );
      });
    }

    /* Date boundaries */
    const today = new Date(nowUtc);
    today.setHours(0, 0, 0, 0);

    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);

    const dayAfterTomorrow = new Date(today);
    dayAfterTomorrow.setDate(
      dayAfterTomorrow.getDate() + 1
    );

    const endOfWeek = new Date(today);
    endOfWeek.setDate(endOfWeek.getDate() + 7);

    const endOfMonth = new Date(
      today.getFullYear(),
      today.getMonth() + 1,
      0,
      23,
      59,
      59,
      999
    );

    /* Date filter */
    if (selectedDateFilter !== "All") {
      list = list.filter((prediction) => {
        const date = new Date(prediction.utcDate);

        switch (selectedDateFilter) {
          case "Today":
            return (
              date >= today &&
              date < tomorrow
            );

          case "Tomorrow":
            return (
              date >= tomorrow &&
              date < dayAfterTomorrow
            );

          case "This Week":
            return (
              date >= today &&
              date <= endOfWeek
            );

          case "This Month":
            return (
              date >= today &&
              date <= endOfMonth
            );

          default:
            return true;
        }
      });
    }

    /* Top predictions */
    if (showTopPredictions) {
      list = list.filter((prediction) => {
        const probabilities =
          prediction.prediction?.probabilities || {};

        const maxProbability = Math.max(
          getProbability(probabilities, "home_win"),
          getProbability(probabilities, "draw"),
          getProbability(probabilities, "away_win")
        );

        return maxProbability >= 0.6;
      });
    }

    /* Sort */
    return [...list].sort((a, b) => {
      const timeA = new Date(a.utcDate).getTime();
      const timeB = new Date(b.utcDate).getTime();

      return sortOrder === "asc"
        ? timeA - timeB
        : timeB - timeA;
    });
  }, [
    predictions,
    selectedCompetition,
    selectedDateFilter,
    searchTerm,
    sortOrder,
    showTopPredictions,
    nowUtc,
  ]);

  /* =======================================================
     GROUP BY DATE
     ======================================================= */

  const groupedByDate = useMemo(() => {
    return filtered.reduce((groups, prediction) => {
      const key = getDateKey(prediction.utcDate);

      if (!groups[key]) {
        groups[key] = [];
      }

      groups[key].push(prediction);

      return groups;
    }, {});
  }, [filtered]);

  /* =======================================================
     LOADING / ERROR
     ======================================================= */

  if (loading) {
    return <Loader text="Loading predictions..." />;
  }

  if (error) {
    return (
      <div
        className="
          flex
          min-h-[240px]
          items-center
          justify-center
          px-4
          text-center
        "
      >
        <p
          className="
            rounded-xl
            bg-red-50
            px-4
            py-3
            text-sm
            font-medium
            text-red-600
            dark:bg-red-950/40
            dark:text-red-300
          "
          role="alert"
        >
          {error}
        </p>
      </div>
    );
  }

  /* =======================================================
     RENDER
     ======================================================= */

  return (
    <div className="space-y-6 pt-4 pb-4">

      {/* ===================================================
          FILTERS
      =================================================== */}

      <section
        aria-label="Prediction filters"
        className="
          flex
          flex-wrap
          items-center
          gap-2
        "
      >
        {/* Search */}
        <label className="sr-only" htmlFor="prediction-search">
          Search team
        </label>

        <input
          id="prediction-search"
          type="search"
          placeholder="Search team"
          value={searchTerm}
          onChange={(event) =>
            setSearchTerm(event.target.value)
          }
          className="
            min-w-[160px]
            flex-1
            rounded-lg
            border
            border-gray-200
            bg-white
            px-3
            py-2
            text-sm
            text-gray-900
            outline-none
            transition
            placeholder:text-gray-400
            focus:border-green-500
            focus:ring-2
            focus:ring-green-500/20
            dark:border-gray-700
            dark:bg-gray-900
            dark:text-white
            dark:placeholder:text-gray-500
          "
        />

        {/* Competition */}
        <label className="sr-only" htmlFor="competition-filter">
          Competition
        </label>

        <select
          id="competition-filter"
          value={selectedCompetition}
          onChange={(event) =>
            setSelectedCompetition(event.target.value)
          }
          className="
            rounded-lg
            border
            border-gray-200
            bg-white
            px-3
            py-2
            text-sm
            text-gray-900
            outline-none
            transition
            focus:border-green-500
            focus:ring-2
            focus:ring-green-500/20
            dark:border-gray-700
            dark:bg-gray-900
            dark:text-white
          "
        >
          <option value="All">
            All Competitions
          </option>

          {competitions.map((competition) => (
            <option
              key={competition}
              value={competition}
            >
              {competition}
            </option>
          ))}
        </select>

        {/* Date */}
        <label className="sr-only" htmlFor="date-filter">
          Date
        </label>

        <select
          id="date-filter"
          value={selectedDateFilter}
          onChange={(event) =>
            setSelectedDateFilter(event.target.value)
          }
          className="
            rounded-lg
            border
            border-gray-200
            bg-white
            px-3
            py-2
            text-sm
            text-gray-900
            outline-none
            transition
            focus:border-green-500
            focus:ring-2
            focus:ring-green-500/20
            dark:border-gray-700
            dark:bg-gray-900
            dark:text-white
          "
        >
          {DATE_FILTERS.map((filter) => (
            <option
              key={filter}
              value={filter}
            >
              {filter}
            </option>
          ))}
        </select>

        {/* Top predictions */}
        <button
          type="button"
          onClick={() =>
            setShowTopPredictions(
              (value) => !value
            )
          }
          aria-pressed={showTopPredictions}
          className={`
            rounded-lg
            border
            px-3
            py-2
            text-sm
            font-medium
            transition
            ${
              showTopPredictions
                ? "border-green-500 bg-green-50 text-green-700 dark:bg-green-950/40 dark:text-green-300"
                : "border-gray-200 bg-white text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
            }
          `}
        >
          {showTopPredictions
            ? "Top 60% Only"
            : "Filter Top 60%"}
        </button>

        {/* Sort */}
        <button
          type="button"
          onClick={() =>
            setSortOrder((order) =>
              order === "asc" ? "desc" : "asc"
            )
          }
          className="
            rounded-lg
            border
            border-gray-200
            bg-white
            px-3
            py-2
            text-sm
            font-medium
            text-gray-700
            transition
            hover:border-gray-300
            dark:border-gray-700
            dark:bg-gray-900
            dark:text-gray-200
          "
          aria-label={`Sort ${
            sortOrder === "asc"
              ? "latest to earliest"
              : "earliest to latest"
          }`}
        >
          {sortOrder === "asc"
            ? "Earliest → Latest"
            : "Latest → Earliest"}
        </button>
      </section>

      {/* ===================================================
          RESULTS
      =================================================== */}

      {Object.keys(groupedByDate).length === 0 ? (
        <div
          className="
            rounded-xl
            border
            border-dashed
            border-gray-300
            px-4
            py-12
            text-center
            dark:border-gray-700
          "
        >
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">
            No predictions found.
          </p>
        </div>
      ) : (
        <div className="space-y-7">
          {Object.entries(groupedByDate).map(
            ([date, predictionsForDate]) => (
              <section
                key={date}
                aria-labelledby={`date-${date}`}
                className="space-y-3"
              >
                <h3
                  id={`date-${date}`}
                  className="
                    px-1
                    text-sm
                    font-bold
                    uppercase
                    tracking-wide
                    text-gray-500
                    dark:text-gray-400
                  "
                >
                  {date}
                </h3>

                <AnimatePresence mode="popLayout">
                  {predictionsForDate.map(
                    (prediction) => {
                      const probabilities =
                        prediction.prediction
                          ?.probabilities || {};

                      const predictedResult =
                        prediction.prediction
                          ?.prediction || "-";

                      return (
                        <motion.article
                          key={
                            prediction.match_id ??
                            `${prediction.utcDate}-${prediction.home_team_name}-${prediction.away_team_name}`
                          }
                          layout
                          initial={{
                            opacity: 0,
                            y: 10,
                          }}
                          animate={{
                            opacity: 1,
                            y: 0,
                          }}
                          exit={{
                            opacity: 0,
                            y: -10,
                          }}
                          transition={{
                            duration: 0.2,
                          }}
                          className="
                            overflow-hidden
                            rounded-xl
                            border
                            border-gray-200
                            bg-white
                            p-4
                            shadow-sm
                            transition-shadow
                            hover:shadow-md
                            dark:border-gray-800
                            dark:bg-gray-900
                          "
                        >
                          {/* Match header */}
                          <div
                            className="
                              flex
                              items-start
                              justify-between
                              gap-3
                            "
                          >
                            <div
                              className="
                                flex
                                min-w-0
                                flex-1
                                items-center
                                justify-center
                                gap-2
                              "
                            >
                              <img
                                src={prediction.home_logo}
                                alt=""
                                className="
                                  h-7
                                  w-7
                                  shrink-0
                                  object-contain
                                "
                                loading="lazy"
                                onError={(event) => {
                                  event.currentTarget.src =
                                    PLACEHOLDER;
                                }}
                              />

                              <span
                                className="
                                  min-w-0
                                  truncate
                                  text-sm
                                  font-semibold
                                  text-gray-900
                                  dark:text-white
                                "
                              >
                                {prediction.home_team_name}
                              </span>

                              <span
                                className="
                                  shrink-0
                                  text-xs
                                  font-medium
                                  text-gray-400
                                "
                                aria-label="versus"
                              >
                                vs
                              </span>

                              <span
                                className="
                                  min-w-0
                                  truncate
                                  text-sm
                                  font-semibold
                                  text-gray-900
                                  dark:text-white
                                "
                              >
                                {prediction.away_team_name}
                              </span>

                              <img
                                src={prediction.away_logo}
                                alt=""
                                className="
                                  h-7
                                  w-7
                                  shrink-0
                                  object-contain
                                "
                                loading="lazy"
                                onError={(event) => {
                                  event.currentTarget.src =
                                    PLACEHOLDER;
                                }}
                              />
                            </div>

                            {/* Prediction */}
                            <span
                              className={`
                                shrink-0
                                rounded-full
                                px-2.5
                                py-1
                                text-[11px]
                                font-bold
                                ${getPredictionBadgeClass(
                                  predictedResult
                                )}
                              `}
                            >
                              {predictedResult}
                            </span>
                          </div>

                          {/* Match time */}
                          <div
                            className="
                              mt-2
                              text-center
                              text-xs
                              font-medium
                              text-gray-500
                              dark:text-gray-400
                            "
                          >
                            🕒 {formatEAT(prediction.utcDate)}
                          </div>

                          {/* =================================================
                              COMPACT PROBABILITY BADGES
                          ================================================= */}

                          <div
                            className="
                              mt-3
                              flex
                              items-center
                              justify-center
                              gap-2
                            "
                            aria-label="Prediction probabilities"
                          >
                            {PROBABILITY_KEYS.map(
                              ([key, label]) => {
                                const probability =
                                  getProbability(
                                    probabilities,
                                    key
                                  );

                                return (
                                  <span
                                    key={key}
                                    className="
                                      rounded-lg
                                      bg-gray-100
                                      px-2.5
                                      py-1
                                      text-[11px]
                                      font-bold
                                      text-gray-700
                                      dark:bg-gray-800
                                      dark:text-gray-200
                                    "
                                  >
                                    {label}{" "}
                                    {formatPercent(
                                      probability
                                    )}
                                  </span>
                                );
                              }
                            )}
                          </div>
                        </motion.article>
                      );
                    }
                  )}
                </AnimatePresence>
              </section>
            )
          )}
        </div>
      )}
    </div>
  );
}
