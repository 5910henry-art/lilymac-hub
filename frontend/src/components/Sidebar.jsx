// src/components/Sidebar.jsx

import React, { useState, useMemo, useContext } from "react";
import { NavLink } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { TipsContext } from "../contexts/TipsContext";
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
  X,
  Flame,
  Crown,
  User,
} from "lucide-react";

const SIDEBAR_WIDTH = {
  expanded: 270,
  collapsed: 82,
};

const MOBILE_WIDTH = 290;

export default function Sidebar({
  mobileOpen,
  setMobileOpen,
  initialCollapsed = false,
  isDesktop,
}) {
  const { topCount } = useContext(TipsContext);

  const isAdminAuthenticated = Boolean(
    localStorage.getItem("admin_token")
  );

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
      {
        type: "link",
        label: "OVERVIEW",
        title: "Dashboard",
        path: "/",
        icon: <LayoutDashboard size={19} strokeWidth={1.8} />,
      },

      {
        type: "actionGroup",
        label: "QUICK ACTIONS",
        title: "Quick Actions",
        items: [
          {
            name: "Bets",
            path: "/bookmarks",
            icon: (
              <span className="text-[20px] leading-none">
                💵💰
              </span>
            ),
          },
          {
            name: "🔥 Tips",
            path: "/tips/daily",
            icon: <Flame size={18} strokeWidth={1.8} />,
            badge: topCount,
          },
          {
            name: "Membership",
            path: "/vip",
            icon: <Crown size={18} strokeWidth={1.8} />,
            vip: true,
          },
          {
            name: "Admin",
            path: "/admin",
            icon: <User size={18} strokeWidth={1.8} />,
          },
        ],
      },

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

      {
        type: "link",
        label: "FOOTBALL",
        title: "Teams",
        path: "/teams",
        icon: <Shield size={19} strokeWidth={1.8} />,
      },

,
    ],
    []
  );

  return (
    <>
      {/* =====================================================
          MOBILE BACKDROP
      ====================================================== */}
      <AnimatePresence>
        {mobileOpen && !isDesktop && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={() => setMobileOpen(false)}
            className="
              fixed
              inset-0
              z-[80]
              bg-black/55
              backdrop-blur-[2px]
            "
            aria-hidden="true"
          />
        )}
      </AnimatePresence>

      {/* =====================================================
          SIDEBAR / MOBILE DRAWER
      ====================================================== */}
      <motion.aside
        initial={false}
        animate={{
          x: isDesktop ? 0 : mobileOpen ? 0 : -MOBILE_WIDTH - 30,
          width: isDesktop
            ? collapsed
              ? SIDEBAR_WIDTH.collapsed
              : SIDEBAR_WIDTH.expanded
            : MOBILE_WIDTH,
        }}
        transition={{
          type: "spring",
          stiffness: 320,
          damping: 32,
          mass: 0.8,
        }}
        className={`
          flex
          flex-col
          text-white

          ${
            isDesktop
              ? "relative h-screen shrink-0"
              : "fixed left-0 top-16 bottom-0 z-[90] max-w-[86vw]"
          }
        `}
        style={{
          background:
            "linear-gradient(160deg, #07152F 0%, #123B8F 42%, #2563EB 67%, #C1121F 100%)",

          borderRight:
            "1px solid rgba(255,255,255,0.10)",

          boxShadow: isDesktop
            ? "8px 0 40px rgba(0,0,0,0.30)"
            : "10px 0 45px rgba(0,0,0,0.40)",
        }}
      >
        <div className="flex flex-col h-full min-h-0">
          {/* =================================================
              BRAND HEADER
          ================================================== */}
          <div
            className={`
              flex
              items-center
              shrink-0
              ${
                collapsed && isDesktop
                  ? "justify-center"
                  : "justify-between"
              }
              px-5
              py-4
              border-b border-white/10
            `}
          >
            {collapsed && isDesktop ? (
              <div
                className="
                  flex
                  items-center
                  justify-center
                  w-11
                  h-11
                  rounded-xl
                "
                style={{
                  background:
                    "linear-gradient(135deg, #2563EB, #DC2626)",
                  boxShadow:
                    "0 0 25px rgba(37,99,235,0.45)",
                }}
              >
                <Zap size={21} fill="currentColor" />
              </div>
            ) : (
              <div className="flex items-center gap-3 min-w-0">
                <div
                  className="
                    flex
                    items-center
                    justify-center
                    w-10
                    h-10
                    shrink-0
                    rounded-xl
                  "
                  style={{
                    background:
                      "linear-gradient(135deg, #2563EB, #DC2626)",
                    boxShadow:
                      "0 0 25px rgba(37,99,235,0.45)",
                  }}
                >
                  <Zap size={21} fill="currentColor" />
                </div>

                <div className="min-w-0">
                  <h1 className="text-base font-bold tracking-wide">
                    LILYMAC
                  </h1>

                  <p className="text-[10px] uppercase tracking-[0.18em] text-white/60 whitespace-nowrap">
                    Football Intelligence
                  </p>
                </div>
              </div>
            )}

            {/* Mobile close button */}
            {!isDesktop && (
              <button
                type="button"
                onClick={() => setMobileOpen(false)}
                className="
                  flex
                  items-center
                  justify-center
                  w-10
                  h-10
                  shrink-0
                  rounded-xl
                  text-white/75
                  hover:text-white
                  hover:bg-white/10
                  active:bg-white/20
                  transition
                "
                aria-label="Close menu"
              >
                <X size={21} />
              </button>
            )}
          </div>

          {/* =================================================
              SYSTEM STATUS
          ================================================== */}
          {!collapsed && (
            <div className="px-4 pt-4 pb-3 shrink-0">
              <div
                className="
                  flex
                  items-center
                  gap-2
                  px-3
                  py-2
                  rounded-lg
                "
                style={{
                  background:
                    "rgba(255,255,255,0.08)",
                  border:
                    "1px solid rgba(255,255,255,0.12)",
                  backdropFilter: "blur(10px)",
                }}
              >
                <span className="relative flex h-2 w-2 shrink-0">
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
          <div
            className="
              flex-1
              min-h-0
              px-3
              overflow-y-auto
              overflow-x-hidden
              overscroll-contain
              scrollbar-thin
            "
          >
            {menuSections.map((section) => (
              <div
                key={section.title}
                className="mb-5"
              >
                {/* Section label */}
                {!collapsed && (
                  <div className="px-3 mb-2">
                    <span className="text-[9px] font-semibold tracking-[0.2em] text-white/45">
                      {section.label}
                    </span>
                  </div>
                )}

                {/* =================================================
                    DIRECT LINK
                ================================================== */}
                {section.type === "link" && (
                  <NavLink
                    to={section.path}
                    end={section.path === "/"}
                    onClick={handleLinkClick}
                    className="block"
                  >
                    {({ isActive }) => (
                      <motion.div
                        whileHover={{
                          x: isDesktop ? 3 : 2,
                        }}
                        transition={{ duration: 0.15 }}
                        className={`
                          relative
                          flex
                          items-center
                          ${
                            collapsed && isDesktop
                              ? "justify-center"
                              : "gap-3"
                          }
                          px-3
                          py-3
                          rounded-xl
                          text-sm
                          transition-all

                          ${
                            isActive
                              ? "bg-white/20 text-white shadow-lg"
                              : "text-white/75 hover:text-white hover:bg-white/10"
                          }
                        `}
                      >
                        {isActive && (
                          <motion.div
                            layoutId={`active-${section.title}`}
                            className="
                              absolute
                              left-0
                              top-1/2
                              -translate-y-1/2
                              w-1
                              h-7
                              rounded-full
                              bg-white
                            "
                          />
                        )}

                        <span
                          className={
                            isActive
                              ? "text-white"
                              : "text-white/75"
                          }
                        >
                          {section.icon}
                        </span>

                        {(!collapsed || !isDesktop) && (
                          <span className="font-medium">
                            {section.title}
                          </span>
                        )}

                        {isActive &&
                          !collapsed && (
                            <span className="ml-auto w-1.5 h-1.5 rounded-full bg-white shadow-[0_0_8px_rgba(255,255,255,0.9)]" />
                          )}
                      </motion.div>
                    )}
                  </NavLink>
                )}

                {/* =================================================
                    QUICK ACTIONS
                ================================================== */}
                {section.type === "actionGroup" && (
                  <div className="space-y-1">
                    {section.items
                      .filter(
                        (item) =>
                          item.name !== "Admin" || isAdminAuthenticated
                      )
                      .map((item) => (
                      <NavLink
                        key={item.path}
                        to={item.path}
                        onClick={handleLinkClick}
                        className="block"
                      >
                        {({ isActive }) => (
                          <motion.div
                            whileHover={{
                              x: isDesktop ? 3 : 2,
                            }}
                            transition={{ duration: 0.15 }}
                            className={`
                              relative
                              flex
                              items-center
                              ${
                                collapsed && isDesktop
                                  ? "justify-center"
                                  : "gap-3"
                              }
                              px-3
                              py-3
                              rounded-xl
                              text-sm
                              transition-all

                              ${
                                isActive
                                  ? "bg-white/20 text-white shadow-lg"
                                  : "text-white/75 hover:text-white hover:bg-white/10"
                              }
                            `}
                          >
                            {isActive && (
                              <motion.div
                                className="
                                  absolute
                                  left-0
                                  top-1/2
                                  -translate-y-1/2
                                  w-1
                                  h-7
                                  rounded-full
                                  bg-white
                                "
                              />
                            )}

                            <span
                              className={
                                isActive
                                  ? "text-white"
                                  : "text-white/75"
                              }
                            >
                              {item.icon}
                            </span>

                            {(!collapsed || !isDesktop) && (
                              <span className="font-medium">
                                {item.name}
                              </span>
                            )}

                            {item.badge > 0 && (
                              <span
                                className="
                                  ml-auto
                                  flex
                                  items-center
                                  justify-center
                                  min-w-5
                                  h-5
                                  px-1
                                  rounded-full
                                  bg-red-600
                                  text-white
                                  text-[10px]
                                  font-bold
                                  shadow-lg
                                  border-2
                                  border-white
                                "
                              >
                                {item.badge}
                              </span>
                            )}

                            {item.vip && !collapsed && (
                              <motion.span
                                className="
                                  ml-auto
                                  flex
                                  items-center
                                  justify-center
                                  min-w-6
                                  h-6
                                  px-1
                                  rounded-full
                                  bg-amber-400
                                  text-black
                                  text-[9px]
                                  font-extrabold
                                  shadow-md
                                  border-2
                                  border-white
                                "
                                animate={{
                                  scale: [1, 1.08, 1],
                                }}
                                transition={{
                                  duration: 1.8,
                                  repeat: Infinity,
                                }}
                              >
                                VIP
                              </motion.span>
                            )}

                            {isActive && !item.badge && !item.vip && !collapsed && (
                              <span className="ml-auto w-1.5 h-1.5 rounded-full bg-white shadow-[0_0_8px_rgba(255,255,255,0.9)]" />
                            )}
                          </motion.div>
                        )}
                      </NavLink>
                    ))}
                  </div>
                )}

                {/* =================================================
                    COLLAPSIBLE SECTION
                ================================================== */}
                {section.type === "section" && (
                  <>
                    {/* Desktop collapsed */}
                    {collapsed && isDesktop ? (
                      <div className="relative group">
                        <button
                          type="button"
                          onClick={() =>
                            toggleSection(section.title)
                          }
                          className="
                            flex
                            items-center
                            justify-center
                            w-full
                            px-3
                            py-3
                            rounded-xl
                            text-white/70
                            hover:text-white
                            hover:bg-white/10
                            transition-all
                          "
                          aria-label={section.title}
                        >
                          {section.icon}
                        </button>

                        <div
                          className="
                            absolute
                            left-full
                            top-1/2
                            -translate-y-1/2
                            ml-3
                            px-3
                            py-1.5
                            rounded-lg
                            bg-gray-900/95
                            border
                            border-white/10
                            text-xs
                            whitespace-nowrap
                            opacity-0
                            invisible
                            group-hover:opacity-100
                            group-hover:visible
                            transition-all
                            z-[100]
                            shadow-xl
                          "
                        >
                          {section.title}
                        </div>
                      </div>
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={() =>
                            toggleSection(section.title)
                          }
                          className="
                            flex
                            items-center
                            justify-between
                            w-full
                            px-3
                            py-2.5
                            rounded-xl
                            text-white/90
                            hover:text-white
                            hover:bg-white/10
                            transition-all
                          "
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
                            className={`
                              text-white/50
                              transition-transform
                              ${
                                expandedSections[
                                  section.title
                                ]
                                  ? "rotate-180"
                                  : ""
                              }
                            `}
                          />
                        </button>

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
                                      className="block"
                                    >
                                      {({
                                        isActive,
                                      }) => (
                                        <motion.div
                                          whileHover={{
                                            x: 2,
                                          }}
                                          transition={{
                                            duration: 0.15,
                                          }}
                                          className={`
                                            relative
                                            flex
                                            items-center
                                            gap-3
                                            px-3
                                            py-2.5
                                            rounded-lg
                                            text-sm
                                            transition-all

                                            ${
                                              isActive
                                                ? "text-white bg-white/20 shadow-md"
                                                : "text-white/60 hover:text-white hover:bg-white/10"
                                            }
                                          `}
                                        >
                                          {isActive && (
                                            <motion.div
                                              layoutId={`child-${section.title}`}
                                              className="
                                                absolute
                                                left-0
                                                top-1/2
                                                -translate-y-1/2
                                                w-1
                                                h-6
                                                rounded-full
                                                bg-white
                                              "
                                            />
                                          )}

                                          <span
                                            className={
                                              isActive
                                                ? "text-white"
                                                : "text-white/60"
                                            }
                                          >
                                            {item.icon}
                                          </span>

                                          <span>
                                            {item.name}
                                          </span>

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
              DESKTOP COLLAPSE BUTTON
          ================================================== */}
          {isDesktop && (
            <div className="px-3 pb-4 pt-2 shrink-0">
              <button
                type="button"
                onClick={() =>
                  setCollapsed(!collapsed)
                }
                className={`
                  flex
                  items-center
                  ${
                    collapsed
                      ? "justify-center"
                      : "justify-between"
                  }
                  w-full
                  px-3
                  py-2.5
                  rounded-xl
                  text-white/60
                  hover:text-white
                  hover:bg-white/10
                  transition-all
                `}
                aria-label={
                  collapsed
                    ? "Expand menu"
                    : "Collapse menu"
                }
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
