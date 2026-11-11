import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useParams } from "react-router-dom";
import api from "../api/api";

/* =========================================================
   HELPERS
========================================================= */

function clamp(value, min = 0, max = 100) {
  const n = Number(value);

  if (!Number.isFinite(n)) return min;

  return Math.max(min, Math.min(n, max));
}

function normalizePct(value) {
  const n = Number(value);

  if (!Number.isFinite(n)) return 0;

  return n >= 0 && n <= 1
    ? clamp(n * 100)
    : clamp(n);
}

function getMatchDate(match) {
  if (!match) return null;

  if (
    match.timestamp !== undefined &&
    match.timestamp !== null
  ) {
    const timestamp = Number(match.timestamp);

    if (Number.isFinite(timestamp)) {
      const date = new Date(timestamp * 1000);

      if (!Number.isNaN(date.getTime())) {
        return date;
      }
    }
  }

  const value =
    match.match_time ||
    match.kickoff ||
    match.localDate ||
    match.utcDate ||
    match.utcdate ||
    match.date;

  if (!value) return null;

  const date = new Date(value);

  return Number.isNaN(date.getTime())
    ? null
    : date;
}

function getMatchTimestamp(match) {
  const date = getMatchDate(match);

  return date ? date.getTime() : 0;
}

function getDefaultStats() {
  return {
    over25: 0,
    btts: 0,
    avgGoals: 0,
    attackHome: 0,
    defenseHome: 0,
    attackAway: 0,
    defenseAway: 0,
  };
}

function getFormColor(result) {
  if (result === "W") {
    return "bg-emerald-500 text-white";
  }

  if (result === "L") {
    return "bg-rose-500 text-white";
  }

  return "bg-amber-400 text-slate-900";
}

function getPredictionColor(prediction) {
  const value = String(
    prediction || ""
  ).toUpperCase();

  if (
    value.includes("HOME") ||
    value === "1"
  ) {
    return "text-emerald-600";
  }

  if (
    value.includes("AWAY") ||
    value === "2"
  ) {
    return "text-blue-600";
  }

  if (
    value.includes("DRAW") ||
    value === "X"
  ) {
    return "text-amber-600";
  }

  return "text-slate-900";
}

function getConfidenceLevel(value) {
  const pct = normalizePct(value);

  if (pct >= 80) return "Very High";
  if (pct >= 65) return "High";
  if (pct >= 50) return "Moderate";

  return "Low";
}

/* =========================================================
   TEAM FORM
========================================================= */

function getTeamForm(
  matches,
  teamName,
  limit = 5
) {
  if (!teamName || !Array.isArray(matches)) {
    return [];
  }

  return matches
    .filter(
      (match) =>
        match?.home_team_name === teamName ||
        match?.away_team_name === teamName
    )
    .filter(
      (match) =>
        match.home_score !== null &&
        match.home_score !== undefined &&
        match.away_score !== null &&
        match.away_score !== undefined
    )
    .sort(
      (a, b) =>
        getMatchTimestamp(b) -
        getMatchTimestamp(a)
    )
    .slice(0, limit)
    .map((match) => {
      const home = Number(match.home_score);
      const away = Number(match.away_score);

      const isHome =
        match.home_team_name === teamName;

      const teamScore = isHome
        ? home
        : away;

      const opponentScore = isHome
        ? away
        : home;

      if (teamScore > opponentScore) {
        return "W";
      }

      if (teamScore < opponentScore) {
        return "L";
      }

      return "D";
    });
}

/* =========================================================
   CALCULATE STATS
========================================================= */

