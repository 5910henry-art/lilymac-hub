// src/components/MatchCard.jsx

import React, {
  useState,
  useMemo,
  useCallback,
  memo,
} from "react";
import { CSSTransition } from "react-transition-group";
import "./MatchCard.css";

// =========================================================
// HELPERS
// =========================================================

function formatKickoff(matchTime) {
  if (!matchTime) return "";

  const date = new Date(matchTime);

  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

// =========================================================
// MATCH CARD
// =========================================================

function MatchCard({
  match,
  toggleBetslip = () => {},
  isPicked = () => false,
  formatOdds = (o) => Number(o || 0).toFixed(2),
  getCountdown = () => "",
  oddsFlashHome = null,
  oddsFlashDraw = null,
  oddsFlashAway = null,
}) {
  const [showMarkets, setShowMarkets] = useState(false);

  const id = match?.match_id ?? match?.id;

  const leagueName =
    match?.league_name ||
    match?.competition_name ||
    match?.league ||
    "Football";

  const formattedKickoff = useMemo(() => {
    const formatted = formatKickoff(match?.match_time);

    if (formatted) {
      return formatted;
    }

    return match?.match_date || "";
  }, [match?.match_time, match?.match_date]);

  // =======================================================
  // 1X2 MARKETS
  // =======================================================

  const h2hMarkets = useMemo(() => {
    if (!match) return [];

    return [
      {
        key: "home",
        shortLabel: "1",
        teamLabel: match.home_team || "Home",
        odds: Number(match.home_odds || 0),
      },
      {
        key: "draw",
        shortLabel: "X",
        teamLabel: "Draw",
        odds: Number(match.draw_odds || 0),
      },
      {
        key: "away",
        shortLabel: "2",
        teamLabel: match.away_team || "Away",
        odds: Number(match.away_odds || 0),
      },
    ].filter((market) => market.odds > 0);
  }, [match]);

  // =======================================================
  // GOALS MARKETS
  // =======================================================

  const goalMarkets = useMemo(() => {
    if (!match) return [];

    return [
      {
        key: "over05",
        label: "Over 0.5 Goals",
        compactLabel: "O 0.5",
        odds: Number(match.over05 || 0),
      },
      {
        key: "under05",
        label: "Under 0.5 Goals",
        compactLabel: "U 0.5",
        odds: Number(match.under05 || 0),
      },
      {
        key: "over15",
        label: "Over 1.5 Goals",
        compactLabel: "O 1.5",
        odds: Number(match.over15 || 0),
      },
      {
        key: "under15",
        label: "Under 1.5 Goals",
        compactLabel: "U 1.5",
        odds: Number(match.under15 || 0),
      },
      {
        key: "over25",
        label: "Over 2.5 Goals",
        compactLabel: "O 2.5",
        odds: Number(match.over25 || 0),
      },
      {
        key: "under25",
        label: "Under 2.5 Goals",
        compactLabel: "U 2.5",
        odds: Number(match.under25 || 0),
      },
      {
        key: "over35",
        label: "Over 3.5 Goals",
        compactLabel: "O 3.5",
        odds: Number(match.over35 || 0),
      },
      {
        key: "under35",
        label: "Under 3.5 Goals",
        compactLabel: "U 3.5",
        odds: Number(match.under35 || 0),
      },
    ].filter((market) => market.odds > 0);
  }, [match]);

  // =======================================================
  // BTTS MARKETS
  // =======================================================

  const bttsMarkets = useMemo(() => {
    if (!match) return [];

    return [
      {
        key: "gg",
        label: "Both Teams To Score",
        compactLabel: "GG",
        odds: Number(match.gg || 0),
      },
      {
        key: "ng",
        label: "Both Teams Not To Score",
        compactLabel: "NG",
        odds: Number(match.ng || 0),
      },
    ].filter((market) => market.odds > 0);
  }, [match]);

  // =======================================================
  // EXTRA MARKETS
  // =======================================================

  const extraMarkets = useMemo(
    () => [...goalMarkets, ...bttsMarkets],
    [goalMarkets, bttsMarkets]
  );

  // =======================================================
  // HANDLE MARKET CLICK
  // =======================================================

  const handleClick = useCallback(
    (market) => {
      if (!match || !market) return;

      toggleBetslip(
        match,
        market.key,
        market.odds
      );
    },
    [match, toggleBetslip]
  );

  // =======================================================
  // TOGGLE MARKETS
  // =======================================================

  const handleMarketsToggle = useCallback(() => {
    setShowMarkets((previous) => !previous);
  }, []);

  // =======================================================
  // FLASH CLASSES
  // =======================================================

  const getFlashClass = useCallback((direction) => {
    if (direction === "up") {
      return "odds-up";
    }

    if (direction === "down") {
      return "odds-down";
    }

    return "";
  }, []);

  const homeFlashClass = getFlashClass(oddsFlashHome);
  const drawFlashClass = getFlashClass(oddsFlashDraw);
  const awayFlashClass = getFlashClass(oddsFlashAway);

  // =======================================================
  // SAFETY
  // =======================================================

  if (!match) {
    return null;
  }

  // =======================================================
  // RENDER
  // =======================================================

  return (
    <article className="match-card">

      {/* =================================================
          HEADER
          ================================================= */}

      <div className="match-card-top">

        <div className="match-league">
          <span className="league-name">
            {leagueName}
          </span>
        </div>

        <div className="match-time">
          {formattedKickoff}
        </div>

      </div>


      {/* =================================================
          FIXTURE
          ================================================= */}

      <div className="fixture-row">

        <div className="teams">

          {/* HOME */}

          <div className="team-row home-team-row">
            <span className="team-name">
              {match.home_team || "Home"}
            </span>
          </div>


          {/* VS */}

          <div className="fixture-status">
            <span>VS</span>
          </div>


          {/* AWAY */}

          <div className="team-row away-team-row">
            <span className="team-name">
              {match.away_team || "Away"}
            </span>
          </div>

        </div>

      </div>


      {/* =================================================
          1X2 TITLE
          ================================================= */}

      <div className="market-title-row">

        <span>1X2</span>

        <span>Match Result</span>

      </div>


      {/* =================================================
          1X2 ODDS

          IMPORTANT:
          result-market itself is the grid.

          This fixes the vertical odds problem.
          ================================================= */}

      <div className="result-market">

        {h2hMarkets.map((market) => {

          const picked = isPicked(
            id,
            market.key
          );

          let flashClass = "";

          if (market.key === "home") {
            flashClass = homeFlashClass;
          }

          if (market.key === "draw") {
            flashClass = drawFlashClass;
          }

          if (market.key === "away") {
            flashClass = awayFlashClass;
          }

          return (
            <button
              key={market.key}
              type="button"
              className={[
                "result-odd",
                picked ? "picked" : "",
                flashClass,
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={() => handleClick(market)}
              aria-pressed={picked}
            >

              <span className="result-label">
                {market.shortLabel}
              </span>

              <span className="result-team">
                {market.teamLabel}
              </span>

              <strong className="result-value">
                {formatOdds(market.odds)}
              </strong>

            </button>
          );
        })}

      </div>


      {/* =================================================
          EXTRA MARKETS
          ================================================= */}

      {extraMarkets.length > 0 && (
        <>

          {/* MORE MARKETS */}

          <button
            type="button"
            className={`markets-toggle ${
              showMarkets ? "markets-open" : ""
            }`}
            onClick={handleMarketsToggle}
            aria-expanded={showMarkets}
          >

            <span>
              {showMarkets
                ? "Hide Markets"
                : "More Markets"}
            </span>

            <span className="markets-count">
              {extraMarkets.length}
            </span>

            <span className="markets-arrow">
              {showMarkets ? "⌃" : "⌄"}
            </span>

          </button>


          {/* EXPANDED MARKETS */}

          <CSSTransition
            in={showMarkets}
            timeout={180}
            classNames="slide"
            unmountOnExit
          >

            <div className="extra-markets">

              {/* =========================================
                  GOALS
                  ========================================= */}

              {goalMarkets.length > 0 && (
                <div className="market-section">

                  <div className="market-section-title">
                    <span>Goals</span>
                  </div>

                  <div className="compact-market-grid">

                    {goalMarkets.map((market) => {

                      const picked = isPicked(
                        id,
                        market.key
                      );

                      return (
                        <button
                          key={market.key}
                          type="button"
                          className={[
                            "compact-market",
                            picked ? "picked" : "",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          onClick={() =>
                            handleClick(market)
                          }
                          aria-pressed={picked}
                        >

                          <span className="compact-label">
                            {market.compactLabel}
                          </span>

                          <strong>
                            {formatOdds(market.odds)}
                          </strong>

                        </button>
                      );
                    })}

                  </div>

                </div>
              )}


              {/* =========================================
                  BTTS
                  ========================================= */}

              {bttsMarkets.length > 0 && (
                <div className="market-section">

                  <div className="market-section-title">
                    <span>
                      Both Teams To Score
                    </span>
                  </div>

                  <div className="compact-market-grid btts-grid">

                    {bttsMarkets.map((market) => {

                      const picked = isPicked(
                        id,
                        market.key
                      );

                      return (
                        <button
                          key={market.key}
                          type="button"
                          className={[
                            "compact-market",
                            picked ? "picked" : "",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          onClick={() =>
                            handleClick(market)
                          }
                          aria-pressed={picked}
                        >

                          <span className="compact-label">
                            {market.compactLabel}
                          </span>

                          <strong>
                            {formatOdds(market.odds)}
                          </strong>

                        </button>
                      );
                    })}

                  </div>

                </div>
              )}

            </div>

          </CSSTransition>

        </>
      )}

    </article>
  );
}


// =========================================================
// EXPORT
//
// IMPORTANT:
// Do NOT use the old custom areEqual().
// isPicked changes when the betslip changes, so the card
// must be allowed to re-render.
// =========================================================

export default memo(MatchCard);
