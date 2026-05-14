// src/pages/VIPPortal.jsx
import React, { useState, useEffect, useMemo, useCallback } from "react";
import api from "../api/api";

const PLANS = [
  { name: "Daily", price: 99, display: "KES 99", quota: 3, days: 1, icon: "☀️" },
  { name: "Weekly", price: 399, display: "KES 399", quota: 5, days: 7, icon: "📅" },
  { name: "Monthly", price: 999, display: "KES 999", quota: 7, days: 30, icon: "🗓️" },
  { name: "Yearly", price: 4999, display: "KES 4,999", quota: 10, days: 365, icon: "💎" },
];

const PLAN_ORDER = ["Daily", "Weekly", "Monthly", "Yearly"];
const PHONE_RE = /^(07\d{8}|01\d{8}|2547\d{8})$/;

function normalizeToE164(input) {
  if (!input) return "";
  let s = input.replace(/\s|-/g, "");
  if (/^0\d{9}$/.test(s)) return "254" + s.slice(1);
  if (/^7\d{8}$/.test(s)) return "254" + s;
  if (/^254\d+$/.test(s)) return s;
  return s;
}

const formatExpiry = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
const getPlanInfo = (planName) =>
  PLANS.find((p) => p.name.toLowerCase() === (planName || "").toLowerCase());

function useToast() {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((msg, type = "info", ttl = 3500) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, type }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), ttl);
  }, []);
  return { toasts, push };
}

// ---------------- VIP Summary Card ----------------
function VipSummary({ me, onDeregister }) {
  if (!me) return null;
  const expired = !me.subscription_expiry || new Date(me.subscription_expiry) < new Date();
  return (
    <div className="p-4 rounded-2xl border bg-slate-800/60 text-white border-slate-700 space-y-2">
      <div className="flex justify-between items-center">
        <div className="font-semibold text-lg">{me.name}</div>
        <button
          onClick={onDeregister}
          className="text-red-400 bg-slate-800/50 hover:bg-red-600 hover:text-white p-1 rounded text-sm"
        >
          Deregister
        </button>
      </div>
      <div className="flex justify-between">
        <div>Plan:</div>
        <div>{me.subscription}</div>
      </div>
      <div className="flex justify-between">
        <div>Expiry:</div>
        <div>{formatExpiry(me.subscription_expiry)}</div>
      </div>
      <div className="flex justify-between items-center">
        <div>Status:</div>
        <div className={expired ? "text-red-400 font-semibold" : "text-green-400 font-semibold"}>
          {expired ? "Expired" : "Active"}
        </div>
      </div>
    </div>
  );
}

