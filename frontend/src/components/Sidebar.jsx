// src/components/Sidebar.jsx
import React, { useState, useMemo } from "react";
import { NavLink } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard,
  BarChart3,
  Trophy,
  Clock3,
  GitBranch,
  Layers3,
  Target,
  TrendingUp,
  Shield,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Activity,
  Zap,
} from "lucide-react";

const SIDEBAR_WIDTH = {
  expanded: 270,
  collapsed: 82,
};

export default function Sidebar({
  mobileOpen,
  setMobileOpen,
  initialCollapsed = false,
  isDesktop,
}) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);

  const [expandedSections, setExpandedSections] = useState({
    Predictions: true,
    "Match Center": true,
  });

  const toggleSection = (title) => {
    setExpandedSections((prev) => ({
      ...prev,
      [title]: !prev[title],
    }));
  };

  const handleLinkClick = () => {
    if (!isDesktop) {
      setMobileOpen(false);
    }
  };

  const menuSections = useMemo(
    () => [
      // =========================
      // DASHBOARD
      // =========================
      {
        type: "link",
        label: "OVERVIEW",
        title: "Dashboard",
        path: "/",
        icon: <LayoutDashboard size={19} strokeWidth={1.8} />,
      },

      // =========================
      // PREDICTIONS
      // =========================
      {
        type: "section",
        label: "PREDICTIONS",
        title: "Predictions",
        icon: <BarChart3 size={19} strokeWidth={1.8} />,
        items: [
          {
            name: "All Predictions",
            path: "/predictions",
            icon: <BarChart3 size={17} strokeWidth={1.8} />,
          },
          {
            name: "Grouped",
            path: "/predictions/grouped",
            icon: <Layers3 size={17} strokeWidth={1.8} />,
          },
          {
            name: "Accumulator",
            path: "/tips/accumulator",
            icon: <Target size={17} strokeWidth={1.8} />,
          },
          {
            name: "Value Tips",
            path: "/tips/value",
            icon: <TrendingUp size={17} strokeWidth={1.8} />,
          },
        ],
      },

      // =========================
      // TEAMS
      // =========================
      {
        type: "link",
        label: "FOOTBALL",
        title: "Teams",
        path: "/teams",
        icon: <Shield size={19} strokeWidth={1.8} />,
      },

      // =========================
      // MATCH CENTER
      // =========================
      {
        type: "section",
        label: "MATCH CENTER",
        title: "Match Center",
        icon: <Activity size={19} strokeWidth={1.8} />,
        items: [
          {
            name: "Upcoming",
            path: "/matches/upcoming",
            icon: <Clock3 size={17} strokeWidth={1.8} />,
          },
          {
            name: "Results",
            path: "/results",
            icon: <Trophy size={17} strokeWidth={1.8} />,
          },
          {
            name: "H2H",
            path: "/h2h",
            icon: <GitBranch size={17} strokeWidth={1.8} />,
          },
        ],
      },
    ],
    []
  );

  return (
    <>
      {/* =====================================================
          MOBILE OVERLAY
      ====================================================== */}
      <AnimatePresence>
        {mobileOpen && !isDesktop && (
          <motion.div
            className="fixed inset-0 z-40 bg-black/55 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setMobileOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* =====================================================
          SIDEBAR
      ====================================================== */}
      <motion.aside
        animate={{
          x: isDesktop ? 0 : mobileOpen ? 0 : -320,
          width: collapsed
            ? SIDEBAR_WIDTH.collapsed
            : SIDEBAR_WIDTH.expanded,
        }}
        transition={{
          type: "spring",
          stiffness: 280,
          damping: 30,
        }}
        className={`${
          isDesktop
            ? "relative h-screen"
            : "fixed top-0 left-0 h-full z-50"
        } flex flex-col overflow-hidden text-white`}
        style={{
          /*
           * PREMIUM RED → BLUE GRADIENT
           */
          background:
            "linear-gradient(160deg, #07152F 0%, #123B8F 42%, #2563EB 67%, #C1121F 100%)",

          borderRight: "1px solid rgba(255,255,255,0.10)",

          boxShadow:
            "8px 0 40px rgba(0,0,0,0.30)",
        }}
      >
        <div className="flex flex-col h-full">

          {/* =================================================
              BRAND HEADER
          ================================================== */}
          <div
            className={`flex items-center ${
              collapsed
                ? "justify-center"
                : "justify-start"
            } px-5 py-5`}
          >
            {collapsed ? (
              <div
                className="flex items-center justify-center w-11 h-11 rounded-xl"
                style={{
                  background:
                    "linear-gradient(135deg, #2563EB, #DC2626)",
                  boxShadow:
                    "0 0 25px rgba(37,99,235,0.45)",
                }}
              >
                <Zap
                  size={21}
                  fill="currentColor"
                />
              </div>
            ) : (
              <div className="flex items-center gap-3">

                {/* Logo */}
                <div
                  className="flex items-center justify-center w-10 h-10 rounded-xl"
                  style={{
                    background:
                      "linear-gradient(135deg, #2563EB, #DC2626)",
                    boxShadow:
                      "0 0 25px rgba(37,99,235,0.45)",
                  }}
                >
                  <Zap
                    size={21}
                    fill="currentColor"
                  />
                </div>

                {/* Brand text */}
                <div>
                  <h1 className="text-base font-bold tracking-wide">
                    LILYMAC
                  </h1>

                  <p className="text-[10px] uppercase tracking-[0.18em] text-white/60">
                    Football Intelligence
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* =================================================
              SYSTEM STATUS
          ================================================== */}
          {!collapsed && (
            <div className="px-4 mb-5">
              <div
                className="flex items-center gap-2 px-3 py-2 rounded-lg"
                style={{
                  background:
                    "rgba(255,255,255,0.08)",
                  border:
                    "1px solid rgba(255,255,255,0.12)",
                  backdropFilter: "blur(10px)",
                }}
              >
                {/* Status indicator */}
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-300 opacity-60" />

                  <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-300" />
                </span>

                <span className="text-[10px] uppercase tracking-wider text-white/70">
                  System Online
                </span>
              </div>
            </div>
          )}

          {/* =================================================
              NAVIGATION
          ================================================== */}
          <div className="flex-1 px-3 overflow-y-auto">

            {menuSections.map((section) => (
              <div
                key={section.title}
                className="mb-5"
              >

                {/* ==========================================
                    SECTION LABEL
                =========================================== */}
                {!collapsed && (
                  <div className="px-3 mb-2">
                    <span className="text-[9px] font-semibold tracking-[0.2em] text-white/45">
                      {section.label}
                    </span>
                  </div>
                )}

                {/* ==========================================
                    DIRECT LINK
                =========================================== */}
                {section.type === "link" && (
                  <NavLink
                    to={section.path}
                    end={section.path === "/"}
                    onClick={handleLinkClick}
                  >
                    {({ isActive }) => (
                      <motion.div
                        whileHover={{
                          x: 3,
                        }}
                        transition={{
                          duration: 0.15,
                        }}
                        className={`relative flex items-center ${
                          collapsed
                            ? "justify-center"
                            : "gap-3"
                        } px-3 py-3 rounded-xl text-sm transition-all ${
                          isActive
                            ? "bg-white/20 text-white shadow-lg"
                            : "text-white/75 hover:text-white hover:bg-white/10"
                        }`}
                      >

                        {/* Active indicator */}
                        {isActive && (
                          <motion.div
                            layoutId="activeDirectIndicator"
                            className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-7 rounded-full bg-white"
                          />
                        )}

                        {/* Icon */}
                        <span
                          className={
                            isActive
                              ? "text-white"
                              : "text-white/75"
                          }
                        >
                          {section.icon}
                        </span>

                        {/* Text */}
                        {!collapsed && (
                          <span className="font-medium">
                            {section.title}
                          </span>
                        )}

                        {/* Active dot */}
                        {isActive &&
                          !collapsed && (
                            <span className="ml-auto w-1.5 h-1.5 rounded-full bg-white shadow-[0_0_8px_rgba(255,255,255,0.9)]" />
                          )}
                      </motion.div>
                    )}
                  </NavLink>
                )}

                {/* ==========================================
                    COLLAPSIBLE SECTION
                =========================================== */}
                {section.type === "section" && (
                  <>
                    {/* ================================
                        COLLAPSED MODE
                    ================================= */}
                    {collapsed ? (
                      <div className="relative group">

                        <button
                          onClick={() =>
                            toggleSection(
                              section.title
                            )
                          }
                          className="flex items-center justify-center w-full px-3 py-3 rounded-xl text-white/70 hover:text-white hover:bg-white/10 transition-all"
                        >
                          {section.icon}
                        </button>

                        {/* Tooltip */}
                        <div className="absolute left-full top-1/2 -translate-y-1/2 ml-3 px-3 py-1.5 rounded-lg bg-gray-900/95 border border-white/10 text-xs whitespace-nowrap opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 shadow-xl">
                          {section.title}
                        </div>
                      </div>
                    ) : (
                      <>
                        {/* Section header */}
                        <button
                          onClick={() =>
                            toggleSection(
                              section.title
                            )
                          }
                          className="flex items-center justify-between w-full px-3 py-2.5 rounded-xl text-white/90 hover:text-white hover:bg-white/10 transition-all"
                        >
                          <div className="flex items-center gap-3">

                            <span className="text-white/90">
                              {section.icon}
                            </span>

                            <span className="text-sm font-medium">
                              {section.title}
                            </span>
                          </div>

                          <ChevronDown
                            size={14}
                            className={`text-white/50 transition-transform ${
                              expandedSections[
                                section.title
                              ]
                                ? "rotate-180"
                                : ""
                            }`}
                          />
                        </button>

                        {/* Child items */}
                        <AnimatePresence initial={false}>
                          {expandedSections[
                            section.title
                          ] && (
                            <motion.div
                              initial={{
                                height: 0,
                                opacity: 0,
                              }}
                              animate={{
                                height: "auto",
                                opacity: 1,
                              }}
                              exit={{
                                height: 0,
                                opacity: 0,
                              }}
                              transition={{
                                duration: 0.2,
                              }}
                              className="overflow-hidden"
                            >
                              <div className="mt-1 ml-3 pl-3 border-l border-white/15 space-y-1">

                                {section.items.map(
                                  (item) => (
                                    <NavLink
                                      key={item.path}
                                      to={item.path}
                                      onClick={
                                        handleLinkClick
                                      }
                                    >
                                      {({
                                        isActive,
                                      }) => (
                                        <motion.div
                                          whileHover={{
                                            x: 3,
                                          }}
                                          transition={{
                                            duration: 0.15,
                                          }}
                                          className={`relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all ${
                                            isActive
                                              ? "text-white bg-white/20 shadow-md"
                                              : "text-white/60 hover:text-white hover:bg-white/10"
                                          }`}
                                        >

                                          {/* Active line */}
                                          {isActive && (
                                            <motion.div
                                              layoutId="activeChildIndicator"
                                              className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 rounded-full bg-white"
                                            />
                                          )}

                                          {/* Icon */}
                                          <span
                                            className={
                                              isActive
                                                ? "text-white"
                                                : "text-white/60"
                                            }
                                          >
                                            {item.icon}
                                          </span>

                                          {/* Name */}
                                          <span>
                                            {item.name}
                                          </span>

                                          {/* Active dot */}
                                          {isActive && (
                                            <span className="ml-auto w-1.5 h-1.5 rounded-full bg-white shadow-[0_0_8px_rgba(255,255,255,0.9)]" />
                                          )}
                                        </motion.div>
                                      )}
                                    </NavLink>
                                  )
                                )}
                              </div>
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>

          {/* =================================================
              COLLAPSE BUTTON
          ================================================== */}
          {isDesktop && (
            <div className="px-3 pb-4">

              <button
                onClick={() =>
                  setCollapsed(!collapsed)
                }
                className={`flex items-center ${
                  collapsed
                    ? "justify-center"
                    : "justify-between"
                } w-full px-3 py-2.5 rounded-xl text-white/60 hover:text-white hover:bg-white/10 transition-all`}
              >

                {!collapsed && (
                  <span className="text-[10px] uppercase tracking-wider">
                    Collapse Menu
                  </span>
                )}

                {collapsed ? (
                  <ChevronRight size={18} />
                ) : (
                  <ChevronLeft size={18} />
                )}
              </button>

            </div>
          )}
        </div>
      </motion.aside>
    </>
  );
}
