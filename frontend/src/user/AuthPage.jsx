// src/user/AuthPage.jsx

import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import * as api from "../api/betsWallet";
import { setToken, getAuthToken, clearToken } from "../api/core";
import { useUser } from "../contexts/UserContext";

const PHONE_RE = /^(07\d{8}|01\d{8}|2547\d{8})$/;

/* =========================================================
   PHONE HELPERS
========================================================= */

function normalizePhone(input) {
  if (!input) return "";

  const s = String(input).replace(/\s|-/g, "");

  if (/^0\d{9}$/.test(s)) {
    return "254" + s.slice(1);
  }

  if (/^7\d{8}$/.test(s)) {
    return "254" + s;
  }

  if (/^254\d+$/.test(s)) {
    return s;
  }

  return s;
}

/* =========================================================
   ERROR HELPERS
========================================================= */

function isHtmlError(value) {
  if (typeof value !== "string") return false;

  const text = value.trim().toLowerCase();

  return (
    text.startsWith("<!doctype") ||
    text.startsWith("<html") ||
    text.includes("<html") ||
    text.includes("<title>500 internal server error") ||
    text.includes("internal server error</h1>")
  );
}

function cleanMessage(value) {
  if (value === null || value === undefined) {
    return "";
  }

  if (typeof value !== "string") {
    return "";
  }

  const message = value.trim();

  if (!message) {
    return "";
  }

  // NEVER expose server-generated HTML to the user.
  if (isHtmlError(message)) {
    return "";
  }

  return message;
}

function getResponseData(err) {
  const response = err?.response;

  if (!response) {
    return null;
  }

  const data = response?.data;

  if (!data) {
    return null;
  }

  // JSON response
  if (typeof data === "object") {
    return data;
  }

  // Plain text response
  if (typeof data === "string") {
    const cleaned = cleanMessage(data);

    return cleaned
      ? {
          message: cleaned,
        }
      : null;
  }

  return null;
}

function getBackendMessage(err) {
  const data = getResponseData(err);

  if (!data) return "";

  const candidates = [
    data.message,
    data.error,
    data.msg,
    data.detail,
  ];

  for (const candidate of candidates) {
    const cleaned = cleanMessage(candidate);

    if (cleaned) {
      return cleaned;
    }
  }

  return "";
}

/*
 * Convert technical/backend errors into messages suitable
 * for normal Lilymac users.
 */
function getFriendlyError(err, type = "login") {
  const status = err?.response?.status;

  /*
   * Axios/network errors
   */
  if (
    err?.code === "ERR_NETWORK" ||
    err?.message === "Network Error"
  ) {
    return "Unable to connect to Lilymac Hub. Please check your internet connection.";
  }

  if (
    err?.code === "ECONNABORTED" ||
    err?.code === "ETIMEDOUT" ||
    String(err?.message || "")
      .toLowerCase()
      .includes("timeout")
  ) {
    return "The request took too long. Please try again.";
  }

  /*
   * No HTTP response at all.
   */
  if (!err?.response && err) {
    const message = cleanMessage(err?.message);

    if (
      message &&
      !message.toLowerCase().includes("request failed") &&
      !message.toLowerCase().includes("network error")
    ) {
      return message;
    }

    return "Unable to connect to Lilymac Hub. Please try again.";
  }

  /*
   * Backend status-specific handling.
   */
  switch (status) {
    case 400:
      return (
        getBackendMessage(err) ||
        "Please check the information you entered and try again."
      );

    case 401:
      if (type === "login") {
        return "Incorrect phone number or password.";
      }

      return "Your account details could not be verified.";

    case 403:
      return (
        getBackendMessage(err) ||
        "You are not allowed to perform this action."
      );

    case 404:
      if (type === "login") {
        return "We couldn't find an account with those details.";
      }

      return "The requested service could not be found.";

    case 409:
      return (
        getBackendMessage(err) ||
        "An account with these details already exists."
      );

    case 422:
      return (
        getBackendMessage(err) ||
        "Some of the information you entered is invalid."
      );

    case 429:
      return (
        getBackendMessage(err) ||
        "Too many attempts. Please wait a moment and try again."
      );

    case 500:
    case 501:
    case 502:
    case 503:
    case 504:
      return "Something went wrong on our server. Please try again shortly.";

    default:
      break;
  }

  /*
   * A backend JSON message is okay to show if it isn't HTML
   * or some obvious technical response.
   */
  const backendMessage = getBackendMessage(err);

  if (backendMessage) {
    const lower = backendMessage.toLowerCase();

    const looksTechnical =
      lower.includes("traceback") ||
      lower.includes("internal server error") ||
      lower.includes("werkzeug") ||
      lower.includes("sqlalchemy") ||
      lower.includes("psycopg") ||
      lower.includes("exception") ||
      lower.includes("<html");

    if (!looksTechnical) {
      return backendMessage;
    }
  }

  return type === "login"
    ? "Login failed. Please try again."
    : "Account creation failed. Please try again.";
}

