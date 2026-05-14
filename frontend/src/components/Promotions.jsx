// src/components/Promotions.jsx
import React from "react";
import { motion } from "framer-motion";

export default function Promotions() {
  const promos = [
    "/promos/jackpot.jpg",
    "/promos/odds.jpg",
    "/promos/freebet.jpg",
    "/promos/mpesa.jpg",
  ];

  return (
    <div className="mt-4 flex gap-6 justify-center">
      {promos.map((img, i) => (
        <motion.div
          key={i}
          className="min-w-[240px] h-36 rounded-xl overflow-hidden shadow-lg cursor-pointer bg-slate-800"
          animate={{ scale: [1, 1.05, 1] }} // pulse effect
          transition={{
            duration: 3 + i * 0.5, // slow pulse, slightly staggered per card
            repeat: Infinity,
            ease: "easeInOut",
          }}
        >
          <img
            src={img}
            alt="promo"
            className="w-full h-full object-cover"
          />
        </motion.div>
      ))}
    </div>
  );
}
