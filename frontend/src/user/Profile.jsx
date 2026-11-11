// src/user/Profile.jsx

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";

import {
  logout,
  getStats,
  getProfitHistory,
  changePassword,
  deleteAccount,
} from "../api/betsWallet";

import { useUser } from "../contexts/UserContext";
import WalletPage from "./WalletPage";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

function getAvatarColor(value = "") {
  const colors = [
    "bg-blue-600",
    "bg-emerald-600",
    "bg-purple-600",
    "bg-orange-600",
    "bg-pink-600",
    "bg-indigo-600",
  ];

  let hash = 0;

  for (let i = 0; i < value.length; i++) {
    hash =
      (hash * 31 + value.charCodeAt(i)) %
      colors.length;
  }

  return colors[hash];
}

function formatMoney(value) {
  const amount = Number(value);

  return Number.isFinite(amount)
    ? amount.toLocaleString("en-KE", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    : "0.00";
}

export default function Profile() {
  const navigate = useNavigate();

  const {
    user,
    balance,
    bonusBalance,
    loadingUser,
  } = useUser();

  const [walletOpen, setWalletOpen] =
    useState(false);

  const [showPassword, setShowPassword] =
    useState(false);

  const [showDanger, setShowDanger] =
    useState(false);

  const [stats, setStats] = useState({
    total_bets: 0,
    wins: 0,
    losses: 0,
  });

  const [profit, setProfit] = useState(0);

  const [profitHistory, setProfitHistory] =
    useState([]);

  const [oldPassword, setOldPassword] =
    useState("");

  const [newPassword, setNewPassword] =
    useState("");

  const [savingPassword, setSavingPassword] =
    useState(false);

  const [loadingStats, setLoadingStats] =
    useState(false);

  const [message, setMessage] =
    useState(null);

  const phone = user?.phone || "User";

  const avatarDigits =
    String(phone).slice(-3) || "000";

  const avatarColor =
    getAvatarColor(String(phone));

  /* ---------------------------------
     LOAD PROFILE ANALYTICS
  --------------------------------- */

  const loadAnalytics = useCallback(
    async () => {
      if (!user) return;

      setLoadingStats(true);

      try {
        const [
          statsResponse,
          profitHistoryResponse,
        ] = await Promise.all([
          getStats().catch((error) => {
            console.error(
              "Stats request failed:",
              error
            );

            return null;
          }),

          getProfitHistory().catch((error) => {
            console.error(
              "Profit history request failed:",
              error
            );

            return null;
          }),
        ]);

        console.log(
          "STATS RESPONSE:",
          statsResponse
        );

        console.log(
          "PROFIT HISTORY RESPONSE:",
          profitHistoryResponse
        );

        setStats({
          total_bets:
            statsResponse?.data?.total_bets ??
            user?.total_bets ??
            0,

          wins:
            statsResponse?.data?.won_bets ??
            0,

          losses:
            statsResponse?.data?.lost_bets ??
            0,
        });

        const realizedProfit =
          profitHistoryResponse?.data
            ?.realized_profit;

        setProfit(
          realizedProfit !== null &&
          realizedProfit !== undefined
            ? Number(realizedProfit)
            : 0
        );

        const entries =
          profitHistoryResponse?.data?.entries;

        setProfitHistory(
          Array.isArray(entries)
            ? entries
            : []
        );
      } catch (error) {
        console.error(
          "Profile analytics error:",
          error
        );

        setStats({
          total_bets:
            Number(user?.total_bets) || 0,
          wins: 0,
          losses: 0,
        });

        setProfit(0);
        setProfitHistory([]);
      } finally {
        setLoadingStats(false);
      }
    },
    [user]
  );

  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);

  /* ---------------------------------
     DERIVED STATS
  --------------------------------- */

  const winRate = useMemo(() => {
    if (!stats.total_bets) return "0.0";

    return (
      (Number(stats.wins) /
        Number(stats.total_bets)) *
      100
    ).toFixed(1);
  }, [stats]);

  const lossRate = useMemo(() => {
    if (!stats.total_bets) return "0.0";

    return (
      (Number(stats.losses) /
        Number(stats.total_bets)) *
      100
    ).toFixed(1);
  }, [stats]);

  /*
   * --------------------------------------------------
   * PROFIT / LOSS RESULT
   * --------------------------------------------------
   *
   * Positive = Profit
   * Negative = Loss
   * Zero = No profit/loss
   *
   * The displayed amount is ALWAYS positive.
   * The sign is represented by the label.
   */

  const profitValue = Number(profit) || 0;

  const performanceResult = useMemo(() => {
    if (profitValue > 0) {
      return {
        type: "profit",
        label: "Total Profit",
        amount: profitValue,
        color: "text-emerald-400",
      };
    }

    if (profitValue < 0) {
      return {
        type: "loss",
        label: "Total Loss",
        amount: Math.abs(profitValue),
        color: "text-red-400",
      };
    }

    return {
      type: "neutral",
      label: "Net Result",
      amount: 0,
      color: "text-slate-300",
    };
  }, [profitValue]);

  /* ---------------------------------
     CHART DATA
  --------------------------------- */

  const chartData = useMemo(() => {
    if (!Array.isArray(profitHistory)) {
      return [];
    }

    return profitHistory
      .slice()
      .reverse()
      .map((item, index) => {
        let label = `Bet ${index + 1}`;

        if (item?.created) {
          const date =
            new Date(item.created);

          if (!Number.isNaN(date.getTime())) {
            label =
              date.toLocaleDateString(
                "en-KE",
                {
                  day: "2-digit",
                  month: "short",
                }
              );
          }
        } else if (item?.day) {
          label = item.day;
        } else if (item?.date) {
          label = item.date;
        }

        return {
          ...item,
          label,

          /*
           * Keep the chart signed.
           *
           * Positive = profit
           * Negative = loss
           */

          profit:
            Number(item?.profit) || 0,
        };
      });
  }, [profitHistory]);

  /* ---------------------------------
     PASSWORD
  --------------------------------- */

  const handlePassword = async () => {
    if (!oldPassword || !newPassword) {
      setMessage({
        type: "error",
        text: "Please fill in both password fields.",
      });

      return;
    }

    if (newPassword.length < 6) {
      setMessage({
        type: "error",
        text: "New password must contain at least 6 characters.",
      });

      return;
    }

    setSavingPassword(true);
    setMessage(null);

    try {
      const response =
        await changePassword(
          oldPassword,
          newPassword
        );

      if (response?.success) {
        setMessage({
          type: "success",
          text: "Password updated successfully.",
        });

        setOldPassword("");
        setNewPassword("");
        setShowPassword(false);
      } else {
        setMessage({
          type: "error",
          text:
            response?.error ||
            response?.message ||
            "Failed to change password.",
        });
      }
    } catch (error) {
      setMessage({
        type: "error",
        text:
          error?.message ||
          "Failed to change password.",
      });
    } finally {
      setSavingPassword(false);
    }
  };

  /* ---------------------------------
     LOGOUT
  --------------------------------- */

  const handleLogout = () => {
    logout();

    // Fully refresh the app after logout
    window.location.href = "/bookmarks";
  };

  /* ---------------------------------
     DELETE ACCOUNT
  --------------------------------- */

  const handleDeleteAccount = async () => {
    const confirmed = window.confirm(
      "This will permanently delete your account and account data. Continue?"
    );

    if (!confirmed) return;

    try {
      const response =
        await deleteAccount();

      if (response?.success) {
        logout();

        window.location.href = "/vip";
      } else {
        setMessage({
          type: "error",
          text:
            response?.error ||
            response?.message ||
            "Failed to delete account.",
        });
      }
    } catch (error) {
      setMessage({
        type: "error",
        text:
          error?.message ||
          "Failed to delete account.",
      });
    }
  };

  /* ---------------------------------
     LOADING
  --------------------------------- */

  if (loadingUser) {
    return (
      <div className="min-h-screen bg-slate-950 text-white flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-9 h-9 rounded-full border-4 border-slate-700 border-t-blue-500 animate-spin" />

          <p className="text-sm text-slate-400">
            Loading profile...
          </p>
        </div>
      </div>
    );
  }

  /* ---------------------------------
     RENDER
  --------------------------------- */

  return (
    <div className="min-h-screen bg-slate-950 text-white pb-24">

      {/* HEADER */}

      <header className="bg-gradient-to-br from-slate-900 via-slate-900 to-blue-950 border-b border-slate-800">

        <div className="max-w-5xl mx-auto px-4 pt-14 pb-8">

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-5">

            <div className="flex items-center gap-4">

              <div
                className={`w-16 h-16 rounded-2xl ${avatarColor} flex flex-col items-center justify-center shadow-lg`}
              >
                <span className="text-2xl">
                  👤
                </span>

                <span className="text-[10px] font-black">
                  {avatarDigits}
                </span>
              </div>

              <div>

                <p className="text-xs uppercase tracking-widest text-blue-400 font-bold">
                  My Account
                </p>

                <h1 className="text-xl sm:text-2xl font-black mt-1">
                  {phone}
                </h1>

                <p className="text-sm text-slate-400 mt-1">
                  Welcome back
                </p>

              </div>

            </div>

            <div className="flex gap-2">

              <button
                onClick={() =>
                  navigate("/bookmarks")
                }
                className="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-sm font-bold transition"
              >
                Home
              </button>

              <button
                onClick={() =>
                  setWalletOpen(true)
                }
                className="px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-sm font-black transition"
              >
                Wallet
              </button>

            </div>

          </div>

          {/* BALANCES */}

          <div className="grid grid-cols-2 gap-3 mt-6">

            <BalanceCard
              label="Cash Balance"
              value={`KES ${formatMoney(
                balance
              )}`}
              icon="💰"
            />

            <BalanceCard
              label="Bonus Balance"
              value={`KES ${formatMoney(
                bonusBalance
              )}`}
              icon="🎁"
              color="text-yellow-400"
            />

          </div>

        </div>

      </header>

      <main className="max-w-5xl mx-auto px-4 py-5 space-y-5">

        {/* MESSAGE */}

        {message && (
          <div
            className={`rounded-xl border px-4 py-3 text-sm ${
              message.type === "success"
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                : "bg-red-500/10 border-red-500/30 text-red-400"
            }`}
          >
            {message.text}
          </div>
        )}

        {/* STATISTICS */}

        <section>

          <div className="flex items-center justify-between mb-3">

            <div>
              <h2 className="font-black text-lg">
                Betting Performance
              </h2>

              <p className="text-xs text-slate-500">
                Your account statistics
              </p>
            </div>

            {loadingStats && (
              <div className="w-4 h-4 rounded-full border-2 border-slate-700 border-t-blue-500 animate-spin" />
            )}

          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">

            <PerformanceCard
              label="Total Bets"
              value={stats.total_bets}
              icon="🎯"
            />

            <PerformanceCard
              label="Wins"
              value={stats.wins}
              icon="🏆"
              color="text-emerald-400"
            />

            <PerformanceCard
              label="Losses"
              value={stats.losses}
              icon="❌"
              color="text-red-400"
            />

            <PerformanceCard
              label="Win Rate"
              value={`${winRate}%`}
              icon="📈"
              color="text-blue-400"
            />

          </div>

        </section>

        {/* PROFIT / LOSS */}

        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-5">

          <div className="flex items-start justify-between">

            <div>

              <p className="text-xs uppercase tracking-wider text-slate-500 font-bold">
                {performanceResult.label}
              </p>

              <p
                className={`text-2xl sm:text-3xl font-black mt-1 ${performanceResult.color}`}
              >
                KES{" "}
                {formatMoney(
                  performanceResult.amount
                )}
              </p>

            </div>

            <div className="text-right">

              <p className="text-xs text-slate-500">
                Loss Rate
              </p>

              <p className="font-bold text-red-400">
                {lossRate}%
              </p>

            </div>

          </div>

        </section>

        {/* PROFIT CHART */}

        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-5">

          <div className="mb-4">

            <h2 className="font-black">
              Profit History
            </h2>

            <p className="text-xs text-slate-500 mt-1">
              Betting performance
            </p>

          </div>

          {chartData.length > 0 ? (

            <div className="w-full h-[250px]">

              <ResponsiveContainer
                width="100%"
                height="100%"
              >

                <LineChart
                  data={chartData}
                  margin={{
                    top: 10,
                    right: 10,
                    left: -20,
                    bottom: 0,
                  }}
                >

                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#1e293b"
                  />

                  <XAxis
                    dataKey="label"
                    tick={{
                      fill: "#64748b",
                      fontSize: 10,
                    }}
                    axisLine={false}
                    tickLine={false}
                  />

                  <YAxis
                    tick={{
                      fill: "#64748b",
                      fontSize: 10,
                    }}
                    axisLine={false}
                    tickLine={false}
                  />

                  <Tooltip
                    contentStyle={{
                      background:
                        "#0f172a",
                      border:
                        "1px solid #1e293b",
                      borderRadius: "12px",
                      color: "#fff",
                    }}
                    formatter={(value) => {
                      const numericValue =
                        Number(value) || 0;

                      if (numericValue < 0) {
                        return `Loss: KES ${formatMoney(
                          Math.abs(
                            numericValue
                          )
                        )}`;
                      }

                      if (numericValue > 0) {
                        return `Profit: KES ${formatMoney(
                          numericValue
                        )}`;
                      }

                      return "Net: KES 0.00";
                    }}
                  />

                  <Line
                    type="monotone"
                    dataKey="profit"
                    stroke="#10b981"
                    strokeWidth={3}
                    dot={false}
                    activeDot={{
                      r: 5,
                    }}
                  />

                </LineChart>

              </ResponsiveContainer>

            </div>

          ) : (

            <div className="h-[220px] flex items-center justify-center text-sm text-slate-500">
              No profit history available yet.
            </div>

          )}

        </section>

        {/* QUICK ACTIONS */}

        <section>

          <h2 className="font-black text-lg mb-3">
            Account
          </h2>

          <div className="space-y-2">

            {/* TRANSACTION HISTORY REMOVED */}

            <ActionButton
              icon="🔐"
              title="Change Password"
              description="Update your account password"
              onClick={() =>
                setShowPassword(
                  (value) => !value
                )
              }
            />

            <ActionButton
              icon="🚪"
              title="Logout"
              description="Sign out of your account"
              onClick={handleLogout}
              danger
            />

          </div>

        </section>

        {/* PASSWORD */}

        {showPassword && (

          <section className="bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-5 space-y-3">

            <div>

              <h3 className="font-black">
                Change Password
              </h3>

              <p className="text-xs text-slate-500 mt-1">
                Choose a strong password with at least 6 characters.
              </p>

            </div>

            <input
              type="password"
              placeholder="Current password"
              value={oldPassword}
              onChange={(e) =>
                setOldPassword(
                  e.target.value
                )
              }
              className="w-full rounded-xl bg-slate-800 border border-slate-700 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-blue-500"
            />

            <input
              type="password"
              placeholder="New password"
              value={newPassword}
              onChange={(e) =>
                setNewPassword(
                  e.target.value
                )
              }
              className="w-full rounded-xl bg-slate-800 border border-slate-700 px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-blue-500"
            />

            <button
              onClick={handlePassword}
              disabled={savingPassword}
              className="w-full rounded-xl bg-blue-600 hover:bg-blue-500 py-3 font-black disabled:opacity-50 transition"
            >
              {savingPassword
                ? "Updating..."
                : "Update Password"}
            </button>

          </section>

        )}

        {/* DANGER ZONE */}

        <section className="pt-2">

          <button
            onClick={() =>
              setShowDanger(
                (value) => !value
              )
            }
            className="w-full text-left text-xs text-slate-600 hover:text-red-400 transition"
          >
            Account danger zone{" "}
            {showDanger ? "▲" : "▼"}
          </button>

          {showDanger && (

            <div className="mt-3 bg-red-500/5 border border-red-500/20 rounded-2xl p-4">

              <p className="text-sm font-bold text-red-400">
                Delete account
              </p>

              <p className="text-xs text-slate-500 mt-1 mb-4">
                This action cannot be undone.
              </p>

              <button
                onClick={
                  handleDeleteAccount
                }
                className="w-full rounded-xl bg-red-600 hover:bg-red-500 py-3 text-sm font-black transition"
              >
                Permanently Delete Account
              </button>

            </div>

          )}

        </section>

      </main>

      {/* WALLET */}

      {walletOpen && (
        <WalletPage
          onClose={() =>
            setWalletOpen(false)
          }
        />
      )}

    </div>
  );
}

