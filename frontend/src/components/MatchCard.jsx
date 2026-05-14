// src/components/MatchCard.jsx
import React, { useState, memo } from "react";
import { CSSTransition } from "react-transition-group";
import "./MatchCard.css";

/* ---------- Market Label ---------- */
function formatMarketLabel(market, label) {
  if (/over|under/i.test(market)) {
    return label.replace(/goals/i, "").trim();
  }
  return label;
}

function MatchCard({
  match,
  toggleBetslip = () => {},
  isPicked = () => false,
  formatOdds = (o) => Number(o || 0).toFixed(2),
  getCountdown = () => "",
  oddsFlash = {},
}) {
  const [showMarkets, setShowMarkets] = useState(false);

  if (!match) return null;

  const id = match.match_id || match.id;
  const flash = oddsFlash?.[id] || {};

  const oddsColor = (type) => {
    if (flash[type] === "up") return "text-green-400";
    if (flash[type] === "down") return "text-red-400";
    return "text-white";
  };

  /* ---------- Normalize Keys ---------- */
  const normalizeKey = (key) => {
    if (key === "home") return "home_odds";
    if (key === "draw") return "draw_odds";
    if (key === "away") return "away_odds";
    return key;
  };

  /* ---------- H2H Markets ---------- */
  const h2hMarkets = [
    { key: "home", label: "Home", odds: match.home_odds },
    { key: "draw", label: "Draw", odds: match.draw_odds },
    { key: "away", label: "Away", odds: match.away_odds },
  ].filter((m) => m.odds);

  /* ---------- Goal Markets ---------- */
  const goalMarkets = [
    { key: "over05", label: "Over 0.5", odds: match.over05 },
    { key: "under05", label: "Under 0.5", odds: match.under05 },
    { key: "over15", label: "Over 1.5", odds: match.over15 },
    { key: "under15", label: "Under 1.5", odds: match.under15 },
    { key: "over25", label: "Over 2.5", odds: match.over25 },
    { key: "under25", label: "Under 2.5", odds: match.under25 },
    { key: "over35", label: "Over 3.5", odds: match.over35 },
    { key: "under35", label: "Under 3.5", odds: match.under35 },
  ].filter((m) => m.odds);

  /* ---------- BTTS Markets (GG / NG) ---------- */
  const bttsMarkets = [
    { key: "gg", label: "GG", odds: match.gg_odds },
    { key: "ng", label: "NG", odds: match.ng_odds },
  ].filter((m) => m.odds);

  const extraMarkets = [...goalMarkets, ...bttsMarkets];

  /* ---------- Handle Bet Click ---------- */
  const handleClick = (m) => {
    let key = m.key;
    if (key === "home") key = "home_odds";
    if (key === "draw") key = "draw_odds";
    if (key === "away") key = "away_odds";
    toggleBetslip(match, key, m.odds);
  };

  return (
    <div className="bg-slate-800 p-3 rounded-lg shadow space-y-2">
      {/* TEAMS */}
      <div className="flex justify-between items-center">
        <div>
          <div className="font-semibold text-white">{match.home_team}</div>
          <div className="text-gray-400 text-sm">{match.away_team}</div>
        </div>

        {/* H2H MARKETS */}
        <div className="flex gap-1 items-center">
          {h2hMarkets.map((m) => {
            const selected = isPicked(id, normalizeKey(m.key)); // ✅ FIXED LINE
            return (
              <button
                key={m.key}
                onClick={() => handleClick(m)}
                className={`px-2 py-1 rounded text-xs min-w-[58px] transition ${
                  selected
                    ? "bg-green-600 text-white ring-2 ring-green-400"
                    : "bg-slate-700 hover:bg-slate-600"
                }`}
              >
                <span className={oddsColor(m.key)}>
                  {formatMarketLabel(m.key, m.label)}
                </span>
                <div className="text-xs">{formatOdds(m.odds)}</div>
              </button>
            );
          })}

          {/* Toggle Extra Markets */}
          {extraMarkets.length > 0 && (
            <button
              onClick={() => setShowMarkets(!showMarkets)}
              className="px-2 py-1 rounded bg-gray-600 hover:bg-gray-500 text-xs"
            >
              {showMarkets ? "-" : `+${extraMarkets.length}`}
            </button>
          )}
        </div>
      </div>

      {/* COLLAPSIBLE MARKETS */}
      <CSSTransition in={showMarkets} timeout={200} classNames="slide" unmountOnExit>
        <div className="flex flex-wrap gap-1 mt-2">
          {extraMarkets.map((m) => {
            const selected = isPicked(id, m.key);
            return (
              <button
                key={m.key}
                onClick={() => handleClick(m)}
                className={`px-2 py-1 rounded text-xs min-w-[58px] transition ${
                  selected
                    ? "bg-green-600 text-white ring-2 ring-green-400"
                    : "bg-slate-700 hover:bg-slate-600"
                }`}
              >
                <span className={oddsColor(m.key)}>{m.label}</span>
                <div className="text-xs">{formatOdds(m.odds)}</div>
              </button>
            );
          })}
        </div>
      </CSSTransition>

      {/* FOOTER */}
      <div className="text-xs text-gray-400 flex justify-between">
        <span>{match.league}</span>
        <span>{getCountdown(match.match_time)}</span>
      </div>
    </div>
  );
}

export default memo(MatchCard);
