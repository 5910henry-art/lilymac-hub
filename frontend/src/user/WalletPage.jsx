// src/user/WalletPage.jsx

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import CountUp from "react-countup";
import { useUser } from "../contexts/UserContext";

const ITEMS_PER_PAGE = 5;

const QUICK_AMOUNTS = [500, 1000, 2000, 5000];

const PLACEHOLDER_AMOUNT = "0";

/* =========================================================
   TRANSACTION HELPERS
========================================================= */

function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function normalizeType(type) {
  return String(type || "transaction")
    .toLowerCase()
    .trim();
}

function getTransactionDate(transaction) {
  const raw =
    transaction?.created_at ??
    transaction?.createdAt ??
    transaction?.created ??
    transaction?.time ??
    transaction?.date ??
    transaction?.timestamp ??
    null;

  if (!raw) return null;

  if (raw instanceof Date) {
    return Number.isNaN(raw.getTime())
      ? null
      : raw;
  }

  const value = String(raw).trim();

  if (!value) return null;

  const date = new Date(value);

  if (!Number.isNaN(date.getTime())) {
    return date;
  }

  const normalized = value.includes(" ")
    ? value.replace(" ", "T")
    : value;

  const fallback = new Date(normalized);

  return Number.isNaN(fallback.getTime())
    ? null
    : fallback;
}

function formatNumber(value) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "0.00";
  }

  return number.toLocaleString("en-KE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/*
 * Same date/time formatter used by the
 * previous TransactionHistory.jsx.
 *
 * Example:
 * 07 Sep 2026, 03:26 PM
 */
function formatDateTime(value) {
  const date =
    value instanceof Date
      ? value
      : new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Unknown date";
  }

  return date.toLocaleString("en-KE", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Africa/Nairobi",
  });
}

/* =========================================================
   TRANSACTION TYPE / DIRECTION
========================================================= */

function isCreditType(type) {
  return [
    "deposit",
    "win",
    "cashout",
    "credit",
    "refund",
    "bonus",
    "reward",
  ].includes(normalizeType(type));
}

function isDebitType(type) {
  return [
    "withdraw",
    "withdrawal",
    "bet",
    "debit",
    "stake",
    "fee",
  ].includes(normalizeType(type));
}

function getDirection(type) {
  if (isCreditType(type)) {
    return "credit";
  }

  if (isDebitType(type)) {
    return "debit";
  }

  return "neutral";
}

function getTransactionIcon(type) {
  const normalized = normalizeType(type);

  if (normalized === "deposit") return "↓";

  if (
    normalized === "withdraw" ||
    normalized === "withdrawal"
  ) {
    return "↑";
  }

  if (
    normalized === "bet" ||
    normalized === "stake"
  ) {
    return "🎯";
  }

  if (normalized === "win") return "🏆";

  if (normalized === "cashout") return "💰";

  if (
    normalized === "bonus" ||
    normalized === "reward"
  ) {
    return "🎁";
  }

  if (normalized === "refund") return "↩";

  if (normalized === "credit") return "↓";

  return "•";
}

function getTransactionTheme(type) {
  const normalized = normalizeType(type);

  if (isCreditType(normalized)) {
    return {
      icon:
        "bg-emerald-500/10 text-emerald-400 border-emerald-500/10",
      amount: "text-emerald-400",
      badge:
        "bg-emerald-500/10 text-emerald-400 border-emerald-500/10",
    };
  }

  if (isDebitType(normalized)) {
    return {
      icon:
        "bg-red-500/10 text-red-400 border-red-500/10",
      amount: "text-red-400",
      badge:
        "bg-red-500/10 text-red-400 border-red-500/10",
    };
  }

  return {
    icon:
      "bg-slate-700 text-slate-300 border-slate-600",
    amount: "text-slate-300",
    badge:
      "bg-slate-800 text-slate-400 border-slate-700",
  };
}

function getTransactionLabel(transaction) {
  const type =
    transaction?.type ??
    transaction?.transaction_type ??
    transaction?.transactionType ??
    transaction?.kind ??
    "transaction";

  return String(type)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) =>
      letter.toUpperCase()
    );
}

/* =========================================================
   DATE GROUPING
   Nairobi timezone
========================================================= */

function isToday(transaction) {
  const date = getTransactionDate(transaction);

  if (!date) return false;

  const now = new Date();

  return (
    date.toLocaleDateString("en-KE", {
      timeZone: "Africa/Nairobi",
    }) ===
    now.toLocaleDateString("en-KE", {
      timeZone: "Africa/Nairobi",
    })
  );
}

