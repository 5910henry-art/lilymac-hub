// src/user/AuthPage.jsx
import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import * as api from "../api/betsWallet";
import { setToken, getAuthToken, clearToken } from "../api/core";
import { useUser } from "../contexts/UserContext";

const PHONE_RE = /^(07\d{8}|01\d{8}|2547\d{8})$/;

function normalizePhone(input) {
  if (!input) return "";
  let s = input.replace(/\s|-/g, "");
  if (/^0\d{9}$/.test(s)) return "254" + s.slice(1);
  if (/^7\d{8}$/.test(s)) return "254" + s;
  if (/^254\d+$/.test(s)) return s;
  return s;
}

function normalizeError(err, fallback = "Request failed") {
  if (!err) return fallback;
  if (typeof err === "string") return err;
  if (typeof err === "object") return err.error || err.msg || JSON.stringify(err);
  return fallback;
}

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

  const inputClass =
    "w-full rounded-lg p-2 border bg-slate-700 text-white border-slate-600 focus:outline-none focus:ring-2 focus:ring-amber-300";

  // ------------------------
  // AUTO LOGIN
  // ------------------------
  useEffect(() => {
    const autoLogin = async () => {
      try {
        const token = getAuthToken();
        if (!token) return setCheckingToken(false);

        try {
          // Attempt to reload user context
          await reloadUser?.();
          navigate("/profile", { replace: true });
        } catch (e) {
          console.warn("Auto-login reloadUser failed:", e);
          clearToken();
        }
      } catch (err) {
        console.error("Auto-login failed:", err);
        clearToken();
      } finally {
        setCheckingToken(false);
      }
    };
    autoLogin();
  }, [reloadUser, navigate]);

  // ------------------------
  // LOGIN / SIGNUP
  // ------------------------
  const handleAuth = async (type) => {
    setError("");
    if (!PHONE_RE.test(phone) && !PHONE_RE.test(normalizePhone(phone))) {
      return setError("Invalid phone number");
    }

    setLoading(true);
    try {
      const normalized = normalizePhone(phone);
      const res =
        type === "login"
          ? await api.login(normalized, password)
          : await api.signup(normalized, password);

      const data = res?.data?.data || res?.data || {};
      const token =
        data?.token || data?.access_token || res?.token || res?.access_token || null;

      if (res?.success && token) {
        setToken(token);
        try {
          await reloadUser?.(); // ensures user context is populated
        } catch {}
        navigate("/profile", { replace: true });
      } else {
        setError(res?.error || res?.msg || `${type} failed`);
      }
    } catch (err) {
      console.error("Auth request error:", err);
      setError(normalizeError(err?.message, "Network error"));
    } finally {
      setLoading(false);
    }
  };

  const handleLogin = (e) => { e.preventDefault(); handleAuth("login"); };
  const handleSignup = (e) => { e.preventDefault(); handleAuth("signup"); };

  if (checkingToken) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-900 text-white">
        <div className="animate-pulse text-lg">Checking session...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 text-white p-4">
      <div className="w-full max-w-md p-6 rounded-2xl border border-slate-700 bg-slate-800/60 space-y-4">
        <h1 className="text-2xl font-bold text-center">🎯 Lilymac Hub</h1>

        <div className="flex gap-2">
          <button
            className={"flex-1 p-2 rounded " + (mode === "login" ? "bg-amber-500 text-black font-semibold" : "bg-slate-700")}
            onClick={() => { setMode("login"); setError(""); }}
          >
            Login
          </button>
          <button
            className={"flex-1 p-2 rounded " + (mode === "signup" ? "bg-amber-500 text-black font-semibold" : "bg-slate-700")}
            onClick={() => { setMode("signup"); setError(""); }}
          >
            Sign Up
          </button>
        </div>

        <form onSubmit={mode === "login" ? handleLogin : handleSignup} className="space-y-3">
          <input type="text" placeholder="Phone number" value={phone} onChange={(e) => setPhone(e.target.value)} className={inputClass} />

          <div className="relative">
            <input type={showPassword ? "text" : "password"} placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} className={inputClass} />
            <button type="button" className="absolute right-3 top-2" onClick={() => setShowPassword(!showPassword)}>
              {showPassword ? "🙈" : "👁️"}
            </button>
          </div>

          {error && <div className="text-rose-400 text-sm text-center">{error}</div>}

          <button disabled={loading} className="w-full bg-amber-500 hover:bg-amber-600 text-black font-semibold p-2 rounded-lg">
            {loading ? "Please wait..." : mode === "login" ? "Login" : "Create Account"}
          </button>
        </form>
      </div>
    </div>
  );
}
