// src/user/Betslip.jsx

import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { placeBet } from "../api/betsWallet";
import { useUser } from "../contexts/UserContext";
import { useBetslip } from "../contexts/BetslipContext";
import { toast } from "react-hot-toast";

const MAX_STAKE = 50000;
const MAX_PAYOUT = 200000;
const MIN_STAKE = 1;

function formatMarket(market, selection) {
  const m = String(market || "").toLowerCase();
  const value = String(selection || "").toUpperCase();

  if (m.includes("3way") || m.includes("3-way")) {
    if (value === "HOME") return "Home Win";
    if (value === "AWAY") return "Away Win";
    if (value === "DRAW") return "Draw";
  }

  if (m.includes("btts")) {
    return value === "YES" ? "BTTS Yes" : "BTTS No";
  }

  if (m.includes("o2.5") || m.includes("over 2.5")) {
    return value === "OVER" ? "Over 2.5" : "Under 2.5";
  }

  if (m.includes("o3.5") || m.includes("over 3.5")) {
    return value === "OVER" ? "Over 3.5" : "Under 3.5";
  }

  if (m.includes("o1.5") || m.includes("over 1.5")) {
    return value === "OVER" ? "Over 1.5" : "Under 1.5";
  }

  if (m.includes("o4.5") || m.includes("over 4.5")) {
    return value === "OVER" ? "Over 4.5" : "Under 4.5";
  }

  return value || "Selection";
}

function formatKickoff(value) {
  if (!value) return "Kickoff TBA";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Kickoff TBA";
  }

  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function hasOdds(value) {
  const odds = Number(value);
  return Number.isFinite(odds) && odds > 0;
}

