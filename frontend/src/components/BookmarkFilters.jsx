import React, { useMemo } from "react";

/**
 * Horizontal chip-style filters for leagues and days.
 *
 * Props:
 * - bookmarks: array of match objects (must include .league and .match_time)
 * - filterLeague, setFilterLeague
 * - filterDay, setFilterDay
 *
 * Behaviour:
 * - Shows "All" as the first chip for both rows
 * - Leagues are deduped and shown as horizontal scroll chips
 * - Days are deduped, formatted to locale date, and if a date equals today/tomorrow
 *   the chip label becomes "Today" / "Tomorrow" (internally the value is still the date string)
 */
export default function BookmarkFilters({
  bookmarks = [],
  filterLeague,
  setFilterLeague,
  filterDay,
  setFilterDay,
}) {
  // dedupe leagues
  const leagues = useMemo(() => {
    const set = new Set(bookmarks.map((m) => m.league).filter(Boolean));
    return ["All", ...Array.from(set)];
  }, [bookmarks]);

  // dedupe days (locale date string)
  const days = useMemo(() => {
    const daySet = new Set(
      bookmarks
        .map((m) => {
          try {
            return new Date(m.match_time).toLocaleDateString();
          } catch {
            return null;
          }
        })
        .filter(Boolean)
    );

    // sort by actual date ascending
    const sorted = Array.from(daySet).sort((a, b) => {
      const da = new Date(a);
      const db = new Date(b);
      return da - db;
    });

    return ["All", ...sorted];
  }, [bookmarks]);

  // helpers for friendly labels
  const getDayLabel = (dayStr) => {
    if (dayStr === "All") return "All Days";
    try {
      const d = new Date(dayStr);
      const today = new Date();
      const tomorrow = new Date();
      tomorrow.setDate(today.getDate() + 1);

      const isSame = (x, y) =>
        x.getFullYear() === y.getFullYear() &&
        x.getMonth() === y.getMonth() &&
        x.getDate() === y.getDate();

      if (isSame(d, today)) return "Today";
      if (isSame(d, tomorrow)) return "Tomorrow";

      // show weekday + short date (e.g., Mon 9/3/2026) — use locale short
      return d.toLocaleDateString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
      });
    } catch {
      return dayStr;
    }
  };

  const chipBase =
    "whitespace-nowrap px-3 py-1 rounded-full text-sm font-medium border flex-shrink-0";

  return (
    <div className="flex flex-col gap-2">
      {/* League chips */}
      <div className="flex items-center gap-2 overflow-x-auto">
        {leagues.map((league) => {
          const active = filterLeague === league;
          return (
            <button
              key={league}
              onClick={() => setFilterLeague(league)}
              aria-pressed={active}
              className={`${chipBase} ${
                active
                  ? "bg-green-500 text-black border-transparent"
                  : "bg-slate-800 text-gray-200 border-slate-700"
              }`}
            >
              {league === "All" ? "All Leagues" : league}
            </button>
          );
        })}
      </div>

      {/* Day chips */}
      <div className="flex items-center gap-2 overflow-x-auto">
        {days.map((day) => {
          const active = filterDay === day;
          return (
            <button
              key={day}
              onClick={() => setFilterDay(day)}
              aria-pressed={active}
              className={`${chipBase} ${
                active
                  ? "bg-green-500 text-black border-transparent"
                  : "bg-slate-800 text-gray-200 border-slate-700"
              }`}
            >
              {getDayLabel(day)}
            </button>
          );
        })}
      </div>
    </div>
  );
}
