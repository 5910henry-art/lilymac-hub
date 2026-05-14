// src/components/BetCard.jsx
import React from "react";

export default function BetCard({ b, index, formatDateKenya }) {
  const ticketId = b.ticket_id ?? index;

  // Status from DB (already lowercase "won", "lost", etc.)
  const status = (b.status || "pending").toLowerCase();

  // Dot colors for status
  const statusDot = {
    won: "bg-emerald-400",
    lost: "bg-red-500",
    cashed_out: "bg-emerald-400",
    pending: "bg-yellow-400",
    active: "bg-yellow-400",
  };

  // Text colors for status (applied to a <span> to avoid parent override)
  const statusTextColor = {
    won: "bg-emerald-500/20 text-emerald-300",
    lost: "text-red-500",
    cashed_out: "bg-emerald-500/20 text-emerald-300",
    pending: "text-yellow-400",
    active: "text-yellow-400",
  };

  const formatNumber = (n) => {
    const num = Number(n);
    return Number.isFinite(num) ? num.toFixed(2) : "0.00";
  };

  return (
    <div className="bg-slate-800 rounded-xl px-3 py-2 shadow-sm hover:bg-slate-700 transition cursor-pointer">
      {/* ROW */}
      <div className="flex justify-between items-center">
        {/* LEFT */}
        <div className="flex flex-col">
          <div className="flex items-center gap-1">
            <span className="text-xs text-gray-400">#{ticketId}</span>
            <div className={`w-2 h-2 rounded-full ${statusDot[status]}`} />
          </div>
          <span className="text-[11px] text-gray-500">
            {formatDateKenya(b.created_at)}
          </span>
        </div>

        {/* RIGHT */}
        <div className="text-right">
          <p className="text-sm font-semibold leading-tight text-white">
            KES {b.current_cashout ? formatNumber(b.current_cashout) : b.potential_win || b.stake || 0}
          </p>
          <p className="text-[11px] font-semibold">
            <span className={statusTextColor[status]}>
              {status.toLowerCase()}
            </span>
          </p>
        </div>
      </div>

      {/* FOOTER SMALL INFO */}
      <div className="mt-1 flex justify-between text-[11px] text-gray-400">
        <span>{b.selections?.length || 0} picks</span>
        {b.total_odds && <span>{b.total_odds} odds</span>}
      </div>
    </div>
  );
}
