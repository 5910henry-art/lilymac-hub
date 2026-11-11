// src/pages/DailyTips.jsx
import React, {
  useEffect,
  useState,
  useContext,
  memo,
} from "react";
import api from "../api/api";
import Loader from "../components/Loader";
import { TipsContext } from "../contexts/TipsContext";

function normalize(str = "") {
  return String(str || "")
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "")
    .replace(/[^\w]/g, "");
}

function normalizeLogoUrl(url) {
  if (!url) return "/default-logo.png";

  if (typeof url === "string") {
    const t = url.trim();

    if (
      t.startsWith("data:") ||
      t.startsWith("blob:") ||
      t.startsWith("<svg")
    ) {
      return url;
    }
  }

  try {
    if (url.startsWith("/")) return url;

    const parsed = new URL(
      url,
      window.location.origin
    );

    if (
      parsed.hostname === "localhost" ||
      parsed.hostname === "127.0.0.1"
    ) {
      return (
        window.location.origin +
        parsed.pathname +
        parsed.search
      );
    }

    if (
      window.location.protocol === "https:" &&
      parsed.protocol === "http:"
    ) {
      parsed.protocol = "https:";
      return parsed.toString();
    }

    return parsed.toString();
  } catch {
    return url || "/default-logo.png";
  }
}

/**
 * UTC → East Africa Time
 */
function toLocalDateTime(utcdate) {
  if (!utcdate) return null;

  const d = new Date(utcdate);

  if (Number.isNaN(d.getTime())) {
    return null;
  }

  const datePart = d.toLocaleDateString("en-KE", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    timeZone: "Africa/Nairobi",
  });

  const timePart = d.toLocaleTimeString("en-KE", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Africa/Nairobi",
  });

  return `${datePart} • ${timePart}`;
}

const TeamLogo = memo(
  ({ src, alt = "", size = "w-14 h-14" }) => (
    <div
      className={`
        ${size}
        flex-shrink-0
        rounded-2xl
        bg-white
        dark:bg-slate-900
        p-2
        shadow-sm
        border
        border-slate-200/80
        dark:border-slate-700
        flex
        items-center
        justify-center
      `}
    >
      <img
        src={src || "/default-logo.png"}
        alt={alt}
        className="w-full h-full object-contain"
        loading="lazy"
        onError={(e) => {
          e.currentTarget.src = "/default-logo.png";
        }}
      />
    </div>
  )
);

/* =========================================================
   DAILY TIP CARD
========================================================= */