function calculateStats(
  matches,
  team1,
  team2
) {
  if (
    !Array.isArray(matches) ||
    !matches.length ||
    !team1 ||
    !team2
  ) {
    return getDefaultStats();
  }

  const relevantMatches = matches
    .filter(
      (match) =>
        match?.home_team_name === team1 ||
        match?.away_team_name === team1 ||
        match?.home_team_name === team2 ||
        match?.away_team_name === team2
    )
    .filter(
      (match) =>
        match.home_score !== null &&
        match.home_score !== undefined &&
        match.away_score !== null &&
        match.away_score !== undefined
    )
    .sort(
      (a, b) =>
        getMatchTimestamp(b) -
        getMatchTimestamp(a)
    )
    .slice(0, 10);

  if (!relevantMatches.length) {
    return getDefaultStats();
  }

  let over25 = 0;
  let btts = 0;
  let totalGoals = 0;

  let team1GF = 0;
  let team1GA = 0;

  let team2GF = 0;
  let team2GA = 0;

  relevantMatches.forEach((match) => {
    const home = Number(match.home_score);
    const away = Number(match.away_score);

    if (
      !Number.isFinite(home) ||
      !Number.isFinite(away)
    ) {
      return;
    }

    const goals = home + away;

    totalGoals += goals;

    if (goals > 2.5) {
      over25++;
    }

    if (home > 0 && away > 0) {
      btts++;
    }

    if (match.home_team_name === team1) {
      team1GF += home;
      team1GA += away;
    }

    if (match.away_team_name === team1) {
      team1GF += away;
      team1GA += home;
    }

    if (match.home_team_name === team2) {
      team2GF += home;
      team2GA += away;
    }

    if (match.away_team_name === team2) {
      team2GF += away;
      team2GA += home;
    }
  });

  const count = relevantMatches.length;

  return {
    over25: Number(
      ((over25 / count) * 100).toFixed(1)
    ),

    btts: Number(
      ((btts / count) * 100).toFixed(1)
    ),

    avgGoals: Number(
      (totalGoals / count).toFixed(1)
    ),

    attackHome: Number(
      (team1GF / count).toFixed(1)
    ),

    defenseHome: Number(
      (team1GA / count).toFixed(1)
    ),

    attackAway: Number(
      (team2GF / count).toFixed(1)
    ),

    defenseAway: Number(
      (team2GA / count).toFixed(1)
    ),
  };
}

/* =========================================================
   MAIN COMPONENT
========================================================= */

