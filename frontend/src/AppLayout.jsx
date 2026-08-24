// src/AppLayout.jsx
import React, { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { Outlet } from "react-router-dom";

import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import BottomNav from "./components/BottomNav";

export default function AppLayout({
  role = "user",
  user = { name: "Khisa Henry", initials: "KH" },
}) {
  const [dark, setDark] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Reference to the actual scrolling page container
  const scrollContainerRef = useRef(null);

  const [isDesktop, setIsDesktop] = useState(
    window.innerWidth >= 768
  );

  useEffect(() => {
    const handleResize = () => {
      const desktop = window.innerWidth >= 768;

      setIsDesktop(desktop);

      // Close mobile sidebar when switching to desktop
      if (desktop) {
        setMobileOpen(false);
      }
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  const toggleDark = () => {
    setDark((prev) => !prev);
  };

  return (
    <div
      className={`h-screen flex overflow-hidden ${
        dark
          ? "bg-gray-900 text-white"
          : "bg-gray-50 text-gray-900"
      }`}
    >
      {/* =====================================================
          SIDEBAR
      ====================================================== */}
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

      {/* =====================================================
          MAIN APPLICATION AREA
      ====================================================== */}
      <div className="flex-1 flex flex-col h-screen min-h-0 overflow-hidden relative">

        {/* =================================================
            HEADER
        ================================================== */}
        <Header
          mobileOpen={mobileOpen}
          setMobileOpen={setMobileOpen}
        />

        {/* =================================================
            PAGE CONTENT
        ================================================== */}
        <main className="flex-1 min-h-0 overflow-hidden pt-16 pb-20 md:pb-24">
          <div
            ref={scrollContainerRef}
            className="h-full overflow-y-auto"
          >
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.25 }}
              className="
                w-full
                px-4
                sm:px-6
                lg:px-8
                max-w-screen-xl
                mx-auto
              "
            >
              {/* Routes render here */}
              <Outlet />
            </motion.div>
          </div>
        </main>

        {/* =================================================
            RESPONSIVE BOTTOM NAVIGATION
        ================================================== */}
        <footer>
          <BottomNav
            scrollContainerRef={scrollContainerRef}
          />
        </footer>

      </div>
    </div>
  );
}
