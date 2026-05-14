// src/contexts/UserContext.jsx
import React, { createContext, useContext, useState, useEffect } from "react";
import * as api from "../api/betsWallet";
import { getAuthToken, clearToken } from "../api/core";

const UserContext = createContext(null);

// Normalize API responses to arrays
function ensureArray(v) {
  if (!v) return [];
  if (Array.isArray(v)) return v;
  if (Array.isArray(v.data)) return v.data;
  if (Array.isArray(v.transactions)) return v.transactions;
  if (Array.isArray(v.history)) return v.history;
  if (Array.isArray(v.data?.transactions)) return v.data.transactions;
  if (Array.isArray(v.data?.history)) return v.data.history;
  return [];
}

export function UserProvider({ children }) {
  const [user, setUser] = useState(null);
  const [balance, setBalance] = useState(0);
  const [transactions, setTransactions] = useState([]);
  const [balanceHistory, setBalanceHistory] = useState([]);
  const [loadingUser, setLoadingUser] = useState(true);

  // --------------------------------------------------
  // Load user + wallet data
  // --------------------------------------------------
  const reloadUser = async () => {
    setLoadingUser(true);
    try {
      const token = getAuthToken();
      if (!token) throw new Error("No auth token");

      // Fetch profile
      const res = await api.getMe();
      console.log("reloadUser /me response:", res); // <-- debug log

      if (!res?.success || !res?.data) throw new Error("Invalid /me response");

      // Handle different API shapes
      const data = res.data.data || res.data || {};
      setUser(data.user || null);
      setBalance(data.balance ?? data.user?.balance ?? 0);

      // Fetch transactions & balance history
      const [txRes, histRes] = await Promise.all([
        api.getTransactions().catch(() => null),
        api.getBalanceHistory().catch(() => null),
      ]);

      setTransactions(ensureArray(txRes));
      setBalanceHistory(ensureArray(histRes));
    } catch (err) {
      console.error("Failed to load user:", err);
      clearToken();
      setUser(null);
      setBalance(0);
      setTransactions([]);
      setBalanceHistory([]);
    } finally {
      setLoadingUser(false);
    }
  };

  // --------------------------------------------------
  // Wallet operations
  // --------------------------------------------------
  const deposit = async (amount) => {
    const res = await api.deposit(amount);
    if (!res?.success) throw new Error(res?.error || "Deposit failed");
    await reloadUser();
  };

  const withdraw = async (amount) => {
    const res = await api.withdraw(amount);
    if (!res?.success) throw new Error(res?.error || "Withdraw failed");
    await reloadUser();
  };

  // --------------------------------------------------
  // Real-time UX helpers
  // --------------------------------------------------
  const updateBalance = (newBalance) => setBalance(newBalance);

  const updateTransactions = (newTxOrArray) => {
    if (!newTxOrArray) return;
    setTransactions((prev) =>
      Array.isArray(newTxOrArray)
        ? [...newTxOrArray, ...prev]
        : [newTxOrArray, ...prev]
    );
  };

  const updateBalanceHistory = (newHistOrArray) => {
    if (!newHistOrArray) return;
    setBalanceHistory((prev) =>
      Array.isArray(newHistOrArray)
        ? [...newHistOrArray, ...prev]
        : [newHistOrArray, ...prev]
    );
  };

  // --------------------------------------------------
  // Initial load
  // --------------------------------------------------
  useEffect(() => {
    reloadUser();
  }, []);

  return (
    <UserContext.Provider
      value={{
        user,
        balance,
        transactions,
        balanceHistory,
        loadingUser,
        setUser,
        setBalance,
        reloadUser,
        deposit,
        withdraw,
        updateBalance,
        updateTransactions,
        updateBalanceHistory,
      }}
    >
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  const context = useContext(UserContext);
  if (!context) throw new Error("useUser must be used inside a UserProvider");
  return context;
}
