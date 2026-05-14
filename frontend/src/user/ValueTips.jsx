// src/pages/ValueTips.jsx
import React, { useEffect, useState } from "react";
import api from "../api/api";

export default function ValueTips() {
  const [tips, setTips] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchTips() {
      setLoading(true);
      const res = await api.getTipsValue();
      if (res.success && Array.isArray(res.data.tips)) {
        setTips(res.data.tips);
      }
      setLoading(false);
    }
    fetchTips();
  }, []);

  if (loading) return <div className="p-4">Loading...</div>;
  if (!tips.length) return <div className="p-4">No tips available.</div>;

  const formatMarket = (market) => {
    if (!market) return null;
    const prob = market.confidence ?? 0;
    const isYesHigher = prob >= 0.5;
    const displaySide = isYesHigher ? "Yes" : "No";
    const displayProb = Math.round(isYesHigher ? prob * 100 : (1 - prob) * 100);
    return { text: `${displaySide} (${displayProb}%)`, isYes: displaySide === "Yes" };
  };

  const tipsByDate = tips.reduce((acc, tip) => {
    const date = new Date(tip.utcDate).toLocaleDateString();
    if (!acc[date]) acc[date] = [];
    acc[date].push(tip);
    return acc;
  }, {});

  return (
    <div className="p-4 space-y-6">
      {Object.entries(tipsByDate).map(([date, tipsForDate]) => (
        <div key={date}>
          <h2 className="text-lg font-semibold mb-2">{date}</h2>
          <div className="space-y-4">
            {tipsForDate.map((tip) => (
              <div
                key={tip.match_id}
                className="border rounded-lg p-3 shadow-sm bg-white/5"
              >
                {/* Match Header */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <img
                      src={tip.home_logo || "/default-logo.png"}
                      alt={tip.home_team_name}
                      className="w-6 h-6 object-contain"
                    />
                    <span className="font-semibold">{tip.home_team_name}</span>
                  </div>

                  <div className="font-semibold">
                    Vs — Predicted: {tip.predicted_score?.most_likely || "-"}
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{tip.away_team_name}</span>
                    <img
                      src={tip.away_logo || "/default-logo.png"}
                      alt={tip.away_team_name}
                      className="w-6 h-6 object-contain"
                    />
                  </div>
                </div>

                {/* Markets - Horizontal */}
                <div className="ml-2 flex flex-wrap gap-4 text-sm">
                  {["btts", "over_under?.over_1_5", "over_under?.over_2_5", "over_under?.over_3_5", "over_under?.over_4_5"].map((key) => {
                    const market = key.split("?.").reduce((obj, k) => obj?.[k], tip);
                    const { text, isYes } = formatMarket(market) || {};
                    if (!text) return null;
                    return (
                      <div key={key} className={`font-medium ${isYes ? "text-green-400" : "text-red-400"}`}>
                        {key.replace("over_under?.", "").toUpperCase()}: {text}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
