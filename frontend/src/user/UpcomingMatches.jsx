import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/api";

export default function UpcomingMatches() {
  const navigate = useNavigate();

  const [fixtures, setFixtures] = useState([]);
  const [standings, setStandings] = useState([]);
  const [selectedDate, setSelectedDate] = useState(
    new Date().toLocaleDateString("en-CA")
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());

  const [expandedStandings, setExpandedStandings] = useState({});

  const competitionNameMap = {
    "Primera Division": "LaLiga",
    "Premier League": "Premier League",
    "Serie A": "Serie A",
    Bundesliga: "Bundesliga",
    "Ligue 1": "Ligue 1",
    "UEFA Champions League": "Champions League",
  };

  const getDateObj = useCallback((match) => {
    if (!match) return null;

    if (
      match.timestamp !== undefined &&
      match.timestamp !== null
    ) {
      const timestamp = Number(match.timestamp);

      if (!Number.isNaN(timestamp)) {
        return new Date(timestamp * 1000);
      }
    }

    const dateValue =
      match.localDate ||
      match.utcDate ||
      match.utcdate ||
      match.date ||
      null;

    if (!dateValue) return null;

    const parsedDate = new Date(dateValue);

    if (Number.isNaN(parsedDate.getTime())) {
      return null;
    }

    return parsedDate;
  }, []);

  const formatLocalDate = useCallback((date) => {
    if (!date || Number.isNaN(date.getTime())) {
      return null;
    }

    return date.toLocaleDateString("en-CA");
  }, []);

  const loadFixtures = useCallback(async () => {
    try {
      setLoading(true);
      setError("");

      const response = await api.getUpcomingMatches();

      if (response?.success) {
        const matches = Array.isArray(
          response.data?.matches
        )
          ? response.data.matches
          : [];

        const tables = Array.isArray(
          response.data?.standings
        )
          ? response.data.standings
          : [];

        setFixtures(matches);
        setStandings(tables);
      } else {
        setFixtures([]);
        setStandings([]);

        setError(
          response?.message ||
            "Failed to load upcoming matches."
        );
      }
    } catch (err) {
      console.error(
        "Failed to load fixtures:",
        err
      );

      setFixtures([]);
      setStandings([]);

      setError(
        "Failed to load upcoming matches."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadFixtures();

    const refreshTimer = setInterval(() => {
      loadFixtures();
    }, 60000);

    return () => clearInterval(refreshTimer);
  }, [loadFixtures]);

  useEffect(() => {
    const clockTimer = setInterval(() => {
      setNow(Date.now());
    }, 10000);

    return () => clearInterval(clockTimer);
  }, []);

  const getMatchStatus = useCallback(
    (match) => {
      const matchDate = getDateObj(match);

      if (!matchDate) {
        return {
          label: "TBC",
          type: "unknown",
          color: "text-gray-400",
        };
      }

      const diff =
        matchDate.getTime() - now;

      if (diff <= 0) {
        return {
          label: "LIVE",
          type: "live",
          color: "text-red-600",
        };
      }

      const totalMinutes = Math.floor(
        diff / 60000
      );

      if (totalMinutes <= 15) {
        return {
          label: "Starting Soon",
          type: "soon",
          color: "text-orange-600",
        };
      }

      const hours = Math.floor(
        totalMinutes / 60
      );

      const minutes =
        totalMinutes % 60;

      let label = "";

      if (hours > 0) {
        label = `KO in ${hours}h ${minutes}m`;
      } else {
        label = `KO in ${minutes}m`;
      }

      return {
        label,
        type: "upcoming",
        color: "text-blue-600",
      };
    },
    [getDateObj, now]
  );

  const filteredFixtures = useMemo(() => {
    return fixtures.filter((match) => {
      const matchDate = getDateObj(match);

      if (!matchDate) return false;

      return (
        formatLocalDate(matchDate) ===
        selectedDate
      );
    });
  }, [
    fixtures,
    selectedDate,
    getDateObj,
    formatLocalDate,
  ]);

  const groupedFixtures = useMemo(() => {
    const groups = {};

    filteredFixtures.forEach((match) => {
      const competition =
        match?.competition || "Other";

      if (!groups[competition]) {
        groups[competition] = [];
      }

      groups[competition].push(match);
    });

    Object.keys(groups).forEach(
      (competition) => {
        groups[competition].sort(
          (a, b) => {
            const dateA =
              getDateObj(a);

            const dateB =
              getDateObj(b);

            const timeA = dateA
              ? dateA.getTime()
              : 0;

            const timeB = dateB
              ? dateB.getTime()
              : 0;

            return timeA - timeB;
          }
        );
      }
    );

    return groups;
  }, [
    filteredFixtures,
    getDateObj,
  ]);

  const getCompetitionStandings =
    useCallback(
      (competition, season) => {
        return standings.find(
          (item) =>
            item?.competition ===
              competition &&
            Number(item?.season) ===
              Number(season)
        );
      },
      [standings]
    );

  const toggleStandings = useCallback(
    (key) => {
      setExpandedStandings(
        (previous) => ({
          ...previous,
          [key]: !previous[key],
        })
      );
    },
    []
  );

  const openMatch = useCallback(
    (match) => {
      if (!match?.id) return;

      navigate(
        `/matches/${match.id}/overview`
      );
    },
    [navigate]
  );

  const openLineups = useCallback(
    (event, match) => {
      event.stopPropagation();

      const homeTeam =
        match?.home_team_name ||
        "Home Team";

      const awayTeam =
        match?.away_team_name ||
        "Away Team";

      const matchDate =
        getDateObj(match);

      const dateText = matchDate
        ? matchDate.toLocaleDateString(
            "en-GB",
            {
              day: "numeric",
              month: "long",
              year: "numeric",
            }
          )
        : "";

      const competition =
        match?.competition || "";

      const query = [
        `${homeTeam} vs ${awayTeam}`,
        dateText,
        competition,
        "lineups starting XI team news",
      ]
        .filter(Boolean)
        .join(" ");

      const browserUrl =
        `https://www.google.com/search?q=${encodeURIComponent(
          query
        )}`;

      window.location.href =
        browserUrl;
    },
    [getDateObj]
  );

  const handleRefresh =
    useCallback(() => {
      loadFixtures();
    }, [loadFixtures]);

  const renderStandingRow = useCallback(
    (
      team,
      homeTeamId,
      awayTeamId
    ) => {
      const isHome =
        homeTeamId !== null &&
        homeTeamId !== undefined &&
        Number(team?.team_id) ===
          Number(homeTeamId);

      const isAway =
        awayTeamId !== null &&
        awayTeamId !== undefined &&
        Number(team?.team_id) ===
          Number(awayTeamId);

      const isHighlighted =
        isHome || isAway;

      return (
        <div
          key={`${team?.team_id}-${team?.rank}`}
          className={`grid grid-cols-[32px_minmax(0,1fr)_42px_70px_42px] items-center gap-2 border-b px-3 py-2.5 text-xs last:border-b-0 sm:grid-cols-[40px_minmax(0,1fr)_55px_90px_55px_65px] sm:px-4 ${
            isHighlighted
              ? "bg-blue-50"
              : "bg-white"
          }`}
        >
          <div className="text-center">
            <span
              className={`inline-flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-extrabold ${
                team?.rank <= 4
                  ? "bg-green-100 text-green-700"
                  : team?.rank >= 18
                  ? "bg-red-100 text-red-700"
                  : "bg-gray-100 text-gray-600"
              }`}
            >
              {team?.rank ?? "-"}
            </span>
          </div>

          <div className="flex min-w-0 items-center gap-2">
            {team?.team_crest ? (
              <img
                src={team.team_crest}
                alt=""
                className="h-7 w-7 flex-shrink-0 object-contain"
                onError={(event) => {
                  event.currentTarget.style.display =
                    "none";
                }}
              />
            ) : (
              <div className="h-7 w-7 flex-shrink-0 rounded-full bg-gray-100" />
            )}

            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span
                  className={`truncate font-bold ${
                    isHighlighted
                      ? "text-blue-700"
                      : "text-gray-800"
                  }`}
                >
                  {team?.team_short_name ||
                    team?.team_name ||
                    "Unknown"}
                </span>

                {isHome && (
                  <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[9px] font-extrabold text-blue-700">
                    H
                  </span>
                )}

                {isAway && (
                  <span className="rounded bg-purple-100 px-1.5 py-0.5 text-[9px] font-extrabold text-purple-700">
                    A
                  </span>
                )}
              </div>

              <span className="hidden text-[10px] text-gray-400 sm:block">
                {team?.team_tla ||
                  team?.team_name ||
                  ""}
              </span>
            </div>
          </div>

          <div className="text-center">
            <span className="font-semibold text-gray-700">
              {team?.played ?? 0}
            </span>
          </div>

          <div className="hidden justify-center gap-1 sm:flex">
            <span className="font-bold text-green-600">
              {team?.win ?? 0}
            </span>

            <span className="text-gray-300">
              /
            </span>

            <span className="font-bold text-gray-500">
              {team?.draw ?? 0}
            </span>

            <span className="text-gray-300">
              /
            </span>

            <span className="font-bold text-red-600">
              {team?.lose ?? 0}
            </span>
          </div>

          <div className="hidden text-center sm:block">
            <span
              className={`font-bold ${
                Number(team?.goal_diff) > 0
                  ? "text-green-600"
                  : Number(team?.goal_diff) < 0
                  ? "text-red-600"
                  : "text-gray-500"
              }`}
            >
              {Number(team?.goal_diff) > 0
                ? `+${team.goal_diff}`
                : team?.goal_diff ?? 0}
            </span>
          </div>

          <div className="text-right">
            <span className="text-sm font-extrabold text-gray-900">
              {team?.points ?? 0}
            </span>

            <span className="ml-1 text-[9px] text-gray-400">
              pts
            </span>
          </div>
        </div>
      );
    },
    []
  );

  return (
    <div className="min-h-screen bg-gray-50 px-4 pb-8 pt-20 sm:px-6 lg:px-8">
      <div className="mx-auto w-full max-w-7xl">
        {/* HEADER */}
        <div className="mb-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <div className="h-8 w-1.5 rounded-full bg-blue-600" />

                <h1 className="text-2xl font-extrabold tracking-tight text-gray-900 sm:text-3xl">
                  Upcoming Matches
                </h1>
              </div>

              <p className="mt-2 text-sm text-gray-500">
                Fixtures, kickoff times and current league standings
              </p>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <input
                type="date"
                value={selectedDate}
                onChange={(event) => {
                  setSelectedDate(
                    event.target.value
                  );
                }}
                className="rounded-xl border border-gray-300 bg-white px-3 py-2.5 text-sm font-medium text-gray-700 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500"
              />

              <button
                type="button"
                onClick={handleRefresh}
                disabled={loading}
                className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-blue-700 active:scale-95 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading
                  ? "Loading..."
                  : "Refresh"}
              </button>
            </div>
          </div>
        </div>

        {/* ERROR */}
        {error && (
          <div className="mb-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-600">
            {error}
          </div>
        )}

        {/* LOADING */}
        {loading &&
          fixtures.length === 0 && (
            <div className="flex justify-center py-16">
              <div className="h-10 w-10 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600" />
            </div>
          )}

        {/* EMPTY STATE */}
        {!loading &&
          !error &&
          filteredFixtures.length === 0 && (
            <div className="rounded-2xl border border-gray-200 bg-white p-10 text-center shadow-sm">
              <div className="mb-3 text-4xl">
                ⚽
              </div>

              <p className="font-bold text-gray-700">
                No fixtures for this date
              </p>

              <p className="mt-1 text-sm text-gray-400">
                Try selecting another date.
              </p>
            </div>
          )}

        {/* COMPETITIONS */}
        {Object.entries(groupedFixtures).map(
          ([competition, matches]) => {
            const displayCompetition =
              competitionNameMap[
                competition
              ] || competition;

            const firstMatch =
              matches[0];

            const competitionTable =
              getCompetitionStandings(
                competition,
                firstMatch?.season
              );

            const standingsKey =
              `${competition}-${firstMatch?.season}`;

            const isStandingsOpen =
              Boolean(
                expandedStandings[
                  standingsKey
                ]
              );

            return (
              <section
                key={competition}
                className="mb-9"
              >
                {/* COMPETITION HEADER */}
                <div className="mb-3 flex items-center justify-between px-1">
                  <div className="flex items-center gap-2">
                    <div className="h-7 w-1 rounded-full bg-blue-600" />

                    <div>
                      <h2 className="text-base font-extrabold text-gray-900 sm:text-lg">
                        {displayCompetition}
                      </h2>

                      {firstMatch?.season && (
                        <span className="text-[10px] font-medium text-gray-400">
                          Season{" "}
                          {firstMatch.season}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-400 sm:text-sm">
                      {matches.length}{" "}
                      {matches.length === 1
                        ? "match"
                        : "matches"}
                    </span>
                  </div>
                </div>

                {/* MATCH LIST */}
                <div className="space-y-3">
                  {matches.map((match) => {
                    const matchDate =
                      getDateObj(match);

                    const status =
                      getMatchStatus(match);

                    const difference =
                      matchDate
                        ? matchDate.getTime() -
                          now
                        : null;

                    const isSoon =
                      difference !== null &&
                      difference > 0 &&
                      difference <=
                        15 * 60 * 1000;

                    const homeStanding =
                      match.home_standing;

                    const awayStanding =
                      match.away_standing;

                    return (
                      <div
                        key={match.id}
                        className={`group w-full overflow-hidden rounded-2xl border shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg ${
                          isSoon
                            ? "border-orange-300 bg-orange-50"
                            : "border-gray-200 bg-white"
                        }`}
                      >
                        <div className="p-4 sm:p-5">
                          {/* TOP ROW */}
                          <div className="mb-4 flex items-center justify-between">
                            <span className="rounded-full bg-gray-100 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-gray-500">
                              {displayCompetition}
                            </span>

                            {match.matchday !==
                              undefined &&
                              match.matchday !==
                                null && (
                                <span className="text-xs font-semibold text-gray-400">
                                  MD{" "}
                                  {match.matchday}
                                </span>
                              )}
                          </div>

                          {/* MATCH */}
                          <button
                            type="button"
                            onClick={() =>
                              openMatch(match)
                            }
                            className="w-full text-left"
                          >
                            <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
                              {/* HOME */}
                              <div className="min-w-0">
                                <div className="flex items-center gap-2 sm:gap-3">
                                  <img
                                    src={
                                      match.home_logo ||
                                      homeStanding?.team_crest ||
                                      "/logo-placeholder.png"
                                    }
                                    alt={
                                      match.home_team_name ||
                                      "Home team"
                                    }
                                    className="h-10 w-10 flex-shrink-0 object-contain sm:h-12 sm:w-12"
                                    onError={(
                                      event
                                    ) => {
                                      event.currentTarget.src =
                                        "/logo-placeholder.png";
                                    }}
                                  />

                                  <div className="min-w-0">
                                    <span className="block truncate text-sm font-extrabold text-gray-800 sm:text-base">
                                      {match.home_team_name ||
                                        "Home Team"}
                                    </span>
                                  </div>
                                </div>
                              </div>

                              {/* KICKOFF */}
                              <div className="flex min-w-[90px] flex-col items-center">
                                <span className="text-xl font-black tracking-tight text-gray-900 sm:text-2xl">
                                  {matchDate
                                    ? matchDate.toLocaleTimeString(
                                        [],
                                        {
                                          hour: "2-digit",
                                          minute: "2-digit",
                                        }
                                      )
                                    : "--:--"}
                                </span>

                                <span
                                  className={`mt-1 rounded-full px-2 py-0.5 text-[10px] font-extrabold sm:text-xs ${
                                    status.type ===
                                    "live"
                                      ? "bg-red-100 text-red-600"
                                      : status.type ===
                                        "soon"
                                      ? "bg-orange-100 text-orange-600"
                                      : "bg-blue-50 text-blue-600"
                                  }`}
                                >
                                  {status.label}
                                </span>

                                <span className="mt-1 text-[9px] font-semibold tracking-wider text-gray-300">
                                  KICKOFF
                                </span>
                              </div>

                              {/* AWAY */}
                              <div className="min-w-0">
                                <div className="flex items-center justify-end gap-2 sm:gap-3">
                                  <div className="min-w-0 text-right">
                                    <span className="block truncate text-sm font-extrabold text-gray-800 sm:text-base">
                                      {match.away_team_name ||
                                        "Away Team"}
                                    </span>
                                  </div>

                                  <img
                                    src={
                                      match.away_logo ||
                                      awayStanding?.team_crest ||
                                      "/logo-placeholder.png"
                                    }
                                    alt={
                                      match.away_team_name ||
                                      "Away team"
                                    }
                                    className="h-10 w-10 flex-shrink-0 object-contain sm:h-12 sm:w-12"
                                    onError={(
                                      event
                                    ) => {
                                      event.currentTarget.src =
                                        "/logo-placeholder.png";
                                    }}
                                  />
                                </div>
                              </div>
                            </div>
                          </button>

                          {/* STANDING SNAPSHOT */}
                          {(homeStanding ||
                            awayStanding) && (
                            <div className="mt-4 grid grid-cols-2 gap-2">
                              {/* HOME SNAPSHOT */}
                              <div className="rounded-xl border border-blue-100 bg-blue-50/70 px-3 py-2">
                                <div className="flex items-center justify-between">
                                  <span className="text-[9px] font-bold uppercase tracking-wide text-blue-500">
                                    Home
                                  </span>

                                  <span className="text-xs font-black text-blue-700">
                                    #{homeStanding?.rank ??
                                      "-"}
                                  </span>
                                </div>

                                <div className="mt-1 flex items-end justify-between">
                                  <span className="truncate text-xs font-bold text-gray-700">
                                    {homeStanding?.team_short_name ||
                                      match.home_team_name ||
                                      "Home"}
                                  </span>

                                  <span className="ml-2 whitespace-nowrap text-sm font-black text-blue-700">
                                    {homeStanding?.points ??
                                      0}{" "}
                                    <span className="text-[9px] font-semibold">
                                      pts
                                    </span>
                                  </span>
                                </div>

                                <div className="mt-1 text-[9px] text-gray-500">
                                  {homeStanding?.played ??
                                    0}{" "}
                                  played •{" "}
                                  {homeStanding?.win ??
                                    0}
                                  W{" "}
                                  {homeStanding?.draw ??
                                    0}
                                  D{" "}
                                  {homeStanding?.lose ??
                                    0}
                                  L
                                </div>
                              </div>

                              {/* AWAY SNAPSHOT */}
                              <div className="rounded-xl border border-purple-100 bg-purple-50/70 px-3 py-2">
                                <div className="flex items-center justify-between">
                                  <span className="text-[9px] font-bold uppercase tracking-wide text-purple-500">
                                    Away
                                  </span>

                                  <span className="text-xs font-black text-purple-700">
                                    #{awayStanding?.rank ??
                                      "-"}
                                  </span>
                                </div>

                                <div className="mt-1 flex items-end justify-between">
                                  <span className="truncate text-xs font-bold text-gray-700">
                                    {awayStanding?.team_short_name ||
                                      match.away_team_name ||
                                      "Away"}
                                  </span>

                                  <span className="ml-2 whitespace-nowrap text-sm font-black text-purple-700">
                                    {awayStanding?.points ??
                                      0}{" "}
                                    <span className="text-[9px] font-semibold">
                                      pts
                                    </span>
                                  </span>
                                </div>

                                <div className="mt-1 text-[9px] text-gray-500">
                                  {awayStanding?.played ??
                                    0}{" "}
                                  played •{" "}
                                  {awayStanding?.win ??
                                    0}
                                  W{" "}
                                  {awayStanding?.draw ??
                                    0}
                                  D{" "}
                                  {awayStanding?.lose ??
                                    0}
                                  L
                                </div>
                              </div>
                            </div>
                          )}

                          {/* FOOTER ACTIONS */}
                          <div className="mt-5 flex flex-col gap-2 border-t border-gray-100 pt-3 sm:flex-row sm:items-center sm:justify-between">
                            <span className="hidden text-xs font-medium text-gray-400 sm:block">
                              Select an option
                            </span>

                            <div className="flex w-full gap-2 sm:w-auto">
                              <button
                                type="button"
                                onClick={(event) =>
                                  openLineups(
                                    event,
                                    match
                                  )
                                }
                                className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-purple-200 bg-purple-50 px-3 py-2.5 text-xs font-bold text-purple-700 transition hover:border-purple-300 hover:bg-purple-100 active:scale-95 sm:flex-none sm:text-sm"
                              >
                                <span>👥</span>

                                <span>
                                  View Lineups
                                </span>
                              </button>

                              <button
                                type="button"
                                onClick={() =>
                                  openMatch(match)
                                }
                                className="flex flex-1 items-center justify-center rounded-xl bg-blue-600 px-3 py-2.5 text-xs font-bold text-white shadow-sm transition hover:bg-blue-700 active:scale-95 sm:flex-none sm:text-sm"
                              >
                                View Match →
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* FULL STANDINGS */}
                {competitionTable &&
                  Array.isArray(
                    competitionTable.table
                  ) &&
                  competitionTable.table.length >
                    0 && (
                    <div className="mt-4 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
                      <button
                        type="button"
                        onClick={() =>
                          toggleStandings(
                            standingsKey
                          )
                        }
                        className="flex w-full items-center justify-between px-4 py-3.5 text-left transition hover:bg-gray-50 sm:px-5"
                      >
                        <div className="flex items-center gap-3">
                          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-50 text-lg">
                            📊
                          </div>

                          <div>
                            <div className="text-sm font-extrabold text-gray-900">
                              League Standings
                            </div>

                            <div className="text-[10px] font-medium text-gray-400">
                              {competitionTable.count ||
                                competitionTable
                                  .table.length}{" "}
                              teams • Season{" "}
                              {competitionTable.season}
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-2">
                          <span className="hidden rounded-full bg-gray-100 px-2.5 py-1 text-[10px] font-bold text-gray-500 sm:block">
                            Full Table
                          </span>

                          <span
                            className={`text-lg text-gray-400 transition-transform ${
                              isStandingsOpen
                                ? "rotate-180"
                                : ""
                            }`}
                          >
                            ⌄
                          </span>
                        </div>
                      </button>

                      {isStandingsOpen && (
                        <div className="border-t border-gray-100">
                          <div className="grid grid-cols-[32px_minmax(0,1fr)_42px_70px_42px] gap-2 bg-gray-50 px-3 py-2 text-[9px] font-extrabold uppercase tracking-wide text-gray-400 sm:grid-cols-[40px_minmax(0,1fr)_55px_90px_55px_65px] sm:px-4">
                            <div className="text-center">
                              #
                            </div>

                            <div>Team</div>

                            <div className="text-center">
                              P
                            </div>

                            <div className="hidden text-center sm:block">
                              W / D / L
                            </div>

                            <div className="hidden text-center sm:block">
                              GD
                            </div>

                            <div className="text-right">
                              PTS
                            </div>
                          </div>

                          <div>
                            {competitionTable.table.map(
                              (team) =>
                                renderStandingRow(
                                  team,
                                  null,
                                  null
                                )
                            )}
                          </div>

                          <div className="border-t border-gray-100 bg-gray-50 px-4 py-3">
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[9px] font-medium text-gray-400">
                              <span>
                                P = Played
                              </span>

                              <span>
                                GD = Goal Difference
                              </span>

                              <span>
                                PTS = Points
                              </span>

                              <span className="flex items-center gap-1">
                                <span className="font-bold text-green-600">
                                  W
                                </span>
                                Wins
                              </span>

                              <span className="flex items-center gap-1">
                                <span className="font-bold text-gray-500">
                                  D
                                </span>
                                Draws
                              </span>

                              <span className="flex items-center gap-1">
                                <span className="font-bold text-red-600">
                                  L
                                </span>
                                Losses
                              </span>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
              </section>
            );
          }
        )}
      </div>
    </div>
  );
}
