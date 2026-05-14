// src/user/MyBetsPage.jsx
import { useEffect, useState, useCallback } from "react";
import { getMyBets } from "../api/betsWallet";
import { useUser } from "../contexts/UserContext";
import TicketDrawer from "../components/TicketDrawer";
import BetCard from "../components/BetCard";
import VirtualBets from "../components/virtualbets";

export default function MyBetsPage() {
  const { reloadUser } = useUser();
  const [bets, setBets] = useState([]);
  const [filteredBets, setFilteredBets] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [tabFilter, setTabFilter] = useState("open"); // default filter is "open"
  const [viewMode, setViewMode] = useState("mybets"); // "mybets" | "virtual"

  // helper: only accept NON-empty arrays
  const pickSelections = (src) =>
    Array.isArray(src) && src.length > 0 ? src : null;

  const loadBets = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getMyBets();
      const dataCandidate = res?.success ? res?.data ?? {} : res?.data ?? res ?? {};

      let items = [];

      const mapItem = (it, type) => {
        let selections =
          pickSelections(it.selections) ||
          pickSelections(it.events) ||
          pickSelections(it.bet_selections) ||
          [];

        // Patch: if single bet has no selections, create 1 virtual selection
        if (!selections.length && (type === "single_bet" || it.match_id)) {
          selections = [
            {
              home_team: it.home_team_name || it.home_team || "Home",
              away_team: it.away_team_name || it.away_team || "Away",
              selection: it.selection || "-",
              odds: it.odds || 0,
              result: it.status || "-",
              match_time: it.match_time || null,
              ticket_id: it.ticket_id ?? it.id ?? null,
            },
          ];
        }

        return {
          ticket_id: it.ticket_id ?? it.id ?? null,
          status: String(it.status ?? it.state ?? "pending").toLowerCase(),
          created_at:
            it.created ??
            it.created_at ??
            it.createdAt ??
            it.date ??
            it.timestamp ??
            null,
          stake: it.stake ?? it.amount ?? null,
          total_odds: it.total_odds ?? null,
          potential_win: it.potential ?? it.potential_win ?? 0,
          current_cashout: it.current_cashout ?? null,
          selections,
          type: type ?? it.type ?? "betslip",
          raw: it,
        };
      };

      if (Array.isArray(dataCandidate.betslips)) {
        items.push(...dataCandidate.betslips.map((it) => mapItem(it, "betslip")));
      }

      if (Array.isArray(dataCandidate.single_bets)) {
        items.push(...dataCandidate.single_bets.map((it) => mapItem(it, "single_bet")));
      }

      if (!items.length && Array.isArray(dataCandidate)) {
        items = dataCandidate.map((it) => mapItem(it, it.type));
      }

      items.sort(
        (a, b) =>
          (new Date(b.created_at).getTime() || 0) -
          (new Date(a.created_at).getTime() || 0)
      );

      setBets(items);
    } catch (err) {
      console.error("loadBets error:", err);
      setBets([]);
    } finally {
      setLoading(false);
    }
  }, [reloadUser]);

  useEffect(() => {
    loadBets();
  }, [loadBets]);

  const formatDateKenya = (iso) => {
    if (!iso) return "-";
    try {
      const d = new Date(iso);
      const kenyaTime = new Date(d.getTime() + 3 * 60 * 60 * 1000);
      return kenyaTime.toLocaleString([], {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  const tabs = [
    { key: "all", label: "All" },
    { key: "open", label: "Open" },
    { key: "won", label: "Won" },
    { key: "lost", label: "Lost" },
    { key: "cashout", label: "Cashout" },
  ];

  useEffect(() => {
    let data = [...bets];

    if (tabFilter !== "all") {
      data = data.filter((b) => {
        const s = (b.status || "").toLowerCase();
        if (tabFilter === "open") return s === "pending" || s === "active";
        return s === tabFilter;
      });
    }

    setFilteredBets(data);
  }, [bets, tabFilter]);

  const renderMyBets = () => (
    <>
      {/* TABS */}
      <div className="flex gap-2 overflow-x-auto mb-3">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTabFilter(t.key)}
            className={`px-3 py-1 rounded-full text-xs whitespace-nowrap ${
              tabFilter === t.key
                ? t.key === "won"
                  ? "bg-green-500 text-black"
                  : t.key === "lost"
                  ? "bg-red-500 text-black"
                  : t.key === "cashout"
                  ? "bg-orange-400 text-black"
                  : "bg-yellow-400 text-black"
                : "bg-slate-800 text-gray-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && <p className="text-gray-400 text-sm">Loading...</p>}
      {!loading && filteredBets.length === 0 && (
        <p className="text-gray-400 text-sm">No bets found.</p>
      )}

      <div className="space-y-3">
        {filteredBets.map((b, index) => (
          <div
            key={b.ticket_id ?? index}
            onClick={() =>
              setSelectedTicket({
                ...b,
                selections:
                  pickSelections(b.selections) ||
                  pickSelections(b.raw?.selections) ||
                  pickSelections(b.raw?.events) ||
                  pickSelections(b.raw?.bet_selections) ||
                  (b.type === "single_bet"
                    ? [
                        {
                          home_team:
                            b.raw?.home_team_name || b.raw?.home_team || "Home",
                          away_team:
                            b.raw?.away_team_name || b.raw?.away_team || "Away",
                          selection: b.raw?.selection || "-",
                          odds: b.raw?.odds || 0,
                          result: b.raw?.status || "-",
                          match_time: b.raw?.match_time || null,
                          ticket_id: b.ticket_id,
                        },
                      ]
                    : []),
              })
            }
          >
            <BetCard b={b} index={index} formatDateKenya={formatDateKenya} />
          </div>
        ))}
      </div>

      {selectedTicket && (
        <TicketDrawer
          ticket={selectedTicket}
          onClose={() => setSelectedTicket(null)}
        />
      )}
    </>
  );

  return (
    <div className="p-3 bg-slate-900 min-h-screen text-white">
      {/* TOP MODE SWITCH */}
      <div className="flex gap-2 mb-3">
        <button
          onClick={() => setViewMode("mybets")}
          className={`px-3 py-2 rounded-full text-xs font-medium ${
            viewMode === "mybets"
              ? "bg-yellow-400 text-black"
              : "bg-slate-800 text-gray-300"
          }`}
        >
          My Bets
        </button>

        <button
          onClick={() => setViewMode("virtual")}
          className={`px-3 py-2 rounded-full text-xs font-medium ${
            viewMode === "virtual"
              ? "bg-yellow-400 text-black"
              : "bg-slate-800 text-gray-300"
          }`}
        >
          Virtual Bets
        </button>
      </div>

      {/* HEADER */}
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-lg font-semibold">
          {viewMode === "virtual" ? "Virtual Bets" : "My Bets"}
        </h2>

        {viewMode === "mybets" && (
          <button
            onClick={loadBets}
            className="text-xs bg-slate-800 px-3 py-1 rounded-full"
          >
            Refresh
          </button>
        )}
      </div>

      {/* CONTENT */}
      {viewMode === "virtual" ? <VirtualBets /> : renderMyBets()}
    </div>
  );
}
