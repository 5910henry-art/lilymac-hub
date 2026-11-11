export function normalizeId(id) {
  if (id === null || id === undefined) {
    return "";
  }

  return String(id);
}

export function normalizeStatus(status) {
  if (!status) {
    return "SCHEDULED";
  }

  const value = String(status).toUpperCase().trim();

  if (
    value === "LIVE" ||
    value === "IN_PLAY" ||
    value === "INPLAY" ||
    value === "RUNNING"
  ) {
    return "RUNNING";
  }

  if (
    value === "FINISHED" ||
    value === "FINISH" ||
    value === "COMPLETED" ||
    value === "COMPLETE" ||
    value === "ENDED" ||
    value === "END"
  ) {
    return "FINISHED";
  }

  return value;
}

export function isLiveMatch(match) {
  return normalizeStatus(match?.status) === "RUNNING";
}

export function isFinishedMatch(match) {
  return normalizeStatus(match?.status) === "FINISHED";
}

export function parseDate(value) {
  if (!value) {
    return null;
  }

  const date = new Date(value);

  return Number.isNaN(date.getTime()) ? null : date;
}

export function parseScore(match) {
  const home =
    match?.home_score ??
    match?.homeScore;

  const away =
    match?.away_score ??
    match?.awayScore;

  if (
    home !== undefined &&
    home !== null &&
    away !== undefined &&
    away !== null
  ) {
    return {
      home: Number(home) || 0,
      away: Number(away) || 0,
    };
  }

  const raw =
    match?.score ??
    match?.result ??
    "";

  if (typeof raw === "string") {
    const parts = raw.trim().split(/[-:]/);

    if (parts.length >= 2) {
      return {
        home: Number(parts[0]) || 0,
        away: Number(parts[1]) || 0,
      };
    }
  }

  return {
    home: 0,
    away: 0,
  };
}

export function getEventType(event) {
  if (!event) {
    return "Event";
  }

  const raw = String(
    event.type ??
      event.event_type ??
      event.event_name ??
      event.eventName ??
      event.name ??
      event.event ??
      ""
  ).trim();

  const description = String(
    event.description ??
      event.text ??
      event.commentary ??
      ""
  ).toLowerCase();

  const text = `${raw} ${description}`.toLowerCase();

  if (text.includes("own goal")) {
    return "Own goal";
  }

  if (
    text.includes("goal") ||
    text.includes("scored") ||
    text.includes("score")
  ) {
    return "Goal";
  }

  if (text.includes("yellow")) {
    return "Yellow card";
  }

  if (
    text.includes("red card") ||
    text.includes("sent off")
  ) {
    return "Red card";
  }

  if (text.includes("penalty")) {
    return "Penalty";
  }

  if (
    text.includes("substitution") ||
    text.includes("substitute")
  ) {
    return "Substitution";
  }

  if (text.includes("var")) {
    return "VAR";
  }

  if (text.includes("corner")) {
    return "Corner";
  }

  if (text.includes("free kick")) {
    return "Free kick";
  }

  return raw || "Event";
}

export function getEventPlayer(event) {
  if (!event) {
    return "";
  }

  if (typeof event.player === "string") {
    return event.player;
  }

  return (
    event.player?.name ||
    event.player?.short_name ||
    event.player_name ||
    (typeof event.scorer === "string"
      ? event.scorer
      : event.scorer?.name ||
        event.scorer?.short_name ||
        "") ||
    ""
  );
}

export function getEventTeam(event) {
  if (!event) {
    return "";
  }

  if (typeof event.team === "string") {
    return event.team;
  }

  return (
    event.team?.name ||
    event.team?.short_name ||
    event.team_name ||
    ""
  );
}

export function getEventMinute(event) {
  if (!event) {
    return "";
  }

  return (
    event.minute ??
    event.min ??
    event.elapsed ??
    event.time ??
    ""
  );
}

export function getEventKey(event, index = 0) {
  if (!event) {
    return `event-${index}`;
  }

  if (
    event.id !== undefined &&
    event.id !== null
  ) {
    return `id-${event.id}`;
  }

  if (
    event.event_id !== undefined &&
    event.event_id !== null
  ) {
    return `event-id-${event.event_id}`;
  }

  return [
    getEventMinute(event),
    getEventType(event),
    getEventPlayer(event),
    getEventTeam(event),
    event.description ??
      event.text ??
      "",
  ].join("|");
}

