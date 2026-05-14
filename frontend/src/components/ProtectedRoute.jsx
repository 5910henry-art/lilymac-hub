// src/components/ProtectedRoute.jsx
import React, { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { getMe } from "../api/betsWallet";
import { getAuthToken } from "../api/core";

export default function ProtectedRoute({ children }) {
  const [loading, setLoading] = useState(true);
  const [authorized, setAuthorized] = useState(false);

  useEffect(() => {
    const checkAuth = async () => {
      const token = getAuthToken();

      // No token → immediately reject
      if (!token) {
        setAuthorized(false);
        setLoading(false);
        return;
      }

      try {
        const res = await getMe();

        if (res && res.success) {
          setAuthorized(true);
        } else {
          setAuthorized(false);
        }
      } catch (err) {
        console.error("Auth check failed:", err);
        setAuthorized(false);
      }

      setLoading(false);
    };

    checkAuth();
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-900 text-white">
        Checking authentication...
      </div>
    );
  }

  if (!authorized) {
    return <Navigate to="/auth" replace />;
  }

  return children;
}
