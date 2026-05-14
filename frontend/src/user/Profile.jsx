// src/user/Profile.jsx
import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  logout,
  getStats,
  getProfit,
  getProfitHistory,
  changePassword,
  deleteAccount,
} from "../api/betsWallet";
import { useUser } from "../contexts/UserContext";
import WalletPage from "./WalletPage";

import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

// Simple avatar color based on phone
function getAvatarColor(phone = "") {
  const colors = ["bg-blue-500","bg-green-500","bg-purple-500","bg-orange-500","bg-pink-500","bg-indigo-500"];
  let hash = 0;
  for (let i = 0; i < phone.length; i++) hash += phone.charCodeAt(i);
  return colors[hash % colors.length];
}

export default function Profile() {
  const navigate = useNavigate();
  const { user, balance, loadingUser, reloadUser } = useUser();

  const [walletOpen, setWalletOpen] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [stats, setStats] = useState({ total_bets: 0, wins: 0, losses: 0 });
  const [profit, setProfit] = useState(0);
  const [profitHistory, setProfitHistory] = useState([]);
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  // Load stats & profit when user is ready
  useEffect(() => {
    if (!user) return;

    const loadData = async () => {
      try {
        const s = await getStats().catch(() => null);
        const p = await getProfit().catch(() => null);
        const h = await getProfitHistory().catch(() => null);

        setStats({
          total_bets: user.total_bets ?? 0,
          wins: s?.data?.wins ?? 0,
          losses: s?.data?.losses ?? 0,
        });

        setProfit(p?.data?.profit ?? 0);
        setProfitHistory(h?.data?.history ?? []);
      } catch (e) {
        console.error("Profile load error", e);
      }
    };

    loadData();
  }, [user]);

  const winRate = stats.total_bets > 0 ? ((stats.wins / stats.total_bets) * 100).toFixed(1) : 0;

  const handlePassword = async () => {
    if (!oldPassword || !newPassword) return alert("Please fill both fields");
    const res = await changePassword(oldPassword, newPassword);
    if (res?.success) {
      alert("Password updated");
      setOldPassword("");
      setNewPassword("");
      setShowPassword(false);
    } else {
      alert(res?.error || "Failed to change password");
    }
  };

  const handleLogout = () => {
    logout();
    navigate("/bookmarks", { replace: true });
  };

  const handleDeleteAccount = async () => {
    if (!window.confirm("Are you sure you want to delete your account?")) return;
    const res = await deleteAccount();
    if (res?.success) {
      alert("Account deleted successfully");
      logout();
      navigate("/vip", { replace: true });
    } else {
      alert(res?.error || "Failed to delete account");
    }
  };

  if (loadingUser) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-800 text-white">
        <div className="animate-pulse text-lg">Loading profile...</div>
      </div>
    );
  }

  const phone = user?.phone ?? "Unknown";
  const avatarDigits = phone.slice(-3) || "000";
  const avatarColor = getAvatarColor(phone);

  return (
    <div className="min-h-screen bg-gray-800 text-white pb-10 relative">
      {/* Header */}
      <div className="bg-gray-900 p-6 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className={`h-14 w-14 rounded-full ${avatarColor} flex flex-col items-center justify-center`}>
            <span>👤</span>
            <span className="text-xs font-bold">{avatarDigits}</span>
          </div>
          <div>
            <p className="text-sm text-gray-400">Account</p>
            <h1 className="text-lg font-semibold">{phone}</h1>
            <p className="text-sm text-green-400">KES {Number(balance).toFixed(2)}</p>
          </div>
        </div>
        <div className="flex gap-3">
          <button onClick={() => navigate("/bookmarks")} className="bg-blue-600 hover:bg-blue-700 py-2 px-4 rounded">Home</button>
          <button onClick={() => setWalletOpen(true)} className="bg-green-600 hover:bg-green-700 py-2 px-4 rounded">Wallet</button>
        </div>
      </div>

      <div className="max-w-md mx-auto space-y-4 p-4">
        {/* Stats */}
        <div className="bg-gray-700 rounded-lg p-5 flex justify-around text-center">
          <div><p className="font-bold">{stats.total_bets}</p><p className="text-xs text-gray-300">Bets</p></div>
          <div><p className="font-bold text-green-400">{stats.wins}</p><p className="text-xs text-gray-300">Wins</p></div>
          <div><p className="font-bold text-red-400">{stats.losses}</p><p className="text-xs text-gray-300">Losses</p></div>
        </div>

        <div className="bg-gray-700 rounded-lg p-5 text-center">
          <p className="text-sm text-gray-300">Win Rate</p>
          <p className="text-2xl font-bold text-green-400">{winRate}%</p>
        </div>

        <div className="bg-gray-700 rounded-lg p-5">
          <p className="text-sm text-gray-300">Total Profit</p>
          <p className={`text-xl font-bold ${profit >= 0 ? "text-green-400" : "text-red-400"}`}>
            KES {Number(profit).toFixed(2)}
          </p>
        </div>

        <div className="bg-gray-700 rounded-lg p-5">
          <p className="text-sm text-gray-300 mb-3">Daily Profit</p>
          <div style={{ width: "100%", height: 200 }}>
            <ResponsiveContainer>
              <LineChart data={profitHistory || []}>
                <XAxis dataKey="day" />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="profit" stroke="#16a34a" strokeWidth={3} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <button onClick={() => setShowPassword(!showPassword)} className="w-full bg-gray-700 p-5 text-left">
          Change Password {showPassword ? "▲" : "▼"}
        </button>

        {showPassword && (
          <div className="space-y-3">
            <input type="password" placeholder="Old password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} className="w-full p-2 bg-gray-800" />
            <input type="password" placeholder="New password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className="w-full p-2 bg-gray-800" />
            <button onClick={handlePassword} className="w-full bg-green-600 py-2">Update</button>
          </div>
        )}

        <button onClick={handleLogout} className="bg-gray-700 p-5 w-full text-red-400">Logout</button>
        <button onClick={handleDeleteAccount} className="bg-red-700 p-5 w-full">Delete Account</button>
      </div>

      {walletOpen && <WalletPage onClose={() => setWalletOpen(false)} />}
    </div>
  );
}
