// src/components/Sidebar.jsx
import React, { useState, useMemo } from "react";
import { NavLink } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard, BarChart2, Trophy, Clock, GitBranch,
  Layers, Target, TrendingUp,
  ChevronLeft, ChevronRight, ChevronDown
} from "lucide-react";

const SIDEBAR_WIDTH = { expanded: 260, collapsed: 80 };

export default function Sidebar({ mobileOpen, setMobileOpen, initialCollapsed = false, isDesktop }) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [expandedSections, setExpandedSections] = useState({ Predictions: true });

  const toggleSection = (title) => {
    setExpandedSections((prev) => ({ ...prev, [title]: !prev[title] }));
  };

  const handleLinkClick = () => {
    if (!isDesktop) setMobileOpen(false);
  };

  const menuSections = useMemo(
    () => [
      {
        title: "Dashboard",
        icon: <LayoutDashboard size={18} />,
        items: [
          { name: "Dashboard", path: "/", icon: <LayoutDashboard size={16} /> },
        ],
      },
      {
        title: "Predictions",
        icon: <BarChart2 size={18} />,
        items: [
          { name: "All Predictions", path: "/predictions", icon: <BarChart2 size={16} /> },
          { name: "Grouped", path: "/predictions/grouped", icon: <Layers size={16} /> },
          { name: "Accumulator", path: "/tips/accumulator", icon: <Target size={16} /> },
          { name: "Value Tips", path: "/tips/value", icon: <TrendingUp size={16} /> },
        ],
      },
      {
        title: "Matches",
        icon: <Clock size={18} />,
        items: [
          { name: "Upcoming", path: "/matches/upcoming", icon: <Clock size={16} /> },
          { name: "Results", path: "/results", icon: <Trophy size={16} /> },
          { name: "H2H", path: "/h2h", icon: <GitBranch size={16} /> },
        ],
      },
    ],
    []
  );

  return (
    <>
      <AnimatePresence>
        {mobileOpen && !isDesktop && (
          <motion.div
            className="fixed inset-0 bg-black/40 z-50"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setMobileOpen(false)}
          />
        )}
      </AnimatePresence>

      <motion.aside
        animate={{
          x: isDesktop ? 0 : mobileOpen ? 0 : -300,
          width: collapsed ? SIDEBAR_WIDTH.collapsed : SIDEBAR_WIDTH.expanded,
        }}
        className={`${isDesktop ? "relative h-screen" : "fixed top-0 left-0 h-full z-50"} flex flex-col shadow-2xl text-white`}
        style={{ background: "linear-gradient(135deg, #7c3aed 0%, #ec4899 100%)" }}
      >
        <div className="relative flex flex-col h-full p-3 overflow-y-auto">
          {menuSections.map((section) => (
            <div key={section.title} className="mb-2 group">
              {collapsed ? (
                <div className="relative flex justify-center p-3 hover:bg-white/10 rounded-lg cursor-pointer">
                  {section.icon}
                  <span className="absolute left-full ml-2 px-2 py-1 rounded-md bg-black/80 text-white text-xs opacity-0 group-hover:opacity-100 whitespace-nowrap pointer-events-none transition-opacity">
                    {section.title}
                  </span>
                </div>
              ) : (
                <>
                  <button
                    onClick={() => toggleSection(section.title)}
                    className="flex items-center justify-between w-full px-3 py-2 rounded-lg hover:bg-white/10 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      {section.icon}
                      <span className="font-semibold">{section.title}</span>
                    </div>

                    {section.items.length > 1 && (
                      <ChevronDown
                        size={14}
                        className={`transition-transform ${
                          expandedSections[section.title] ? "rotate-180" : ""
                        }`}
                      />
                    )}
                  </button>

                  <AnimatePresence>
                    {expandedSections[section.title] && section.items.length > 0 && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="overflow-hidden ml-4 mt-1 space-y-1"
                      >
                        {section.items.map((item) => (
                          <motion.div key={item.path} whileHover={{ scale: 1.03 }} transition={{ duration: 0.15 }}>
                            <NavLink
                              to={item.path}
                              onClick={handleLinkClick}
                              className={({ isActive }) =>
                                `flex items-center gap-3 px-4 py-2 rounded-lg text-sm transition-all ${
                                  isActive
                                    ? "bg-white/20 font-medium"
                                    : "hover:bg-white/5 opacity-80 hover:opacity-100"
                                }`
                              }
                            >
                              {item.icon}
                              <span>{item.name}</span>
                            </NavLink>
                          </motion.div>
                        ))}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </>
              )}
            </div>
          ))}

          {isDesktop && (
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="mt-auto p-2 rounded-md hover:bg-white/20 self-center"
            >
              {collapsed ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}
            </button>
          )}

          <div className="absolute bottom-0 left-0 w-full h-8 pointer-events-none bg-gradient-to-t from-black/40 to-transparent" />
        </div>
      </motion.aside>
    </>
  );
}