export default function Betslip() {
  const navigate = useNavigate();

  const {
    user,
    balance = 0,
    reloadUser,
    setUser,
    setBalance,
  } = useUser() || {};

  const {
    betslip,
    removeBet,
    clearBetslip,
    combinedOdds,
    totalStake,
    getPayload,
    setTotalStake,
  } = useBetslip();

  const [stakeInput, setStakeInput] = useState(
    totalStake ? String(totalStake) : String(MIN_STAKE)
  );

  const [loading, setLoading] = useState(false);

  const placeBtnRef = useRef(null);

  useEffect(() => {
    reloadUser?.();
  }, [reloadUser]);

  useEffect(() => {
    setStakeInput(
      totalStake ? String(totalStake) : String(MIN_STAKE)
    );
  }, [totalStake]);

  const parseStake = (value) => {
    if (
      value === "" ||
      value === null ||
      typeof value === "undefined"
    ) {
      return 0;
    }

    const number = Number(value);

    return Number.isFinite(number) ? number : 0;
  };

  const effectiveStake = Math.max(
    parseStake(stakeInput),
    MIN_STAKE
  );

  const oddsAvailable =
    betslip.length > 0 &&
    betslip.every((bet) => hasOdds(bet?.odds));

  const potentialWin =
    oddsAvailable && Number(combinedOdds) > 0
      ? effectiveStake * Number(combinedOdds)
      : 0;

  const canPlaceBetClient = () => {
    if (!betslip.length) return false;

    if (effectiveStake < MIN_STAKE) {
      return false;
    }

    if (effectiveStake > MAX_STAKE) {
      return false;
    }

    if (effectiveStake > Number(balance)) {
      return false;
    }

    if (
      potentialWin > 0 &&
      potentialWin > MAX_PAYOUT
    ) {
      return false;
    }

    return true;
  };

  const validateBeforeSend = () => {
    if (!betslip.length) {
      return {
        ok: false,
        msg: "No selections in betslip",
      };
    }

    if (effectiveStake < MIN_STAKE) {
      return {
        ok: false,
        msg: `Stake must be at least KES ${MIN_STAKE}`,
      };
    }

    if (effectiveStake > MAX_STAKE) {
      return {
        ok: false,
        msg: `Stake exceeds the maximum of KES ${MAX_STAKE}`,
      };
    }

    if (effectiveStake > Number(balance)) {
      return {
        ok: false,
        msg: "Insufficient balance",
      };
    }

    if (
      potentialWin > 0 &&
      potentialWin > MAX_PAYOUT
    ) {
      return {
        ok: false,
        msg: `Potential win KES ${potentialWin.toFixed(
          2
        )} exceeds the maximum payout of KES ${MAX_PAYOUT}`,
      };
    }

    return {
      ok: true,
    };
  };

  const handlePlaceBet = async () => {
    const stake = effectiveStake;

    setTotalStake(stake);

    const check = validateBeforeSend();

    if (!check.ok) {
      toast.error(check.msg);
      return;
    }

    const token = localStorage.getItem("token");

    if (!token) {
      toast.error("Please login first.");
      navigate("/auth");
      return;
    }

    try {
      setLoading(true);

      const payload = getPayload();

      payload.stake = Math.max(
        Number(payload?.stake ?? stake),
        MIN_STAKE
      );

      if (
        !Number.isFinite(payload.stake) ||
        payload.stake < MIN_STAKE
      ) {
        toast.error("Invalid stake.");
        return;
      }

      console.debug(
        "Placing bet:",
        JSON.stringify(payload)
      );

      const response = await placeBet(payload);

      console.debug(
        "placeBet response:",
        response
      );

      const success =
        response &&
        (
          response.success === true ||
          !!response?.betslip_id ||
          !!response?.ticket_id ||
          !!response?.msg
        );

      if (!success) {
        const errorMessage =
          response?.error ||
          response?.msg ||
          "Bet placement failed.";

        toast.error(errorMessage);
        return;
      }

      const newBalance =
        response?.data?.balance ??
        response?.balance ??
        response?.data?.user?.balance ??
        null;

      if (
        newBalance !== null &&
        typeof newBalance !== "undefined"
      ) {
        const numericBalance = Number(newBalance);

        setBalance?.(numericBalance);

        if (user) {
          setUser?.({
            ...user,
            balance: numericBalance,
          });
        }
      } else {
        setBalance?.(
          (previous) =>
            Number(previous || 0) - payload.stake
        );
      }

      const serverPotentialWin =
        response?.data?.potential_win ??
        response?.potential_win ??
        null;

      if (
        serverPotentialWin !== null &&
        Number.isFinite(
          Number(serverPotentialWin)
        )
      ) {
        toast.success(
          `Bet placed • Potential win KES ${Number(
            serverPotentialWin
          ).toFixed(2)}`
        );
      } else {
        toast.success("Bet placed successfully.");
      }

      await reloadUser?.();

      clearBetslip();
      setStakeInput("");
    } catch (error) {
      console.error(
        "PLACE BET ERROR:",
        error
      );

      toast.error(
        error?.message ||
          "Unable to place bet."
      );
    } finally {
      setLoading(false);
    }
  };

  const handleFocusTotalStake = () => {
    placeBtnRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  };

  return (
    <div className="min-h-screen bg-[#070b10] text-white">
      {/* Background glow */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-32 left-1/2 h-72 w-72 -translate-x-1/2 rounded-full bg-emerald-500/10 blur-3xl" />
        <div className="absolute bottom-0 right-0 h-64 w-64 rounded-full bg-cyan-500/5 blur-3xl" />
      </div>

      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-white/5 bg-[#070b10]/90 backdrop-blur-xl">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <button
            type="button"
            onClick={() => navigate("/bookmarks")}
            className="flex items-center gap-2 rounded-xl border border-white/5 bg-white/[0.04] px-3 py-2 text-sm font-semibold text-gray-300 transition hover:bg-white/[0.08]"
          >
            <span className="text-lg">←</span>
            <span className="hidden sm:inline">
              Back
            </span>
          </button>

          <div className="text-center">
            <div className="text-[9px] font-black uppercase tracking-[0.25em] text-emerald-400">
              LilyMac Hub
            </div>

            <h1 className="mt-0.5 text-lg font-black tracking-tight sm:text-xl">
              Betslip
            </h1>
          </div>

          <button
            type="button"
            onClick={() => {
              clearBetslip();
              setStakeInput("");
            }}
            disabled={!betslip.length}
            className="rounded-xl border border-red-500/10 bg-red-500/5 px-3 py-2 text-xs font-bold text-red-400 transition hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Clear
          </button>
        </div>
      </header>

      <main className="relative mx-auto max-w-4xl px-4 py-5 pb-52 sm:px-6 sm:py-7">
        {/* Hero */}
        <section className="mb-5 rounded-3xl border border-white/5 bg-gradient-to-br from-white/[0.06] to-white/[0.02] p-5 shadow-2xl shadow-black/20">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/10 text-lg">
                  ⚽
                </span>

                <div>
                  <p className="text-[10px] font-black uppercase tracking-[0.2em] text-gray-500">
                    Your selections
                  </p>

                  <h2 className="mt-0.5 text-xl font-black tracking-tight">
                    {betslip.length}{" "}
                    {betslip.length === 1
                      ? "selection"
                      : "selections"}
                  </h2>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-emerald-500/10 bg-emerald-500/5 px-4 py-3 text-right">
              <div className="text-[9px] font-black uppercase tracking-widest text-gray-500">
                Balance
              </div>

              <div className="mt-0.5 text-sm font-black text-emerald-400">
                KES{" "}
                {Number(balance || 0).toLocaleString(
                  "en-KE",
                  {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  }
                )}
              </div>
            </div>
          </div>
        </section>

        {/* Empty state */}
        {betslip.length === 0 ? (
          <section className="rounded-3xl border border-white/5 bg-white/[0.03] p-10 text-center">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-emerald-500/10 text-3xl">
              🧾
            </div>

            <h2 className="mt-5 text-xl font-black">
              Your betslip is empty
            </h2>

            <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-gray-500">
              Add selections from matches or
              accumulator tips and they will appear here.
            </p>

            <button
              type="button"
              onClick={() => navigate("/")}
              className="mt-6 rounded-xl bg-emerald-500 px-5 py-3 text-sm font-black text-black transition hover:bg-emerald-400"
            >
              Browse Tips
            </button>
          </section>
        ) : (
          <section className="space-y-3">
            {betslip.map((bet, index) => {
              const marketLabel = formatMarket(
                bet?.market,
                bet?.selection
              );

              const oddsPresent = hasOdds(
                bet?.odds
              );

              return (
                <article
                  key={
                    bet?.id ??
                    `${bet?.match?.id}-${bet?.market}-${index}`
                  }
                  className="group overflow-hidden rounded-2xl border border-white/5 bg-white/[0.035] shadow-lg shadow-black/10 transition hover:border-white/10 hover:bg-white/[0.05]"
                >
                  <div className="p-4 sm:p-5">
                    <div className="flex items-start gap-3">
                      {/* Number */}
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gray-800 text-xs font-black text-gray-400">
                        {String(index + 1).padStart(
                          2,
                          "0"
                        )}
                      </div>

                      <div className="min-w-0 flex-1">
                        {/* Teams */}
                        <div className="pr-2">
                          <h3 className="truncate text-sm font-black text-white sm:text-base">
                            {bet?.match?.home_team ||
                              "Home Team"}
                          </h3>

                          <div className="my-1 text-[9px] font-black uppercase tracking-[0.18em] text-gray-600">
                            VS
                          </div>

                          <h3 className="truncate text-sm font-black text-white sm:text-base">
                            {bet?.match?.away_team ||
                              "Away Team"}
                          </h3>
                        </div>

                        {/* Selection */}
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <span className="rounded-lg bg-emerald-500/10 px-2.5 py-1.5 text-[11px] font-black text-emerald-400">
                            {marketLabel}
                          </span>

                          <span className="rounded-lg bg-white/[0.04] px-2.5 py-1.5 text-[11px] font-semibold text-gray-400">
                            {formatKickoff(
                              bet?.match?.match_time ??
                                bet?.match?.kickoff
                            )}
                          </span>
                        </div>
                      </div>

                      {/* Remove */}
                      <button
                        type="button"
                        onClick={() =>
                          removeBet(
                            bet?.id ??
                              bet?.match?.id
                          )
                        }
                        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-red-500/5 text-lg text-red-400 transition hover:bg-red-500/10"
                        aria-label="Remove selection"
                      >
                        ×
                      </button>
                    </div>

                    {/* Odds status */}
                    <div className="mt-4 flex items-center justify-between border-t border-white/5 pt-3">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-gray-600">
                        {oddsPresent
                          ? "Selection odds"
                          : "Odds"}
                      </span>

                      <span
                        className={`text-xs font-black ${
                          oddsPresent
                            ? "text-emerald-400"
                            : "text-gray-500"
                        }`}
                      >
                        {oddsPresent
                          ? `@${Number(
                              bet.odds
                            ).toFixed(2)}`
                          : "Calculated at placement"}
                      </span>
                    </div>
                  </div>
                </article>
              );
            })}
          </section>
        )}

        {/* Information */}
        {betslip.length > 0 && (
          <div className="mt-5 rounded-2xl border border-cyan-500/10 bg-cyan-500/5 p-4">
            <div className="flex gap-3">
              <span className="text-lg">ℹ️</span>

              <div>
                <p className="text-xs font-bold text-cyan-300">
                  Betting information
                </p>

                <p className="mt-1 text-xs leading-5 text-gray-500">
                  Selections added from accumulator tips
                  are submitted with the fixture and
                  selection. Odds can be calculated by the
                  betting service when the bet is placed.
                </p>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Bottom controls */}
      {betslip.length > 0 && (
        <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-white/5 bg-[#070b10]/95 backdrop-blur-xl">
          <div className="mx-auto max-w-4xl px-4 py-3 sm:px-6">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-xl bg-white/[0.035] px-3 py-2.5">
                <div className="text-[9px] font-black uppercase tracking-widest text-gray-600">
                  Total odds
                </div>

                <div className="mt-1 font-black text-white">
                  {oddsAvailable &&
                  Number(combinedOdds) > 0
                    ? `@${Number(
                        combinedOdds
                      ).toFixed(2)}`
                    : "—"}
                </div>
              </div>

              <div className="rounded-xl bg-white/[0.035] px-3 py-2.5 text-right">
                <div className="text-[9px] font-black uppercase tracking-widest text-gray-600">
                  Balance
                </div>

                <div className="mt-1 font-black text-emerald-400">
                  KES{" "}
                  {Number(balance || 0).toFixed(2)}
                </div>
              </div>
            </div>

            {/* Stake */}
            <div className="mt-3 flex items-center gap-3 rounded-2xl border border-white/5 bg-white/[0.035] p-3">
              <div className="min-w-0 flex-1">
                <div className="text-[9px] font-black uppercase tracking-widest text-gray-600">
                  Stake
                </div>

                <input
                  type="number"
                  inputMode="decimal"
                  value={stakeInput}
                  min={MIN_STAKE}
                  max={MAX_STAKE}
                  onFocus={handleFocusTotalStake}
                  onChange={(event) => {
                    const value =
                      event.target.value;

                    if (
                      value === "" ||
                      /^\d*\.?\d*$/.test(value)
                    ) {
                      setStakeInput(value);
                    }

                    const numericValue =
                      Number(value);

                    if (
                      !Number.isFinite(
                        numericValue
                      ) ||
                      numericValue < MIN_STAKE
                    ) {
                      setTotalStake(MIN_STAKE);
                    } else {
                      setTotalStake(
                        numericValue
                      );
                    }
                  }}
                  className="mt-1 w-full bg-transparent text-lg font-black text-white outline-none"
                  placeholder="KES 1"
                />
              </div>

              <div className="border-l border-white/5 pl-3 text-right">
                <div className="text-[9px] font-black uppercase tracking-widest text-gray-600">
                  Potential
                </div>

                <div className="mt-1 text-sm font-black text-emerald-400">
                  {potentialWin > 0
                    ? `KES ${potentialWin.toFixed(
                        2
                      )}`
                    : "Calculated at placement"}
                </div>
              </div>
            </div>

            {/* Place bet */}
            <button
              ref={placeBtnRef}
              type="button"
              onClick={handlePlaceBet}
              disabled={
                loading ||
                !canPlaceBetClient()
              }
              className={`mt-3 w-full rounded-2xl px-4 py-3.5 text-sm font-black tracking-wide transition ${
                loading ||
                !canPlaceBetClient()
                  ? "cursor-not-allowed bg-gray-800 text-gray-600"
                  : "bg-emerald-500 text-black shadow-lg shadow-emerald-500/10 hover:bg-emerald-400 active:scale-[0.99]"
              }`}
            >
              {loading
                ? "PLACING BET..."
                : `PLACE BET • KES ${
                    stakeInput === ""
                      ? "0.00"
                      : Number(
                          stakeInput
                        ).toFixed(2)
                  }`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
