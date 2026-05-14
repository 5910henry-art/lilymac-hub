// src/components/Virtual.js
import React, { useEffect, useState, useMemo, useRef } from "react";
import VirtualAPI from "../api/virtualAPI";
import "../styles/virtual.css";
import { useUser } from "../contexts/UserContext";

export default function VirtualSportsbook() {
  const { balance, updateBalance, reloadUser } = useUser();

  const [rounds, setRounds] = useState([]);
  const [selectedRound, setSelectedRound] = useState(null);
  const [manualRoundSelect, setManualRoundSelect] = useState(false);
  const [highlightedRound, setHighlightedRound] = useState(null);

  const [matches, setMatches] = useState([]);
  const [market, setMarket] = useState("1X2");

  const [bets, setBets] = useState([]);
  const [stake, setStake] = useState("");

  const [events, setEvents] = useState({});
  const [selectedMatch, setSelectedMatch] = useState(null);

  const [oddsFlash, setOddsFlash] = useState({});
  const [isOffline, setIsOffline] = useState(false);
  const [toast, setToast] = useState(null);

  const prevOdds = useRef({});
  const inputRef = useRef(null);
  const toastTimerRef = useRef(null);
  const [now, setNow] = useState(Date.now());

  const MATCH_DELAY = 30 * 1000;
  const MATCH_DURATION = 45 * 1000;

  const showToast = (message, type = "info") => {
    setToast({ message, type });
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToast(null), 2500);
  };

  /* ---------------- GLOBAL CLOCK ---------------- */
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  /* ---------------- HELPERS ---------------- */
  const parseUTCtoLocal = (utcStr) => new Date(utcStr);

  const getRoundStatus = (r) => {
    if (!r || !r.status) return "SCHEDULED";
    return r.status;
  };

  const formatCountdown = (r) => {
    if (!r) return "";

    if (typeof r.time_to_start === "number") {
      const diff = r.time_to_start;
      if (diff <= 0) return r.status === "RUNNING" ? "LIVE" : "0:00";
      const m = Math.floor(diff / 60);
      const s = diff % 60;
      return `${m}:${s.toString().padStart(2, "0")}`;
    }

    if (!r.open_time) return "";
    const start = parseUTCtoLocal(r.open_time).getTime() + MATCH_DELAY;
    const diff = Math.floor((start - now) / 1000);
    if (diff <= 0) return "LIVE";
    const m = Math.floor(diff / 60);
    const s = diff % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  const pickNextAvailableRound = (data) => {
    if (!Array.isArray(data) || data.length === 0) return null;

    const nextRound = data.find((r) => {
      const status = getRoundStatus(r);
      return status === "OPEN" || status === "SCHEDULED" || status === "RUNNING";
    });

    return nextRound || data[0] || null;
  };

  /* ---------------- LOAD ROUNDS ---------------- */
  useEffect(() => {
    let alive = true;

    const loadRounds = async () => {
      try {
        const data = await VirtualAPI.getRounds();
        if (!alive) return;

        if (!data || data.length === 0) {
          setIsOffline(true);
          setRounds([]);
          setMatches([]);
          return;
        }

        setIsOffline(false);
        setRounds(data);

        const currentExists = selectedRound != null && data.some((r) => r.round === selectedRound);

        if (!selectedRound || !currentExists) {
          const nextRound = pickNextAvailableRound(data);
          if (nextRound) {
            setSelectedRound(nextRound.round);
            setHighlightedRound(nextRound.round);
            setManualRoundSelect(false);
          }
        }
      } catch {
        if (!alive) return;
        setIsOffline(true);
      }
    };

    loadRounds();

    return () => {
      alive = false;
    };
  }, [now]);

  /* ---------------- AUTO RETRY WHEN OFFLINE ---------------- */
  useEffect(() => {
    if (!isOffline) return;

    const retry = setInterval(() => {
      VirtualAPI.getRounds()
        .then((data) => {
          if (data && data.length > 0) {
            setIsOffline(false);
            setRounds(data);

            const currentExists = selectedRound != null && data.some((r) => r.round === selectedRound);
            if (!selectedRound || !currentExists) {
              const nextRound = pickNextAvailableRound(data);
              if (nextRound) {
                setSelectedRound(nextRound.round);
                setHighlightedRound(nextRound.round);
                setManualRoundSelect(false);
              }
            }
          }
        })
        .catch(() => {});
    }, 5000);

    return () => clearInterval(retry);
  }, [isOffline, selectedRound]);

  /* ---------------- AUTO SWITCH WHEN ROUND FINISHES ---------------- */
  useEffect(() => {
    if (!rounds.length) return;

    const currentExists = selectedRound != null && rounds.some((r) => r.round === selectedRound);

    if (!currentExists) {
      const nextRound = pickNextAvailableRound(rounds);
      if (nextRound) {
        setSelectedRound(nextRound.round);
        setHighlightedRound(nextRound.round);
        setManualRoundSelect(false);
      }
    }
  }, [rounds, selectedRound]);

  /* ---------------- AUTO SKIP FINISHED ---------------- */
  useEffect(() => {
    if (!selectedRound || manualRoundSelect) return;

    const roundData = rounds.find((r) => r.round === selectedRound);
    if (!roundData) return;

    if (getRoundStatus(roundData) === "FINISHED") {
      const nextRound = pickNextAvailableRound(rounds);
      if (nextRound) {
        setSelectedRound(nextRound.round);
        setHighlightedRound(nextRound.round);
      }
    }
  }, [rounds, now, selectedRound, manualRoundSelect]);

  /* ---------------- RESET MANUAL FLAG ---------------- */
  useEffect(() => {
    if (!selectedRound) return;
    const roundData = rounds.find((r) => r.round === selectedRound);
    if (!roundData) return;
    if (getRoundStatus(roundData) !== "FINISHED") setManualRoundSelect(false);
  }, [selectedRound, rounds, now]);

  /* ---------------- LOAD MATCHES (POLLING ONLY) ---------------- */
  useEffect(() => {
    if (!selectedRound) {
      setMatches([]);
      return;
    }

    const stop = VirtualAPI.liveRoundMatches(
      selectedRound,
      (data) => {
        const matchList = data?.matches || [];
        const flash = {};

        matchList.forEach((m) => {
          if (!m.odds) return;
          const prev = prevOdds.current[m.id] || {};
          flash[m.id] = {};

          Object.keys(m.odds).forEach((k) => {
            if (prev[k] && m.odds[k] !== prev[k]) {
              flash[m.id][k] = m.odds[k] > prev[k] ? "up" : "down";
            }
          });

          prevOdds.current[m.id] = m.odds;
        });

        setOddsFlash(flash);
        setMatches(matchList);
        setTimeout(() => setOddsFlash({}), 800);
      },
      2000
    );

    return () => stop();
  }, [selectedRound, isOffline]);

  /* ---------------- LOAD EVENTS (POLLING) ---------------- */
  useEffect(() => {
    if (!matches.length) return;

    const stops = [];
    matches.forEach((match) => {
      if (match.status === "RUNNING") {
        const stop = VirtualAPI.liveEvents(
          match.id,
          (data) => setEvents((prev) => ({ ...prev, [match.id]: data || [] })),
          1500
        );
        stops.push(stop);
      }
    });

    return () => stops.forEach((s) => s());
  }, [matches]);

  /* ---------------- MULTIBET ---------------- */
  const toggleBet = (match, selection, odd) => {
    if (!match || match.status === "RUNNING") return;
    if (odd === undefined || odd === null || Number.isNaN(Number(odd))) return;

    const id = match.id + "-" + selection;
    const exists = bets.find((b) => b.id === id);

    if (exists) {
      setBets((prev) => prev.filter((b) => b.id !== id));
    } else {
      setBets((prev) => [
        ...prev,
        {
          id,
          matchId: match.id,
          home: match.home,
          away: match.away,
          selection,
          odd: Number(odd),
        },
      ]);
    }
  };

  const combinedOdds = useMemo(() => {
    if (!bets.length) return "0.00";
    const val = bets.reduce((acc, b) => acc * b.odd, 1);
    return Number.isFinite(val) ? val.toFixed(2) : "0.00";
  }, [bets]);

  const potentialWin = useMemo(() => {
    if (!stake) return "0.00";
    const s = Number(stake);
    if (!s || s <= 0) return "0.00";
    const pw = s * Number(combinedOdds);
    return Number.isFinite(pw) ? pw.toFixed(2) : "0.00";
  }, [stake, combinedOdds]);

  useEffect(() => {
    if (bets.length > 0 && inputRef.current) inputRef.current.focus();
  }, [bets]);

  /* ---------------- PLACE BET ---------------- */
  const placeBet = async () => {
    if (isOffline) {
      showToast("No connection. Try again.", "error");
      return;
    }

    if (!bets.length) {
      showToast("Select at least one selection", "error");
      return;
    }

    const numericStake = Number(stake);
    if (!stake || Number.isNaN(numericStake) || numericStake <= 0) {
      showToast("Enter a valid stake", "error");
      return;
    }

    try {
      const selectionsArray = bets.map((b) => ({
        match_id: b.matchId,
        selection: b.selection,
      }));

      const payload = {
        stake: numericStake,
        selections: selectionsArray,
        bets: selectionsArray,
      };

      const res = await VirtualAPI.placeBet(payload);

      if (res?.data?.success === false) {
        const detail = res.data.detail || res.data.error || "Bet failed";
        showToast(detail, "error");
        return;
      }

      showToast("Bet placed successfully", "success");

      setBets([]);
      setStake("");

      updateBalance((prev) => prev - numericStake);
      reloadUser().catch(() => {});
    } catch {
      setIsOffline(true);
      showToast("Network error. Please try again.", "error");
    }
  };

  /* ---------------- UI HELPERS ---------------- */
  const matchTimer = (m) => {
    if (!m) return "";
    if (m.status === "OPEN") return `Start in ${m.time_to_start}s`;
    if (m.status === "RUNNING") return `Live ${m.time_to_end}s`;
    if (m.status === "FINISHED") return "Finished";
    return "";
  };

  const isSelected = (matchId, selection) =>
    bets.some((b) => b.matchId === matchId && b.selection === selection);

  const visibleRounds = rounds;

  const renderEvent = (e) => {
    if (!e) return "Match event";
    return e.description || e.text || e.event || e.type || (e.minute ? `${e.minute}' event` : "Match event");
  };

  return (
    <div className="virtualPage">
      <div className="roundTabs">
        {visibleRounds.map((r) => {
          const rStatus = getRoundStatus(r);
          const countdown = formatCountdown(r);

          return (
            <button
              key={r.round}
              className={`${rStatus === "RUNNING" ? "liveRound" : rStatus === "OPEN" ? "preLiveRound" : ""} ${
                highlightedRound === r.round ? "selectedRound" : ""
              }`}
              onClick={() => {
                setSelectedRound(r.round);
                setManualRoundSelect(true);
                setHighlightedRound(r.round);
              }}
            >
              <div>
                {r.open_time
                  ? parseUTCtoLocal(r.open_time).toLocaleTimeString("en-KE", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : `Round ${r.round}`}
              </div>
              <small>{countdown}</small>
            </button>
          );
        })}
      </div>

      {/* MARKET TABS */}
      <div className="marketTabs">
        {["1X2", "BTTS", "OU15", "OU25"].map((mkt) => (
          <button key={mkt} className={market === mkt ? "active" : ""} onClick={() => setMarket(mkt)}>
            {mkt}
          </button>
        ))}
      </div>

      {/* MATCH LIST */}
      <div className="matchList">
        {matches.map((match) => {
          const o = match.odds || {};
          const flash = oddsFlash[match.id] || {};
          let buttons = [];

          if (market === "1X2")
            buttons = [
              { key: "home", label: "1", odd: o.home },
              { key: "draw", label: "X", odd: o.draw },
              { key: "away", label: "2", odd: o.away },
            ];
          else if (market === "BTTS")
            buttons = [
              { key: "btts_yes", label: "Yes", odd: o.btts_yes },
              { key: "btts_no", label: "No", odd: o.btts_no },
            ];
          else if (market === "OU25")
            buttons = [
              { key: "over25", label: "O2.5", odd: o.over25 },
              { key: "under25", label: "U2.5", odd: o.under25 },
            ];
          else if (market === "OU15")
            buttons = [
              { key: "over15", label: "O1.5", odd: o.over15 },
              { key: "under15", label: "U1.5", odd: o.under15 },
            ];

          const matchEvents = events[match.id] || [];

          return (
            <div
              key={match.id}
              className="matchRow"
              onClick={() => setSelectedMatch(match.id)}
              style={{ cursor: "pointer" }}
            >
              <div className="teams">
                <div>{match.home}</div>
                <div>{match.away}</div>
                <small>{matchTimer(match)}</small>

                {match.status === "RUNNING" && matchEvents.length > 0 && (
                  <div className="liveTicker">
                    {matchEvents.slice(-2).map((e, i) => (
                      <div key={i}>{renderEvent(e)}</div>
                    ))}
                  </div>
                )}
              </div>

              <div className="oddsRow">
                {match.status === "RUNNING" ? (
                  <div style={{ fontSize: 12, color: "#ff4d4d" }}>LIVE</div>
                ) : (
                  buttons.map((btn) => {
                    const oddValue = btn.odd;
                    const flashClass = flash[btn.key] ? "flash-" + flash[btn.key] : "";
                    const selectedClass = isSelected(match.id, btn.key) ? "selected" : "";

                    if (oddValue === undefined || oddValue === null) {
                      return (
                        <button key={btn.key} className={`oddBtn disabled`} disabled>
                          <span>{btn.label}</span>
                          <b>—</b>
                        </button>
                      );
                    }

                    return (
                      <button
                        key={btn.key}
                        className={`oddBtn ${flashClass} ${selectedClass}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleBet(match, btn.key, oddValue);
                        }}
                      >
                        <span>{btn.label}</span>
                        <b>{oddValue}</b>
                      </button>
                    );
                  })
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* BET SLIP PANEL */}
      {bets.length > 0 && (
        <div className="betSlipPanel">
          <input
            ref={inputRef}
            type="number"
            placeholder="Stake"
            value={stake}
            onChange={(e) => setStake(e.target.value)}
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
          <div>Total Odds: {combinedOdds}</div>
          <div>Potential Win: {potentialWin}</div>
          <button
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
              background: isOffline ? "#94a3b8" : "#22c55e",
              opacity: isOffline ? 0.7 : 1,
              cursor: isOffline ? "not-allowed" : "pointer",
            }}
          >
            {isOffline ? "No Connection" : "Place Bet"}
          </button>
        </div>
      )}

      {/* TOAST */}
      {toast && (
        <div
          style={{
            position: "fixed",
            bottom: "120px",
            left: "50%",
            transform: "translateX(-50%)",
            background: toast.type === "success" ? "#16a34a" : toast.type === "error" ? "#dc2626" : "#334155",
            color: "#fff",
            padding: "12px 20px",
            borderRadius: "10px",
            fontWeight: "bold",
            boxShadow: "0 5px 20px rgba(0,0,0,0.3)",
            zIndex: 9999,
            animation: "fadeIn 0.3s ease",
            maxWidth: "90vw",
            textAlign: "center",
          }}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}
