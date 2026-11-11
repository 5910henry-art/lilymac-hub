// src/user/Lineups.jsx

import { useState } from "react";

export default function Lineups() {
  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [matchDate, setMatchDate] = useState("");

  const openLineupSearch = (event) => {
    event.preventDefault();

    const home = homeTeam.trim();
    const away = awayTeam.trim();

    if (!home || !away) {
      return;
    }

    const match = `${home} vs ${away}`;

    const query = [
      `${match} lineups`,
      matchDate ? matchDate : "",
      "starting lineup team news",
    ]
      .filter(Boolean)
      .join(" ");

    const browserUrl = `https://www.google.com/search?q=${encodeURIComponent(
      query
    )}`;

    window.location.href = browserUrl;
  };

  const openPopularLineups = (website) => {
    window.location.href = website;
  };

  return (
    <div className="min-h-screen bg-gray-50 px-4 pb-24 pt-20">
      <div className="mx-auto max-w-2xl space-y-6">

        {/* HEADER */}

        <header>
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-100 text-2xl">
              ⚽
            </div>

            <div>
              <h1 className="text-2xl font-extrabold tracking-tight text-gray-900">
                Team Lineups
              </h1>

              <p className="mt-1 text-sm text-gray-500">
                Check starting XI, substitutes, injuries, and team news.
              </p>
            </div>
          </div>
        </header>

        {/* SEARCH CARD */}

        <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="mb-5">
            <h2 className="text-lg font-bold text-gray-900">
              Find Match Lineups
            </h2>

            <p className="mt-1 text-sm text-gray-500">
              Enter both teams to open lineup information in your browser.
            </p>
          </div>

          <form onSubmit={openLineupSearch} className="space-y-4">

            {/* HOME TEAM */}

            <div>
              <label
                htmlFor="home-team"
                className="mb-1.5 block text-sm font-semibold text-gray-700"
              >
                Home Team
              </label>

              <input
                id="home-team"
                type="text"
                value={homeTeam}
                onChange={(event) =>
                  setHomeTeam(event.target.value)
                }
                placeholder="e.g. Arsenal"
                required
                className="
                  w-full
                  rounded-xl
                  border
                  border-gray-200
                  bg-gray-50
                  px-4
                  py-3
                  text-sm
                  text-gray-900
                  outline-none
                  transition
                  focus:border-blue-500
                  focus:bg-white
                  focus:ring-2
                  focus:ring-blue-500/20
                "
              />
            </div>

            {/* AWAY TEAM */}

            <div>
              <label
                htmlFor="away-team"
                className="mb-1.5 block text-sm font-semibold text-gray-700"
              >
                Away Team
              </label>

              <input
                id="away-team"
                type="text"
                value={awayTeam}
                onChange={(event) =>
                  setAwayTeam(event.target.value)
                }
                placeholder="e.g. Chelsea"
                required
                className="
                  w-full
                  rounded-xl
                  border
                  border-gray-200
                  bg-gray-50
                  px-4
                  py-3
                  text-sm
                  text-gray-900
                  outline-none
                  transition
                  focus:border-blue-500
                  focus:bg-white
                  focus:ring-2
                  focus:ring-blue-500/20
                "
              />
            </div>

            {/* MATCH DATE */}

            <div>
              <label
                htmlFor="match-date"
                className="mb-1.5 block text-sm font-semibold text-gray-700"
              >
                Match Date
                <span className="ml-1 font-normal text-gray-400">
                  (Optional)
                </span>
              </label>

              <input
                id="match-date"
                type="date"
                value={matchDate}
                onChange={(event) =>
                  setMatchDate(event.target.value)
                }
                className="
                  w-full
                  rounded-xl
                  border
                  border-gray-200
                  bg-gray-50
                  px-4
                  py-3
                  text-sm
                  text-gray-900
                  outline-none
                  transition
                  focus:border-blue-500
                  focus:bg-white
                  focus:ring-2
                  focus:ring-blue-500/20
                "
              />
            </div>

            {/* SUBMIT */}

            <button
              type="submit"
              className="
                flex
                w-full
                items-center
                justify-center
                gap-2
                rounded-xl
                bg-blue-600
                px-4
                py-3.5
                text-sm
                font-bold
                text-white
                shadow-sm
                transition
                hover:bg-blue-700
                active:scale-[0.98]
              "
            >
              <span>🌐</span>
              Search Team Lineups
              <span>↗</span>
            </button>
          </form>
        </section>

        {/* DIRECT WEBSITES */}

        <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-bold text-gray-900">
            Lineup Websites
          </h2>

          <p className="mt-1 text-sm text-gray-500">
            Open a football website in your browser to check match lineups.
          </p>

          <div className="mt-4 space-y-3">

            {/* SOFASCORE */}

            <button
              type="button"
              onClick={() =>
                openPopularLineups(
                  "https://www.sofascore.com/"
                )
              }
              className="
                flex
                w-full
                items-center
                justify-between
                rounded-xl
                border
                border-gray-200
                bg-gray-50
                px-4
                py-3
                text-left
                transition
                hover:border-blue-300
                hover:bg-blue-50
              "
            >
              <div>
                <p className="text-sm font-bold text-gray-900">
                  Sofascore
                </p>

                <p className="mt-0.5 text-xs text-gray-500">
                  Lineups, formations, and player statistics
                </p>
              </div>

              <span className="text-lg text-blue-600">
                ↗
              </span>
            </button>

            {/* SOCCERWAY */}

            <button
              type="button"
              onClick={() =>
                openPopularLineups(
                  "https://int.soccerway.com/"
                )
              }
              className="
                flex
                w-full
                items-center
                justify-between
                rounded-xl
                border
                border-gray-200
                bg-gray-50
                px-4
                py-3
                text-left
                transition
                hover:border-blue-300
                hover:bg-blue-50
              "
            >
              <div>
                <p className="text-sm font-bold text-gray-900">
                  Soccerway
                </p>

                <p className="mt-0.5 text-xs text-gray-500">
                  Fixtures, team information, and match details
                </p>
              </div>

              <span className="text-lg text-blue-600">
                ↗
              </span>
            </button>

            {/* GOOGLE */}

            <button
              type="button"
              onClick={() =>
                openPopularLineups(
                  "https://www.google.com/search?q=football+match+lineups"
                )
              }
              className="
                flex
                w-full
                items-center
                justify-between
                rounded-xl
                border
                border-gray-200
                bg-gray-50
                px-4
                py-3
                text-left
                transition
                hover:border-blue-300
                hover:bg-blue-50
              "
            >
              <div>
                <p className="text-sm font-bold text-gray-900">
                  Google Lineup Search
                </p>

                <p className="mt-0.5 text-xs text-gray-500">
                  Search for confirmed starting lineups
                </p>
              </div>

              <span className="text-lg text-blue-600">
                ↗
              </span>
            </button>

          </div>
        </section>

        {/* INFORMATION NOTICE */}

        <div className="rounded-xl border border-amber-100 bg-amber-50 px-4 py-3">
          <p className="text-xs leading-relaxed text-amber-800">
            <strong>Note:</strong> Starting lineups are usually confirmed
            shortly before kickoff. Always check the latest team news before
            making decisions based on player availability.
          </p>
        </div>

      </div>
    </div>
  );
}
