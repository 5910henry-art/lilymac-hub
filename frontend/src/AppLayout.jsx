// src/AppLayout.jsx
import React, { useState, useEffect, useContext } from "react";
import { motion } from "framer-motion";
import { Outlet } from "react-router-dom";
import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import BottomNav from "./components/BottomNav";
import { TipsContext } from "./contexts/TipsContext";

export default function AppLayout({
  role = "user",
  user = { name: "Khisa Henry", initials: "KH" },
}) {
  const [dark, setDark] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isDesktop, setIsDesktop] = useState(window.innerWidth >= 768);

  const tipsContext = useContext(TipsContext) || {};
  const topCount = tipsContext.topCount || 0;

  useEffect(() => {
    const handleResize = () => {
      const desktop = window.innerWidth >= 768;
      setIsDesktop(desktop);
      if (desktop) setMobileOpen(false);
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const toggleDark = () => setDark((prev) => !prev);

  return (
    <div
      className={`h-screen flex overflow-hidden ${
        dark ? "bg-gray-900 text-white" : "bg-gray-50 text-gray-900"
      }`}
    >
      {/* Sidebar */}
      <Sidebar
        dark={dark}
        toggleDark={toggleDark}
        mobileOpen={mobileOpen}
        setMobileOpen={setMobileOpen}
        initialCollapsed={false}
        role={role}
        user={user}
        isDesktop={isDesktop}
      />

      {/* Main layout */}
      <div className="flex-1 flex flex-col h-screen overflow-hidden relative">
        {/* Header */}
        <Header mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} />

        {/* Page Content */}
        <main className="flex-1 overflow-hidden pt-16 pb-20">
          <div className="h-full overflow-y-auto">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.25 }}
              className="w-full px-4 sm:px-6 lg:px-8 max-w-screen-xl mx-auto"
            >
              {/* THIS IS WHAT RENDERS ROUTES */}
              <Outlet />
            </motion.div>
          </div>
        </main>

        {/* Bottom Navigation */}
        <footer className="md:hidden flex-shrink-0">
          <BottomNav topCount={topCount} />
        </footer>
      </div>
    </div>
  );
}
