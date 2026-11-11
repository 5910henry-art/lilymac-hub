// src/pages/H2H.jsx

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  getTeams,
  getH2H,
  attachLogosSafe,
} from "../api/api";
import Loader from "../components/Loader";

const PLACEHOLDER = "/logos/placeholder.png";

/* =========================================================
   HELPERS
========================================================= */

function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function getDateValue(match) {
  return (
    match?.date_played ||
    match?.match_date ||
    match?.date ||
    match?.utcDate ||
    match?.match_time ||
    match?.kickoff ||
    null
  );
}

function getMatchDate(match) {
  const value = getDateValue(match);

  if (!value) return null;

  const date = new Date(value);

  return Number.isNaN(date.getTime()) ? null : date;
}

function getTimestamp(match) {
  const date = getMatchDate(match);
  return date ? date.getTime() : 0;
}

function formatDate(match) {
  const date = getMatchDate(match);

  if (!date) {
    return "Unknown date";
  }

  return date.toLocaleDateString("en-KE", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Africa/Nairobi",
  });
}

function getResultType(match) {
  const homeScore = safeNumber(match?.home_score);
  const awayScore = safeNumber(match?.away_score);

  if (homeScore > awayScore) {
    return "Home Win";
  }

  if (homeScore < awayScore) {
    return "Away Win";
  }

  return "Draw";
}

function getTeamResult(match, selectedTeamId) {
  const homeScore = safeNumber(match?.home_score);
  const awayScore = safeNumber(match?.away_score);

  const selectedId = Number(selectedTeamId);
  const homeId = Number(match?.home_team_id);
  const awayId = Number(match?.away_team_id);

  if (
    Number.isFinite(selectedId) &&
    Number.isFinite(homeId) &&
    selectedId === homeId
  ) {
    if (homeScore > awayScore) return "W";
    if (homeScore < awayScore) return "L";
    return "D";
  }

  if (
    Number.isFinite(selectedId) &&
    Number.isFinite(awayId) &&
    selectedId === awayId
  ) {
    if (awayScore > homeScore) return "W";
    if (awayScore < homeScore) return "L";
    return "D";
  }

  const selectedName = String(
    selectedTeamId || ""
  )
    .trim()
    .toLowerCase();

  const homeName = String(
    match?.home_team_name || ""
  )
    .trim()
    .toLowerCase();

  const awayName = String(
    match?.away_team_name || ""
  )
    .trim()
    .toLowerCase();

  if (selectedName && selectedName === homeName) {
    if (homeScore > awayScore) return "W";
    if (homeScore < awayScore) return "L";
    return "D";
  }

  if (selectedName && selectedName === awayName) {
    if (awayScore > homeScore) return "W";
    if (awayScore < homeScore) return "L";
    return "D";
  }

  return null;
}

function getBadgeClasses(result) {
  if (result === "W") {
    return "bg-emerald-50 text-emerald-700 border border-emerald-200";
  }

  if (result === "L") {
    return "bg-rose-50 text-rose-700 border border-rose-200";
  }

  return "bg-amber-50 text-amber-700 border border-amber-200";
}

function getResultLabel(result) {
  if (result === "W") return "Win";
  if (result === "L") return "Loss";
  return "Draw";
}

function percentage(value, total) {
  if (!total) return 0;
  return (value / total) * 100;
}

function formatPercentage(value) {
  return `${safeNumber(value).toFixed(1)}%`;
}

/* =========================================================
   MAIN COMPONENT
========================================================= */

