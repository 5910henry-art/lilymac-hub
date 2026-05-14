// src/user/ProfileButton.jsx
import React from "react";

export default function ProfileButton({
  children,
  onClick,
  color = "blue",
  disabled = false,
  small = false,
  className = "",
}) {
  const colors = {
    blue: "bg-blue-500 hover:bg-blue-600",
    green: "bg-green-500 hover:bg-green-600",
    red: "bg-red-500 hover:bg-red-600",
    gray: "bg-gray-500 hover:bg-gray-600",
  };
  const size = small ? "px-2 py-1 text-sm" : "px-4 py-2";
  const width = small ? "" : "w-full";
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`${colors[color]} text-white ${size} ${width} rounded transition disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
    >
      {children}
    </button>
  );
}
