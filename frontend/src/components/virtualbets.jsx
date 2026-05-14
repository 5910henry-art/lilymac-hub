import React, { useEffect, useState, useMemo } from "react";
import VirtualAPI from "../api/virtualAPI";

export default function MyBets() {
  const [bets, setBets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("OPEN");
  const [expandedTickets, setExpandedTickets] = useState({});

  useEffect(() => {
    const stopPolling = VirtualAPI.liveBets(
      (data) => {
        setBets(Array.isArray(data) ? data : []);
        setLoading(false);
      },
      2000
    );
    return () => stopPolling && stopPolling();
  }, []);

  const tabs = ["ALL", "OPEN", "WON", "LOST", "MIXED"];

  const filteredBets = useMemo(() => {
    return bets.filter(
      (t) => filter === "ALL" || (t.status || "OPEN").toUpperCase() === filter
    );
  }, [bets, filter]);

  const toggleTicket = (id) => {
    setExpandedTickets((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const formatNumber = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(2) : "-";
  };

  const computeTotalOdds = (ticket) => {
    return (ticket.selections || []).reduce((acc, s) => {
      const o = Number(s.odds);
      return o > 0 ? acc * o : acc;
    }, 1);
  };

  const computeWin = (ticket, odds) => {
    const stake = Number(ticket.stake);
    return stake > 0 && odds > 0 ? stake * odds : null;
  };

  const statusStyle = {
    WON: "bg-emerald-500/20 text-emerald-300",
    LOST: "bg-red-500/20 text-red-300",
    MIXED: "bg-amber-500/20 text-amber-300",
    OPEN: "bg-yellow-500/20 text-yellow-300",
  };

  if (loading)
    return (
      <div className="p-4 text-center text-gray-400 text-sm">
        Loading bets...
      </div>
    );

  if (!bets.length)
    return (
      <div className="p-4 text-center text-gray-400 text-sm">
        No bets yet.
      </div>
    );

  return (
    <div className="p-3 bg-slate-900 min-h-screen text-white">
      
      {/* FILTER TABS */}
      <div className="flex gap-2 overflow-x-auto mb-3">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setFilter(t)}
            className={`px-3 py-1 text-xs rounded-full whitespace-nowrap ${
              filter === t
                ? "bg-yellow-400 text-black"
                : "bg-slate-800 text-gray-300"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* LIST */}
      <div className="space-y-2">
        {filteredBets.map((ticket) => {
          const status = (ticket.status || "OPEN").toUpperCase();
          const isOpen = expandedTickets[ticket.ticket_id];
          const odds = computeTotalOdds(ticket);
          const win = computeWin(ticket, odds);

          return (
            <div
              key={ticket.ticket_id}
              className="bg-slate-800 rounded-xl px-3 py-2"
            >
              {/* HEADER */}
              <div className="flex justify-between items-center">
                
                <div className="min-w-0">
                  <p className="text-xs text-gray-400">
                    #{ticket.ticket_id}
                  </p>
                  <p className="text-[11px] text-gray-500">
                    Stake: {formatNumber(ticket.stake)}
                  </p>
                </div>

                <div className="text-right">
                  <p className="text-xs font-semibold">
                    {win ? formatNumber(win) : "-"}
                  </p>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${statusStyle[status]}`}
                  >
                    {status === "WON" ? "✔ WON" : status}
                  </span>
                </div>
              </div>

              {/* SMALL INFO */}
              <div className="flex justify-between text-[10px] text-gray-400 mt-1">
                <span>{ticket.selections?.length || 0} picks</span>
                <span>{odds > 1 ? formatNumber(odds) : "-"}</span>
              </div>

              {/* TOGGLE */}
              <button
                onClick={() => toggleTicket(ticket.ticket_id)}
                className="text-[10px] text-blue-400 mt-1"
              >
                {isOpen ? "Hide" : "Show"}
              </button>

              {/* SELECTIONS */}
              {isOpen && (
                <div className="flex gap-2 mt-2 overflow-x-auto">
                  {ticket.selections.map((s, i) => {
                    const sStatus = (s.status || "").toUpperCase();

                    return (
                      <div
                        key={i}
                        className="min-w-[120px] bg-slate-700 rounded-lg p-2 text-[10px]"
                      >
                        <p className="truncate">
                          {s.home_team} vs {s.away_team}
                        </p>
                        <p className="text-gray-400 truncate">
                          {s.selection}
                        </p>
                        <p>Odd: {formatNumber(s.odds)}</p>

                        <span
                          className={`mt-1 inline-block px-1 py-0.5 rounded ${
                            sStatus === "WON"
                              ? "bg-emerald-500/20 text-emerald-300"
                              : sStatus === "LOST"
                              ? "bg-red-500/20 text-red-300"
                              : "bg-slate-600 text-gray-300"
                          }`}
                        >
                          {sStatus || "OPEN"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
