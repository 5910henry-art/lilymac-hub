import React from "react";

export default function VirtualRounds({
  rounds,
  selectedRound,
  highlightedRound,
  getStatus,
  getCountdown,
  normalizeId,
  parseUTCtoLocal,
  onSelect,
}) {
  return (
    <div className="roundTabs">
      {rounds.map((round) => {
        const roundId =
          round.round ?? round.id;

        const status =
          getStatus(round);

        const selected =
          normalizeId(
            highlightedRound
          ) ===
          normalizeId(roundId);

        return (
          <button
            key={normalizeId(roundId)}
            type="button"
            className={`
              ${
                status === "RUNNING"
                  ? "liveRound"
                  : ""
              }
              ${
                status === "OPEN"
                  ? "preLiveRound"
                  : ""
              }
              ${
                selected
                  ? "selectedRound"
                  : ""
              }
            `}
            onClick={() =>
              onSelect(roundId)
            }
          >
            <div>
              {round.open_time
                ? parseUTCtoLocal(
                    round.open_time
                  ).toLocaleTimeString(
                    "en-KE",
                    {
                      hour: "2-digit",
                      minute: "2-digit",
                    }
                  )
                : `Round ${roundId}`}
            </div>

            <small>
              {getCountdown(round)}
            </small>
          </button>
        );
      })}
    </div>
  );
}
