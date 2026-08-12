// src/components/BottomNav.jsx
import React, { useContext } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  Home,
  Flame,
  Crown,
  User,
  WalletCards,
} from "lucide-react";
import { TipsContext } from "../contexts/TipsContext";
import { motion, AnimatePresence } from "framer-motion";

export default function BottomNav() {
  const { topCount } = useContext(TipsContext);
  const location = useLocation();

  return (
    <motion.nav
      initial={{ y: 80 }}
      animate={{ y: 0 }}
      transition={{
        type: "spring",
        stiffness: 320,
        damping: 28,
      }}
      className="
        fixed
        bottom-0
        left-0
        right-0
        z-[60]
        md:hidden
        h-[68px]
        flex
        items-center
        justify-around
        px-2
        pb-[env(safe-area-inset-bottom)]
        bg-white/95
        backdrop-blur-xl
        border-t border-gray-200
        shadow-[0_-6px_25px_rgba(0,0,0,0.10)]
      "
      aria-label="Bottom navigation"
    >

      {/* HOME */}
      <NavItem
        to="/"
        icon={<Home size={22} strokeWidth={2} />}
        label="Home"
      />

      {/* MONEY / BOOKMARKS */}
      <NavItem
        to="/bookmarks"
        icon={<WalletCards size={22} strokeWidth={2} />}
        label="Saved"
      />

      {/* DAILY TIPS */}
      <NavItem
        to="/tips/daily"
        icon={<Flame size={22} strokeWidth={2} />}
        label="Tips"
      >
        <AnimatePresence>
          {topCount > 0 && (
            <motion.span
              key={`tips-${topCount}`}
              initial={{
                scale: 0,
                opacity: 0,
              }}
              animate={{
                scale: 1,
                opacity: 1,
              }}
              exit={{
                scale: 0,
                opacity: 0,
              }}
              transition={{
                type: "spring",
                stiffness: 500,
                damping: 25,
              }}
              className="
                absolute
                -top-1
                -right-1
                flex
                items-center
                justify-center
                min-w-[19px]
                h-[19px]
                px-1
                rounded-full
                bg-red-600
                text-white
                text-[9px]
                font-bold
                border-2
                border-white
                shadow-md
              "
              aria-label={`${topCount} hot tips available`}
              role="status"
            >
              {topCount}
            </motion.span>
          )}
        </AnimatePresence>
      </NavItem>

      {/* VIP */}
      <NavItem
        to="/vip"
        icon={<Crown size={22} strokeWidth={2} />}
        label="VIP"
      >
        <motion.span
          className="
            absolute
            -top-1
            -right-2
            flex
            items-center
            justify-center
            px-1.5
            h-[18px]
            rounded-full
            bg-gradient-to-r
            from-red-500
            to-blue-600
            text-white
            text-[8px]
            font-extrabold
            border-2
            border-white
            shadow-md
          "
          animate={{
            scale: [1, 1.08, 1],
          }}
          transition={{
            duration: 2,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        >
          VIP
        </motion.span>
      </NavItem>

      {/* PROFILE / ADMIN */}
      <NavItem
        to="/admin"
        icon={<User size={22} strokeWidth={2} />}
        label="Account"
      />

    </motion.nav>
  );
}


/* ============================================================
   BOTTOM NAV ITEM
============================================================ */

function NavItem({
  to,
  icon,
  label,
  children,
}) {
  const location = useLocation();

  const isActive =
    location.pathname === to ||
    (to !== "/" &&
      location.pathname.startsWith(to));

  return (
    <NavLink
      to={to}
      className="
        relative
        flex
        flex-col
        items-center
        justify-center
        min-w-[58px]
        h-full
        select-none
      "
    >
      <motion.div
        whileTap={{
          scale: 0.9,
        }}
        className="
          relative
          flex
          flex-col
          items-center
          justify-center
        "
      >

        {/* Active background */}
        <motion.div
          animate={{
            scale: isActive ? 1 : 0.8,
            opacity: isActive ? 1 : 0,
          }}
          transition={{
            duration: 0.2,
          }}
          className="
            absolute
            -top-1
            w-11
            h-9
            rounded-xl
            bg-gradient-to-r
            from-blue-500/15
            to-red-500/15
          "
        />

        {/* Icon */}
        <span
          className={`
            relative
            z-10
            transition-all
            duration-200
            ${
              isActive
                ? "text-blue-600"
                : "text-gray-500"
            }
          `}
        >
          {icon}
        </span>

        {/* Label */}
        {label && (
          <span
            className={`
              relative
              z-10
              mt-1
              text-[10px]
              font-medium
              transition-all
              duration-200
              ${
                isActive
                  ? "text-blue-600"
                  : "text-gray-500"
              }
            `}
          >
            {label}
          </span>
        )}

        {/* Active indicator */}
        {isActive && (
          <motion.span
            layoutId="bottomNavIndicator"
            className="
              absolute
              -bottom-0
              w-7
              h-[3px]
              rounded-full
              bg-gradient-to-r
              from-blue-600
              to-red-500
            "
          />
        )}

        {children}
      </motion.div>
    </NavLink>
  );
}
