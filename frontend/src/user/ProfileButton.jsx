// src/user/ProfileButton.jsx

import React from "react";

export default function ProfileButton({
  children,
  onClick,
  color = "blue",
  disabled = false,
  small = false,
  className = "",
  type = "button",
  ...props
}) {
  const colors = {
    blue: `
      bg-blue-600
      hover:bg-blue-700
      focus-visible:ring-blue-400/50
    `,
    green: `
      bg-emerald-600
      hover:bg-emerald-700
      focus-visible:ring-emerald-400/50
    `,
    red: `
      bg-red-600
      hover:bg-red-700
      focus-visible:ring-red-400/50
    `,
    gray: `
      bg-gray-600
      hover:bg-gray-700
      focus-visible:ring-gray-400/50
    `,
  };

  const size = small
    ? "min-h-9 px-3 py-1.5 text-sm"
    : "min-h-11 px-4 py-2.5 text-sm";

  const width = small ? "w-auto" : "w-full";

  const colorClasses = colors[color] || colors.blue;

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`
        inline-flex
        items-center
        justify-center
        gap-2

        ${colorClasses}
        ${size}
        ${width}

        rounded-xl
        font-semibold
        text-white

        shadow-sm
        hover:shadow-md
        active:scale-[0.98]

        transition-all
        duration-200
        ease-out

        focus:outline-none
        focus-visible:ring-2
        focus-visible:ring-offset-2
        focus-visible:ring-offset-transparent

        disabled:pointer-events-none
        disabled:cursor-not-allowed
        disabled:opacity-50
        disabled:shadow-none

        ${className}
      `}
      {...props}
    >
      {children}
    </button>
  );
}
