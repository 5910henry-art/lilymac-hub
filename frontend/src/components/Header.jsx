// src/components/Header.jsx
import React from "react";
import { Menu } from "lucide-react";

export default function Header({ mobileOpen, setMobileOpen }) {
  return (
    <header
      className="
        fixed top-0 z-50
        w-full h-16
        flex items-center justify-between
        px-6 sm:px-8
        bg-gradient-to-r from-blue-500 via-purple-500 to-red-500
        bg-[length:200%_200%] animate-gradient-x
        shadow-md text-white
        transition-all duration-300
      "
    >
      <div className="flex items-center gap-3">
        {/* Mobile Hamburger */}
        <button
          className="md:hidden p-2 rounded-md hover:bg-white/20 transition"
          onClick={() => setMobileOpen(!mobileOpen)}
        >
          <Menu className="w-6 h-6" />
        </button>

        <h1 className="text-lg sm:text-xl font-semibold tracking-wide">
          🏆 Lilymac ✨ Predictions Hub
        </h1>
      </div>

      {/* Right side placeholder (future profile, notifications, etc.) */}
      <div className="hidden sm:block text-sm font-medium opacity-90">
        Smart Predictions • Better Wins
      </div>
    </header>
  );
}
