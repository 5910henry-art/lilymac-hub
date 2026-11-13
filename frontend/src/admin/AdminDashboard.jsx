// src/admin/AdminDashboard.jsx

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";

import {
  gradeMatch,
  getSettlementStatuses,
  getSettlementMatches,
} from "../api/betsWallet";

import {
  adminListVips,
  adminBettingOverview,
  adminHouseBalanceHistory,
  adminListBets,
  adminListTransactions,
  adminListPendingVips,
  adminListUpgradeRequests,
  adminApproveVip,
  adminDeclineVip,
  adminDeleteVip,
  adminSetVipPassword,
  adminSendVipPushTest,
  vipPushPublicKey,
  adminPushSubscribe,
  adminPushUnsubscribe,
  adminApproveUpgrade,
  adminDeclineUpgrade,
  adminPreviewVipPicks,
  adminDistributeVipPicks,
  adminGetVipPickHistory,
} from "../api/authVipAdmin";

const REFRESH_MS = 30_000;

function formatVipHistoryDate(value) {
  if (!value) return "—";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-KE", {
    timeZone: "Africa/Nairobi",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export default function AdminDashboard() {
  const [token, setToken] = useState(() => localStorage.getItem("admin_token"));
  const [admin, setAdmin] = useState(() =>
    JSON.parse(localStorage.getItem("admin_user") || "null")
  );


  const [vips, setVips] = useState([]);
  const [bettingOverview, setBettingOverview] = useState(null);
  const [houseBalanceHistory, setHouseBalanceHistory] = useState(null);
  const [houseBalanceRange, setHouseBalanceRange] = useState("30d");
  const [houseBalanceHistoryLoading, setHouseBalanceHistoryLoading] = useState(false);
  const [houseBalanceHistoryError, setHouseBalanceHistoryError] = useState("");
  const [pendingVips, setPendingVips] = useState([]);
  const [upgradeRequests, setUpgradeRequests] = useState([]);

  const pendingUpgradeRequests = upgradeRequests.filter(
    (req) => String(req.status || "").toLowerCase() === "pending"
  );
  const pendingActionCount =
    pendingVips.length + pendingUpgradeRequests.length;
  const [allMatches, setAllMatches] = useState([]);
const [selectedVIPs, setSelectedVIPs] = useState([]);
  const [selectedMatches, setSelectedMatches] = useState([]);
  const [pick, setPick] = useState("1X2");
  const [odds, setOdds] = useState(1.5);
  const [distributionSummary, setDistributionSummary] = useState([]);

  const [vipHistory, setVipHistory] = useState([]);
  const [vipHistoryTotals, setVipHistoryTotals] = useState({
    total: 0,
    won: 0,
    lost: 0,
    pending: 0,
    ungraded: 0,
  });
  const [vipHistoryNumber, setVipHistoryNumber] = useState("");
  const [vipHistoryPlan, setVipHistoryPlan] = useState("all");
  const [vipHistoryFrom, setVipHistoryFrom] = useState("");
  const [vipHistoryTo, setVipHistoryTo] = useState("");
  const [vipHistoryLoading, setVipHistoryLoading] = useState(false);
  const [vipHistoryError, setVipHistoryError] = useState("");

  const [loading, setLoading] = useState(false);
  const [loadingText, setLoadingText] = useState("");
  const [msg, setMsg] = useState(null);

  const [search, setSearch] = useState("");
  const [filterApproved, setFilterApproved] = useState("all");
  const [filterPlan, setFilterPlan] = useState("all");
  const [activeSection, setActiveSection] = useState("overview");

  const [settlementDate, setSettlementDate] = useState(() => {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Africa/Nairobi",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date());

    const values = Object.fromEntries(
      parts.map((part) => [part.type, part.value])
    );

    return `${values.year}-${values.month}-${values.day}`;
  });
  const [settlementMatches, setSettlementMatches] = useState([]);
  const [settlementStatuses, setSettlementStatuses] = useState([]);
  const [settlementMatchId, setSettlementMatchId] = useState("");
  const [homeScore, setHomeScore] = useState("");
  const [awayScore, setAwayScore] = useState("");
  const [settlementStatus, setSettlementStatus] = useState("");
  const [settlementLoading, setSettlementLoading] = useState(false);

  // Read-only bet management
  const [betRecords, setBetRecords] = useState([]);
  const [betMeta, setBetMeta] = useState({
    total: 0,
    page: 1,
    per_page: 5,
    total_pages: 0,
  });
  const [betSearch, setBetSearch] = useState("");
  const [betStatus, setBetStatus] = useState("all");
  const [betType, setBetType] = useState("all");
  const [betLoading, setBetLoading] = useState(false);
  const [expandedBet, setExpandedBet] = useState(null);

  // Read-only transaction management
  const [transactionRecords, setTransactionRecords] = useState([]);
  const [transactionMeta, setTransactionMeta] = useState({
    total: 0,
    page: 1,
    per_page: 20,
    total_pages: 0,
  });
  const [transactionCounts, setTransactionCounts] = useState({
    wallet: 0,
    deposit_attempt: 0,
    withdrawal: 0,
  });
  const [transactionSearch, setTransactionSearch] = useState("");
  const [transactionCategory, setTransactionCategory] = useState("all");
  const [transactionStatus, setTransactionStatus] = useState("all");
  const [transactionLoading, setTransactionLoading] = useState(false);
  const [expandedTransaction, setExpandedTransaction] = useState(null);

  useEffect(() => {
    document.documentElement.classList.add("dark");

    return () => {
      document.documentElement.classList.remove("dark");
    };
  }, []);

  const safeArray = useCallback((res) => {
    if (!res) return [];

    if (Array.isArray(res)) return res;
    if (Array.isArray(res?.data)) return res.data;

    const payload = res?.data ?? res;

    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload?.data)) return payload.data;
    if (Array.isArray(payload?.vips)) return payload.vips;
    if (Array.isArray(payload?.requests)) return payload.requests;
    if (Array.isArray(payload?.matches)) return payload.matches;
    if (Array.isArray(payload?.statuses)) return payload.statuses;
    if (Array.isArray(payload?.users)) return payload.users;
    if (Array.isArray(payload?.tickets)) return payload.tickets;
    if (Array.isArray(payload?.summary)) return payload.summary;

    return [];
  }, []);

  const safeObj = useCallback((res) => res?.data ?? res ?? null, []);

  const fetchVipPickHistory = useCallback(async () => {
    if (!token) return;

    setVipHistoryLoading(true);
    setVipHistoryError("");

    try {
      const filters = {
        number: vipHistoryNumber.trim(),
        plan: vipHistoryPlan === "all" ? "" : vipHistoryPlan,
        from: vipHistoryFrom,
        to: vipHistoryTo,
        limit: 500,
      };

      const res = await adminGetVipPickHistory(token, filters);

      if (res?.success === false) {
        throw new Error(
          res?.error || res?.message || "Could not load VIP pick history."
        );
      }

      const payload = safeObj(res) || {};

      setVipHistory(
        Array.isArray(payload.history) ? payload.history : []
      );

      setVipHistoryTotals(
        payload.totals || {
          total: 0,
          won: 0,
          lost: 0,
          pending: 0,
          ungraded: 0,
        }
      );
    } catch (error) {
      setVipHistoryError(
        error?.message || "Could not load VIP pick history."
      );
    } finally {
      setVipHistoryLoading(false);
    }
  }, [
    token,
    safeObj,
    vipHistoryNumber,
    vipHistoryPlan,
    vipHistoryFrom,
    vipHistoryTo,
  ]);

  const showError = useCallback(
    (error, fallback = "Something went wrong") => {
      setMsg({
        type: "error",
        text: error?.message || String(error) || fallback,
      });
    },
    []
  );

  const logout = () => {
    localStorage.removeItem("admin_token");
    localStorage.removeItem("admin_user");

    setToken(null);
    setAdmin(null);

    setVips([]);
    setPendingVips([]);
    setUpgradeRequests([]);
    setAllMatches([]);
    setSelectedVIPs([]);
    setSelectedMatches([]);
setDistributionSummary([]);

    setMsg({
      type: "info",
      text: "You have been logged out.",
    });
  };

  const [pushLoading, setPushLoading] = useState(false);
  const [pushMessage, setPushMessage] = useState("");
  const [adminPushEnabled, setAdminPushEnabled] = useState(false);

  useEffect(() => {
    let active = true;

    const checkAdminPushStatus = async () => {
      if (
        !token ||
        !("serviceWorker" in navigator) ||
        !("PushManager" in window) ||
        !("Notification" in window)
      ) {
        if (active) setAdminPushEnabled(false);
        return;
      }

      try {
        const registration =
          await navigator.serviceWorker.getRegistration();
        const subscription = registration
          ? await registration.pushManager.getSubscription()
          : null;

        if (active) {
          setAdminPushEnabled(
            Boolean(subscription) && Notification.permission === "granted"
          );
        }
      } catch (error) {
        console.error("[ADMIN PUSH] Status check failed:", error);
        if (active) setAdminPushEnabled(false);
      }
    };

    checkAdminPushStatus();
    return () => {
      active = false;
    };
  }, [token]);

  const enableAdminNotifications = async () => {
    if (!token) return;

    if (
      !("serviceWorker" in navigator) ||
      !("PushManager" in window) ||
      !("Notification" in window)
    ) {
      setPushMessage("This browser does not support push notifications.");
      return;
    }

    setPushLoading(true);
    setPushMessage("");

    try {
      const permission = await Notification.requestPermission();

      if (permission !== "granted") {
        throw new Error(
          permission === "denied"
            ? "Notifications are blocked. Allow them in your browser site settings, then try again."
            : "Notification permission was not granted."
        );
      }

      const registration = await navigator.serviceWorker.ready;
      let subscription = await registration.pushManager.getSubscription();

      if (!subscription) {
        const keyResponse = await vipPushPublicKey();
        const publicKey =
          keyResponse?.data?.publicKey || keyResponse?.publicKey;

        if (!keyResponse?.success || !publicKey) {
          throw new Error("Could not load the push notification public key.");
        }

        const padding = "=".repeat((4 - publicKey.length % 4) % 4);
        const base64 = (publicKey + padding)
          .replace(/-/g, "+")
          .replace(/_/g, "/");
        const raw = window.atob(base64);
        const applicationServerKey = Uint8Array.from(
          raw,
          (char) => char.charCodeAt(0)
        );

        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey,
        });
      }

      const saved = await adminPushSubscribe(token, subscription.toJSON());

      if (!saved?.success) {
        throw new Error(saved?.error || "Could not save the admin device.");
      }

      setAdminPushEnabled(true);
      setPushMessage("Admin notifications are enabled on this device.");
    } catch (error) {
      console.error("[ADMIN PUSH] Enable failed:", error);
      setPushMessage(error?.message || "Could not enable admin notifications.");
    } finally {
      setPushLoading(false);
    }
  };

  const disableAdminNotifications = async () => {
    if (!token) return;

    setPushLoading(true);
    setPushMessage("");

    try {
      if (
        !("serviceWorker" in navigator) ||
        !("PushManager" in window)
      ) {
        setAdminPushEnabled(false);
        setPushMessage("This browser does not support push notifications.");
        return;
      }

      const registration =
        await navigator.serviceWorker.getRegistration();
      const subscription = registration
        ? await registration.pushManager.getSubscription()
        : null;

      if (!subscription) {
        setAdminPushEnabled(false);
        setPushMessage("There is no active push subscription on this device.");
        return;
      }

      const removed = await adminPushUnsubscribe(
        token,
        subscription.endpoint
      );

      if (!removed?.success) {
        throw new Error(
          removed?.error || "Could not disable admin notifications."
        );
      }

      setAdminPushEnabled(false);
      const browserRemoved = await subscription.unsubscribe();

      setPushMessage(
        browserRemoved
          ? "Admin notifications are disabled on this device."
          : "Server notifications are disabled, but the browser subscription could not be removed."
      );
    } catch (error) {
      console.error("[ADMIN PUSH] Disable failed:", error);
      setPushMessage(error?.message || "Could not disable admin notifications.");
    } finally {
      setPushLoading(false);
    }
  };

  const fetchAll = useCallback(async (silent = false) => {
    if (!token) return;

    if (!silent) {
      setLoading(true);
      setLoadingText("Refreshing dashboard…");
    }

    try {
      const [
        vipList,
        pendingList,
        upgrades,
        matches,
] = await Promise.all([
        adminListVips(token),
        adminListPendingVips(token),
        adminListUpgradeRequests(token),
        adminPreviewVipPicks(token, 50),
]);

      const freshVips = safeArray(vipList);
      setVips(freshVips);
      setSelectedVIPs((prev) =>
        prev.filter((number) =>
          freshVips.some(
            (v) =>
              v.approved &&
              String(v.number) === String(number) &&
              Number(v.daily_quota_remaining) > 0
          )
        )
      );
      setPendingVips(safeArray(pendingList));
      setUpgradeRequests(safeArray(upgrades));
      setAllMatches(safeArray(matches));

      // Betting overview is independent of VIP list loading.
      const overview = await adminBettingOverview(token);
      setBettingOverview(
        overview?.success
          ? (safeObj(safeObj(overview)) ?? null)
          : null
      );
} catch (e) {
      console.error(
        "[ADMIN] fetchAll failed:",
        e
      );

      showError(e);
    } finally {
      if (!silent) {
        setLoading(false);
        setLoadingText("");
      }
    }
  }, [token, safeArray, safeObj, showError]);

  useEffect(() => {
    if (!token) return;

    fetchAll();

    const interval = setInterval(
      () => fetchAll(true),
      REFRESH_MS
    );

    return () => clearInterval(interval);
  }, [token, fetchAll]);

  // Load the available match statuses from the database.
  useEffect(() => {
    if (!token) return;

    let active = true;

    const loadStatuses = async () => {
      try {
        const res = await getSettlementStatuses(token);

        if (!active) return;

        if (!res?.success) {
          setSettlementStatuses([]);
          showError(res?.error || res?.message || "Could not load match statuses");
          return;
        }

        setSettlementStatuses(safeArray(res));
      } catch (error) {
        if (active) {
          console.error("[ADMIN] Settlement statuses failed:", error);
          showError(error);
        }
      }
    };

    loadStatuses();

    return () => {
      active = false;
    };
  }, [token, safeArray, showError]);

  // Load unfinished matches for the selected Nairobi calendar date.
  useEffect(() => {
    if (!token || !settlementDate) return;

    let active = true;

    setSettlementMatchId("");
    setHomeScore("");
    setAwayScore("");
    setSettlementStatus("");
    setSettlementLoading(true);

    const loadMatches = async () => {
      try {
        const res = await getSettlementMatches(settlementDate, token);

        if (!active) return;

        if (!res?.success) {
          setSettlementMatches([]);
          showError(res?.error || res?.message || "Could not load matches");
          return;
        }

        setSettlementMatches(safeArray(res));
      } catch (error) {
        if (active) {
          console.error("[ADMIN] Settlement matches failed:", error);
          setSettlementMatches([]);
          showError(error);
        }
      } finally {
        if (active) setSettlementLoading(false);
      }
    };

    loadMatches();

    return () => {
      active = false;
    };
  }, [token, settlementDate, safeArray, showError]);


  useEffect(() => {
    if (!token) {
      setHouseBalanceHistory(null);
      return;
    }

    let cancelled = false;

    const loadHistory = async () => {
      setHouseBalanceHistoryLoading(true);
      setHouseBalanceHistoryError("");

      try {
        const response = await adminHouseBalanceHistory(
          token,
          houseBalanceRange
        );

        const body =
          response?.data?.success !== undefined
            ? response.data
            : response;

        if (!body?.success) {
          throw new Error(
            body?.error || body?.message || "Could not load balance history."
          );
        }

        const payload = body?.data ?? {};

        if (!cancelled) {
          setHouseBalanceHistory({
            ...payload,
            points: Array.isArray(payload.points) ? payload.points : [],
          });
        }
      } catch (error) {
        console.error("[ADMIN] House balance history failed:", error);

        if (!cancelled) {
          setHouseBalanceHistoryError(
            error?.message || "Could not load balance history."
          );
        }
      } finally {
        if (!cancelled) {
          setHouseBalanceHistoryLoading(false);
        }
      }
    };

    loadHistory();
    const interval = setInterval(loadHistory, REFRESH_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [token, houseBalanceRange]);

  const fetchBets = async (page = 1) => {
    if (!token || betLoading) return;

    setBetLoading(true);

    try {
      const response = await adminListBets(token, {
        search: betSearch.trim(),
        status: betStatus,
        type: betType,
        page,
        per_page: 5,
      });

      let result = response;

      // Support both direct and wrapped API response formats.
      if (result?.data?.success !== undefined) {
        result = result.data;
      }

      if (result?.success === false) {
        throw new Error(
          result.error || result.message || "Could not load bet records."
        );
      }

      const data = result?.data ?? result ?? {};

      setBetRecords(
        Array.isArray(data.bets) ? data.bets : []
      );

      setBetMeta({
        total: Number(data.total || 0),
        page: Number(data.page || page),
        per_page: Number(data.per_page || 5),
        total_pages: Number(data.total_pages || 0),
      });

      setExpandedBet(null);
    } catch (error) {
      console.error("[ADMIN] Bet management load failed:", error);
      showError(error);
    } finally {
      setBetLoading(false);
    }
  };

  const fetchTransactions = async (page = 1, filters = null) => {
    if (!token || transactionLoading) return;

    const activeFilters = filters || {
      search: transactionSearch.trim(),
      category: transactionCategory,
      status: transactionStatus,
    };

    setTransactionLoading(true);

    try {
      const response = await adminListTransactions(token, {
        ...activeFilters,
        page,
        per_page: 20,
      });

      let result = response;

      if (result?.data?.success !== undefined) {
        result = result.data;
      }

      if (result?.success === false) {
        throw new Error(
          result.error || result.message || "Could not load transactions."
        );
      }

      const data = result?.data ?? result ?? {};
      const rows = Array.isArray(data.transactions)
        ? data.transactions
        : [];

      setTransactionRecords(rows);

      setTransactionCounts({
        wallet: Number(data.counts?.wallet || 0),
        deposit_attempt: Number(data.counts?.deposit_attempt || 0),
        withdrawal: Number(data.counts?.withdrawal || 0),
      });

      setTransactionMeta({
        total: Number(data.pagination?.total || 0),
        page: Number(data.pagination?.page || page),
        per_page: Number(data.pagination?.per_page || 20),
        total_pages: Number(data.pagination?.total_pages || 0),
      });

      setExpandedTransaction(null);
    } catch (error) {
      console.error("[ADMIN] Transaction management load failed:", error);
      showError(error);
    } finally {
      setTransactionLoading(false);
    }
  };

  const vipAction = async (id, action) => {
    const verb =
      action === "approve"
        ? "approve"
        : action === "delete"
          ? "delete"
          : "decline";

    const confirmMessage =
      action === "delete"
        ? "Are you sure you want to permanently DELETE this VIP?\\n\\nThis will remove the VIP account, all VIP picks, and subscription requests. This cannot be undone."
        : `Are you sure you want to ${verb} this VIP?`;

    if (!window.confirm(confirmMessage)) {
      return;
    }

    setLoading(true);
    setLoadingText(
      action === "approve"
        ? "Approving VIP…"
        : action === "delete"
          ? "Deleting VIP…"
          : "Declining VIP…"
    );
    setMsg(null);

    try {
      let res;

      if (action === "approve") {
        res = await adminApproveVip(token, id);
      } else if (action === "delete") {
        res = await adminDeleteVip(token, id);
      } else {
        res = await adminDeclineVip(token, id);
      }

      if (res?.success === false) {
        throw new Error(
          res?.error ||
            res?.message ||
            `Failed to ${action} VIP`
        );
      }

      setMsg({
        type: "success",
        text:
          action === "delete"
            ? "VIP deleted successfully."
            : `VIP ${action}d successfully.`,
      });

      await fetchAll();
    } catch (e) {
      console.error(
        `[ADMIN] VIP ${action} failed:`,
        e
      );

      showError(e);
    } finally {
      setLoading(false);
      setLoadingText("");
    }
  };

  const setVipPassword = async (vip) => {
    const newPassword = window.prompt(
      `Enter a new password for ${vip.name || vip.number || "this VIP"} (minimum 8 characters):`
    );

    if (newPassword === null) return;

    if (newPassword.length < 8) {
      showError(new Error("Password must be at least 8 characters."));
      return;
    }

    if (!window.confirm("Save this VIP password?")) return;

    setLoading(true);
    setLoadingText("Updating VIP password…");
    setMsg(null);

    try {
      const res = await adminSetVipPassword(
        token,
        vip.id,
        newPassword
      );

      if (res?.success === false) {
        throw new Error(
          res?.error || res?.message || "Failed to update VIP password."
        );
      }

      setMsg({
        type: "success",
        text: "VIP password updated successfully.",
      });

      await fetchAll();
    } catch (e) {
      console.error("[ADMIN] VIP password update failed:", e);
      showError(e);
    } finally {
      setLoading(false);
      setLoadingText("");
    }
  };

  const upgradeAction = async (
    reqId,
    action,
    requestType = "upgrade"
  ) => {
    const verb =
      action === "approve"
        ? "approve"
        : "decline";

    if (
      !window.confirm(
        `Are you sure you want to ${verb} this ${requestType === "renewal" ? "renewal" : "upgrade"} request?`
      )
    ) {
      return;
    }

    setLoading(true);
    setLoadingText(
      `${
        verb === "approve"
          ? "Approving"
          : "Declining"
      } request…`
    );
    setMsg(null);

    try {
      const res =
        action === "approve"
          ? await adminApproveUpgrade(
              token,
              reqId
            )
          : await adminDeclineUpgrade(
              token,
              reqId
            );

      if (res?.success === false) {
        throw new Error(
          res?.error ||
            res?.message ||
            `Failed to ${action} subscription request`
        );
      }

      setMsg({
        type: "success",
        text: `${requestType === "renewal" ? "Renewal" : "Upgrade"} ${action}d successfully.`,
      });

      await fetchAll();
    } catch (e) {
      console.error(
        `[ADMIN] Upgrade ${action} failed:`,
        e
      );

      showError(e);
    } finally {
      setLoading(false);
      setLoadingText("");
    }
  };

  const sendVipPushTest = async () => {
    if (selectedVIPs.length !== 1) {
      setMsg({
        type: "error",
        text: "Select exactly one VIP to test push notifications.",
      });
      return;
    }

    const vip = approvedVips.find(
      (item) =>
        String(item.number) === String(selectedVIPs[0])
    );

    if (!vip?.id) {
      setMsg({
        type: "error",
        text: "Could not find the selected VIP account.",
      });
      return;
    }

    setLoading(true);
    setLoadingText("Sending test notification…");
    setMsg(null);

    try {
      const res = await adminSendVipPushTest(token, vip.id);
      const result = res?.data ?? res;

      if (res?.success === false || result?.success === false) {
        throw new Error(
          result?.error ||
          res?.error ||
          "The test notification could not be sent."
        );
      }

      const sent = result?.sent ?? 0;

      setMsg({
        type: "success",
        text: `Test notification sent to ${sent} device subscription(s) for ${vip.name || vip.number}.`,
      });
    } catch (error) {
      setMsg({
        type: "error",
        text: error?.message || "Push test failed.",
      });
    } finally {
      setLoading(false);
      setLoadingText("");
    }
  };

  const distributePicks = async () => {
    if (
      !selectedVIPs.length ||
      !selectedMatches.length
    ) {
      setMsg({
        type: "error",
        text: "Select at least one VIP and one match.",
      });

      return;
    }

    const numericOdds = Number(odds);

    if (!pick.trim()) {
      setMsg({
        type: "error",
        text: "Enter a pick.",
      });

      return;
    }

    if (
      !Number.isFinite(numericOdds) ||
      numericOdds <= 1
    ) {
      setMsg({
        type: "error",
        text: "Odds must be greater than 1.00.",
      });

      return;
    }

    setLoading(true);
    setLoadingText("Distributing picks…");
    setMsg(null);

    try {
      const allPicks = selectedMatches.map((m) => ({
        match_id: m.match_id,
        pick,
        odds: numericOdds,
      }));

      const summaries = [];

      for (const vipNumber of selectedVIPs) {
        try {
          const payload = {
            number: vipNumber,
            picks: allPicks,
          };

          const res =
            await adminDistributeVipPicks(
              token,
              payload
            );

          if (res?.success === false) {
            summaries.push({
              number: vipNumber,
              success: false,
              error:
                res?.error ||
                res?.message ||
                "Failed to distribute picks",
            });

            continue;
          }

          const data = safeObj(res);

          summaries.push({
            number: vipNumber,
            success: true,
            ...(Array.isArray(data)
              ? { results: data }
              : data || {}),
          });
        } catch (err) {
          summaries.push({
            number: vipNumber,
            success: false,
            error:
              err?.message ||
              "Failed to distribute picks",
          });
        }
      }

      setDistributionSummary(
        summaries
      );

      const successful =
        summaries.filter(
          (item) => item.success
        ).length;

      const failed =
        summaries.length -
        successful;

      if (
        successful > 0 &&
        failed === 0
      ) {
        setMsg({
          type: "success",
          text: `Pick${
            allPicks.length === 1
              ? ""
              : "s"
          } distributed to ${
            successful
          } VIP${
            successful === 1
              ? ""
              : "s"
          }.`,
        });
      } else if (
        successful > 0
      ) {
        setMsg({
          type: "success",
          text: `Distributed to ${
            successful
          } VIP${
            successful === 1
              ? ""
              : "s"
          }; ${
            failed
          } failed.`,
        });
      } else {
        setMsg({
          type: "error",
          text: "No picks were distributed.",
        });
      }

      setSelectedVIPs([]);
      setSelectedMatches([]);

      await fetchAll();

      if (successful > 0) {
        await fetchVipPickHistory();
      }
    } catch (e) {
      console.error(
        "[ADMIN] Distribution failed:",
        e
      );

      showError(e);
    } finally {
      setLoading(false);
      setLoadingText("");
    }
  };

  const gradeMatchResult = async () => {
    if (!settlementMatchId || homeScore === "" || awayScore === "" || !settlementStatus) {
      setMsg({
        type: "error",
        text: "Select a match, enter both scores, and choose a status.",
      });
      return;
    }

    const home = Number(homeScore);
    const away = Number(awayScore);

    if (
      !Number.isInteger(home) ||
      home < 0 ||
      !Number.isInteger(away) ||
      away < 0
    ) {
      setMsg({
        type: "error",
        text: "Both scores must be whole numbers, zero or greater.",
      });
      return;
    }

    const selectedMatch = settlementMatches.find(
      (match) => String(match.id) === String(settlementMatchId)
    );

    const matchName = selectedMatch
      ? `${selectedMatch.home_team_name} vs ${selectedMatch.away_team_name}`
      : `Match ${settlementMatchId}`;

    if (
      !window.confirm(
        `Update ${matchName} to ${home} - ${away} with status "${settlementStatus}"?`
      )
    ) {
      return;
    }

    setLoading(true);
    setLoadingText("Updating match result…");
    setMsg(null);

    try {
      const res = await gradeMatch(
        Number(settlementMatchId),
        home,
        away,
        settlementStatus,
        token
      );

      if (!res?.success || res?.data?.success === false) {
        showError(
          res?.error ||
          res?.message ||
          res?.data?.error ||
          "Could not update match"
        );
        return;
      }

      setMsg({
        type: "success",
        text: "Match record updated successfully. The scheduler will process it automatically.",
      });

      setSettlementMatchId("");
      setHomeScore("");
      setAwayScore("");
      setSettlementStatus("");

      const refreshed = await getSettlementMatches(settlementDate, token);

      if (refreshed?.success) {
        setSettlementMatches(safeArray(refreshed));
      }
    } catch (error) {
      console.error("[ADMIN] Grade match failed:", error);
      showError(error);
    } finally {
      setLoading(false);
      setLoadingText("");
    }
  };

  const filteredVips = useMemo(() => {
    const q =
      search.trim().toLowerCase();

    return vips.filter((v) => {
      const matchSearch =
        !q ||
        String(v.name || "")
          .toLowerCase()
          .includes(q) ||
        String(v.number || "")
          .toLowerCase()
          .includes(q) ||
        String(v.id || "").includes(q);

      const matchApproved =
        filterApproved === "all" ||
        (filterApproved === "yes" &&
          v.approved) ||
        (filterApproved === "no" &&
          !v.approved);

      const matchPlan =
        filterPlan === "all" ||
        v.subscription ===
          filterPlan;

      return (
        matchSearch &&
        matchApproved &&
        matchPlan
      );
    });
  }, [
    vips,
    search,
    filterApproved,
    filterPlan,
  ]);

  const plans = useMemo(
    () =>
      [
        ...new Set(
          vips
            .map(
              (v) =>
                v.subscription
            )
            .filter(Boolean)
        ),
      ],
    [vips]
  );

  const approvedVips = useMemo(
    () =>
      vips.filter(
        (v) => v.approved
      ),
    [vips]
  );

  const eligibleApprovedVips = useMemo(
    () =>
      approvedVips.filter(
        (v) => Number(v.daily_quota_remaining) > 0
      ),
    [approvedVips]
  );

  const stats = useMemo(
    () => {
      const money = (value) =>
        `${Number(value || 0).toLocaleString("en-KE", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}`;

      const signedMoney = (value) => {
        const amount = Number(value || 0);
        const sign = amount > 0 ? "+" : amount < 0 ? "-" : "";

        return `${sign}${Math.abs(amount).toLocaleString("en-KE", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}`;
      };

      const profitLoss = Number(bettingOverview?.profit_loss || 0);
      const houseBalancePerformance = Number(
        bettingOverview?.house_balance_performance || 0
      );

      return [
        {
          label: "Total VIPs",
          value: vips.length,
          detail: `${vips.filter((v) => v.approved).length} approved`,
          icon: "◆",
        },
        {
          label: "Pending VIPs",
          value: pendingVips.length,
          detail: "Awaiting approval",
          icon: "◷",
        },
        {
          label: "Subscription requests",
          value: upgradeRequests.filter(
            (req) => req.status === "pending"
          ).length,
          detail: "Need review",
          icon: "↗",
        },
        {
          label: "Betting users",
          value: bettingOverview?.betting_users ?? "—",
          detail: "Registered betting accounts",
          icon: "●",
        },
        {
          label: "Bets today",
          value: bettingOverview?.bets_today ?? "—",
          detail: bettingOverview
            ? `${bettingOverview.single_bets_today} singles · ${bettingOverview.accumulator_tickets_today} accumulators`
            : "Betting activity today",
          icon: "▣",
        },
        {
          label: "High-stake bets today",
          value: bettingOverview?.high_stake_bets_today ?? "—",
          detail: "Individual stakes strictly above 1,500",
          icon: "◆",
        },
        {
          label: "High-stake amount today",
          value: bettingOverview
            ? money(bettingOverview.high_stake_amount_today)
            : "—",
          detail: "All single-bet and accumulator stakes placed today",
          icon: "◈",
        },
        {
          label: "Total bets overall",
          value: bettingOverview?.total_bets ?? "—",
          detail: bettingOverview
            ? `${bettingOverview.total_single_bets} singles · ${bettingOverview.total_accumulator_tickets} accumulators`
            : "All-time betting records",
          icon: "▤",
        },
        {
          label: "House balance",
          value: bettingOverview
            ? money(bettingOverview.house_balance)
            : "—",
          detail: "Current house wallet",
          icon: "◈",
        },
        {
          label: "House Capital Profit / Loss",
          value: bettingOverview
            ? signedMoney(bettingOverview.house_capital_profit_loss)
            : "—",
          detail: "House balance minus original 500 capital",
          icon: bettingOverview?.house_capital_profit_loss >= 0 ? "↗" : "↘",
        },
        {
          label: "House Balance Performance",
          value: bettingOverview
            ? signedMoney(houseBalancePerformance)
            : "—",
          detail: bettingOverview
            ? `Compared with starting balance ${money(bettingOverview.house_balance_baseline)}`
            : "Progressive house balance profit / loss",
          icon: houseBalancePerformance >= 0 ? "↗" : "↘",
        },
        {
          label: "M-PESA reserved",
          value: bettingOverview
            ? money(bettingOverview.mpesa_reserved_amount)
            : "—",
          detail: bettingOverview
            ? `${bettingOverview.mpesa_outstanding_count} unfinished house withdrawals`
            : "Outstanding house B2C payouts",
          icon: "◷",
        },
        {
          label: "Betting Profit / Loss",
          value: bettingOverview
            ? signedMoney(profitLoss)
            : "—",
          detail: "Net betting ledger; excludes M-PESA reservations",
          icon: profitLoss >= 0 ? "↗" : "↘",
        },
        {
          label: "Matches",
          value: allMatches.length,
          detail: "Available for picks",
          icon: "⚽",
        },
      ];
    },
    [vips, pendingVips, upgradeRequests, allMatches, bettingOverview]
  );

  const toggleVIP = (
    number,
    checked
  ) => {
    const eligible = eligibleApprovedVips.some(
      (v) => String(v.number) === String(number)
    );

    if (checked && !eligible) return;

    setSelectedVIPs((prev) =>
      checked
        ? prev.some((n) => String(n) === String(number))
          ? prev
          : [...prev, number]
        : prev.filter(
            (n) => String(n) !== String(number)
          )
    );
  };

  const toggleMatch = (
    match,
    checked
  ) => {
    setSelectedMatches(
      (prev) =>
        checked
          ? prev.some(
              (x) =>
                x.match_id ===
                match.match_id
            )
            ? prev
            : [...prev, match]
          : prev.filter(
              (x) =>
                x.match_id !==
                match.match_id
            )
    );
  };

  const selectAllApprovedVips =
    () => {
      const allEligibleSelected =
        eligibleApprovedVips.length > 0 &&
        eligibleApprovedVips.every((v) =>
          selectedVIPs.some(
            (number) => String(number) === String(v.number)
          )
        );

      setSelectedVIPs(
        allEligibleSelected
          ? []
          : eligibleApprovedVips.map((v) => v.number)
      );
    };

  const selectAllMatches = () => {
    setSelectedMatches(
      selectedMatches.length ===
        allMatches.length
        ? []
        : allMatches
    );
  };

  if (!token) {
    return <Navigate to="/lm-access-7qN4vP9x2K" replace />;
  }

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100">
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -left-32 -top-32 h-96 w-96 rounded-full bg-indigo-600/10 blur-3xl" />

        <div className="absolute -right-32 top-1/3 h-96 w-96 rounded-full bg-cyan-500/10 blur-3xl" />
      </div>

      <header className="sticky top-0 z-40 border-b border-white/[0.08] bg-[#080e1b]/90 shadow-lg shadow-black/10 backdrop-blur-2xl">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-1.5 px-2.5 py-2.5 sm:gap-4 sm:px-6 sm:py-3">
          <div className="flex min-w-0 items-center gap-2 sm:gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/15 bg-gradient-to-br from-indigo-500 via-indigo-500 to-cyan-400 text-lg font-black text-white shadow-lg shadow-indigo-500/20">
              L
            </div>

            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-white">
                LilyMac Admin
              </p>

              <p className="hidden truncate text-xs text-slate-500 sm:block">
                Operations control center
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => fetchAll(false)}
              disabled={loading}
              className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.045] px-2.5 py-2 text-sm font-semibold text-slate-300 transition hover:bg-white/[0.08] disabled:opacity-50 sm:px-3"
            >
              ↻ <span className="hidden sm:inline">Refresh</span>
            </button>

            <div className="hidden items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 sm:flex">
              <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,.8)]" />

              <span className="text-xs text-slate-400">
                {admin?.username ||
                  "Administrator"}
              </span>
            </div>

            <button
              type="button"
              onClick={
                adminPushEnabled
                  ? disableAdminNotifications
                  : enableAdminNotifications
              }
              disabled={pushLoading || !token}
              aria-pressed={adminPushEnabled}
              title={
                adminPushEnabled
                  ? "Disable admin push notifications"
                  : "Enable admin push notifications"
              }
              className={`rounded-xl border px-2 py-2 text-xs font-semibold transition disabled:opacity-50 sm:px-3 sm:text-sm ${
                adminPushEnabled
                  ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-300 hover:bg-emerald-400/20"
                  : "border-cyan-400/20 bg-cyan-400/10 text-cyan-300 hover:bg-cyan-400/20"
              }`}
            >
              {pushLoading ? (
                <>
                  <span className="sm:hidden">Wait…</span>
                  <span className="hidden sm:inline">Please wait...</span>
                </>
              ) : adminPushEnabled ? (
                <>
                  <span className="sm:hidden">Push on</span>
                  <span className="hidden sm:inline">Disable notifications</span>
                </>
              ) : (
                <>
                  <span className="sm:hidden">Push</span>
                  <span className="hidden sm:inline">Enable notifications</span>
                </>
              )}
            </button>

            <button
              type="button"
              onClick={logout}
              className="shrink-0 rounded-xl border border-rose-400/20 bg-rose-400/[0.07] px-2.5 py-2 text-xs font-bold text-rose-300 transition hover:bg-red-400/20"
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      <main className="relative mx-auto max-w-[1600px] px-3 py-4 sm:px-6 sm:py-5 lg:py-7">
        <div className="mb-5 overflow-hidden rounded-2xl border border-cyan-400/[0.12] bg-gradient-to-br from-[#14243a]/90 via-[#101b2d]/85 to-[#0b1422]/90 p-4 shadow-xl shadow-black/20 sm:mb-6 sm:rounded-3xl sm:p-6 lg:p-7">
          <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
            <div>
              <p className="mb-2 inline-flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.24em] text-cyan-300 sm:text-xs">
                Command center
              </p>

              <h1 className="text-2xl font-extrabold tracking-tight text-white sm:text-3xl lg:text-4xl">
                LilyMac Command Center
              </h1>

              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-400 sm:text-[15px]">
                Manage VIPs, picks,
                the available data and
                match settlement from
                one place.
              </p>

              {pushMessage && (
                <p className="mt-2 text-xs text-cyan-300" role="status">
                  {pushMessage}
                </p>
              )}
            </div>

            <div className="inline-flex items-center gap-2 self-start rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-xs text-slate-400 lg:self-auto">
              Auto refresh{" "}
              <span className="font-semibold text-slate-200">
                30s
              </span>
            </div>
          </div>
        </div>

        {msg && (
          <div className="mb-5">
            <Banner msg={msg} />
          </div>
        )}

        <nav className="mb-6 flex gap-1.5 overflow-x-auto rounded-2xl border border-white/[0.08] bg-[#0d1625]/90 p-1.5 shadow-lg shadow-black/10 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {[
            ["overview", "Overview"],
            ["bets", "Bet Management"],
            ["vip", "VIP Management"],
            [
              "distribution",
              "Pick Distribution",
            ],
            [
              "settlement",
              "Settlement",
            ],
            ["transactions", "Transactions"],
          ].map(
            ([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => {
                  setActiveSection(id);
                  if (id === "bets") {
                    fetchBets(1);
                  }
                  if (id === "transactions") {
                    fetchTransactions(1);
                  }
                  if (id === "distribution") {
                    fetchVipPickHistory();
                  }
                }}
                className={`whitespace-nowrap rounded-xl px-3.5 py-2.5 text-xs font-bold transition sm:px-4 sm:text-sm ${
                  activeSection === id
                    ? "border border-cyan-300/20 bg-gradient-to-r from-cyan-300 to-sky-400 text-slate-950 shadow-md shadow-cyan-500/10"
                    : "border border-transparent text-slate-400 hover:bg-white/[0.06] hover:text-slate-100"
                }`}
              >
                {label}
                {id === "vip" && pendingActionCount > 0 && (
                  <span className="ml-2 inline-flex h-5 min-w-5 items-center justify-center rounded-full border border-rose-300/20 bg-rose-500 px-1.5 text-[10px] font-extrabold text-white shadow-md shadow-rose-500/20">
                    {pendingActionCount > 99 ? "99+" : pendingActionCount}
                  </span>
                )}
              </button>
            )
          )}
        </nav>

        {activeSection ===
          "overview" && (
          <>
            <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
              {stats.map((stat) => (
                <StatCard
                  key={stat.label}
                  {...stat}
                />
              ))}
            </section>

            <section className="mt-6 overflow-hidden rounded-3xl border border-white/[0.09] bg-gradient-to-br from-[#111b2d]/95 via-[#0d1626]/95 to-[#0a1220]/95 p-4 shadow-xl shadow-black/20 sm:p-5">
              <div className="mb-5 flex flex-col gap-4 border-b border-white/[0.06] pb-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="text-base font-extrabold tracking-tight text-white sm:text-lg">
                    House Balance History
                  </h2>
                  <p className="mt-1 text-xs text-slate-400">
                    Recorded wallet balance over time · KES
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  {[
                    ["7d", "7 days"],
                    ["30d", "30 days"],
                    ["90d", "90 days"],
                    ["all", "All history"],
                  ].map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setHouseBalanceRange(value)}
                      className={`rounded-xl border px-3.5 py-2 text-xs font-bold transition ${
                        houseBalanceRange === value
                          ? "border-cyan-400/50 bg-cyan-400/10 text-cyan-300"
                          : "border-white/10 text-slate-400 hover:bg-white/[0.06] hover:text-white"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {houseBalanceHistoryLoading && !houseBalanceHistory && (
                <div className="flex h-56 items-center justify-center text-sm text-slate-400">
                  Loading house balance history…
                </div>
              )}

              {houseBalanceHistoryError && (
                <div className="rounded-xl border border-rose-400/20 bg-rose-400/5 p-3 text-sm text-rose-300">
                  {houseBalanceHistoryError}
                </div>
              )}

              {houseBalanceHistory?.points?.length > 0 && (
                <>
                  <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div className="rounded-2xl border border-cyan-400/15 bg-gradient-to-br from-cyan-400/[0.08] to-transparent p-4 shadow-inner shadow-black/10">
                      <p className="text-xs text-slate-500">Current wallet balance</p>
                      <p className="mt-1 text-base font-bold text-white">
                        {Number(
                          houseBalanceHistory.current_balance || 0
                        ).toLocaleString("en-KE", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                      </p>
                    </div>

                    <div className="rounded-2xl border border-cyan-400/15 bg-gradient-to-br from-cyan-400/[0.08] to-transparent p-4 shadow-inner shadow-black/10">
                      <p className="text-xs text-slate-500">First displayed balance</p>
                      <p className="mt-1 text-base font-bold text-white">
                        {Number(
                          houseBalanceHistory.points[0].balance
                        ).toLocaleString("en-KE", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                      </p>
                    </div>

                    <div className="rounded-2xl border border-emerald-400/15 bg-gradient-to-br from-emerald-400/[0.08] to-transparent p-4 shadow-inner shadow-black/10">
                      <p className="text-xs text-slate-500">Change across displayed points</p>
                      {(() => {
                        const points = houseBalanceHistory.points;
                        const change =
                          points[points.length - 1].balance -
                          points[0].balance;

                        return (
                          <p className={`mt-1 text-base font-bold ${
                            change >= 0 ? "text-emerald-400" : "text-rose-400"
                          }`}>
                            {change >= 0 ? "+" : "-"}{Math.abs(
                              change
                            ).toLocaleString("en-KE", {
                              minimumFractionDigits: 2,
                              maximumFractionDigits: 2,
                            })}
                          </p>
                        );
                      })()}
                    </div>
                  </div>

                  <div className="h-64 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart
                        data={houseBalanceHistory.points}
                        margin={{ top: 8, right: 8, left: 0, bottom: 4 }}
                      >
                        <defs>
                          <linearGradient
                            id="houseBalanceGradient"
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="1"
                          >
                            <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.30} />
                            <stop offset="95%" stopColor="#22d3ee" stopOpacity={0.01} />
                          </linearGradient>
                        </defs>

                        <CartesianGrid
                          stroke="#ffffff"
                          strokeOpacity={0.08}
                          vertical={false}
                        />

                        <XAxis
                          dataKey="timestamp"
                          tick={{ fill: "#94a3b8", fontSize: 11 }}
                          tickLine={false}
                          axisLine={false}
                          minTickGap={28}
                          tickFormatter={(value) =>
                            new Intl.DateTimeFormat("en-KE", {
                              day: "numeric",
                              month: "short",
                              timeZone: "Africa/Nairobi",
                            }).format(new Date(value))
                          }
                        />

                        <YAxis
                          width={76}
                          tick={{ fill: "#94a3b8", fontSize: 10 }}
                          tickLine={false}
                          axisLine={false}
                          tickFormatter={(value) =>
                            `KES ${Number(value).toLocaleString("en-KE", {
                              maximumFractionDigits: 0,
                            })}`
                          }
                        />

                        <Tooltip
                          contentStyle={{
                            background: "#0f172a",
                            border: "1px solid rgba(255,255,255,0.12)",
                            borderRadius: 12,
                            color: "#fff",
                          }}
                          labelStyle={{ color: "#94a3b8" }}
                          labelFormatter={(value) =>
                            new Intl.DateTimeFormat("en-KE", {
                              dateStyle: "medium",
                              timeStyle: "short",
                              timeZone: "Africa/Nairobi",
                            }).format(new Date(value))
                          }
                          formatter={(value) => [
                            `KES ${Number(value).toLocaleString("en-KE", {
                              minimumFractionDigits: 2,
                              maximumFractionDigits: 2,
                            })}`,
                            "House balance",
                          ]}
                        />

                        <Area
                          type="monotone"
                          dataKey="balance"
                          name="House balance"
                          stroke="#22d3ee"
                          strokeWidth={2}
                          fill="url(#houseBalanceGradient)"
                          activeDot={{ r: 5, fill: "#22d3ee" }}
                          dot={false}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>

                  <p className="mt-3 text-xs text-slate-500">
                    {houseBalanceHistory.transaction_count} recorded balance
                    points. Chart timestamps use East Africa Time.
                  </p>
                </>
              )}

              {!houseBalanceHistoryLoading &&
                !houseBalanceHistoryError &&
                houseBalanceHistory &&
                houseBalanceHistory.points.length === 0 && (
                  <div className="flex h-48 items-center justify-center text-sm text-slate-400">
                    No recorded balance transactions in this period.
                  </div>
                )}

              {houseBalanceHistoryLoading && houseBalanceHistory && (
                <p className="mt-2 text-right text-xs text-slate-500">
                  Updating history…
                </p>
              )}
            </section>


          </>
        )}

        {activeSection === "vip" && (
          <section className="space-y-5">
            <Card
              title="VIP Users"
              subtitle={`${filteredVips.length} of ${vips.length} VIP accounts`}
            >
              <div className="grid gap-2 md:grid-cols-[1fr_auto_auto]">
                <Input
                  placeholder="Search name, number or ID…"
                  value={search}
                  onChange={setSearch}
                />

                <Select
                  value={filterApproved}
                  onChange={
                    setFilterApproved
                  }
                >
                  <option value="all">
                    All statuses
                  </option>
                  <option value="yes">
                    Approved
                  </option>
                  <option value="no">
                    Not approved
                  </option>
                </Select>

                <Select
                  value={filterPlan}
                  onChange={setFilterPlan}
                >
                  <option value="all">
                    All plans
                  </option>

                  {plans.map(
                    (plan) => (
                      <option
                        key={plan}
                        value={plan}
                      >
                        {plan}
                      </option>
                    )
                  )}
                </Select>
              </div>

              <div className="mt-4 overflow-hidden rounded-2xl border border-white/10">
                <div className="overflow-x-auto">
                  <table className="min-w-[850px] w-full text-left text-sm">
                    <thead className="bg-[#162338]/90 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">
                      <tr>
                        <th className="px-4 py-3">
                          VIP
                        </th>

                        <th className="px-4 py-3">
                          Number
                        </th>

                        <th className="px-4 py-3">
                          Plan
                        </th>

                        <th className="px-4 py-3">
                          Status
                        </th>

                        <th className="px-4 py-3">
                          Expiry
                        </th>

                        <th className="px-4 py-3 text-right">
                          Action
                        </th>
                      </tr>
                    </thead>

                    <tbody className="divide-y divide-white/5">
                      {filteredVips.map(
                        (v) => (
                          <tr
                            key={v.id}
                            className="transition-colors duration-150 hover:bg-cyan-400/[0.045]"
                          >
                            <td className="px-4 py-3">
                              <div>
                                <p className="font-semibold text-white">
                                  {v.name ||
                                    "Unnamed"}
                                </p>

                                <p className="text-xs text-slate-500">
                                  ID #
                                  {v.id}
                                </p>
                              </div>
                            </td>

                            <td className="px-4 py-3 text-slate-300">
                              {v.number ||
                                "—"}
                            </td>

                            <td className="px-4 py-3">
                              <div className="flex flex-col items-start gap-1">
                                <Badge>
                                  {v.subscription ||
                                    "—"}
                                </Badge>

                                {v.queued_subscription && (
                                  <span className="text-[11px] font-semibold text-amber-300">
                                    Queued: {v.queued_subscription}
                                  </span>
                                )}
                              </div>
                            </td>

                            <td className="px-4 py-3">
                              <StatusBadge
                                active={Boolean(
                                  v.approved
                                )}
                              />
                            </td>

                            <td className="px-4 py-3 text-slate-400">
                              {v.subscription_expiry ||
                                "—"}
                            </td>

                            <td className="px-4 py-3">
                              <div className="flex justify-end gap-2">
                                {!v.approved && (
                                  <>
                                    <Btn
                                      success
                                      small
                                      onClick={() =>
                                        vipAction(
                                          v.id,
                                          "approve"
                                        )
                                      }
                                    >
                                      Approve
                                    </Btn>

                                    <Btn
                                      danger
                                      small
                                      onClick={() =>
                                        vipAction(
                                          v.id,
                                          "decline"
                                        )
                                      }
                                    >
                                      Decline
                                    </Btn>
                                  </>
                                )}

                                {v.approved && (
                                  <span className="text-xs text-slate-600">
                                    Active
                                  </span>
                                )}

                                <Btn
                                  small
                                  onClick={() => setVipPassword(v)}
                                >
                                  {v.has_password ? "Reset Password" : "Set Password"}
                                </Btn>

                                <Btn
                                  danger
                                  small
                                  onClick={() =>
                                    vipAction(
                                      v.id,
                                      "delete"
                                    )
                                  }
                                >
                                  Delete
                                </Btn>
                              </div>
                            </td>
                          </tr>
                        )
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {!filteredVips.length && (
                <Empty text="No VIP users match the current filters." />
              )}
            </Card>

            {(pendingVips.length > 0 || pendingUpgradeRequests.length > 0) && (
            <div className="grid gap-5 xl:grid-cols-2">
              {pendingVips.length > 0 && (
              <Card
                title="Pending approvals"
                subtitle="Review new VIP requests"
              >
                <div className="space-y-2">
                  {pendingVips.map(
                    (v) => (
                      <div
                        key={v.id}
                        className="flex flex-col gap-3 rounded-2xl border border-white/[0.07] bg-gradient-to-r from-white/[0.035] to-white/[0.015] p-4 transition-colors hover:border-cyan-400/20 sm:flex-row sm:items-center sm:justify-between"
                      >
                        <div>
                          <p className="text-sm font-semibold text-white">
                            {v.name ||
                              "Unnamed"}
                          </p>

                          <p className="text-xs text-slate-500">
                            {v.number ||
                              "—"}
                          </p>
                        </div>

                        <div className="flex flex-wrap gap-2">
                          <Btn
                            success
                            small
                            onClick={() =>
                              vipAction(
                                v.id,
                                "approve"
                              )
                            }
                          >
                            Approve
                          </Btn>

                          <Btn
                            danger
                            small
                            onClick={() =>
                              vipAction(
                                v.id,
                                "decline"
                              )
                            }
                          >
                            Decline
                          </Btn>

                          <Btn
                            danger
                            small
                            onClick={() =>
                              vipAction(
                                v.id,
                                "delete"
                              )
                            }
                          >
                            Delete
                          </Btn>
                        </div>
                      </div>
                    )
                  )}

                  {!pendingVips.length && (
                    <Empty text="No pending VIPs." />
                  )}
                </div>
              </Card>
              )}

              {pendingUpgradeRequests.length > 0 && (
              <Card
                title="Subscription requests"
                subtitle="Approve or decline renewals and upgrades"
              >
                <div className="space-y-2">
                  {pendingUpgradeRequests.map(
                    (req) => (
                      <div
                        key={req.id}
                        className="flex flex-col gap-3 rounded-2xl border border-white/[0.07] bg-gradient-to-r from-white/[0.035] to-white/[0.015] p-4 transition-colors hover:border-cyan-400/20 sm:flex-row sm:items-center sm:justify-between"
                      >
                        <div>
                          <p className="text-sm font-semibold text-white">
                            {req.vip_name ||
                              req.name ||
                              req.number ||
                              "VIP"}
                          </p>

                          <p className="text-xs text-slate-500">
                            <span className="font-semibold text-amber-400">
                              {req.request_type === "renewal" ? "Renewal" : "Upgrade"}
                            </span>
                            {" · "}
                            {req.number ||
                              "—"}{" "}
                            →{" "}
                            {req.to_plan ||
                              req.plan ||
                              req.toPlan ||
                              "—"}
                          </p>
                        </div>

                        <div className="flex flex-wrap items-center gap-2">
                          {req.status === "pending" ? (
                            <>
                              <Btn
                                success
                                small
                                onClick={() =>
                                  upgradeAction(
                                    req.id,
                                    "approve"
                                  )
                                }
                              >
                                Approve
                              </Btn>

                              <Btn
                                danger
                                small
                                onClick={() =>
                                  upgradeAction(
                                    req.id,
                                    "decline"
                                  )
                                }
                              >
                                Decline
                              </Btn>
                            </>
                          ) : (
                            <span
                              className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase ${
                                req.status === "approved"
                                  ? "bg-emerald-500/15 text-emerald-400"
                                  : "bg-red-500/15 text-red-400"
                              }`}
                            >
                              {req.status || "unknown"}
                            </span>
                          )}
                        </div>
                      </div>
                    )
                  )}

                  {!pendingUpgradeRequests.length && (
                    <Empty text="No subscription requests." />
                  )}
                </div>
              </Card>
              )}
            </div>
            )} 
          </section>
        )}

        {activeSection ===
          "distribution" && (
          <section className="space-y-5">
            <Card
              title="Distribute picks"
              subtitle="Select approved VIPs and one or more matches"
              action={
                <div className="text-xs text-slate-500">
                  {selectedVIPs.length}{" "}
                  VIPs ·{" "}
                  {selectedMatches.length}{" "}
                  matches
                </div>
              }
            >
              <div className="grid gap-5 xl:grid-cols-2">
                <SelectionPanel
                  title="Approved VIPs"
                  count={
                    selectedVIPs.length
                  }
                  onSelectAll={
                    selectAllApprovedVips
                  }
                  allSelected={
                    eligibleApprovedVips.length > 0 &&
                    eligibleApprovedVips.every((v) =>
                      selectedVIPs.some(
                        (number) => String(number) === String(v.number)
                      )
                    )
                  }
                >
                  {approvedVips.map(
                    (v) => (
                      <CheckRow
                        key={v.number}
                        checked={selectedVIPs.some(
                          (number) => String(number) === String(v.number)
                        )}
                        disabled={Number(v.daily_quota_remaining) <= 0}
                        status={
                          Number(v.daily_quota_remaining) <= 0
                            ? "Daily quota full"
                            : `${v.daily_quota_remaining} picks remaining`
                        }
                        onChange={(
                          checked
                        ) =>
                          toggleVIP(
                            v.number,
                            checked
                          )
                        }
                        title={
                          v.name ||
                          "Unnamed VIP"
                        }
                        subtitle={`${v.number || "—"} · ${
                          v.subscription ||
                          "No plan"
                        }`}
                      />
                    )
                  )}

                  {!approvedVips.length && (
                    <Empty text="No approved VIPs." />
                  )}

                  {approvedVips.length > 0 &&
                    eligibleApprovedVips.length === 0 && (
                      <Empty text="All approved VIPs have used their daily quota." />
                    )}

                  <div className="mt-4 border-t border-white/10 pt-4">
                    <Btn
                      onClick={sendVipPushTest}
                      disabled={
                        loading ||
                        selectedVIPs.length !== 1
                      }
                    >
                      Send test notification
                    </Btn>
                    <p className="mt-2 text-xs text-slate-400">
                      Select exactly one approved VIP above. This sends a test push only; it does not distribute picks.
                    </p>
                  </div>
                </SelectionPanel>

                <SelectionPanel
                  title="Matches"
                  count={
                    selectedMatches.length
                  }
                  onSelectAll={
                    selectAllMatches
                  }
                  allSelected={
                    allMatches.length >
                      0 &&
                    selectedMatches.length ===
                      allMatches.length
                  }
                >
                  {Object.entries(
                    allMatches.reduce(
                      (acc, m) => {
                        const date =
                          formatDate(
                            m.local ||
                              m.match_time,
                            "Unknown date"
                          );

                        (acc[date] ||= []).push(
                          m
                        );

                        return acc;
                      },
                      {}
                    )
                  ).map(
                    ([date, matches]) => (
                      <div
                        key={date}
                        className="mb-4 last:mb-0"
                      >
                        <p className="mb-2 px-1 text-[11px] font-bold uppercase tracking-wider text-cyan-400">
                          {date}
                        </p>

                        <div className="space-y-1">
                          {matches.map(
                            (m) => (
                              <CheckRow
                                key={
                                  m.match_id
                                }
                                checked={selectedMatches.some(
                                  (sm) =>
                                    sm.match_id ===
                                    m.match_id
                                )}
                                onChange={(
                                  checked
                                ) =>
                                  toggleMatch(
                                    m,
                                    checked
                                  )
                                }
                                title={`${m.home || "Home"} vs ${
                                  m.away ||
                                  "Away"
                                }`}
                                subtitle={formatTime(
                                  m.local ||
                                    m.match_time
                                )}
                              />
                            )
                          )}
                        </div>
                      </div>
                    )
                  )}

                  {!allMatches.length && (
                    <Empty text="No matches available." />
                  )}
                </SelectionPanel>
              </div>

              <div className="mt-5 grid gap-3 rounded-2xl border border-white/10 bg-white/[0.025] p-4 md:grid-cols-[1fr_180px_auto]">
                <Select
                  value={pick}
                  onChange={setPick}
                >
                  <option value="1X2">1X2</option>
                  <option value="1">Home Win (1)</option>
                  <option value="X">Draw (X)</option>
                  <option value="2">Away Win (2)</option>
                  <option value="Over 1.5">Over 1.5</option>
                  <option value="Under 1.5">Under 1.5</option>
                  <option value="Over 2.5">Over 2.5</option>
                  <option value="Under 2.5">Under 2.5</option>
                  <option value="Over 3.5">Over 3.5</option>
                  <option value="Under 3.5">Under 3.5</option>
                  <option value="BTTS Yes">BTTS Yes</option>
                  <option value="BTTS No">BTTS No</option>
                </Select>

                <Input
                  type="number"
                  placeholder="Odds"
                  value={odds}
                  onChange={setOdds}
                />

                <Btn
                  success
                  onClick={
                    distributePicks
                  }
                  disabled={
                    loading ||
                    !selectedVIPs.length ||
                    !selectedMatches.length
                  }
                >
                  Distribute
                </Btn>
              </div>
            </Card>

            <Card
              title="Distribution results"
              subtitle="Latest API response"
            >
              {!distributionSummary.length ? (
                <Empty text="No distribution results yet." />
              ) : (
                <div className="grid gap-2 md:grid-cols-2">
                  {distributionSummary.map(
                    (item, index) => (
                      <div
                        key={index}
                        className="rounded-xl border border-white/10 bg-black/20 p-4"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-semibold text-white">
                            VIP: {item.number || "Unknown"}
                          </span>
                          <span
                            className={`rounded-full px-3 py-1 text-xs font-semibold ${
                              item.success
                                ? "bg-emerald-500/10 text-emerald-400"
                                : "bg-red-500/10 text-red-400"
                            }`}
                          >
                            {item.success ? "Successful" : "Failed"}
                          </span>
                        </div>

                        <p className="mt-2 text-sm text-slate-300">
                          {item.success
                            ? item.message ||
                              (Array.isArray(item.results)
                                ? `${item.results.length} pick result(s) returned.`
                                : "Distribution completed successfully.")
                            : item.error || "Distribution failed."}
                        </p>
                      </div>
                    )
                  )}
                </div>
              )}
            </Card>

            <Card
              title="VIP distribution history"
              subtitle="Permanent delivery records · Times shown in East Africa Time"
              action={
                <Btn
                  small
                  onClick={fetchVipPickHistory}
                  disabled={vipHistoryLoading}
                >
                  {vipHistoryLoading ? "Refreshing…" : "Refresh history"}
                </Btn>
              }
            >
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <Input
                  type="text"
                  placeholder="Search VIP phone number"
                  value={vipHistoryNumber}
                  onChange={setVipHistoryNumber}
                />

                <Select
                  value={vipHistoryPlan}
                  onChange={setVipHistoryPlan}
                >
                  <option value="all">All plans</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                  <option value="yearly">Yearly</option>
                </Select>

                <Input
                  type="date"
                  value={vipHistoryFrom}
                  onChange={setVipHistoryFrom}
                />

                <Input
                  type="date"
                  value={vipHistoryTo}
                  onChange={setVipHistoryTo}
                />
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Btn
                  small
                  onClick={fetchVipPickHistory}
                  disabled={vipHistoryLoading}
                >
                  Apply filters
                </Btn>

                <Btn
                  small
                  onClick={() => {
                    setVipHistoryNumber("");
                    setVipHistoryPlan("all");
                    setVipHistoryFrom("");
                    setVipHistoryTo("");
                  }}
                  disabled={vipHistoryLoading}
                >
                  Clear filters
                </Btn>

                <span className="text-xs text-slate-500">
                  Showing up to 500 records per request
                </span>
              </div>

              {vipHistoryError && (
                <div className="mt-4 rounded-xl border border-red-400/20 bg-red-500/10 p-3 text-sm text-red-300">
                  {vipHistoryError}
                </div>
              )}

              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
                {[
                  ["Delivered", vipHistoryTotals.total],
                  ["Won", vipHistoryTotals.won],
                  ["Lost", vipHistoryTotals.lost],
                  ["Pending", vipHistoryTotals.pending],
                  ["Ungraded", vipHistoryTotals.ungraded],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="rounded-xl border border-white/10 bg-white/[0.025] p-3"
                  >
                    <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                      {label}
                    </p>
                    <p className="mt-1 text-xl font-extrabold text-slate-100">
                      {Number(value || 0).toLocaleString()}
                    </p>
                  </div>
                ))}
              </div>

              <div className="mt-4 overflow-hidden rounded-2xl border border-white/10">
                <div className="overflow-x-auto">
                  <table className="min-w-[1150px] w-full text-left text-xs">
                    <thead className="bg-[#162338]/90 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      <tr>
                        <th className="px-3 py-3">Delivered</th>
                        <th className="px-3 py-3">VIP</th>
                        <th className="px-3 py-3">Plan</th>
                        <th className="px-3 py-3">Match / Competition</th>
                        <th className="px-3 py-3">Kick-off</th>
                        <th className="px-3 py-3">Selection</th>
                        <th className="px-3 py-3">Odds</th>
                        <th className="px-3 py-3">Score</th>
                        <th className="px-3 py-3">Result</th>
                      </tr>
                    </thead>

                    <tbody className="divide-y divide-white/5">
                      {vipHistory.map((item) => {
                        const result = String(
                          item.result || "pending"
                        ).toLowerCase();

                        const resultClass =
                          result === "won"
                            ? "bg-emerald-500/15 text-emerald-400"
                            : result === "lost"
                              ? "bg-red-500/15 text-red-400"
                              : result === "pending"
                                ? "bg-amber-500/15 text-amber-300"
                                : "bg-slate-500/15 text-slate-300";

                        return (
                          <tr
                            key={item.id}
                            className="text-slate-300 hover:bg-white/[0.025]"
                          >
                            <td className="whitespace-nowrap px-3 py-3">
                              {formatVipHistoryDate(
                                item.delivered_at_kenya || item.delivered_at
                              )}
                            </td>
                            <td className="px-3 py-3">
                              <div className="font-semibold text-slate-100">
                                {item.vip_name || "Unnamed VIP"}
                              </div>
                              <div className="text-slate-500">
                                {item.number || "—"}
                              </div>
                            </td>
                            <td className="px-3 py-3 capitalize">
                              {item.plan || "—"}
                            </td>
                            <td className="px-3 py-3">
                              <div className="font-semibold text-slate-100">
                                {item.home_team || "Home"} vs {item.away_team || "Away"}
                              </div>
                              <div className="mt-1 text-slate-500">
                                {item.competition || "Competition unavailable"}
                              </div>
                            </td>
                            <td className="whitespace-nowrap px-3 py-3">
                              {formatVipHistoryDate(item.match_time)}
                            </td>
                            <td className="px-3 py-3 font-semibold text-cyan-300">
                              {item.selection || "—"}
                            </td>
                            <td className="px-3 py-3 tabular-nums">
                              {item.odds == null
                                ? "—"
                                : Number(item.odds).toFixed(2)}
                            </td>
                            <td className="px-3 py-3 font-bold tabular-nums">
                              {item.home_score == null || item.away_score == null
                                ? "—"
                                : `${item.home_score} - ${item.away_score}`}
                            </td>
                            <td className="px-3 py-3">
                              <span
                                className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase ${resultClass}`}
                              >
                                {result}
                              </span>
                            </td>
                          </tr>
                        );
                      })}

                      {!vipHistory.length && (
                        <tr>
                          <td
                            colSpan={9}
                            className="px-4 py-8 text-center text-sm text-slate-500"
                          >
                            {vipHistoryLoading
                              ? "Loading distribution history…"
                              : "No distribution history found for these filters."}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </Card>
          </section>
        )}





        {activeSection === "bets" && (
          <section className="space-y-5">
            <Card
              title="Bet Management"
              subtitle="Review single bets and accumulator tickets. This section is read-only."
              action={
                <Btn
                  small
                  onClick={() => fetchBets(betMeta.page || 1)}
                  disabled={betLoading}
                >
                  {betLoading ? "Loading…" : "Refresh"}
                </Btn>
              }
            >
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4">
                <div className="sm:col-span-2 md:col-span-2">
                  <Input
                    placeholder="Search phone, user ID or bet ID"
                    value={betSearch}
                    onChange={setBetSearch}
                  />
                </div>

                <Select
                  value={betType}
                  onChange={setBetType}
                  options={[
                    { value: "all", label: "All bet types" },
                    { value: "single", label: "Single bets" },
                    { value: "accumulator", label: "Accumulators" },
                  ]}
                />

                <Select
                  value={betStatus}
                  onChange={setBetStatus}
                  options={[
                    { value: "all", label: "All statuses" },
                    { value: "pending", label: "Pending" },
                    { value: "won", label: "Won" },
                    { value: "lost", label: "Lost" },
                    { value: "void", label: "Void" },
                    { value: "cancelled", label: "Cancelled" },
                    { value: "cashed_out", label: "Cashed out" },
                  ]}
                />
              </div>

              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-slate-500">
                  {formatNumber(betMeta.total)} matching records
                </p>

                <div className="flex gap-2">
                  <Btn
                    small
                    onClick={() => {
                      setBetSearch("");
                      setBetStatus("all");
                      setBetType("all");
                      setTimeout(() => fetchBets(1), 0);
                    }}
                    disabled={betLoading}
                  >
                    Reset
                  </Btn>

                  <Btn
                    small
                    success
                    onClick={() => fetchBets(1)}
                    disabled={betLoading}
                  >
                    Apply filters
                  </Btn>
                </div>
              </div>
            </Card>

            <Card
              title="Bet records"
              subtitle={`Page ${betMeta.page} of ${Math.max(1, betMeta.total_pages)}`}
            >
              {betLoading ? (
                <div className="py-10 text-center text-sm text-slate-400">
                  Loading bet records…
                </div>
              ) : !betRecords.length ? (
                <Empty text="No bet records found for these filters." />
              ) : (
                <div className="space-y-3">
                  {betRecords.map((bet) => {
                    const recordKey = `${bet.bet_type}-${bet.bet_id}`;
                    const isExpanded = expandedBet === recordKey;
                    const selections = Array.isArray(bet.selections)
                      ? bet.selections
                      : [];

                    return (
                      <div
                        key={recordKey}
                        className="overflow-hidden rounded-2xl border border-white/[0.08] bg-gradient-to-br from-[#142137]/75 to-[#0b1422]/90 shadow-lg shadow-black/10 transition-colors hover:border-cyan-400/20"
                      >
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedBet(
                              isExpanded ? null : recordKey
                            )
                          }
                          className="w-full p-4 text-left transition-colors duration-200 hover:bg-cyan-400/[0.035] sm:p-5"
                        >
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div>
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-bold text-white">
                                  #{bet.bet_id}
                                </span>

                                <Badge>
                                  {bet.bet_type === "single"
                                    ? "Single"
                                    : "Accumulator"}
                                </Badge>

                                <span className="rounded-lg bg-white/5 px-2 py-1 text-xs text-slate-300">
                                  {String(bet.status || "unknown").replaceAll("_", " ")}
                                </span>
                              </div>

                              <p className="mt-2 text-sm text-slate-300">
                                {bet.phone || "Phone unavailable"}
                                <span className="mx-2 text-slate-600">•</span>
                                User ID: {bet.user_id}
                              </p>

                              <p className="mt-1 text-xs text-slate-500">
                                {formatDate(bet.created)} · {formatTime(bet.created)}
                              </p>
                            </div>

                            <div className="grid grid-cols-2 gap-x-5 gap-y-2 text-right sm:grid-cols-3">
                              <div>
                                <p className="text-[11px] text-slate-500">Stake</p>
                                <p className="font-semibold text-white">
                                  KSh {formatNumber(bet.stake)}
                                </p>
                              </div>

                              <div>
                                <p className="text-[11px] text-slate-500">Odds</p>
                                <p className="font-semibold text-white">
                                  {formatNumber(bet.total_odds)}
                                </p>
                              </div>

                              <div>
                                <p className="text-[11px] text-slate-500">Potential</p>
                                <p className="font-semibold text-cyan-300">
                                  KSh {formatNumber(bet.potential)}
                                </p>
                              </div>
                            </div>
                          </div>

                          <p className="mt-3 text-xs font-semibold text-cyan-400">
                            {isExpanded ? "Hide selections ▲" : `View ${selections.length} selection(s) ▼`}
                          </p>
                        </button>

                        {isExpanded && (
                          <div className="border-t border-cyan-400/10 bg-[#081321]/80 p-4 sm:p-5">
                            <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
                              <MiniMetric
                                label="Bet ID"
                                value={bet.bet_id}
                              />
                              <MiniMetric
                                label="Current cashout"
                                value={`KSh ${formatNumber(bet.current_cashout)}`}
                              />
                              <MiniMetric
                                label="Cashed out"
                                value={bet.cashed_out ? "Yes" : "No"}
                              />
                            </div>

                            <h3 className="mb-2 text-sm font-bold text-white">
                              Selections
                            </h3>

                            {!selections.length ? (
                              <Empty text="No selection details available." />
                            ) : (
                              <div className="space-y-2">
                                {selections.map((selection, index) => (
                                  <div
                                    key={`${recordKey}-selection-${index}`}
                                    className="rounded-xl border border-white/[0.07] bg-white/[0.035] p-3 transition-colors hover:border-cyan-400/15"
                                  >
                                    <div className="flex flex-wrap justify-between gap-2">
                                      <p className="text-sm font-semibold text-white">
                                        {selection.home_team || "Home team"}
                                        {" vs "}
                                        {selection.away_team || "Away team"}
                                      </p>
                                      <span className="text-xs text-cyan-300">
                                        Odds: {formatNumber(selection.odds)}
                                      </span>
                                    </div>

                                    <p className="mt-1 text-sm text-slate-300">
                                      Pick: {selection.selection || "—"}
                                    </p>

                                    <p className="mt-1 text-xs text-slate-500">
                                      {selection.league || "Competition unavailable"}
                                      {" · "}
                                      {formatDate(selection.match_time)}
                                      {selection.status
                                        ? ` · ${selection.status}`
                                        : ""}
                                    </p>

                                    {selection.match_id && (
                                      <p className="mt-1 text-xs text-slate-600">
                                        Match ID: {selection.match_id}
                                      </p>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              <div className="mt-5 flex flex-col flex-wrap items-start justify-between gap-3 border-t border-white/[0.08] pt-4 sm:flex-row sm:items-center">
                <p className="text-xs text-slate-500">
                  Showing {betRecords.length} of {formatNumber(betMeta.total)} records
                </p>

                <div className="flex items-center gap-2">
                  <Btn
                    small
                    onClick={() => fetchBets(betMeta.page - 1)}
                    disabled={betLoading || betMeta.page <= 1}
                  >
                    Previous
                  </Btn>

                  <span className="px-2 text-xs text-slate-400">
                    {betMeta.page} / {Math.max(1, betMeta.total_pages)}
                  </span>

                  <Btn
                    small
                    onClick={() => fetchBets(betMeta.page + 1)}
                    disabled={
                      betLoading ||
                      betMeta.page >= betMeta.total_pages
                    }
                  >
                    Next
                  </Btn>
                </div>
              </div>
            </Card>
          </section>
        )}

        {activeSection ===
          "settlement" && (
          <section className="grid gap-5 xl:grid-cols-2">
            <Card
              title="Grade match"
              subtitle="Settle a match result"
            >
              <div className="grid gap-4">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-slate-400">
                    Match date
                  </label>
                  <Input
                    type="date"
                    value={settlementDate}
                    onChange={setSettlementDate}
                  />
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-slate-400">
                    Unfinished match
                  </label>
                  <Select
                    value={settlementMatchId}
                    onChange={(value) => {
                      setSettlementMatchId(value);
                      setHomeScore("");
                      setAwayScore("");
                      setSettlementStatus("");
                    }}
                  >
                    <option value="">
                      {settlementLoading
                        ? "Loading matches…"
                        : settlementMatches.length
                          ? "Select a match"
                          : "No unfinished matches for this date"}
                    </option>
                    {settlementMatches.map((match) => (
                      <option key={match.id} value={String(match.id)}>
                        {match.home_team_name} vs {match.away_team_name}
                        {match.competition ? ` · ${match.competition}` : ""}
                      </option>
                    ))}
                  </Select>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-slate-400">
                      Home score
                    </label>
                    <Input
                      type="number"
                      placeholder="Home"
                      value={homeScore}
                      onChange={setHomeScore}
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-slate-400">
                      Away score
                    </label>
                    <Input
                      type="number"
                      placeholder="Away"
                      value={awayScore}
                      onChange={setAwayScore}
                    />
                  </div>
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-slate-400">
                    Match status
                  </label>
                  <Select
                    value={settlementStatus}
                    onChange={setSettlementStatus}
                  >
                    <option value="">Select status</option>
                    {settlementStatuses.map((status) => (
                      <option key={status} value={status}>
                        {status}
                      </option>
                    ))}
                  </Select>
                </div>

                <Btn
                  success
                  onClick={gradeMatchResult}
                  disabled={
                    loading ||
                    settlementLoading ||
                    !settlementMatchId ||
                    homeScore === "" ||
                    awayScore === "" ||
                    !settlementStatus
                  }
                >
                  Grade match
                </Btn>

                <p className="text-xs text-slate-500">
                  This updates only the match result and status in the database.
                  The existing scheduler handles subsequent bet processing.
                </p>
              </div>
            </Card>

          </section>
        )}

        {activeSection === "transactions" && (
          <section className="space-y-5">
            <Card
              title="Transactions Management"
              subtitle="Read-only wallet ledger, M-PESA deposit requests and withdrawals."
              action={
                <Btn
                  small
                  onClick={() => fetchTransactions(transactionMeta.page || 1)}
                  disabled={transactionLoading}
                >
                  {transactionLoading ? "Loading…" : "Refresh"}
                </Btn>
              }
            >
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
                  <p className="text-xs text-slate-500">Wallet ledger</p>
                  <p className="mt-1 text-2xl font-bold text-white">
                    {formatNumber(transactionCounts.wallet)}
                  </p>
                </div>

                <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
                  <p className="text-xs text-slate-500">Uncredited deposit attempts</p>
                  <p className="mt-1 text-2xl font-bold text-white">
                    {formatNumber(transactionCounts.deposit_attempt)}
                  </p>
                </div>

                <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
                  <p className="text-xs text-slate-500">M-PESA withdrawals</p>
                  <p className="mt-1 text-2xl font-bold text-white">
                    {formatNumber(transactionCounts.withdrawal)}
                  </p>
                </div>
              </div>

              <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="sm:col-span-2">
                  <Input
                    placeholder="Search phone, receipt, reference or description"
                    value={transactionSearch}
                    onChange={setTransactionSearch}
                  />
                </div>

                <Select
                  value={transactionCategory}
                  onChange={setTransactionCategory}
                >
                  <option value="all">All categories</option>
                  <option value="wallet">Wallet transactions</option>
                  <option value="deposit_attempt">Deposit attempts</option>
                  <option value="withdrawal">M-PESA withdrawals</option>
                </Select>

                <Select
                  value={transactionStatus}
                  onChange={setTransactionStatus}
                >
                  <option value="all">All statuses</option>
                  <option value="completed">Completed</option>
                  <option value="success">Success</option>
                  <option value="pending">Pending</option>
                  <option value="submitted">Submitted</option>
                  <option value="processing">Processing</option>
                  <option value="submission_unknown">Submission unknown</option>
                  <option value="timeout">Timeout</option>
                  <option value="failed">Failed</option>
                  <option value="cancelled">Cancelled</option>
                </Select>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <Btn
                  small
                  onClick={() => {
                    setTransactionSearch("");
                    setTransactionCategory("all");
                    setTransactionStatus("all");
                    fetchTransactions(1, {
                      search: "",
                      category: "all",
                      status: "all",
                    });
                  }}
                  disabled={transactionLoading}
                >
                  Reset
                </Btn>

                <Btn
                  small
                  success
                  onClick={() => fetchTransactions(1)}
                  disabled={transactionLoading}
                >
                  Apply filters
                </Btn>
              </div>
            </Card>

            <Card
              title="Transaction records"
              subtitle={`Page ${transactionMeta.page} of ${Math.max(1, transactionMeta.total_pages)}`}
            >
              {transactionLoading && !transactionRecords.length ? (
                <Empty text="Loading transaction records…" />
              ) : !transactionRecords.length ? (
                <Empty text="No transactions match these filters." />
              ) : (
                <div className="space-y-3">
                  {transactionRecords.map((item) => {
                    const expanded =
                      expandedTransaction === item.record_key;

                    const categoryLabel =
                      item.category === "wallet"
                        ? "Wallet"
                        : item.category === "deposit_attempt"
                          ? "M-PESA deposit attempt"
                          : "M-PESA withdrawal";

                    const statusText = String(item.status || "unknown")
                      .replaceAll("_", " ");

                    return (
                      <div
                        key={item.record_key}
                        className="overflow-hidden rounded-2xl border border-white/[0.08] bg-slate-950/50"
                      >
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedTransaction(
                              expanded ? null : item.record_key
                            )
                          }
                          className="grid w-full gap-3 p-4 text-left sm:grid-cols-[1fr_auto] sm:items-center"
                        >
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-bold text-white">
                                {categoryLabel}
                              </span>

                              <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] font-semibold uppercase text-slate-300">
                                {statusText}
                              </span>
                            </div>

                            <p className="mt-1 text-xs text-slate-400">
                              User: {item.user_phone || "—"} · ID: {item.user_id}
                            </p>

                            <p className="mt-1 truncate text-xs text-slate-500">
                              {item.description || item.type || "Transaction"}
                              {item.reference ? ` · Ref: ${item.reference}` : ""}
                            </p>

                            <p className="mt-1 text-[11px] text-slate-600">
                              {formatVipHistoryDate(item.created)}
                            </p>
                          </div>

                          <div className="flex items-center justify-between gap-4 sm:justify-end">
                            <span className="text-base font-bold tabular-nums text-white">
                              KSh {formatNumber(item.amount)}
                            </span>

                            <span className="text-xs text-slate-500">
                              {expanded ? "Hide details ▲" : "Details ▼"}
                            </span>
                          </div>
                        </button>

                        {expanded && (
                          <div className="grid grid-cols-1 gap-3 border-t border-white/[0.08] bg-white/[0.02] p-4 text-xs sm:grid-cols-2 lg:grid-cols-3">
                            <div>
                              <p className="text-slate-500">Record type</p>
                              <p className="mt-1 break-all text-slate-200">
                                {item.type || "—"}
                              </p>
                            </div>

                            <div>
                              <p className="text-slate-500">Transaction phone</p>
                              <p className="mt-1 break-all text-slate-200">
                                {item.phone || "—"}
                              </p>
                            </div>

                            <div>
                              <p className="text-slate-500">M-PESA receipt</p>
                              <p className="mt-1 break-all text-slate-200">
                                {item.receipt || "—"}
                              </p>
                            </div>

                            <div>
                              <p className="text-slate-500">Reference</p>
                              <p className="mt-1 break-all text-slate-200">
                                {item.reference || "—"}
                              </p>
                            </div>

                            <div>
                              <p className="text-slate-500">Wallet balance after</p>
                              <p className="mt-1 text-slate-200">
                                {item.balance_after
                                  ? `KSh ${formatNumber(item.balance_after)}`
                                  : "—"}
                              </p>
                            </div>

                            <div>
                              <p className="text-slate-500">Credited to wallet</p>
                              <p className="mt-1 text-slate-200">
                                {item.credited === null ||
                                item.credited === undefined
                                  ? "—"
                                  : item.credited
                                    ? "Yes"
                                    : "No"}
                              </p>
                            </div>

                            <div>
                              <p className="text-slate-500">Checkout request ID</p>
                              <p className="mt-1 break-all text-slate-200">
                                {item.checkout_request_id || "—"}
                              </p>
                            </div>

                            <div>
                              <p className="text-slate-500">Conversation ID</p>
                              <p className="mt-1 break-all text-slate-200">
                                {item.conversation_id ||
                                  item.originator_conversation_id ||
                                  "—"}
                              </p>
                            </div>

                            <div>
                              <p className="text-slate-500">Provider result code</p>
                              <p className="mt-1 text-slate-200">
                                {item.result_code === null ||
                                item.result_code === undefined
                                  ? "—"
                                  : item.result_code}
                              </p>
                            </div>

                            <div className="sm:col-span-2 lg:col-span-3">
                              <p className="text-slate-500">Provider response</p>
                              <p className="mt-1 break-words text-slate-200">
                                {item.result_description || "—"}
                              </p>
                            </div>

                            <div>
                              <p className="text-slate-500">Last updated</p>
                              <p className="mt-1 text-slate-200">
                                {formatVipHistoryDate(item.updated)}
                              </p>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              <div className="mt-5 flex flex-col flex-wrap items-start justify-between gap-3 border-t border-white/[0.08] pt-4 sm:flex-row sm:items-center">
                <p className="text-xs text-slate-500">
                  Showing {transactionRecords.length} of{" "}
                  {formatNumber(transactionMeta.total)} records
                </p>

                <div className="flex items-center gap-2">
                  <Btn
                    small
                    onClick={() => fetchTransactions(transactionMeta.page - 1)}
                    disabled={
                      transactionLoading || transactionMeta.page <= 1
                    }
                  >
                    Previous
                  </Btn>

                  <span className="px-2 text-xs text-slate-400">
                    {transactionMeta.page} /{" "}
                    {Math.max(1, transactionMeta.total_pages)}
                  </span>

                  <Btn
                    small
                    onClick={() => fetchTransactions(transactionMeta.page + 1)}
                    disabled={
                      transactionLoading ||
                      transactionMeta.page >= transactionMeta.total_pages
                    }
                  >
                    Next
                  </Btn>
                </div>
              </div>
            </Card>
          </section>
        )}
      </main>

      {loading && (
        <LoadingOverlay
          text={
            loadingText ||
            "Working…"
          }
        />
      )}
    </div>
  );
}

function Card({
  title,
  subtitle,
  action,
  children,
}) {
  return (
    <section className="overflow-hidden rounded-3xl border border-white/[0.09] bg-gradient-to-br from-[#111b2d]/95 via-[#0d1626]/95 to-[#0a1220]/95 p-4 shadow-xl shadow-black/20 backdrop-blur-xl sm:p-5">
      <div className="mb-5 flex items-start justify-between gap-4 border-b border-white/[0.06] pb-4">
        <div className="min-w-0">
          <h2 className="text-base font-bold tracking-tight text-white sm:text-lg">
            {title}
          </h2>

          {subtitle && (
            <p className="mt-1 text-xs leading-relaxed text-slate-400">
              {subtitle}
            </p>
          )}
        </div>

        {action && (
          <div className="shrink-0">
            {action}
          </div>
        )}
      </div>

      {children}
    </section>
  );
}

function StatCard({
  label,
  value,
  detail,
  icon,
}) {
  const styles = {
    "Total VIPs": {
      accent: "border-indigo-400/25",
      icon: "bg-indigo-400/10 text-indigo-300",
      glow: "from-indigo-500/[0.12]",
    },
    "Pending VIPs": {
      accent: "border-amber-400/25",
      icon: "bg-amber-400/10 text-amber-300",
      glow: "from-amber-500/[0.12]",
    },
    "Subscription requests": {
      accent: "border-rose-400/25",
      icon: "bg-rose-400/10 text-rose-300",
      glow: "from-rose-500/[0.12]",
    },
    "Betting users": {
      accent: "border-cyan-400/25",
      icon: "bg-cyan-400/10 text-cyan-300",
      glow: "from-cyan-500/[0.12]",
    },
    "Bets today": {
      accent: "border-sky-400/25",
      icon: "bg-sky-400/10 text-sky-300",
      glow: "from-sky-500/[0.12]",
    },
    "High-stake bets today": {
      accent: "border-orange-400/25",
      icon: "bg-orange-400/10 text-orange-300",
      glow: "from-orange-500/[0.12]",
    },
    "High-stake amount today": {
      accent: "border-emerald-400/25",
      icon: "bg-emerald-400/10 text-emerald-300",
      glow: "from-emerald-500/[0.12]",
    },
    "Total bets overall": {
      accent: "border-violet-400/25",
      icon: "bg-violet-400/10 text-violet-300",
      glow: "from-violet-500/[0.12]",
    },
  };

  const style = styles[label] || {
    accent: "border-white/10",
    icon: "bg-indigo-400/10 text-indigo-300",
    glow: "from-indigo-500/[0.08]",
  };

  return (
    <div className={`group relative overflow-hidden rounded-2xl border ${style.accent} bg-gradient-to-br ${style.glow} via-[#111b2b]/95 to-[#0b1422] p-4 shadow-lg shadow-black/10 transition duration-200 hover:-translate-y-0.5 hover:border-white/20 hover:shadow-xl sm:p-5`}>
      <div className="pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full bg-white/[0.025] blur-2xl transition group-hover:bg-white/[0.05]" />

      <div className="relative flex items-start justify-between gap-3">
        <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-sm font-bold ${style.icon}`}>
          {icon}
        </span>

        <span className="max-w-[70%] break-words text-right text-xl font-extrabold leading-tight tracking-tight text-white sm:text-2xl">
          {formatNumber(value)}
        </span>
      </div>

      <div className="relative mt-5">
        <p className="text-sm font-bold text-slate-100">
          {label}
        </p>

        <p className="mt-1 text-xs leading-relaxed text-slate-400">
          {detail}
        </p>
      </div>

      <div className="absolute bottom-0 left-4 right-4 h-px bg-gradient-to-r from-transparent via-white/10 to-transparent" />
    </div>
  );
}

function SelectionPanel({
  title,
  count,
  onSelectAll,
  allSelected,
  children,
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-black/10">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-white">
            {title}
          </p>

          <p className="text-xs text-slate-500">
            {count} selected
          </p>
        </div>

        <button
          type="button"
          onClick={onSelectAll}
          className="text-xs font-semibold text-cyan-400 hover:text-cyan-300"
        >
          {allSelected
            ? "Clear all"
            : "Select all"}
        </button>
      </div>

      <div className="max-h-80 overflow-y-auto p-2">
        {children}
      </div>
    </div>
  );
}

function CheckRow({
  checked,
  onChange,
  title,
  subtitle,
  disabled = false,
  status,
}) {
  return (
    <label
      className={`flex items-center gap-3 rounded-xl border p-3 transition ${
        disabled
          ? "cursor-not-allowed border-transparent opacity-50"
          : checked
            ? "cursor-pointer border-cyan-400/30 bg-cyan-400/10"
            : "cursor-pointer border-transparent hover:bg-white/[0.05]"
      }`}
    >
      <span
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border text-xs font-black transition ${
          checked
            ? "border-cyan-400 bg-cyan-400 text-slate-950"
            : "border-slate-600 bg-slate-950 text-transparent"
        }`}
      >
        ✓
      </span>

      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) =>
          onChange(e.target.checked)
        }
        className="sr-only"
      />

      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-slate-200">
          {title}
        </span>

        <span className="block truncate text-xs text-slate-500">
          {subtitle}
        </span>
      </span>

      {status && (
        <span
          className={`shrink-0 text-right text-[11px] ${
            disabled ? "text-amber-400" : "text-slate-500"
          }`}
        >
          {status}
        </span>
      )}
    </label>
  );
}
function Input({
  type = "text",
  placeholder,
  value,
  onChange,
  autoComplete,
}) {
  return (
    <input
      type={type}
      placeholder={placeholder}
      value={value}
      autoComplete={autoComplete}
      onChange={(e) =>
        onChange(e.target.value)
      }
      className="w-full rounded-xl border border-white/10 bg-slate-950/80 px-3.5 py-2.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-500/10"
    />
  );
}

function Select({
  value,
  onChange,
  children,
}) {
  return (
    <select
      value={value}
      onChange={(e) =>
        onChange(e.target.value)
      }
      className="rounded-xl border border-white/10 bg-slate-950/80 px-3.5 py-2.5 text-sm text-slate-200 outline-none focus:border-indigo-400/60"
    >
      {children}
    </select>
  );
}

function Btn({
  children,
  success,
  danger,
  small,
  className = "",
  onClick,
  disabled,
  type = "button",
}) {
  const base =
    "inline-flex items-center justify-center rounded-xl font-semibold transition disabled:cursor-not-allowed disabled:opacity-50";

  const size = small
    ? "px-2.5 py-1.5 text-xs"
    : "px-4 py-2.5 text-sm";

  const color = success
    ? "bg-emerald-400 text-slate-950 hover:bg-emerald-300"
    : danger
      ? "bg-red-400 text-slate-950 hover:bg-red-300"
      : "bg-indigo-500 text-white hover:bg-indigo-400";

  return (
    <button
      type={type}
      onClick={onClick}
      className={`${base} ${size} ${color} ${className}`}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

function Banner({ msg }) {
  const styles = {
    error:
      "border-red-400/20 bg-red-400/10 text-red-200",

    success:
      "border-emerald-400/20 bg-emerald-400/10 text-emerald-200",

    info:
      "border-indigo-400/20 bg-indigo-400/10 text-indigo-200",
  };

  return (
    <div
      role="status"
      className={`rounded-2xl border px-4 py-3 text-sm ${
        styles[msg.type] ||
        styles.info
      }`}
    >
      {msg.text}
    </div>
  );
}

function Badge({ children }) {
  return (
    <span className="inline-flex rounded-lg border border-indigo-400/15 bg-indigo-400/10 px-2 py-1 text-xs font-semibold text-indigo-200">
      {children}
    </span>
  );
}

function StatusBadge({ active }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-semibold ${
        active
          ? "bg-emerald-400/10 text-emerald-300"
          : "bg-red-400/10 text-red-300"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          active
            ? "bg-emerald-400"
            : "bg-red-400"
        }`}
      />

      {active
        ? "Approved"
        : "Pending"}
    </span>
  );
}

function MiniMetric({
  label,
  value,
}) {
  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.025] p-3">
      <p className="text-xs text-slate-500">
        {label}
      </p>

      <p className="mt-1 text-xl font-bold text-white">
        {formatNumber(value)}
      </p>
    </div>
  );
}

function Empty({ text }) {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-slate-600">
      {text}
    </div>
  );
}

function LoadingOverlay({
  text,
}) {
  return (
    <div
      className="fixed inset-0 z-[100] grid place-items-center bg-slate-950/60 p-4 backdrop-blur-sm"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-slate-900 px-5 py-4 shadow-2xl">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-slate-700 border-t-cyan-400" />

        <span className="text-sm font-semibold text-slate-200">
          {text}
        </span>
      </div>
    </div>
  );
}

function formatNumber(
  value
) {
  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {
    return "0";
  }

  const n = Number(value);

  return Number.isFinite(n)
    ? n.toLocaleString()
    : String(value);
}

function formatDate(
  value,
  fallback = "—"
) {
  if (!value) return fallback;

  const date = new Date(value);

  return Number.isNaN(
    date.getTime()
  )
    ? String(value)
    : date.toLocaleDateString(
        undefined,
        {
          weekday: "short",
          month: "short",
          day: "numeric",
          year: "numeric",
        }
      );
}

function formatTime(value) {
  if (!value)
    return "Time unavailable";

  const date = new Date(value);

  return Number.isNaN(
    date.getTime()
  )
    ? String(value)
    : date.toLocaleTimeString(
        undefined,
        {
          hour: "2-digit",
          minute: "2-digit",
        }
      );
}
