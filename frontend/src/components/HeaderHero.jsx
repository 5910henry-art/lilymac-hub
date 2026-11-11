// src/components/HeaderHero.jsx

import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

export default function HeaderHero({ user, balance = 0 }) {
  const navigate = useNavigate();
  const [small, setSmall] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setSmall(window.scrollY > 40);
    };

    window.addEventListener("scroll", handleScroll, {
      passive: true,
    });

    return () => {
      window.removeEventListener("scroll", handleScroll);
    };
  }, []);

  return (
    <>
      {/* =====================================================
          FIXED HEADER HERO
      ====================================================== */}

      <header
        className={`
          fixed
          top-0
          left-0
          right-0
          z-[60]
          text-white
          transition-all
          duration-300
          backdrop-blur-xl
          ${
            small
              ? "py-2 px-3"
              : "py-4 px-4"
          }
        `}
        style={{
          background:
            "linear-gradient(90deg,rgba(69,10,10,0.96) 0%,rgba(15,23,42,0.97) 48%,rgba(23,37,84,0.96) 100%)",

          borderBottom:
            "1px solid rgba(59,130,246,0.30)",

          boxShadow:
            "0 8px 28px rgba(0,0,0,0.65), inset 0 -1px 0 rgba(239,68,68,0.12)",
        }}
      >
        {/* Subtle red/blue glow */}
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          <div
            className="
              absolute
              -left-20
              -top-20
              h-40
              w-40
              rounded-full
              bg-red-600/20
              blur-3xl
            "
          />

          <div
            className="
              absolute
              -right-20
              -top-20
              h-40
              w-40
              rounded-full
              bg-blue-600/20
              blur-3xl
            "
          />
        </div>

        <div
          className="
            relative
            z-10
            w-full
            max-w-6xl
            mx-auto
            flex
            items-center
            justify-between
            gap-4
          "
        >
          {/* =================================================
              BRAND
          ================================================== */}

          <div className="leading-tight min-w-0">
            <h1
              className={`
                font-bold
                tracking-wide
                truncate
                ${
                  small
                    ? "text-sm"
                    : "text-xl"
                }
              `}
            >
              Lilymac Sports Hub
            </h1>

            {!small && (
              <p className="text-xs text-slate-300/70">
                Bet smarter. Win bigger.
              </p>
            )}
          </div>

          {/* =================================================
              USER / BALANCE
          ================================================== */}

          <div className="flex items-center gap-3 shrink-0">
            {user ? (
              <>
                <div className="text-right">
                  {!small && (
                    <div className="text-[10px] opacity-60 uppercase tracking-wide">
                      Balance
                    </div>
                  )}

                  <div
                    className="
                      font-bold
                      text-xs
                      bg-gradient-to-r
                      from-red-500/20
                      via-slate-800/80
                      to-blue-500/20
                      border
                      border-blue-400/30
                      px-3
                      py-1
                      rounded-full
                      whitespace-nowrap
                      shadow-lg
                    "
                  >
                    💰{" "}
                    {Number(
                      balance || 0
                    ).toFixed(2)}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() =>
                    navigate("/profile")
                  }
                  className="
                    w-9
                    h-9
                    shrink-0
                    rounded-full
                    bg-gradient-to-br
                    from-red-500/30
                    to-blue-600/30
                    border
                    border-slate-600/70
                    hover:border-blue-400/60
                    hover:from-red-500/40
                    hover:to-blue-600/40
                    flex
                    items-center
                    justify-center
                    transition-all
                  "
                  aria-label="Profile"
                >
                  👤
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() =>
                  navigate("/auth")
                }
                className="
                  bg-yellow-400
                  hover:bg-yellow-500
                  text-black
                  px-4
                  py-1.5
                  rounded-full
                  text-xs
                  font-bold
                  whitespace-nowrap
                  transition
                  shadow-lg
                "
              >
                🎁 Register now and get FREE KSh 50 bonus
              </button>
            )}
          </div>
        </div>
      </header>

      {/* =====================================================
          FIXED HEADER SPACER
      ====================================================== */}

      <div
        aria-hidden="true"
        className={
          small
            ? "h-[64px]"
            : "h-[88px]"
        }
      />
    </>
  );
}
