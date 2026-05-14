// src/components/BottomNav.jsx
import React, { useContext, useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Home, Flame, Crown, User } from "lucide-react";
import { TipsContext } from "../contexts/TipsContext";
import { motion, AnimatePresence, useAnimation } from "framer-motion";

export default function BottomNav() {
  const location = useLocation();
  const { topCount } = useContext(TipsContext);
  const controls = useAnimation();

  // Slide nav on scroll
  useEffect(() => {
    let lastScrollY = window.scrollY;
    const handleScroll = () => {
      const currentScrollY = window.scrollY;
      if (currentScrollY > lastScrollY) {
        controls.start({ y: 100, transition: { type: "spring", stiffness: 300, damping: 30 } });
      } else {
        controls.start({ y: 0, transition: { type: "spring", stiffness: 300, damping: 30 } });
      }
      lastScrollY = currentScrollY;
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, [controls]);

  return (
    <motion.nav
      animate={controls}
      className="fixed bottom-0 left-0 right-0 bg-white dark:bg-gray-900
                 border-t border-gray-200 dark:border-gray-800
                 h-16 flex justify-around items-center shadow-md z-50"
      aria-label="Bottom navigation"
    >
      {/* Home → Dashboard */}
      <NavItem to="/" icon={<Home size={22} />} label="Home" />

      {/* Bookmarks → Money emoji 💵💰 */}
      <NavItem
        to="/bookmarks"
        icon={<span className="text-2xl">💵💰</span>}
        pulse
        bounce
        glow
        shimmer
        activeScale={1.5}
      />

      {/* Tips */}
      <NavItem to="/tips/daily" icon={<Flame size={22} />} label="🔥">
        <AnimatePresence>
          {topCount > 0 && (
            <motion.span
              key={`top-${topCount}`}
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0 }}
              transition={{ type: "spring", stiffness: 500, damping: 30 }}
              className="absolute -top-2 right-0 flex items-center justify-center
                         w-6 h-6 rounded-full bg-red-600 text-white text-[12px] font-bold
                         shadow-lg border-2 border-white dark:border-gray-900"
              aria-label={`${topCount} hot tips available`}
              role="status"
            >
              {topCount}
            </motion.span>
          )}
        </AnimatePresence>
      </NavItem>

      {/* VIP */}
      <NavItem to="/vip" icon={<Crown size={22} />} label="VIP">
        <motion.span
          className="absolute -top-2 right-0 flex items-center justify-center
                     w-6 h-6 rounded-full bg-amber-400 text-black text-[10px] font-extrabold
                     shadow-md border-2 border-white dark:border-gray-900"
          aria-label="VIP section"
          title="VIP"
          role="img"
          animate={{ scale: [1, 1.2, 1] }}
          transition={{ duration: 1.5, repeat: Infinity }}
        >
          VIP
        </motion.span>
      </NavItem>

      {/* Profile */}
      <NavItem to="/admin" icon={<User size={22} />} label="🔐">
        {location.pathname === "/profile" && (
          <button
            onClick={() => (window.location.href = "/admin")}
            className="absolute -top-6 right-0 w-7 h-7 rounded-full bg-red-500 text-white text-xs flex items-center justify-center shadow-md"
            title="Go to Admin"
            aria-label="Go to Admin"
          >
            A
          </button>
        )}
      </NavItem>
    </motion.nav>
  );
}

// NavItem with pulse + bounce + glow + shimmer
function NavItem({ to, icon, label, pulse, bounce, glow, shimmer, activeScale = 1.2, children }) {
  const location = useLocation();
  const isActive = location.pathname === to;

  return (
    <NavLink
      to={to}
      className={`flex flex-col items-center text-xs relative min-w-[56px] ${
        isActive ? "text-green-600" : "text-gray-500 dark:text-gray-400"
      }`}
    >
      <motion.div
        animate={
          isActive
            ? {
                scale: activeScale,
                filter: glow ? "drop-shadow(0 0 10px gold)" : undefined,
                textShadow: shimmer ? "0 0 10px gold, 0 0 20px gold" : undefined,
              }
            : pulse
            ? {
                scale: [1, 1.15, 1],
                y: bounce ? [0, -3, 3, 0] : 0,
                rotate: bounce ? [0, 5, -5, 0] : 0,
                filter: glow ? "drop-shadow(0 0 10px gold)" : undefined,
                textShadow: shimmer
                  ? ["0 0 5px gold", "0 0 15px gold", "0 0 5px gold"]
                  : undefined,
              }
            : {}
        }
        transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
      >
        {icon}
      </motion.div>
      {label && <span className="mt-1 select-none">{label}</span>}
      {children}
    </NavLink>
  );
}