export default function TeamMatchOverviewPage() {
  const { matchId: paramId } = useParams();

  const [matches, setMatches] = useState([]);
  const [matchId, setMatchId] = useState(null);

  const [data, setData] = useState(null);
  const [recentMatches, setRecentMatches] =
    useState([]);

  const [matchesLoading, setMatchesLoading] =
    useState(true);

  const [loading, setLoading] =
    useState(false);

  const [error, setError] = useState("");

  const mountedRef = useRef(true);

  /* =======================================================
     URL MATCH ID
  ======================================================= */

  useEffect(() => {
    if (!paramId) return;

    const id = Number(paramId);

    if (Number.isFinite(id)) {
      setMatchId(id);
    } else {
      setMatchId(null);
    }
  }, [paramId]);

  /* =======================================================
     LOAD MATCHES
  ======================================================= */

  const loadMatches = useCallback(async () => {
    try {
      setMatchesLoading(true);

      const response =
        await api.getUpcomingMatches();

      if (!mountedRef.current) return;

      if (response?.success) {
        const list = Array.isArray(
          response.data?.matches
        )
          ? response.data.matches
          : [];

        setMatches(list);

        if (!paramId && list.length > 0) {
          const firstId =
            Number(list[0]?.id);

          if (Number.isFinite(firstId)) {
            setMatchId(firstId);
          }
        }
      } else {
        setMatches([]);
      }
    } catch (err) {
      console.error(
        "Failed to load matches:",
        err
      );

      if (!mountedRef.current) return;

      setMatches([]);
      setError(
        "Unable to load upcoming matches."
      );
    } finally {
      if (mountedRef.current) {
        setMatchesLoading(false);
      }
    }
  }, [paramId]);

  /* =======================================================
     LOAD OVERVIEW
  ======================================================= */

  const loadOverview = useCallback(
    async (id) => {
      if (!id) return;

      try {
        setLoading(true);
        setError("");

        const [
          overviewResponse,
          recentResponse,
        ] = await Promise.all([
          api.getTeamMatchOverview(
            Number(id)
          ),

          api.getRecentMatches({
            limit: 200,
          }),
        ]);

        if (!mountedRef.current) return;

        setData(
          overviewResponse?.success
            ? overviewResponse.data || null
            : null
        );

        setRecentMatches(
          recentResponse?.success &&
            Array.isArray(
              recentResponse.data?.matches
            )
            ? recentResponse.data.matches
            : []
        );
      } catch (err) {
        console.error(
          "Failed to load overview:",
          err
        );

        if (!mountedRef.current) return;

        setData(null);
        setRecentMatches([]);

        setError(
          "Unable to load match analysis."
        );
      } finally {
        if (mountedRef.current) {
          setLoading(false);
        }
      }
    },
    []
  );

  /* =======================================================
     INITIAL LOAD
  ======================================================= */

  useEffect(() => {
    mountedRef.current = true;

    loadMatches();

    return () => {
      mountedRef.current = false;
    };
  }, [loadMatches]);

  /* =======================================================
     LOAD SELECTED MATCH
  ======================================================= */

  useEffect(() => {
    if (matchId !== null) {
      loadOverview(matchId);
    }
  }, [matchId, loadOverview]);

  /* =======================================================
     SCROLL TOP
  ======================================================= */

  useEffect(() => {
    window.scrollTo({
      top: 0,
      behavior: "smooth",
    });
  }, [matchId]);

  /* =======================================================
     DERIVED DATA
  ======================================================= */

  const h2h = data?.h2h_stats || null;

  const prediction =
    data?.next_match_prediction || null;

  const pastPredictions =
    Array.isArray(data?.past_predictions)
      ? data.past_predictions
      : [];

  const finishedMatches = useMemo(() => {
    if (!Array.isArray(h2h?.matches)) {
      return [];
    }

    return h2h.matches.filter(
      (match) =>
        match.home_score !== null &&
        match.home_score !== undefined &&
        match.away_score !== null &&
        match.away_score !== undefined
    );
  }, [h2h]);

  const homeForm = useMemo(
    () =>
      getTeamForm(
        recentMatches,
        prediction?.home_team
      ),
    [recentMatches, prediction]
  );

  const awayForm = useMemo(
    () =>
      getTeamForm(
        recentMatches,
        prediction?.away_team
      ),
    [recentMatches, prediction]
  );

  const stats = useMemo(
    () =>
      calculateStats(
        recentMatches,
        prediction?.home_team,
        prediction?.away_team
      ),
    [recentMatches, prediction]
  );

  const confidence = normalizePct(
    prediction?.confidence
  );

  /* =======================================================
     INVALID ID
  ======================================================= */

  if (paramId && matchId === null) {
    return (
      <div className="
        min-h-screen
        bg-slate-50
        flex
        items-center
        justify-center
        p-4
      ">
        <div className="
          w-full
          max-w-sm
          rounded-2xl
          border
          border-slate-200
          bg-white
          p-6
          text-center
          shadow-sm
        ">
          <div className="text-3xl mb-3">
            ⚠️
          </div>

          <h2 className="
            font-bold
            text-slate-800
          ">
            Invalid match
          </h2>

          <p className="
            mt-1
            text-sm
            text-slate-500
          ">
            The selected match ID is invalid.
          </p>
        </div>
      </div>
    );
  }

  /* =======================================================
     PAGE
  ======================================================= */

  return (
    <div className="
      min-h-screen
      bg-slate-50
    ">

      <div className="
        mx-auto
        w-full
        max-w-6xl
        px-3
        py-4
        sm:px-5
        sm:py-5
      ">

        {/* =================================================
            HEADER
        ================================================= */}

        <div className="
          mb-4
          flex
          flex-col
          gap-3
          sm:flex-row
          sm:items-center
          sm:justify-between
        ">

          <div>
            <p className="
              text-[10px]
              font-bold
              uppercase
              tracking-[0.2em]
              text-blue-600
            ">
              Football Analytics
            </p>

            <h1 className="
              mt-0.5
              text-xl
              font-black
              tracking-tight
              text-slate-900
              sm:text-2xl
            ">
              Match Overview
            </h1>

          </div>

          <div className="
            w-full
            sm:w-80
          ">

            {matchesLoading ? (
              <div className="
                h-10
                animate-pulse
                rounded-xl
                bg-slate-200
              " />
            ) : (
              <select
                aria-label="Select upcoming match"
                value={matchId ?? ""}
                onChange={(event) => {
                  const id = Number(
                    event.target.value
                  );

                  if (Number.isFinite(id)) {
                    setMatchId(id);
                  }
                }}
                className="
                  w-full
                  rounded-xl
                  border
                  border-slate-200
                  bg-white
                  px-3
                  py-2.5
                  text-sm
                  font-medium
                  text-slate-700
                  shadow-sm
                  outline-none
                  focus:border-blue-500
                  focus:ring-2
                  focus:ring-blue-500/20
                "
              >
                {matches.length === 0 && (
                  <option value="">
                    No upcoming matches
                  </option>
                )}

                {matches.map((match) => (
                  <option
                    key={match.id}
                    value={match.id}
                  >
                    {match.home_team_name ||
                      "Home"}
                    {" vs "}
                    {match.away_team_name ||
                      "Away"}
                  </option>
                ))}
              </select>
            )}

          </div>
        </div>

        {/* =================================================
            ERROR
        ================================================= */}

        {error && (
          <div className="
            mb-4
            rounded-xl
            border
            border-rose-200
            bg-rose-50
            px-3
            py-2.5
            text-xs
            text-rose-700
          ">
            ⚠️ {error}
          </div>
        )}

        {/* =================================================
            LOADING
        ================================================= */}

        {loading && (
          <div className="
            mb-4
            flex
            items-center
            gap-2
            rounded-xl
            border
            border-slate-200
            bg-white
            px-4
            py-3
            text-xs
            text-slate-500
          ">
            <div className="
              h-4
              w-4
              animate-spin
              rounded-full
              border-2
              border-slate-200
              border-t-blue-600
            " />

            Updating analysis...
          </div>
        )}

        {/* =================================================
            PREDICTION
        ================================================= */}

        {prediction && !loading && (
          <section className="
            mb-4
            overflow-hidden
            rounded-2xl
            border
            border-slate-200
            bg-white
            shadow-sm
          ">

            <div className="
              bg-gradient-to-br
              from-slate-950
              via-slate-900
              to-blue-950
              px-4
              py-4
              text-white
              sm:px-5
            ">

              <div className="
                mb-4
                flex
                items-center
                justify-between
              ">

                <div>
                  <p className="
                    text-[9px]
                    font-bold
                    uppercase
                    tracking-[0.18em]
                    text-blue-300
                  ">
                    Match Prediction
                  </p>

                  <h2 className="
                    mt-1
                    text-base
                    font-bold
                    sm:text-lg
                  ">
                    {prediction.home_team ||
                      "Home"}

                    <span className="
                      mx-2
                      text-slate-500
                    ">
                      vs
                    </span>

                    {prediction.away_team ||
                      "Away"}
                  </h2>
                </div>

                <span className="
                  rounded-full
                  bg-white/10
                  px-2.5
                  py-1
                  text-[9px]
                  font-bold
                  text-blue-200
                ">
                  AI
                </span>

              </div>

              <div className="
                grid
                grid-cols-3
                items-center
                gap-2
              ">

                <CompactTeam
                  name={
                    prediction.home_team ||
                    "Home"
                  }
                  form={homeForm}
                />

                <div className="
                  text-center
                ">

                  <p className="
                    text-[9px]
                    uppercase
                    tracking-wider
                    text-slate-400
                  ">
                    Prediction
                  </p>

                  <p
                    className={`
                      mt-1
                      text-2xl
                      font-black
                      ${getPredictionColor(
                        prediction.prediction
                      )}
                    `}
                  >
                    {prediction.prediction ||
                      "-"}
                  </p>

                </div>

                <CompactTeam
                  name={
                    prediction.away_team ||
                    "Away"
                  }
                  form={awayForm}
                  align="right"
                />

              </div>
            </div>

            {/* CONFIDENCE */}

            <div className="
              px-4
              py-3
              sm:px-5
            ">

              <div className="
                mb-1.5
                flex
                items-center
                justify-between
              ">

                <span className="
                  text-[10px]
                  font-semibold
                  uppercase
                  tracking-wide
                  text-slate-400
                ">
                  Confidence
                </span>

                <span className="
                  text-sm
                  font-black
                  text-slate-800
                ">
                  {confidence.toFixed(0)}%
                </span>

              </div>

              <div className="
                h-2
                overflow-hidden
                rounded-full
                bg-slate-100
              ">
                <div
                  className="
                    h-full
                    rounded-full
                    bg-gradient-to-r
                    from-blue-500
                    to-emerald-500
                  "
                  style={{
                    width: `${confidence}%`,
                  }}
                />
              </div>

              <p className="
                mt-1
                text-[10px]
                text-slate-400
              ">
                {getConfidenceLevel(
                  confidence
                )} confidence
              </p>

            </div>
          </section>
        )}

        {/* =================================================
            INDICATORS
        ================================================= */}

        {prediction && (
          <section className="mb-4">

            <div className="mb-2">
              <h2 className="
                text-sm
                font-bold
                text-slate-900
              ">
                Match Indicators
              </h2>
            </div>

            <div className="
              grid
              grid-cols-3
              gap-2
            ">

              <SmallStat
                label="Over 2.5"
                value={`${stats.over25.toFixed(
                  0
                )}%`}
                progress={stats.over25}
                color="bg-emerald-500"
              />

              <SmallStat
                label="BTTS"
                value={`${stats.btts.toFixed(
                  0
                )}%`}
                progress={stats.btts}
                color="bg-blue-500"
              />

              <SmallStat
                label="Avg Goals"
                value={stats.avgGoals.toFixed(
                  1
                )}
                progress={clamp(
                  (stats.avgGoals / 5) *
                    100
                )}
                color="bg-violet-500"
              />

            </div>
          </section>
        )}

        {/* =================================================
            TEAM STRENGTH
        ================================================= */}

        {prediction && (
          <section className="
            mb-4
            rounded-xl
            border
            border-slate-200
            bg-white
            p-4
            shadow-sm
          ">

            <div className="mb-3">
              <h2 className="
                text-sm
                font-bold
                text-slate-900
              ">
                Team Strength
              </h2>

              <p className="
                mt-0.5
                text-[10px]
                text-slate-400
              ">
                Recent attacking and defensive performance
              </p>
            </div>

            <div className="
              grid
              gap-x-5
              gap-y-3
              sm:grid-cols-2
            ">

              <StrengthBar
                team={
                  prediction.home_team ||
                  "Home"
                }
                metric="Attack"
                value={stats.attackHome}
                color="bg-emerald-500"
              />

              <StrengthBar
                team={
                  prediction.away_team ||
                  "Away"
                }
                metric="Attack"
                value={stats.attackAway}
                color="bg-blue-500"
              />

              <StrengthBar
                team={
                  prediction.home_team ||
                  "Home"
                }
                metric="Defense"
                value={stats.defenseHome}
                color="bg-rose-500"
              />

              <StrengthBar
                team={
                  prediction.away_team ||
                  "Away"
                }
                metric="Defense"
                value={stats.defenseAway}
                color="bg-violet-500"
              />

            </div>
          </section>
        )}

        {/* =================================================
            H2H
        ================================================= */}

        {h2h && (
          <section className="
            mb-4
            rounded-xl
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
            ">

              <div>
                <h2 className="
                  text-sm
                  font-bold
                  text-slate-900
                ">
                  Head-to-Head
                </h2>

                <p className="
                  mt-0.5
                  text-[10px]
                  text-slate-400
                ">
                  Historical results
                </p>
              </div>

              <span className="
                rounded-full
                bg-slate-100
                px-2
                py-1
                text-[9px]
                font-bold
                text-slate-500
              ">
                H2H
              </span>

            </div>

            <div className="
              grid
              grid-cols-3
              gap-2
            ">

              <H2HCard
                label="Home"
                value={h2h.home_win_rate}
                color="emerald"
              />

              <H2HCard
                label="Draw"
                value={h2h.draw_rate}
                color="amber"
              />

              <H2HCard
                label="Away"
                value={h2h.away_win_rate}
                color="blue"
              />

            </div>
          </section>
        )}

        {/* =================================================
            COMPACT MATCH HISTORY
        ================================================= */}

        {finishedMatches.length > 0 && (
          <section className="
            overflow-hidden
            rounded-xl
            border
            border-slate-200
            bg-white
            shadow-sm
          ">

            <div className="
              flex
              items-center
              justify-between
              border-b
              border-slate-100
              px-4
              py-3
            ">

              <div>
                <h2 className="
                  text-sm
                  font-bold
                  text-slate-900
                ">
                  Match History
                </h2>

                <p className="
                  mt-0.5
                  text-[10px]
                  text-slate-400
                ">
                  Previous meetings
                </p>
              </div>

              <span className="
                rounded-full
                bg-slate-100
                px-2
                py-1
                text-[9px]
                font-bold
                text-slate-500
              ">
                {finishedMatches.length}
              </span>

            </div>

            <div className="
              max-h-80
              overflow-y-auto
              p-2
              sm:p-3
            ">

              <div className="space-y-1.5">

                {finishedMatches.map(
                  (match, index) => {
                    const predictionResult =
                      pastPredictions.find(
                        (item) =>
                          String(
                            item?.match_id
                          ) ===
                          String(
                            match?.match_id
                          )
                      );

                    return (
                      <HistoryRow
                        key={
                          match.match_id ||
                          match.id ||
                          index
                        }
                        match={match}
                        prediction={
                          predictionResult
                        }
                      />
                    );
                  }
                )}

              </div>
            </div>
          </section>
        )}

        {/* =================================================
            EMPTY
        ================================================= */}

        {!loading &&
          !prediction &&
          !finishedMatches.length &&
          !matchesLoading && (
            <div className="
              rounded-xl
              border
              border-dashed
              border-slate-300
              bg-white
              p-8
              text-center
            ">

              <div className="text-3xl">
                ⚽
              </div>

              <h2 className="
                mt-2
                text-sm
                font-bold
                text-slate-800
              ">
                No analysis available
              </h2>

              <p className="
                mt-1
                text-xs
                text-slate-500
              ">
                Analysis is not available for this match.
              </p>

            </div>
          )}

      </div>
    </div>
  );
}

