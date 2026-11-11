// src/pages/Teams.jsx

import React, { useEffect, useMemo, useState } from "react";
import { Search, Filter, Users, X, ChevronDown } from "lucide-react";
import { getTeams } from "../api/api";
import Loader from "../components/Loader";
import PlayersModal from "../components/PlayersModal";

const PLACEHOLDER = "/logos/placeholder.png";

export default function Teams() {
  const [teams, setTeams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [competitionFilter, setCompetitionFilter] = useState("All");
  const [competitions, setCompetitions] = useState(["All"]);
  const [selectedTeam, setSelectedTeam] = useState(null);

  // =========================================================
  // PREVENT BACKGROUND SCROLL WHEN MODAL IS OPEN
  // =========================================================

  useEffect(() => {
    if (selectedTeam) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }

    return () => {
      document.body.style.overflow = "";
    };
  }, [selectedTeam]);

  // =========================================================
  // FETCH TEAMS
  // =========================================================

  useEffect(() => {
    let mounted = true;

    const fetchTeams = async () => {
      setLoading(true);

      try {
        const res = await getTeams();

        if (
          mounted &&
          res?.success &&
          Array.isArray(res?.data?.teams)
        ) {
          const fetchedTeams = res.data.teams;

          setTeams(fetchedTeams);

          const compsSet = new Set();

          fetchedTeams.forEach((team) => {
            (team.competitions || []).forEach((competition) => {
              if (competition) {
                compsSet.add(competition);
              }
            });
          });

          setCompetitions([
            "All",
            ...Array.from(compsSet).sort(),
          ]);
        }
      } catch (err) {
        console.error("Error fetching teams:", err);

        if (mounted) {
          setTeams([]);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    fetchTeams();

    return () => {
      mounted = false;
    };
  }, []);

  // =========================================================
  // FILTER TEAMS
  // =========================================================

  const filteredTeams = useMemo(() => {
    const query = search.trim().toLowerCase();

    return teams.filter((team) => {
      const name = String(team?.name || "").toLowerCase();

      const matchName =
        !query || name.includes(query);

      const matchCompetition =
        competitionFilter === "All" ||
        (team?.competitions || []).includes(
          competitionFilter
        );

      return matchName && matchCompetition;
    });
  }, [teams, search, competitionFilter]);

  // =========================================================
  // CLEAR FILTERS
  // =========================================================

  const clearFilters = () => {
    setSearch("");
    setCompetitionFilter("All");
  };

  const hasFilters =
    search.trim() !== "" ||
    competitionFilter !== "All";

  // =========================================================
  // LOADING
  // =========================================================

  if (loading) {
    return <Loader text="Loading teams..." />;
  }

  // =========================================================
  // PAGE
  // =========================================================

  return (
    <div className="min-h-screen bg-slate-50">
      {/* =====================================================
          HEADER
      ====================================================== */}

      <div className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="mb-2 flex items-center gap-2">
                <div className="h-1 w-8 rounded-full bg-blue-600" />

                <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-blue-600">
                  Football
                </span>
              </div>

              <h1 className="text-2xl font-black tracking-tight text-slate-900 sm:text-3xl">
                Teams
              </h1>

              <p className="mt-1 text-sm text-slate-500">
                Explore teams, competitions and players.
              </p>
            </div>

            {/* Team count */}
            <div
              className="
                flex
                w-fit
                items-center
                gap-3
                rounded-2xl
                border
                border-slate-200
                bg-slate-50
                px-4
                py-3
              "
            >
              <div
                className="
                  flex
                  h-9
                  w-9
                  items-center
                  justify-center
                  rounded-xl
                  bg-blue-600
                  text-white
                  shadow-sm
                "
              >
                <Users size={18} />
              </div>

              <div>
                <p className="text-lg font-bold leading-none text-slate-900">
                  {filteredTeams.length}
                </p>

                <p className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  {filteredTeams.length === 1
                    ? "Team"
                    : "Teams"}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* =====================================================
          CONTENT
      ====================================================== */}

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        {/* ===================================================
            SEARCH / FILTER BAR
        ==================================================== */}

        <div
          className="
            mb-7
            rounded-2xl
            border
            border-slate-200
            bg-white
            p-3
            shadow-sm
          "
        >
          <div className="flex flex-col gap-3 md:flex-row">
            {/* Search */}
            <div className="relative flex-1">
              <Search
                size={18}
                className="
                  pointer-events-none
                  absolute
                  left-4
                  top-1/2
                  -translate-y-1/2
                  text-slate-400
                "
              />

              <input
                type="text"
                placeholder="Search teams..."
                value={search}
                onChange={(e) =>
                  setSearch(e.target.value)
                }
                className="
                  w-full
                  rounded-xl
                  border
                  border-slate-200
                  bg-slate-50
                  py-3
                  pl-11
                  pr-4
                  text-sm
                  text-slate-900
                  outline-none
                  transition
                  placeholder:text-slate-400
                  hover:border-slate-300
                  focus:border-blue-500
                  focus:bg-white
                  focus:ring-2
                  focus:ring-blue-500/10
                "
              />
            </div>

            {/* Competition */}
            <div className="relative md:w-64">
              <Filter
                size={16}
                className="
                  pointer-events-none
                  absolute
                  left-4
                  top-1/2
                  -translate-y-1/2
                  text-slate-400
                "
              />

              <select
                value={competitionFilter}
                onChange={(e) =>
                  setCompetitionFilter(e.target.value)
                }
                className="
                  w-full
                  appearance-none
                  rounded-xl
                  border
                  border-slate-200
                  bg-slate-50
                  py-3
                  pl-10
                  pr-10
                  text-sm
                  font-medium
                  text-slate-700
                  outline-none
                  transition
                  hover:border-slate-300
                  focus:border-blue-500
                  focus:bg-white
                  focus:ring-2
                  focus:ring-blue-500/10
                "
              >
                {competitions.map((competition) => (
                  <option
                    key={competition}
                    value={competition}
                  >
                    {competition}
                  </option>
                ))}
              </select>

              <ChevronDown
                size={16}
                className="
                  pointer-events-none
                  absolute
                  right-4
                  top-1/2
                  -translate-y-1/2
                  text-slate-400
                "
              />
            </div>

            {/* Clear */}
            {hasFilters && (
              <button
                type="button"
                onClick={clearFilters}
                className="
                  inline-flex
                  items-center
                  justify-center
                  gap-2
                  rounded-xl
                  border
                  border-slate-200
                  px-4
                  py-3
                  text-sm
                  font-semibold
                  text-slate-600
                  transition
                  hover:border-red-200
                  hover:bg-red-50
                  hover:text-red-600
                "
              >
                <X size={16} />
                Clear
              </button>
            )}
          </div>

          {/* Filter status */}
          <div className="mt-3 flex items-center justify-between px-1">
            <p className="text-xs text-slate-400">
              Showing{" "}
              <span className="font-semibold text-slate-600">
                {filteredTeams.length}
              </span>{" "}
              of{" "}
              <span className="font-semibold text-slate-600">
                {teams.length}
              </span>{" "}
              teams
            </p>

            {competitionFilter !== "All" && (
              <span className="hidden rounded-full bg-blue-50 px-2.5 py-1 text-[10px] font-semibold text-blue-600 sm:block">
                {competitionFilter}
              </span>
            )}
          </div>
        </div>

        {/* ===================================================
            EMPTY STATE
        ==================================================== */}

        {filteredTeams.length === 0 ? (
          <div
            className="
              flex
              min-h-[280px]
              flex-col
              items-center
              justify-center
              rounded-2xl
              border
              border-dashed
              border-slate-300
              bg-white
              px-6
              text-center
            "
          >
            <div
              className="
                mb-4
                flex
                h-14
                w-14
                items-center
                justify-center
                rounded-2xl
                bg-slate-100
                text-slate-400
              "
            >
              <Search size={23} />
            </div>

            <h2 className="text-base font-bold text-slate-800">
              No teams found
            </h2>

            <p className="mt-1 max-w-sm text-sm text-slate-400">
              Try changing your search or selecting a
              different competition.
            </p>

            {hasFilters && (
              <button
                type="button"
                onClick={clearFilters}
                className="
                  mt-5
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
                  active:scale-[0.98]
                "
              >
                Clear filters
              </button>
            )}
          </div>
        ) : (
          /* =================================================
             TEAMS GRID
          ================================================== */

          <div
            className="
              grid
              grid-cols-1
              gap-4
              sm:grid-cols-2
              lg:grid-cols-3
              xl:grid-cols-4
            "
          >
            {filteredTeams.map((team) => (
              <button
                key={team.id}
                type="button"
                onClick={() =>
                  setSelectedTeam(team)
                }
                className="
                  group
                  relative
                  flex
                  min-h-[150px]
                  w-full
                  items-center
                  gap-4
                  overflow-hidden
                  rounded-2xl
                  border
                  border-slate-200
                  bg-white
                  p-5
                  text-left
                  shadow-sm
                  transition-all
                  duration-200
                  hover:-translate-y-1
                  hover:border-blue-200
                  hover:shadow-xl
                  hover:shadow-slate-200/70
                  focus:outline-none
                  focus:ring-2
                  focus:ring-blue-500/30
                "
              >
                {/* Accent */}
                <div
                  className="
                    absolute
                    left-0
                    top-0
                    h-full
                    w-1
                    origin-left
                    scale-y-0
                    rounded-r-full
                    bg-blue-600
                    transition-transform
                    duration-200
                    group-hover:scale-y-100
                  "
                />

                {/* Crest */}
                <div
                  className="
                    flex
                    h-16
                    w-16
                    shrink-0
                    items-center
                    justify-center
                    rounded-2xl
                    border
                    border-slate-100
                    bg-slate-50
                    p-2
                    transition
                    duration-200
                    group-hover:bg-blue-50
                  "
                >
                  <img
                    src={
                      team.crest ||
                      PLACEHOLDER
                    }
                    onError={(e) => {
                      if (
                        e.currentTarget.src.includes(
                          PLACEHOLDER
                        )
                      ) {
                        return;
                      }

                      e.currentTarget.src =
                        PLACEHOLDER;
                    }}
                    alt={`${team.name || "Team"} crest`}
                    className="
                      h-full
                      w-full
                      object-contain
                      transition-transform
                      duration-200
                      group-hover:scale-110
                    "
                    loading="lazy"
                  />
                </div>

                {/* Team info */}
                <div className="min-w-0 flex-1">
                  <h3
                    className="
                      truncate
                      text-sm
                      font-bold
                      text-slate-800
                      transition
                      group-hover:text-blue-600
                    "
                  >
                    {team.name || "Unknown Team"}
                  </h3>

                  {team.venue ? (
                    <p className="mt-1 truncate text-xs text-slate-500">
                      {team.venue}
                    </p>
                  ) : (
                    <p className="mt-1 text-xs text-slate-400">
                      Venue unavailable
                    </p>
                  )}

                  {team.founded ? (
                    <p className="mt-1 text-[11px] text-slate-400">
                      Founded {team.founded}
                    </p>
                  ) : null}

                  {/* Competition tags */}
                  {Array.isArray(
                    team.competitions
                  ) &&
                    team.competitions.length > 0 && (
                      <div className="mt-3 flex items-center gap-1.5 overflow-hidden">
                        {team.competitions
                          .slice(0, 1)
                          .map((competition) => (
                            <span
                              key={competition}
                              className="
                                max-w-[130px]
                                truncate
                                rounded-full
                                bg-slate-100
                                px-2
                                py-1
                                text-[9px]
                                font-semibold
                                text-slate-500
                              "
                            >
                              {competition}
                            </span>
                          ))}

                        {team.competitions.length >
                          1 && (
                          <span
                            className="
                              rounded-full
                              bg-blue-50
                              px-2
                              py-1
                              text-[9px]
                              font-semibold
                              text-blue-500
                            "
                          >
                            +
                            {team.competitions
                              .length - 1}
                          </span>
                        )}
                      </div>
                    )}
                </div>

                {/* Arrow */}
                <div
                  className="
                    absolute
                    right-4
                    top-4
                    text-slate-300
                    transition
                    group-hover:translate-x-1
                    group-hover:text-blue-500
                  "
                >
                  →
                </div>
              </button>
            ))}
          </div>
        )}
      </main>

      {/* =====================================================
          PLAYERS MODAL
      ====================================================== */}

      {selectedTeam && (
        <PlayersModal
          team={selectedTeam}
          onClose={() =>
            setSelectedTeam(null)
          }
        />
      )}
    </div>
  );
}
