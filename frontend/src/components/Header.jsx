// src/components/Header.jsx
import React from "react";
import { Menu, Zap } from "lucide-react";

export default function Header({ mobileOpen, setMobileOpen }) {
  return (
    <header
      className="
        fixed top-0 left-0 right-0 z-[60]
        h-16
        flex items-center justify-between
        px-4 sm:px-6
        text-white
        shadow-lg
      "
      style={{
        background:
          "linear-gradient(110deg, #2563EB 0%, #1D4ED8 38%, #7C3AED 68%, #DC2626 100%)",
      }}
    >
      {/* Left side */}
      <div className="flex items-center gap-3 min-w-0">

        {/* Mobile menu */}
        <button
          type="button"
          onClick={() => setMobileOpen(!mobileOpen)}
          className="
            md:hidden
            flex items-center justify-center
            w-10 h-10
            rounded-xl
            bg-white/10
            border border-white/10
            hover:bg-white/20
            active:scale-95
            transition-all
          "
          aria-label="Toggle navigation menu"
        >
          <Menu size={24} strokeWidth={2.2} />
        </button>

        {/* Brand */}
        <div className="flex items-center gap-2 min-w-0">
          <div
            className="
              hidden sm:flex
              items-center justify-center
              w-9 h-9
              rounded-xl
              bg-white/15
              border border-white/20
              shadow-sm
            "
          >
            <Zap size={19} fill="currentColor" />
          </div>

          <div className="min-w-0">
            <h1 className="text-base sm:text-xl font-bold tracking-wide truncate">
              🏆 Lilymac ✨ Predictions Hub
            </h1>

            <p className="hidden sm:block text-[9px] uppercase tracking-[0.2em] text-white/65 mt-0.5">
              Smart Football Intelligence
            </p>
          </div>
        </div>
      </div>

      {/* Desktop right side */}
      <div className="hidden md:flex items-center gap-3">

        {/* Online indicator */}
        <div
          className="
            flex items-center gap-2
            px-3 py-2
            rounded-xl
            bg-white/10
            border border-white/10
            backdrop-blur-sm
          "
        >
          <span className="relative flex w-2 h-2">
            <span className="absolute inline-flex w-full h-full rounded-full bg-emerald-300 animate-ping opacity-60" />
            <span className="relative inline-flex w-2 h-2 rounded-full bg-emerald-300" />
          </span>

          <span className="text-[10px] uppercase tracking-wider font-medium text-white/80">
            Live
          </span>
        </div>

        <span className="text-xs font-medium text-white/75">
          Smart Predictions • Better Wins
        </span>
      </div>
    </header>
  );
}