export function extractMatchEvents(match) {
  if (!match) {
    return [];
  }

  const value =
    match.events ??
    match.live_events ??
    match.match_events ??
    match.timeline ??
    match.match_timeline ??
    [];

  if (Array.isArray(value)) {
    return value;
  }

  if (
    value &&
    typeof value === "object"
  ) {
    return [value];
  }

  return [];
}

export function extractSocketEvent(payload) {
  if (!payload) {
    return null;
  }

  if (
    payload.event &&
    typeof payload.event === "object"
  ) {
    return payload.event;
  }

  if (
    typeof payload.event === "string" &&
    payload.event.trim()
  ) {
    return {
      type: payload.event,
      minute:
        payload.minute ??
        payload.min ??
        payload.elapsed ??
        payload.time,
      player:
        payload.player ??
        payload.player_name ??
        payload.scorer,
      team:
        payload.team ??
        payload.team_name,
      description:
        payload.description ??
        payload.text ??
        payload.commentary,
    };
  }

  if (
    payload.match_event &&
    typeof payload.match_event === "object"
  ) {
    return payload.match_event;
  }

  if (
    payload.live_event &&
    typeof payload.live_event === "object"
  ) {
    return payload.live_event;
  }

  if (
    payload.data &&
    typeof payload.data === "object"
  ) {
    if (
      payload.data.event &&
      typeof payload.data.event === "object"
    ) {
      return payload.data.event;
    }

    if (
      payload.data.type ||
      payload.data.event_type ||
      payload.data.event_name ||
      payload.data.eventName ||
      payload.data.description ||
      payload.data.text ||
      payload.data.commentary
    ) {
      return payload.data;
    }
  }

  if (
    payload.type ||
    payload.event_type ||
    payload.event_name ||
    payload.eventName ||
    payload.description ||
    payload.text ||
    payload.commentary
  ) {
    return payload;
  }

  return null;
}

export function formatEvent(event) {
  if (!event) {
    return "";
  }

  const minute = getEventMinute(event);
  const type = getEventType(event);
  const player = getEventPlayer(event);

  const icons = {
    Goal: "⚽",
    "Own goal": "⚽",
    "Yellow card": "🟨",
    "Red card": "🟥",
    Penalty: "⚽",
    Substitution: "🔄",
    VAR: "📺",
    Corner: "🚩",
    "Free kick": "🦶",
    Shot: "🎯",
    Miss: "❌",
  };

  const icon = icons[type] || "•";

  let minuteText = "";

  if (
    minute !== "" &&
    minute !== null &&
    minute !== undefined
  ) {
    const value = String(minute).trim();

    minuteText = value.endsWith("'")
      ? value
      : `${value}'`;
  }

  let result = "";

  if (minuteText) {
    result += `${minuteText}  `;
  }

  result += `${icon} ${type}`;

  if (player) {
    result += ` • ${player}`;
  }

  return result;
}

export function normalizeRoundsResponse(data) {
  if (Array.isArray(data)) {
    return data;
  }

  if (Array.isArray(data?.rounds)) {
    return data.rounds;
  }

  if (Array.isArray(data?.data)) {
    return data.data;
  }

  return [];
}

export function normalizeMatchesResponse(data) {
  if (Array.isArray(data)) {
    return data;
  }

  if (Array.isArray(data?.matches)) {
    return data.matches;
  }

  if (Array.isArray(data?.fixtures)) {
    return data.fixtures;
  }

  if (Array.isArray(data?.data)) {
    return data.data;
  }

  return [];
}

export function pickNextAvailableRound(rounds) {
  if (
    !Array.isArray(rounds) ||
    rounds.length === 0
  ) {
    return null;
  }

  return (
    rounds.find((round) => {
      const status =
        String(
          round?.status || ""
        ).toUpperCase();

      return (
        status === "OPEN" ||
        status === "SCHEDULED" ||
        status === "RUNNING"
      );
    }) ||
    rounds[0]
  );
}
