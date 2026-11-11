// src/components/MatchEvents.jsx

import React, {
  useEffect,
  useMemo,
  useState,
} from "react";

import VirtualAPI from "../api/virtualAPI";
import VirtualSocket from "../api/virtualSocket";

function getEventIcon(type) {
  const value = String(type || "").toUpperCase();

  if (
    value.includes("OWN") &&
    value.includes("GOAL")
  ) {
    return "⚽";
  }

  if (
    value.includes("GOAL") ||
    value.includes("SCORE")
  ) {
    return "⚽";
  }

  if (
    value.includes("PENALTY") ||
    value.includes("PEN")
  ) {
    return "🟢";
  }

  if (
    value.includes("YELLOW") ||
    value === "CARD_YELLOW" ||
    value === "YELLOW_CARD"
  ) {
    return "🟨";
  }

  if (
    value.includes("RED") ||
    value === "CARD_RED" ||
    value === "RED_CARD"
  ) {
    return "🟥";
  }

  if (
    value.includes("SUB") ||
    value.includes("SUBSTITUTION")
  ) {
    return "🔄";
  }

  if (value.includes("VAR")) {
    return "📺";
  }

  return "•";
}

function getEventLabel(type) {
  const value = String(type || "")
    .toUpperCase()
    .trim();

  if (
    value.includes("OWN") &&
    value.includes("GOAL")
  ) {
    return "Own goal";
  }

  if (value.includes("GOAL")) {
    return "Goal";
  }

  if (
    value.includes("PENALTY") ||
    value.includes("PEN")
  ) {
    return "Penalty";
  }

  if (
    value.includes("YELLOW") ||
    value === "CARD_YELLOW" ||
    value === "YELLOW_CARD"
  ) {
    return "Yellow card";
  }

  if (
    value.includes("RED") ||
    value === "CARD_RED" ||
    value === "RED_CARD"
  ) {
    return "Red card";
  }

  if (
    value.includes("SUB") ||
    value.includes("SUBSTITUTION")
  ) {
    return "Substitution";
  }

  if (value.includes("VAR")) {
    return "VAR";
  }

  return type || "Event";
}

function getPlayerName(event) {
  if (!event) return "";

  if (typeof event.player === "string") {
    return event.player;
  }

  if (event.player?.name) {
    return event.player.name;
  }

  if (event.player?.short_name) {
    return event.player.short_name;
  }

  if (event.player_name) {
    return event.player_name;
  }

  if (typeof event.scorer === "string") {
    return event.scorer;
  }

  if (event.scorer?.name) {
    return event.scorer.name;
  }

  if (event.scorer?.short_name) {
    return event.scorer.short_name;
  }

  return "";
}

function getAssistName(event) {
  if (!event) return "";

  if (typeof event.assist === "string") {
    return event.assist;
  }

  if (event.assist?.name) {
    return event.assist.name;
  }

  if (event.assist?.short_name) {
    return event.assist.short_name;
  }

  if (event.assist_name) {
    return event.assist_name;
  }

  return "";
}

function getTeamName(event) {
  if (!event) return "";

  if (typeof event.team === "string") {
    return event.team;
  }

  if (event.team?.name) {
    return event.team.name;
  }

  if (event.team?.short_name) {
    return event.team.short_name;
  }

  if (event.team_name) {
    return event.team_name;
  }

  return "";
}

function getMinute(event) {
  if (!event) return "";

  const minute =
    event.minute ??
    event.elapsed ??
    event.time ??
    event.minute_value;

  if (
    minute === null ||
    minute === undefined
  ) {
    return "";
  }

  if (typeof minute === "object") {
    if (minute.elapsed !== undefined) {
      return String(minute.elapsed);
    }

    return "";
  }

  return String(minute);
}

function getEventKey(event, index) {
  if (
    event?.id !== undefined &&
    event?.id !== null
  ) {
    return `event-${event.id}`;
  }

  return [
    event?.match_id ?? "",
    getMinute(event),
    event?.type ??
      event?.event_type ??
      "",
    getTeamName(event),
    getPlayerName(event),
    index,
  ].join("-");
}

function getEventIdentity(event) {
  return JSON.stringify({
    id: event?.id ?? null,
    match_id:
      event?.match_id ??
      event?.matchId ??
      null,
    minute:
      event?.minute ??
      event?.elapsed ??
      event?.time ??
      null,
    type:
      event?.type ??
      event?.event_type ??
      "",
    team:
      event?.team?.id ??
      event?.team?.name ??
      event?.team_name ??
      event?.team ??
      "",
    player:
      event?.player?.id ??
      event?.player?.name ??
      event?.player_name ??
      event?.player ??
      event?.scorer ??
      "",
  });
}

