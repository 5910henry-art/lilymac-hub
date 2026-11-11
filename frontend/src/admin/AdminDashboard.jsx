// src/admin/AdminDashboard.jsx

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";

import {
  gradeMatch,
} from "../api/betsWallet";

import {
  adminListVips,
  adminListPendingVips,
  adminListUpgradeRequests,
  adminApproveVip,
  adminDeclineVip,
  adminDeleteVip,
  adminSetVipPassword,
  adminApproveUpgrade,
  adminDeclineUpgrade,
  adminPreviewVipPicks,
  adminDistributeVipPicks,
} from "../api/authVipAdmin";

const REFRESH_MS = 30_000;

export default function AdminDashboard() {
  const [token, setToken] = useState(() => localStorage.getItem("admin_token"));
  const [admin, setAdmin] = useState(() =>
    JSON.parse(localStorage.getItem("admin_user") || "null")
  );


  const [vips, setVips] = useState([]);
  const [pendingVips, setPendingVips] = useState([]);
  const [upgradeRequests, setUpgradeRequests] = useState([]);

  const pendingUpgradeRequests = upgradeRequests.filter(
    (req) => String(req.status || "").toLowerCase() === "pending"
  );
  const [allMatches, setAllMatches] = useState([]);
const [selectedVIPs, setSelectedVIPs] = useState([]);
  const [selectedMatches, setSelectedMatches] = useState([]);
  const [pick, setPick] = useState("1X2");
  const [odds, setOdds] = useState(1.5);
  const [distributionSummary, setDistributionSummary] = useState([]);

  const [loading, setLoading] = useState(false);
  const [loadingText, setLoadingText] = useState("");
  const [msg, setMsg] = useState(null);

  const [search, setSearch] = useState("");
  const [filterApproved, setFilterApproved] = useState("all");
  const [filterPlan, setFilterPlan] = useState("all");
  const [activeSection, setActiveSection] = useState("overview");

  const [gradeMatchId, setGradeMatchId] = useState("");
  const [gradeResult, setGradeResult] = useState("");

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
    if (Array.isArray(payload?.users)) return payload.users;
    if (Array.isArray(payload?.tickets)) return payload.tickets;
    if (Array.isArray(payload?.summary)) return payload.summary;

    return [];
  }, []);

  const safeObj = useCallback((res) => res?.data ?? res ?? null, []);

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

      setVips(safeArray(vipList));
      setPendingVips(safeArray(pendingList));
      setUpgradeRequests(safeArray(upgrades));
      setAllMatches(safeArray(matches));
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
  }, [token, safeArray, showError]);

  useEffect(() => {
    if (!token) return;

    fetchAll();

    const interval = setInterval(
      () => fetchAll(true),
      REFRESH_MS
    );

    return () => clearInterval(interval);
  }, [token, fetchAll]);

  const vipAction = async (id, action) => {
    const verb =
      action === "approve"
        ? "approve"
        : action === "delete"
          ? "delete"
          : "decline";

    const confirmMessage =
      action === "delete"
        ? "Are you sure you want to permanently DELETE this VIP?\\n\\nThis will remove the VIP account, all VIP picks, and upgrade requests. This cannot be undone."
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
    action
  ) => {
    const verb =
      action === "approve"
        ? "approve"
        : "decline";

    if (
      !window.confirm(
        `Are you sure you want to ${verb} this upgrade request?`
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
            `Failed to ${action} upgrade`
        );
      }

      setMsg({
        type: "success",
        text: `Upgrade ${action}d successfully.`,
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
    if (
      !gradeMatchId ||
      !gradeResult
    ) {
      setMsg({
        type: "error",
        text: "Provide a match ID and result.",
      });

      return;
    }

    if (
      !window.confirm(
        `Grade match ${gradeMatchId} as "${gradeResult}"?`
      )
    ) {
      return;
    }

    setLoading(true);
    setLoadingText("Grading match…");
    setMsg(null);

    try {
      await gradeMatch(
        gradeMatchId,
        gradeResult
      );

      setMsg({
        type: "success",
        text: "Match graded successfully.",
      });

      setGradeMatchId("");
      setGradeResult("");

      await fetchAll();
    } catch (e) {
      console.error(
        "[ADMIN] Grade match failed:",
        e
      );

      showError(e);
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

  const stats = useMemo(
    () => [
      {
        label: "Total VIPs",
        value: vips.length,
        detail: `${
          vips.filter(
            (v) => v.approved
          ).length
        } approved`,
        icon: "◆",
      },
      {
        label: "Pending VIPs",
        value:
          pendingVips.length,
        detail:
          "Awaiting approval",
        icon: "◷",
      },
      {
        label:
          "Upgrade requests",
        value:
          upgradeRequests.filter(
            (req) => req.status === "pending"
          ).length,
        detail:
          "Need review",
        icon: "↗",
      },
      {
        label: "Users",
        detail:
          "Registered users",
        icon: "●",
      },
      {
        label: "Tickets",
        detail:
          "Recent betting tickets",
        icon: "▣",
      },
      {
        label: "Matches",
        value:
          allMatches.length,
        detail:
          "Available for picks",
        icon: "⚽",
      },
    ],
    [
      vips,
      pendingVips,
      upgradeRequests,
      allMatches,
    ]
  );

  const toggleVIP = (
    number,
    checked
  ) => {
    setSelectedVIPs((prev) =>
      checked
        ? prev.includes(number)
          ? prev
          : [...prev, number]
        : prev.filter(
            (n) => n !== number
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
      setSelectedVIPs(
        selectedVIPs.length ===
          approvedVips.length
          ? []
          : approvedVips.map(
              (v) => v.number
            )
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

      <header className="sticky top-0 z-40 border-b border-white/10 bg-[#070b14]/85 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-cyan-400 text-lg font-black text-white shadow-lg shadow-indigo-500/20">
              L
            </div>

            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-white">
                LilyMac Admin
              </p>

              <p className="truncate text-xs text-slate-500">
                Operations control center
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={fetchAll}
              disabled={loading}
              className="hidden rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-medium text-slate-300 transition hover:bg-white/[0.08] disabled:opacity-50 sm:inline-flex"
            >
              ↻ Refresh
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
              onClick={logout}
              className="rounded-xl border border-red-400/20 bg-red-400/10 px-3 py-2 text-sm font-semibold text-red-300 transition hover:bg-red-400/20"
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      <main className="relative mx-auto max-w-[1600px] px-4 py-5 sm:px-6 lg:py-7">
        <div className="mb-6">
          <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-400">
                Command center
              </p>

              <h1 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">
                Admin Dashboard
              </h1>

              <p className="mt-1 max-w-2xl text-sm text-slate-400">
                Manage VIPs, picks,
                the available data and
                match settlement from
                one place.
              </p>
            </div>

            <div className="rounded-2xl border border-white/10 bg-white/[0.035] px-4 py-3 text-xs text-slate-400">
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

        <nav className="mb-6 flex gap-1 overflow-x-auto rounded-2xl border border-white/10 bg-white/[0.025] p-1">
          {[
            ["overview", "Overview"],
            ["vip", "VIP Management"],
            [
              "distribution",
              "Pick Distribution",
            ],
            [
              "settlement",
              "Settlement",
            ],
          ].map(
            ([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() =>
                  setActiveSection(id)
                }
                className={`whitespace-nowrap rounded-xl px-4 py-2.5 text-sm font-semibold transition ${
                  activeSection === id
                    ? "bg-white text-slate-950 shadow"
                    : "text-slate-400 hover:bg-white/[0.06] hover:text-white"
                }`}
              >
                {label}
              </button>
            )
          )}
        </nav>

        {activeSection ===
          "overview" && (
          <>
            <section className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              {stats.map((stat) => (
                <StatCard
                  key={stat.label}
                  {...stat}
                />
              ))}
            </section>

            {pendingVips.length > 0 || pendingUpgradeRequests.length > 0 ? (
              <section className="mt-6 grid gap-5 xl:grid-cols-2">
                {pendingVips.length > 0 && (
              <Card
                title="Pending VIP approvals"
                subtitle="Quick review queue"
                action={
                  <button
                    type="button"
                    onClick={() =>
                      setActiveSection(
                        "vip"
                      )
                    }
                    className="text-xs font-semibold text-cyan-400 hover:text-cyan-300"
                  >
                    View all →
                  </button>
                }
              >
                <div className="space-y-2">
                  {pendingVips
                    .slice(0, 5)
                    .map((v) => (
                      <div
                        key={v.id}
                        className="flex items-center justify-between gap-3 rounded-xl border border-white/5 bg-white/[0.025] p-3"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-white">
                            {v.name ||
                              "Unnamed VIP"}
                          </p>

                          <p className="text-xs text-slate-500">
                            {v.number ||
                              "No number"}
                          </p>
                        </div>

                        <div className="flex shrink-0 gap-2">
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
                    ))}

                </div>
              </Card>

              )}
                {pendingUpgradeRequests.length > 0 && (
              <Card
                title="Upgrade requests"
                subtitle="Latest requests requiring attention"
                action={
                  <button
                    type="button"
                    onClick={() =>
                      setActiveSection(
                        "vip"
                      )
                    }
                    className="text-xs font-semibold text-cyan-400 hover:text-cyan-300"
                  >
                    Manage →
                  </button>
                }
              >
                <div className="space-y-2">
                  {pendingUpgradeRequests
                    .slice(0, 5)
                    .map((req) => (
                      <div
                        key={req.id}
                        className="flex items-center justify-between gap-3 rounded-xl border border-white/5 bg-white/[0.025] p-3"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-white">
                            {req.vip_name ||
                              req.name ||
                              req.number ||
                              "VIP"}
                          </p>

                          <p className="text-xs text-slate-500">
                            {req.number ||
                              "No number"}{" "}
                            →{" "}
                            {req.to_plan ||
                              req.plan ||
                              req.toPlan ||
                              "—"}
                          </p>
                        </div>

                        <div className="flex shrink-0 items-center gap-2">
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
                    ))}

                  {!pendingUpgradeRequests.length && (
                    <Empty text="No upgrade requests." />
                  )}
                </div>
              </Card>
                )}
                )}
              </section>
            ) : null}
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
                    <thead className="bg-white/[0.035] text-xs uppercase tracking-wider text-slate-500">
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
                            className="transition hover:bg-white/[0.025]"
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
                              <Badge>
                                {v.subscription ||
                                  "—"}
                              </Badge>
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
                        className="flex items-center justify-between gap-3 rounded-xl border border-white/5 bg-white/[0.025] p-3"
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

                        <div className="flex gap-2">
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
                title="Upgrade requests"
                subtitle="Approve or decline plan changes"
              >
                <div className="space-y-2">
                  {pendingUpgradeRequests.map(
                    (req) => (
                      <div
                        key={req.id}
                        className="flex items-center justify-between gap-3 rounded-xl border border-white/5 bg-white/[0.025] p-3"
                      >
                        <div>
                          <p className="text-sm font-semibold text-white">
                            {req.vip_name ||
                              req.name ||
                              req.number ||
                              "VIP"}
                          </p>

                          <p className="text-xs text-slate-500">
                            {req.number ||
                              "—"}{" "}
                            →{" "}
                            {req.to_plan ||
                              req.plan ||
                              req.toPlan ||
                              "—"}
                          </p>
                        </div>

                        <div className="flex items-center gap-2">
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
                    <Empty text="No upgrade requests." />
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
                    approvedVips.length >
                      0 &&
                    selectedVIPs.length ===
                      approvedVips.length
                  }
                >
                  {approvedVips.map(
                    (v) => (
                      <CheckRow
                        key={v.number}
                        checked={selectedVIPs.includes(
                          v.number
                        )}
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
                      <pre
                        key={index}
                        className="overflow-x-auto rounded-xl border border-white/5 bg-black/20 p-3 text-xs text-slate-300"
                      >
                        {JSON.stringify(
                          item,
                          null,
                          2
                        )}
                      </pre>
                    )
                  )}
                </div>
              )}
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
              <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
                <Input
                  placeholder="Match ID"
                  value={gradeMatchId}
                  onChange={
                    setGradeMatchId
                  }
                />

                <Input
                  placeholder="Result"
                  value={gradeResult}
                  onChange={
                    setGradeResult
                  }
                />

                <Btn
                  success
                  onClick={
                    gradeMatchResult
                  }
                  disabled={
                    loading ||
                    !gradeMatchId ||
                    !gradeResult
                  }
                >
                  Grade match
                </Btn>
              </div>

              <p className="mt-3 text-xs text-slate-500">
                Confirm the result carefully
                before grading because
                settlement may affect user
                balances.
              </p>
            </Card>

            <Card
              title="System status"
              subtitle="Current dashboard data"
            >
              <div className="grid grid-cols-2 gap-3">
                <MiniMetric
                  label="VIPs"
                  value={vips.length}
                />

                <MiniMetric
                  label="Matches"
                  value={allMatches.length}
                />
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
    <section className="rounded-3xl border border-white/10 bg-white/[0.035] p-4 shadow-xl shadow-black/5 backdrop-blur-sm sm:p-5">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-white">
            {title}
          </h2>

          {subtitle && (
            <p className="mt-0.5 text-xs text-slate-500">
              {subtitle}
            </p>
          )}
        </div>

        {action}
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
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.035] p-4">
      <div className="flex items-center justify-between">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-indigo-500/10 text-xs font-bold text-indigo-300">
          {icon}
        </span>

        <span className="text-2xl font-bold tracking-tight text-white">
          {formatNumber(value)}
        </span>
      </div>

      <p className="mt-4 text-sm font-semibold text-slate-200">
        {label}
      </p>

      <p className="mt-0.5 text-xs text-slate-500">
        {detail}
      </p>
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
}) {
  return (
    <label
      className={`flex cursor-pointer items-center gap-3 rounded-xl border p-3 transition ${
        checked
          ? "border-cyan-400/30 bg-cyan-400/10"
          : "border-transparent hover:bg-white/[0.05]"
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
        onChange={(e) =>
          onChange(e.target.checked)
        }
        className="sr-only"
      />

      <span className="min-w-0">
        <span className="block truncate text-sm font-medium text-slate-200">
          {title}
        </span>

        <span className="block truncate text-xs text-slate-500">
          {subtitle}
        </span>
      </span>
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
