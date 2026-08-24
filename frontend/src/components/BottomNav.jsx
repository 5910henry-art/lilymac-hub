// src/components/BottomNav.jsx
import React, { useContext, useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Home, Flame, Crown, User } from "lucide-react";
import { TipsContext } from "../contexts/TipsContext";
import {
  motion,
  AnimatePresence,
  useAnimation,
} from "framer-motion";

export default function BottomNav({ scrollContainerRef }) {
  const location = useLocation();
  const { topCount } = useContext(TipsContext);
  const controls = useAnimation();

  // =========================================================
  // RESPONSIVE SCROLL BEHAVIOR
  // Uses the actual AppLayout scroll container
  // =========================================================
  useEffect(() => {
    const scrollContainer = scrollContainerRef?.current;

    if (!scrollContainer) return;

    let lastScrollTop = scrollContainer.scrollTop;

    const handleScroll = () => {
      const currentScrollTop = scrollContainer.scrollTop;

      // Always show navigation near the top
      if (currentScrollTop <= 20) {
        controls.start({
          y: 0,
          transition: {
            type: "spring",
            stiffness: 300,
            damping: 30,
          },
        });

        lastScrollTop = currentScrollTop;
        return;
      }

      // Scrolling DOWN → hide navigation
      if (currentScrollTop > lastScrollTop + 5) {
        controls.start({
          y: 120,
          transition: {
            type: "spring",
            stiffness: 300,
            damping: 30,
          },
        });
      }

      // Scrolling UP → show navigation
      else if (currentScrollTop < lastScrollTop - 5) {
        controls.start({
          y: 0,
          transition: {
            type: "spring",
            stiffness: 300,
            damping: 30,
          },
        });
      }

      lastScrollTop = currentScrollTop;
    };

    scrollContainer.addEventListener(
      "scroll",
      handleScroll,
      { passive: true }
    );

    return () => {
      scrollContainer.removeEventListener(
        "scroll",
        handleScroll
      );
    };
  }, [scrollContainerRef, controls]);

  return (
    <motion.nav
      animate={controls}
      className="
        fixed
        bottom-0
        left-0
        right-0
        z-[9999]

        h-16
        px-2
        pb-[env(safe-area-inset-bottom)]

        bg-white/95
        dark:bg-gray-900/95

        border-t
        border-gray-200
        dark:border-gray-800

        shadow-[0_-4px_20px_rgba(0,0,0,0.08)]
        backdrop-blur-xl

        md:left-1/2
        md:right-auto
        md:bottom-5
        md:-translate-x-1/2

        md:w-[620px]
        md:h-[76px]

        md:px-5
        md:pb-0

        md:rounded-2xl

        md:border
        md:border-gray-200
        md:dark:border-gray-700

        md:shadow-2xl

        lg:w-[680px]
      "
      aria-label="Main navigation"
    >
      <div
        className="
          w-full
          h-full

          flex
          items-center
          justify-around

          md:justify-between

          gap-1
          md:gap-3
        "
      >

        {/* =================================================
            HOME
        ================================================== */}
        <NavItem
          to="/"
          icon={<Home size={22} />}
          label="Home"
        />

        {/* =================================================
            BOOKMARKS / BETS
        ================================================== */}
        <NavItem
          to="/bookmarks"
          icon={
            <span className="text-2xl md:text-3xl">
              💵💰
            </span>
          }
          label="Bets"
          pulse
          bounce
          glow
          shimmer
          activeScale={1.15}
        />

        {/* =================================================
            DAILY TIPS
        ================================================== */}
        <NavItem
          to="/tips/daily"
          icon={<Flame size={22} />}
          label="Tips"
        >
          <AnimatePresence>
            {topCount > 0 && (
              <motion.span
                key={`top-${topCount}`}
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                exit={{ scale: 0 }}
                transition={{
                  type: "spring",
                  stiffness: 500,
                  damping: 30,
                }}
                className="
                  absolute
                  -top-2
                  right-0

                  md:-top-1
                  md:right-1

                  flex
                  items-center
                  justify-center

                  w-6
                  h-6

                  rounded-full

                  bg-red-600
                  text-white

                  text-[12px]
                  font-bold

                  shadow-lg

                  border-2
                  border-white
                  dark:border-gray-900
                "
                aria-label={`${topCount} hot tips available`}
                role="status"
              >
                {topCount}
              </motion.span>
            )}
          </AnimatePresence>
        </NavItem>

        {/* =================================================
            VIP
        ================================================== */}
        <NavItem
          to="/vip"
          icon={<Crown size={22} />}
          label="VIP"
        >
          <motion.span
            className="
              absolute
              -top-2
              right-0

              md:-top-1
              md:right-1

              flex
              items-center
              justify-center

              w-6
              h-6

              rounded-full

              bg-amber-400
              text-black

              text-[10px]
              font-extrabold

              shadow-md

              border-2
              border-white
              dark:border-gray-900
            "
            aria-label="VIP section"
            title="VIP"
            role="img"
            animate={{
              scale: [1, 1.2, 1],
            }}
            transition={{
              duration: 1.5,
              repeat: Infinity,
            }}
          >
            VIP
          </motion.span>
        </NavItem>

        {/* =================================================
            ACCOUNT / ADMIN
        ================================================== */}
        <NavItem
          to="/admin"
          icon={<User size={22} />}
          label="Account"
        >
          {location.pathname === "/profile" && (
            <button
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                window.location.href = "/admin";
              }}
              className="
                absolute
                -top-6
                right-0

                w-7
                h-7

                rounded-full

                bg-red-500
                text-white

                text-xs

                flex
                items-center
                justify-center

                shadow-md
              "
              title="Go to Admin"
              aria-label="Go to Admin"
            >
              A
            </button>
          )}
        </NavItem>

      </div>
    </motion.nav>
  );
}


