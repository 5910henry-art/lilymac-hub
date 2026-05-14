```javascript
// src/user/AccountPage.jsx

import React, { useState } from "react";
import { deposit, withdraw } from "../api/betsWallet";
import { useUser } from "../contexts/UserContext";

export default function AccountPage() {
  const { user, reloadUser } = useUser();

  const balance = user?.balance || 0;

  const [amount, setAmount] = useState("");
  const [action, setAction] = useState("deposit");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();

    const numAmount = Number(amount);

    if (!numAmount || numAmount <= 0) {
      alert("Please enter a valid amount");
      return;
    }

    try {
      setLoading(true);

      let res;

      if (action === "deposit") {
        res = await deposit(numAmount);
      } else {
        res = await withdraw(numAmount);
      }

      if (!res.success) {
        alert(res.error || "Transaction failed");
        return;
      }

      alert(
        action === "deposit"
          ? `Deposited KES ${numAmount.toFixed(2)}`
          : `Withdrew KES ${numAmount.toFixed(2)}`
      );

      setAmount("");

      // refresh wallet globally
      await reloadUser();

    } catch (err) {
      console.error(err);
      alert("Transaction failed");
    }

    setLoading(false);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 p-4">
      <div className="w-full max-w-lg bg-slate-800 rounded-lg shadow-inner shadow-black/25 p-6 space-y-6">

        <h1 className="text-2xl font-bold text-white text-center">
          Account Management
        </h1>

        {/* Balance */}
        <div className="text-center bg-slate-700 p-4 rounded text-white font-semibold text-xl shadow">
          Balance: KES {balance.toFixed(2)}
        </div>

        {/* Deposit / Withdraw Form */}
        <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
          <div className="flex gap-2">
            <select
              value={action}
              onChange={(e) => setAction(e.target.value)}
              className="flex-1 p-3 rounded bg-slate-700 border border-slate-600 text-white"
            >
              <option value="deposit">Deposit</option>
              <option value="withdraw">Withdraw</option>
            </select>

            <input
              type="number"
              placeholder="Amount"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="flex-1 p-3 rounded bg-slate-700 border border-slate-600 text-white placeholder-gray-300"
            />
          </div>

          <button
            disabled={loading}
            type="submit"
            className="w-full bg-green-500 text-black font-bold py-3 rounded hover:bg-green-600 transition"
          >
            {loading
              ? "Processing..."
              : action === "deposit"
              ? "Deposit"
              : "Withdraw"}
          </button>
        </form>

        <div className="text-gray-400 text-sm text-center">
          Deposits and withdrawals update your wallet instantly.
        </div>

      </div>
    </div>
  );
}
```