/* =========================================================
   COMPONENT
========================================================= */

export default function AuthPage() {
  const navigate = useNavigate();
  const { reloadUser } = useUser() || {};

  const [mode, setMode] = useState("login");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const [loading, setLoading] = useState(false);
  const [checkingToken, setCheckingToken] = useState(true);
  const [error, setError] = useState("");

  /* =========================================================
     AUTO LOGIN
  ========================================================= */

  useEffect(() => {
    let mounted = true;

    const autoLogin = async () => {
      try {
        const token = getAuthToken();

        if (!token) {
          if (mounted) {
            setCheckingToken(false);
          }

          return;
        }

        try {
          await reloadUser?.();

          if (mounted) {
            navigate("/profile", { replace: true });
          }
        } catch (err) {
          console.warn(
            "Auto-login reloadUser failed:",
            err
          );

          clearToken();
        }
      } catch (err) {
        console.error("Auto-login failed:", err);

        clearToken();
      } finally {
        if (mounted) {
          setCheckingToken(false);
        }
      }
    };

    autoLogin();

    return () => {
      mounted = false;
    };
  }, [reloadUser, navigate]);

  /* =========================================================
     MODE SWITCH
  ========================================================= */

  const switchMode = (nextMode) => {
    if (loading) return;

    setMode(nextMode);
    setError("");
    setPassword("");
  };

  /* =========================================================
     INPUT HANDLERS
  ========================================================= */

  const handlePhoneChange = (e) => {
    setPhone(e.target.value);

    if (error) {
      setError("");
    }
  };

  const handlePasswordChange = (e) => {
    setPassword(e.target.value);

    if (error) {
      setError("");
    }
  };

  /* =========================================================
     LOGIN / SIGNUP
  ========================================================= */

  const handleAuth = async (type) => {
    if (loading) return;

    setError("");

    const rawPhone = phone.trim();
    const normalized = normalizePhone(rawPhone);

    /* -------------------------
       Phone validation
    ------------------------- */

    if (
      !PHONE_RE.test(rawPhone) &&
      !PHONE_RE.test(normalized)
    ) {
      setError(
        "Enter a valid Kenyan phone number, e.g. 0712345678"
      );

      return;
    }

    /* -------------------------
       Password validation
    ------------------------- */

    if (!password) {
      setError("Please enter your password.");

      return;
    }

    if (password.length < 4) {
      setError("Password must contain at least 4 characters.");

      return;
    }

    setLoading(true);

    try {
      const res =
        type === "login"
          ? await api.login(normalized, password)
          : await api.signup(normalized, password);

      /*
       * Support both:
       *
       * {
       *   success: true,
       *   token: "..."
       * }
       *
       * and Axios-style:
       *
       * {
       *   data: {
       *     success: true,
       *     token: "..."
       *   }
       * }
       */

      const responseData =
        res?.data?.data ||
        res?.data ||
        res ||
        {};

      const data =
        responseData?.data ||
        responseData ||
        {};

      const token =
        data?.token ||
        data?.access_token ||
        res?.token ||
        res?.access_token ||
        null;

      const success =
        res?.success === true ||
        res?.data?.success === true ||
        data?.success === true ||
        Boolean(token);

      /* -------------------------
         SUCCESS
      ------------------------- */

      if (success && token) {
        setToken(token);

        try {
          await reloadUser?.();
        } catch (err) {
          /*
           * Token is already valid, so don't turn a successful
           * login into an error merely because user profile
           * loading failed.
           */
          console.warn(
            "User context reload failed after authentication:",
            err
          );
        }

        navigate("/profile", {
          replace: true,
        });

        return;
      }

      /* -------------------------
         API returned an error
         without throwing
      ------------------------- */

      const returnedMessage =
        cleanMessage(res?.error) ||
        cleanMessage(res?.msg) ||
        cleanMessage(res?.message) ||
        cleanMessage(data?.error) ||
        cleanMessage(data?.msg) ||
        cleanMessage(data?.message);

      if (returnedMessage) {
        setError(returnedMessage);
      } else {
        setError(
          type === "login"
            ? "Login failed. Please check your details and try again."
            : "Account creation failed. Please try again."
        );
      }
    } catch (err) {
      /*
       * IMPORTANT:
       * Never display err.response.data directly.
       *
       * Flask can return an HTML 500 page, which was the
       * reason the screenshot showed raw HTML.
       */
      console.error("Auth request error:", err);

      setError(getFriendlyError(err, type));
    } finally {
      setLoading(false);
    }
  };

  /* =========================================================
     FORM SUBMIT
  ========================================================= */

  const handleSubmit = (e) => {
    e.preventDefault();

    if (loading) return;

    handleAuth(mode);
  };

  /* =========================================================
     SESSION CHECK
  ========================================================= */

  if (checkingToken) {
    return (
      <div className="min-h-screen bg-slate-950 text-white flex items-center justify-center px-4">
        <div className="text-center">
          <div
            className="
              mx-auto
              mb-5
              flex
              h-14
              w-14
              items-center
              justify-center
              rounded-2xl
              bg-gradient-to-br
              from-blue-600
              to-red-600
              shadow-lg
              shadow-blue-500/20
            "
          >
            <span className="text-2xl">
              ⚡
            </span>
          </div>

          <div className="text-sm font-medium text-white/80">
            Checking session...
          </div>

          <div className="mt-3 h-1 w-32 overflow-hidden rounded-full bg-white/10">
            <div className="h-full w-1/2 animate-pulse rounded-full bg-blue-500" />
          </div>
        </div>
      </div>
    );
  }

  /* =========================================================
     AUTH PAGE
  ========================================================= */

  return (
    <div
      className="
        relative
        min-h-screen
        overflow-hidden
        bg-slate-950
        text-white
        flex
        items-center
        justify-center
        px-4
        py-8
      "
    >
      {/* Background glow */}

      <div
        className="
          pointer-events-none
          absolute
          -top-40
          -left-40
          h-80
          w-80
          rounded-full
          bg-blue-600/20
          blur-3xl
        "
      />

      <div
        className="
          pointer-events-none
          absolute
          -bottom-40
          -right-40
          h-80
          w-80
          rounded-full
          bg-red-600/15
          blur-3xl
        "
      />

      {/* =====================================================
          AUTH CARD
      ====================================================== */}

      <div
        className="
          relative
          z-10
          w-full
          max-w-md
        "
      >
        {/* Logo / Brand */}

        <div className="mb-7 text-center">
          <div
            className="
              mx-auto
              mb-4
              flex
              h-16
              w-16
              items-center
              justify-center
              rounded-2xl
              bg-gradient-to-br
              from-blue-600
              via-blue-500
              to-red-600
              shadow-xl
              shadow-blue-500/20
            "
          >
            <span className="text-3xl">
              ⚡
            </span>
          </div>

          <h1 className="text-2xl font-black tracking-tight">
            LILYMAC
          </h1>

          <p className="mt-1 text-xs font-medium uppercase tracking-[0.22em] text-white/40">
            Football Intelligence
          </p>
        </div>

        {/* Main card */}

        <div
          className="
            rounded-3xl
            border
            border-white/10
            bg-slate-900/80
            p-5
            shadow-2xl
            shadow-black/40
            backdrop-blur-xl
            sm:p-7
          "
        >
          {/* Header */}

          <div className="mb-6">
            <h2 className="text-xl font-bold">
              {mode === "login"
                ? "Welcome back"
                : "Create your account"}
            </h2>

            <p className="mt-1 text-sm text-white/45">
              {mode === "login"
                ? "Sign in to continue to Lilymac Hub."
                : "Join Lilymac Hub and get started."}
            </p>
          </div>

          {/* =================================================
              MODE SWITCH
          ================================================== */}

          <div
            className="
              mb-6
              grid
              grid-cols-2
              gap-1
              rounded-xl
              bg-slate-800
              p-1
            "
          >
            <button
              type="button"
              disabled={loading}
              onClick={() => switchMode("login")}
              className={`
                rounded-lg
                px-4
                py-2.5
                text-sm
                font-semibold
                transition-all
                duration-200
                ${
                  mode === "login"
                    ? "bg-blue-600 text-white shadow-md"
                    : "text-white/50 hover:bg-white/5 hover:text-white"
                }
              `}
            >
              Login
            </button>

            <button
              type="button"
              disabled={loading}
              onClick={() => switchMode("signup")}
              className={`
                rounded-lg
                px-4
                py-2.5
                text-sm
                font-semibold
                transition-all
                duration-200
                ${
                  mode === "signup"
                    ? "bg-blue-600 text-white shadow-md"
                    : "text-white/50 hover:bg-white/5 hover:text-white"
                }
              `}
            >
              Sign Up
            </button>
          </div>

          {/* =================================================
              FORM
          ================================================== */}

          <form
            onSubmit={handleSubmit}
            className="space-y-5"
            noValidate
          >
            {/* Phone */}

            <div>
              <label
                htmlFor="phone"
                className="
                  mb-2
                  block
                  text-xs
                  font-semibold
                  uppercase
                  tracking-wider
                  text-white/55
                "
              >
                Phone Number
              </label>

              <div className="relative">
                <span
                  className="
                    pointer-events-none
                    absolute
                    left-4
                    top-1/2
                    -translate-y-1/2
                    text-base
                    text-white/35
                  "
                >
                  📱
                </span>

                <input
                  id="phone"
                  type="tel"
                  inputMode="numeric"
                  autoComplete="tel"
                  placeholder="0712 345 678"
                  value={phone}
                  onChange={handlePhoneChange}
                  disabled={loading}
                  aria-invalid={Boolean(error)}
                  className="
                    w-full
                    rounded-xl
                    border
                    border-white/10
                    bg-slate-800/80
                    py-3.5
                    pl-11
                    pr-4
                    text-sm
                    text-white
                    placeholder:text-white/25
                    outline-none
                    transition
                    duration-200
                    focus:border-blue-500
                    focus:bg-slate-800
                    focus:ring-2
                    focus:ring-blue-500/20
                    disabled:cursor-not-allowed
                    disabled:opacity-50
                  "
                />
              </div>
            </div>

            {/* Password */}

            <div>
              <label
                htmlFor="password"
                className="
                  mb-2
                  block
                  text-xs
                  font-semibold
                  uppercase
                  tracking-wider
                  text-white/55
                "
              >
                Password
              </label>

              <div className="relative">
                <span
                  className="
                    pointer-events-none
                    absolute
                    left-4
                    top-1/2
                    -translate-y-1/2
                    text-base
                    text-white/35
                  "
                >
                  🔒
                </span>

                <input
                  id="password"
                  type={
                    showPassword
                      ? "text"
                      : "password"
                  }
                  autoComplete={
                    mode === "login"
                      ? "current-password"
                      : "new-password"
                  }
                  placeholder="Enter your password"
                  value={password}
                  onChange={handlePasswordChange}
                  disabled={loading}
                  className="
                    w-full
                    rounded-xl
                    border
                    border-white/10
                    bg-slate-800/80
                    py-3.5
                    pl-11
                    pr-12
                    text-sm
                    text-white
                    placeholder:text-white/25
                    outline-none
                    transition
                    duration-200
                    focus:border-blue-500
                    focus:bg-slate-800
                    focus:ring-2
                    focus:ring-blue-500/20
                    disabled:cursor-not-allowed
                    disabled:opacity-50
                  "
                />

                <button
                  type="button"
                  onClick={() =>
                    setShowPassword(
                      (prev) => !prev
                    )
                  }
                  disabled={loading}
                  aria-label={
                    showPassword
                      ? "Hide password"
                      : "Show password"
                  }
                  className="
                    absolute
                    right-2
                    top-1/2
                    flex
                    h-9
                    w-9
                    -translate-y-1/2
                    items-center
                    justify-center
                    rounded-lg
                    text-white/40
                    transition
                    hover:bg-white/5
                    hover:text-white
                    disabled:pointer-events-none
                  "
                >
                  {showPassword
                    ? "🙈"
                    : "👁️"}
                </button>
              </div>
            </div>

            {/* =================================================
                ERROR
            ================================================== */}

            {error && (
              <div
                role="alert"
                aria-live="polite"
                className="
                  flex
                  items-start
                  gap-3
                  rounded-xl
                  border
                  border-red-500/20
                  bg-red-500/10
                  px-4
                  py-3
                  text-sm
                  text-red-300
                "
              >
                <span
                  className="mt-0.5 shrink-0"
                  aria-hidden="true"
                >
                  ⚠️
                </span>

                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-red-200">
                    {mode === "login"
                      ? "Login failed"
                      : "Account creation failed"}
                  </p>

                  <p className="mt-0.5 leading-5 text-red-300">
                    {error}
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => setError("")}
                  disabled={loading}
                  aria-label="Dismiss error"
                  className="
                    shrink-0
                    rounded-lg
                    px-2
                    py-1
                    text-red-300/60
                    transition
                    hover:bg-red-500/10
                    hover:text-red-200
                  "
                >
                  ×
                </button>
              </div>
            )}

            {/* =================================================
                SUBMIT
            ================================================== */}

            <button
              type="submit"
              disabled={loading}
              className="
                group
                relative
                flex
                w-full
                items-center
                justify-center
                gap-2
                overflow-hidden
                rounded-xl
                bg-gradient-to-r
                from-blue-600
                to-blue-500
                px-4
                py-3.5
                text-sm
                font-bold
                text-white
                shadow-lg
                shadow-blue-600/20
                transition-all
                duration-200
                hover:from-blue-500
                hover:to-blue-400
                hover:shadow-xl
                hover:shadow-blue-600/30
                active:scale-[0.98]
                disabled:pointer-events-none
                disabled:opacity-60
              "
            >
              {loading ? (
                <>
                  <span
                    className="
                      h-4
                      w-4
                      animate-spin
                      rounded-full
                      border-2
                      border-white/30
                      border-t-white
                    "
                  />

                  <span>
                    {mode === "login"
                      ? "Signing in..."
                      : "Creating account..."}
                  </span>
                </>
              ) : (
                <>
                  <span>
                    {mode === "login"
                      ? "Login"
                      : "Create Account"}
                  </span>

                  <span
                    className="
                      transition-transform
                      duration-200
                      group-hover:translate-x-1
                    "
                  >
                    →
                  </span>
                </>
              )}
            </button>
          </form>

          {/* Footer */}

          <div className="mt-6 text-center">
            <p className="text-xs text-white/30">
              {mode === "login"
                ? "Don't have an account?"
                : "Already have an account?"}
            </p>

            <button
              type="button"
              disabled={loading}
              onClick={() =>
                switchMode(
                  mode === "login"
                    ? "signup"
                    : "login"
                )
              }
              className="
                mt-1
                text-sm
                font-semibold
                text-blue-400
                transition
                hover:text-blue-300
                disabled:pointer-events-none
                disabled:opacity-50
              "
            >
              {mode === "login"
                ? "Create one"
                : "Sign in instead"}
            </button>
          </div>
        </div>

        {/* Bottom branding */}

        <p className="mt-6 text-center text-[10px] uppercase tracking-[0.2em] text-white/20">
          Lilymac Hub • Football Predictions
        </p>
      </div>
    </div>
  );
}