export default function H2H() {
  const [teams, setTeams] = useState([]);

  const [homeId, setHomeId] = useState("");
  const [awayId, setAwayId] = useState("");

  const [matches, setMatches] = useState([]);

  const [loading, setLoading] = useState(true);
  const [matchesLoading, setMatchesLoading] =
    useState(false);

  const [error, setError] = useState("");

  const [homeSearch, setHomeSearch] = useState("");
  const [awaySearch, setAwaySearch] = useState("");

  const [resultFilter, setResultFilter] =
    useState("all");

  const [searchQuery, setSearchQuery] = useState("");

  const [sortOrder, setSortOrder] =
    useState("newest");

  const [showOnlyScoring, setShowOnlyScoring] =
    useState(false);

  const [showOnlyHighScoring, setShowOnlyHighScoring] =
    useState(false);

  /* =======================================================
     SELECTED TEAMS
  ======================================================= */

  const homeTeam = useMemo(() => {
    return teams.find(
      (team) => String(team.id) === String(homeId)
    );
  }, [teams, homeId]);

  const awayTeam = useMemo(() => {
    return teams.find(
      (team) => String(team.id) === String(awayId)
    );
  }, [teams, awayId]);

  /* =======================================================
     LOAD TEAMS
  ======================================================= */

  const fetchTeams = useCallback(async () => {
    try {
      setLoading(true);
      setError("");

      const response = await getTeams();

      if (
        response?.success &&
        Array.isArray(response.data?.teams)
      ) {
        const list = response.data.teams;

        setTeams(list);

        if (!homeId && list.length > 0) {
          setHomeId(String(list[0]?.id || ""));
        }

        if (!awayId && list.length > 1) {
          setAwayId(String(list[1]?.id || ""));
        }
      } else {
        setTeams([]);
        setHomeId("");
        setAwayId("");
        setError("No teams available.");
      }
    } catch (err) {
      console.error(
        "Failed to load teams:",
        err
      );

      setTeams([]);
      setHomeId("");
      setAwayId("");
      setError("Failed to load teams.");
    } finally {
      setLoading(false);
    }
  }, [homeId, awayId]);

  useEffect(() => {
    fetchTeams();
  }, [fetchTeams]);

  /* =======================================================
     LOAD H2H
  ======================================================= */

  const fetchH2H = useCallback(async () => {
    if (!homeId || !awayId) {
      setMatches([]);
      return;
    }

    if (String(homeId) === String(awayId)) {
      setMatches([]);
      setError(
        "Please select two different teams."
      );
      return;
    }

    try {
      setMatchesLoading(true);
      setError("");

      /*
       * Clear old results immediately.
       * This makes the team change visually obvious
       * while the new H2H data is being loaded.
       */
      setMatches([]);

      const response = await getH2H(
        homeId,
        awayId,
        100
      );

      if (
        !response?.success ||
        !Array.isArray(response.data?.matches)
      ) {
        setMatches([]);
        return;
      }

      const processed =
        response.data.matches.map((match) => {
          try {
            const withLogos = attachLogosSafe(
              match,
              "home_team_name",
              "away_team_name",
              "home_team_id",
              "away_team_id"
            );

            return {
              ...match,

              home_team_name:
                match.home_team_name ||
                match.home_team ||
                match.home ||
                "Home",

              away_team_name:
                match.away_team_name ||
                match.away_team ||
                match.away ||
                "Away",

              home_logo:
                withLogos?.home_logo ||
                match.home_logo ||
                PLACEHOLDER,

              away_logo:
                withLogos?.away_logo ||
                match.away_logo ||
                PLACEHOLDER,
            };
          } catch (err) {
            return {
              ...match,

              home_team_name:
                match.home_team_name ||
                match.home_team ||
                match.home ||
                "Home",

              away_team_name:
                match.away_team_name ||
                match.away_team ||
                match.away ||
                "Away",

              home_logo:
                match.home_logo ||
                PLACEHOLDER,

              away_logo:
                match.away_logo ||
                PLACEHOLDER,
            };
          }
        });

      setMatches(processed);
    } catch (err) {
      console.error(
        "Failed to load H2H:",
        err
      );

      setMatches([]);
      setError(
        "Failed to load head-to-head matches."
      );
    } finally {
      setMatchesLoading(false);
    }
  }, [homeId, awayId]);

  useEffect(() => {
    fetchH2H();
  }, [fetchH2H]);

  /* =======================================================
     TEAM SEARCH
  ======================================================= */

  const filteredHomeTeams = useMemo(() => {
    const query = homeSearch
      .trim()
      .toLowerCase();

    if (!query) {
      return teams;
    }

    return teams.filter((team) =>
      String(team?.name || "")
        .toLowerCase()
        .includes(query)
    );
  }, [teams, homeSearch]);

  const filteredAwayTeams = useMemo(() => {
    const query = awaySearch
      .trim()
      .toLowerCase();

    if (!query) {
      return teams;
    }

    return teams.filter((team) =>
      String(team?.name || "")
        .toLowerCase()
        .includes(query)
    );
  }, [teams, awaySearch]);

  /* =======================================================
     TEAM CHANGE
  ======================================================= */

  const handleHomeTeamChange = useCallback(
    (value) => {
      if (String(value) === String(awayId)) {
        setError(
          "Please select two different teams."
        );
      } else {
        setError("");
      }

      setHomeId(String(value));
    },
    [awayId]
  );

  const handleAwayTeamChange = useCallback(
    (value) => {
      if (String(value) === String(homeId)) {
        setError(
          "Please select two different teams."
        );
      } else {
        setError("");
      }

      setAwayId(String(value));
    },
    [homeId]
  );

  /* =======================================================
     SWAP
  ======================================================= */

  const swapTeams = useCallback(() => {
    setHomeId(awayId);
    setAwayId(homeId);

    setHomeSearch("");
    setAwaySearch("");
    setError("");
  }, [homeId, awayId]);

  /* =======================================================
     FILTERED MATCHES
  ======================================================= */

  const filteredMatches = useMemo(() => {
    const query = searchQuery
      .trim()
      .toLowerCase();

    const list = matches.filter((match) => {
      const result = getResultType(match);

      if (
        resultFilter !== "all" &&
        result !== resultFilter
      ) {
        return false;
      }

      if (
        showOnlyScoring &&
        safeNumber(match.home_score) +
          safeNumber(match.away_score) ===
          0
      ) {
        return false;
      }

      if (
        showOnlyHighScoring &&
        safeNumber(match.home_score) +
          safeNumber(match.away_score) <
          3
      ) {
        return false;
      }

      if (query) {
        const haystack = [
          match.home_team_name,
          match.away_team_name,
          formatDate(match),
        ]
          .join(" ")
          .toLowerCase();

        if (!haystack.includes(query)) {
          return false;
        }
      }

      return true;
    });

    return [...list].sort((a, b) => {
      const timeA = getTimestamp(a);
      const timeB = getTimestamp(b);

      if (sortOrder === "oldest") {
        return timeA - timeB;
      }

      return timeB - timeA;
    });
  }, [
    matches,
    resultFilter,
    searchQuery,
    sortOrder,
    showOnlyScoring,
    showOnlyHighScoring,
  ]);

  /* =======================================================
     SUMMARY
  ======================================================= */

  const summary = useMemo(() => {
    let homeWins = 0;
    let awayWins = 0;
    let draws = 0;

    let totalGoals = 0;
    let over25 = 0;
    let btts = 0;

    matches.forEach((match) => {
      const homeScore = safeNumber(
        match.home_score
      );

      const awayScore = safeNumber(
        match.away_score
      );

      const result = getResultType(match);

      if (result === "Draw") {
        draws++;
      } else if (result === "Home Win") {
        homeWins++;
      } else {
        awayWins++;
      }

      const goals =
        homeScore + awayScore;

      totalGoals += goals;

      if (goals > 2) {
        over25++;
      }

      if (
        homeScore > 0 &&
        awayScore > 0
      ) {
        btts++;
      }
    });

    const total = matches.length;

    const selectedHomeWins =
      matches.filter(
        (match) =>
          getTeamResult(
            match,
            homeId
          ) === "W"
      ).length;

    const selectedAwayWins =
      matches.filter(
        (match) =>
          getTeamResult(
            match,
            awayId
          ) === "W"
      ).length;

    return {
      total,
      homeWins,
      awayWins,
      draws,
      totalGoals,

      averageGoals:
        total > 0
          ? totalGoals / total
          : 0,

      over25,
      over25Pct:
        percentage(over25, total),

      btts,
      bttsPct:
        percentage(btts, total),

      homeWinPct:
        percentage(homeWins, total),

      awayWinPct:
        percentage(awayWins, total),

      drawPct:
        percentage(draws, total),

      selectedHomeWins,
      selectedAwayWins,
    };
  }, [matches, homeId, awayId]);

  /* =======================================================
     FILTER RESET
  ======================================================= */

  const clearFilters = () => {
    setResultFilter("all");
    setSearchQuery("");
    setSortOrder("newest");
    setShowOnlyScoring(false);
    setShowOnlyHighScoring(false);
  };

  const hasActiveFilters =
    resultFilter !== "all" ||
    searchQuery.trim() !== "" ||
    sortOrder !== "newest" ||
    showOnlyScoring ||
    showOnlyHighScoring;

  /* =======================================================
     LOADING
  ======================================================= */

  if (loading) {
    return <Loader text="Loading H2H..." />;
  }

  /* =======================================================
     RENDER
  ======================================================= */

  return (
    <div className="min-h-screen bg-slate-50 pb-24 pt-16">
      <div className="
        mx-auto
        w-full
        max-w-7xl
        px-4
        sm:px-6
        lg:px-8
      ">

        {/* =================================================
            HEADER
        ================================================= */}

        <div className="mb-6">
          <div className="
            flex
            flex-col
            gap-3
            sm:flex-row
            sm:items-end
            sm:justify-between
          ">
            <div>
              <p className="
                text-xs
                font-bold
                uppercase
                tracking-[0.2em]
                text-blue-600
              ">
                Football Analytics
              </p>

              <h1 className="
                mt-1
                text-2xl
                font-black
                tracking-tight
                text-slate-900
                sm:text-3xl
              ">
                Head-to-Head
              </h1>

              <p className="
                mt-1
                text-sm
                text-slate-500
              ">
                Compare historical meetings,
                results and goal trends.
              </p>
            </div>

            <button
              type="button"
              onClick={fetchH2H}
              disabled={
                matchesLoading ||
                !homeId ||
                !awayId
              }
              className="
                rounded-xl
                border
                border-slate-200
                bg-white
                px-4
                py-2.5
                text-sm
                font-semibold
                text-slate-700
                shadow-sm
                transition
                hover:border-blue-300
                hover:text-blue-600
                disabled:cursor-not-allowed
                disabled:opacity-50
              "
            >
              {matchesLoading
                ? "Refreshing..."
                : "↻ Refresh"}
            </button>
          </div>
        </div>

        {/* =================================================
            TEAM SELECTOR
        ================================================= */}

        <section className="
          mb-5
          rounded-2xl
          border
          border-slate-200
          bg-white
          p-4
          shadow-sm
          sm:p-5
        ">
          <div className="mb-4">
            <h2 className="font-bold text-slate-900">
              Compare Teams
            </h2>

            <p className="
              mt-1
              text-xs
              text-slate-500
            ">
              Search and select two teams to
              view their historical meetings.
            </p>
          </div>

          <div className="
            grid
            gap-4
            md:grid-cols-[1fr_auto_1fr]
            md:items-center
          ">

            {/* TEAM 1 */}

            <TeamSelector
              label="Team 1"
              team={homeTeam}
              value={homeId}
              search={homeSearch}
              setSearch={setHomeSearch}
              options={filteredHomeTeams}
              onChange={handleHomeTeamChange}
            />

            {/* SWAP */}

            <button
              type="button"
              onClick={swapTeams}
              disabled={
                matchesLoading ||
                !homeId ||
                !awayId
              }
              aria-label="Swap teams"
              className="
                flex
                h-11
                w-11
                items-center
                justify-center
                self-center
                rounded-xl
                border
                border-slate-200
                bg-slate-50
                text-lg
                font-bold
                text-slate-600
                shadow-sm
                transition
                hover:border-blue-300
                hover:bg-blue-50
                hover:text-blue-600
                disabled:cursor-not-allowed
                disabled:opacity-50
              "
            >
              ↔
            </button>

            {/* TEAM 2 */}

            <TeamSelector
              label="Team 2"
              team={awayTeam}
              value={awayId}
              search={awaySearch}
              setSearch={setAwaySearch}
              options={filteredAwayTeams}
              onChange={handleAwayTeamChange}
            />
          </div>

          {homeId === awayId &&
            homeId !== "" && (
              <div className="
                mt-4
                flex
                items-center
                gap-2
                rounded-xl
                border
                border-amber-200
                bg-amber-50
                px-4
                py-3
                text-sm
                text-amber-700
              ">
                <span>⚠️</span>

                <span>
                  Please select two different
                  teams.
                </span>
              </div>
            )}

          {/* DATA REFRESH INDICATOR */}

          {matchesLoading && (
            <div className="
              mt-4
              flex
              items-center
              gap-2
              rounded-xl
              border
              border-blue-100
              bg-blue-50
              px-4
              py-3
              text-xs
              font-semibold
              text-blue-700
            ">
              <span className="
                h-3.5
                w-3.5
                animate-spin
                rounded-full
                border-2
                border-blue-200
                border-t-blue-600
              " />

              Updating H2H for{" "}
              <span className="font-black">
                {homeTeam?.name || "Team 1"}
              </span>

              <span>vs</span>

              <span className="font-black">
                {awayTeam?.name || "Team 2"}
              </span>
            </div>
          )}
        </section>

        {/* ERROR */}

        {error &&
          homeId !== awayId && (
            <div className="
              mb-5
              rounded-xl
              border
              border-rose-200
              bg-rose-50
              px-4
              py-3
              text-sm
              text-rose-700
            ">
              {error}
            </div>
          )}

        {/* =================================================
            TEAM BANNER
        ================================================= */}

        {(homeTeam || awayTeam) && (
          <section className="
            mb-5
            overflow-hidden
            rounded-2xl
            bg-gradient-to-r
            from-slate-950
            via-slate-900
            to-blue-950
            p-5
            text-white
            shadow-sm
            sm:p-6
          ">
            <div className="
              grid
              grid-cols-[1fr_auto_1fr]
              items-center
              gap-4
            ">
              <TeamBanner
                team={homeTeam}
                align="left"
              />

              <div className="
                flex
                flex-col
                items-center
              ">
                <span className="
                  text-[10px]
                  font-bold
                  uppercase
                  tracking-[0.2em]
                  text-slate-400
                ">
                  Head to Head
                </span>

                <span className="
                  mt-1
                  text-lg
                  font-black
                  text-white
                ">
                  VS
                </span>
              </div>

              <TeamBanner
                team={awayTeam}
                align="right"
              />
            </div>
          </section>
        )}

        {/* =================================================
            SUMMARY CARDS
        ================================================= */}

        {matches.length > 0 && (
          <section className="
            mb-5
            grid
            grid-cols-2
            gap-3
            sm:grid-cols-3
            lg:grid-cols-6
          ">
            <SummaryCard
              label="Matches"
              value={summary.total}
            />

            <SummaryCard
              label={
                homeTeam?.name ||
                "Team 1"
              }
              value={summary.selectedHomeWins}
              subtitle="wins"
              accent="emerald"
            />

            <SummaryCard
              label={
                awayTeam?.name ||
                "Team 2"
              }
              value={summary.selectedAwayWins}
              subtitle="wins"
              accent="blue"
            />

            <SummaryCard
              label="Draws"
              value={summary.draws}
              accent="amber"
            />

            <SummaryCard
              label="Over 2.5"
              value={formatPercentage(
                summary.over25Pct
              )}
              accent="violet"
            />

            <SummaryCard
              label="BTTS"
              value={formatPercentage(
                summary.bttsPct
              )}
              accent="rose"
            />
          </section>
        )}

        {/* =================================================
            WIN DISTRIBUTION
        ================================================= */}

        {matches.length > 0 && (
          <section className="
            mb-5
            rounded-2xl
            border
            border-slate-200
            bg-white
            p-5
            shadow-sm
            sm:p-6
          ">
            <div className="mb-4">
              <h2 className="
                font-bold
                text-slate-900
              ">
                Outcome Distribution
              </h2>

              <p className="
                mt-1
                text-xs
                text-slate-500
              ">
                How previous meetings ended.
              </p>
            </div>

            <div className="space-y-4">
              <DistributionBar
                label={
                  homeTeam?.name ||
                  "Team 1"
                }
                value={
                  summary.homeWinPct
                }
                color="bg-emerald-500"
              />

              <DistributionBar
                label="Draw"
                value={
                  summary.drawPct
                }
                color="bg-amber-400"
              />

              <DistributionBar
                label={
                  awayTeam?.name ||
                  "Team 2"
                }
                value={
                  summary.awayWinPct
                }
                color="bg-blue-500"
              />
            </div>
          </section>
        )}

        {/* =================================================
            FILTERS
        ================================================= */}

        {matches.length > 0 && (
          <section className="
            mb-5
            rounded-2xl
            border
            border-slate-200
            bg-white
            p-4
            shadow-sm
          ">
            <div className="
              mb-3
              flex
              items-center
              justify-between
              gap-3
            ">
              <div>
                <h2 className="
                  font-bold
                  text-slate-900
                ">
                  Match Filters
                </h2>

                <p className="
                  mt-1
                  text-xs
                  text-slate-500
                ">
                  Narrow down the history.
                </p>
              </div>

              {hasActiveFilters && (
                <button
                  type="button"
                  onClick={clearFilters}
                  className="
                    text-xs
                    font-semibold
                    text-blue-600
                    hover:text-blue-700
                  "
                >
                  Clear filters
                </button>
              )}
            </div>

            <div className="
              grid
              gap-3
              sm:grid-cols-2
              lg:grid-cols-4
            ">
              {/* SEARCH */}

              <div className="lg:col-span-2">
                <label className="
                  mb-1.5
                  block
                  text-xs
                  font-semibold
                  text-slate-500
                ">
                  Search matches
                </label>

                <input
                  type="text"
                  value={searchQuery}
                  onChange={(event) =>
                    setSearchQuery(
                      event.target.value
                    )
                  }
                  placeholder="Search team or date..."
                  className="
                    w-full
                    rounded-xl
                    border
                    border-slate-200
                    bg-slate-50
                    px-3
                    py-2.5
                    text-sm
                    text-slate-700
                    outline-none
                    transition
                    focus:border-blue-500
                    focus:bg-white
                  "
                />
              </div>

              {/* RESULT */}

              <div>
                <label className="
                  mb-1.5
                  block
                  text-xs
                  font-semibold
                  text-slate-500
                ">
                  Result
                </label>

                <select
                  value={resultFilter}
                  onChange={(event) =>
                    setResultFilter(
                      event.target.value
                    )
                  }
                  className="
                    w-full
                    rounded-xl
                    border
                    border-slate-200
                    bg-slate-50
                    px-3
                    py-2.5
                    text-sm
                    text-slate-700
                    outline-none
                    focus:border-blue-500
                  "
                >
                  <option value="all">
                    All results
                  </option>

                  <option value="Home Win">
                    Home wins
                  </option>

                  <option value="Away Win">
                    Away wins
                  </option>

                  <option value="Draw">
                    Draws
                  </option>
                </select>
              </div>

              {/* SORT */}

              <div>
                <label className="
                  mb-1.5
                  block
                  text-xs
                  font-semibold
                  text-slate-500
                ">
                  Sort
                </label>

                <select
                  value={sortOrder}
                  onChange={(event) =>
                    setSortOrder(
                      event.target.value
                    )
                  }
                  className="
                    w-full
                    rounded-xl
                    border
                    border-slate-200
                    bg-slate-50
                    px-3
                    py-2.5
                    text-sm
                    text-slate-700
                    outline-none
                    focus:border-blue-500
                  "
                >
                  <option value="newest">
                    Newest first
                  </option>

                  <option value="oldest">
                    Oldest first
                  </option>
                </select>
              </div>
            </div>

            {/* TOGGLES */}

            <div className="
              mt-4
              flex
              flex-wrap
              gap-2
            ">
              <FilterToggle
                active={showOnlyScoring}
                onClick={() =>
                  setShowOnlyScoring(
                    (value) => !value
                  )
                }
              >
                ⚽ Goals scored
              </FilterToggle>

              <FilterToggle
                active={showOnlyHighScoring}
                onClick={() =>
                  setShowOnlyHighScoring(
                    (value) => !value
                  )
                }
              >
                🔥 3+ goals
              </FilterToggle>
            </div>
          </section>
        )}

        {/* =================================================
            MATCH COUNT
        ================================================= */}

        {matches.length > 0 && (
          <div className="
            mb-3
            flex
            items-center
            justify-between
          ">
            <span className="
              text-sm
              font-semibold
              text-slate-700
            ">
              {filteredMatches.length}{" "}
              {filteredMatches.length === 1
                ? "match"
                : "matches"}
            </span>

            <span className="
              text-xs
              text-slate-400
            ">
              {matches.length} total
            </span>
          </div>
        )}

        {/* =================================================
            LOADING H2H
        ================================================= */}

        {matchesLoading && (
          <div className="
            mb-5
            flex
            items-center
            justify-center
            rounded-2xl
            border
            border-blue-100
            bg-white
            p-10
            shadow-sm
          ">
            <div className="text-center">
              <div className="
                mx-auto
                h-8
                w-8
                animate-spin
                rounded-full
                border-2
                border-slate-200
                border-t-blue-600
              " />

              <p className="
                mt-3
                text-sm
                font-semibold
                text-slate-600
              ">
                Loading head-to-head history...
              </p>
            </div>
          </div>
        )}

        {/* =================================================
            EMPTY
        ================================================= */}

        {!matchesLoading &&
          filteredMatches.length === 0 && (
            <div className="
              rounded-2xl
              border
              border-dashed
              border-slate-300
              bg-white
              p-10
              text-center
            ">
              <div className="text-5xl">
                ⚽
              </div>

              <h3 className="
                mt-4
                font-bold
                text-slate-800
              ">
                No matches found
              </h3>

              <p className="
                mx-auto
                mt-1
                max-w-md
                text-sm
                text-slate-500
              ">
                There are no head-to-head
                matches matching the current
                teams and filters.
              </p>

              {hasActiveFilters && (
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
                  Reset filters
                </button>
              )}
            </div>
          )}

        {/* =================================================
            MATCH HISTORY
        ================================================= */}

        {!matchesLoading &&
          filteredMatches.length > 0 && (
            <div className="space-y-3">
              {filteredMatches.map(
                (match, index) => (
                  <MatchCard
                    key={
                      match.match_id ||
                      match.id ||
                      `${match.home_team_name}-${match.away_team_name}-${index}`
                    }
                    match={match}
                    selectedHomeId={homeId}
                  />
                )
              )}
            </div>
          )}

        {/* =================================================
            FOOTER STATS
        ================================================= */}

        {matches.length > 0 && (
          <section className="
            mt-6
            rounded-2xl
            border
            border-slate-200
            bg-white
            p-5
            shadow-sm
          ">
            <div className="
              grid
              grid-cols-2
              gap-4
              sm:grid-cols-4
            ">
              <MiniStat
                label="Total Goals"
                value={
                  summary.totalGoals
                }
              />

              <MiniStat
                label="Avg Goals"
                value={summary.averageGoals.toFixed(1)}
              />

              <MiniStat
                label="Over 2.5"
                value={formatPercentage(
                  summary.over25Pct
                )}
              />

              <MiniStat
                label="BTTS"
                value={formatPercentage(
                  summary.bttsPct
                )}
              />
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

/* =========================================================
   TEAM SELECTOR
========================================================= */

function TeamSelector({
  label,
  team,
  value,
  search,
  setSearch,
  options,
  onChange,
}) {
  const [isOpen, setIsOpen] = useState(false);

  const selectedTeam = team;

  const visibleOptions = useMemo(() => {
    const query = search
      .trim()
      .toLowerCase();

    const filtered = options.filter((item) =>
      String(item?.name || "")
        .toLowerCase()
        .includes(query)
    );

    /*
     * Always keep the currently selected team
     * visible, even when searching.
     */
    if (
      selectedTeam &&
      !filtered.some(
        (item) =>
          String(item.id) ===
          String(selectedTeam.id)
      )
    ) {
      return [selectedTeam, ...filtered];
    }

    return filtered;
  }, [
    options,
    search,
    selectedTeam,
  ]);

  const handleSelect = (selectedValue) => {
    onChange(String(selectedValue));

    setSearch("");
    setIsOpen(false);
  };

  return (
    <div className="
      relative
      min-w-0
    ">
      {/* LABEL */}

      <label className="
        mb-2
        block
        text-xs
        font-bold
        uppercase
        tracking-wider
        text-slate-400
      ">
        {label}
      </label>

      {/* SELECTED TEAM */}

      <div className="
        mb-2
        flex
        min-h-[64px]
        items-center
        gap-3
        rounded-xl
        border
        border-blue-100
        bg-gradient-to-r
        from-blue-50
        to-slate-50
        px-3
        py-2
      ">
        <div className="
          flex
          h-10
          w-10
          flex-shrink-0
          items-center
          justify-center
          rounded-full
          border
          border-slate-100
          bg-white
          shadow-sm
        ">
          <img
            src={
              selectedTeam?.logo ||
              selectedTeam?.crest ||
              PLACEHOLDER
            }
            alt=""
            className="
              h-8
              w-8
              object-contain
            "
            onError={(event) => {
              event.currentTarget.src =
                PLACEHOLDER;
            }}
          />
        </div>

        <div className="
          min-w-0
          flex-1
        ">
          <p className="
            text-[10px]
            font-bold
            uppercase
            tracking-wide
            text-blue-500
          ">
            Selected {label}
          </p>

          <p className="
            truncate
            text-sm
            font-black
            text-slate-800
          ">
            {selectedTeam?.name ||
              "Choose a team"}
          </p>
        </div>

        {selectedTeam && (
          <span className="
            flex
            h-6
            w-6
            flex-shrink-0
            items-center
            justify-center
            rounded-full
            bg-emerald-100
            text-xs
            font-black
            text-emerald-600
          ">
            ✓
          </span>
        )}
      </div>

      {/* SEARCH */}

      <div className="relative">
        <input
          type="text"
          value={search}
          onFocus={() =>
            setIsOpen(true)
          }
          onChange={(event) => {
            setSearch(event.target.value);
            setIsOpen(true);
          }}
          placeholder={`Search ${label.toLowerCase()}...`}
          className="
            w-full
            rounded-xl
            border
            border-slate-200
            bg-white
            px-3
            py-3
            pr-10
            text-sm
            text-slate-700
            shadow-sm
            outline-none
            transition
            placeholder:text-slate-400
            focus:border-blue-500
            focus:ring-2
            focus:ring-blue-500/20
          "
        />

        <span className="
          pointer-events-none
          absolute
          right-3
          top-1/2
          -translate-y-1/2
          text-slate-400
        ">
          🔍
        </span>
      </div>

      {/* DROPDOWN */}

      {isOpen && (
        <>
          <div
            className="
              fixed
              inset-0
              z-10
            "
            onClick={() =>
              setIsOpen(false)
            }
          />

          <div className="
            absolute
            left-0
            right-0
            z-20
            mt-2
            max-h-64
            overflow-y-auto
            rounded-xl
            border
            border-slate-200
            bg-white
            p-1
            shadow-xl
          ">
            {visibleOptions.length > 0 ? (
              visibleOptions.map((item) => {
                const isSelected =
                  String(item.id) ===
                  String(value);

                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() =>
                      handleSelect(item.id)
                    }
                    className={`
                      flex
                      w-full
                      items-center
                      gap-3
                      rounded-lg
                      px-3
                      py-2.5
                      text-left
                      transition
                      ${
                        isSelected
                          ? "bg-blue-50 text-blue-700"
                          : "text-slate-700 hover:bg-slate-50"
                      }
                    `}
                  >
                    <div className="
                      flex
                      h-9
                      w-9
                      flex-shrink-0
                      items-center
                      justify-center
                      rounded-full
                      bg-slate-50
                    ">
                      <img
                        src={
                          item.logo ||
                          item.crest ||
                          PLACEHOLDER
                        }
                        alt=""
                        className="
                          h-7
                          w-7
                          object-contain
                        "
                        onError={(event) => {
                          event.currentTarget.src =
                            PLACEHOLDER;
                        }}
                      />
                    </div>

                    <span className="
                      min-w-0
                      flex-1
                      truncate
                      text-sm
                      font-semibold
                    ">
                      {item.name}
                    </span>

                    {isSelected && (
                      <span className="
                        flex
                        h-6
                        w-6
                        flex-shrink-0
                        items-center
                        justify-center
                        rounded-full
                        bg-blue-100
                        text-xs
                        font-black
                        text-blue-600
                      ">
                        ✓
                      </span>
                    )}
                  </button>
                );
              })
            ) : (
              <div className="
                px-3
                py-7
                text-center
                text-sm
                text-slate-400
              ">
                <div className="text-2xl">
                  🔎
                </div>

                <p className="mt-2 font-medium">
                  No teams found
                </p>

                <p className="
                  mt-0.5
                  text-xs
                ">
                  Try another team name.
                </p>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/* =========================================================
   TEAM BANNER
========================================================= */

function TeamBanner({
  team,
  align = "left",
}) {
  const isRight = align === "right";

  return (
    <div
      className={
        isRight
          ? "text-right"
          : "text-left"
      }
    >
      <div
        className={`
          mb-2
          flex
          items-center
          gap-3
          ${
            isRight
              ? "justify-end"
              : "justify-start"
          }
        `}
      >
        <img
          src={
            team?.logo ||
            team?.crest ||
            PLACEHOLDER
          }
          alt=""
          className="
            h-10
            w-10
            object-contain
            sm:h-12
            sm:w-12
          "
          onError={(event) => {
            event.currentTarget.src =
              PLACEHOLDER;
          }}
        />

        <div>
          <p className="
            text-[10px]
            font-semibold
            uppercase
            tracking-widest
            text-slate-400
          ">
            {isRight ? "Team 2" : "Team 1"}
          </p>

          <h2 className="
            mt-0.5
            text-sm
            font-black
            text-white
            sm:text-lg
          ">
            {team?.name || "Select team"}
          </h2>
        </div>
      </div>
    </div>
  );
}

/* =========================================================
   SUMMARY CARD
========================================================= */

function SummaryCard({
  label,
  value,
  subtitle,
  accent = "blue",
}) {
  const accents = {
    blue: "text-blue-600",
    emerald: "text-emerald-600",
    rose: "text-rose-600",
    amber: "text-amber-600",
    violet: "text-violet-600",
  };

  return (
    <div className="
      rounded-2xl
      border
      border-slate-200
      bg-white
      p-4
      shadow-sm
    ">
      <p className="
        text-[10px]
        font-bold
        uppercase
        tracking-wide
        text-slate-400
      ">
        {label}
      </p>

      <p
        className={`
          mt-1
          text-xl
          font-black
          ${accents[accent] || accents.blue}
        `}
      >
        {value}
      </p>

      {subtitle && (
        <p className="
          mt-0.5
          text-[10px]
          text-slate-400
        ">
          {subtitle}
        </p>
      )}
    </div>
  );
}

/* =========================================================
   DISTRIBUTION BAR
========================================================= */

function DistributionBar({
  label,
  value,
  color,
}) {
  return (
    <div>
      <div className="
        mb-1.5
        flex
        items-center
        justify-between
      ">
        <span className="
          text-sm
          font-semibold
          text-slate-700
        ">
          {label}
        </span>

        <span className="
          text-sm
          font-bold
          text-slate-900
        ">
          {safeNumber(value).toFixed(1)}%
        </span>
      </div>

      <div className="
        h-2.5
        overflow-hidden
        rounded-full
        bg-slate-100
      ">
        <div
          className={`
            h-full
            rounded-full
            transition-all
            duration-500
            ${color}
          `}
          style={{
            width: `${Math.max(
              0,
              Math.min(100, value)
            )}%`,
          }}
        />
      </div>
    </div>
  );
}

/* =========================================================
   FILTER TOGGLE
========================================================= */

function FilterToggle({
  active,
  onClick,
  children,
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`
        rounded-full
        border
        px-3
        py-1.5
        text-xs
        font-semibold
        transition
        ${
          active
            ? "border-blue-200 bg-blue-50 text-blue-700"
            : "border-slate-200 bg-white text-slate-500 hover:border-slate-300"
        }
      `}
    >
      {children}
    </button>
  );
}

/* =========================================================
   MATCH CARD
========================================================= */

function MatchCard({
  match,
  selectedHomeId,
}) {
  const result = getResultType(match);

  const selectedTeamResult =
    getTeamResult(
      match,
      selectedHomeId
    );

  const homeScore =
    safeNumber(match.home_score);

  const awayScore =
    safeNumber(match.away_score);

  const totalGoals =
    homeScore + awayScore;

  return (
    <article className="
      overflow-hidden
      rounded-2xl
      border
      border-slate-200
      bg-white
      shadow-sm
      transition
      hover:-translate-y-0.5
      hover:border-slate-300
      hover:shadow-md
    ">
      {/* DATE */}

      <div className="
        flex
        items-center
        justify-between
        border-b
        border-slate-100
        bg-slate-50
        px-4
        py-2.5
      ">
        <span className="
          text-xs
          font-semibold
          text-slate-500
        ">
          {formatDate(match)}
        </span>

        <div className="
          flex
          items-center
          gap-2
        ">
          {totalGoals >= 3 && (
            <span className="
              rounded-full
              bg-orange-50
              px-2
              py-0.5
              text-[10px]
              font-bold
              text-orange-600
            ">
              🔥 3+ Goals
            </span>
          )}

          {homeScore > 0 &&
            awayScore > 0 && (
              <span className="
                rounded-full
                bg-violet-50
                px-2
                py-0.5
                text-[10px]
                font-bold
                text-violet-600
              ">
                BTTS
              </span>
            )}
        </div>
      </div>

      {/* MATCH */}

      <div className="
        grid
        grid-cols-[1fr_auto_1fr]
        items-center
        gap-3
        p-4
        sm:p-5
      ">
        {/* HOME */}

        <div className="min-w-0">
          <div className="
            flex
            items-center
            gap-2
          ">
            <img
              src={
                match.home_logo ||
                PLACEHOLDER
              }
              alt=""
              className="
                h-8
                w-8
                flex-shrink-0
                object-contain
                sm:h-10
                sm:w-10
              "
              onError={(event) => {
                event.currentTarget.src =
                  PLACEHOLDER;
              }}
              loading="lazy"
            />

            <span className="
              truncate
              text-sm
              font-bold
              text-slate-800
              sm:text-base
            ">
              {match.home_team_name ||
                "Home"}
            </span>
          </div>
        </div>

        {/* SCORE */}

        <div className="
          flex
          min-w-[90px]
          flex-col
          items-center
        ">
          <div className="
            text-2xl
            font-black
            tracking-tight
            text-slate-900
            sm:text-3xl
          ">
            {homeScore}

            <span className="
              mx-1
              text-slate-300
            ">
              -
            </span>

            {awayScore}
          </div>

          <span
            className={`
              mt-1
              rounded-full
              px-2.5
              py-1
              text-[10px]
              font-bold
              ${getBadgeClasses(
                selectedTeamResult
              )}
            `}
          >
            {selectedTeamResult
              ? `Your team: ${getResultLabel(
                  selectedTeamResult
                )}`
              : result}
          </span>
        </div>

        {/* AWAY */}

        <div className="
          min-w-0
          text-right
        ">
          <div className="
            flex
            items-center
            justify-end
            gap-2
          ">
            <span className="
              truncate
              text-sm
              font-bold
              text-slate-800
              sm:text-base
            ">
              {match.away_team_name ||
                "Away"}
            </span>

            <img
              src={
                match.away_logo ||
                PLACEHOLDER
              }
              alt=""
              className="
                h-8
                w-8
                flex-shrink-0
                object-contain
                sm:h-10
                sm:w-10
              "
              onError={(event) => {
                event.currentTarget.src =
                  PLACEHOLDER;
              }}
              loading="lazy"
            />
          </div>
        </div>
      </div>

      {/* FOOTER */}

      <div className="
        flex
        items-center
        justify-between
        border-t
        border-slate-100
        px-4
        py-2.5
      ">
        <span className="
          text-[11px]
          text-slate-400
        ">
          {totalGoals} total goals
        </span>

        <span className="
          text-[11px]
          font-semibold
          text-slate-500
        ">
          {result}
        </span>
      </div>
    </article>
  );
}

/* =========================================================
   MINI STAT
========================================================= */

function MiniStat({
  label,
  value,
}) {
  return (
    <div className="text-center">
      <p className="
        text-[10px]
        font-bold
        uppercase
        tracking-wide
        text-slate-400
      ">
        {label}
      </p>

      <p className="
        mt-1
        text-xl
        font-black
        text-slate-900
      ">
        {value}
      </p>
    </div>
  );
}
