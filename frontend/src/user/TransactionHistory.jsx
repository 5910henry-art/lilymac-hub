```javascript
// src/user/TransactionHistory.jsx

import { useEffect, useState } from "react";
import { getTransactions } from "../api/betsWallet";

export default function TransactionHistory() {
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(false);

  async function loadTransactions() {
    try {
      setLoading(true);

      const res = await getTransactions();

      if (res.success) {
        setTransactions(res.data || []);
      } else {
        setTransactions([]);
      }
    } catch (err) {
      console.error(err);
      setTransactions([]);
    }

    setLoading(false);
  }

  useEffect(() => {
    loadTransactions();
  }, []);

  const formatNumber = (n) => {
    const num = Number(n);
    return isFinite(num) ? num.toFixed(2) : "0.00";
  };

  const getColor = (type) => {
    if (type === "deposit" || type === "win" || type === "cashout") {
      return "text-green-400";
    }

    if (type === "withdraw" || type === "bet") {
      return "text-red-400";
    }

    return "text-gray-300";
  };

  return (
    <div className="p-4 bg-slate-900 min-h-screen text-white">
      <h2 className="font-bold text-xl mb-4">Transaction History</h2>

      {loading && (
        <p className="text-gray-400">Loading transactions...</p>
      )}

      {!loading && transactions.length === 0 && (
        <p className="text-gray-400">No transactions yet.</p>
      )}

      <div className="space-y-2">
        {transactions.map((t, i) => (
          <div
            key={i}
            className="bg-slate-800 p-3 rounded flex justify-between items-center"
          >
            <div>
              <div className="font-medium capitalize">
                {t.type || "transaction"}
              </div>

              <div className="text-gray-400 text-sm">
                {t.created_at
                  ? new Date(t.created_at).toLocaleString()
                  : ""}
              </div>
            </div>

            <div className={`font-semibold ${getColor(t.type)}`}>
              KES {formatNumber(t.amount)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```