const TipCard = memo(({ tip, rank }) => {
  return (
    <article
      className="
        group
        relative
        overflow-hidden
        rounded-3xl
        border
        border-slate-200/80
        dark:border-slate-700
        bg-white
        dark:bg-slate-800
        shadow-sm
        hover:shadow-2xl
        hover:-translate-y-1
        transition-all
        duration-300
      "
    >
      {/* Accent line */}
      <div className="h-1 bg-gradient-to-r from-blue-500 via-violet-500 to-fuchsia-500" />

      <div className="p-4 sm:p-5">

        {/* HEADER */}
        <div className="flex items-center justify-between gap-3 mb-5">

          <div className="flex items-center gap-2 min-w-0">

            <span
              className="
                flex
                h-8
                w-8
                items-center
                justify-center
                rounded-xl
                bg-slate-100
                dark:bg-slate-700
                text-xs
                font-black
                text-slate-600
                dark:text-slate-200
              "
            >
              #{rank}
            </span>

            <span
              className="
                truncate
                text-xs
                font-semibold
                text-slate-500
                dark:text-slate-400
              "
            >
              {tip.competition || "Unknown League"}
            </span>

          </div>

          {/* PERCENTAGE */}
          <span
            className="
              flex-shrink-0
              rounded-full
              bg-emerald-50
              dark:bg-emerald-500/10
              px-2.5
              py-1
              text-xs
              font-black
              text-emerald-600
              dark:text-emerald-400
            "
          >
            {Number(tip.probability || 0).toFixed(1)}%
          </span>

        </div>

        {/* TEAMS */}
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">

          {/* HOME */}
          <div className="min-w-0 text-center">

            <div className="flex justify-center mb-3">
              <TeamLogo
                src={tip.home_logo}
                alt={tip._home_name}
                size="w-14 h-14"
              />
            </div>

            <p
              className="
                text-sm
                font-bold
                text-slate-800
                dark:text-white
                truncate
              "
            >
              {tip._home_name}
            </p>

            <p className="mt-1 text-[10px] font-medium uppercase tracking-wider text-slate-400">
              Home
            </p>

          </div>

          {/* VS */}
          <div className="flex flex-col items-center">

            <span
              className="
                text-[10px]
                font-black
                uppercase
                tracking-widest
                text-slate-300
                dark:text-slate-600
              "
            >
              VS
            </span>

          </div>

          {/* AWAY */}
          <div className="min-w-0 text-center">

            <div className="flex justify-center mb-3">
              <TeamLogo
                src={tip.away_logo}
                alt={tip._away_name}
                size="w-14 h-14"
              />
            </div>

            <p
              className="
                text-sm
                font-bold
                text-slate-800
                dark:text-white
                truncate
              "
            >
              {tip._away_name}
            </p>

            <p className="mt-1 text-[10px] font-medium uppercase tracking-wider text-slate-400">
              Away
            </p>

          </div>

        </div>

        {/* TIME */}
        <div
          className="
            mt-5
            flex
            items-center
            justify-center
            gap-2
            rounded-xl
            bg-slate-50
            dark:bg-slate-900/50
            px-3
            py-2
            text-xs
            font-medium
            text-slate-500
            dark:text-slate-400
          "
        >
          <span>🕒</span>

          <span>
            {tip._local_display ||
              "Match time unavailable"}
          </span>
        </div>

        {/* PICK */}
        <div
          className="
            mt-3
            rounded-2xl
            border
            border-slate-100
            dark:border-slate-700
            bg-slate-50
            dark:bg-slate-900/60
            p-3.5
          "
        >
          <div
            className="
              text-[10px]
              font-bold
              uppercase
              tracking-widest
              text-slate-400
            "
          >
            Recommended Pick
          </div>

          <div
            className="
              mt-1
              text-base
              font-black
              text-slate-900
              dark:text-white
            "
          >
            {tip.prediction ||
              "Prediction unavailable"}
          </div>
        </div>

      </div>
    </article>
  );
});

/* =========================================================
   PAGE
========================================================= */

