// src/user/Bookmarks.jsx

import React, {
  useEffect,
  useState,
  useRef,
  useMemo,
  useCallback,
} from "react";

import api from "../api/api";
import { useUser } from "../contexts/UserContext";
import { useLive } from "../contexts/LiveContext";
import { useBetslip } from "../contexts/BetslipContext";

import MatchCard from "../components/MatchCard";
import FloatingBetslip from "../components/FloatingBetslip";
import BottomN from "../components/BottomN";
import Promotions from "../components/Promotions";
import HeaderHero from "../components/HeaderHero";
import SportsMenu from "../components/SportsMenu";
import Virtual from "../user/Virtual";
import Live from "./Live";

// =========================================================
// SKELETON MATCH CARD
// =========================================================

function MatchSkeleton() {
  return (
    <div
      className="
        w-full
        overflow-hidden
        rounded-2xl
        border
        border-slate-800/80
        bg-slate-900/80
        p-3
        shadow-sm
      "
    >
      <div className="animate-pulse">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="h-3 w-28 rounded-full bg-slate-800" />
          <div className="h-3 w-16 rounded-full bg-slate-800" />
        </div>

        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <div className="h-10 w-10 shrink-0 rounded-full bg-slate-800" />

            <div className="min-w-0 flex-1">
              <div className="h-3 w-24 max-w-full rounded-full bg-slate-800" />
              <div className="mt-2 h-2.5 w-16 rounded-full bg-slate-800/80" />
            </div>
          </div>

          <div className="flex shrink-0 flex-col items-center gap-2">
            <div className="h-3 w-10 rounded-full bg-slate-800" />
            <div className="h-2.5 w-14 rounded-full bg-slate-800/70" />
          </div>

          <div className="flex min-w-0 flex-1 flex-row-reverse items-center gap-3">
            <div className="h-10 w-10 shrink-0 rounded-full bg-slate-800" />

            <div className="min-w-0 flex-1">
              <div className="ml-auto h-3 w-24 max-w-full rounded-full bg-slate-800" />
              <div className="mt-2 ml-auto h-2.5 w-16 rounded-full bg-slate-800/80" />
            </div>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-2">
          <div className="h-9 rounded-xl bg-slate-800" />
          <div className="h-9 rounded-xl bg-slate-800" />
          <div className="h-9 rounded-xl bg-slate-800" />
        </div>
      </div>
    </div>
  );
}

// =========================================================
// BOOKMARK SKELETONS
// =========================================================

function BookmarkSkeletons() {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((group) => (
        <div key={group}>
          <div className="mb-2 flex items-center justify-between px-1">
            <div className="h-4 w-20 animate-pulse rounded-full bg-slate-800" />
            <div className="h-3 w-14 animate-pulse rounded-full bg-slate-800/80" />
          </div>

          <div className="mb-2 h-10 animate-pulse rounded-xl bg-slate-900/90" />

          <div className="space-y-2">
            <MatchSkeleton />
            <MatchSkeleton />
          </div>
        </div>
      ))}
    </div>
  );
}

// =========================================================
// BOOKMARKS
// =========================================================

