// src/components/ui/card.jsx
import React from "react";

export const Card = ({ children, className = "" }) => (
  <div
    className={`
      rounded-2xl
      bg-white dark:bg-gray-900
      border border-gray-100 dark:border-gray-800
      shadow-sm
      transition-all duration-200
      active:scale-[0.98]
      hover:shadow-md
      ${className}
    `}
  >
    {children}
  </div>
);

export const CardContent = ({ children, className = "" }) => (
  <div className={`p-4 ${className}`}>
    {children}
  </div>
);
