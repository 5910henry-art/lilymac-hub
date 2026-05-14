// src/components/FloatingBetslip.jsx
import React from "react";
import { useNavigate } from "react-router-dom";

export default function FloatingBetslip({
  betslip = [],
  combinedOdds = 0,
  floatRef,
  floatPos = { left: null, bottom: 72 },
  handlePointerDown,
  isDragging = false,
  bounce = false
}) {
  const navigate = useNavigate();

  return (
    <div
      ref={floatRef}
      onPointerDown={handlePointerDown}
      className="fixed z-50"
      style={{
        left: typeof floatPos.left === "number" ? floatPos.left : "50%",
        bottom: typeof floatPos.bottom === "number" ? floatPos.bottom : 72,
        transform: typeof floatPos.left === "number" ? "none" : "translateX(-50%)",
        touchAction: "none",
        cursor: isDragging ? "grabbing" : "grab",
        userSelect: "none",
      }}
    >
      <div
        onClick={() => {
          if (!isDragging) navigate("/betslip");
        }}
        className={`flex items-center gap-3 px-4 py-2 rounded-full shadow-lg select-none transition-transform duration-180 ${
          bounce ? "scale-105" : "scale-100"
        } ${isDragging ? "opacity-90" : "opacity-100"}`}
        style={{
          background: "linear-gradient(90deg, rgba(255,255,255,0.92), rgba(255,255,255,0.85))",
          color: "#0b1220",
          boxShadow: "0 6px 18px rgba(2,6,23,0.4)",
        }}
      >
        <div className="text-xs">Bets:</div>
        <div className="font-bold">{betslip.length}</div>

        <div className="h-6 w-px bg-black/10" />

        <div className="text-xs">Odds</div>
        <div className="font-semibold">{combinedOdds ? combinedOdds.toFixed(2) : "0.00"}</div>
      </div>
    </div>
  );
}