/* ---------------------------------
   COMPONENTS
--------------------------------- */

function BalanceCard({
  label,
  value,
  icon,
  color = "text-emerald-400",
}) {
  return (
    <div className="bg-slate-800/70 border border-slate-700/60 rounded-2xl p-4">

      <div className="flex items-center justify-between">

        <span className="text-xs text-slate-500 font-bold uppercase tracking-wider">
          {label}
        </span>

        <span className="text-lg">
          {icon}
        </span>

      </div>

      <p
        className={`text-lg sm:text-xl font-black mt-2 ${color}`}
      >
        {value}
      </p>

    </div>
  );
}

function PerformanceCard({
  label,
  value,
  icon,
  color = "text-white",
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">

      <div className="flex items-center justify-between">

        <span className="text-xl">
          {icon}
        </span>

        <span
          className={`text-xl font-black ${color}`}
        >
          {value}
        </span>

      </div>

      <p className="text-xs text-slate-500 mt-2">
        {label}
      </p>

    </div>
  );
}

function ActionButton({
  icon,
  title,
  description,
  onClick,
  danger = false,
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full flex items-center gap-4 p-4 rounded-2xl border text-left transition ${
        danger
          ? "bg-slate-900 border-slate-800 hover:border-red-500/30"
          : "bg-slate-900 border-slate-800 hover:border-blue-500/30"
      }`}
    >

      <div className="w-11 h-11 rounded-xl bg-slate-800 flex items-center justify-center text-lg flex-shrink-0">
        {icon}
      </div>

      <div className="min-w-0 flex-1">

        <p
          className={`font-bold ${
            danger
              ? "text-red-400"
              : "text-white"
          }`}
        >
          {title}
        </p>

        <p className="text-xs text-slate-500 mt-0.5 truncate">
          {description}
        </p>

      </div>

      <span className="text-slate-600">
        →
      </span>

    </button>
  );
}