export default function DailyTips() {
  const { tips: contextTips = [] } =
    useContext(TipsContext);

  const [tips, setTips] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    const prepare = async () => {
      setLoading(true);

      try {
        const teamsRes = await api.getTeams();

        const teams =
          teamsRes?.success &&
          teamsRes?.data &&
          Array.isArray(teamsRes.data.teams)
            ? teamsRes.data.teams
            : [];

        const crestMap = new Map();

        for (const t of teams) {
          const candidates = [
            t?.name,
            t?.short_name,
            t?.common_name,
            t?.alias,
            t?.display_name,
            t?.club_name,
            t?.team_name,
          ];

          for (const c of candidates) {
            if (!c) continue;

            crestMap.set(
              normalize(c),
              t
            );
          }
        }

        const findCrestByName = (name) => {
          if (!name) {
            return "/default-logo.png";
          }

          const t =
            crestMap.get(normalize(name));

          if (!t) {
            return "/default-logo.png";
          }

          const raw =
            t.crest ||
            t.logo ||
            t.icon ||
            t.badge ||
            t.image ||
            t.svg ||
            "/default-logo.png";

          return normalizeLogoUrl(raw);
        };

        const sourceTips = Array.isArray(
          contextTips
        )
          ? contextTips
          : [];

        const enriched =
          sourceTips.map((t) => {
            const prediction =
              t.prediction || "";

            const pFromField =
              Number(t.probability);

            const pHome = Number(
              t.probabilities?.home_win || 0
            );

            const pAway = Number(
              t.probabilities?.away_win || 0
            );

            const pDraw = Number(
              t.probabilities?.draw || 0
            );

            let prob = Number.isFinite(
              pFromField
            )
              ? pFromField
              : 0;

            if (
              !Number.isFinite(
                pFromField
              ) ||
              pFromField === 0
            ) {
              if (
                prediction === "Home Win"
              ) {
                prob = pHome * 100;
              } else if (
                prediction === "Away Win"
              ) {
                prob = pAway * 100;
              } else {
                prob = pDraw * 100;
              }
            }

            const probability =
              Math.round(
                Number(prob) * 10
              ) / 10;

            const homeName =
              t.home_team?.name ||
              t.home_team_name ||
              "";

            const awayName =
              t.away_team?.name ||
              t.away_team_name ||
              "";

            const homeLogo =
              normalizeLogoUrl(
                t.home_team?.crest ||
                  findCrestByName(
                    homeName
                  )
              );

            const awayLogo =
              normalizeLogoUrl(
                t.away_team?.crest ||
                  findCrestByName(
                    awayName
                  )
              );

            const utc =
              t.utcdate || t.utcDate;

            return {
              ...t,
              probability,
              home_logo: homeLogo,
              away_logo: awayLogo,
              _home_name: homeName,
              _away_name: awayName,
              _local_display:
                toLocalDateTime(utc),
            };
          });

        /*
         * Probability remains internal for
         * filtering and ranking.
         */
        const filtered = enriched
          .filter(
            (x) =>
              Number(x.probability) > 60
          )
          .sort(
            (a, b) =>
              b.probability -
              a.probability
          );

        if (mounted) {
          setTips(filtered);
        }
      } catch (err) {
        console.error(
          "[DAILY TIPS]",
          err
        );

        if (mounted) {
          setTips([]);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    prepare();

    return () => {
      mounted = false;
    };
  }, [contextTips]);

  /* =======================================================
     LOADING
  ======================================================= */

  if (loading) {
    return <Loader />;
  }

  /* =======================================================
     EMPTY STATE
  ======================================================= */

  if (!tips.length) {
    return (
      <div className="min-h-[70vh] flex items-center justify-center px-4">

        <div
          className="
            w-full
            max-w-md
            overflow-hidden
            rounded-3xl
            border
            border-slate-200
            dark:border-slate-700
            bg-white
            dark:bg-slate-800
            shadow-xl
            p-8
            text-center
          "
        >
          <div
            className="
              mx-auto
              mb-5
              flex
              h-16
              w-16
              items-center
              justify-center
              rounded-2xl
              bg-gradient-to-br
              from-orange-400
              to-red-500
              text-3xl
              shadow-lg
            "
          >
            🔥
          </div>

          <h1 className="text-2xl font-black text-slate-900 dark:text-white">
            No Tips Today
          </h1>

          <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
            Predictions will appear here
            when today's selections are available.
          </p>
        </div>

      </div>
    );
  }

  const tipOfTheDay = tips[0];

  /* =======================================================
     MAIN PAGE
  ======================================================= */

  return (
    <div className="min-h-screen w-full bg-slate-50 dark:bg-slate-950">

      <div className="w-full px-3 py-5 sm:px-5 lg:px-8 xl:px-10">
        <div className="mx-auto w-full max-w-7xl">

          {/* =================================================
              PAGE HEADER
          ================================================= */}

          <header className="mb-7">

            <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">

              <div>

                <div className="mb-3 flex items-center gap-2">

                  <span
                    className="
                      flex
                      h-8
                      w-8
                      items-center
                      justify-center
                      rounded-xl
                      bg-gradient-to-br
                      from-blue-500
                      to-violet-600
                      text-sm
                      shadow-lg
                    "
                  >
                    ⚽
                  </span>

                  <span
                    className="
                      text-[11px]
                      font-black
                      uppercase
                      tracking-[0.22em]
                      text-blue-600
                      dark:text-blue-400
                    "
                  >
                    LilyMac Predictions
                  </span>

                </div>

                <h1
                  className="
                    text-3xl
                    sm:text-4xl
                    lg:text-5xl
                    font-black
                    tracking-tight
                    text-slate-950
                    dark:text-white
                  "
                >
                  Daily Tips
                </h1>

              </div>

              {/* TOTAL */}
              <div
                className="
                  flex
                  w-fit
                  items-center
                  gap-3
                  rounded-2xl
                  border
                  border-slate-200
                  dark:border-slate-700
                  bg-white
                  dark:bg-slate-800
                  px-4
                  py-3
                  shadow-sm
                "
              >

                <div
                  className="
                    flex
                    h-10
                    w-10
                    items-center
                    justify-center
                    rounded-xl
                    bg-blue-50
                    dark:bg-blue-500/10
                    text-lg
                  "
                >
                  🎯
                </div>

                <div>

                  <div className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
                    Today's tips
                  </div>

                  <div className="text-xl font-black text-slate-900 dark:text-white">
                    {tips.length}
                  </div>

                </div>

              </div>

            </div>

          </header>

          {/* =================================================
              FEATURED PICK
          ================================================= */}

          {tipOfTheDay && (
            <section
              className="
                relative
                mb-9
                overflow-hidden
                rounded-[2rem]
                bg-slate-950
                text-white
                shadow-2xl
              "
            >

              {/* Background glow */}
              <div
                className="
                  pointer-events-none
                  absolute
                  -right-32
                  -top-32
                  h-80
                  w-80
                  rounded-full
                  bg-blue-500/25
                  blur-3xl
                "
              />

              <div
                className="
                  pointer-events-none
                  absolute
                  -bottom-32
                  -left-32
                  h-80
                  w-80
                  rounded-full
                  bg-violet-500/20
                  blur-3xl
                "
              />

              <div className="relative p-5 sm:p-7 lg:p-9">

                {/* FEATURE HEADER */}
                <div className="flex items-start justify-between gap-4 mb-8">

                  <div>

                    <div
                      className="
                        inline-flex
                        items-center
                        gap-2
                        rounded-full
                        border
                        border-white/10
                        bg-white/10
                        px-3
                        py-1.5
                        text-[10px]
                        font-black
                        uppercase
                        tracking-widest
                        text-blue-200
                      "
                    >
                      <span>⭐</span>
                      Featured Pick
                    </div>

                    <h2 className="mt-3 text-xl sm:text-2xl font-black">
                      Today's Featured Match
                    </h2>

                    <p className="mt-1 text-xs sm:text-sm text-white/45">
                      Our top-ranked selection for today
                    </p>

                  </div>

                  {/* FEATURED PERCENTAGE */}
                  <div
                    className="
                      flex-shrink-0
                      rounded-2xl
                      border
                      border-emerald-400/20
                      bg-emerald-400/10
                      px-3
                      py-2
                      text-right
                    "
                  >
                    <div className="text-[9px] font-bold uppercase tracking-widest text-white/40">
                      Probability
                    </div>

                    <div className="mt-0.5 text-lg font-black text-emerald-300">
                      {Number(
                        tipOfTheDay.probability || 0
                      ).toFixed(1)}
                      %
                    </div>
                  </div>

                </div>

                {/* MATCH */}
                <div
                  className="
                    grid
                    grid-cols-1
                    lg:grid-cols-[1fr_auto_1fr]
                    items-center
                    gap-7
                    lg:gap-10
                  "
                >

                  {/* HOME */}
                  <div
                    className="
                      flex
                      items-center
                      justify-center
                      gap-4
                      lg:justify-end
                      text-center
                      lg:text-right
                    "
                  >

                    <div className="order-2 lg:order-1 min-w-0">

                      <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-white/35">
                        Home
                      </p>

                      <p className="mt-1 text-lg sm:text-xl font-black truncate max-w-[180px]">
                        {tipOfTheDay._home_name}
                      </p>

                    </div>

                    <div className="order-1 lg:order-2">

                      <TeamLogo
                        src={
                          tipOfTheDay.home_logo
                        }
                        alt={
                          tipOfTheDay._home_name
                        }
                        size="w-16 h-16 sm:w-20 sm:h-20"
                      />

                    </div>

                  </div>

                  {/* CENTER */}
                  <div className="flex flex-col items-center">

                    <div
                      className="
                        flex
                        h-11
                        w-11
                        items-center
                        justify-center
                        rounded-full
                        border
                        border-white/10
                        bg-white/5
                        text-[10px]
                        font-black
                        tracking-widest
                        text-white/40
                      "
                    >
                      VS
                    </div>

                    <div
                      className="
                        mt-3
                        rounded-full
                        border
                        border-white/10
                        bg-white/5
                        px-3
                        py-1.5
                        text-[10px]
                        font-semibold
                        text-white/55
                      "
                    >
                      {tipOfTheDay.competition ||
                        "Unknown League"}
                    </div>

                  </div>

                  {/* AWAY */}
                  <div
                    className="
                      flex
                      items-center
                      justify-center
                      gap-4
                      text-center
                      lg:justify-start
                      lg:text-left
                    "
                  >

                    <TeamLogo
                      src={
                        tipOfTheDay.away_logo
                      }
                      alt={
                        tipOfTheDay._away_name
                      }
                      size="w-16 h-16 sm:w-20 sm:h-20"
                    />

                    <div className="min-w-0">

                      <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-white/35">
                        Away
                      </p>

                      <p className="mt-1 text-lg sm:text-xl font-black truncate max-w-[180px]">
                        {tipOfTheDay._away_name}
                      </p>

                    </div>

                  </div>

                </div>

                {/* FEATURE INFO */}
                <div
                  className="
                    mt-8
                    grid
                    grid-cols-1
                    sm:grid-cols-3
                    gap-3
                  "
                >

                  {/* KICKOFF */}
                  <div
                    className="
                      rounded-2xl
                      border
                      border-white/10
                      bg-white/5
                      px-4
                      py-3
                      text-center
                    "
                  >
                    <div className="text-[9px] font-bold uppercase tracking-widest text-white/30">
                      Kickoff
                    </div>

                    <div className="mt-1 text-xs sm:text-sm font-semibold text-white/80">
                      {tipOfTheDay._local_display ||
                        "TBA"}
                    </div>
                  </div>

                  {/* PREDICTION */}
                  <div
                    className="
                      rounded-2xl
                      border
                      border-emerald-400/15
                      bg-emerald-400/5
                      px-4
                      py-3
                      text-center
                    "
                  >
                    <div className="text-[9px] font-bold uppercase tracking-widest text-white/30">
                      Prediction
                    </div>

                    <div className="mt-1 text-sm sm:text-base font-black text-emerald-300">
                      {tipOfTheDay.prediction ||
                        "N/A"}
                    </div>
                  </div>

                  {/* RANK */}
                  <div
                    className="
                      rounded-2xl
                      border
                      border-white/10
                      bg-white/5
                      px-4
                      py-3
                      text-center
                    "
                  >
                    <div className="text-[9px] font-bold uppercase tracking-widest text-white/30">
                      Ranking
                    </div>

                    <div className="mt-1 text-sm font-black text-white">
                      #1
                    </div>
                  </div>

                </div>

              </div>
            </section>
          )}

          {/* =================================================
              MORE TIPS
          ================================================= */}

          {tips.length > 1 && (
            <section>

              {/* SECTION HEADER */}
              <div className="mb-5 flex items-end justify-between gap-4">

                <div>

                  <div className="flex items-center gap-2">

                    <span
                      className="
                        h-2
                        w-2
                        rounded-full
                        bg-blue-500
                        shadow-lg
                        shadow-blue-500/40
                      "
                    />

                    <h2 className="text-xl sm:text-2xl font-black text-slate-950 dark:text-white">
                      More Daily Tips
                    </h2>

                  </div>

                  <p className="mt-1 text-xs sm:text-sm text-slate-500 dark:text-slate-400">
                    Additional predictions for today's matches
                  </p>

                </div>

                <div
                  className="
                    hidden
                    sm:flex
                    items-center
                    rounded-full
                    bg-slate-100
                    dark:bg-slate-800
                    px-3
                    py-1.5
                    text-[10px]
                    font-bold
                    uppercase
                    tracking-wider
                    text-slate-500
                    dark:text-slate-400
                  "
                >
                  {tips.length - 1}{" "}
                  {tips.length - 1 === 1
                    ? "tip"
                    : "tips"}
                </div>

              </div>

              {/* GRID */}
              <div
                className="
                  grid
                  grid-cols-1
                  sm:grid-cols-2
                  xl:grid-cols-3
                  gap-4
                  lg:gap-5
                "
              >
                {tips.slice(1).map(
                  (tip, index) => {
                    const key =
                      tip.prediction_id ||
                      tip.match_id ||
                      tip.id ||
                      `${tip._home_name}-${tip._away_name}-${tip._local_display}`;

                    return (
                      <TipCard
                        key={key}
                        tip={tip}
                        rank={index + 2}
                      />
                    );
                  }
                )}
              </div>

            </section>
          )}

          {/* =================================================
              FOOTER
          ================================================= */}

          <div className="mt-9 pb-4 text-center">

            <div className="mx-auto mb-3 h-px max-w-xs bg-gradient-to-r from-transparent via-slate-300 dark:via-slate-700 to-transparent" />

            <p className="text-[11px] font-medium text-slate-400">
              Predictions selected from today's available matches.
            </p>

          </div>

        </div>
      </div>
    </div>
  );
}
