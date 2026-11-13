// src/user/VIPPortal.jsx
import React, {
  useState,
  useEffect,
  useMemo,
  useCallback,
} from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/api";

/* ============================================================
   VIP PLANS
============================================================ */

const PLANS = [
  {
    name: "Daily",
    key: "daily",
    price: 99,
    display: "KES 99",
    quota: 3,
    days: 1,
    icon: "☀️",
    description: "Perfect for trying VIP picks",
  },
  {
    name: "Weekly",
    key: "weekly",
    price: 399,
    display: "KES 399",
    quota: 5,
    days: 7,
    icon: "📅",
    description: "A full week of premium picks",
  },
  {
    name: "Monthly",
    key: "monthly",
    price: 999,
    display: "KES 999",
    quota: 7,
    days: 30,
    icon: "🗓️",
    description: "More picks throughout the month",
  },
  {
    name: "Yearly",
    key: "yearly",
    price: 4999,
    display: "KES 4,999",
    quota: 10,
    days: 365,
    icon: "💎",
    description: "Maximum value for serious VIP members",
  },
];

const PLAN_ORDER = [
  "daily",
  "weekly",
  "monthly",
  "yearly",
];

const PHONE_RE =
  /^(07\d{8}|01\d{8}|2547\d{8}|2541\d{8})$/;

/* ============================================================
   HELPERS
============================================================ */

function normalizeToE164(input) {
  if (!input) return "";

  const s = String(input).replace(/\s|-/g, "");

  if (/^0\d{9}$/.test(s)) {
    return "254" + s.slice(1);
  }

  if (/^[71]\d{8}$/.test(s)) {
    return "254" + s;
  }

  if (/^254\d+$/.test(s)) {
    return s;
  }

  return s;
}

function clientValidateNumber(number) {
  if (!number) return false;

  const cleaned = String(number)
    .replace(/\s|-/g, "");

  return PHONE_RE.test(cleaned);
}

function normalizePlan(plan) {
  return String(plan || "")
    .trim()
    .toLowerCase();
}

function getPlanInfo(planName) {
  const key = normalizePlan(planName);

  return PLANS.find(
    (plan) => plan.key === key
  );
}

function formatExpiry(value) {
  if (!value) return "—";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  return date.toLocaleString();
}

function getDeliveryDateKey(value) {
  if (!value) return "undated";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "undated";

  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Africa/Nairobi",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);

  const values = Object.fromEntries(
    parts.map((part) => [part.type, part.value])
  );

  return `${values.year}-${values.month}-${values.day}`;
}