export default function Bookmarks() {
  const { user, balance } = useUser() || {};

  const {
    betslip,
    toggleBetslip,
    isPicked,
    combinedOdds,
  } = useBetslip();

  // =========================================================
  // STATE
  // =========================================================

  const [bookmarks, setBookmarks] = useState([]);
  const [oddsFlash, setOddsFlash] = useState({});
  const [selectedSport, setSelectedSport] = useState("Football");
  const [evMode, setEvMode] = useState(false);
  const [limit, setLimit] = useState(10);

  const [floatPos, setFloatPos] = useState({
    left: null,
    bottom: 72,
  });

  const [isDragging, setIsDragging] = useState(false);
  const [liveOpen, setLiveOpen] = useState(false);

  const [bounce, setBounce] = useState(false);
  const [prevBetsCount, setPrevBetsCount] = useState(0);

  // ONLY true during the first bookmark request.
  // Background refreshes NEVER touch this.
  const [initialLoading, setInitialLoading] = useState(true);

  // =========================================================
  // REFS
  // =========================================================

  const loadMoreRef = useRef(null);
  const mountedRef = useRef(true);

  const prevOddsRef = useRef({});
  const oddsFlashTimerRef = useRef(null);

  const floatRef = useRef(null);

  const selectedSportRef = useRef("Football");

  const floatPosRef = useRef({
    left: null,
    bottom: 72,
  });

  const dragStartRef = useRef({
    startX: 0,
    startY: 0,
    startLeft: 0,
    startBottom: 0,
  });

  // =========================================================
  // KEEP REFS CURRENT
  // =========================================================

  useEffect(() => {
    selectedSportRef.current = selectedSport;
  }, [selectedSport]);

  useEffect(() => {
    floatPosRef.current = floatPos;
  }, [floatPos]);

  // =========================================================
  // BETSLIP HANDLER
  // =========================================================

  const handleToggleBetslip = useCallback(
    (match, selection, odds) => {
      if (!match || !selection) {
        return;
      }

      toggleBetslip(match, selection, odds);
    },
    [toggleBetslip]
  );

  // =========================================================
  // FLOATING BETSLIP POSITION
  // =========================================================

  const setInitialFloatPosition = useCallback(() => {
    const element = floatRef.current;

    const width = element
      ? element.getBoundingClientRect().width
      : 240;

    const left = Math.max(
      8,
      Math.round(window.innerWidth / 2 - width / 2)
    );

    setFloatPos((previous) => {
      if (previous.left === left) {
        return previous;
      }

      const next = {
        ...previous,
        left,
      };

      floatPosRef.current = next;

      return next;
    });
  }, []);

  // =========================================================
  // MERGE BOOKMARKS
  // =========================================================

  const mergeBookmarks = useCallback((incoming) => {
    setBookmarks((previous) => {
      const previousById = new Map(
        previous.map((match) => [
          match.match_id || match.id,
          match,
        ])
      );

      let changed =
        previous.length !== incoming.length;

      const merged = incoming.map((next) => {
        const id = next.match_id || next.id;

        const previousMatch =
          previousById.get(id);

        if (!previousMatch) {
          changed = true;
          return next;
        }

        const same =
          previousMatch.home_odds ===
            next.home_odds &&
          previousMatch.draw_odds ===
            next.draw_odds &&
          previousMatch.away_odds ===
            next.away_odds &&
          previousMatch.over05 ===
            next.over05 &&
          previousMatch.under05 ===
            next.under05 &&
          previousMatch.over15 ===
            next.over15 &&
          previousMatch.under15 ===
            next.under15 &&
          previousMatch.over25 ===
            next.over25 &&
          previousMatch.under25 ===
            next.under25 &&
          previousMatch.over35 ===
            next.over35 &&
          previousMatch.under35 ===
            next.under35 &&
          previousMatch.gg ===
            next.gg &&
          previousMatch.ng ===
            next.ng &&
          previousMatch.gg_odds ===
            next.gg_odds &&
          previousMatch.ng_odds ===
            next.ng_odds &&
          previousMatch.match_time ===
            next.match_time &&
          previousMatch.status ===
            next.status &&
          previousMatch.home_team ===
            next.home_team &&
          previousMatch.away_team ===
            next.away_team &&
          previousMatch.league ===
            next.league &&
          previousMatch.EV ===
            next.EV;

        if (same) {
          return previousMatch;
        }

        changed = true;

        return next;
      });

      if (!changed) {
        return previous;
      }

      return merged;
    });
  }, []);

  // =========================================================
  // LOAD BOOKMARKS
  // =========================================================

  const loadBookmarks = useCallback(
    async (background = false) => {
      try {
        if (!background) {
          setInitialLoading((previous) =>
            previous ? previous : true
          );
        }

        const response =
          await api.getAllBookmarks();

        if (!mountedRef.current) {
          return;
        }

        if (response?.success) {
          const now = new Date();

          const incoming =
            response.data?.bookmarks || [];

          const upcoming = incoming.filter(
            (match) => {
              const matchDate = new Date(
                match.match_time
              );

              return (
                !Number.isNaN(
                  matchDate.getTime()
                ) &&
                matchDate > now
              );
            }
          );

          // =================================================
          // ODDS CHANGE DETECTION
          // =================================================

          const newOdds = {};
          const flash = {};

          let hasOddsChange = false;

          upcoming.forEach((match) => {
            const id =
              match.match_id || match.id;

            const current = {
              home: Number(
                match.home_odds ?? 0
              ),
              draw: Number(
                match.draw_odds ?? 0
              ),
              away: Number(
                match.away_odds ?? 0
              ),
            };

            newOdds[id] = current;

            const previous =
              prevOddsRef.current[id];

            let home = null;
            let draw = null;
            let away = null;

            if (previous) {
              if (
                current.home >
                previous.home
              ) {
                home = "up";
                hasOddsChange = true;
              } else if (
                current.home <
                previous.home
              ) {
                home = "down";
                hasOddsChange = true;
              }

              if (
                current.draw >
                previous.draw
              ) {
                draw = "up";
                hasOddsChange = true;
              } else if (
                current.draw <
                previous.draw
              ) {
                draw = "down";
                hasOddsChange = true;
              }

              if (
                current.away >
                previous.away
              ) {
                away = "up";
                hasOddsChange = true;
              } else if (
                current.away <
                previous.away
              ) {
                away = "down";
                hasOddsChange = true;
              }
            }

            flash[id] = {
              home,
              draw,
              away,
            };
          });

          prevOddsRef.current = newOdds;

          // =================================================
          // ODDS FLASH
          // =================================================

          if (hasOddsChange) {
            setOddsFlash(flash);

            if (oddsFlashTimerRef.current) {
              clearTimeout(
                oddsFlashTimerRef.current
              );
            }

            oddsFlashTimerRef.current =
              setTimeout(() => {
                if (
                  !mountedRef.current
                ) {
                  return;
                }

                setOddsFlash({});

                oddsFlashTimerRef.current =
                  null;
              }, 1200);
          }

          // =================================================
          // SILENT UPDATE
          // =================================================

          mergeBookmarks(upcoming);
        } else {
          if (!background) {
            setBookmarks([]);
          }
        }
      } catch (error) {
        console.error(
          "Error loading bookmarks",
          error
        );

        if (
          mountedRef.current &&
          !background
        ) {
          setBookmarks([]);
        }
      } finally {
        if (
          mountedRef.current &&
          !background
        ) {
          setInitialLoading(false);
        }
      }
    },
    [mergeBookmarks]
  );

  // =========================================================
  // INITIAL BOOKMARK LOAD
  // =========================================================

  useEffect(() => {
    mountedRef.current = true;

    loadBookmarks(false);

    setInitialFloatPosition();

    const handleResize = () => {
      setInitialFloatPosition();
    };

    window.addEventListener(
      "resize",
      handleResize
    );

    return () => {
      mountedRef.current = false;

      window.removeEventListener(
        "resize",
        handleResize
      );

      if (oddsFlashTimerRef.current) {
        clearTimeout(
          oddsFlashTimerRef.current
        );

        oddsFlashTimerRef.current = null;
      }
    };
  }, [
    loadBookmarks,
    setInitialFloatPosition,
  ]);

  // =========================================================
  // SILENT BACKGROUND REFRESH
  // =========================================================

  useEffect(() => {
    const interval = setInterval(() => {
      if (
        document.visibilityState !==
        "visible"
      ) {
        return;
      }

      if (
        selectedSportRef.current ===
        "Virtual"
      ) {
        return;
      }

      loadBookmarks(true);
    }, 10000);

    return () => {
      clearInterval(interval);
    };
  }, [loadBookmarks]);

  // =========================================================
  // RESET LOAD MORE
  // =========================================================

  useEffect(() => {
    setLimit(10);
  }, [
    selectedSport,
    evMode,
  ]);

  // =========================================================
  // LOAD MORE
  // =========================================================

  useEffect(() => {
    const node = loadMoreRef.current;

    if (!node) {
      return undefined;
    }

    const observer =
      new IntersectionObserver(
        (entries) => {
          if (
            !entries[0]?.isIntersecting
          ) {
            return;
          }

          setLimit((previous) => {
            if (
              previous >=
              bookmarks.length
            ) {
              return previous;
            }

            return previous + 10;
          });
        },
        {
          root: null,
          rootMargin: "200px",
          threshold: 0,
        }
      );

    observer.observe(node);

    return () => {
      observer.disconnect();
    };
  }, [
    selectedSport,
    evMode,
    bookmarks.length,
  ]);

  // =========================================================
  // BETSLIP BOUNCE
  // =========================================================

  useEffect(() => {
    const count =
      betslip?.length || 0;

    if (count === prevBetsCount) {
      return undefined;
    }

    setBounce(true);
    setPrevBetsCount(count);

    const timer = setTimeout(() => {
      if (mountedRef.current) {
        setBounce(false);
      }
    }, 600);

    return () => {
      clearTimeout(timer);
    };
  }, [
    betslip,
    prevBetsCount,
  ]);

  // =========================================================
  // STABLE ODDS FORMATTER
  // =========================================================

  const formatOdds = useCallback(
    (odds) => {
      const number = Number(odds);

      return Number.isFinite(number)
        ? number.toFixed(2)
        : "0.00";
    },
    []
  );

  // =========================================================
  // STABLE COUNTDOWN
  // =========================================================

  const getCountdown = useCallback(
    (matchTime) => {
      try {
        const now = new Date();
        const match = new Date(matchTime);

        const diff = match - now;

        if (diff <= 0) {
          return "Live";
        }

        const fiveMinutes =
          5 * 60 * 1000;

        if (diff <= fiveMinutes) {
          const minutes = Math.floor(
            diff / 60000
          );

          const seconds = Math.floor(
            (diff % 60000) / 1000
          );

          return `${String(
            minutes
          ).padStart(
            2,
            "0"
          )}:${String(
            seconds
          ).padStart(
            2,
            "0"
          )}`;
        }

        return match.toLocaleString(
          [],
          {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          }
        );
      } catch {
        return "";
      }
    },
    []
  );

  // =========================================================
  // EV MATCHES
  // =========================================================

  const evMatches = useMemo(() => {
    return bookmarks
      .filter((match) => {
        const ev = Number(match.EV);

        return (
          Number.isFinite(ev) &&
          ev > 0
        );
      })
      .sort(
        (a, b) =>
          Number(b.EV || 0) -
          Number(a.EV || 0)
      );
  }, [bookmarks]);

  // =========================================================
  // BEST EV
  // =========================================================

  const bestEv = useMemo(() => {
    if (!evMatches.length) {
      return 0;
    }

    return Number(
      evMatches[0].EV || 0
    );
  }, [evMatches]);

  // =========================================================
  // EV PERCENT
  // =========================================================

  const evPercent = useMemo(() => {
    return Math.round(bestEv * 100);
  }, [bestEv]);

  const valueBets = evMatches.length;

  // =========================================================
  // EV CLICK
  // =========================================================

  const handleEvClick = useCallback(() => {
    setEvMode(
      (previous) => !previous
    );

    setLimit(10);
  }, []);

  // =========================================================
  // LIVE COUNT
  // =========================================================

  const { liveCount } = useLive();

  // =========================================================
  // VISIBLE MATCHES
  // =========================================================

  const visibleMatches = useMemo(() => {
    if (
      selectedSport === "Virtual"
    ) {
      return [];
    }

    const list = evMode
      ? evMatches
      : bookmarks;

    return list.slice(0, limit);
  }, [
    bookmarks,
    selectedSport,
    evMode,
    evMatches,
    limit,
  ]);

  // =========================================================
  // GROUP BY DATE + LEAGUE
  // =========================================================

  const groupedByDate = useMemo(() => {
    const map = {};

    visibleMatches.forEach((match) => {
      const date = new Date(
        match.match_time
      );

      if (
        Number.isNaN(date.getTime())
      ) {
        return;
      }

      const dateKey = date
        .toISOString()
        .slice(0, 10);

      const league =
        match.league || "Other";

      if (!map[dateKey]) {
        map[dateKey] = {};
      }

      if (!map[dateKey][league]) {
        map[dateKey][league] = [];
      }

      map[dateKey][league].push(
        match
      );
    });

    Object.keys(map).forEach(
      (dateKey) => {
        Object.keys(
          map[dateKey]
        ).forEach((league) => {
          map[dateKey][league].sort(
            (a, b) =>
              new Date(
                a.match_time
              ) -
              new Date(
                b.match_time
              )
          );
        });
      }
    );

    return Object.fromEntries(
      Object.entries(map).sort(
        (a, b) =>
          new Date(a[0]) -
          new Date(b[0])
      )
    );
  }, [visibleMatches]);

  // =========================================================
  // DATE HEADER
  // =========================================================

  const formatDateHeader = useCallback(
    (dateKey) => {
      const date = new Date(
        `${dateKey}T00:00:00`
      );

      const today = new Date();

      const todayKey = today
        .toISOString()
        .slice(0, 10);

      const tomorrow =
        new Date(today);

      tomorrow.setDate(
        today.getDate() + 1
      );

      const tomorrowKey =
        tomorrow
          .toISOString()
          .slice(0, 10);

      if (dateKey === todayKey) {
        return "Today";
      }

      if (
        dateKey ===
        tomorrowKey
      ) {
        return "Tomorrow";
      }

      return date.toLocaleDateString(
        [],
        {
          day: "2-digit",
          month: "short",
          year: "numeric",
        }
      );
    },
    []
  );

  // =========================================================
  // POINTER DOWN
  // =========================================================

  const handlePointerDown =
    useCallback((event) => {
      const pointer =
        event.touches
          ? event.touches[0]
          : event;

      const element =
        floatRef.current;

      const rect = element
        ? element.getBoundingClientRect()
        : {
            width: 240,
            height: 80,
          };

      const currentPosition =
        floatPosRef.current;

      const startLeft =
        currentPosition.left ??
        Math.max(
          8,
          Math.round(
            window.innerWidth / 2 -
              rect.width / 2
          )
        );

      const startBottom =
        currentPosition.bottom ??
        72;

      dragStartRef.current = {
        startX: pointer.clientX,
        startY: pointer.clientY,
        startLeft,
        startBottom,
        active: true,
        dragging: false,
      };
    }, []);

  // =========================================================
  // POINTER MOVE / UP
  // =========================================================

  useEffect(() => {
    const handlePointerMove =
      (event) => {
        const drag = dragStartRef.current;

        if (!drag?.active) {
          return;
        }

        const pointer =
          event.touches
            ? event.touches[0]
            : event;

        const deltaX =
          pointer.clientX -
          drag.startX;

        const deltaY =
          pointer.clientY -
          drag.startY;

        // A normal click may move by a few pixels.
        // Only treat it as a drag after 6px of movement.
        const distance = Math.sqrt(
          deltaX * deltaX +
          deltaY * deltaY
        );

        if (!drag.dragging && distance < 6) {
          return;
        }

        if (!drag.dragging) {
          drag.dragging = true;
          setIsDragging(true);
        }

        const element =
          floatRef.current;

        const rect = element
          ? element.getBoundingClientRect()
          : {
              width: 240,
              height: 80,
            };

        const maxLeft =
          Math.max(
            8,
            window.innerWidth -
              rect.width -
              8
          );

        let newLeft =
          Math.round(
            drag.startLeft + deltaX
          );

        newLeft = Math.max(
          8,
          Math.min(
            maxLeft,
            newLeft
          )
        );

        const maxBottom =
          Math.max(
            8,
            window.innerHeight -
              rect.height -
              8
          );

        let newBottom =
          Math.round(
            drag.startBottom - deltaY
          );

        newBottom = Math.max(
          8,
          Math.min(
            maxBottom,
            newBottom
          )
        );

        const next = {
          left: newLeft,
          bottom: newBottom,
        };

        floatPosRef.current =
          next;

        setFloatPos(next);

        if (event.cancelable) {
          event.preventDefault();
        }
      };

    const handlePointerUp = () => {
      const drag =
        dragStartRef.current;

      if (drag) {
        drag.active = false;
        drag.dragging = false;
      }

      setIsDragging(false);
    };

    window.addEventListener(
      "mousemove",
      handlePointerMove,
      {
        passive: false,
      }
    );

    window.addEventListener(
      "touchmove",
      handlePointerMove,
      {
        passive: false,
      }
    );

    window.addEventListener(
      "mouseup",
      handlePointerUp
    );

    window.addEventListener(
      "touchend",
      handlePointerUp
    );

    window.addEventListener(
      "touchcancel",
      handlePointerUp
    );

    return () => {
      window.removeEventListener(
        "mousemove",
        handlePointerMove
      );

      window.removeEventListener(
        "touchmove",
        handlePointerMove
      );

      window.removeEventListener(
        "mouseup",
        handlePointerUp
      );

      window.removeEventListener(
        "touchend",
        handlePointerUp
      );

      window.removeEventListener(
        "touchcancel",
        handlePointerUp
      );
    };
  }, []);

  // =========================================================
  // SPORT CHANGE
  // =========================================================

  const handleSportChange =
    useCallback((sport) => {
      setSelectedSport(sport);

      if (sport === "Virtual") {
        setEvMode(false);
      }
    }, []);

  // =========================================================
  // RENDER
  // =========================================================

  return (
    <div
      className="
        relative
        isolate
        w-full
        max-w-full
        min-w-0
        overflow-x-hidden
        text-white
        p-2
        sm:p-3
        flex
        flex-col
        bg-slate-950
      "
    >
      {/* =====================================================
          RED / BLUE MATCHCARD-STYLE BACKGROUND
      ====================================================== */}

      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        {/* Main red → dark → blue gradient */}
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(239,68,68,0.28),transparent_38%),radial-gradient(circle_at_top_right,rgba(37,99,235,0.28),transparent_40%),linear-gradient(135deg,#450a0a_0%,#0f172a_42%,#172554_100%)]" />

        {/* Dark overlay for readability */}
        <div className="absolute inset-0 bg-slate-950/55" />

        {/* Red glow */}
        <div className="absolute -left-32 top-10 h-80 w-80 rounded-full bg-red-600/20 blur-3xl" />

        {/* Blue glow */}
        <div className="absolute -right-32 top-32 h-80 w-80 rounded-full bg-blue-600/20 blur-3xl" />

        {/* Bottom dark fade */}
        <div className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-slate-950 via-slate-950/60 to-transparent" />
      </div>

      <div className="relative z-10 flex w-full max-w-full min-w-0 flex-col">

        {/* ===================================================
            HEADER
        ==================================================== */}

        <div className="relative z-50 w-full">
          <HeaderHero
            user={user}
            balance={balance}
          />
        </div>

        {/* ===================================================
            PROMOTIONS
        ==================================================== */}

        <div className="relative z-40 w-full max-w-full min-w-0">
          <Promotions />
        </div>

        {/* ===================================================
            SPORTS MENU
        ==================================================== */}

        <div className="relative z-20 mt-3 w-full max-w-full min-w-0">
          <SportsMenu
            setSelectedSport={
              handleSportChange
            }
            selectedSport={
              selectedSport
            }
            evPercent={evPercent}
            valueBets={valueBets}
          />
        </div>

        {/* ===================================================
            EV MODE
        ==================================================== */}

        {selectedSport ===
          "Football" &&
          evMode && (
            <div className="relative z-10 mt-3">
              <div className="flex items-center justify-between rounded-xl border border-green-500/30 bg-green-500/10 px-3 py-2">
                <div>
                  <div className="text-xs font-bold text-green-400">
                    ⚡ EV+ VALUE
                  </div>

                  <div className="text-[10px] text-gray-500">
                    Showing{" "}
                    {valueBets}{" "}
                    positive-EV
                    matches
                  </div>
                </div>

                <button
                  type="button"
                  onClick={
                    handleEvClick
                  }
                  className="text-[10px] text-gray-400 transition hover:text-white"
                >
                  Clear
                </button>
              </div>
            </div>
          )}

        {/* ===================================================
            MATCH CONTENT
        ==================================================== */}

        <div className="relative z-10 mt-3 w-full min-w-0">
          {selectedSport ===
          "Virtual" ? (
            <div className="w-full max-w-full min-w-0 rounded-2xl bg-slate-950/35 shadow-[0_10px_30px_rgba(0,0,0,0.26)] backdrop-blur-sm">
              <Virtual />
            </div>
          ) : initialLoading ? (
            <BookmarkSkeletons />
          ) : (
            <>
              {Object.keys(
                groupedByDate
              ).length ? (
                Object.entries(
                  groupedByDate
                ).map(
                  ([
                    dateKey,
                    leagues,
                  ]) => {
                    const totalMatches =
                      Object.values(
                        leagues
                      ).reduce(
                        (
                          total,
                          matches
                        ) =>
                          total +
                          matches.length,
                        0
                      );

                    return (
                      <div
                        key={dateKey}
                        className="mb-5 w-full min-w-0"
                      >
                        {/* DATE */}

                        <div className="mb-2 flex items-center justify-between gap-3 px-1">
                          <div className="shrink-0 text-sm font-semibold text-gray-300">
                            {formatDateHeader(
                              dateKey
                            )}
                          </div>

                          <div className="shrink-0 text-xs text-gray-500">
                            {
                              totalMatches
                            }{" "}
                            {totalMatches ===
                            1
                              ? "match"
                              : "matches"}
                          </div>
                        </div>

                        {/* LEAGUES */}

                        {Object.entries(
                          leagues
                        ).map(
                          ([
                            league,
                            matches,
                          ]) => (
                            <div
                              key={
                                league
                              }
                              className="mb-4 w-full min-w-0"
                            >
                              <div className="flex w-full max-w-full min-w-0 items-center justify-between rounded-xl bg-slate-900/80 px-3 py-2.5 text-sm font-semibold text-gray-200">
                                <span className="truncate">
                                  {
                                    league
                                  }
                                </span>

                                <span className="ml-2 shrink-0 text-[10px] font-normal text-slate-500">
                                  {
                                    matches.length
                                  }
                                </span>
                              </div>

                              {/* MATCHES */}

                              <div className="mt-2 w-full min-w-0 space-y-2">
                                {matches.map(
                                  (
                                    match
                                  ) => {
                                    const matchId =
                                      match.match_id ||
                                      match.id;

                                    const flash =
                                      oddsFlash[
                                        matchId
                                      ];

                                    return (
                                      <MatchCard
                                        key={
                                          matchId
                                        }
                                        match={
                                          match
                                        }
                                        toggleBetslip={
                                          handleToggleBetslip
                                        }
                                        isPicked={
                                          isPicked
                                        }
                                        formatOdds={
                                          formatOdds
                                        }
                                        getCountdown={
                                          getCountdown
                                        }
                                        oddsFlashHome={
                                          flash?.home ||
                                          null
                                        }
                                        oddsFlashDraw={
                                          flash?.draw ||
                                          null
                                        }
                                        oddsFlashAway={
                                          flash?.away ||
                                          null
                                        }
                                      />
                                    );
                                  }
                                )}
                              </div>
                            </div>
                          )
                        )}
                      </div>
                    );
                  }
                )
              ) : (
                <div className="flex min-h-[180px] flex-col items-center justify-center rounded-2xl border border-slate-800 bg-slate-900/50 px-5 text-center">
                  <div className="mb-3 text-3xl">
                    ⚽
                  </div>

                  <p className="text-sm font-semibold text-slate-300">
                    {evMode
                      ? "No positive EV matches"
                      : "No bookmarked matches"}
                  </p>

                  <p className="mt-1 text-xs text-slate-500">
                    {evMode
                      ? "There are currently no value opportunities."
                      : "Your bookmarked matches will appear here."}
                  </p>
                </div>
              )}

              <div
                ref={loadMoreRef}
                className="h-8 w-full"
              />
            </>
          )}
        </div>

        {/* ===================================================
            FLOATING BETSLIP
        ==================================================== */}

        {selectedSport !==
          "Virtual" && (
          <FloatingBetslip
            betslip={betslip}
            combinedOdds={
              combinedOdds
            }
            floatRef={floatRef}
            floatPos={floatPos}
            handlePointerDown={
              handlePointerDown
            }
            isDragging={isDragging}
            bounce={bounce}
          />
        )}

        {/* ===================================================
            BOTTOM NAV
        ==================================================== */}

        <BottomN
          liveCount={liveCount}
          onLiveClick={() =>
            setLiveOpen(true)
          }
        />

        <Live
          open={liveOpen}
          onClose={() =>
            setLiveOpen(false)
          }
        />
      </div>
    </div>
  );
}
