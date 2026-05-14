// src/components/SportsMenu.jsx
import React from "react";
import { motion } from "framer-motion";

export default function SportsMenu({
  selectedSport = "All",
  setSelectedSport,
  evPercent = 12,
  valueBets = 8,
  topPick = "Arsenal vs Chelsea",
  profit = "+24%",
}) {
  const sports = ["All", "Football", "Virtual"];

  return (
    <div className="mt-3 space-y-2">

      {/* SPORTS TABS */}
      <div className="flex gap-2 overflow-x-auto no-scrollbar">
        {sports.map((sport) => (
          <button
            key={sport}
            onClick={() => setSelectedSport?.(sport)}
            className={`px-4 py-1.5 rounded-full text-xs font-semibold transition
              ${
                selectedSport === sport
                  ? "bg-green-500 text-white shadow"
                  : "bg-slate-800 text-gray-300"
              }`}
          >
            {sport}
          </button>
        ))}
      </div>

      {/* STATS BAR */}
      <div className="bg-slate-800 rounded p-3 flex justify-between items-center text-xs">

        {/* EV Badge */}
        <motion.div
          className="px-3 py-1 text-green-400 font-bold bg-slate-900 rounded-full border border-green-500"
          animate={{
            scale: [1, 1.08, 1],
            boxShadow: [
              "0 0 4px #22c55e",
              "0 0 12px #22c55e",
              "0 0 4px #22c55e",
            ],
          }}
          transition={{ duration: 1.8, repeat: Infinity }}
        >
          ⚡ EV+ {evPercent}%
        </motion.div>

        {/* Value Bets */}
        <div className="text-orange-400 font-semibold">
          🔥 {valueBets} Bets
        </div>

        {/* Top Pick */}
        <div className="text-sky-400 truncate max-w-[120px]">
          🎯 {topPick}
        </div>

        {/* Profit */}
        <div className="text-green-400 font-bold">
          💰 {profit}
        </div>
      </div>
    </div>
  );
}