function formatDeliveryDateLabel(key) {
  if (key === "undated") {
    return "Delivery date not recorded";
  }

  return new Intl.DateTimeFormat("en-KE", {
    timeZone: "Africa/Nairobi",
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(`${key}T12:00:00Z`));
}

function isSubscriptionExpired(expiry) {
  if (!expiry) return true;

  const date = new Date(expiry);

  if (Number.isNaN(date.getTime())) {
    return true;
  }

  return date.getTime() <= Date.now();
}

function getDaysRemaining(expiry) {
  if (!expiry) return 0;

  const date = new Date(expiry);

  if (Number.isNaN(date.getTime())) {
    return 0;
  }

  const diff =
    date.getTime() - Date.now();

  return Math.max(
    0,
    Math.ceil(
      diff / (1000 * 60 * 60 * 24)
    )
  );
}

/*
 * Supports both:
 *
 * {
 *   success: true,
 *   data: {...}
 * }
 *
 * and the raw backend shape:
 *
 * {
 *   token: "...",
 *   user: {...}
 * }
 */
function getResponseToken(res) {
  return (
    res?.data?.token ||
    res?.token ||
    res?.data?.data?.token ||
    null
  );
}

function getResponseUser(res) {
  return (
    res?.data?.user ||
    res?.user ||
    res?.data?.data?.user ||
    null
  );
}

function getResponseData(res) {
  return (
    res?.data?.data ||
    res?.data ||
    null
  );
}

/* ============================================================
   TOASTS
============================================================ */

function useToast() {
  const [toasts, setToasts] = useState([]);

  const push = useCallback(
    (msg, type = "info", ttl = 3500) => {
      const id =
        Date.now() + Math.random();

      setToasts((current) => [
        ...current,
        {
          id,
          msg,
          type,
        },
      ]);

      setTimeout(() => {
        setToasts((current) =>
          current.filter(
            (toast) =>
              toast.id !== id
          )
        );
      }, ttl);
    },
    []
  );

  const dismiss = useCallback((id) => {
    setToasts((current) =>
      current.filter((toast) => toast.id !== id)
    );
  }, []);

  return {
    toasts,
    push,
    dismiss,
  };
}

/* ============================================================
   GLASS CARD
============================================================ */

function GlassCard({
  children,
  className = "",
}) {
  return (
    <div
      className={`
        rounded-3xl
        border border-slate-200
        bg-white
        shadow-2xl shadow-black/20
        backdrop-blur-xl
        ${className}
      `}
    >
      {children}
    </div>
  );
}

/* ============================================================
   SECTION TITLE
============================================================ */

function SectionTitle({
  icon,
  title,
  subtitle,
}) {
  return (
    <div className="mb-4">
      <div className="flex items-center gap-2">
        {icon && (
          <span className="text-xl">
            {icon}
          </span>
        )}

        <h2 className="text-lg font-bold text-slate-900">
          {title}
        </h2>
      </div>

      {subtitle && (
        <p className="mt-1 text-sm text-slate-600">
          {subtitle}
        </p>
      )}
    </div>
  );
}

/* ============================================================
   VIP SUMMARY
============================================================ */

function VipSummary({
  me,
  quota,
  onDeregister,
}) {
  if (!me) return null;

  const quotaSource =
    quota?.data?.data ||
    quota?.data ||
    quota;

  const expiryValue =
    quotaSource?.entitlement_expires_at ||
    me.subscription_expiry;

  const expired =
    typeof quotaSource?.expired === "boolean"
      ? quotaSource.expired
      : isSubscriptionExpired(expiryValue);

  const plan =
    getPlanInfo(me.subscription);

  const daysRemaining =
    getDaysRemaining(expiryValue);

  return (
    <GlassCard className="overflow-hidden">
      <div className="bg-gradient-to-r from-blue-600/15 via-red-600/10 to-transparent p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="mb-1 flex items-center gap-2">
              <span className="text-2xl">
                👑
              </span>

              <span className="text-xs font-bold uppercase tracking-widest text-blue-600">
                VIP Member
              </span>
            </div>

            <h2 className="text-xl font-bold text-slate-900">
              {me.name || "VIP Member"}
            </h2>

            <p className="mt-1 text-sm text-slate-600">
              {me.number ||
                "Phone unavailable"}
            </p>
          </div>

          <button
            type="button"
            onClick={onDeregister}
            className="
              rounded-xl
              border border-red-500/20
              bg-red-500/10
              px-3 py-2
              text-xs font-semibold
              text-red-400
              transition
              hover:bg-red-500
              hover:text-white
            "
          >
            Deregister
          </button>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-[11px] uppercase tracking-wider text-slate-500">
              Current plan
            </p>

            <p className="mt-1 flex items-center gap-2 font-bold capitalize text-slate-900">
              <span>
                {plan?.icon || "⭐"}
              </span>

              {me.subscription ||
                "—"}
            </p>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-[11px] uppercase tracking-wider text-slate-500">
              Remaining
            </p>

            <p
              className={`mt-1 font-bold ${
                expired
                  ? "text-red-400"
                  : "text-emerald-400"
              }`}
            >
              {expired
                ? "Expired"
                : `${daysRemaining} day${
                    daysRemaining ===
                    1
                      ? ""
                      : "s"
                  }`}
            </p>
          </div>
        </div>

        <div className="mt-4">
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-blue-600">
            Paid picks overview
          </p>

          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <p className="text-[10px] uppercase tracking-wide text-slate-500">
                Purchased
              </p>
              <p className="mt-1 text-xl font-bold text-slate-900">
                {Number(quotaSource?.total_picks || 0).toLocaleString()}
              </p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <p className="text-[10px] uppercase tracking-wide text-slate-500">
                Delivered
              </p>
              <p className="mt-1 text-xl font-bold text-emerald-600">
                {Number(quotaSource?.delivered_picks || 0).toLocaleString()}
              </p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <p className="text-[10px] uppercase tracking-wide text-slate-500">
                Outstanding
              </p>
              <p className="mt-1 text-xl font-bold text-blue-600">
                {Number(quotaSource?.outstanding_picks || 0).toLocaleString()}
              </p>
            </div>
          </div>
        </div>

        {quotaSource?.extension_active === true && (
          <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-3">
            <p className="text-sm font-semibold text-emerald-800">
              Paid-picks extension active
            </p>
            <p className="mt-1 text-xs text-emerald-700">
              Your subscription period has ended, but you still have
              paid picks outstanding. We will continue delivering
              those picks without requiring another payment.
            </p>
          </div>
        )}

        {Number(quotaSource?.queued_entitlements || 0) > 0 && (
          <div className="mt-3 rounded-xl border border-blue-200 bg-blue-50 px-3 py-3">
            <p className="text-sm font-semibold text-blue-800">
              Future subscription queued
            </p>
            <p className="mt-1 text-xs text-blue-700">
              {Number(quotaSource.queued_entitlements)} paid
              entitlement{Number(quotaSource.queued_entitlements) === 1 ? "" : "s"}
              {" "}waiting to activate after your current entitlement is completed.
            </p>
          </div>
        )}

        <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 p-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-slate-500">
              Subscription expiry
            </span>

            <span
              className={`text-right text-xs font-semibold ${
                expired
                  ? "text-red-400"
                  : "text-slate-200"
              }`}
            >
              {formatExpiry(expiryValue)}
            </span>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              expired
                ? "bg-red-400"
                : "bg-emerald-400"
            }`}
          />

          <span
            className={`text-sm font-semibold ${
              expired
                ? "text-red-400"
                : "text-emerald-400"
            }`}
          >
            {expired
              ? "Subscription expired"
              : "Subscription active"}
          </span>
        </div>
      </div>
    </GlassCard>
  );
}

/* ============================================================
   QUOTA CARD
============================================================ */

function VipQuotaCard({
  me,
  quota,
  onUpgrade,
  upgradeLoading,
  upgradeOptions,
  onDowngrade,
  downgradeLoading,
  downgradeOptions,
}) {
  if (!me || !quota) {
    return null;
  }

  const quotaSource =
    quota?.data?.data ||
    quota?.data ||
    quota;

  const dailyQuota =
    Number(
      quotaSource?.daily_quota ??
      quotaSource?.quota ??
      quotaSource?.dailyQuota
    ) || 0;

  const usedToday =
    Number(
      quotaSource?.used_today ??
      quotaSource?.used ??
      quotaSource?.usedToday
    ) || 0;

  const expired =
    quotaSource?.expired === true;

  const remainingToday = expired
    ? 0
    : Math.max(
        0,
        Number(
          quotaSource?.remaining ??
          (dailyQuota - usedToday)
        ) || 0
      );

  const percent =
    dailyQuota > 0
      ? Math.min(
          100,
          Math.round(
            (usedToday /
              dailyQuota) *
              100
          )
        )
      : 0;

  const planInfo =
    getPlanInfo(
      me.subscription
    );

  return (
    <GlassCard className="p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-blue-600">
            Daily quota
          </p>

          <h3 className="mt-1 text-xl font-bold text-slate-900">
            {usedToday}

            <span className="text-slate-500">
              {" "}
              / {dailyQuota}
            </span>
          </h3>
        </div>

        <div className="rounded-xl bg-blue-600/10 px-3 py-2 text-right">
          <p className="text-xs font-semibold text-blue-600">
            {planInfo?.icon ||
              "⭐"}{" "}
            {planInfo?.name ||
              me.subscription ||
              "VIP"}
          </p>

          <p className="mt-0.5 text-[10px] text-slate-500">
            {planInfo
              ? `${planInfo.quota} picks/day`
              : "VIP plan"}
          </p>
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between rounded-xl bg-blue-600/5 px-3 py-3">
        <span className="text-sm font-medium text-slate-600">
          Remaining today
        </span>
        <span className="text-lg font-bold text-blue-600">
          {remainingToday}
        </span>
      </div>

      {expired && (
        <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-3">
          <p className="text-sm font-semibold text-red-700">
            Subscription expired
          </p>
          <p className="mt-1 text-xs text-red-600">
            No new picks can be distributed until you renew or upgrade.
            Your existing picks remain available.
          </p>
        </div>
      )}

      <div className="mt-4 h-3 overflow-hidden rounded-full bg-slate-200">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${percent}%`,
            background:
              "linear-gradient(90deg,#2563eb,#dc2626)",
          }}
        />
      </div>

      <div className="mt-2 flex justify-between text-[11px] text-slate-500">
        <span>
          {percent}% used
        </span>

        {quotaSource.resets_at && (
          <span>
            Resets{" "}
            {formatExpiry(
              quotaSource.resets_at
            )}
          </span>
        )}
      </div>

      {/* ONLY HIGHER PLANS */}

      {upgradeOptions.length >
        0 && (
        <div className="mt-6 border-t border-slate-200 pt-5">
          <div className="mb-3">
            <h3 className="font-semibold text-slate-900">
              Upgrade your plan
            </h3>

            <p className="mt-1 text-xs text-slate-500">
              Choose a higher plan for
              more daily picks.
            </p>
          </div>

          <div className="space-y-2">
            {upgradeOptions.map(
              (plan) => (
                <button
                  key={plan.key}
                  type="button"
                  onClick={() =>
                    onUpgrade(
                      plan.name
                    )
                  }
                  disabled={
                    !!upgradeLoading[
                      plan.name
                    ]
                  }
                  className="
                    group
                    flex w-full
                    items-center
                    justify-between
                    gap-3
                    rounded-2xl
                    border border-slate-200
                    bg-slate-50
                    p-3
                    text-left
                    transition
                    hover:border-blue-600/40
                    hover:bg-blue-600/10
                    disabled:cursor-not-allowed
                    disabled:opacity-50
                  "
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600/10 text-xl">
                      {plan.icon}
                    </div>

                    <div>
                      <p className="text-sm font-semibold text-slate-900">
                        {plan.name}
                      </p>

                      <p className="text-[11px] text-slate-500">
                        {plan.quota} picks/day
                        {" • "}
                        {plan.days} day
                        {plan.days ===
                        1
                          ? ""
                          : "s"}
                      </p>
                    </div>
                  </div>

                  <div className="text-right">
                    <p className="text-sm font-bold text-blue-600">
                      {upgradeLoading[
                        plan.name
                      ]
                        ? "Sending..."
                        : plan.display}
                    </p>

                    {!upgradeLoading[
                      plan.name
                    ] && (
                      <p className="text-[10px] text-slate-500">
                        Request upgrade →
                      </p>
                    )}
                  </div>
                </button>
              )
            )}
          </div>
        </div>
      )}

      {downgradeOptions.length > 0 && (
        <div className="mt-6 border-t border-slate-200 pt-5">
          <div className="mb-3">
            <h3 className="font-semibold text-slate-900">
              Downgrade your plan
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              Your current paid picks and entitlement will be preserved.
              The lower plan starts only after your existing entitlement
              is completed and expires.
            </p>
          </div>

          <div className="space-y-2">
            {downgradeOptions.map((plan) => (
              <button
                key={plan.key}
                type="button"
                onClick={() => {
                  if (window.confirm(
                    `Request a downgrade to ${plan.name}? Your current paid picks will be preserved.`
                  )) {
                    onDowngrade(plan.name);
                  }
                }}
                disabled={!!downgradeLoading[plan.name]}
                className="
                  flex w-full items-center justify-between gap-3
                  rounded-2xl border border-amber-200
                  bg-amber-50 p-3 text-left transition
                  hover:border-amber-400 hover:bg-amber-100
                  disabled:cursor-not-allowed disabled:opacity-50
                "
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-100 text-xl">
                    {plan.icon}
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-900">
                      {plan.name}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      {plan.quota} picks/day · {plan.days} day
                      {plan.days === 1 ? "" : "s"}
                    </p>
                  </div>
                </div>

                <div className="text-right">
                  <p className="text-sm font-bold text-amber-700">
                    {downgradeLoading[plan.name]
                      ? "Sending..."
                      : plan.display}
                  </p>
                  {!downgradeLoading[plan.name] && (
                    <p className="text-[10px] text-slate-500">
                      Request downgrade →
                    </p>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {upgradeOptions.length ===
        0 && downgradeOptions.length === 0 && (
        <div className="mt-5 rounded-2xl border border-blue-600/10 bg-blue-600/5 p-3 text-center">
          <p className="text-sm font-semibold text-blue-600">
            💎 You are on the highest plan
          </p>

          <p className="mt-1 text-xs text-slate-500">
            Yearly is currently our top
            VIP plan.
          </p>
        </div>
      )}
    </GlassCard>
  );
}

/* ============================================================
   WAITING APPROVAL
============================================================ */

function WaitingApproval({
  number,
  onBackToLogin,
}) {
  return (
    <GlassCard className="overflow-hidden">
      <div className="relative p-7 text-center">
        <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-blue-600 via-red-600 to-blue-600" />

        <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full border border-blue-600/20 bg-blue-600/10 text-4xl">
          ⏳
        </div>

        <h2 className="mt-5 text-2xl font-bold text-slate-900">
          Waiting for approval
        </h2>

        <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-600">
          Your VIP account has been
          created successfully. An
          administrator needs to approve
          your registration before you can
          log in.
        </p>

        <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <p className="text-[11px] uppercase tracking-widest text-slate-500">
            Registered number
          </p>

          <p className="mt-1 font-semibold text-slate-900">
            {number || "—"}
          </p>
        </div>

        <div className="mt-5 flex items-center justify-center gap-2 text-xs text-slate-500">
          <span className="h-2 w-2 animate-pulse rounded-full bg-blue-600" />
          Waiting for administrator approval
        </div>

        <button
          type="button"
          onClick={onBackToLogin}
          className="
            mt-6
            rounded-xl
            border border-slate-200
            bg-slate-100
            px-5 py-2.5
            text-sm font-semibold
            text-slate-700
            transition
            hover:bg-slate-200
            hover:text-white
          "
        >
          Back to login
        </button>
      </div>
    </GlassCard>
  );
}

/* ============================================================
   LOCKED OVERLAY
============================================================ */

function LockedOverlay() {
  return (
    <div className="absolute inset-0 flex items-center justify-center rounded-2xl">
      <div className="absolute inset-0 rounded-2xl bg-white/75 backdrop-blur-sm" />

      <div className="relative z-10 rounded-full border border-blue-600/20 bg-white px-4 py-2 text-xs font-bold text-blue-700 shadow-xl">
        🔒 VIP ONLY
      </div>
    </div>
  );
}

/* ============================================================
   MAIN VIP PORTAL
============================================================ */

export default function VIPPortal() {
  const navigate = useNavigate();


  const [mode, setMode] =
    useState("signup");

  const [logged, setLogged] =
    useState(
      !!localStorage.getItem(
        "vip_token"
      )
    );

  const [form, setForm] =
    useState({
      name: "",
      number: "",
      password: "",
      subscription: "Daily",
    });

  const [loading, setLoading] =
    useState(false);

  const [error, setError] =
    useState("");

  const [
    successMessage,
    setSuccessMessage,
  ] = useState("");

  const [
    waitingApproval,
    setWaitingApproval,
  ] = useState(false);

  const [me, setMe] =
    useState(null);

  const [quota, setQuota] =
    useState(null);

  const [picks, setPicks] =
    useState([]);

  const [notifications, setNotifications] =
    useState([]);

  const [unreadNotifications, setUnreadNotifications] =
    useState(0);

  const [notificationsOpen, setNotificationsOpen] =
    useState(false);

  const [pushEnabled, setPushEnabled] =
    useState(false);

  const [pushLoading, setPushLoading] =
    useState(false);

  const [pushMessage, setPushMessage] =
    useState("");

  const [
    upgradeLoading,
    setUpgradeLoading,
  ] = useState({});

  const [
    pendingUpgrade,
    setPendingUpgrade,
  ] = useState(null);

  const [
    downgradeLoading,
    setDowngradeLoading,
  ] = useState({});

  const [
    pendingDowngrade,
    setPendingDowngrade,
  ] = useState(null);

  const [
    renewalLoading,
    setRenewalLoading,
  ] = useState({});

  const [
    pendingRenewal,
    setPendingRenewal,
  ] = useState(null);

  const { toasts, push, dismiss } =
    useToast();

  /* ==========================================================
     CURRENT PLAN
  ========================================================== */

  const currentPlanIndex =
    useMemo(() => {
      if (!me?.subscription) {
        return -1;
      }

      return PLAN_ORDER.findIndex(
        (plan) =>
          plan ===
          normalizePlan(
            me.subscription
          )
      );
    }, [me]);

  /*
   * ONLY plans higher than the current plan.
   *
   * Daily   -> Weekly, Monthly, Yearly
   * Weekly  -> Monthly, Yearly
   * Monthly -> Yearly
   * Yearly  -> none
   */

  const upgradeOptions =
    useMemo(() => {
      if (currentPlanIndex === -1) {
        return [];
      }

      return PLANS.filter(
        (_, index) =>
          index > currentPlanIndex
      );
    }, [currentPlanIndex]);

  const downgradeOptions =
    useMemo(() => {
      if (currentPlanIndex === -1) {
        return [];
      }

      return PLANS.filter(
        (_, index) => index < currentPlanIndex
      );
    }, [currentPlanIndex]);

  /* ==========================================================
     FETCH VIP DATA
  ========================================================== */

  const fetchVipDataOnce =
    useCallback(
      async (token) => {
        if (!token) {
          return null;
        }

        try {
          const [
            meData,
            quotaData,
            picksData,
            notificationsData,
          ] = await Promise.all([
            api.vipMe(token),
            api.vipQuota(token),
            api.vipPicks(token),
            api.vipNotifications(token),
          ]);

          if (
            meData?.success
          ) {
            const profile =
              getResponseUser(
                meData
              );

            if (profile) {
              setMe(profile);
            }
          }

          if (
            quotaData?.success
          ) {
            const quotaResponse =
              getResponseData(
                quotaData
              );

            if (quotaResponse) {
              setQuota(
                quotaResponse
              );
            }
          }

          if (
            picksData?.success
          ) {
            const picksResponse =
              getResponseData(
                picksData
              );

            const vipPicksList =
              Array.isArray(picksResponse)
                ? picksResponse
                : Array.isArray(picksResponse?.picks)
                  ? picksResponse.picks
                  : [];

            setPicks(vipPicksList);
          }

          if (notificationsData?.success) {
            const notificationResponse =
              getResponseData(notificationsData);

            setNotifications(
              Array.isArray(notificationResponse?.notifications)
                ? notificationResponse.notifications
                : []
            );

            setUnreadNotifications(
              Number(notificationResponse?.unread_count || 0)
            );
          }

          return {
            meData,
            quotaData,
            picksData,
            notificationsData,
          };
        } catch (err) {
          console.error(
            "fetchVipDataOnce error:",
            err
          );

          setError(
            typeof err?.error ===
              "string"
              ? err.error
              : err?.message ||
                  "Failed to fetch VIP data"
          );

          return null;
        }
      },
      []
    );

  /* ==========================================================
     INITIAL / AUTO REFRESH
  ========================================================== */

  useEffect(() => {
    const token =
      localStorage.getItem(
        "vip_token"
      );

    if (!logged || !token) {
      setMe(null);
      setQuota(null);
      setPicks([]);
      setNotifications([]);
      setUnreadNotifications(0);
      setNotificationsOpen(false);
      return undefined;
    }

    let mounted = true;

    const load = async () => {
      if (!mounted) return;

      await fetchVipDataOnce(
        token
      );
    };

    load();

    /*
     * Refresh every 30 seconds.
     * This catches admin-approved upgrades.
     */
    const interval =
      setInterval(
        load,
        30000
      );

    return () => {
      mounted = false;
      clearInterval(
        interval
      );
    };
  }, [
    logged,
    fetchVipDataOnce,
  ]);

  /* ==========================================================
     LOGIN
  ========================================================== */

  const login = async (e) => {
    e?.preventDefault();

    setError("");
    setSuccessMessage("");

    if (!form.number) {
      setError(
        "Phone number is required"
      );
      return;
    }

    if (!form.password) {
      setError(
        "Password is required"
      );
      return;
    }

    if (
      !clientValidateNumber(
        form.number
      )
    ) {
      setError(
        "Enter a valid Kenyan phone number"
      );
      return;
    }

    setLoading(true);

    try {
      const normalized =
        normalizeToE164(
          form.number
        );

      /*
       * IMPORTANT:
       * authVipAdmin.js now accepts:
       *
       * vipLogin(number, password)
       */
      const res =
        await api.vipLogin(
          normalized,
          form.password
        );

      const token =
        getResponseToken(res);

      const loginUser =
        getResponseUser(res);

      if (
        token &&
        (
          res?.success ||
          res?.message ===
            "login successful"
        )
      ) {
        /*
         * Store ONLY the token.
         *
         * Password is never stored in localStorage.
         */
        localStorage.setItem(
          "vip_token",
          token
        );

        setLogged(true);
        setWaitingApproval(false);

        setError("");
        setSuccessMessage("");

        /*
         * Use the user returned directly from login
         * immediately. This prevents the UI from showing
         * "Expired" / "—" while vipMe is loading.
         */
        if (loginUser) {
          setMe(loginUser);
        }

        /*
         * Clear password from React state after login.
         */
        setForm(
          (current) => ({
            ...current,
            password: "",
            number: normalized,
          })
        );

        /*
         * Fetch latest profile, quota and picks.
         */
        await fetchVipDataOnce(
          token
        );

        push(
          "Welcome back! Login successful.",
          "success"
        );
      } else {
        localStorage.removeItem(
          "vip_token"
        );

        setLogged(false);
        setMe(null);
        setQuota(null);
        setPicks([]);

        setError(
          typeof res?.error ===
            "string"
            ? res.error
            : "Login failed or account is not approved"
        );
      }
    } catch (err) {
      console.error(
        "login error:",
        err
      );

      localStorage.removeItem(
        "vip_token"
      );

      setLogged(false);
      setMe(null);
      setQuota(null);
      setPicks([]);

      setError(
        typeof err?.error ===
          "string"
          ? err.error
          : err?.message ||
              "Network error"
      );
    } finally {
      setLoading(false);
    }
  };

  /* ==========================================================
     SIGN UP
  ========================================================== */

  const signup = async (e) => {
    e?.preventDefault();

    setError("");
    setSuccessMessage("");

    if (
      !form.name ||
      !form.number
    ) {
      setError(
        "Name and phone number are required"
      );
      return;
    }

    if (
      !clientValidateNumber(
        form.number
      )
    ) {
      setError(
        "Enter a valid Kenyan phone number"
      );
      return;
    }

    if (!form.password || form.password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setLoading(true);

    try {
      const normalized =
        normalizeToE164(
          form.number
        );

      const res =
        await api.vipRegister({
          name: form.name,
          number: normalized,
          subscription:
            form.subscription,
          password: form.password,
        });

      if (
        res &&
        res.success
      ) {
        setForm(
          (current) => ({
            ...current,
            number: normalized,
          })
        );

        setWaitingApproval(
          true
        );

        setLogged(false);

        setError("");
        setSuccessMessage("");

        push(
          "Registration successful — waiting for admin approval",
          "success",
          6000
        );
      } else {
        setError(
          typeof res?.error ===
            "string"
            ? res.error
            : "Registration failed"
        );
      }
    } catch (err) {
      console.error(
        "signup error:",
        err
      );

      setError(
        typeof err?.error ===
          "string"
          ? err.error
          : err?.message ||
              "Network error"
      );
    } finally {
      setLoading(false);
    }
  };

  /* ==========================================================
     VIP NOTIFICATION ACTIONS
  ========================================================== */

  const markNotificationRead = async (notification) => {
    if (!notification || notification.is_read) {
      return;
    }

    const token = localStorage.getItem("vip_token");
    if (!token) return;

    try {
      const res = await api.vipMarkNotificationRead(
        token,
        notification.id
      );

      if (res?.success) {
        setNotifications((current) =>
          current.map((item) =>
            item.id === notification.id
              ? { ...item, is_read: true }
              : item
          )
        );

        setUnreadNotifications((current) =>
          Math.max(0, current - 1)
        );
      }
    } catch (err) {
      console.error("markNotificationRead error:", err);
    }
  };

  const markAllNotificationsRead = async () => {
    const token = localStorage.getItem("vip_token");
    if (!token || unreadNotifications === 0) return;

    try {
      const res =
        await api.vipMarkAllNotificationsRead(token);

      if (res?.success) {
        setNotifications((current) =>
          current.map((item) => ({
            ...item,
            is_read: true,
          }))
        );

        setUnreadNotifications(0);
      }
    } catch (err) {
      console.error("markAllNotificationsRead error:", err);
    }
  };

  const openNotification = async (notification) => {
    await markNotificationRead(notification);
    setNotificationsOpen(false);
    navigate(notification?.link || "/vip");
  };

  /* ==========================================================
     LOGOUT
  ========================================================== */

  const logout = () => {
    try {
      if (
        api.vipLogout
      ) {
        api.vipLogout();
      }
    } catch (err) {
      // Ignore logout API errors.
    }

    localStorage.removeItem(
      "vip_token"
    );

    setLogged(false);
    setMe(null);
    setQuota(null);
    setPicks([]);
    setNotifications([]);
    setUnreadNotifications(0);
    setNotificationsOpen(false);
    setPendingUpgrade(null);

    push(
      "Logged out successfully",
      "info"
    );
  };

  /* ==========================================================
     UPGRADE
  ========================================================== */

  const handleUpgrade =
    async (planName) => {
      if (!me) {
        push(
          "Please log in first",
          "error"
        );
        return;
      }

      const requestedPlan =
        getPlanInfo(planName);

      if (!requestedPlan) {
        push(
          "Invalid upgrade plan",
          "error"
        );
        return;
      }

      const currentIndex =
        PLAN_ORDER.indexOf(
          normalizePlan(
            me.subscription
          )
        );

      const requestedIndex =
        PLAN_ORDER.indexOf(
          requestedPlan.key
        );

      /*
       * Never allow same plan or downgrade.
       */
      if (
        currentIndex === -1 ||
        requestedIndex <=
          currentIndex
      ) {
        push(
          "You can only upgrade to a higher plan.",
          "error"
        );
        return;
      }

      setUpgradeLoading(
        (current) => ({
          ...current,
          [planName]: true,
        })
      );

      try {
        const token =
          localStorage.getItem(
            "vip_token"
          );

        if (!token) {
          throw new Error(
            "VIP session expired. Please log in again."
          );
        }

        const res =
          await api.vipUpgrade(
            token,
            planName
          );

        if (
          res &&
          res.success
        ) {
          setPendingUpgrade({
            to_plan:
              requestedPlan.key,
            requested_at:
              new Date().toISOString(),
          });

          push(
            `Upgrade request for ${requestedPlan.name} sent to admin.`,
            "success",
            6000
          );

          /*
           * Do not fake the new subscription.
           * Admin approval changes the real DB record.
           */
          await fetchVipDataOnce(
            token
          );
        } else {
          push(
            typeof res?.error ===
              "string"
              ? res.error
              : "Upgrade request failed",
            "error"
          );
        }
      } catch (err) {
        console.error(
          "handleUpgrade error:",
          err
        );

        push(
          typeof err?.message ===
            "string"
            ? err.message
            : "Upgrade request failed",
          "error"
        );
      } finally {
        setUpgradeLoading(
          (current) => ({
            ...current,
            [planName]: false,
          })
        );
      }
    };

  /* ==========================================================
     DOWNGRADE
  ========================================================== */

  const handleDowngrade = async (planName) => {
    if (!me) {
      push("Please log in first", "error");
      return;
    }

    const requestedPlan = getPlanInfo(planName);

    if (!requestedPlan) {
      push("Invalid downgrade plan", "error");
      return;
    }

    const currentIndex = PLAN_ORDER.indexOf(
      normalizePlan(me.subscription)
    );
    const requestedIndex = PLAN_ORDER.indexOf(
      requestedPlan.key
    );

    if (
      currentIndex === -1 ||
      requestedIndex < 0 ||
      requestedIndex >= currentIndex
    ) {
      push("You can only downgrade to a lower plan.", "error");
      return;
    }

    setDowngradeLoading((current) => ({
      ...current,
      [planName]: true,
    }));

    try {
      const token = localStorage.getItem("vip_token");

      if (!token) {
        throw new Error(
          "VIP session expired. Please log in again."
        );
      }

      const res = await api.vipDowngrade(
        token,
        requestedPlan.key
      );

      if (res && res.success) {
        setPendingDowngrade({
          to_plan: requestedPlan.key,
          requested_at: new Date().toISOString(),
        });

        push(
          `Downgrade request for ${requestedPlan.name} sent to admin.`,
          "success",
          6000
        );

        await fetchVipDataOnce(token);
      } else {
        push(
          typeof res?.error === "string"
            ? res.error
            : "Downgrade request failed",
          "error"
        );
      }
    } catch (err) {
      console.error("handleDowngrade error:", err);
      push(
        typeof err?.message === "string"
          ? err.message
          : "Downgrade request failed",
        "error"
      );
    } finally {
      setDowngradeLoading((current) => ({
        ...current,
        [planName]: false,
      }));
    }
  };

  /* ==========================================================
     VIP SUBSCRIPTION RENEWAL
  ========================================================== */

  const handleRenewal = async (planName) => {
    if (!me) {
      push("Please log in first", "error");
      return;
    }

    const requestedPlan = getPlanInfo(planName);

    if (!requestedPlan) {
      push("Invalid renewal plan", "error");
      return;
    }

    const currentPlan = getPlanInfo(me.subscription);

    if (!currentPlan || requestedPlan.key !== currentPlan.key) {
      push(
        "You can only renew your current VIP plan. Use Upgrade to choose a higher plan.",
        "error"
      );
      return;
    }

    setRenewalLoading((current) => ({
      ...current,
      [requestedPlan.key]: true,
    }));

    try {
      const token = localStorage.getItem("vip_token");

      if (!token) {
        throw new Error(
          "VIP session expired. Please log in again."
        );
      }

      const res = await api.vipRenew(
        token,
        requestedPlan.key
      );

      if (res?.success) {
        setPendingRenewal({
          to_plan: requestedPlan.key,
          requested_at: new Date().toISOString(),
        });

        push(
          `Renewal request for ${requestedPlan.name} sent to admin.`,
          "success",
          6000
        );

        await fetchVipDataOnce(token);
      } else {
        push(
          typeof res?.error === "string"
            ? res.error
            : "Renewal request failed",
          "error"
        );
      }
    } catch (err) {
      console.error("handleRenewal error:", err);

      push(
        typeof err?.message === "string"
          ? err.message
          : "Renewal request failed",
        "error"
      );
    } finally {
      setRenewalLoading((current) => ({
        ...current,
        [requestedPlan.key]: false,
      }));
    }
  };

  /* ==========================================================
     DEREGISTER
  ========================================================== */

  const deregister =
    async () => {
      if (!me?.number) {
        push(
          "No registered number",
          "error"
        );
        return;
      }

      if (
        !window.confirm(
          "Are you sure you want to deregister your VIP account?"
        )
      ) {
        return;
      }

      setLoading(true);

      try {
        const token =
          localStorage.getItem(
            "vip_token"
          );

        const res = await api.vipDeregister(token);

        if (
          res &&
          res.success
        ) {
          push(
            "Account deregistered successfully",
            "success"
          );

          logout();
        } else {
          push(
            typeof res?.error ===
              "string"
              ? res.error
              : "Failed to deregister",
            "error"
          );
        }
      } catch (err) {
        console.error(
          "deregister error:",
          err
        );

        push(
          typeof err?.message ===
            "string"
            ? err.message
            : "Failed to deregister",
          "error"
        );
      } finally {
        setLoading(false);
      }
    };

  /* ==========================================================
     FORM CLASSES
  ========================================================== */

  const inputClass = `
    w-full
    rounded-2xl
    border border-slate-200
    bg-white
    px-4 py-3
    text-sm text-slate-900
    placeholder:text-slate-400
    outline-none
    transition
    focus:border-blue-600/50
    focus:ring-2
    focus:ring-blue-600/15
  `;

  const visiblePicks =
    logged
      ? picks
      : picks.slice(0, 2);

  const visiblePickGroups = [];
  const pickGroupMap = new Map();

  visiblePicks.forEach((pick) => {
    const key = getDeliveryDateKey(pick?.delivered_at);

    if (!pickGroupMap.has(key)) {
      const group = {
        key,
        label: formatDeliveryDateLabel(key),
        picks: [],
      };

      pickGroupMap.set(key, group);
      visiblePickGroups.push(group);
    }

    pickGroupMap.get(key).picks.push(pick);
  });

  /* ==========================================================
     WEB PUSH CONTROLS
  ========================================================== */

  const enablePushNotifications = async () => {
    const token = localStorage.getItem("vip_token");

    if (!token || pushLoading) return;

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
        setPushMessage(
          permission === "denied"
            ? "Notifications are blocked in your browser settings."
            : "Notification permission was not granted."
        );
        return;
      }

      const registration = await navigator.serviceWorker.ready;

      let subscription =
        await registration.pushManager.getSubscription();

      if (!subscription) {
        const keyResponse = await api.vipPushPublicKey();

        if (!keyResponse?.success) {
          throw new Error(
            keyResponse?.error || "Could not load the push notification key."
          );
        }

        const keyData = getResponseData(keyResponse);
        const publicKey =
          keyData?.publicKey ||
          keyResponse?.publicKey;

        if (!publicKey) {
          throw new Error("Push notifications are not configured on the server.");
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

      const saved = await api.vipPushSubscribe(
        token,
        subscription.toJSON()
      );

      if (!saved?.success) {
        throw new Error(
          saved?.error || "Could not save this device subscription."
        );
      }

      setPushEnabled(true);
      setPushMessage("Notifications are enabled on this device.");
      push("VIP push notifications enabled.", "success");
    } catch (err) {
      console.error("VIP push enable error:", err);
      setPushMessage(
        err?.message || "Could not enable push notifications."
      );
    } finally {
      setPushLoading(false);
    }
  };

  const disablePushNotifications = async () => {
    const token = localStorage.getItem("vip_token");

    if (!token || pushLoading) return;

    setPushLoading(true);
    setPushMessage("");

    try {
      const registration = await navigator.serviceWorker.ready;
      const subscription =
        await registration.pushManager.getSubscription();

      if (subscription) {
        const result = await api.vipPushUnsubscribe(
          token,
          subscription.endpoint
        );

        if (!result?.success) {
          throw new Error(
            result?.error || "Could not remove this device from the server."
          );
        }

        await subscription.unsubscribe();
      }

      setPushEnabled(false);
      setPushMessage("Notifications are turned off on this device.");
      push("VIP push notifications disabled.", "info");
    } catch (err) {
      console.error("VIP push disable error:", err);
      setPushMessage(
        err?.message || "Could not disable push notifications."
      );
    } finally {
      setPushLoading(false);
    }
  };

  useEffect(() => {
    let active = true;

    const checkPushSubscription = async () => {
      const token = localStorage.getItem("vip_token");

      if (!logged || !token || !("serviceWorker" in navigator)) {
        if (active) setPushEnabled(false);
        return;
      }

      try {
        const registration = await navigator.serviceWorker.ready;
        const subscription =
          await registration.pushManager.getSubscription();

        if (!subscription) {
          if (active) setPushEnabled(false);
          return;
        }

        // Associate this device with the currently logged-in VIP account.
        const saved = await api.vipPushSubscribe(
          token,
          subscription.toJSON()
        );

        if (!saved?.success) {
          throw new Error(
            saved?.error || "Could not sync this device's push subscription."
          );
        }

        if (active) setPushEnabled(true);
      } catch (err) {
        console.warn("Could not sync VIP push subscription:", err);
        if (active) {
          setPushMessage(
            err?.message || "Could not sync this device's notifications."
          );
        }
      }
    };

    checkPushSubscription();

    return () => {
      active = false;
    };
  }, [logged]);

  /* ==========================================================
     RENDER
  ========================================================== */

  return (
    <div
      className={`
        min-h-screen
        bg-slate-100 text-slate-900
      `}
    >
      {/* Background glow */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -left-32 -top-32 h-80 w-80 rounded-full bg-blue-600/10 blur-3xl" />

        <div className="absolute right-0 top-1/3 h-96 w-96 rounded-full bg-red-600/5 blur-3xl" />

        <div className="absolute bottom-0 left-1/3 h-80 w-80 rounded-full bg-red-500/5 blur-3xl" />
      </div>

      <div className="relative mx-auto w-full min-w-0 max-w-7xl px-3 py-4 sm:px-6 sm:py-5 lg:px-8">
        {/* ====================================================
            HEADER
        ==================================================== */}

        <header className="mb-8">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-700 to-red-600 text-xl shadow-lg shadow-red-600/20">
                  👑
                </div>

                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-blue-600">
                    Lilymac
                  </p>

                  <h1 className="text-2xl font-black tracking-tight text-slate-900">
                    VIP Predictions
                  </h1>
                </div>
              </div>

              <p className="mt-3 max-w-xl text-sm text-slate-600">
                Premium football predictions,
                carefully selected for VIP members.
              </p>
            </div>

            <div className="relative flex items-center gap-2">

              {logged && (
                <div className="flex flex-col items-end gap-1">
                  <button
                    type="button"
                    onClick={
                      pushEnabled
                        ? disablePushNotifications
                        : enablePushNotifications
                    }
                    disabled={pushLoading}
                    className="
                      rounded-xl border border-blue-200
                      bg-white px-3 py-2 text-xs font-bold
                      text-blue-700 shadow-sm transition
                      hover:bg-blue-50 disabled:opacity-50
                    "
                  >
                    {pushLoading
                      ? "Please wait..."
                      : pushEnabled
                        ? "Turn off notifications"
                        : "Enable notifications"}
                  </button>

                  {pushMessage && (
                    <p className="max-w-52 text-right text-[10px] text-slate-500">
                      {pushMessage}
                    </p>
                  )}
                </div>
              )}

              {logged && (
                <div className="relative">
                  <button
                    type="button"
                    onClick={async () => {
                      const opening = !notificationsOpen;
                      setNotificationsOpen(opening);

                      if (opening) {
                        await markAllNotificationsRead();
                      }
                    }}
                    aria-label="Notifications"
                    aria-expanded={notificationsOpen}
                    className="
                      relative flex h-10 w-10 items-center
                      justify-center rounded-xl
                      border border-slate-200
                      bg-white text-xl text-slate-700
                      shadow-sm transition
                      hover:bg-slate-50
                    "
                  >
                    🔔

                    {unreadNotifications > 0 && (
                      <span className="
                        absolute -right-1 -top-1
                        flex h-5 min-w-5 items-center
                        justify-center rounded-full
                        bg-red-600 px-1
                        text-[10px] font-bold text-white
                      ">
                        {unreadNotifications > 99
                          ? "99+"
                          : unreadNotifications}
                      </span>
                    )}
                  </button>

                  {notificationsOpen && (
                    <div className="
                      fixed right-3 top-20 z-[100]
                      w-[min(22rem,calc(100vw-1.5rem))]
                      max-h-[calc(100vh-6rem)] overflow-y-auto
                      rounded-2xl border border-slate-200
                      bg-white shadow-2xl
                    ">
                      <div className="
                        flex items-center justify-between
                        border-b border-slate-100 px-4 py-3
                      ">
                        <div>
                          <h3 className="text-sm font-bold text-slate-900">
                            Notifications
                          </h3>
                          <p className="text-xs text-slate-500">
                            {unreadNotifications} unread
                          </p>
                        </div>

                        {unreadNotifications > 0 && (
                          <button
                            type="button"
                            onClick={markAllNotificationsRead}
                            className="
                              text-xs font-semibold
                              text-blue-600 hover:text-blue-800
                            "
                          >
                            Mark all read
                          </button>
                        )}
                      </div>

                      <div className="max-h-80 overflow-y-auto">
                        {notifications.length === 0 ? (
                          <div className="px-4 py-8 text-center">
                            <p className="text-2xl">🔔</p>
                            <p className="mt-2 text-sm font-semibold text-slate-700">
                              No notifications yet
                            </p>
                            <p className="mt-1 text-xs text-slate-500">
                              New VIP picks and quota updates will appear here.
                            </p>
                          </div>
                        ) : (
                          notifications.map((notification) => (
                            <button
                              key={notification.id}
                              type="button"
                              onClick={() =>
                                openNotification(notification)
                              }
                              className={`
                                block w-full border-b border-slate-100
                                px-4 py-3 text-left transition
                                hover:bg-slate-50
                                ${
                                  notification.is_read
                                    ? "bg-white"
                                    : "bg-blue-50/70"
                                }
                              `}
                            >
                              <div className="flex items-start gap-3">
                                <span className="mt-0.5 text-lg">
                                  {notification.notification_type === "quota_renewal"
                                    ? "🔄"
                                    : "⚽"}
                                </span>

                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center justify-between gap-2">
                                    <p className="text-sm font-bold text-slate-900">
                                      {notification.title}
                                    </p>

                                    {!notification.is_read && (
                                      <span className="
                                        h-2 w-2 shrink-0
                                        rounded-full bg-blue-600
                                      " />
                                    )}
                                  </div>

                                  <p className="mt-1 text-xs leading-relaxed text-slate-600">
                                    {notification.message}
                                  </p>

                                  <p className="mt-2 text-[10px] text-slate-400">
                                    {notification.created_at
                                      ? new Date(
                                          notification.created_at
                                        ).toLocaleString()
                                      : ""}
                                  </p>
                                </div>
                              </div>
                            </button>
                          ))
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {logged && (
                <button
                  type="button"
                  onClick={
                    logout
                  }
                  className="
                    rounded-xl
                    border border-red-500/20
                    bg-red-500/10
                    px-4 py-2.5
                    text-xs font-semibold
                    text-red-400
                    transition
                    hover:bg-red-500
                    hover:text-white
                  "
                >
                  Logout
                </button>
              )}
            </div>
          </div>
        </header>

        {/* ====================================================
            MAIN GRID
        ==================================================== */}

        <div className="grid min-w-0 grid-cols-1 gap-4 sm:gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
          {/* ==================================================
              LEFT
          ================================================== */}

          <div className="space-y-5">
            {!logged &&
              !waitingApproval && (
                <GlassCard className="p-5">
                  <div className="mb-5">
                    <p className="text-xs font-bold uppercase tracking-widest text-blue-600">
                      VIP Access
                    </p>

                    <h2 className="mt-1 text-xl font-bold text-slate-900">
                      {mode ===
                      "login"
                        ? "Welcome back"
                        : "Join VIP"}
                    </h2>

                    <p className="mt-1 text-xs text-slate-500">
                      {mode ===
                      "login"
                        ? "Log in to unlock your premium picks."
                        : "Create your VIP account and wait for approval."}
                    </p>
                  </div>

                  <div className="mb-5 grid grid-cols-2 rounded-2xl bg-slate-50 p-1">
                    <button
                      type="button"
                      onClick={() => {
                        navigate("/vip-admin-login?mode=vip");
                      }}
                      className={`
                        rounded-xl
                        px-3 py-2
                        text-sm font-semibold
                        transition
                        ${
                          mode ===
                          "login"
                            ? "bg-blue-600 text-black shadow-lg"
                            : "text-slate-500 hover:text-white"
                        }
                      `}
                    >
                      Login
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setMode(
                          "signup"
                        );
                        setError("");
                        setSuccessMessage(
                          ""
                        );
                      }}
                      className={`
                        rounded-xl
                        px-3 py-2
                        text-sm font-semibold
                        transition
                        ${
                          mode ===
                          "signup"
                            ? "bg-blue-600 text-black shadow-lg"
                            : "text-slate-500 hover:text-white"
                        }
                      `}
                    >
                      Sign Up
                    </button>
                  </div>

                  {successMessage && (
                    <div className="mb-4 rounded-2xl border border-emerald-500/20 bg-emerald-500/10 p-3 text-sm text-emerald-300">
                      ✓{" "}
                      {successMessage}
                    </div>
                  )}

                  {/* LOGIN */}

                  {mode ===
                    "login" && (
                    <form
                      onSubmit={
                        login
                      }
                      className="space-y-3"
                    >
                      <input
                        className={
                          inputClass
                        }
                        placeholder="Phone number"
                        inputMode="tel"
                        autoComplete="tel"
                        value={
                          form.number
                        }
                        onChange={(
                          e
                        ) =>
                          setForm({
                            ...form,
                            number:
                              e
                                .target
                                .value,
                          })
                        }
                      />

                      <input
                        type="password"
                        className={
                          inputClass
                        }
                        placeholder="Password"
                        autoComplete="current-password"
                        value={
                          form.password
                        }
                        onChange={(
                          e
                        ) =>
                          setForm({
                            ...form,
                            password:
                              e
                                .target
                                .value,
                          })
                        }
                      />

                      <button
                        type="submit"
                        disabled={
                          loading
                        }
                        className="
                          w-full
                          rounded-2xl
                          bg-gradient-to-r
                          from-blue-600
                          to-red-600
                          px-4 py-3
                          text-sm font-black
                          text-black
                          shadow-lg
                          shadow-red-600/20
                          transition
                          hover:brightness-110
                          disabled:cursor-not-allowed
                          disabled:opacity-50
                        "
                      >
                        {loading
                          ? "Signing in..."
                          : "Login to VIP →"}
                      </button>

                      {error && (
                        <div className="rounded-2xl border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-300">
                          {error}
                        </div>
                      )}
                    </form>
                  )}

                  {/* SIGN UP */}

                  {mode ===
                    "signup" && (
                    <form
                      onSubmit={
                        signup
                      }
                      className="space-y-3"
                    >
                      <input
                        className={
                          inputClass
                        }
                        placeholder="Full name"
                        autoComplete="name"
                        value={
                          form.name
                        }
                        onChange={(
                          e
                        ) =>
                          setForm({
                            ...form,
                            name: e
                              .target
                              .value,
                          })
                        }
                      />

                      <input
                        className={
                          inputClass
                        }
                        placeholder="Phone number"
                        inputMode="tel"
                        autoComplete="tel"
                        value={
                          form.number
                        }
                        onChange={(
                          e
                        ) =>
                          setForm({
                            ...form,
                            number:
                              e
                                .target
                                .value,
                          })
                        }
                      />

                      <input
                        className={inputClass}
                        type="password"
                        placeholder="Create password (minimum 8 characters)"
                        autoComplete="new-password"
                        minLength={8}
                        required
                        value={form.password}
                        onChange={(e) =>
                          setForm({
                            ...form,
                            password: e.target.value,
                          })
                        }
                      />

                      <select
                        className={
                          inputClass
                        }
                        value={
                          form.subscription
                        }
                        onChange={(
                          e
                        ) =>
                          setForm({
                            ...form,
                            subscription:
                              e
                                .target
                                .value,
                          })
                        }
                      >
                        {PLANS.map(
                          (
                            plan
                          ) => (
                            <option
                              key={
                                plan.key
                              }
                              value={
                                plan.name
                              }
                              className="bg-white"
                            >
                              {
                                plan.name
                              }{" "}
                              —{" "}
                              {
                                plan.display
                              }
                            </option>
                          )
                        )}
                      </select>

                      <button
                        type="submit"
                        disabled={
                          loading
                        }
                        className="
                          w-full
                          rounded-2xl
                          bg-gradient-to-r
                          from-blue-600
                          to-red-600
                          px-4 py-3
                          text-sm font-black
                          text-black
                          shadow-lg
                          shadow-red-600/20
                          transition
                          hover:brightness-110
                          disabled:cursor-not-allowed
                          disabled:opacity-50
                        "
                      >
                        {loading
                          ? "Creating account..."
                          : "Create VIP account →"}
                      </button>

                      {error && (
                        <div className="rounded-2xl border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-300">
                          {error}
                        </div>
                      )}
                    </form>
                  )}
                </GlassCard>
              )}

            {/* WAITING */}

            {!logged &&
              waitingApproval && (
                <WaitingApproval
                  number={
                    form.number
                  }
                  onBackToLogin={() => {
                    setWaitingApproval(false);
                    navigate("/vip-admin-login?mode=vip");
                  }}
                />
              )}

            {/* LOGGED USER */}

            {logged && me && (
              <>
                <VipSummary
                  me={me}
                  quota={quota}
                  onDeregister={
                    deregister
                  }
                />

                {quota && (
                  Number(quota.queued_entitlements || 0) === 0 &&
                  (
                    quota.expired === true ||
                    Number(quota.active_entitlement_total || 0) > 0
                  )
                ) && (
                  <GlassCard className="border-amber-500/20 bg-amber-500/5 p-5">
                    <SectionTitle
                      icon="🔄"
                      title="Renew Your Current Plan"
                      subtitle="Extend your existing plan. If you still have paid-for picks outstanding, the renewed entitlement will begin after they are delivered."
                    />

                    {pendingRenewal ? (
                      <div className="mt-4 rounded-2xl border border-blue-500/20 bg-blue-500/5 p-4">
                        <p className="text-sm font-bold text-blue-700">
                          Renewal request pending
                        </p>
                        <p className="mt-1 text-xs text-slate-600">
                          Your request for{" "}
                          <strong>
                            {getPlanInfo(pendingRenewal.to_plan)?.name ||
                              pendingRenewal.to_plan}
                          </strong>{" "}
                          is waiting for admin approval.
                        </p>
                      </div>
                    ) : (
                      <div className="mt-4 space-y-3">
                        {PLANS.filter(
                          (plan) =>
                            plan.key === normalizePlan(me.subscription)
                        ).map((plan) => (
                          <div
                            key={plan.key}
                            className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-3"
                          >
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600/10 text-xl">
                              {plan.icon}
                            </div>

                            <div className="min-w-0 flex-1">
                              <p className="text-sm font-bold text-slate-900">
                                {plan.name}
                              </p>
                              <p className="text-xs text-slate-500">
                                {plan.display} · {plan.quota} picks/day · {plan.days} days
                              </p>
                            </div>

                            <button
                              type="button"
                              disabled={Boolean(renewalLoading[plan.key])}
                              onClick={() => handleRenewal(plan.key)}
                              className="rounded-xl bg-blue-600 px-3 py-2 text-xs font-bold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {renewalLoading[plan.key]
                                ? "Sending..."
                                : "Renew current plan"}
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </GlassCard>
                )}

                {quota && (
                  <VipQuotaCard
                    me={me}
                    quota={quota}
                    onUpgrade={
                      handleUpgrade
                    }
                    upgradeLoading={
                      upgradeLoading
                    }
                    upgradeOptions={
                      upgradeOptions
                    }
                    onDowngrade={
                      handleDowngrade
                    }
                    downgradeLoading={
                      downgradeLoading
                    }
                    downgradeOptions={
                      downgradeOptions
                    }
                  />
                )}

                {pendingUpgrade && (
                  <GlassCard className="border-blue-600/20 bg-blue-600/5 p-4">
                    <div className="flex items-start gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-600/10">
                        ⏳
                      </div>

                      <div>
                        <p className="text-sm font-semibold text-blue-700">
                          Upgrade request pending
                        </p>

                        <p className="mt-1 text-xs leading-5 text-slate-500">
                          Your request for{" "}
                          <span className="font-semibold text-slate-700">
                            {getPlanInfo(
                              pendingUpgrade.to_plan
                            )?.name ||
                              pendingUpgrade.to_plan}
                          </span>{" "}
                          is waiting for admin approval.
                        </p>
                      </div>
                    </div>
                  </GlassCard>
                )}

                {pendingDowngrade && (
                  <GlassCard className="border-amber-300/40 bg-amber-50 p-4">
                    <div className="flex items-start gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-100">
                        ⏳
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-amber-800">
                          Downgrade request pending
                        </p>
                        <p className="mt-1 text-xs leading-5 text-slate-600">
                          Your request to move to{" "}
                          <span className="font-semibold text-slate-800">
                            {getPlanInfo(pendingDowngrade.to_plan)?.name ||
                              pendingDowngrade.to_plan}
                          </span>{" "}
                          is waiting for admin approval. Your current paid
                          entitlement remains protected.
                        </p>
                      </div>
                    </div>
                  </GlassCard>
                )}
              </>
            )}

            {/* AVAILABLE PLANS */}

            {!logged &&
              !waitingApproval && (
                <GlassCard className="p-5">
                  <SectionTitle
                    icon="💎"
                    title="VIP Plans"
                    subtitle="Choose the plan that fits you."
                  />

                  <div className="space-y-2">
                    {PLANS.map(
                      (plan) => (
                        <div
                          key={
                            plan.key
                          }
                          className="
                            rounded-2xl
                            border border-slate-200
                            bg-white
                            p-3
                            transition
                            hover:border-blue-600/20
                            hover:bg-blue-600/5
                          "
                        >
                          <div className="flex items-center gap-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600/10 text-xl">
                              {
                                plan.icon
                              }
                            </div>

                            <div className="min-w-0 flex-1">
                              <div className="flex items-center justify-between gap-2">
                                <p className="text-sm font-bold text-slate-900">
                                  {
                                    plan.name
                                  }
                                </p>

                                <p className="text-sm font-bold text-blue-600">
                                  {
                                    plan.display
                                  }
                                </p>
                              </div>

                              <p className="mt-0.5 text-[11px] text-slate-500">
                                {
                                  plan.quota
                                }{" "}
                                picks/day
                                {" • "}
                                {
                                  plan.days
                                }{" "}
                                day
                                {plan.days ===
                                1
                                  ? ""
                                  : "s"}
                              </p>
                            </div>
                          </div>
                        </div>
                      )
                    )}
                  </div>
                </GlassCard>
              )}
          </div>

          {/* ==================================================
              RIGHT — PICKS
          ================================================== */}

          {logged && (
          <div className="min-w-0">
            <GlassCard className="overflow-hidden">
              <div className="border-b border-slate-200 bg-gradient-to-r from-blue-600/10 via-transparent to-transparent p-5 sm:p-6">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xl">
                        🔥
                      </span>

                      <h2 className="text-xl font-black text-slate-900">
                        Your VIP Picks
                      </h2>
                    </div>

                    <p className="mt-1 text-xs text-slate-500">
                      Premium predictions updated by
                      the Lilymac team.
                    </p>
                  </div>

                  {logged && (
                    <div className="hidden rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-emerald-400 sm:block">
                      ● VIP Active
                    </div>
                  )}
                </div>
              </div>

              <div className="p-4 sm:p-6">
                {loading && (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    {[1, 2, 3, 4].map(
                      (item) => (
                        <div
                          key={item}
                          className="h-36 animate-pulse rounded-2xl bg-slate-100"
                        />
                      )
                    )}
                  </div>
                )}

                {!loading &&
                  picks.length ===
                    0 && (
                    <div className="rounded-3xl border border-dashed border-slate-200 p-10 text-center">
                      <div className="text-4xl">
                        ⚽
                      </div>

                      <h3 className="mt-3 font-semibold text-slate-900">
                        No picks available
                      </h3>

                      <p className="mt-1 text-xs text-slate-500">
                        Check back later for new VIP
                        predictions.
                      </p>
                    </div>
                  )}

                {!loading &&
                  picks.length >
                    0 && (
                    <div className="space-y-6">
                      {visiblePickGroups.map((group) => (
                        <section key={group.key} className="min-w-0">
                          <div className="mb-3 flex flex-wrap items-center gap-2">
                            <span className="h-2 w-2 rounded-full bg-blue-600" />
                            <h3 className="text-sm font-black text-slate-800">
                              {group.label}
                            </h3>
                            <span className="rounded-full bg-blue-600/10 px-2 py-0.5 text-[10px] font-bold text-blue-700">
                              {group.picks.length} {group.picks.length === 1 ? "pick" : "picks"}
                            </span>
                          </div>
                          <div className="grid min-w-0 grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
                            {group.picks.map(
                        (
                          pick,
                          index
                        ) => {
                          const matchName =
                            pick?.match ||
                            `${pick?.home_team || "Home"} vs ${
                              pick?.away_team ||
                              "Away"
                            }`;

                          const matchTime =
                            pick?.match_time;

                          const tip =
                            logged
                              ? pick?.tip ||
                                pick?.pick ||
                                "—"
                              : pick?.preview_tip ||
                                "VIP ONLY";

                          return (
                            <div
                              key={
                                pick?._id ||
                                pick?.id ||
                                index
                              }
                              className="
                                group
                                relative
                                min-w-0
                                overflow-hidden
                                rounded-2xl
                                border border-slate-200
                                bg-white
                                p-4
                                transition
                                hover:-translate-y-0.5
                                hover:border-blue-600/20
                                hover:bg-white
                              "
                            >
                              <div className="absolute right-0 top-0 h-24 w-24 rounded-full bg-blue-600/5 blur-2xl" />

                              <div className="relative">
                                <div className="flex items-start justify-between gap-3">
                                  <div className="min-w-0">
                                    <p className="break-words text-sm font-bold leading-5 text-slate-900">
                                      {
                                        matchName
                                      }
                                    </p>

                                    <p className="mt-1 text-[11px] text-slate-500">
                                      {matchTime
                                        ? formatExpiry(
                                            matchTime
                                          )
                                        : "Match time unavailable"}
                                    </p>
                                  </div>

                                  <div className="shrink-0 rounded-lg bg-blue-600/10 px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-blue-600">
                                    VIP
                                  </div>
                                </div>

                                <div className="mt-4 rounded-xl border border-blue-600/10 bg-blue-600/5 p-3">
                                  <p className="text-[9px] font-bold uppercase tracking-widest text-slate-500">
                                    Prediction
                                  </p>

                                  <p className="mt-1 text-sm font-black text-blue-600">
                                    {tip}
                                  </p>
                                </div>
                              </div>

                              {!logged && (
                                <LockedOverlay />
                              )}
                            </div>
                          );
                        }
                            )}
                          </div>
                        </section>
                      ))}
                    </div>
                  )}

                {!logged &&
                  picks.length >
                    2 && (
                    <div className="mt-5 rounded-2xl border border-blue-600/10 bg-blue-600/5 p-4 text-center">
                      <p className="text-sm font-semibold text-blue-700">
                        🔒 More VIP picks are locked
                      </p>

                      <p className="mt-1 text-xs text-slate-500">
                        Log in to unlock all premium
                        predictions.
                      </p>
                    </div>
                  )}
              </div>
            </GlassCard>
          </div>
          )}
        </div>
      </div>

      {/* ======================================================
          TOASTS
      ====================================================== */}

      <div className="fixed bottom-4 right-4 z-50 flex max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="alert"
            className={`
              flex items-start gap-3
              rounded-2xl
              border
              px-4 py-3
              text-sm font-semibold
              shadow-2xl
              backdrop-blur-xl
              ${
                toast.type === "success"
                  ? "border-emerald-500/20 bg-emerald-500/90 text-white"
                  : toast.type === "error"
                  ? "border-red-500/20 bg-red-500/90 text-white"
                  : "border-slate-200 bg-slate-200/95 text-slate-900"
              }
            `}
          >
            <span className="min-w-0 flex-1 break-words">
              {toast.msg}
            </span>

            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              aria-label="Close notification"
              title="Close"
              className="ml-1 shrink-0 rounded-md px-1 text-xl font-bold leading-none opacity-80 transition hover:bg-black/10 hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-current"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
