// src/pages/ValueTips.jsx

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import api from "../api/api";

const PLACEHOLDER = "/logos/placeholder.png";

/* =========================================================
   HELPERS
========================================================= */

/**
 * Get today's date in Nairobi timezone.
 * Returns: YYYY-MM-DD
 */
function getTodayNairobi() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Africa/Nairobi",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());

  const values = {};

  parts.forEach(({ type, value }) => {
    values[type] = value;
  });

  return `${values.year}-${values.month}-${values.day}`;
}

function formatDate(value) {
  if (!value) return "Date TBC";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Date TBC";
  }

  return date.toLocaleDateString("en-KE", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Africa/Nairobi",
  });
}

function formatTime(value) {
  if (!value) return "--:--";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "--:--";
  }

  return date.toLocaleTimeString("en-KE", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Africa/Nairobi",
  });
}

function getMarketValue(tip, path) {
  return path
    .split(".")
    .reduce((obj, key) => obj?.[key], tip);
}

function formatMarket(market) {
  if (market == null) return null;

  let confidence = null;

  if (typeof market === "number") {
    confidence = market;
  } else if (typeof market === "object") {
    confidence =
      market.confidence ??
      market.probability ??
      market.prob ??
      market.value ??
      null;
  }

  if (confidence == null) return null;

  const raw = Number(confidence);

  if (!Number.isFinite(raw)) return null;

  const probability = raw <= 1 ? raw : raw / 100;

  const yes = probability >= 0.5;

  const displayProbability = Math.round(
    (yes ? probability : 1 - probability) * 100
  );

  return {
    side: yes ? "Yes" : "No",
    probability: displayProbability,
    isYes: yes,
  };
}

function getValue(tip) {
  const value =
    tip.value ??
    tip.edge ??
    tip.value_percentage ??
    tip.expected_value ??
    null;

  if (value == null) return null;

  const number = Number(value);

  if (!Number.isFinite(number)) return null;

  return number;
}

function getTipDate(tip) {
  return (
    tip.utcDate ||
    tip.utc_date ||
    tip.match_date ||
    tip.date ||
    tip.kickoff ||
    null
  );
}

/* =========================================================
   MARKET CONFIG
========================================================= */

const MARKETS = [
  {
    key: "btts",
    label: "BTTS",
    path: "btts",
  },
  {
    key: "over_1_5",
    label: "Over 1.5",
    path: "over_under.over_1_5",
  },
  {
    key: "over_2_5",
    label: "Over 2.5",
    path: "over_under.over_2_5",
  },
  {
    key: "over_3_5",
    label: "Over 3.5",
    path: "over_under.over_3_5",
  },
  {
    key: "over_4_5",
    label: "Over 4.5",
    path: "over_under.over_4_5",
  },
];

/* =========================================================
   MAIN COMPONENT
========================================================= */