export default function MatchEvents({
  matchId,
}) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!matchId) {
      setEvents([]);
      return;
    }

    let active = true;

    const loadHistory = async () => {
      setLoading(true);

      try {
        const data =
          await VirtualAPI.getEvents(matchId);

        if (!active) return;

        let history = [];

        if (Array.isArray(data)) {
          history = data;
        } else if (
          Array.isArray(data?.events)
        ) {
          history = data.events;
        } else if (
          Array.isArray(data?.data)
        ) {
          history = data.data;
        }

        setEvents(history);
      } catch (error) {
        console.error(
          "Failed loading match events:",
          error
        );

        if (active) {
          setEvents([]);
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    loadHistory();

    VirtualSocket.connect();

    VirtualSocket.joinMatch(
      matchId
    ).catch((error) => {
      console.error(
        "Failed joining virtual match:",
        error
      );
    });

    const stop =
      VirtualSocket.on(
        "virtual_match_event",
        (payload) => {
          if (!active) return;

          const payloadMatchId =
            payload?.match_id ??
            payload?.matchId ??
            payload?.match?.id ??
            payload?.event?.match_id;

          if (
            payloadMatchId !==
              undefined &&
            payloadMatchId !== null &&
            Number(payloadMatchId) !==
              Number(matchId)
          ) {
            return;
          }

          const incomingEvent =
            payload?.event ??
            payload?.data ??
            payload;

          if (!incomingEvent) return;

          setEvents((previous) => {
            const incomingKey =
              getEventIdentity(
                incomingEvent
              );

            const exists =
              previous.some(
                (item) =>
                  getEventIdentity(
                    item
                  ) === incomingKey
              );

            if (exists) {
              return previous;
            }

            return [
              ...previous,
              incomingEvent,
            ];
          });
        }
      );

    return () => {
      active = false;

      stop?.();

      // leaveMatch() is synchronous
      VirtualSocket.leaveMatch(
        matchId
      );
    };
  }, [matchId]);

  const sortedEvents = useMemo(() => {
    return [...events].sort((a, b) => {
      const minuteA = Number(
        a?.minute ??
          a?.elapsed ??
          a?.time ??
          0
      );

      const minuteB = Number(
        b?.minute ??
          b?.elapsed ??
          b?.time ??
          0
      );

      return minuteA - minuteB;
    });
  }, [events]);

  if (!matchId) {
    return null;
  }

  return (
    <div className="mt-3 w-full">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-bold text-gray-800 dark:text-white">
          Match Events
        </h3>

        {events.length > 0 && (
          <span className="text-[10px] text-gray-500">
            {events.length}{" "}
            event
            {events.length === 1
              ? ""
              : "s"}
          </span>
        )}
      </div>

      {loading &&
        events.length === 0 && (
          <div className="rounded-lg bg-gray-100 px-3 py-2 text-center text-xs text-gray-500 dark:bg-gray-800 dark:text-gray-400">
            Loading events...
          </div>
        )}

      {!loading &&
        sortedEvents.length === 0 && (
          <div className="rounded-lg bg-gray-100 px-3 py-3 text-center text-xs text-gray-500 dark:bg-gray-800 dark:text-gray-400">
            No events yet
          </div>
        )}

      {sortedEvents.length > 0 && (
        <div className="space-y-1.5">
          {sortedEvents.map(
            (event, index) => {
              const type =
                event?.type ||
                event?.event_type ||
                "Event";

              const icon =
                getEventIcon(type);

              const label =
                getEventLabel(type);

              const minute =
                getMinute(event);

              const player =
                getPlayerName(event);

              const assist =
                getAssistName(event);

              const team =
                getTeamName(event);

              return (
                <div
                  key={getEventKey(
                    event,
                    index
                  )}
                  className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-2.5 py-2 shadow-sm dark:border-gray-700 dark:bg-gray-800"
                >
                  <div className="w-8 shrink-0 text-center text-xs font-bold text-gray-500 dark:text-gray-400">
                    {minute
                      ? `${minute}'`
                      : "•"}
                  </div>

                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-100 text-sm dark:bg-gray-700">
                    {icon}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-semibold text-gray-800 dark:text-white">
                      {label}
                    </div>

                    {player && (
                      <div className="truncate text-[11px] text-gray-600 dark:text-gray-300">
                        {player}

                        {assist
                          ? ` • Assist: ${assist}`
                          : ""}
                      </div>
                    )}

                    {!player &&
                      team && (
                        <div className="truncate text-[11px] text-gray-600 dark:text-gray-300">
                          {team}
                        </div>
                      )}
                  </div>

                  {team &&
                    player && (
                      <div className="max-w-[80px] truncate text-right text-[9px] text-gray-500 dark:text-gray-400">
                        {team}
                      </div>
                    )}
                </div>
              );
            }
          )}
        </div>
      )}
    </div>
  );
}
