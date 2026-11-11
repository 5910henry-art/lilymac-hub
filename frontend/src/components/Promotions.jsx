// src/components/Promotions.jsx

import React from "react";
import { motion } from "framer-motion";

export default function Promotions() {
  const promos = [
    "/promos/welcome.jpg",
    "/promos/top.jpg",
    "/promos/vip.jpg",
    "/promos/live.jpg",
    "/promos/stat.jpg",
  ];

  return (
    <div
      className="
        relative
        w-full
        max-w-full
        min-w-0
        overflow-x-auto
        overflow-y-hidden
        scrollbar-hide
        pt-0
        pb-1
        px-1
      "
    >
      <div
        className="
          pointer-events-none
          absolute
          left-0
          top-0
          h-full
          w-24
          bg-gradient-to-r
          from-red-950/30
          to-transparent
        "
      />

      <div
        className="
          pointer-events-none
          absolute
          right-0
          top-0
          h-full
          w-24
          bg-gradient-to-l
          from-blue-950/30
          to-transparent
        "
      />

      <div
        className="
          relative
          flex
          gap-3
          sm:gap-4
          md:gap-5
          w-max
          min-w-full
          md:w-full
          md:min-w-0
          md:justify-center
        "
      >
        {promos.map((img, i) => (
          <motion.div
            key={i}
            className="
              relative
              shrink-0
              w-[255px]
              sm:w-[280px]
              md:w-[230px]
              lg:w-[250px]
              xl:w-[270px]
              rounded-xl
              overflow-hidden
              cursor-pointer
              bg-gradient-to-br
              from-red-950
              via-slate-900
              to-blue-950
              border
              border-slate-700/50
              shadow-lg
            "
            animate={{
              scale: [
                1,
                1.015,
                1,
              ],
            }}
            transition={{
              duration:
                3 + i * 0.5,
              repeat: Infinity,
              ease: "easeInOut",
            }}
          >
            <div className="pointer-events-none absolute inset-0 z-10 bg-gradient-to-br from-red-500/5 via-transparent to-blue-500/10" />

            <img
              src={img}
              alt={`Promotion ${i + 1}`}
              className="
                relative
                z-0
                block
                w-full
                h-auto
                object-contain
              "
            />
          </motion.div>
        ))}
      </div>
    </div>
  );
}
