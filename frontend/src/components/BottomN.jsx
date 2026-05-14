// src/components/BottomN.jsx
import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Home, Ticket } from "lucide-react";
import { motion, useAnimation } from "framer-motion";

export default function BottomNav({ liveCount = 0 }) {
  const navigate = useNavigate();
  const controls = useAnimation();

  // Hide / show on scroll (same behavior as first file)
  useEffect(() => {
    let lastScrollY = window.scrollY;

    const handleScroll = () => {
      const currentScrollY = window.scrollY;

      if (currentScrollY > lastScrollY) {
        controls.start({
          y: 100,
          transition: { type: "spring", stiffness: 300, damping: 30 },
        });
      } else {
        controls.start({
          y: 0,
          transition: { type: "spring", stiffness: 300, damping: 30 },
        });
      }

      lastScrollY = currentScrollY;
    };

    window.addEventListener("scroll", handleScroll, { passive: true });

    return () => window.removeEventListener("scroll", handleScroll);
  }, [controls]);

  return (
    <motion.nav
      animate={controls}
      className="fixed bottom-0 left-0 right-0
      bg-slate-900 border-t border-slate-700
      flex justify-around items-center
      h-16 shadow-lg z-50"
    >
      {/* LIVE COUNT */}
      <button
        onClick={() => navigate("/live")}
        className="flex flex-col items-center text-red-500 text-sm"
      >
        <motion.div
          animate={{ scale: [1, 1.15, 1] }}
          transition={{ duration: 1.5, repeat: Infinity }}
          className="text-lg font-bold"
        >
          🔴 {liveCount}
        </motion.div>
        <span className="text-xs text-gray-400">Live</span>
      </button>

      {/* HOME (CENTER) */}
      <button
        onClick={() => navigate("/")}
        className="flex flex-col items-center text-green-500"
      >
        <motion.div
          animate={{ scale: [1, 1.2, 1] }}
          transition={{ duration: 2, repeat: Infinity }}
        >
          <Home size={28} />
        </motion.div>
        <span className="text-xs text-gray-400">Home</span>
      </button>

      {/* MY BETS */}
      <button
        onClick={() => navigate("/my-bets")}
        className="flex flex-col items-center text-yellow-400"
      >
        <motion.div
          animate={{ scale: [1, 1.2, 1] }}
          transition={{ duration: 2, repeat: Infinity }}
        >
          <Ticket size={30} /> {/* Increased icon size */}
        </motion.div>

        <span className="text-xs text-gray-400">My Bets</span>
      </button>
    </motion.nav>
  );
}
