import React from "react";

import {
  getEventKey,
  formatEvent,
  isLiveMatch,
  parseScore,
} from "../../utils/virtualHelpers";

export default function VirtualMatch({
  match,
  odds,
  flash,
  marketButtons,
  isSelected,
  onSelectBet,
  getTimer,
  onOpen,
}) {
  const live = isLiveMatch(match);
  const score = parseScore(match);

  const events =
    match.events || [];

  return (
    <div
      className={`matchRow ${
        live ? "liveMatch" : ""
      }`}
      onClick={() =>
        onOpen(match.id)
      }
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (
          event.key === "Enter" ||
          event.key === " "
        ) {
          onOpen(match.id);
        }
      }}
    >
      {/* TEAM / EVENTS AREA */}

      <div className="teams">
        <div>{match.home}</div>

        <div>{match.away}</div>

        {live &&
          events.length > 0 && (
            <div
              className="liveTicker"
              style={{
                marginTop: "8px",
                display: "flex",
                flexDirection: "column",
                gap: "4px",
              }}
            >
              {events
                .slice(-5)
                .reverse()
                .map(
                  (event, index) => (
                    <div
                      key={getEventKey(
                        event,
                        index
                      )}
                      style={{
                        fontSize: "11px",
                        lineHeight: "1.4",
                      }}
                    >
                      <span className="liveEventText">
                          {formatEvent(event)}
                       </span>
                    </div>
                  )
                )}
            </div>
          )}

        {live && (
          <small>
            {getTimer(match)}
          </small>
        )}
      </div>

      {/* SCORE / ODDS AREA */}

      <div className="oddsRow">
        {live ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              minWidth: "75px",
              padding: "8px",
              borderRadius: "8px",
              color: "#fff",
              fontWeight: "bold",
              background:
                "rgba(34,197,94,0.10)",
              fontSize: "13px",
            }}
          >
            {score.home} - {score.away}
          </div>
        ) : (
          marketButtons.map(
            (button) => {
              const odd = button.odd;

              const flashClass =
                flash[button.key]
                  ? `flash-${flash[button.key]}`
                  : "";

              const selectedClass =
                isSelected(
                  match.id,
                  button.key
                )
                  ? "selected"
                  : "";

              if (
                odd === undefined ||
                odd === null
              ) {
                return (
                  <button
                    key={button.key}
                    type="button"
                    className="oddBtn disabled"
                    disabled
                  >
                    <span>
                      {button.label}
                    </span>

                    <b>—</b>
                  </button>
                );
              }

              return (
                <button
                  key={button.key}
                  type="button"
                  className={`oddBtn ${flashClass} ${selectedClass}`}
                  onClick={(event) => {
                    event.stopPropagation();

                    onSelectBet(
                      match,
                      button.key,
                      odd
                    );
                  }}
                >
                  <span>
                    {button.label}
                  </span>

                  <b>
                    {Number(odd).toFixed(2)}
                  </b>
                </button>
              );
            }
          )
        )}
      </div>
    </div>
  );
}
