
import React, { useState } from "react";
import VirtualSportsbook from "../components/Virtual";   // matches + bets
import LiveLeagueTable from "../components/table";       // table
import FinishedMatches from "../components/finished";    // results

import "../styles/virtualPage.css";

export default function VirtualPage() {
  const [tab, setTab] = useState("matches");

  return (
    <div className="virtual-container">

      {/* 🔥 TOP NAV TABS */}
      <div className="virtual-tabs">
        <button
          className={tab === "matches" ? "active" : ""}
          onClick={() => setTab("matches")}
        >
          Matches
        </button>

        <button
          className={tab === "table" ? "active" : ""}
          onClick={() => setTab("table")}
        >
          Table
        </button>

        <button
          className={tab === "results" ? "active" : ""}
          onClick={() => setTab("results")}
        >
          Results
        </button>
      </div>

      {/* 🔥 CONTENT */}
      <div className="virtual-content">
        {tab === "matches" && <VirtualSportsbook />}
        {tab === "table" && <LiveLeagueTable />}
        {tab === "results" && <FinishedMatches />}
      </div>

    </div>
  );
}