function isYesterday(transaction) {
  const date = getTransactionDate(transaction);

  if (!date) return false;

  const now = new Date();

  const yesterday = new Date(now);

  yesterday.setDate(
    yesterday.getDate() - 1
  );

  return (
    date.toLocaleDateString("en-KE", {
      timeZone: "Africa/Nairobi",
    }) ===
    yesterday.toLocaleDateString("en-KE", {
      timeZone: "Africa/Nairobi",
    })
  );
}

/* =========================================================
   MAIN COMPONENT
========================================================= */

export default function WalletPage({ onClose }) {
  const {
    balance,
    bonusBalance,
    updateBalance,
    transactions: ctxTransactions,
    deposit,
    withdraw,
  } = useUser();

  const [amount, setAmount] = useState("");

  const [action, setAction] = useState(
    "deposit"
  );

  const [processing, setProcessing] =
    useState(false);

  const [message, setMessage] = useState(null);

  const [search, setSearch] = useState("");

  const [filter, setFilter] = useState("all");

  const [page, setPage] = useState(0);

  const [
    showAllTransactions,
    setShowAllTransactions,
  ] = useState(false);

  /* =======================================================
     SAFE WELCOME BONUS
  ======================================================= */

  useEffect(() => {
    const bonusGiven =
      localStorage.getItem(
        "welcome_bonus"
      );

    const hasTransactions =
      Array.isArray(ctxTransactions) &&
      ctxTransactions.length > 0;

    if (
      !bonusGiven &&
      !hasTransactions
    ) {
      updateBalance({
        bonusBalance: 50,
      });

      localStorage.setItem(
        "welcome_bonus",
        "true"
      );
    }
  }, [
    ctxTransactions,
    updateBalance,
  ]);

  /* =======================================================
     FLASH MESSAGE
  ======================================================= */

  const showMessage = useCallback(
    (type, text) => {
      setMessage({
        type,
        text,
      });

      window.setTimeout(() => {
        setMessage(null);
      }, 3500);
    },
    []
  );

  /* =======================================================
     TRANSACTIONS
     
     UserContext is the single source of truth.

     No:
     - reloadUser()
     - explicit transaction API reload
     - window.location.reload()
     - loadingUser cycle
  ======================================================= */

  const transactions = useMemo(() => {
    const list = Array.isArray(
      ctxTransactions
    )
      ? [...ctxTransactions]
      : [];

    return list.sort((a, b) => {
      const dateA =
        getTransactionDate(
          a
        )?.getTime() || 0;

      const dateB =
        getTransactionDate(
          b
        )?.getTime() || 0;

      return dateB - dateA;
    });
  }, [ctxTransactions]);

  /* =======================================================
     FILTER TRANSACTIONS
  ======================================================= */

  const filteredTransactions =
    useMemo(() => {
      const query = search
        .trim()
        .toLowerCase();

      return transactions.filter(
        (transaction) => {
          const type =
            normalizeType(
              transaction?.type ??
                transaction?.transaction_type ??
                transaction?.transactionType ??
                transaction?.kind
            );

          let matchesFilter = true;

          if (filter === "credit") {
            matchesFilter =
              isCreditType(type);
          }

          if (filter === "debit") {
            matchesFilter =
              isDebitType(type);
          }

          if (filter === "deposit") {
            matchesFilter =
              type === "deposit";
          }

          if (
            filter === "withdraw" ||
            filter === "withdrawal"
          ) {
            matchesFilter =
              type === "withdraw" ||
              type === "withdrawal";
          }

          if (!matchesFilter) {
            return false;
          }

          if (!query) {
            return true;
          }

          const date =
            getTransactionDate(
              transaction
            );

          const searchableText = [
            transaction?.id,
            transaction?.transaction_id,
            transaction?.transactionId,
            transaction?.type,
            transaction?.transaction_type,
            transaction?.transactionType,
            transaction?.kind,
            transaction?.description,
            transaction?.reason,
            transaction?.note,
            transaction?.reference,
            transaction?.status,
            transaction?.state,
            transaction?.amount,
            transaction?.value,
            transaction?.transaction_amount,
            transaction?.transactionAmount,
            transaction?.balance_after,
            transaction?.balanceAfter,
            transaction?.running_balance,
            transaction?.runningBalance,
            date
              ? formatDateTime(date)
              : "",
          ]
            .filter(
              (value) =>
                value !== null &&
                value !== undefined &&
                value !== ""
            )
            .join(" ")
            .toLowerCase();

          return searchableText.includes(
            query
          );
        }
      );
    }, [
      transactions,
      filter,
      search,
    ]);

  /* =======================================================
     PAGINATION
  ======================================================= */

  const totalPages = Math.max(
    1,
    Math.ceil(
      filteredTransactions.length /
        ITEMS_PER_PAGE
    )
  );

  useEffect(() => {
    setPage(0);
  }, [search, filter]);

  useEffect(() => {
    if (page >= totalPages) {
      setPage(
        Math.max(
          0,
          totalPages - 1
        )
      );
    }
  }, [
    page,
    totalPages,
  ]);

  const pageTransactions =
    useMemo(() => {
      if (showAllTransactions) {
        return filteredTransactions;
      }

      const start =
        page * ITEMS_PER_PAGE;

      return filteredTransactions.slice(
        start,
        start + ITEMS_PER_PAGE
      );
    }, [
      filteredTransactions,
      page,
      showAllTransactions,
    ]);

  /* =======================================================
     TRANSACTION SUMMARY
  ======================================================= */

  const transactionStats =
    useMemo(() => {
      let credits = 0;
      let debits = 0;

      transactions.forEach(
        (transaction) => {
          const amount =
            safeNumber(
              transaction?.amount ??
                transaction?.value ??
                transaction?.transaction_amount ??
                transaction?.transactionAmount
            );

          const type =
            normalizeType(
              transaction?.type ??
                transaction?.transaction_type ??
                transaction?.transactionType ??
                transaction?.kind
            );

          if (isCreditType(type)) {
            credits += amount;
          }

          if (isDebitType(type)) {
            debits += amount;
          }
        }
      );

      return {
        credits,
        debits,
        count: transactions.length,
      };
    }, [transactions]);

  /* =======================================================
     AMOUNT
  ======================================================= */

  const numericAmount =
    Number(amount);

  const validAmount =
    Number.isFinite(
      numericAmount
    ) &&
    numericAmount > 0;

  const currentBalance =
    safeNumber(balance);

  const currentBonusBalance =
    safeNumber(bonusBalance);

  /* =======================================================
     DEPOSIT
  ======================================================= */

  const handleDeposit =
    async (value) => {
      if (processing) return;

      if (
        !Number.isFinite(value) ||
        value <= 0
      ) {
        showMessage(
          "error",
          "Enter a valid deposit amount."
        );

        return;
      }

      setProcessing(true);

      try {
        /*
         * UserContext deposit()
         * updates shared wallet state.
         *
         * We intentionally do NOT call:
         * - reloadUser()
         * - loadAnalytics()
         * - window.location.reload()
         */

        await deposit(value);

        setAmount("");

        setPage(0);

        showMessage(
          "success",
          `M-PESA STK Push sent for KES ${formatNumber(
            value
          )}. Enter your M-PESA PIN to complete the deposit.`
        );
      } catch (error) {
        console.error(
          "Deposit failed:",
          error
        );

        showMessage(
          "error",
          error?.message ||
            "Deposit failed. Please try again."
        );
      } finally {
        setProcessing(false);
      }
    };

  /* =======================================================
     WITHDRAW
  ======================================================= */

  const handleWithdraw =
    async (value) => {
      if (processing) return;

      if (
        !Number.isFinite(value) ||
        value <= 0
      ) {
        showMessage(
          "error",
          "Enter a valid withdrawal amount."
        );

        return;
      }

      if (
        value > currentBalance
      ) {
        showMessage(
          "error",
          "Insufficient withdrawable balance."
        );

        return;
      }

      setProcessing(true);

      try {
        /*
         * UserContext withdraw()
         * updates shared wallet state.
         *
         * No reloadUser().
         * No full user loading cycle.
         */

        await withdraw(value);

        setAmount("");

        setPage(0);

        showMessage(
          "success",
          `KES ${formatNumber(
            value
          )} withdrawn successfully.`
        );
      } catch (error) {
        console.error(
          "Withdrawal failed:",
          error
        );

        showMessage(
          "error",
          error?.message ||
            "Withdrawal failed. Please try again."
        );
      } finally {
        setProcessing(false);
      }
    };

  /* =======================================================
     FORM
  ======================================================= */

  const handleSubmit =
    async (event) => {
      event.preventDefault();

      if (!validAmount) {
        showMessage(
          "error",
          "Enter a valid amount."
        );

        return;
      }

      if (
        action === "deposit"
      ) {
        await handleDeposit(
          numericAmount
        );
      } else {
        await handleWithdraw(
          numericAmount
        );
      }
    };

  /* =======================================================
     QUICK AMOUNT
  ======================================================= */

  const handleQuickAmount =
    (value) => {
      setAmount(
        String(value)
      );
    };

  /* =======================================================
     WITHDRAW ALL
  ======================================================= */

  const handleWithdrawAll =
    async () => {
      if (processing) return;

      if (
        currentBalance <= 0
      ) {
        showMessage(
          "error",
          "You have no withdrawable balance."
        );

        return;
      }

      const confirmed =
        window.confirm(
          `Withdraw your full balance of KES ${formatNumber(
            currentBalance
          )}?`
        );

      if (!confirmed) {
        return;
      }

      setAction("withdraw");

      await handleWithdraw(
        currentBalance
      );
    };

  /* =======================================================
     ESCAPE KEY
  ======================================================= */

  useEffect(() => {
    const handleKeyDown =
      (event) => {
        if (
          event.key ===
          "Escape"
        ) {
          onClose?.();
        }
      };

    window.addEventListener(
      "keydown",
      handleKeyDown
    );

    return () => {
      window.removeEventListener(
        "keydown",
        handleKeyDown
      );
    };
  }, [onClose]);

  /* =======================================================
     GROUP TRANSACTIONS
  ======================================================= */

  const groupedTransactions =
    useMemo(() => {
      const groups = {
        Today: [],
        Yesterday: [],
        Earlier: [],
      };

      pageTransactions.forEach(
        (transaction) => {
          if (
            isToday(transaction)
          ) {
            groups.Today.push(
              transaction
            );
          } else if (
            isYesterday(
              transaction
            )
          ) {
            groups.Yesterday.push(
              transaction
            );
          } else {
            groups.Earlier.push(
              transaction
            );
          }
        }
      );

      return groups;
    }, [pageTransactions]);

  /* =======================================================
     RENDER
  ======================================================= */

  return (
    <AnimatePresence>
      {/* =================================================
          BACKDROP
      ================================================= */}

      <motion.div
        initial={{
          opacity: 0,
        }}
        animate={{
          opacity: 1,
        }}
        exit={{
          opacity: 0,
        }}
        transition={{
          duration: 0.2,
        }}
        className="
          fixed
          inset-0
          bg-black/70
          backdrop-blur-sm
          z-40
        "
        onClick={onClose}
      />

      {/* =================================================
          WALLET
      ================================================= */}

      <motion.div
        initial={{
          opacity: 0,
          y: "100%",
        }}
        animate={{
          opacity: 1,
          y: 0,
        }}
        exit={{
          opacity: 0,
          y: "100%",
        }}
        transition={{
          type: "spring",
          stiffness: 150,
          damping: 24,
        }}
        className="
          fixed
          bottom-0
          left-0
          right-0
          md:left-auto
          md:right-5
          md:bottom-5
          md:w-[480px]
          z-50
          max-h-[94vh]
          flex
          flex-col
          overflow-hidden
          rounded-t-[28px]
          md:rounded-[28px]
          border
          border-white/10
          bg-slate-950
          shadow-2xl
        "
        role="dialog"
        aria-modal="true"
        aria-label="Wallet"
      >
        {/* =================================================
            DRAG HANDLE
        ================================================= */}

        <div className="flex justify-center pt-3 md:hidden">
          <div className="
            w-12
            h-1.5
            rounded-full
            bg-slate-700
          " />
        </div>

        {/* =================================================
            HEADER
        ================================================= */}

        <div className="
          flex
          items-center
          justify-between
          px-5
          pt-4
          pb-3
        ">
          <div>
            <h2 className="
              text-xl
              font-black
              text-white
            ">
              My Wallet
            </h2>

            <p className="
              text-xs
              text-slate-400
              mt-0.5
            ">
              Manage your funds
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="
              w-9
              h-9
              rounded-full
              flex
              items-center
              justify-center
              bg-slate-800
              text-slate-300
              hover:bg-slate-700
              hover:text-white
              transition
            "
            aria-label="Close wallet"
          >
            ×
          </button>
        </div>

        {/* =================================================
            CONTENT
        ================================================= */}

        <div className="
          overflow-y-auto
          px-5
          pb-6
          space-y-5
        ">

          {/* =================================================
              SUCCESS / ERROR MESSAGE
          ================================================= */}

          <AnimatePresence>
            {message && (
              <motion.div
                initial={{
                  opacity: 0,
                  y: -10,
                }}
                animate={{
                  opacity: 1,
                  y: 0,
                }}
                exit={{
                  opacity: 0,
                  y: -10,
                }}
                className={`
                  rounded-2xl
                  border
                  px-4
                  py-3
                  text-sm
                  font-medium
                  ${
                    message.type ===
                    "success"
                      ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                      : "bg-red-500/10 border-red-500/20 text-red-400"
                  }
                `}
              >
                <div className="
                  flex
                  items-center
                  gap-2
                ">
                  <span>
                    {message.type ===
                    "success"
                      ? "✓"
                      : "!"}
                  </span>

                  <span>
                    {message.text}
                  </span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* =================================================
              BALANCE CARDS
          ================================================= */}

          <div className="
            grid
            grid-cols-2
            gap-3
          ">

            {/* CASH BALANCE */}

            <div className="
              relative
              overflow-hidden
              rounded-2xl
              border
              border-emerald-500/20
              bg-gradient-to-br
              from-emerald-500/15
              to-slate-900
              p-4
            ">
              <div className="
                flex
                items-center
                justify-between
              ">
                <span className="
                  text-xs
                  text-slate-400
                ">
                  Cash Balance
                </span>

                <span className="
                  w-7
                  h-7
                  rounded-full
                  bg-emerald-500/15
                  flex
                  items-center
                  justify-center
                  text-emerald-400
                  text-sm
                ">
                  K
                </span>
              </div>

              <div className="mt-3">
                <span className="
                  text-xs
                  text-slate-500
                ">
                  KES
                </span>

                <div className="
                  text-xl
                  font-black
                  text-white
                  mt-0.5
                ">
                  <CountUp
                    end={
                      currentBalance
                    }
                    duration={0.6}
                    decimals={2}
                    separator=","
                  />
                </div>
              </div>

              <div className="
                absolute
                -right-8
                -bottom-8
                w-24
                h-24
                rounded-full
                bg-emerald-500/5
              " />
            </div>

            {/* BONUS */}

            <div className="
              relative
              overflow-hidden
              rounded-2xl
              border
              border-yellow-500/20
              bg-gradient-to-br
              from-yellow-500/15
              to-slate-900
              p-4
            ">
              <div className="
                flex
                items-center
                justify-between
              ">
                <span className="
                  text-xs
                  text-slate-400
                ">
                  Bonus
                </span>

                <span className="
                  w-7
                  h-7
                  rounded-full
                  bg-yellow-500/15
                  flex
                  items-center
                  justify-center
                  text-yellow-400
                  text-sm
                ">
                  🎁
                </span>
              </div>

              <div className="mt-3">
                <span className="
                  text-xs
                  text-slate-500
                ">
                  KES
                </span>

                <div className="
                  text-xl
                  font-black
                  text-yellow-400
                  mt-0.5
                ">
                  <CountUp
                    end={
                      currentBonusBalance
                    }
                    duration={0.6}
                    decimals={2}
                    separator=","
                  />
                </div>
              </div>
            </div>
          </div>

          {/* =================================================
              WALLET ACTION
          ================================================= */}

          <div className="
            rounded-2xl
            border
            border-white/10
            bg-slate-900
            p-4
          ">

            {/* TABS */}

            <div className="
              grid
              grid-cols-2
              gap-1
              p-1
              bg-slate-800
              rounded-xl
              mb-4
            ">
              <button
                type="button"
                onClick={() => {
                  setAction(
                    "deposit"
                  );
                  setAmount("");
                }}
                className={`
                  py-2.5
                  rounded-lg
                  text-sm
                  font-bold
                  transition
                  ${
                    action ===
                    "deposit"
                      ? "bg-emerald-500 text-slate-950 shadow"
                      : "text-slate-400 hover:text-white"
                  }
                `}
              >
                Deposit
              </button>

              <button
                type="button"
                onClick={() => {
                  setAction(
                    "withdraw"
                  );
                  setAmount("");
                }}
                className={`
                  py-2.5
                  rounded-lg
                  text-sm
                  font-bold
                  transition
                  ${
                    action ===
                    "withdraw"
                      ? "bg-red-500 text-white shadow"
                      : "text-slate-400 hover:text-white"
                  }
                `}
              >
                Withdraw
              </button>
            </div>

            {/* AMOUNT */}

            <form
              onSubmit={
                handleSubmit
              }
              className="space-y-4"
            >
              <div>
                <label
                  htmlFor="wallet-amount"
                  className="
                    block
                    text-xs
                    font-semibold
                    text-slate-400
                    mb-2
                  "
                >
                  Amount
                </label>

                <div className="
                  flex
                  items-center
                  gap-2
                  rounded-xl
                  border
                  border-white/10
                  bg-slate-800
                  px-3
                  focus-within:border-emerald-500/50
                  transition
                ">
                  <span className="
                    text-sm
                    font-bold
                    text-slate-500
                  ">
                    KES
                  </span>

                  <input
                    id="wallet-amount"
                    type="number"
                    min="1"
                    step="0.01"
                    inputMode="decimal"
                    value={amount}
                    onChange={(event) =>
                      setAmount(
                        event.target.value
                      )
                    }
                    placeholder={
                      PLACEHOLDER_AMOUNT
                    }
                    disabled={
                      processing
                    }
                    className="
                      w-full
                      bg-transparent
                      py-3
                      outline-none
                      text-white
                      font-bold
                      placeholder:text-slate-600
                    "
                  />
                </div>
              </div>

              {/* QUICK AMOUNTS */}

              <div>
                <div className="
                  flex
                  items-center
                  justify-between
                  mb-2
                ">
                  <span className="
                    text-xs
                    font-semibold
                    text-slate-500
                  ">
                    Quick amount
                  </span>

                  {action ===
                    "withdraw" && (
                    <span className="
                      text-xs
                      text-slate-500
                    ">
                      Available: KES{" "}
                      {formatNumber(
                        currentBalance
                      )}
                    </span>
                  )}
                </div>

                <div className="
                  grid
                  grid-cols-4
                  gap-2
                ">
                  {QUICK_AMOUNTS.map(
                    (quickAmount) => (
                      <button
                        key={
                          quickAmount
                        }
                        type="button"
                        disabled={
                          processing
                        }
                        onClick={() =>
                          handleQuickAmount(
                            quickAmount
                          )
                        }
                        className="
                          py-2
                          rounded-lg
                          bg-slate-800
                          border
                          border-white/5
                          text-xs
                          font-bold
                          text-slate-300
                          hover:bg-slate-700
                          hover:text-white
                          transition
                          disabled:opacity-50
                        "
                      >
                        {quickAmount.toLocaleString()}
                      </button>
                    )
                  )}
                </div>
              </div>

              {/* SUBMIT */}

              <div className="
                flex
                gap-2
              ">
                {action ===
                  "withdraw" && (
                  <button
                    type="button"
                    onClick={
                      handleWithdrawAll
                    }
                    disabled={
                      processing ||
                      currentBalance <=
                        0
                    }
                    className="
                      px-4
                      rounded-xl
                      bg-slate-800
                      border
                      border-white/10
                      text-xs
                      font-bold
                      text-slate-300
                      hover:bg-slate-700
                      disabled:opacity-40
                      transition
                    "
                  >
                    All
                  </button>
                )}

                <button
                  type="submit"
                  disabled={
                    processing ||
                    !validAmount
                  }
                  className={`
                    flex-1
                    py-3
                    rounded-xl
                    font-black
                    text-sm
                    transition
                    disabled:opacity-40
                    disabled:cursor-not-allowed
                    ${
                      action ===
                      "deposit"
                        ? "bg-emerald-500 text-slate-950 hover:bg-emerald-400"
                        : "bg-red-500 text-white hover:bg-red-400"
                    }
                  `}
                >
                  {processing ? (
                    <span className="
                      flex
                      items-center
                      justify-center
                      gap-2
                    ">
                      <span className="
                        w-4
                        h-4
                        rounded-full
                        border-2
                        border-current
                        border-t-transparent
                        animate-spin
                      " />

                      Processing...
                    </span>
                  ) : action ===
                    "deposit" ? (
                    "Deposit Funds"
                  ) : (
                    "Withdraw Funds"
                  )}
                </button>
              </div>
            </form>
          </div>

          {/* =================================================
              TRANSACTION HEADER
          ================================================= */}

          <div>
            <div className="
              flex
              items-center
              justify-between
              mb-3
            ">
              <div>
                <h3 className="
                  text-base
                  font-black
                  text-white
                ">
                  Transactions
                </h3>

                <p className="
                  text-xs
                  text-slate-500
                  mt-0.5
                ">
                  {transactionStats.count}{" "}
                  total
                </p>
              </div>

              <button
                type="button"
                onClick={() =>
                  setShowAllTransactions(
                    (value) =>
                      !value
                  )
                }
                className="
                  text-xs
                  font-bold
                  text-emerald-400
                  hover:text-emerald-300
                "
              >
                {showAllTransactions
                  ? "Paginate"
                  : "View all"}
              </button>
            </div>

            {/* SEARCH */}

            <div className="
              relative
              mb-3
            ">
              <span className="
                absolute
                left-3
                top-1/2
                -translate-y-1/2
                text-slate-500
              ">
                ⌕
              </span>

              <input
                type="search"
                value={search}
                onChange={(event) =>
                  setSearch(
                    event.target.value
                  )
                }
                placeholder="Search transactions..."
                className="
                  w-full
                  rounded-xl
                  border
                  border-white/10
                  bg-slate-900
                  py-2.5
                  pl-9
                  pr-3
                  text-sm
                  text-white
                  outline-none
                  placeholder:text-slate-600
                  focus:border-emerald-500/40
                "
              />
            </div>

            {/* FILTERS */}

            <div className="
              flex
              gap-2
              overflow-x-auto
              pb-1
            ">
              {[
                ["all", "All"],
                ["credit", "Credits"],
                ["debit", "Debits"],
                ["deposit", "Deposits"],
                [
                  "withdraw",
                  "Withdrawals",
                ],
              ].map(
                ([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() =>
                      setFilter(
                        value
                      )
                    }
                    className={`
                      whitespace-nowrap
                      px-3
                      py-1.5
                      rounded-full
                      text-xs
                      font-bold
                      transition
                      ${
                        filter ===
                        value
                          ? "bg-white text-slate-950"
                          : "bg-slate-800 text-slate-400 hover:text-white"
                      }
                    `}
                  >
                    {label}
                  </button>
                )
              )}
            </div>
          </div>

          {/* =================================================
              TRANSACTION LIST
          ================================================= */}

          <div className="
            rounded-2xl
            border
            border-white/10
            bg-slate-900
            overflow-hidden
          ">
            {pageTransactions.length ===
            0 ? (
              <div className="
                px-5
                py-12
                text-center
              ">
                <div className="
                  mx-auto
                  w-12
                  h-12
                  rounded-full
                  bg-slate-800
                  flex
                  items-center
                  justify-center
                  text-xl
                  mb-3
                ">
                  ◌
                </div>

                <p className="
                  text-sm
                  font-bold
                  text-slate-300
                ">
                  No transactions found
                </p>

                <p className="
                  text-xs
                  text-slate-500
                  mt-1
                ">
                  Try another search or
                  filter.
                </p>
              </div>
            ) : (
              <div className="
                divide-y
                divide-white/5
              ">
                {Object.entries(
                  groupedTransactions
                ).map(
                  ([group, list]) =>
                    list.length > 0 && (
                      <div
                        key={group}
                        className="p-3"
                      >
                        <div className="
                          px-2
                          pb-2
                          text-[11px]
                          uppercase
                          tracking-wider
                          font-bold
                          text-slate-600
                        ">
                          {group}
                        </div>

                        <div className="
                          space-y-1
                        ">
                          {list.map(
                            (
                              transaction,
                              index
                            ) => {
                              const type =
                                normalizeType(
                                  transaction?.type ??
                                    transaction?.transaction_type ??
                                    transaction?.transactionType ??
                                    transaction?.kind
                                );

                              const theme =
                                getTransactionTheme(
                                  type
                                );

                              const direction =
                                getDirection(
                                  type
                                );

                              const amount =
                                safeNumber(
                                  transaction?.amount ??
                                    transaction?.value ??
                                    transaction?.transaction_amount ??
                                    transaction?.transactionAmount
                                );

                              const balanceAfter =
                                transaction?.balance_after ??
                                transaction?.balanceAfter ??
                                transaction?.running_balance ??
                                transaction?.runningBalance ??
                                null;

                              const date =
                                getTransactionDate(
                                  transaction
                                );

                              const transactionId =
                                transaction?.id ??
                                transaction?.transaction_id ??
                                transaction?.transactionId ??
                                null;

                              const description =
                                transaction?.description ??
                                transaction?.reason ??
                                transaction?.note ??
                                "";

                              const status =
                                transaction?.status ??
                                transaction?.state ??
                                "completed";

                              const reference =
                                transaction?.reference ??
                                transaction?.transaction_reference ??
                                transaction?.transactionReference ??
                                "";

                              const transactionKey =
                                transactionId ??
                                reference ??
                                `${type}-${date?.getTime() ?? index}-${index}`;

                              return (
                                <motion.div
                                  key={
                                    transactionKey
                                  }
                                  initial={{
                                    opacity: 0,
                                    y: 5,
                                  }}
                                  animate={{
                                    opacity: 1,
                                    y: 0,
                                  }}
                                  className="
                                    flex
                                    items-center
                                    justify-between
                                    gap-3
                                    rounded-xl
                                    p-3
                                    hover:bg-slate-800/60
                                    transition
                                  "
                                >
                                  {/* LEFT */}

                                  <div className="
                                    flex
                                    items-center
                                    gap-3
                                    min-w-0
                                  ">
                                    <div
                                      className={`
                                        w-10
                                        h-10
                                        shrink-0
                                        rounded-full
                                        border
                                        flex
                                        items-center
                                        justify-center
                                        text-lg
                                        font-black
                                        ${theme.icon}
                                      `}
                                    >
                                      {getTransactionIcon(
                                        type
                                      )}
                                    </div>

                                    <div className="
                                      min-w-0
                                    ">

                                      {/* TYPE */}

                                      <div className="
                                        flex
                                        items-center
                                        gap-2
                                      ">
                                        <div className="
                                          text-sm
                                          font-bold
                                          text-slate-200
                                          truncate
                                          capitalize
                                        ">
                                          {getTransactionLabel(
                                            transaction
                                          )}
                                        </div>

                                        <span
                                          className={`
                                            hidden
                                            rounded-full
                                            border
                                            px-2
                                            py-0.5
                                            text-[9px]
                                            font-bold
                                            uppercase
                                            sm:inline-flex
                                            ${theme.badge}
                                          `}
                                        >
                                          {
                                            status
                                          }
                                        </span>
                                      </div>

                                      {/* DESCRIPTION */}

                                      {description && (
                                        <div className="
                                          text-[11px]
                                          text-slate-500
                                          truncate
                                          mt-0.5
                                        ">
                                          {
                                            description
                                          }
                                        </div>
                                      )}

                                      {/* ID + DATE */}

                                      <div className="
                                        flex
                                        flex-wrap
                                        items-center
                                        gap-2
                                        text-[10px]
                                        text-slate-600
                                        mt-1
                                      ">
                                        {transactionId !==
                                          null && (
                                          <span>
                                            ID #
                                            {
                                              transactionId
                                            }
                                          </span>
                                        )}

                                        {transactionId !==
                                          null &&
                                          date && (
                                            <span>
                                              •
                                            </span>
                                          )}

                                        {date && (
                                          <span>
                                            {formatDateTime(
                                              date
                                            )}
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                  </div>

                                  {/* RIGHT */}

                                  <div className="
                                    text-right
                                    shrink-0
                                  ">
                                    <div
                                      className={`
                                        text-sm
                                        font-black
                                        ${theme.amount}
                                      `}
                                    >
                                      {direction ===
                                        "credit" &&
                                        "+"}

                                      {direction ===
                                        "debit" &&
                                        "-"}

                                      KES{" "}
                                      {formatNumber(
                                        amount
                                      )}
                                    </div>

                                    {balanceAfter !==
                                      null && (
                                      <div className="
                                        text-[10px]
                                        text-slate-600
                                        mt-0.5
                                      ">
                                        Balance: KES{" "}
                                        {formatNumber(
                                          balanceAfter
                                        )}
                                      </div>
                                    )}
                                  </div>
                                </motion.div>
                              );
                            }
                          )}
                        </div>
                      </div>
                    )
                )}
              </div>
            )}
          </div>

          {/* =================================================
              PAGINATION
          ================================================= */}

          {!showAllTransactions &&
            filteredTransactions.length >
              ITEMS_PER_PAGE && (
              <div className="
                flex
                items-center
                justify-between
                rounded-xl
                border
                border-white/5
                bg-slate-900
                px-3
                py-2
              ">
                <button
                  type="button"
                  disabled={
                    page <= 0
                  }
                  onClick={() =>
                    setPage(
                      (value) =>
                        value - 1
                    )
                  }
                  className="
                    px-3
                    py-2
                    rounded-lg
                    bg-slate-800
                    text-xs
                    font-bold
                    text-slate-300
                    disabled:opacity-30
                    hover:bg-slate-700
                  "
                >
                  ← Previous
                </button>

                <span className="
                  text-xs
                  font-bold
                  text-slate-500
                ">
                  {page + 1} /{" "}
                  {totalPages}
                </span>

                <button
                  type="button"
                  disabled={
                    page >=
                    totalPages - 1
                  }
                  onClick={() =>
                    setPage(
                      (value) =>
                        value + 1
                    )
                  }
                  className="
                    px-3
                    py-2
                    rounded-lg
                    bg-slate-800
                    text-xs
                    font-bold
                    text-slate-300
                    disabled:opacity-30
                    hover:bg-slate-700
                  "
                >
                  Next →
                </button>
              </div>
            )}

          {/* =================================================
              SUMMARY
          ================================================= */}

          {transactions.length >
            0 && (
            <div className="
              grid
              grid-cols-2
              gap-3
            ">
              <div className="
                rounded-xl
                bg-slate-900
                border
                border-white/5
                p-3
              ">
                <p className="
                  text-[10px]
                  uppercase
                  tracking-wider
                  text-slate-600
                  font-bold
                ">
                  Total Credits
                </p>

                <p className="
                  text-sm
                  font-black
                  text-emerald-400
                  mt-1
                ">
                  KES{" "}
                  {formatNumber(
                    transactionStats.credits
                  )}
                </p>
              </div>

              <div className="
                rounded-xl
                bg-slate-900
                border
                border-white/5
                p-3
              ">
                <p className="
                  text-[10px]
                  uppercase
                  tracking-wider
                  text-slate-600
                  font-bold
                ">
                  Total Debits
                </p>

                <p className="
                  text-sm
                  font-black
                  text-red-400
                  mt-1
                ">
                  KES{" "}
                  {formatNumber(
                    transactionStats.debits
                  )}
                </p>
              </div>
            </div>
          )}

          {/* =================================================
              CLOSE
          ================================================= */}

          <button
            type="button"
            onClick={onClose}
            className="
              w-full
              rounded-xl
              border
              border-white/10
              bg-slate-900
              py-3
              text-sm
              font-bold
              text-slate-300
              hover:bg-slate-800
              hover:text-white
              transition
            "
          >
            Close Wallet
          </button>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
