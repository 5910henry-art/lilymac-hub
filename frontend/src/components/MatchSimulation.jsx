import React from "react";

export default function MatchSimulation({ home, away }) {
  return (
    <div className="match-sim">

      <div className="team">{home}</div>

      <div className="pitch">
        ⚽
      </div>

      <div className="team">{away}</div>

    </div>
  );
}
