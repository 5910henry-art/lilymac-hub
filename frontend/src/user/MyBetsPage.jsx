// src/user/MyBetsPage.jsx

import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  RefreshCw,
  Wallet,
  Ticket,
  ChevronRight,
} from "lucide-react";

import { getMyBets } from "../api/betsWallet";
import { useUser } from "../contexts/UserContext";
import TicketDrawer from "../components/TicketDrawer";
import BetCard from "../components/BetCard";
import VirtualBets from "../components/virtualbets";

export default function MyBetsPage() {
  const navigate = useNavigate();
  const { reloadUser } = useUser();

  const [bets, setBets] = useState([]);
  const [filteredBets, setFilteredBets] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedTicket, setSelectedTicket] = useState(null);

  const [tabFilter, setTabFilter] = useState("open");
  const [viewMode, setViewMode] = useState("mybets");

  // =========================================================
  // HELPERS
  // =========================================================

  const pickSelections = (src) =>
    Array.isArray(src) && src.length > 0 ? src : null;

  const normalizeStatus = (status) =>
    String(status ?? "")
      .trim()
      .toLowerCase()
      .replace(/[\s-]+/g, "_");

  /*
   * Internal cash-out systems can return different status names.
   *
   * We intentionally support all of these:
   *   cashout
   *   cash_out
   *   cashed_out
   *   cashedout
   *
   * This means the Cashout tab will correctly display
   * bets that have already been internally cashed out.
   */
  const isCashoutStatus = (status) => {
    const normalized = normalizeStatus(status);

    return (
      normalized === "cashout" ||
      normalized === "cash_out" ||
      normalized === "cashed_out" ||
      normalized === "cashedout"
    );
  };

  // =========================================================
  // LOAD BETS
  // =========================================================

  const loadBets = useCallback(async () => {
    try {
      setLoading(true);

      const res = await getMyBets();

      const dataCandidate = res?.success
        ? res?.data ?? {}
        : res?.data ?? res ?? {};

      let items = [];

      const mapItem = (it, type) => {
        let selections =
          pickSelections(it?.selections) ||
          pickSelections(it?.events) ||
          pickSelections(it?.bet_selections) ||
          [];

        /*
         * Single bets sometimes come without a selections array.
         * Build a compatible selection so TicketDrawer/BetCard
         * continue working normally.
         */
        if (
          !selections.length &&
          (type === "single_bet" || it?.match_id)
        ) {
          selections = [
            {
              home_team:
                it?.home_team_name ||
                it?.home_team ||
                "Home",

              away_team:
                it?.away_team_name ||
                it?.away_team ||
                "Away",

              selection: it?.selection || "-",

              odds: it?.odds ?? 0,

              result: it?.status || "-",

              match_time: it?.match_time || null,

              ticket_id:
                it?.ticket_id ??
                it?.id ??
                null,
            },
          ];
        }

        return {
          ticket_id:
            it?.ticket_id ??
            it?.id ??
            null,

          status: normalizeStatus(
            it?.status ??
              it?.state ??
              "pending"
          ),

          created_at:
            it?.created ??
            it?.created_at ??
            it?.createdAt ??
            it?.date ??
            it?.timestamp ??
            null,

          stake:
            it?.stake ??
            it?.amount ??
            null,

          total_odds:
            it?.total_odds ??
            null,

          potential_win:
            it?.potential ??
            it?.potential_win ??
            0,

          current_cashout:
            it?.current_cashout ??
            null,

          selections,

          type:
            type ??
            it?.type ??
            "betslip",

          raw: it,
        };
      };

      // -------------------------------------------------------
      // BETSLIPS
      // -------------------------------------------------------

      if (Array.isArray(dataCandidate?.betslips)) {
        items.push(
          ...dataCandidate.betslips.map((it) =>
            mapItem(it, "betslip")
          )
        );
      }

      // -------------------------------------------------------
      // SINGLE BETS
      // -------------------------------------------------------

      if (Array.isArray(dataCandidate?.single_bets)) {
        items.push(
          ...dataCandidate.single_bets.map((it) =>
            mapItem(it, "single_bet")
          )
        );
      }

      // -------------------------------------------------------
      // FALLBACK ARRAY
      // -------------------------------------------------------

      if (
        !items.length &&
        Array.isArray(dataCandidate)
      ) {
        items = dataCandidate.map((it) =>
          mapItem(it, it?.type)
        );
      }

      // -------------------------------------------------------
      // NEWEST FIRST
      // -------------------------------------------------------

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
  }, []);

  // =========================================================
  // INITIAL LOAD
  // =========================================================

  useEffect(() => {
    loadBets();
  }, [loadBets]);

  // =========================================================
  // FORMAT KENYA DATE
  // =========================================================

  const formatDateKenya = (iso) => {
    if (!iso) return "-";

    try {
      const d = new Date(iso);

      if (Number.isNaN(d.getTime())) {
        return String(iso);
      }

      return d.toLocaleString("en-KE", {
        timeZone: "Africa/Nairobi",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
    } catch {
      return iso;
    }
  };

  // =========================================================
  // FILTER TABS
  // =========================================================

  const tabs = [
    {
      key: "all",
      label: "All",
    },
    {
      key: "open",
      label: "Open",
    },
    {
      key: "won",
      label: "Won",
    },
    {
      key: "lost",
      label: "Lost",
    },
    {
      key: "cashout",
      label: "Cashout",
    },
  ];

  useEffect(() => {
    let data = [...bets];

    if (tabFilter !== "all") {
      data = data.filter((bet) => {
        const status = normalizeStatus(
          bet?.status
        );

        // ---------------------------------------------------
        // OPEN
        // ---------------------------------------------------

        if (tabFilter === "open") {
          return (
            status === "pending" ||
            status === "active"
          );
        }

        // ---------------------------------------------------
        // CASHOUT
        // ---------------------------------------------------

        if (tabFilter === "cashout") {
          return isCashoutStatus(status);
        }

        // ---------------------------------------------------
        // WON / LOST
        // ---------------------------------------------------

        return status === tabFilter;
      });
    }

    setFilteredBets(data);
  }, [bets, tabFilter]);

  // =========================================================
  // OPEN TICKET
  // =========================================================

  const openTicket = (bet) => {
    const selections =
      pickSelections(bet?.selections) ||
      pickSelections(bet?.raw?.selections) ||
      pickSelections(bet?.raw?.events) ||
      pickSelections(bet?.raw?.bet_selections) ||
      (bet?.type === "single_bet"
        ? [
            {
              home_team:
                bet?.raw?.home_team_name ||
                bet?.raw?.home_team ||
                "Home",

              away_team:
                bet?.raw?.away_team_name ||
                bet?.raw?.away_team ||
                "Away",

              selection:
                bet?.raw?.selection || "-",

              odds:
                bet?.raw?.odds ?? 0,

              result:
                bet?.raw?.status || "-",

              match_time:
                bet?.raw?.match_time ||
                null,

              ticket_id:
                bet?.ticket_id ?? null,
            },
          ]
        : []);

    setSelectedTicket({
      ...bet,
      selections,
    });
  };

  // =========================================================
  // RENDER MY BETS
  // =========================================================

  const renderMyBets = () => (
    <>
      {/* ===================================================
          FILTER TABS
      ==================================================== */}

      <div className="mb-4 overflow-x-auto pb-1">
        <div className="flex min-w-max gap-2">
          {tabs.map((tab) => {
            const active =
              tabFilter === tab.key;

            let activeClass =
              "bg-yellow-400 text-black shadow-sm";

            if (tab.key === "won") {
              activeClass =
                "bg-emerald-500 text-white shadow-sm";
            }

            if (tab.key === "lost") {
              activeClass =
                "bg-red-500 text-white shadow-sm";
            }

            if (tab.key === "cashout") {
              activeClass =
                "bg-orange-500 text-white shadow-sm";
            }

            return (
              <button
                key={tab.key}
                type="button"
                onClick={() =>
                  setTabFilter(tab.key)
                }
                className={`
                  rounded-full
                  px-4
                  py-2
                  text-xs
                  font-semibold
                  whitespace-nowrap
                  transition-all
                  duration-200
                  active:scale-95
                  ${
                    active
                      ? activeClass
                      : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                  }
                `}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* ===================================================
          RESULTS SUMMARY
      ==================================================== */}

      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-white">
            {tabFilter === "all"
              ? "All bets"
              : tabs.find(
                  (t) => t.key === tabFilter
                )?.label || "Bets"}
          </p>

          <p className="mt-0.5 text-[11px] text-slate-500">
            {filteredBets.length}{" "}
            {filteredBets.length === 1
              ? "bet"
              : "bets"}
          </p>
        </div>

        {tabFilter === "cashout" && (
          <span
            className="
              rounded-full
              bg-orange-500/10
              px-3
              py-1.5
              text-[10px]
              font-semibold
              text-orange-400
            "
          >
            Cashed out
          </span>
        )}
      </div>

      {/* ===================================================
          LOADING
      ==================================================== */}

      {loading && (
        <div
          className="
            flex
            items-center
            justify-center
            gap-2
            rounded-2xl
            border
            border-slate-800
            bg-slate-800/50
            px-4
            py-8
            text-sm
            text-slate-400
          "
        >
          <RefreshCw
            size={16}
            className="animate-spin"
          />

          Loading bets...
        </div>
      )}

      {/* ===================================================
          EMPTY
      ==================================================== */}

      {!loading &&
        filteredBets.length === 0 && (
          <div
            className="
              rounded-2xl
              border
              border-slate-800
              bg-slate-800/40
              px-5
              py-10
              text-center
            "
          >
            <div
              className="
                mx-auto
                mb-3
                flex
                h-12
                w-12
                items-center
                justify-center
                rounded-2xl
                bg-slate-800
              "
            >
              <Ticket
                size={21}
                className="text-slate-500"
              />
            </div>

            <p className="text-sm font-semibold text-slate-300">
              No bets found
            </p>

            <p className="mt-1 text-xs text-slate-500">
              There are no bets in this category yet.
            </p>
          </div>
        )}

      {/* ===================================================
          BET LIST
      ==================================================== */}

      <div className="space-y-3">
        {filteredBets.map((bet, index) => (
          <button
            key={
              bet?.ticket_id ??
              `${bet?.type}-${index}`
            }
            type="button"
            onClick={() =>
              openTicket(bet)
            }
            className="
              block
              w-full
              text-left
              transition
              focus:outline-none
              focus:ring-2
              focus:ring-yellow-400/30
              rounded-2xl
            "
          >
            <BetCard
              b={bet}
              index={index}
              formatDateKenya={
                formatDateKenya
              }
            />
          </button>
        ))}
      </div>

      {/* ===================================================
          TICKET DRAWER
      ==================================================== */}

      {selectedTicket && (
        <TicketDrawer
          ticket={selectedTicket}
          onClose={() =>
            setSelectedTicket(null)
          }
        />
      )}
    </>
  );

  // =========================================================
  // PAGE
  // =========================================================

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* ===================================================
          TOP HEADER
      ==================================================== */}

      <div
        className="
          sticky
          top-0
          z-20
          border-b
          border-slate-800
          bg-slate-950/95
          backdrop-blur-xl
        "
      >
        <div className="px-3 py-3 sm:px-5">
          <div className="flex items-center justify-between gap-3">
            {/* Back */}
            <button
              type="button"
              onClick={() => navigate(-1)}
              className="
                flex
                items-center
                gap-1.5
                rounded-xl
                bg-slate-800
                px-3
                py-2
                text-xs
                font-semibold
                text-slate-300
                transition
                hover:bg-slate-700
                hover:text-white
                active:scale-95
              "
            >
              <ArrowLeft size={15} />
              Back
            </button>

            {/* View switch */}
            <div
              className="
                flex
                rounded-xl
                border
                border-slate-800
                bg-slate-900
                p-1
              "
            >
              <button
                type="button"
                onClick={() =>
                  setViewMode("mybets")
                }
                className={`
                  rounded-lg
                  px-3
                  py-2
                  text-[11px]
                  font-semibold
                  transition
                  ${
                    viewMode === "mybets"
                      ? "bg-yellow-400 text-black shadow-sm"
                      : "text-slate-400 hover:text-white"
                  }
                `}
              >
                My Bets
              </button>

              <button
                type="button"
                onClick={() =>
                  setViewMode("virtual")
                }
                className={`
                  rounded-lg
                  px-3
                  py-2
                  text-[11px]
                  font-semibold
                  transition
                  ${
                    viewMode === "virtual"
                      ? "bg-yellow-400 text-black shadow-sm"
                      : "text-slate-400 hover:text-white"
                  }
                `}
              >
                Virtual Bets
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ===================================================
          MAIN CONTENT
      ==================================================== */}

      <main className="mx-auto max-w-3xl px-3 py-5 sm:px-5">
        {/* Header */}
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className="
                flex
                h-11
                w-11
                items-center
                justify-center
                rounded-2xl
                bg-yellow-400
                text-black
                shadow-lg
                shadow-yellow-400/10
              "
            >
              {viewMode === "virtual" ? (
                <Wallet size={20} />
              ) : (
                <Ticket size={20} />
              )}
            </div>

            <div>
              <h1 className="text-lg font-black tracking-tight">
                {viewMode === "virtual"
                  ? "Virtual Bets"
                  : "My Bets"}
              </h1>

              <p className="text-[11px] text-slate-500">
                {viewMode === "virtual"
                  ? "Your virtual sports bets"
                  : "Track your predictions and results"}
              </p>
            </div>
          </div>

          {/* Refresh */}
          {viewMode === "mybets" && (
            <button
              type="button"
              onClick={loadBets}
              disabled={loading}
              aria-label="Refresh bets"
              className="
                flex
                h-10
                w-10
                items-center
                justify-center
                rounded-xl
                bg-slate-800
                text-slate-300
                transition
                hover:bg-slate-700
                hover:text-white
                active:scale-95
                disabled:pointer-events-none
                disabled:opacity-50
              "
            >
              <RefreshCw
                size={16}
                className={
                  loading
                    ? "animate-spin"
                    : ""
                }
              />
            </button>
          )}
        </div>

        {/* =================================================
            CONTENT
        ================================================== */}

        {viewMode === "virtual" ? (
          <VirtualBets />
        ) : (
          renderMyBets()
        )}
      </main>
    </div>
  );
}
