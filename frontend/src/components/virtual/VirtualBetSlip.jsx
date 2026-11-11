import React from "react";

export default function VirtualBetSlip({
  bets,
  stake,
  setStake,
  inputRef,
  combinedOdds,
  potentialWin,
  placeBet,
  isOffline,
}) {
  if (!bets.length) {
    return null;
  }

  return (
    <div className="betSlipPanel">
      <div
        style={{
          marginBottom: "10px",
          fontWeight: "bold",
        }}
      >
        Bet Slip ({bets.length})
      </div>

      {bets.map((bet) => (
        <div
          key={bet.id}
          style={{
            display: "flex",
            justifyContent:
              "space-between",
            gap: "10px",
            padding: "6px 0",
            fontSize: "12px",
          }}
        >
          <span>
            {bet.home} vs {bet.away}
            <br />
            <strong>
              {bet.selection}
            </strong>
          </span>

          <strong>
            {Number(
              bet.odd
            ).toFixed(2)}
          </strong>
        </div>
      ))}

      <input
        ref={inputRef}
        type="number"
        inputMode="decimal"
        placeholder="Stake"
        value={stake}
        onChange={(event) =>
          setStake(
            event.target.value
          )
        }
        min="1"
        step="any"
        style={{
          width: "100%",
          padding: "10px",
          fontSize: "16px",
          color: "#000",
          background: "#fff",
          border: "1px solid #ccc",
          borderRadius: "6px",
          outline: "none",
        }}
      />

      <div>
        Total Odds:{" "}
        <strong>
          {combinedOdds}
        </strong>
      </div>

      <div>
        Potential Win:{" "}
        <strong>
          {potentialWin}
        </strong>
      </div>

      <button
        type="button"
        onClick={placeBet}
        disabled={isOffline}
        style={{
          width: "100%",
          padding: "12px",
          marginTop: "10px",
          border: "none",
          borderRadius: "8px",
          fontWeight: "bold",
          color: "#000",
          background: isOffline
            ? "#94a3b8"
            : "#22c55e",
          opacity: isOffline
            ? 0.7
            : 1,
          cursor: isOffline
            ? "not-allowed"
            : "pointer",
        }}
      >
        {isOffline
          ? "No Connection"
          : "Place Bet"}
      </button>
    </div>
  );
}