/* =========================================================
   COMPACT TEAM
========================================================= */

function CompactTeam({
  name,
  form,
  align = "left",
}) {
  return (
    <div
      className={
        align === "right"
          ? "text-right"
          : "text-left"
      }
    >

      <p className="
        text-[9px]
        font-bold
        uppercase
        tracking-wider
        text-slate-400
      ">
        {align === "right"
          ? "Away"
          : "Home"}
      </p>

      <p className="
        mt-0.5
        truncate
        text-sm
        font-bold
        text-white
        sm:text-base
      ">
        {name}
      </p>

      <div
        className={`
          mt-2
          flex
          gap-1
          ${
            align === "right"
              ? "justify-end"
              : "justify-start"
          }
        `}
      >
        {form.length > 0 ? (
          form.map((result, index) => (
            <span
              key={`${result}-${index}`}
              className={`
                flex
                h-5
                w-5
                items-center
                justify-center
                rounded
                text-[8px]
                font-black
                ${getFormColor(result)}
              `}
            >
              {result}
            </span>
          ))
        ) : (
          <span className="
            text-[9px]
            text-slate-500
          ">
            No form
          </span>
        )}
      </div>

    </div>
  );
}

/* =========================================================
   SMALL STAT
========================================================= */

function SmallStat({
  label,
  value,
  progress,
  color,
}) {
  return (
    <div className="
      rounded-xl
      border
      border-slate-200
      bg-white
      p-3
      shadow-sm
    ">

      <p className="
        text-[9px]
        font-bold
        uppercase
        tracking-wide
        text-slate-400
      ">
        {label}
      </p>

      <p className="
        mt-1
        text-lg
        font-black
        text-slate-900
      ">
        {value}
      </p>

      <div className="
        mt-2
        h-1.5
        overflow-hidden
        rounded-full
        bg-slate-100
      ">
        <div
          className={`
            h-full
            rounded-full
            ${color}
          `}
          style={{
            width: `${clamp(progress)}%`,
          }}
        />
      </div>

    </div>
  );
}

