// src/components/TicketDrawer.jsx
import { useState } from "react";
import { cashout } from "../api/betsWallet";
import { useUser } from "../contexts/UserContext";
import { toast } from "react-hot-toast";

export default function TicketDrawer({ ticket, onClose }) {
  const { reloadUser, setBalance } = useUser() || {};
  const [cashoutLoading, setCashoutLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const formatNumber = (n) => {
    const num = Number(n);
    return Number.isFinite(num) ? num.toFixed(2) : "0.00";
  };

  const formatDateKenya = (dateValue) => {
    if (!dateValue) return "";
    const date = new Date(dateValue);
    return date.toLocaleString("en-KE", {
      timeZone: "Africa/Nairobi",
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const handleCashout = async () => {
    const betId = ticket?.id ?? ticket?.ticket_id;
    if (!ticket || !betId || cashoutLoading) return;

    if (ticket.status?.toLowerCase() !== "pending" || !ticket.current_cashout) {
      toast.error("Cashout not available");
      return;
    }

    try {
      setCashoutLoading(true);
      const res = await cashout(betId);

      if (res?.success || res?.msg === "cashed out") {
        toast.success(
          `Cashout successful: KES ${formatNumber(res.amount ?? ticket.current_cashout)}`
        );

        const newBalance = res?.balance ?? ticket.balance;
        if (newBalance != null && typeof setBalance === "function") {
          setBalance(Number(newBalance));
        }

        await reloadUser?.();
      } else {
        toast.error(res?.error || res?.message || "Cashout failed");
      }
    } catch (err) {
      console.error("Cashout error", err);
      toast.error("Cashout failed");
    } finally {
      setCashoutLoading(false);
    }
  };

  if (!ticket) return null;

  const selections = Array.isArray(ticket.selections) ? ticket.selections : [];

  const totalPicks = selections.length;

  const statusLabel = (() => {
    const s = String(ticket.status || "").toLowerCase();
    if (s === "pending") return "Open";
    if (s === "won") return "Won";
    if (s === "lost") return "Lost";
    if (s === "cashed_out") return "Cashed Out";
    return ticket.status || "Open";
  })();

  const statusBadgeClass = (() => {
    const s = String(ticket.status || "").toLowerCase();
    if (s === "won") return "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/20";
    if (s === "lost") return "bg-red-500/15 text-red-300 ring-1 ring-red-500/20";
    if (s === "cashed_out") return "bg-blue-500/15 text-blue-300 ring-1 ring-blue-500/20";
    return "bg-yellow-500/15 text-yellow-300 ring-1 ring-yellow-500/20";
  })();

  const statusColor = {
    won: "text-green-400",
    lost: "text-red-400",
    cashout: "text-blue-400",
    pending: "text-yellow-400",
    active: "text-yellow-400",
  };

  const statusDot = {
    won: "bg-green-400",
    lost: "bg-red-400",
    cashout: "bg-blue-400",
    pending: "bg-yellow-400",
    active: "bg-yellow-400",
  };

  const marketLabel = (s) => {
    const raw = String(s?.market_name ?? s?.market ?? s?.type ?? s?.selection ?? "").toLowerCase();

    if (raw.includes("home_odds") || raw === "home") return "Home";
    if (raw.includes("away_odds") || raw === "away") return "Away";
    if (raw.includes("draw_odds") || raw === "draw") return "Draw";

    if (raw.includes("over")) {
      const m = raw.match(/(\d+)(?:\D*?(\d))?$/);
      if (m) {
        const whole = m[1];
        const dec = m[2] ?? "5";
        return `Over ${whole}.${dec}`;
      }
      return "Over";
    }

    if (raw.includes("under")) {
      const m = raw.match(/(\d+)(?:\D*?(\d))?$/);
      if (m) {
        const whole = m[1];
        const dec = m[2] ?? "5";
        return `Under ${whole}.${dec}`;
      }
      return "Under";
    }

    if (raw.includes("gg") || raw.includes("btts")) return "BTTS";
    if (raw.includes("ng") || raw.includes("no_btts")) return "No BTTS";

    return s?.selection ?? "-";
  };

  const ftLabel = (s) => {
    const pick = String(s?.selection ?? s?.market_name ?? s?.market ?? s?.type ?? "").toLowerCase();
    const scoreRaw = s?.score ?? s?.full_time_score ?? "";

    if (!scoreRaw || scoreRaw === "-" || String(scoreRaw).trim() === "") return "Pending";

    let homeGoals = 0;
    let awayGoals = 0;

    if (String(scoreRaw).includes("-")) {
      const parts = String(scoreRaw)
        .split("-")
        .map((x) => parseInt(x, 10));

      if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
        homeGoals = parts[0];
        awayGoals = parts[1];
      } else {
        return "Pending";
      }
    } else {
      return "Pending";
    }

    const totalGoals = homeGoals + awayGoals;

    if (["home", "home_odds"].includes(pick)) {
      return homeGoals > awayGoals ? "Home" : homeGoals < awayGoals ? "Away" : "Draw";
    }

    if (["away", "away_odds"].includes(pick)) {
      return awayGoals > homeGoals ? "Away" : awayGoals < homeGoals ? "Home" : "Draw";
    }

    if (["draw", "draw_odds"].includes(pick)) {
      return homeGoals === awayGoals ? "Draw" : homeGoals > awayGoals ? "Home" : "Away";
    }

    if (pick.includes("over") || pick.includes("under")) {
      let normalized = pick.replace(/\b(over|under)(\d)(\d)\b/g, "$1 $2.$3");
      const match = normalized.match(/(\d+(\.\d+)?)/);
      if (match) {
        const line = parseFloat(match[0]);
        if (normalized.includes("over")) return totalGoals > line ? `Over ${line}` : `Under ${line}`;
        if (normalized.includes("under")) return totalGoals < line ? `Under ${line}` : `Over ${line}`;
      }
    }

    if (pick.includes("btts") || pick.includes("gg")) {
      return homeGoals > 0 && awayGoals > 0 ? "Yes" : "No";
    }

    if (pick.includes("no_btts") || pick.includes("ng")) {
      return homeGoals > 0 && awayGoals > 0 ? "No" : "Yes";
    }

    return "-";
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm">
      <div className="w-full sm:w-[420px] bg-slate-900 text-white overflow-y-auto text-sm shadow-2xl">
        {/* Header */}
        <div className="sticky top-0 z-10 border-b border-white/5 bg-slate-900/95 backdrop-blur px-4 py-3 flex justify-between items-start">
          <div className="min-w-0">
            <div className="font-semibold text-base truncate">
              Ticket #{ticket.ticket_id ?? ticket.id}
            </div>
            <div className="mt-0.5 text-[11px] text-slate-400">
              {ticket.created_at
                ? `Prematch bet placed at ${formatDateKenya(ticket.created_at)}`
                : ""}
            </div>
          </div>

          <button
            onClick={onClose}
            className="ml-3 rounded-full bg-white/5 px-3 py-1.5 text-sm text-slate-200 transition hover:bg-white/10"
          >
            ✕
          </button>
        </div>

        <div className="px-4 py-3">
          {/* Summary */}
          <div className="rounded-2xl bg-white/5 p-3 ring-1 ring-white/5 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <span
                className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${statusBadgeClass}`}
              >
                {statusLabel}
              </span>
              <span className="text-xs text-slate-400">
                Picks: {totalPicks}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-xl bg-slate-950/60 p-3">
                <div className="text-[11px] uppercase tracking-wide text-slate-400">Amount</div>
                <div className="mt-1 font-semibold text-white">KES {formatNumber(ticket.stake)}</div>
              </div>

              <div className="rounded-xl bg-slate-950/60 p-3">
                <div className="text-[11px] uppercase tracking-wide text-slate-400">
                  Possible Payout
                </div>
                <div className="mt-1 font-semibold text-white">
                  KES {formatNumber(ticket.potential_win ?? ticket.potential)}
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between text-xs text-slate-300">
              <span>Total Odds</span>
              <span className="font-medium text-white">{formatNumber(ticket.total_odds)}</span>
            </div>

            {ticket.status?.toLowerCase() === "pending" && ticket.current_cashout && (
              <div className="flex items-center justify-between rounded-xl bg-emerald-500/10 px-3 py-2 text-sm">
                <span className="font-medium text-emerald-200">Cashout</span>
                <span className="font-semibold text-emerald-300">
                  KES {formatNumber(ticket.current_cashout)}
                </span>
              </div>
            )}
          </div>

          {/* Cashout */}
          {ticket.status?.toLowerCase() === "pending" && ticket.current_cashout && (
            <button
              onClick={handleCashout}
              disabled={cashoutLoading}
              className="mt-3 w-full rounded-xl bg-emerald-500 px-4 py-2.5 text-sm font-semibold text-black transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {cashoutLoading
                ? "Processing..."
                : `Request Cashout KES ${formatNumber(ticket.current_cashout)}`}
            </button>
          )}

          {/* Selections */}
          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                Events ({selections.length})
              </span>
              <button
                onClick={() => setCollapsed(!collapsed)}
                className="rounded-full bg-white/5 px-3 py-1 text-xs text-slate-200 transition hover:bg-white/10"
              >
                {collapsed ? "Expand" : "Collapse"}
              </button>
            </div>

            {!collapsed && (
              <div className="space-y-2">
                {selections.map((s, i) => {
                  const home = s.home_team ?? s.home_team_name ?? "Home";
                  const away = s.away_team ?? s.away_team_name ?? "Away";
                  const odds = s.odds ?? 0;
                  const score = s.score ?? "-";
                  const pick = marketLabel(s);
                  const ft = ftLabel(s);

                  const outcomeRaw = String(s.status || "").toLowerCase();
                  const outcome = (() => {
                    if (outcomeRaw === "won") return "won";
                    if (outcomeRaw === "lost") return "lost";
                    if (outcomeRaw === "cashout") return "cashout";
                    if (outcomeRaw === "tie" || outcomeRaw === "draw") return "pending";
                    return "pending";
                  })();

                  return (
                    <div
                      key={i}
                      className="bg-slate-800 rounded-xl px-3 py-2 shadow-sm hover:bg-slate-700 transition cursor-pointer"
                    >
                      {/* ROW */}
                      <div className="flex justify-between items-center">
                        {/* LEFT */}
                        <div className="flex flex-col min-w-0">
                          <div className="flex items-center gap-1">
                            <span className="text-xs text-gray-400">#{i + 1}</span>
                            <div className={`w-2 h-2 rounded-full ${statusDot[outcome]}`} />
                          </div>
                          <span className="text-[11px] text-gray-500 truncate max-w-[180px]">
                            {home} vs {away}
                          </span>
                        </div>

                        {/* RIGHT */}
                        <div className="text-right">
                          <p className="text-sm font-semibold leading-tight">
                            {pick}
                          </p>
                          <p className={`text-[11px] ${statusColor[outcome]}`}>
                            {outcome.toUpperCase()}
                          </p>
                        </div>
                      </div>

                      {/* FOOTER SMALL INFO */}
                      <div className="mt-1 flex justify-between text-[11px] text-gray-400">
                        <span>Odds {odds}</span>
                        <span>Score {score}</span>
                        <span>FT {ft}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
