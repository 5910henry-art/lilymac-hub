// src/user/Accumulators.jsx
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import api from "../api/api";

const STAKE = 200;

/* ---------- Market Label (for UI display) ---------- */
function formatMarket(market, selection) {
  if (/3-?way/i.test(market)) {
    if (selection === "HOME") return "Home Win";
    if (selection === "AWAY") return "Away Win";
    if (selection === "DRAW") return "Draw";
    return String(selection || "").toUpperCase();
  }

  if (/btts/i.test(market)) {
    return String(selection || "").toUpperCase() === "YES"
      ? "BTTS Yes"
      : "BTTS No";
  }

  if (/^o2\.?5$/i.test(market) || /over\s*2\.5/i.test(market)) {
    return String(selection || "").toUpperCase() === "OVER"
      ? "Over 2.5 Goals"
      : "Under 2.5 Goals";
  }

  if (/^o3\.?5$/i.test(market) || /over\s*3\.5/i.test(market)) {
    return String(selection || "").toUpperCase() === "OVER"
      ? "Over 3.5 Goals"
      : "Under 3.5 Goals";
  }

  return `${market || ""} ${selection || ""}`.trim();
}

/* ---------- Raw selection for backend ---------- */
function getRawSelection(market, selection) {
  if (/3-?way/i.test(market)) {
    if (["HOME", "AWAY", "DRAW"].includes(selection)) return selection;
  }

  if (/btts/i.test(market)) {
    if (["YES", "NO"].includes(selection)) return selection;
  }

  if (/^o2\.?5$/i.test(market) || /over\s*2\.5/i.test(market)) {
    return selection === "OVER" ? "OVER" : "UNDER";
  }

  if (/^o3\.?5$/i.test(market) || /over\s*3\.5/i.test(market)) {
    return selection === "OVER" ? "OVER" : "UNDER";
  }

  return selection;
}