// ============================================================
// RESPONSIVE NAV ITEM
// ============================================================
function NavItem({
  to,
  icon,
  label,
  pulse,
  bounce,
  glow,
  shimmer,
  activeScale = 1.2,
  children,
}) {
  const location = useLocation();
  const isActive = location.pathname === to;

  return (
    <NavLink
      to={to}
      className={`
        relative

        flex
        flex-col
        items-center
        justify-center

        min-w-[56px]
        h-full

        px-2
        md:px-5

        rounded-xl

        transition-all
        duration-200

        ${
          isActive
            ? `
              text-green-600
              dark:text-green-400

              md:bg-green-50
              md:dark:bg-green-950/40
            `
            : `
              text-gray-500
              dark:text-gray-400

              hover:text-green-600
              dark:hover:text-green-400

              md:hover:bg-gray-100
              md:dark:hover:bg-gray-800
            `
        }
      `}
    >
      <motion.div
        animate={
          isActive
            ? {
                scale: activeScale,

                filter: glow
                  ? "drop-shadow(0 0 10px gold)"
                  : undefined,

                textShadow: shimmer
                  ? "0 0 10px gold, 0 0 20px gold"
                  : undefined,
              }
            : pulse
            ? {
                scale: [1, 1.15, 1],

                y: bounce
                  ? [0, -3, 3, 0]
                  : 0,

                rotate: bounce
                  ? [0, 5, -5, 0]
                  : 0,

                filter: glow
                  ? "drop-shadow(0 0 10px gold)"
                  : undefined,

                textShadow: shimmer
                  ? [
                      "0 0 5px gold",
                      "0 0 15px gold",
                      "0 0 5px gold",
                    ]
                  : undefined,
              }
            : {}
        }
        transition={{
          duration: 2,
          repeat: Infinity,
          ease: "easeInOut",
        }}
      >
        {icon}
      </motion.div>

      {/* Navigation label */}
      {label && (
        <span
          className="
            mt-1
            select-none

            text-[10px]
            font-medium

            md:text-xs
            md:font-semibold
          "
        >
          {label}
        </span>
      )}

      {children}
    </NavLink>
  );
}