// ---------------- Quota Card ----------------
function VipQuotaCard({ me, quota, onUpgrade, upgradeLoading, upgradeOptions }) {
  if (!me || !quota) return null;

  const percent =
    quota.daily_quota > 0 ? Math.min(100, Math.round((quota.used_today / quota.daily_quota) * 100)) : 0;

  const planInfo = getPlanInfo(me.subscription);

  return (
    <div className="p-4 rounded-2xl border bg-slate-800/60 text-white border-slate-700 space-y-3">
      <div className="flex justify-between text-xs text-slate-300">
        <div>
          {quota.used_today}/{quota.daily_quota}
        </div>
        <div>
          {planInfo ? `${planInfo.quota} picks/day • ${planInfo.days} day(s)` : "Plan details on server"}
        </div>
      </div>

      <div className="w-full h-3 bg-slate-700 rounded-full overflow-hidden">
        <div
          className="h-3 rounded-full"
          style={{ width: `${percent}%`, background: "linear-gradient(90deg,#ffd166,#f97316)" }}
        />
      </div>

      {quota.resets_at && <div className="text-[11px] text-slate-400">Resets: {formatExpiry(quota.resets_at)}</div>}

      {upgradeOptions.length > 0 && (
        <div className="flex flex-col gap-2 mt-2">
          <div className="text-sm text-slate-300">Upgrade Plan:</div>
          {upgradeOptions.map((plan) => (
            <button
              key={plan.name}
              onClick={() => onUpgrade(plan.name)}
              disabled={!!upgradeLoading[plan.name]}
              className="bg-amber-500 hover:bg-amber-600 text-black font-semibold p-2 rounded-lg text-sm disabled:opacity-50"
            >
              {upgradeLoading[plan.name] ? "Upgrading..." : `${plan.name} — ${plan.display}`}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function LockedOverlay({ message = "VIP — login to view full picks" }) {
  return (
    <div className="absolute inset-0 rounded-2xl flex items-center justify-center pointer-events-none">
      <div className="absolute inset-0 rounded-2xl bg-black/25 backdrop-blur-sm" />
      <div className="relative z-10 text-white text-sm font-semibold">{message}</div>
    </div>
  );
}

// ---------------- Main VIP Portal ----------------
export default function VIPPortal() {
  const [theme, setTheme] = useState("dark");
  const [mode, setMode] = useState("login"); // "login" | "signup"
  const [logged, setLogged] = useState(!!localStorage.getItem("vip_token"));
  const [form, setForm] = useState({ name: "", number: "", subscription: "Daily" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [waitingApproval, setWaitingApproval] = useState(false);
  const [me, setMe] = useState(null);
  const [quota, setQuota] = useState(null);
  const [picks, setPicks] = useState([]);
  const [upgradeLoading, setUpgradeLoading] = useState({});
  const { toasts, push } = useToast();

  const currentPlanIndex = useMemo(() => {
    if (!me?.subscription) return -1;
    return PLAN_ORDER.findIndex((p) => p.toLowerCase() === me.subscription.toLowerCase());
  }, [me]);

  const upgradeOptions = useMemo(() => {
    if (currentPlanIndex === -1) return PLANS;
    return PLANS.filter((p, i) => i > currentPlanIndex);
  }, [currentPlanIndex]);

  // Stable helper to fetch VIP data once (safe to call from other handlers)
  const fetchVipDataOnce = useCallback(
    async (token) => {
      if (!token) return null;
      setLoading(true);
      try {
        const [meData, quotaData, picksData] = await Promise.all([
          api.vipMe(token),
          api.vipQuota(token),
          api.vipPicks(token),
        ]);
        if (meData && meData.success) setMe(meData.data);
        if (quotaData && quotaData.success) setQuota(quotaData.data);
        if (picksData && picksData.success) setPicks(Array.isArray(picksData.data) ? picksData.data : []);
        return { meData, quotaData, picksData };
      } catch (err) {
        console.error("fetchVipDataOnce error:", err);
        setError(typeof err?.error === "string" ? err.error : err?.message || "Failed to fetch VIP data");
        return null;
      } finally {
        setLoading(false);
      }
    },
    [] // stable (setState functions are stable)
  );

  // Polling effect: only runs when logged AND token exists
  useEffect(() => {
    const token = localStorage.getItem("vip_token");
    if (!logged || !token) {
      // ensure we don't leave stale data when not logged
      setMe(null);
      setQuota(null);
      setPicks([]);
      return;
    }

    // initial fetch + polling
    fetchVipDataOnce(token);
    const interval = setInterval(() => fetchVipDataOnce(token), 120000);
    return () => clearInterval(interval);
  }, [logged, fetchVipDataOnce]);

  // ---------------- Helpers ----------------
  const clientValidateNumber = (n) => {
    if (!n) return false;
    const normalized = normalizeToE164(n);
    return PHONE_RE.test(n) || PHONE_RE.test(normalized);
  };

  // Login: set logged only on successful login
  const login = async (e) => {
    e?.preventDefault();
    setError("");
    if (!form.number) return setError("Phone number required");

    setLoading(true);
    try {
      const normalized = normalizeToE164(form.number);
      const res = await api.vipLogin({ number: normalized });

      if (res && res.success && res.data?.token) {
        localStorage.setItem("vip_token", res.data.token);
        setLogged(true);
        setMode("login");
        push("Login successful", "success");

        // fetch profile right away (optional — effect will also fetch)
        await fetchVipDataOnce(res.data.token);

        if (res.data.expired) {
          push("⚠️ Your subscription has expired. Consider renewing.", "error", 5000);
        }
      } else {
        // ensure we don't accidentally mark user logged
        localStorage.removeItem("vip_token");
        setLogged(false);
        setMe(null);
        setQuota(null);
        setPicks([]);
        setError(typeof res?.error === "string" ? res.error : "Login failed or account not registered");
      }
    } catch (err) {
      console.error("login error:", err);
      localStorage.removeItem("vip_token");
      setLogged(false);
      setMe(null);
      setQuota(null);
      setPicks([]);
      setError(typeof err?.error === "string" ? err.error : err?.message || "Network error");
    } finally {
      setLoading(false);
    }
  };

  // Signup: create account, wait for admin approval
  const signup = async (e) => {
    e?.preventDefault();
    setError("");
    if (!form.name || !form.number) return setError("Name and phone number required");
    if (!clientValidateNumber(form.number)) return setError("Invalid phone number");

    setLoading(true);
    try {
      const normalized = normalizeToE164(form.number);
      const res = await api.vipRegister({ ...form, number: normalized });
      if (res && res.success) {
        push("Account created — awaiting admin approval", "success");
        setWaitingApproval(true);
        // keep user logged = false until admin approves
        setLogged(false);
      } else {
        setError(typeof res?.error === "string" ? res.error : "Signup failed");
      }
    } catch (err) {
      console.error("signup error:", err);
      setError(typeof err?.error === "string" ? err.error : err?.message || "Network error");
    } finally {
      setLoading(false);
    }
  };

  const logout = () => {
    try {
      api.vipLogout && api.vipLogout();
    } catch (err) {
      /* ignore */
    }
    localStorage.removeItem("vip_token");
    setLogged(false);
    setMe(null);
    setQuota(null);
    setPicks([]);
    push("Logged out", "info");
  };

  // upgrade uses token in header (api.vipUpgrade must accept planName, token)
  const handleUpgrade = async (planName) => {
    setUpgradeLoading((l) => ({ ...l, [planName]: true }));

    try {
      const token = localStorage.getItem("vip_token");
      if (!token) throw new Error("VIP token missing");

      const res = await api.vipUpgrade(planName, token);
      if (res && res.success) {
        push(`Upgraded to ${planName}`, "success");
        // refresh data
        await fetchVipDataOnce(token);
      } else {
        push(typeof res?.error === "string" ? res.error : "Upgrade failed", "error");
      }
    } catch (err) {
      console.error("handleUpgrade error:", err);
      push(typeof err?.message === "string" ? err.message : "Upgrade failed", "error");
    } finally {
      setUpgradeLoading((l) => ({ ...l, [planName]: false }));
    }
  };

  const deregister = async () => {
    if (!me?.number) return push("No registered number", "error");
    if (!window.confirm("Are you sure you want to deregister your VIP account?")) return;

    setLoading(true);
    try {
      const token = localStorage.getItem("vip_token");
      // assume api.vipDeregister accepts (token) or ({ number }, token) — adapt as needed
      const res = await (api.vipDeregister ? api.vipDeregister(token) : api.post("/vip/deregister", { number: me.number, token }));
      if (res && res.success) {
        push("Account deregistered successfully", "success");
        logout();
      } else {
        push(typeof res?.error === "string" ? res.error : "Failed to deregister", "error");
      }
    } catch (err) {
      console.error("deregister error:", err);
      push(typeof err?.message === "string" ? err.message : "Failed to deregister", "error");
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    "w-full rounded-lg p-2 border bg-slate-700 text-white border-slate-600 focus:outline-none focus:ring-2 focus:ring-amber-300";
  const visiblePicks = logged ? picks : picks.slice(0, 2);

  return (
    <div className={`min-h-screen p-6 ${theme === "dark" ? "bg-slate-900 text-white" : "bg-white text-black"}`}>
      <div className="flex justify-end gap-3 mb-4">
        <button
          onClick={() => {
            setTheme((t) => (t === "dark" ? "light" : "dark"));
          }}
        >
          {theme === "dark" ? "☀️" : "🌙"}
        </button>
        {logged && (
          <button
            onClick={logout}
            className="text-red-400"
          >
            Logout
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="space-y-4">
          {!logged && !waitingApproval && (
            <div className="p-4 rounded-2xl border border-slate-700">
              <div className="flex gap-2 mb-4">
                <button
                  className={mode === "login" ? "bg-amber-500 px-3 py-1 rounded" : ""}
                  onClick={() => {
                    setMode("login");
                    setError("");
                  }}
                >
                  Login
                </button>
                <button
                  className={mode === "signup" ? "bg-amber-500 px-3 py-1 rounded" : ""}
                  onClick={() => {
                    setMode("signup");
                    setError("");
                  }}
                >
                  Sign Up
                </button>
              </div>

              {mode === "login" && (
                <form onSubmit={login} className="space-y-3">
                  <input
                    className={inputClass}
                    placeholder="Phone number"
                    value={form.number}
                    onChange={(e) => setForm({ ...form, number: e.target.value })}
                  />
                  <button type="submit" className="w-full bg-amber-500 hover:bg-amber-600 text-black font-semibold p-2 rounded-lg">
                    {loading ? "Please wait..." : "Login"}
                  </button>
                  {error && <div className="text-rose-400">{error}</div>}
                </form>
              )}

              {mode === "signup" && (
                <form onSubmit={signup} className="space-y-3">
                  <input
                    className={inputClass}
                    placeholder="Full name"
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                  />
                  <input
                    className={inputClass}
                    placeholder="Phone number"
                    value={form.number}
                    onChange={(e) => setForm({ ...form, number: e.target.value })}
                  />
                  <select
                    className={inputClass}
                    value={form.subscription}
                    onChange={(e) => setForm({ ...form, subscription: e.target.value })}
                  >
                    {PLANS.map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.name} — {p.display}
                      </option>
                    ))}
                  </select>
                  <button type="submit" className="w-full bg-amber-500 hover:bg-amber-600 text-black font-semibold p-2 rounded-lg">
                    {loading ? "Creating..." : "Create account"}
                  </button>
                  {error && <div className="text-rose-400">{error}</div>}
                </form>
              )}
            </div>
          )}

          {!logged && (
            <div className="p-4 border border-slate-700 rounded-2xl">
              <h4 className="mb-2 font-semibold">Available VIP Plans</h4>
              {PLANS.map((p) => (
                <div key={p.name} className="flex items-center gap-3 p-3 border border-slate-700 rounded-xl mb-2">
                  <div className="text-2xl">{p.icon}</div>
                  <div>
                    {p.name} — {p.display} • {p.quota} picks/day • {p.days} day(s)
                  </div>
                </div>
              ))}
            </div>
          )}

          {logged && me && (
            <>
              <VipSummary me={me} onDeregister={deregister} />
              <VipQuotaCard
                me={me}
                quota={quota}
                onUpgrade={handleUpgrade}
                upgradeLoading={upgradeLoading}
                upgradeOptions={upgradeOptions}
              />
            </>
          )}
        </div>

        <div className="lg:col-span-2 space-y-4">
          <h2 className="text-xl font-bold">🔥 Today's VIP Picks</h2>
          {loading && <div>Loading picks…</div>}
          {!loading && picks.length === 0 && <div>No picks available</div>}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {visiblePicks.map((pick, i) => (
              <div key={pick?._id || pick?.id || i} className="p-4 rounded-2xl border border-slate-700 relative">
                <div className="font-semibold">{pick?.match || `${pick?.home_team} vs ${pick?.away_team}`}</div>
                <div className="text-sm text-slate-400">{new Date(pick?.match_time || Date.now()).toLocaleString()}</div>
                <div className="mt-2 text-amber-400 font-semibold">
                  {logged ? pick?.tip || pick?.pick : pick?.preview_tip || "VIP ONLY"}
                </div>
                {!logged && <LockedOverlay />}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="fixed bottom-4 right-4 space-y-2 z-50">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`px-4 py-2 rounded-md text-white ${t.type === "success" ? "bg-green-500" : t.type === "error" ? "bg-red-500" : "bg-slate-700"}`}
          >
            {t.msg}
          </div>
        ))}
      </div>
    </div>
  );
}
