// src/components/BottomNav.jsx

import React, {
  useContext,
  useEffect,
} from "react";
import {
  NavLink,
  useLocation,
} from "react-router-dom";
import {
  Home,
  Flame,
  Crown,
  User,
} from "lucide-react";
import { TipsContext } from "../contexts/TipsContext";
import {
  motion,
  AnimatePresence,
  useAnimation,
} from "framer-motion";

export default function BottomNav({
  scrollContainerRef,
  mobileOpen = false,
}) {
  const location = useLocation();
  const { topCount } = useContext(TipsContext);
  const controls = useAnimation();

  /* =========================================================
     SCROLL BEHAVIOUR

     DOWN -> hide
     UP   -> show
     TOP  -> show
  ========================================================= */
  useEffect(() => {
    const scrollContainer =
      scrollContainerRef?.current;

    if (!scrollContainer) return;

    let lastScrollY =
      scrollContainer.scrollTop;

    const showNav = () => {
      controls.start({
        y: 0,
        transition: {
          type: "spring",
          stiffness: 320,
          damping: 32,
        },
      });
    };

    const hideNav = () => {
      controls.start({
        y: 110,
        transition: {
          type: "spring",
          stiffness: 320,
          damping: 32,
        },
      });
    };

    const handleScroll = () => {
      const currentScrollY =
        scrollContainer.scrollTop;

      if (currentScrollY <= 20) {
        showNav();
        lastScrollY = currentScrollY;
        return;
      }

      if (currentScrollY > lastScrollY + 4) {
        hideNav();
      } else if (
        currentScrollY < lastScrollY - 4
      ) {
        showNav();
      }

      lastScrollY = currentScrollY;
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

  /* =========================================================
     SIDEBAR OPEN -> HIDE BOTTOM NAV
  ========================================================= */
  useEffect(() => {
    if (mobileOpen) {
      controls.start({
        y: 120,
        transition: {
          duration: 0.18,
        },
      });
    } else {
      controls.start({
        y: 0,
        transition: {
          type: "spring",
          stiffness: 320,
          damping: 32,
        },
      });
    }
  }, [mobileOpen, controls]);

  return (
    <motion.nav
      animate={controls}
      className="
        fixed
        z-[70]

        left-3
        right-3
        bottom-3

        h-[74px]

        flex
        items-center
        justify-around

        rounded-2xl

        bg-white/95
        backdrop-blur-xl

        border
        border-white/70

        shadow-[0_12px_40px_rgba(0,0,0,0.20)]

        px-2

        select-none

        md:left-auto
        md:right-6
        md:bottom-6
        md:w-[420px]
      "
      style={{
        paddingBottom:
          "env(safe-area-inset-bottom)",
      }}
      aria-label="Bottom navigation"
    >
      {/* HOME */}
      <NavItem
        to="/"
        icon={<Home size={21} strokeWidth={2} />}
        label="Home"
      />

      {/* BETS */}
      <NavItem
        to="/bookmarks"
        icon={
          <span className="text-[22px] leading-none">
            💵💰
          </span>
        }
        pulse
        bounce
        glow
        shimmer
        activeScale={1.08}
      />

      {/* TIPS */}
      <NavItem
        to="/tips/daily"
        icon={
          <Flame
            size={21}
            strokeWidth={2}
          />
        }
        label="🔥"
      >
        <AnimatePresence>
          {topCount > 0 && (
            <motion.span
              key={`top-${topCount}`}
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
                damping: 30,
              }}
              className="
                absolute
                -top-2
                right-1

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
        icon={
          <Crown
            size={21}
            strokeWidth={2}
          />
        }
        label="VIP"
      >
        <motion.span
          className="
            absolute
            -top-2
            right-1

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
          aria-label="VIP section"
          title="VIP"
          role="img"
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
      </NavItem>

      {/* ACCOUNT */}
      <NavItem
        to="/admin"
        icon={
          <User
            size={21}
            strokeWidth={2}
          />
        }
        label="🔐"
      >
        {location.pathname === "/profile" && (
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();

              window.location.href =
                "/admin";
            }}
            className="
              absolute
              -top-5
              right-1

              w-6
              h-6

              rounded-full

              bg-red-500
              text-white
              text-[10px]
              font-bold

              flex
              items-center
              justify-center

              shadow-md

              border-2
              border-white
            "
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

/* ============================================================
   NAV ITEM
============================================================ */

function NavItem({
  to,
  icon,
  label,
  pulse = false,
  bounce = false,
  glow = false,
  shimmer = false,
  activeScale = 1.08,
  children,
}) {
  const location = useLocation();

  const isActive =
    location.pathname === to ||
    (to === "/tips/daily" &&
      location.pathname.startsWith("/tips"));

  return (
    <NavLink
      to={to}
      className={`
        bottom-nav-btn

        relative

        flex
        flex-col
        items-center
        justify-center

        gap-1

        w-[20%]
        min-w-0

        h-full

        rounded-xl

        ${
          isActive
            ? "text-blue-600"
            : "text-gray-500"
        }

        transition-colors
      `}
      aria-current={
        isActive ? "page" : undefined
      }
    >
      <motion.div
        animate={
          isActive
            ? {
                scale: activeScale,

                filter: glow
                  ? "drop-shadow(0 0 7px rgba(245,158,11,0.65))"
                  : undefined,

                textShadow: shimmer
                  ? "0 0 8px rgba(245,158,11,0.7)"
                  : undefined,
              }
            : pulse
            ? {
                scale: [1, 1.06, 1],

                y: bounce
                  ? [0, -2, 2, 0]
                  : 0,

                rotate: bounce
                  ? [0, 3, -3, 0]
                  : 0,

                filter: glow
                  ? "drop-shadow(0 0 7px rgba(245,158,11,0.55))"
                  : undefined,
              }
            : {
                scale: 1,
                y: 0,
                rotate: 0,
              }
        }
        transition={
          isActive
            ? {
                type: "spring",
                stiffness: 350,
                damping: 22,
              }
            : {
                duration: 2,
                repeat: Infinity,
                ease: "easeInOut",
              }
        }
      >
        {icon}
      </motion.div>

      {label && (
        <span className="
          bottom-nav-label
          text-[10px]
          font-medium
          leading-none
          whitespace-nowrap
        ">
          {label}
        </span>
      )}

      {children}
    </NavLink>
  );
}
