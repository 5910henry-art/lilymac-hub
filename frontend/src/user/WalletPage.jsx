// src/user/WalletPage.jsx
import React, { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useUser } from "../contexts/UserContext";
import CountUp from "react-countup";

const ITEMS_PER_PAGE = 2;

function toDateOnly(d) {
  const dt = new Date(d);
  dt.setHours(0, 0, 0, 0);
  return dt.getTime();
}

function isSameDay(a, b) {
  return toDateOnly(a) === toDateOnly(b);
}

function isToday(date) {
  return isSameDay(date, new Date());
}

function isYesterday(date) {
  const today = new Date();
  const y = new Date(today);
  y.setDate(today.getDate() - 1);
  return isSameDay(date, y);
}

const getTxDate = (t) => {
  const raw = t?.time || t?.createdAt || t?.timestamp || t?.date || null;
  if (!raw) return null;
  const d = new Date(raw);
  if (isNaN(d.getTime())) return null;
  return d;
};

export default function WalletPage({ onClose }) {

  const {
    balance,
    bonusBalance,
    updateBalance,
    transactions: ctxTransactions,
    deposit,
    withdraw
  } = useUser();

  const [amount, setAmount] = useState("");
  const [action, setAction] = useState("deposit");
  const [flash, setFlash] = useState(null);

  const [page, setPage] = useState(0);
  const [direction, setDirection] = useState(1);

  /* ---------------- WELCOME BONUS ---------------- */

  useEffect(() => {

    const bonusGiven = localStorage.getItem("welcome_bonus");

    if (!bonusGiven && (!ctxTransactions || ctxTransactions.length === 0)) {

      updateBalance({
        bonusBalance: 50
      });

      localStorage.setItem("welcome_bonus", "true");
    }

  }, []);

  /* ---------------- TRANSACTIONS ---------------- */

  const safeTransactions = useMemo(() => {
    const arr = Array.isArray(ctxTransactions) ? ctxTransactions.slice() : [];

    arr.sort((a, b) => {
      const ta = getTxDate(a)?.getTime() || 0;
      const tb = getTxDate(b)?.getTime() || 0;
      return tb - ta;
    });

    return arr;
  }, [ctxTransactions]);

  const pages = useMemo(() => {

    if (!safeTransactions.length) return [[]];

    const p = [];

    for (let i = 0; i < safeTransactions.length; i += ITEMS_PER_PAGE) {
      p.push(safeTransactions.slice(i, i + ITEMS_PER_PAGE));
    }

    return p.length ? p : [[]];

  }, [safeTransactions]);

  const totalPages = Math.max(1, pages.length);

  useEffect(() => {
    if (page > totalPages - 1) setPage(Math.max(0, totalPages - 1));
  }, [totalPages]);

  const pageItems = pages[page] ?? [];

  const formatTime = (t) => {
    const d = getTxDate(t);
    if (!d) return "--";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  const flashFor = (type) => {
    setFlash(type);
    setTimeout(() => setFlash(null), 700);
  };

  const doDeposit = async (amt) => {
    try {
      await deposit(amt);
      flashFor("deposit");
      setPage(0);
    } catch (err) {
      alert(err?.message || "Deposit failed");
    }
  };

  const doWithdraw = async (amt) => {

    const current = Number(balance) || 0;

    if (amt > current) {
      return alert("Insufficient withdrawable balance");
    }

    try {
      await withdraw(amt);
      flashFor("withdraw");
      setPage(0);
    } catch (err) {
      alert(err?.message || "Withdraw failed");
    }
  };

  const onSubmit = (e) => {
    e.preventDefault();

    const amt = Number(amount);

    if (Number.isNaN(amt) || amt <= 0) {
      alert("Enter valid amount");
      return;
    }

    if (action === "deposit") doDeposit(amt);
    else doWithdraw(amt);

    setAmount("");
  };

  const quickAmounts = [500, 1000, 2000];

  const onQuick = (v) => setAmount(String(v));

  const onWithdrawAll = () => {
    const current = Number(balance) || 0;
    if (current <= 0) return alert("No withdrawable balance");
    doWithdraw(current);
  };

  const goNext = () => {
    if (totalPages <= 1) return;
    setDirection(1);
    setPage((p) => (p + 1) % totalPages);
  };

  const goPrev = () => {
    if (totalPages <= 1) return;
    setDirection(-1);
    setPage((p) => (p - 1 + totalPages) % totalPages);
  };

  const groupedOnPage = useMemo(() => {

    const groups = { Today: [], Yesterday: [], Earlier: [] };

    pageItems.forEach((t) => {

      const d = getTxDate(t);

      if (!d) {
        groups.Earlier.push(t);
        return;
      }

      if (isToday(d)) groups.Today.push(t);
      else if (isYesterday(d)) groups.Yesterday.push(t);
      else groups.Earlier.push(t);

    });

    return groups;

  }, [pageItems]);

  const slideClass = direction === 1 ? "animate-slideLeft" : "animate-slideRight";

  return (
    <AnimatePresence>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 0.4 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black z-30"
        onClick={onClose}
      />

      <motion.div
        initial={{ y: "100%" }}
        animate={{ y: 0 }}
        exit={{ y: "100%" }}
        transition={{ type: "spring", stiffness: 120, damping: 20 }}
        className="fixed bottom-0 left-0 right-0 md:left-auto md:right-4 md:w-[460px] bg-slate-900 z-40 p-6 rounded-t-lg md:rounded-lg max-h-[90vh] flex flex-col shadow-xl"
      >

        <h2 className="text-xl font-bold mb-3 text-white text-center">
          Wallet
        </h2>

        {/* BALANCES */}

        <div className="bg-slate-800 p-4 rounded text-center mb-4">

          <div className="text-white text-lg font-bold">
            Cash: KES <CountUp end={Number(balance || 0)} duration={0.5} decimals={2} />
          </div>

          <div className="text-yellow-400 text-sm mt-1">
            🎁 Bonus: KES <CountUp end={Number(bonusBalance || 0)} duration={0.5} decimals={2} />
          </div>

        </div>

        {/* FORM */}

        <form onSubmit={onSubmit} className="flex flex-col gap-3">

          <select
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="p-2 rounded bg-slate-700 text-white"
          >
            <option value="deposit">Deposit</option>
            <option value="withdraw">Withdraw</option>
          </select>

          <input
            type="number"
            placeholder="Amount"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="p-2 rounded bg-slate-700 text-white"
          />

          <div className="flex gap-2 justify-center">

            {quickAmounts.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => onQuick(q)}
                className="bg-green-500 text-black px-3 py-2 rounded"
              >
                +{q}
              </button>
            ))}

            <button
              type="button"
              onClick={onWithdrawAll}
              className="bg-red-500 text-white px-3 py-2 rounded"
            >
              Withdraw All
            </button>

          </div>

          <button className="w-full bg-green-500 text-black py-2 rounded font-bold">
            {action === "deposit" ? "Deposit" : "Withdraw"}
          </button>

        </form>

        {/* TRANSACTIONS */}

        <div className="flex items-center justify-between mt-4 mb-2">
          <div className="text-white font-semibold">Transactions</div>
          <div className="text-gray-400 text-sm">
            {page + 1}/{totalPages}
          </div>
        </div>

        <div className="relative h-[240px] overflow-hidden bg-slate-800 p-3 rounded">
          <div key={page} className={`${slideClass} h-full overflow-auto`}>

            {Object.entries(groupedOnPage).map(([group, list]) =>
              list.length ? (

                <div key={group} className="mb-3">

                  <div className="text-gray-300 text-sm font-medium mb-2">
                    {group}
                  </div>

                  <div className="space-y-2">

                    {list.map((t, i) => {

                      const dep = t.type === "Deposit";

                      return (

                        <div
                          key={i}
                          className="flex justify-between items-center p-2 rounded bg-slate-700/40"
                        >

                          <div className="flex items-center gap-2">

                            <span className={dep ? "text-green-400" : "text-red-400"}>
                              {dep ? "⬆" : "⬇"}
                            </span>

                            <div className="flex flex-col">
                              <span className="text-white text-sm">{t.type}</span>
                              <span className="text-gray-400 text-xs">{formatTime(t)}</span>
                            </div>

                          </div>

                          <div className={`font-bold ${dep ? "text-green-400" : "text-red-400"}`}>
                            {dep ? "+" : "-"}KES {Number(t.amount).toLocaleString()}
                          </div>

                        </div>

                      );

                    })}

                  </div>

                </div>

              ) : null
            )}

          </div>
        </div>

        <div className="flex justify-center gap-4 mt-3">

          <button
            onClick={goPrev}
            className="w-10 h-10 flex items-center justify-center rounded-full text-xl bg-slate-700 text-white"
          >
            −
          </button>

          <button
            onClick={goNext}
            className="w-10 h-10 flex items-center justify-center rounded-full text-xl bg-green-500 text-black"
          >
            +
          </button>

        </div>

        <button
          onClick={onClose}
          className="w-full mt-4 bg-gray-600 text-white py-3 rounded hover:bg-gray-700"
        >
          Close
        </button>

      </motion.div>

    </AnimatePresence>
  );
}
