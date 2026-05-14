// src/user/Bookmarks.jsx
import React, { useEffect, useState, useRef, useMemo } from "react";
import api from "../api/api";
import { useUser } from "../contexts/UserContext";
import { useBetslip } from "../contexts/BetslipContext";

import MatchCard from "../components/MatchCard";
import FloatingBetslip from "../components/FloatingBetslip";
import BottomN from "../components/BottomN";
import HeaderHero from "../components/HeaderHero";
import Promotions from "../components/Promotions";
import SportsMenu from "../components/SportsMenu";
import Virtual from "../user/Virtual";

export default function Bookmarks() {
  const { user, balance, reloadUser } = useUser() || {};
  const { betslip, toggleBetslip, isPicked, combinedOdds } = useBetslip();

  const [bookmarks, setBookmarks] = useState([]);
  const [prevOdds, setPrevOdds] = useState({});
  const [oddsFlash, setOddsFlash] = useState({});
  const [selectedSport, setSelectedSport] = useState("All");

  const [limit, setLimit] = useState(10);
  const loadMoreRef = useRef(null);
  const mountedRef = useRef(true);
  const bounceTimerRef = useRef(null);

  const floatRef = useRef(null);
  const [floatPos, setFloatPos] = useState({ left: null, bottom: 72 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef({ startX: 0, startY: 0, startLeft: 0, startBottom: 0 });
  const [bounce, setBounce] = useState(false);
  const [prevBetsCount, setPrevBetsCount] = useState(0);

  const normalizeSelectionKey = (selection) => {
    if (!selection) return selection;
    const s = String(selection).toLowerCase();
    if (s === "home" || s === "home_odds" || s === "1" || s === "h") return "home_odds";
    if (s === "draw" || s === "draw_odds" || s === "x" || s === "d") return "draw_odds";
    if (s === "away" || s === "away_odds" || s === "2" || s === "a") return "away_odds";
    return selection;
  };

  const handleToggleBetslip = (match, selection, odds) => {
    const key = normalizeSelectionKey(selection);
    toggleBetslip(match, key, odds);
  };

  useEffect(() => {
    mountedRef.current = true;
    reloadUser?.();
    loadBookmarks();

    const setInitialPos = () => {
      const el = floatRef.current;
      const width = el ? el.getBoundingClientRect().width : 240;
      const left = Math.max(8, Math.round(window.innerWidth / 2 - width / 2));
      setFloatPos((p) => ({ ...p, left }));
    };
    setInitialPos();

    const interval = setInterval(() => {
      if (document.visibilityState === "visible" && selectedSport !== "Virtual") {
        loadBookmarks();
      }
    }, 10000);

    return () => {
      mountedRef.current = false;
      clearInterval(interval);
      if (bounceTimerRef.current) clearTimeout(bounceTimerRef.current);
    };
  }, [selectedSport]);

  async function loadBookmarks() {
    try {
      const resp = await api.getAllBookmarks();
      if (!mountedRef.current) return;

      if (resp?.success) {
        const now = new Date();
        const upcoming = (resp.data?.bookmarks || []).filter((m) => {
          try {
            return new Date(m.match_time) > now;
          } catch {
            return false;
          }
        });

        const newOdds = {};
        const flash = {};

        upcoming.forEach((m) => {
          const id = m.match_id || m.id;
          const cur = {
            home: Number(m.home_odds ?? 0),
            draw: Number(m.draw_odds ?? 0),
            away: Number(m.away_odds ?? 0),
          };

          newOdds[id] = cur;
          const prev = prevOdds[id];
          flash[id] = { home: null, draw: null, away: null };

          if (prev) {
            flash[id].home = cur.home > prev.home ? "up" : cur.home < prev.home ? "down" : null;
            flash[id].draw = cur.draw > prev.draw ? "up" : cur.draw < prev.draw ? "down" : null;
            flash[id].away = cur.away > prev.away ? "up" : cur.away < prev.away ? "down" : null;
          }
        });

        setPrevOdds(newOdds);
        setOddsFlash(flash);
        setBookmarks(upcoming);

        setTimeout(() => {
          if (!mountedRef.current) return;
          setOddsFlash({});
        }, 1200);
      } else {
        setBookmarks([]);
      }
    } catch (err) {
      console.error("Error loading bookmarks", err);
      setBookmarks([]);
    }
  }

  useEffect(() => {
    const node = loadMoreRef.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) setLimit((prev) => prev + 10);
      },
      { root: null, rootMargin: "0px", threshold: 0.5 }
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [selectedSport]);

  useEffect(() => {
    const cur = betslip?.length || 0;
    if (cur !== prevBetsCount) {
      setBounce(true);
      if (bounceTimerRef.current) clearTimeout(bounceTimerRef.current);
      bounceTimerRef.current = setTimeout(() => {
        if (mountedRef.current) setBounce(false);
      }, 600);
      setPrevBetsCount(cur);
    }
  }, [betslip, prevBetsCount]);

  const formatOdds = (o) => {
    const n = Number(o);
    return isFinite(n) ? n.toFixed(2) : "0.00";
  };

  const getCountdown = (matchTime) => {
    try {
      const now = new Date();
      const match = new Date(matchTime);
      const diff = match - now;
      if (diff <= 0) return "Live";

      const fiveMinutes = 5 * 60 * 1000;
      if (diff <= fiveMinutes) {
        const m = Math.floor(diff / 60000);
        const s = Math.floor((diff % 60000) / 1000);
        return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
      }

      return match.toLocaleString([], {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return "";
    }
  };

  const liveCount = useMemo(() => bookmarks.filter((m) => m.status === "live").length, [bookmarks]);

  const visibleMatches = useMemo(() => {
    let list = bookmarks || [];
    if (selectedSport === "Football") {
      list = list.filter((m) => String(m.league || "").toLowerCase().includes("football"));
    }
    return list.slice(0, limit);
  }, [bookmarks, selectedSport, limit]);

  const groupedByDate = useMemo(() => {
    const map = {};
    visibleMatches.forEach((m) => {
      const d = new Date(m.match_time);
      if (!isFinite(d)) return;
      const dateKey = d.toISOString().slice(0, 10);
      const league = m.league || "Other";
      if (!map[dateKey]) map[dateKey] = {};
      if (!map[dateKey][league]) map[dateKey][league] = [];
      map[dateKey][league].push(m);
    });

    Object.keys(map).forEach((dateKey) => {
      Object.keys(map[dateKey]).forEach((league) => {
        map[dateKey][league].sort((a, b) => new Date(a.match_time) - new Date(b.match_time));
      });
    });

    return Object.fromEntries(
      Object.entries(map).sort((a, b) => new Date(a[0]) - new Date(b[0]))
    );
  }, [visibleMatches]);

  const formatDateHeader = (dateKey) => {
    const d = new Date(dateKey + "T00:00:00");
    const today = new Date();
    const todayKey = today.toISOString().slice(0, 10);
    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);
    const tomorrowKey = tomorrow.toISOString().slice(0, 10);
    if (dateKey === todayKey) return "Today";
    if (dateKey === tomorrowKey) return "Tomorrow";
    return d.toLocaleDateString([], { day: "2-digit", month: "short", year: "numeric" });
  };

  function handlePointerDown(e) {
    const ev = e.touches ? e.touches[0] : e;
    const el = floatRef.current;
    const rect = el ? el.getBoundingClientRect() : { width: 240, height: 80 };
    const startX = ev.clientX;
    const startY = ev.clientY;
    dragStartRef.current = {
      startX,
      startY,
      startLeft: floatPos.left ?? Math.max(8, Math.round(window.innerWidth / 2 - rect.width / 2)),
      startBottom: floatPos.bottom ?? 72,
    };
    setIsDragging(true);
    if (e.preventDefault) e.preventDefault();
  }

  useEffect(() => {
    function handlePointerMove(e) {
      if (!isDragging) return;
      const ev = e.touches ? e.touches[0] : e;
      const { startX, startY, startLeft, startBottom } = dragStartRef.current;

      const deltaX = ev.clientX - startX;
      const deltaY = ev.clientY - startY;

      const el = floatRef.current;
      const rect = el ? el.getBoundingClientRect() : { width: 240, height: 80 };

      const minLeft = 8;
      const maxLeft = Math.max(8, window.innerWidth - rect.width - 8);
      let newLeft = Math.round(startLeft + deltaX);
      newLeft = Math.max(minLeft, Math.min(maxLeft, newLeft));

      const minBottom = 8;
      const maxBottom = Math.max(8, window.innerHeight - rect.height - 8);
      let newBottom = Math.round(startBottom - deltaY);
      newBottom = Math.max(minBottom, Math.min(maxBottom, newBottom));

      setFloatPos({ left: newLeft, bottom: newBottom });
    }

    function handlePointerUp() {
      if (!isDragging) return;
      setIsDragging(false);
    }

    if (isDragging) {
      window.addEventListener("mousemove", handlePointerMove, { passive: false });
      window.addEventListener("touchmove", handlePointerMove, { passive: false });
      window.addEventListener("mouseup", handlePointerUp, { passive: true });
      window.addEventListener("touchend", handlePointerUp, { passive: true });
    }

    return () => {
      window.removeEventListener("mousemove", handlePointerMove);
      window.removeEventListener("touchmove", handlePointerMove);
      window.removeEventListener("mouseup", handlePointerUp);
      window.removeEventListener("touchend", handlePointerUp);
    };
  }, [isDragging, floatPos]);

  const pageShell =
    "relative isolate min-h-screen overflow-hidden text-white p-3 flex flex-col bg-slate-950";

  const shell = "rounded-2xl bg-slate-950/35 backdrop-blur-sm shadow-[0_10px_30px_rgba(0,0,0,0.26)]";

  return (
    <div
      className={pageShell}
      style={{
        paddingTop: 92,
      }}
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(16,185,129,0.24),rgba(15,23,42,0.76)_42%,rgba(2,6,23,0.98)_100%)]" />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-emerald-950/50 via-slate-900/30 to-slate-950/90" />

      <div className="relative z-10 flex flex-col">
        <div className="relative z-30">
          <HeaderHero user={user} balance={balance} />
        </div>

        <div className="relative z-20">
          <Promotions />
        </div>

        <div className="relative z-20 mt-3">
          <SportsMenu setSelectedSport={setSelectedSport} selectedSport={selectedSport} />
        </div>

        <div className="mt-3 relative z-10">
          {selectedSport === "Virtual" ? (
            <div className={shell}>
              <Virtual />
            </div>
          ) : (
            <>
              {Object.keys(groupedByDate).length ? (
                Object.entries(groupedByDate).map(([dateKey, leagues]) => (
                  <div key={dateKey} className="mb-5">
                    <div className="text-sm font-semibold text-gray-300 mb-2 px-1 flex items-center justify-between">
                      <div>{formatDateHeader(dateKey)}</div>
                      <div className="text-xs text-gray-400">
                        {Object.values(leagues).reduce((acc, arr) => acc + arr.length, 0)} match
                        {Object.values(leagues).reduce((acc, arr) => acc + arr.length, 0) !== 1 ? "es" : ""}
                      </div>
                    </div>

                    {Object.entries(leagues).map(([league, matches]) => (
                      <div key={league} className="mb-4">
                        <div className="bg-slate-900/80 text-gray-200 px-3 py-2 rounded-lg font-semibold text-sm">
                          {league}
                        </div>

                        <div className="space-y-2 mt-2">
                          {matches.map((m) => (
                            <MatchCard
                              key={m.match_id || m.id}
                              match={m}
                              toggleBetslip={handleToggleBetslip}
                              isPicked={isPicked}
                              formatOdds={formatOdds}
                              getCountdown={getCountdown}
                              oddsFlash={oddsFlash}
                            />
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ))
              ) : (
                <div className="text-center text-gray-400 text-sm py-6">No matches available</div>
              )}

              {selectedSport !== "Virtual" && <div ref={loadMoreRef} style={{ height: 20 }} />}
            </>
          )}
        </div>

        {selectedSport !== "Virtual" && (
          <FloatingBetslip
            betslip={betslip}
            combinedOdds={combinedOdds}
            floatRef={floatRef}
            floatPos={floatPos}
            handlePointerDown={handlePointerDown}
            isDragging={isDragging}
            bounce={bounce}
          />
        )}

        <BottomN liveCount={liveCount} />
      </div>
    </div>
  );
}
