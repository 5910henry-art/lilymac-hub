// src/components/RoundTimer.jsx

import React, {
  useEffect,
  useState,
} from "react";

export default function RoundTimer({
  seconds = 0,
}) {
  const safeSeconds = Math.max(
    0,
    Number(seconds) || 0
  );

  const [time, setTime] =
    useState(safeSeconds);

  /*
   * Reset timer whenever the server
   * provides a new countdown.
   */
  useEffect(() => {
    setTime(safeSeconds);
  }, [safeSeconds]);

  /*
   * Countdown every second.
   */
  useEffect(() => {
    const timer = setInterval(() => {
      setTime((previous) =>
        previous > 0
          ? previous - 1
          : 0
      );
    }, 1000);

    return () => {
      clearInterval(timer);
    };
  }, []);

  const minutes = Math.floor(
    time / 60
  );

  const secs = time % 60;

  return (
    <div className="inline-flex items-center rounded-md bg-blue-600 px-3 py-1 text-sm font-semibold text-white shadow-sm">
      Next Round:{" "}
      {minutes}:
      {secs
        .toString()
        .padStart(2, "0")}
    </div>
  );
}
