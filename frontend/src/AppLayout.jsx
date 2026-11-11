// src/AppLayout.jsx

import React, {
  useState,
  useEffect,
} from "react";
import { motion } from "framer-motion";
import { Outlet } from "react-router-dom";

import Header from "./components/Header";
import Sidebar from "./components/Sidebar";

export default function AppLayout({
  role = "user",
  user = {
    name: "Khisa Henry",
    initials: "KH",
  },
}) {
  const [dark, setDark] = useState(false);
  const [mobileOpen, setMobileOpen] =
    useState(false);

  const [isDesktop, setIsDesktop] =
    useState(() =>
      typeof window !== "undefined"
        ? window.innerWidth >= 768
        : false
    );

  /* =========================================================
     RESPONSIVE BREAKPOINT
  ========================================================= */
  useEffect(() => {
    const mediaQuery = window.matchMedia(
      "(min-width: 768px)"
    );

    const handleChange = (event) => {
      setIsDesktop(event.matches);

      if (event.matches) {
        setMobileOpen(false);
      }
    };

    setIsDesktop(mediaQuery.matches);

    mediaQuery.addEventListener(
      "change",
      handleChange
    );

    return () => {
      mediaQuery.removeEventListener(
        "change",
        handleChange
      );
    };
  }, []);

  /* =========================================================
     PREVENT BACKGROUND INTERACTION WHILE MOBILE DRAWER OPEN
  ========================================================= */
  useEffect(() => {
    if (!mobileOpen || isDesktop) {
      document.body.style.overflow = "";
      return;
    }

    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileOpen, isDesktop]);

  /* =========================================================
     DARK MODE
  ========================================================= */
  const toggleDark = () => {
    setDark((prev) => !prev);
  };

  return (
    <div
      className={`
        min-h-[100dvh]
        w-full
        flex
        overflow-hidden

        ${
          dark
            ? "bg-gray-900 text-white"
            : "bg-gray-50 text-gray-900"
        }
      `}
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
          MAIN APPLICATION
      ====================================================== */}
      <div
        className="
          flex-1
          min-w-0
          min-h-0

          flex
          flex-col

          h-[100dvh]

          overflow-hidden
          relative
        "
      >
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
        <main
          className="
            flex-1
            min-h-0
            overflow-y-auto
            overflow-x-hidden
            pt-16
          "
        >
      
            <motion.div
              initial={{
                opacity: 0,
                y: 4,
              }}
              animate={{
                opacity: 1,
                y: 0,
              }}
              transition={{
                duration: 0.2,
              }}
              className="
                w-full

                px-3
                sm:px-6
                lg:px-8

                max-w-screen-xl
                mx-auto
              "
            >
              <Outlet />
            </motion.div>
          
        </main>

      </div>
    </div>
  );
}
