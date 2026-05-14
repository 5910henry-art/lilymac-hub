// src/components/HeaderHero.jsx
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";                 
export default function HeaderHero({ user, balance = 0 }) {       const navigate = useNavigate();
  const [small, setSmall] = useState(false);

  useEffect(() => {
    const handleScroll = () => setSmall(window.scrollY > 40);
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);                                                              }, []);

  const headerHeight = small ? 64 : 88;

  return (
    <>
      <header
        className={`fixed top-0 left-0 right-0 z-40 text-white transition-all duration-300 backdrop-blur-md ${
          small ? "py-2 px-3" : "py-4 px-4"
        }`}
        style={{
          background: "linear-gradient(90deg,#020617,#0f172a,#1e293b)",
          borderBottom: "1px solid rgba(22,163,74,0.25)",
          boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
        }}
      >
        <div className="flex justify-between items-center max-w-6xl mx-auto">
          <div className="leading-tight">
            <h1 className={`font-bold tracking-wide ${small ? "text-sm" : "text-xl"}`}>
              Lilymac Sports Hub
            </h1>
            {!small && <p className="text-xs opacity-60">Bet smarter. Win bigger.</p>}
          </div>

          <div className="flex items-center gap-3">
            {user ? (
              <>
                <div className="text-right">
                  {!small && <div className="text-[10px] opacity-60 uppercase">Balance</div>}
                  <div className="font-bold text-xs bg-emerald-500/20 border border-emerald-500/30 px-3 py-1 rounded-full">
                    💰 {balance.toFixed(2)}
                  </div>
                </div>

                <button
                  onClick={() => navigate("/profile")}
                  className="w-9 h-9 rounded-full bg-slate-700 hover:bg-slate-600 flex items-center justify-center"
                  aria-label="Profile"
                >
                  👤
                </button>
              </>
            ) : (
              <button
                onClick={() => navigate("/auth")}
                className="bg-yellow-400 hover:bg-yellow-500 text-black px-4 py-1.5 rounded-full text-xs font-bold"
              >
                🎁 Register now and get FREE KSh 50 bonus
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Minimal spacer: just a few pixels so content doesn't hide under fixed header */}
      <div style={{ height: 4 }} />
    </>
  );
}

