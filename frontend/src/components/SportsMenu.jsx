// src/components/SportsMenu.jsx

import React from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";

export default function SportsMenu({
  selectedSport = "Football",
  setSelectedSport,
  evPercent = 0,
  valueBets = 0,
  profit = "+24%",
}) {
  const navigate = useNavigate();

  const activeSport =
    selectedSport === "All" || !selectedSport
      ? "Football"
      : selectedSport;

  const sports = [
    {
      key: "Football",
      label: "Football",
      icon: "⚽",
    },
    {
      key: "Virtual",
      label: "Virtual",
      icon: "🎮",
    },
  ];

  return (
    <div className="mt-3 space-y-3">

      {/* =====================================================
          SPORTS NAVIGATION
      ====================================================== */}

      <div
        className="
          relative
          overflow-hidden
          bg-gradient-to-r
          from-red-950/80
          via-slate-900/90
          to-blue-950/80
          border
          border-slate-700/70
          rounded-xl
          p-1.5
          shadow-lg
        "
      >
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute -left-10 -top-10 h-24 w-24 rounded-full bg-red-600/15 blur-2xl" />
          <div className="absolute -right-10 -top-10 h-24 w-24 rounded-full bg-blue-600/15 blur-2xl" />
        </div>

        <div className="relative flex gap-1">
          {sports.map((sport) => {
            const active =
              activeSport === sport.key;

            return (
              <button
                key={sport.key}
                type="button"
                onClick={() =>
                  setSelectedSport?.(
                    sport.key
                  )
                }
                className={`
                  relative
                  flex-1
                  px-4
                  py-2.5
                  rounded-lg
                  text-xs
                  font-semibold
                  transition-all
                  duration-200
                  active:scale-95
                  ${
                    active
                      ? "bg-gradient-to-r from-red-600/90 via-slate-800 to-blue-600/90 text-white shadow-lg shadow-blue-900/30 border border-blue-400/20"
                      : "text-gray-400 hover:text-white hover:bg-slate-800/80"
                  }
                `}
              >
                <span className="mr-1.5">
                  {sport.icon}
                </span>

                {sport.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* =====================================================
          PERFORMANCE / VALUE METRICS
      ====================================================== */}

      <div className="grid grid-cols-2 gap-2">

        {/* ===================================================
            EV+
        ==================================================== */}

        <motion.button
          type="button"
          onClick={() =>
            navigate("/ev")
          }
          whileTap={{
            scale: 0.97,
          }}
          className="
            relative
            overflow-hidden
            text-left
            bg-gradient-to-br
            from-red-950/70
            via-slate-800/90
            to-blue-950/70
            border
            border-red-500/25
            rounded-xl
            p-3
            transition-all
            hover:border-blue-500/50
            hover:from-red-950/80
            hover:to-blue-950/80
            active:scale-95
            shadow-lg
          "
        >
          <div className="pointer-events-none absolute -left-8 -top-8 h-20 w-20 rounded-full bg-red-500/15 blur-2xl" />

          <div className="relative">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] uppercase tracking-wide text-gray-500">
                Expected Value
              </span>

              <motion.span
                className="text-green-400 text-sm"
                animate={{
                  opacity: [
                    0.55,
                    1,
                    0.55,
                  ],
                }}
                transition={{
                  duration: 1.8,
                  repeat: Infinity,
                }}
              >
                ⚡
              </motion.span>
            </div>

            <div className="flex items-center gap-1">
              <span className="text-green-400 font-bold text-base">
                +
                {Number(
                  evPercent || 0
                ).toFixed(0)}
                %
              </span>

              <span className="text-green-500 text-xs">
                →
              </span>
            </div>

            <div className="text-[10px] text-gray-500 mt-0.5">
              View EV opportunities
            </div>
          </div>
        </motion.button>

        {/* ===================================================
            VALUE BETS
        ==================================================== */}

        <div
          className="
            relative
            overflow-hidden
            bg-gradient-to-br
            from-blue-950/70
            via-slate-800/90
            to-red-950/50
            border
            border-blue-500/25
            rounded-xl
            p-3
            shadow-lg
          "
        >
          <div className="pointer-events-none absolute -right-8 -top-8 h-20 w-20 rounded-full bg-blue-500/15 blur-2xl" />

          <div className="relative">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] uppercase tracking-wide text-gray-500">
                Opportunities
              </span>

              <span className="text-orange-400 text-sm">
                🔥
              </span>
            </div>

            <div className="text-orange-400 font-bold text-base">
              {valueBets}
            </div>

            <div className="text-[10px] text-gray-500 mt-0.5">
              Positive EV
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
