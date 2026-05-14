import React, { useEffect, useState } from "react";
import VirtualAPI from "../api/virtualAPI";

export default function MatchEvents({ matchId }) {
  const [events, setEvents] = useState([]);

  useEffect(() => {
    const stop = VirtualAPI.liveEvents(matchId, (data) => {
      if (Array.isArray(data)) setEvents(data);
    });

    return () => stop();
  }, [matchId]);

  return (
    <div className="events">
      {events.map((e, i) => (
        <div key={i} className="event">
          {e.minute}' {e.type} - {e.team}
        </div>
      ))}
    </div>
  );
}