/* =========================================================
   STRENGTH BAR
========================================================= */

function StrengthBar({
  team,
  metric,
  value,
  color,
}) {
  const number = Number(value) || 0;

  const percentage = clamp(
    (number / 5) * 100
  );

  return (
    <div>

      <div className="
        mb-1
        flex
        items-center
        justify-between
      ">

        <div className="
          flex
          min-w-0
          items-center
          gap-1.5
        ">

          <span className="
            truncate
            text-xs
            font-semibold
            text-slate-700
          ">
            {team}
          </span>

          <span className="
            rounded
            bg-slate-100
            px-1.5
            py-0.5
            text-[8px]
            font-bold
            text-slate-500
          ">
            {metric}
          </span>

        </div>

        <span className="
          text-xs
          font-bold
          text-slate-800
        ">
          {number.toFixed(1)}
        </span>

      </div>

      <div className="
        h-1.5
        overflow-hidden
        rounded-full
        bg-slate-100
      ">
        <div
          className={`
            h-full
            rounded-full
            ${color}
          `}
          style={{
            width: `${percentage}%`,
          }}
        />
      </div>

    </div>
  );
}

/* =========================================================
   H2H CARD
========================================================= */

function H2HCard({
  label,
  value,
  color,
}) {
  const percentage =
    normalizePct(value);

  const colors = {
    emerald: {
      text: "text-emerald-600",
      bar: "bg-emerald-500",
    },

    amber: {
      text: "text-amber-600",
      bar: "bg-amber-500",
    },

    blue: {
      text: "text-blue-600",
      bar: "bg-blue-500",
    },
  };

  const selected =
    colors[color] || colors.blue;

  return (
    <div className="
      rounded-lg
      bg-slate-50
      p-2.5
    ">

      <p className="
        text-[9px]
        font-semibold
        text-slate-400
      ">
        {label}
      </p>

      <p
        className={`
          mt-0.5
          text-base
          font-black
          ${selected.text}
        `}
      >
        {percentage.toFixed(0)}%
      </p>

      <div className="
        mt-1.5
        h-1
        overflow-hidden
        rounded-full
        bg-slate-200
      ">
        <div
          className={`
            h-full
            rounded-full
            ${selected.bar}
          `}
          style={{
            width: `${percentage}%`,
          }}
        />
      </div>

    </div>
  );
}

