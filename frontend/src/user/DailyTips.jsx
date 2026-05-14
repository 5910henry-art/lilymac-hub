// src/pages/DailyTips.jsx
import React, { useEffect, useState, useContext } from "react";
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
    if (t.startsWith("data:") || t.startsWith("blob:") || t.startsWith("<svg")) {
      return url;
    }
  }

  try {
    if (url.startsWith("/")) return url;

    const parsed = new URL(url, window.location.origin);

    if (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1") {
      return window.location.origin + parsed.pathname + parsed.search;
    }

    if (window.location.protocol === "https:" && parsed.protocol === "http:") {
      parsed.protocol = "https:";
      return parsed.toString();
    }

    return parsed.toString();
  } catch {
    return url || "/default-logo.png";
  }
}

/**
 * ✅ Always use UTC date → convert to EAT
 */
function toLocalDateTime(utcdate) {
  if (!utcdate) return null;

  const d = new Date(utcdate);
  if (Number.isNaN(d.getTime())) return null;

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

export default function DailyTips() {
  const { tips: contextTips = [] } = useContext(TipsContext);

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
            crestMap.set(normalize(c), t);
          }
        }

        const findCrestByName = (name) => {
          if (!name) return "/default-logo.png";
          const t = crestMap.get(normalize(name));
          if (!t) return "/default-logo.png";

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

        const sourceTips = Array.isArray(contextTips) ? contextTips : [];

        const enriched = sourceTips.map((t) => {
          const prediction = t.prediction || "";

          const pFromField = Number(t.probability);
          const pHome = Number(t.probabilities?.home_win || 0);
          const pAway = Number(t.probabilities?.away_win || 0);
          const pDraw = Number(t.probabilities?.draw || 0);

          let prob = Number.isFinite(pFromField) ? pFromField : 0;
          if (!Number.isFinite(pFromField) || pFromField === 0) {
            if (prediction === "Home Win") prob = pHome * 100;
            else if (prediction === "Away Win") prob = pAway * 100;
            else prob = pDraw * 100;
          }

          const probability = Math.round(Number(prob) * 10) / 10;

          const homeName = t.home_team?.name || t.home_team_name || "";
          const awayName = t.away_team?.name || t.away_team_name || "";

          const homeLogo = normalizeLogoUrl(
            t.home_team?.crest || findCrestByName(homeName)
          );
          const awayLogo = normalizeLogoUrl(
            t.away_team?.crest || findCrestByName(awayName)
          );

          // ✅ normalize utcdate safely
          const utc = t.utcdate || t.utcDate;

          return {
            ...t,
            probability,
            home_logo: homeLogo,
            away_logo: awayLogo,
            _home_name: homeName,
            _away_name: awayName,
            _local_display: toLocalDateTime(utc),
          };
        });

        const filtered = enriched
          .filter((x) => Number(x.probability) > 60)
          .sort((a, b) => b.probability - a.probability);

        if (mounted) setTips(filtered);
      } catch (err) {
        if (mounted) setTips([]);
      } finally {
        if (mounted) setLoading(false);
      }
    };

    prepare();

    return () => {
      mounted = false;
    };
  }, [contextTips]);

  if (loading) return <Loader />;

  if (!tips.length) {
    return (
      <div className="p-4 max-w-5xl mx-auto text-center">
        <h1 className="text-2xl font-bold">No Tips Today</h1>
      </div>
    );
  }

  const tipOfTheDay = tips[0];

  return (
    <div className="p-4 max-w-5xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">Daily Tips</h1>

      {tipOfTheDay && (
        <section className="bg-gradient-to-r from-blue-500 to-purple-600 text-white p-6 rounded-2xl mb-6 shadow-lg">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-4">
              <img
                src={tipOfTheDay.home_logo}
                className="w-16 h-16 object-contain"
                loading="lazy"
              />
              <div className="flex flex-col">
                <span className="font-semibold">{tipOfTheDay._home_name}</span>
                {tipOfTheDay._local_display && (
                  <span className="text-sm text-white/80">
                    {tipOfTheDay._local_display}
                  </span>
                )}
              </div>
            </div>

            <div className="text-center">
              <div className="text-2xl font-bold">vs</div>
              <div className="text-sm text-white/80 mt-1">
                {tipOfTheDay.competition || "Unknown League"}
              </div>
            </div>

            <div className="flex items-center gap-4">
              <div className="flex flex-col items-end">
                <span className="font-semibold">{tipOfTheDay._away_name}</span>
              </div>
              <img
                src={tipOfTheDay.away_logo}
                className="w-16 h-16 object-contain"
                loading="lazy"
              />
            </div>
          </div>

          <div className="mt-4 flex justify-center">
            <div className="bg-white/20 px-4 py-2 rounded-full font-semibold">
              {tipOfTheDay.prediction} — {tipOfTheDay.probability?.toFixed(1)}%
            </div>
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {tips.slice(1).map((tip) => {
          const key =
            tip.prediction_id ||
            tip.match_id ||
            tip.id ||
            `${tip._home_name}-${tip._away_name}-${tip._local_display}`;

          return (
            <article
              key={key}
              className="p-4 bg-white dark:bg-gray-800 rounded-xl shadow flex flex-col gap-3"
            >
              <div className="flex items-center justify-between w-full gap-2">
                <div className="flex items-center gap-3">
                  <img src={tip.home_logo} className="w-10 h-10 object-contain" />
                  <div>
                    <div className="text-sm font-medium">{tip._home_name}</div>
                    <div className="text-xs text-gray-400">
                      {tip._local_display}
                    </div>
                  </div>
                </div>

                <div className="text-sm font-medium">vs</div>

                <div className="flex items-center gap-3">
                  <div className="text-sm font-medium">{tip._away_name}</div>
                  <img src={tip.away_logo} className="w-10 h-10 object-contain" />
                </div>
              </div>

              <div className="text-center text-sm font-semibold">
                {tip.prediction} — {tip.probability?.toFixed(1)}%
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
