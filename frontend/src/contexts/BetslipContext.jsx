// src/contexts/BetslipContext.jsx
import React, { createContext, useContext, useState, useMemo, useEffect } from "react";

const BetslipContext = createContext();

const BETSLIP_STORAGE_KEY = "betslip";
const MATCH_EXPIRY_MS = 3 * 60 * 60 * 1000; // 3 hours
const MIN_STAKE = 1; // minimum valid stake

export function BetslipProvider({ children }) {
  const [betslip, setBetslip] = useState(() => {
    try {
      const saved = localStorage.getItem(BETSLIP_STORAGE_KEY);
      if (!saved) return [];
      const parsed = JSON.parse(saved);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  });

  const [totalStake, setTotalStake] = useState(MIN_STAKE);

  // Sync across tabs
  useEffect(() => {
    const syncTabs = (e) => {
      if (e.key === BETSLIP_STORAGE_KEY) {
        try {
          const newData = JSON.parse(e.newValue || "[]");
          setBetslip(Array.isArray(newData) ? newData : []);
        } catch {}
      }
    };
    window.addEventListener("storage", syncTabs);
    return () => window.removeEventListener("storage", syncTabs);
  }, []);

  // Persist betslip
  useEffect(() => {
    localStorage.setItem(BETSLIP_STORAGE_KEY, JSON.stringify(betslip));
  }, [betslip]);

  // Auto-expire old matches
  useEffect(() => {
    const now = Date.now();
    const filtered = betslip.filter((b) => {
      if (!b.match?.kickoff) return true;
      const kickoff = new Date(b.match.kickoff).getTime();
      return kickoff + MATCH_EXPIRY_MS > now;
    });
    if (filtered.length !== betslip.length) setBetslip(filtered);
  }, [betslip]);

  const isPicked = (matchId, selection) =>
    betslip.some((b) => b.match?.id === matchId && b.selection === selection);

  const toggleBetslip = (match, selection, odds) => {
    const existingIndex = betslip.findIndex((b) => b.match?.id === match.match_id);

    const betData = {
      id: match.match_id,
      match: { ...match, id: match.match_id },
      selection,
      odds: Number(odds ?? 0),
      addedAt: Date.now(),
    };

    if (existingIndex !== -1) {
      if (betslip[existingIndex].selection === selection) {
        setBetslip(betslip.filter((_, i) => i !== existingIndex));
        return;
      }
      const updated = [...betslip];
      updated[existingIndex] = betData;
      setBetslip(updated);
      return;
    }

    setBetslip([...betslip, betData]);
  };

  const removeBet = (matchId) => setBetslip((prev) => prev.filter((b) => b.match?.id !== matchId));

  const clearBetslip = () => {
    setBetslip([]);
    setTotalStake(MIN_STAKE);
  };

  const combinedOdds = useMemo(() => {
    if (!betslip.length) return 0;
    return betslip.reduce((acc, b) => acc * Number(b.odds || 1), 1);
  }, [betslip]);

  const potentialWin = useMemo(() => {
    if (!totalStake || !combinedOdds) return 0;
    return (totalStake * combinedOdds).toFixed(2);
  }, [totalStake, combinedOdds]);

  // ⚡ Payload for backend with validation
  const getPayload = () => {
    const stake = Math.max(totalStake, MIN_STAKE); // never send 0

    if (!betslip.length) return {};

    if (betslip.length === 1) {
      const b = betslip[0];
      return {
        match_id: b.match.id,
        selection: b.selection,
        stake,
      };
    }

    return {
      stake,
      selections: betslip.map((b) => ({
        match_id: b.match.id,
        selection: b.selection,
        client_odds: b.odds.toString(),
      })),
    };
  };

  return (
    <BetslipContext.Provider
      value={{
        betslip,
        toggleBetslip,
        removeBet,
        clearBetslip,
        isPicked,
        combinedOdds,
        totalStake,
        setTotalStake,
        potentialWin,
        getPayload,
      }}
    >
      {children}
    </BetslipContext.Provider>
  );
}

export function useBetslip() {
  const context = useContext(BetslipContext);
  if (!context) throw new Error("useBetslip must be used inside BetslipProvider");
  return context;
}