/* =========================================================
   COMPACT HISTORY ROW
   NO LOGOS
========================================================= */

function HistoryRow({
  match,
  prediction,
}) {
  const homeScore =
    Number(match.home_score);

  const awayScore =
    Number(match.away_score);

  const home =
    match.home_team_name || "Home";

  const away =
    match.away_team_name || "Away";

  return (
    <div className="
      rounded-lg
      border
      border-slate-100
      bg-slate-50
      px-3
      py-2.5
      transition
      hover:border-slate-200
      hover:bg-white
    ">

      {/* MATCH */}

      <div className="
        flex
        items-center
        justify-between
        gap-3
      ">

        <div className="
          min-w-0
          flex-1
        ">

          <div className="
            flex
            min-w-0
            items-center
            gap-1.5
          ">

            <span className="
              min-w-0
              truncate
              text-[11px]
              font-semibold
              text-slate-700
            ">
              {home}
            </span>

            <span className="
              flex-shrink-0
              text-[9px]
              font-medium
              text-slate-400
            ">
              vs
            </span>

            <span className="
              min-w-0
              truncate
              text-[11px]
              font-semibold
              text-slate-700
            ">
              {away}
            </span>

          </div>

          {/* PREDICTION */}

          {prediction && (
            <div className="
              mt-1.5
              flex
              flex-wrap
              items-center
              gap-1.5
            ">

              <span className="
                text-[9px]
                text-slate-400
              ">
                Pred:
                <strong className="
                  ml-1
                  text-slate-600
                ">
                  {prediction.prediction ||
                    "-"}
                </strong>
              </span>

              <span
                className={`
                  rounded
                  px-1.5
                  py-0.5
                  text-[8px]
                  font-bold
                  ${
                    prediction.correct
                      ? "bg-emerald-100 text-emerald-600"
                      : "bg-rose-100 text-rose-600"
                  }
                `}
              >
                {prediction.correct
                  ? "✓ Correct"
                  : "✕ Wrong"}
              </span>

            </div>
          )}

        </div>

        {/* SCORE */}

        <div className="
          flex-shrink-0
          rounded-md
          bg-white
          px-2
          py-1
          text-sm
          font-black
          text-slate-900
          shadow-sm
        ">

          {Number.isFinite(homeScore)
            ? homeScore
            : "-"}

          <span className="
            mx-1
            text-slate-300
          ">
            -
          </span>

          {Number.isFinite(awayScore)
            ? awayScore
            : "-"}

        </div>

      </div>
    </div>
  );
}