/* ---------- Kickoff Format ---------- */
function formatKickoff(time) {
  if (!time) return "";
  const d = new Date(time);
  return d.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/* ---------- Remove duplicate matches ---------- */
function uniqueMatches(matches) {
  const seen = new Set();
  return matches.filter((m) => {
    const key = `${m.home_team}-${m.away_team}-${m.match_time}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/* ---------- Generate Accumulator Folds ---------- */
function generateFolds(matches) {
  if (!Array.isArray(matches) || matches.length < 2) return [];

  const sorted = [...matches].sort(
    (a, b) => (b.probability || 0) - (a.probability || 0)
  );

  const folds = [];

  const takeUnique = (arr, max) => uniqueMatches(arr).slice(0, max);

  const fold1 = takeUnique(sorted, 10);
  if (fold1.length >= 2)
    folds.push({ title: "Best Tips Accumulator", matches: fold1 });

  const goalsMarkets = sorted.filter((m) => !/3-?way/i.test(m.market));
  const fold2 = takeUnique(goalsMarkets, 8);
  if (fold2.length >= 2)
    folds.push({ title: "Goals & BTTS Acca", matches: fold2 });

  const fold3 = takeUnique(sorted.slice(10), 7);
  if (fold3.length >= 2)
    folds.push({ title: "Weekend Value Acca", matches: fold3 });

  return folds;
}

/* ---------- Calculate Returns ---------- */
function calculateReturns(matches) {
  const clamp = (p) => Math.min(Math.max(Number(p) || 0.01, 0.01), 1);

  const perMatchOdds = matches.map((m) => {
    const baseOdd = 1 / clamp(m.probability);
    const add = baseOdd + 0.35 < 1.1 ? 0.5 : 0.35;
    return baseOdd + add;
  });

  const foldOdds = perMatchOdds.reduce((acc, o) => acc * o, 1);

  return {
    odds: foldOdds.toFixed(2),
    returns: Math.round(foldOdds * STAKE),
  };
}

/* ---------- Component ---------- */
export default function Accumulators({ betslip, setBetslip }) {
  const navigate = useNavigate();

  const [data, setData] = useState({});
  const [dates, setDates] = useState([]);
  const [activeDate, setActiveDate] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function load() {
      setLoading(true);
      try {
        const res = await api.getAccumulator({ by_date: true });
        const d = res?.data || res || {};

        if (!mounted) return;

        setData(d);

        const keys = Object.keys(d).sort();
        setDates(keys);

        if (keys.length) setActiveDate(keys[0]);
      } catch (err) {
        console.error("Failed to load accumulator:", err);
      } finally {
        if (mounted) setLoading(false);
      }
    }

    load();

    return () => {
      mounted = false;
    };
  }, []);

  const rawForDate = activeDate ? data[activeDate] : null;
  let matches = [];

  if (Array.isArray(rawForDate)) matches = rawForDate;
  else if (rawForDate?.matches) matches = rawForDate.matches;

  const folds = generateFolds(matches);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-900 text-emerald-400 font-bold">
        Loading accumulators...
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto p-4">
      <h1 className="text-2xl font-bold mb-4">Accumulator Tips</h1>

      {/* Date Tabs */}
      <div className="flex gap-3 overflow-x-auto mb-6">
        {dates.map((d) => (
          <button
            key={d}
            onClick={() => setActiveDate(d)}
            className={`px-3 py-1 rounded text-sm ${
              d === activeDate
                ? "bg-blue-600 text-white"
                : "bg-gray-200 hover:bg-gray-300"
            }`}
          >
            {d}
          </button>
        ))}
      </div>

      {/* Folds */}
      <div className="space-y-8">
        {folds.length === 0 && (
          <div className="text-center text-gray-500">
            Not enough tips to build folds for this date.
          </div>
        )}

        {folds.map((fold, i) => {
          const { odds, returns } = calculateReturns(fold.matches);

          return (
            <div key={i} className="bg-white shadow-md rounded-lg p-4 border">
              <h2 className="font-bold text-lg mb-2">
                {fold.title} @ {odds}
              </h2>

              <p className="text-sm text-gray-500 mb-4">
                Kick off {formatKickoff(fold.matches[0]?.match_time)}
              </p>

              <div className="space-y-3">
                {fold.matches.map((m, idx) => {
                  const baseOdd = 1 / (m.probability || 0.01);
                  const matchOdd = (
                    baseOdd + (baseOdd + 0.35 < 1.1 ? 0.5 : 0.35)
                  ).toFixed(2);

                  return (
                    <div key={idx} className="border-b pb-2">
                      <div className="text-sm font-semibold text-gray-800">
                        <span className="text-blue-600">{m.home_team}</span> v{" "}
                        <span className="text-blue-600">{m.away_team}</span>{" "}
                        <span className="text-green-600 font-bold">(@{matchOdd})</span>
                      </div>

                      <div className="text-gray-700 text-sm">
                        {formatMarket(m.market, m.selection)}
                      </div>

                      <div className="text-xs text-gray-400">
                        {typeof m.probability === "number"
                          ? `${Math.round(m.probability * 100)}% confidence`
                          : "—"}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="mt-4 text-sm font-medium">
                KSh{STAKE} returns{" "}
                <span className="text-green-600 font-bold">KSh{returns}</span>
              </div>

              {/* Buttons */}
              <div className="flex gap-3 mt-4">
                <button
                  className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded"
                  onClick={() => {
                    const safeBetslip = Array.isArray(betslip) ? betslip : [];

                    const newBets = fold.matches.map((m) => {
                      const baseOdd = 1 / (m.probability || 0.01);
                      const odds = baseOdd + (baseOdd + 0.35 < 1.1 ? 0.5 : 0.35);

                      return {
                        match: {
                          id: `${m.home_team}-${m.away_team}-${m.match_time}`,
                          home_team: m.home_team,
                          away_team: m.away_team,
                          match_time: m.match_time,
                          league: m.league || "",
                        },
                        selection: getRawSelection(m.market, m.selection),
                        odds: Number(odds.toFixed(2)),
                        stake: 0,
                      };
                    });

                    // Merge bets into betslip
                    const merged = [...safeBetslip];
                    newBets.forEach((bet) => {
                      const idx = merged.findIndex(
                        (b) => b?.match?.id === bet.match.id
                      );
                      if (idx === -1) merged.push(bet);
                      else merged[idx] = { ...merged[idx], ...bet, stake: merged[idx].stake ?? bet.stake ?? 0 };
                    });

                    setBetslip(merged);
                    toast.success(`${newBets.length} matches added to betslip`);
                  }}
                >
                  BACK IT
                </button>

                <button
                  className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded"
                  onClick={() => navigate("/betslip")}
                >
                  OPEN BETSLIP
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
