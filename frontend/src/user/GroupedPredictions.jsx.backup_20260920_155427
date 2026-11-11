import React, { useEffect, useMemo, useState } from "react";
import { getGroupedPredictions } from "../api/domain";

function safeNum(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function clamp01(v) {
  return Math.max(0, Math.min(1, safeNum(v, 0)));
}

function pct(v) {
  return `${(clamp01(v) * 100).toFixed(1)}%`;
}

function parseDate(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function dayKey(value) {
  const d = parseDate(value);
  if (!d) return "Unknown Date";
  return d.toISOString().slice(0, 10);
}

function formatDay(value) {
  const d = parseDate(value);
  if (!d) return "Unknown Date";
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function formatTime(value) {
  const d = parseDate(value);
  if (!d) return "";
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function bestGroup(groups = []) {
  if (!Array.isArray(groups) || !groups.length) return null;
  return [...groups].sort(
    (a, b) => safeNum(b?.avg_confidence) - safeNum(a?.avg_confidence)
  )[0];
}

function TeamBadge({ name, logo }) {
  const initials = useMemo(() => {
    const parts = String(name || "FC").trim().split(/\s+/).filter(Boolean);
    return ((parts[0]?.[0] || "F") + (parts[1]?.[0] || "C")).toUpperCase();
  }, [name]);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
      {logo ? (
        <img
          src={logo}
          alt={name || "team"}
          style={{
            width: 28,
            height: 28,
            borderRadius: 999,
            objectFit: "contain",
            background: "#fff",
            flex: "0 0 auto",
          }}
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      ) : (
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: 999,
            display: "grid",
            placeItems: "center",
            background: "#e5e7eb",
            color: "#374151",
            fontSize: 11,
            fontWeight: 700,
            flex: "0 0 auto",
          }}
        >
          {initials}
        </div>
      )}
      <div
        style={{
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          fontWeight: 600,
          fontSize: 14,
        }}
        title={name}
      >
        {name}
      </div>
    </div>
  );
}

export default function MatchGroupedPredictionsPage() {
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [openKey, setOpenKey] = useState(null);
  const [viewMode, setViewMode] = useState("today"); // today | all
  const [selectedDate, setSelectedDate] = useState("");
  const [visibleDays, setVisibleDays] = useState(2);

  useEffect(() => {
    let alive = true;

    (async () => {
      try {
        const res = await getGroupedPredictions();

        const raw =
          res?.data?.predictions ||
          res?.data ||
          res?.predictions ||
          [];

        const list = Array.isArray(raw) ? raw : [];

        if (alive) setMatches(list);
      } catch (err) {
        console.error("Failed to load grouped predictions:", err);
        if (alive) setMatches([]);
      } finally {
        if (alive) setLoading(false);
      }
    })();

    return () => {
      alive = false;
    };
  }, []);

  const badgeColor = (prediction) => {
    if (prediction === "Home Win") return "#16a34a";
    if (prediction === "Away Win") return "#dc2626";
    return "#d97706";
  };

  const dayOptions = useMemo(() => {
    const keys = new Set();
    for (const m of matches) {
      const key = dayKey(m?.localDate || m?.utcDate);
      if (key !== "Unknown Date") keys.add(key);
    }
    return [...keys].sort();
  }, [matches]);

  useEffect(() => {
    if (!selectedDate && dayOptions.length) {
      const today = new Date().toISOString().slice(0, 10);
      setSelectedDate(dayOptions.includes(today) ? today : dayOptions[0]);
    }
  }, [dayOptions, selectedDate]);

  const groupedMatches = useMemo(() => {
    const source = [...matches]
      .sort((a, b) => {
        const da = parseDate(a?.localDate || a?.utcDate)?.getTime() ?? 0;
        const db = parseDate(b?.localDate || b?.utcDate)?.getTime() ?? 0;
        return da - db;
      })
      .filter((m) => {
        if (viewMode === "all") {
          return selectedDate ? dayKey(m?.localDate || m?.utcDate) === selectedDate : true;
        }
        const today = new Date().toISOString().slice(0, 10);
        return dayKey(m?.localDate || m?.utcDate) === today;
      });

    const groups = new Map();

    source.forEach((m) => {
      const key = dayKey(m?.localDate || m?.utcDate);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(m);
    });

    return [...groups.entries()]
      .map(([key, items]) => ({
        key,
        title: formatDay(items?.[0]?.localDate || items?.[0]?.utcDate),
        items: [...items].sort((a, b) => {
          const ta = parseDate(a?.localDate || a?.utcDate)?.getTime() ?? 0;
          const tb = parseDate(b?.localDate || b?.utcDate)?.getTime() ?? 0;
          return ta - tb;
        }),
      }))
      .slice(0, viewMode === "today" ? 1 : visibleDays);
  }, [matches, viewMode, selectedDate, visibleDays]);

  const cardStyle = {
    border: "1px solid #e5e7eb",
    borderRadius: 14,
    background: "#fff",
    padding: 12,
    boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
  };

  if (loading) {
    return (
      <div style={{ padding: 12, color: "#6b7280", fontSize: 14 }}>
        Loading grouped predictions...
      </div>
    );
  }

  if (!matches.length) {
    return (
      <div style={{ padding: 12, color: "#6b7280", fontSize: 14 }}>
        No grouped predictions found.
      </div>
    );
  }

  return (
    <div style={{ padding: 12, maxWidth: 1100, margin: "0 auto" }}>
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
          Grouped Match Predictions
        </h2>
        <div style={{ color: "#6b7280", fontSize: 12, marginTop: 4 }}>
          Compact view grouped by date and sorted by time
        </div>
      </div>

      <div
        style={{
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          marginBottom: 12,
          alignItems: "center",
        }}
      >
        <button
          type="button"
          onClick={() => setViewMode("today")}
          style={{
            border: "1px solid #e5e7eb",
            background: viewMode === "today" ? "#111827" : "#fff",
            color: viewMode === "today" ? "#fff" : "#111827",
            borderRadius: 999,
            padding: "7px 12px",
            fontSize: 12,
            fontWeight: 700,
            cursor: "pointer",
          }}
        >
          Today
        </button>

        <button
          type="button"
          onClick={() => setViewMode("all")}
          style={{
            border: "1px solid #e5e7eb",
            background: viewMode === "all" ? "#111827" : "#fff",
            color: viewMode === "all" ? "#fff" : "#111827",
            borderRadius: 999,
            padding: "7px 12px",
            fontSize: 12,
            fontWeight: 700,
            cursor: "pointer",
          }}
        >
          All dates
        </button>

        {viewMode === "all" && (
          <select
            value={selectedDate}
            onChange={(e) => {
              setSelectedDate(e.target.value);
              setVisibleDays(2);
            }}
            style={{
              border: "1px solid #e5e7eb",
              background: "#fff",
              borderRadius: 999,
              padding: "7px 12px",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
              outline: "none",
            }}
          >
            {dayOptions.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        )}
      </div>

      <div style={{ display: "grid", gap: 14 }}>
        {groupedMatches.map((dayGroup) => (
          <div key={dayGroup.key} style={{ display: "grid", gap: 10 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 700,
                color: "#111827",
                padding: "4px 2px",
              }}
            >
              {dayGroup.title}
            </div>

            <div style={{ display: "grid", gap: 10 }}>
              {dayGroup.items.map((m, idx) => {
                const groups = Array.isArray(m.grouped_predictions)
                  ? m.grouped_predictions
                  : [];
                const top = bestGroup(groups);
                const key = `${m.match_id ?? idx}`;
                const timeText = formatTime(m.localDate || m.utcDate);

                return (
                  <div key={key} style={cardStyle}>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: 12,
                        alignItems: "flex-start",
                      }}
                    >
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            flexWrap: "wrap",
                            marginBottom: 6,
                          }}
                        >
                          <TeamBadge name={m.home} logo={m.home_logo} />
                          <span style={{ color: "#9ca3af", fontSize: 12 }}>
                            vs
                          </span>
                          <TeamBadge name={m.away} logo={m.away_logo} />
                        </div>

                        <div
                          style={{
                            color: "#6b7280",
                            fontSize: 12,
                            lineHeight: 1.4,
                            display: "flex",
                            gap: 8,
                            flexWrap: "wrap",
                            alignItems: "center",
                          }}
                        >
                          {timeText ? (
                            <span
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                padding: "3px 8px",
                                borderRadius: 999,
                                background: "#f3f4f6",
                                color: "#374151",
                                fontWeight: 700,
                                fontSize: 12,
                              }}
                            >
                              {timeText}
                            </span>
                          ) : null}
                          {m.match_id ? <span>Match {m.match_id}</span> : null}
                        </div>
                      </div>

                      {top ? (
                        <div
                          style={{
                            flex: "0 0 auto",
                            padding: "6px 10px",
                            borderRadius: 999,
                            background: `${badgeColor(top.prediction)}14`,
                            color: badgeColor(top.prediction),
                            fontSize: 12,
                            fontWeight: 700,
                            whiteSpace: "nowrap",
                          }}
                        >
                          {top.prediction} · {pct(top.avg_confidence)}
                        </div>
                      ) : null}
                    </div>

                    <div
                      style={{
                        marginTop: 10,
                        display: "grid",
                        gap: 8,
                      }}
                    >
                      {groups.slice(0, 2).map((g, gi) => {
                        const gkey = `${key}-${gi}`;
                        const isOpen = openKey === gkey;

                        return (
                          <div
                            key={gkey}
                            style={{
                              border: "1px solid #f1f5f9",
                              borderRadius: 12,
                              padding: 10,
                              background: "#fafafa",
                            }}
                          >
                            <div
                              style={{
                                display: "grid",
                                gridTemplateColumns: "1fr auto",
                                gap: 10,
                                alignItems: "center",
                              }}
                            >
                              <div>
                                <div
                                  style={{
                                    fontSize: 13,
                                    fontWeight: 700,
                                    color: badgeColor(g.prediction),
                                  }}
                                >
                                  {g.prediction}
                                </div>
                                <div
                                  style={{
                                    fontSize: 12,
                                    color: "#6b7280",
                                    marginTop: 2,
                                  }}
                                >
                                  Avg {pct(g.avg_confidence)} · {g.num_models} model
                                  {g.num_models === 1 ? "" : "s"}
                                </div>
                              </div>

                              <button
                                type="button"
                                onClick={() =>
                                  setOpenKey(isOpen ? null : gkey)
                                }
                                style={{
                                  border: "1px solid #e5e7eb",
                                  background: "#fff",
                                  borderRadius: 10,
                                  padding: "6px 10px",
                                  fontSize: 12,
                                  cursor: "pointer",
                                }}
                              >
                                {isOpen ? "Hide" : "Details"}
                              </button>
                            </div>

                            {isOpen && Array.isArray(g.models) && g.models.length > 0 && (
                              <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
                                {g.models.map((model, mi) => {
                                  const p = model?.probabilities || {};
                                  return (
                                    <div
                                      key={mi}
                                      style={{
                                        borderTop: "1px solid #e5e7eb",
                                        paddingTop: 8,
                                        display: "grid",
                                        gap: 4,
                                      }}
                                    >
                                      <div style={{ fontSize: 12, fontWeight: 600 }}>
                                        {model.model_version}
                                      </div>
                                      <div style={{ fontSize: 12, color: "#6b7280" }}>
                                        Conf {pct(model.confidence)}
                                      </div>
                                      <div style={{ fontSize: 12, color: "#374151" }}>
                                        H {pct(p.home_win)} · D {pct(p.draw)} · A{" "}
                                        {pct(p.away_win)}
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        );
                      })}

                      {groups.length > 2 && (
                        <div style={{ fontSize: 12, color: "#6b7280" }}>
                          {groups.length - 2} more group{groups.length - 2 === 1 ? "" : "s"} hidden
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {viewMode === "all" && groupedMatches.length > 0 && visibleDays < dayOptions.length && (
        <div style={{ marginTop: 14, display: "flex", justifyContent: "center" }}>
          <button
            type="button"
            onClick={() => setVisibleDays((v) => Math.min(v + 2, dayOptions.length))}
            style={{
              border: "1px solid #e5e7eb",
              background: "#fff",
              borderRadius: 999,
              padding: "8px 14px",
              fontSize: 12,
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            Load more days
          </button>
        </div>
      )}
    </div>
  );
}
