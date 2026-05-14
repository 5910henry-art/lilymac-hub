// src/user/Betslip.jsx
import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { placeBet } from "../api/betsWallet";
import { useUser } from "../contexts/UserContext";
import { useBetslip } from "../contexts/BetslipContext";
import { toast } from "react-hot-toast";

const MAX_STAKE = 50000;
const MAX_PAYOUT = 200000;
const MIN_STAKE = 1; // must be >= 1

export default function Betslip() {
  const navigate = useNavigate();
  const { user, balance = 0, reloadUser, setUser, setBalance } = useUser() || {};
  const {
    betslip,
    removeBet,
    clearBetslip,
    combinedOdds,
    totalStake,
    getPayload,
    setTotalStake
  } = useBetslip();

  // Local string state for input
  const [stakeInput, setStakeInput] = useState(totalStake ? String(totalStake) : String(MIN_STAKE));
  const [loading, setLoading] = useState(false);
  const placeBtnRef = useRef(null);

  useEffect(() => {
    reloadUser?.();
  }, []);

  // Sync stakeInput when totalStake changes from other parts of app
  useEffect(() => {
    setStakeInput(totalStake ? String(totalStake) : String(MIN_STAKE));
  }, [totalStake]);

  // Parse numeric stake safely
  const parseStake = (val) => {
    if (val === "" || val === null || typeof val === "undefined") return 0;
    const n = Number(val);
    return Number.isFinite(n) ? n : 0;
  };

  const effectiveStake = Math.max(parseStake(stakeInput), MIN_STAKE);

  const potentialWin = (() => {
    if (!effectiveStake || !combinedOdds) return 0;
    return effectiveStake * combinedOdds;
  })();

  const canPlaceBetClient = () => {
    if (!betslip.length) return false;
    if (effectiveStake < MIN_STAKE) return false;
    if (effectiveStake > MAX_STAKE) return false;
    if (effectiveStake > balance) return false;
    if (potentialWin > MAX_PAYOUT) return false;
    return true;
  };

  const validateBeforeSend = () => {
    if (!betslip.length) return { ok: false, msg: "No selections in betslip" };
    if (effectiveStake < MIN_STAKE) return { ok: false, msg: `Stake must be at least ${MIN_STAKE}` };
    if (effectiveStake > MAX_STAKE) return { ok: false, msg: `Stake exceeds maximum of ${MAX_STAKE}` };
    if (effectiveStake > balance) return { ok: false, msg: "Insufficient balance" };
    if (potentialWin > MAX_PAYOUT) return { ok: false, msg: `Potential win KES ${potentialWin.toFixed(2)} exceeds max payout ${MAX_PAYOUT}` };
    return { ok: true };
  };

  const handlePlaceBet = async () => {
    // update context totalStake from input
    setTotalStake(effectiveStake);

    // client-side validation
    const check = validateBeforeSend();
    if (!check.ok) {
      toast.error(check.msg);
      return;
    }

    const token = localStorage.getItem("token");
    if (!token) {
      toast.error("Please login first!");
      navigate("/auth");
      return;
    }

    try {
      setLoading(true);

      // build payload from context
      const payload = getPayload();

      // extra safety: ensure payload.stake >= MIN_STAKE
      payload.stake = Math.max(Number(payload?.stake ?? 0), MIN_STAKE);

      if (!Number.isFinite(payload.stake) || payload.stake < MIN_STAKE) {
        toast.error("Invalid stake (client).");
        console.debug("Aborting placeBet — invalid stake in payload:", payload);
        setLoading(false);
        return;
      }

      console.debug("Placing bet - payload:", JSON.stringify(payload));

      const res = await placeBet(payload);

      console.debug("placeBet response:", res);

      const ok = res && (res.success === true || !!res?.betslip_id || !!res?.ticket_id || !!res?.msg);

      if (!ok) {
        const errMsg = res?.error || res?.msg || JSON.stringify(res) || "Bet failed";
        toast.error(`Server: ${errMsg}`);
        return;
      }

      // Update balance if returned; otherwise adjust locally
      const newBalance =
        res?.data?.balance ?? res?.balance ?? res?.data?.user?.balance ?? null;

      if (newBalance !== null && typeof newBalance !== "undefined") {
        setBalance?.(Number(newBalance));
        if (user) setUser?.({ ...user, balance: Number(newBalance) });
      } else {
        setBalance?.((prev) => prev - payload.stake);
      }

      const potential =
        Number(res?.data?.potential_win ?? res?.potential_win ?? potentialWin);

      toast.success(`Bet placed! Potential win KES ${Number(potential).toFixed(2)}`);
      await reloadUser?.();

      // clear local + context state
      clearBetslip();
      setStakeInput("");
    } catch (err) {
      console.error("PLACE BET ERROR:", err);
      const errMsg = err?.message || "Bet failed";
      toast.error(errMsg);
    } finally {
      setLoading(false);
    }
  };

  const handleFocusTotalStake = () => {
    placeBtnRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  return (
    <div className="flex flex-col min-h-screen bg-slate-900 text-white">
      {/* Header */}
      <div className="sticky top-0 z-30 bg-slate-900 p-3 flex items-center justify-between border-b border-slate-700">
        <button
          onClick={() => navigate("/bookmarks")}
          className="text-gray-400 font-bold px-3 py-1 bg-slate-800 rounded"
        >
          ← Back
        </button>

        <h1 className="text-xl font-bold">Betslip ({betslip.length})</h1>

        <button
          onClick={() => { clearBetslip(); setStakeInput(""); }}
          className="text-red-500 font-semibold px-3 py-1 bg-slate-800 rounded"
        >
          Remove All
        </button>
      </div>

      {/* Bets list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {betslip.length === 0 ? (
          <p className="text-gray-400 text-center">No selections yet.</p>
        ) : (
          <div className="space-y-3">
            {betslip.map((b, i) => (
              <div
                key={i}
                className="bg-slate-800 p-3 rounded flex justify-between items-center"
              >
                <div className="flex flex-col gap-1">
                  <div className="text-sm font-medium truncate">
                    {b.match?.home_team} vs {b.match?.away_team}
                  </div>
                  <div className="text-gray-400 text-xs">1X2 • {b.selection}</div>
                  <div className="text-gray-400 text-xs">
                    Starts{" "}
                    {b.match?.match_time
                      ? new Date(b.match.match_time).toLocaleString([], {
                          day: "2-digit",
                          month: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "Unknown"}
                  </div>
                </div>

                <div className="flex flex-col items-end gap-1">
                  <span className="text-green-400 font-semibold">
                    {(Number(b.odds) || 0).toFixed(2)}
                  </span>

                  <button
                    onClick={() => removeBet(b.match.id)}
                    className="text-red-400 font-bold text-lg"
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Bet Controls */}
      {betslip.length > 0 && (
        <div className="sticky bottom-0 left-0 right-0 w-full bg-slate-900 p-3 border-t border-slate-700 flex flex-col gap-2 z-30">
          <div className="flex justify-between text-sm text-gray-200">
            <span>Balance</span>
            <span>KES {Number(balance).toFixed(2)}</span>
          </div>

          <div className="flex justify-between text-sm text-gray-200">
            <span>Total Odds</span>
            <span>{combinedOdds.toFixed(2)}</span>
          </div>

          {/* Total stake input */}
          <div className="flex justify-between text-sm text-gray-200 items-center gap-2">
            <span>Total Stake</span>
            <input
              type="number"
              inputMode="numeric"
              value={stakeInput}
              min={MIN_STAKE}
              max={MAX_STAKE}
              onFocus={handleFocusTotalStake}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "" || /^ *\d*\.?\d*$/.test(v)) setStakeInput(v);

                const n = Number(v);
                if (!Number.isFinite(n) || n < MIN_STAKE) {
                  setTotalStake(MIN_STAKE);
                } else {
                  setTotalStake(n);
                }
              }}
              className="w-40 p-2 rounded bg-slate-700 text-white font-semibold text-right placeholder-gray-400"
              placeholder="Enter stake (KES)"
            />
          </div>

          <div className="flex justify-between text-sm text-gray-200">
            <span>Potential Win</span>
            <span>KES {Number(potentialWin).toFixed(2)}</span>
          </div>

          <button
            ref={placeBtnRef}
            onClick={handlePlaceBet}
            disabled={loading}
            className={
              "w-full font-bold py-3 rounded " +
              (canPlaceBetClient()
                ? "bg-green-500 text-black"
                : "bg-gray-700 text-gray-400 cursor-not-allowed")
            }
          >
            {loading ? "Placing Bet..." : `Place Bet KES ${stakeInput === "" ? "0.00" : Number(stakeInput).toFixed(2)}`}
          </button>
        </div>
      )}
    </div>
  );
}