export default function ValueTips() {
  const [tips, setTips] = useState([]);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const [search, setSearch] = useState("");

  // Load today's tips by default using Nairobi time.
  const [dateFilter, setDateFilter] = useState(
    getTodayNairobi
  );

  /* =======================================================
     LOAD TIPS
  ======================================================= */

  const loadTips = useCallback(
    async (manual = false, selectedDate = dateFilter) => {
      if (manual) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }

      setError("");

      try {
        const response = await api.getTipsValue(
          "TIMED,SCHEDULED",
          selectedDate || getTodayNairobi()
        );

        if (
          response?.success &&
          Array.isArray(response?.data?.tips)
        ) {
          setTips(response.data.tips);
        } else {
          setTips([]);

          setError(
            "No value tips are currently available for this date."
          );
        }
      } catch (err) {
        console.error(
          "Failed to load value tips:",
          err
        );

        setError(
          err?.response?.data?.message ||
            err?.message ||
            "Failed to load value tips."
        );

        setTips([]);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [dateFilter]
  );

  useEffect(() => {
    loadTips(false, dateFilter);
  }, [loadTips, dateFilter]);

  /* =======================================================
     FILTER TIPS
  ======================================================= */

  const filteredTips = useMemo(() => {
    const query = search.trim().toLowerCase();

    return tips
      .filter((tip) => {
        if (!query) return true;

        const home = String(
          tip.home_team_name || ""
        ).toLowerCase();

        const away = String(
          tip.away_team_name || ""
        ).toLowerCase();

        return (
          home.includes(query) ||
          away.includes(query)
        );
      })
      .sort((a, b) => {
        const dateA = getTipDate(a);
        const dateB = getTipDate(b);

        if (!dateA && !dateB) return 0;
        if (!dateA) return 1;
        if (!dateB) return -1;

        return (
          new Date(dateA).getTime() -
          new Date(dateB).getTime()
        );
      });
  }, [tips, search]);

  /* =======================================================
     SUMMARY
  ======================================================= */

  const summary = useMemo(() => {
    return {
      total: filteredTips.length,
    };
  }, [filteredTips]);

  /* =======================================================
     CLEAR FILTERS
  ======================================================= */

  const clearFilters = () => {
    setSearch("");
    setDateFilter(getTodayNairobi());
  };

  const hasFilters =
    Boolean(search) ||
    dateFilter !== getTodayNairobi();

  /* =======================================================
     LOADING
  ======================================================= */

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 px-4 pt-20 pb-24">
        <div className="mx-auto max-w-7xl">
          <div className="animate-pulse space-y-5">
            <div className="h-8 w-56 rounded bg-gray-200" />

            <div className="h-24 rounded-2xl border bg-white" />

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[1, 2, 3, 4, 5, 6].map((item) => (
                <div
                  key={item}
                  className="h-64 rounded-2xl border bg-white"
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  /* =======================================================
     RENDER
  ======================================================= */

  return (
    <div className="min-h-screen bg-gray-50 px-4 pb-24 pt-20">
      <div className="mx-auto max-w-7xl space-y-5">

        {/* =================================================
            HEADER
        ================================================= */}

        <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <div className="flex items-center gap-2">
              <div className="h-8 w-1.5 rounded-full bg-blue-600" />

              <h1 className="text-2xl font-extrabold tracking-tight text-gray-900 sm:text-3xl">
                Value Tips
              </h1>
            </div>

            <p className="mt-2 text-sm text-gray-500">
              Explore model-generated football value opportunities.
            </p>

            <div className="mt-2 inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-600" />
              {dateFilter === getTodayNairobi()
                ? "Today's Tips"
                : "Selected Date"}
            </div>
          </div>

          <button
            type="button"
            onClick={() => loadTips(true, dateFilter)}
            disabled={refreshing}
            className="
              inline-flex
              items-center
              justify-center
              gap-2
              rounded-xl
              bg-blue-600
              px-4
              py-2.5
              text-sm
              font-semibold
              text-white
              shadow-sm
              transition
              hover:bg-blue-700
              active:scale-95
              disabled:cursor-not-allowed
              disabled:opacity-60
            "
          >
            <span
              className={refreshing ? "animate-spin" : ""}
            >
              ↻
            </span>

            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        </header>

        {/* =================================================
            ERROR
        ================================================= */}

        {error && (
          <div
            className="
              flex
              items-center
              justify-between
              gap-3
              rounded-xl
              border
              border-red-200
              bg-red-50
              px-4
              py-3
              text-sm
              text-red-700
            "
          >
            <span>{error}</span>

            <button
              type="button"
              onClick={() => loadTips(true, dateFilter)}
              className="font-semibold underline"
            >
              Retry
            </button>
          </div>
        )}

        {/* =================================================
            SUMMARY
        ================================================= */}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard
            label="Available Tips"
            value={summary.total}
            icon="🎯"
          />
        </div>

        {/* =================================================
            SEARCH AND DATE
        ================================================= */}

        <div
          className="
            rounded-2xl
            border
            border-gray-200
            bg-white
            p-4
            shadow-sm
          "
        >
          <div className="flex flex-col gap-3 sm:flex-row">
            {/* Search */}

            <div className="relative flex-1">
              <span
                className="
                  pointer-events-none
                  absolute
                  left-3
                  top-1/2
                  -translate-y-1/2
                  text-gray-400
                "
              >
                🔎
              </span>

              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search home or away team..."
                className="
                  w-full
                  rounded-xl
                  border
                  border-gray-200
                  bg-gray-50
                  py-2.5
                  pl-10
                  pr-4
                  text-sm
                  outline-none
                  transition
                  focus:bg-white
                  focus:ring-2
                  focus:ring-blue-500
                "
              />
            </div>

            {/* Date */}

            <div className="sm:w-52">
              <label
                htmlFor="value-tips-date"
                className="mb-1 block text-xs font-semibold text-gray-500"
              >
                Match Date
              </label>

              <input
                id="value-tips-date"
                type="date"
                value={dateFilter}
                onChange={(e) =>
                  setDateFilter(
                    e.target.value || getTodayNairobi()
                  )
                }
                className="
                  w-full
                  rounded-xl
                  border
                  border-gray-200
                  bg-gray-50
                  px-3
                  py-2.5
                  text-sm
                  outline-none
                  transition
                  focus:bg-white
                  focus:ring-2
                  focus:ring-blue-500
                "
              />
            </div>
          </div>

          {/* Filter footer */}

          <div
            className="
              mt-3
              flex
              flex-wrap
              items-center
              justify-between
              gap-2
              border-t
              border-gray-100
              pt-3
            "
          >
            <span className="text-xs text-gray-500">
              Showing{" "}
              <strong className="text-gray-800">
                {filteredTips.length}
              </strong>{" "}
              of{" "}
              <strong className="text-gray-800">
                {tips.length}
              </strong>{" "}
              tips
            </span>

            {hasFilters && (
              <button
                type="button"
                onClick={clearFilters}
                className="
                  text-xs
                  font-semibold
                  text-blue-600
                  transition
                  hover:text-blue-800
                "
              >
                Reset to Today
              </button>
            )}
          </div>
        </div>

        {/* =================================================
            EMPTY STATE
        ================================================= */}

        {!filteredTips.length && (
          <div
            className="
              rounded-2xl
              border
              border-dashed
              border-gray-300
              bg-white
              p-12
              text-center
            "
          >
            <div className="mb-4 text-5xl">🔎</div>

            <h2 className="font-bold text-gray-800">
              No value tips found
            </h2>

            <p className="mt-1 text-sm text-gray-500">
              Try another team or select a different date.
            </p>

            {hasFilters && (
              <button
                type="button"
                onClick={clearFilters}
                className="
                  mt-4
                  rounded-lg
                  bg-blue-600
                  px-4
                  py-2
                  text-sm
                  font-semibold
                  text-white
                  transition
                  hover:bg-blue-700
                "
              >
                Show Today's Tips
              </button>
            )}
          </div>
        )}

        {/* =================================================
            TIPS
        ================================================= */}

        <div
          className="
            grid
            grid-cols-1
            gap-4
            md:grid-cols-2
            xl:grid-cols-3
          "
        >
          {filteredTips.map((tip, index) => (
            <ValueTipCard
              key={
                tip.match_id ??
                tip.id ??
                `${tip.home_team_name}-${tip.away_team_name}-${index}`
              }
              tip={tip}
              rank={index + 1}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

/* =========================================================
   SUMMARY CARD
========================================================= */

function SummaryCard({ label, value, icon }) {
  return (
    <div
      className="
        rounded-2xl
        border
        border-gray-200
        bg-white
        p-4
        shadow-sm
      "
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-xl">{icon}</span>

        <span className="text-2xl font-extrabold text-gray-900">
          {value}
        </span>
      </div>

      <p className="mt-2 text-xs text-gray-500">
        {label}
      </p>
    </div>
  );
}

/* =========================================================
   VALUE TIP CARD
========================================================= */

function ValueTipCard({ tip, rank }) {
  const value = getValue(tip);
  const date = getTipDate(tip);

  const prediction =
    tip.predicted_score?.most_likely ??
    tip.predicted_score ??
    tip.prediction ??
    "-";

  return (
    <article
      className="
        group
        overflow-hidden
        rounded-2xl
        border
        border-gray-200
        bg-white
        shadow-sm
        transition-all
        duration-200
        hover:-translate-y-0.5
        hover:shadow-lg
      "
    >
      {/* =================================================
          CARD HEADER
      ================================================= */}

      <div
        className="
          flex
          items-center
          justify-between
          gap-2
          border-b
          border-gray-100
          px-4
          py-3
        "
      >
        <div className="flex items-center gap-2">
          <span
            className="
              flex
              h-7
              w-7
              items-center
              justify-center
              rounded-full
              bg-gray-100
              text-xs
              font-bold
              text-gray-600
            "
          >
            #{rank}
          </span>

          <div>
            <p className="text-xs font-semibold text-gray-500">
              {formatDate(date)}
            </p>

            <p className="text-[11px] text-gray-400">
              {formatTime(date)} EAT
            </p>
          </div>
        </div>

        <span
          className="
            rounded-full
            border
            border-blue-100
            bg-blue-50
            px-2.5
            py-1
            text-[10px]
            font-bold
            uppercase
            tracking-wide
            text-blue-600
          "
        >
          Value
        </span>
      </div>

      {/* =================================================
          TEAMS AND PREDICTED SCORE
      ================================================= */}

      <div className="px-4 py-5">
        <div
          className="
            grid
            grid-cols-[1fr_auto_1fr]
            items-center
            gap-3
          "
        >
          {/* HOME */}

          <TeamBlock
            name={tip.home_team_name}
            logo={tip.home_logo}
            align="left"
          />

          {/* SCORE */}

          <div className="text-center">
            <span
              className="
                mb-1
                block
                text-[10px]
                uppercase
                tracking-wider
                text-gray-400
              "
            >
              Predicted
            </span>

            <span
              className="
                text-xl
                font-extrabold
                text-gray-900
              "
            >
              {prediction}
            </span>
          </div>

          {/* AWAY */}

          <TeamBlock
            name={tip.away_team_name}
            logo={tip.away_logo}
            align="right"
          />
        </div>
      </div>

      {/* =================================================
          MARKETS
      ================================================= */}

      <div className="px-4 py-4">
        <div className="grid grid-cols-2 gap-2">
          {MARKETS.map((market) => {
            const result = formatMarket(
              getMarketValue(tip, market.path)
            );

            if (!result) return null;

            return (
              <MarketItem
                key={market.key}
                label={market.label}
                result={result}
              />
            );
          })}
        </div>
      </div>

      {/* =================================================
          MODEL VALUE
      ================================================= */}

      {value != null && (
        <div
          className="
            mx-4
            mb-4
            flex
            items-center
            justify-between
            gap-3
            rounded-xl
            border
            border-blue-100
            bg-blue-50
            px-3
            py-3
          "
        >
          <div>
            <p
              className="
                text-[11px]
                font-semibold
                uppercase
                text-blue-600
              "
            >
              Model Value
            </p>

            <p className="mt-0.5 text-xs text-blue-500">
              Estimated betting edge
            </p>
          </div>

          <span
            className="
              text-lg
              font-extrabold
              text-blue-700
            "
          >
            {value > 0 ? "+" : ""}
            {value.toFixed(2)}
            {Math.abs(value) <= 1 ? "" : "%"}
          </span>
        </div>
      )}

      {/* =================================================
          FOOTER
      ================================================= */}

      <div
        className="
          flex
          items-center
          justify-between
          gap-2
          border-t
          border-gray-100
          bg-gray-50
          px-4
          py-3
        "
      >
        <span className="text-[11px] text-gray-400">
          AI/model generated
        </span>

        <span className="text-[11px] font-semibold text-blue-600">
          Value Opportunity →
        </span>
      </div>
    </article>
  );
}

/* =========================================================
   TEAM BLOCK
========================================================= */

function TeamBlock({
  name,
  logo,
  align = "left",
}) {
  return (
    <div
      className={`
        flex
        min-w-0
        flex-col
        gap-2
        ${
          align === "right"
            ? "items-end text-right"
            : "items-start text-left"
        }
      `}
    >
      <img
        src={logo || PLACEHOLDER}
        alt={name || "Team logo"}
        className="
          h-10
          w-10
          object-contain
          sm:h-12
          sm:w-12
        "
        loading="lazy"
        onError={(e) => {
          if (
            e.currentTarget.src.endsWith(PLACEHOLDER)
          ) {
            return;
          }

          e.currentTarget.src = PLACEHOLDER;
        }}
      />

      <span
        className="
          line-clamp-2
          text-sm
          font-bold
          leading-tight
          text-gray-800
        "
      >
        {name || "Unknown Team"}
      </span>
    </div>
  );
}

/* =========================================================
   MARKET ITEM
========================================================= */

function MarketItem({ label, result }) {
  return (
    <div
      className="
        rounded-xl
        border
        border-gray-100
        bg-gray-50
        px-3
        py-2.5
      "
    >
      <div className="flex items-center justify-between gap-2">
        <span
          className="
            text-[11px]
            font-semibold
            text-gray-500
          "
        >
          {label}
        </span>

        <span
          className={`
            text-[11px]
            font-extrabold
            ${
              result.isYes
                ? "text-green-600"
                : "text-red-500"
            }
          `}
        >
          {result.side}
        </span>
      </div>

      <div className="mt-1 flex items-center justify-between">
        <div
          className="
            mr-2
            h-1.5
            flex-1
            overflow-hidden
            rounded-full
            bg-gray-200
          "
        >
          <div
            className={
              result.isYes
                ? "h-full rounded-full bg-green-500"
                : "h-full rounded-full bg-red-400"
            }
            style={{
              width: `${result.probability}%`,
            }}
          />
        </div>

        <span
          className="
            text-[10px]
            font-bold
            text-gray-700
          "
        >
          {result.probability}%
        </span>
      </div>
    </div>
  );
}
