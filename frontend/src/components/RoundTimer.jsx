import React, { useState, useEffect } from "react";

export default function RoundTimer({ seconds }) {
  const [time, setTime] = useState(seconds);

  // Reset timer if seconds prop changes
  useEffect(() => {
    setTime(seconds);
  }, [seconds]);

  useEffect(() => {
    const timer = setInterval(() => {
      setTime((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  const minutes = Math.floor(time / 60);
  const secs = time % 60;

  return (
    <div className="round-timer px-3 py-1 bg-blue-600 text-white rounded-md inline-block">
      Next Round: {minutes}:{secs.toString().padStart(2, "0")}
    </div>
  );
}
