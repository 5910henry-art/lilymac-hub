// src/components/Virtual.js

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import VirtualAPI from "../api/virtualAPI";
import VirtualSocket from "../api/virtualSocket";
import "../styles/virtual.css";
import { useUser } from "../contexts/UserContext";

import VirtualLoading from "./virtual/VirtualLoading";
import VirtualRounds from "./virtual/VirtualRounds";
import VirtualMatch from "./virtual/VirtualMatch";
import VirtualBetSlip from "./virtual/VirtualBetSlip";

import {
  normalizeId,
  normalizeStatus,
  isLiveMatch,
  isFinishedMatch,
  parseDate,
  extractMatchEvents,
  extractSocketEvent,
  getEventKey,
  normalizeRoundsResponse,
  normalizeMatchesResponse,
  pickNextAvailableRound,
} from "../utils/virtualHelpers";

export default function VirtualSportsbook() {
  const {
    updateBalance,
    reloadUser,
  } = useUser();

  // ============================================================
  // STATE
  // ============================================================

  const [rounds, setRounds] = useState([]);
  const [selectedRound, setSelectedRound] = useState(null);
  const [highlightedRound, setHighlightedRound] = useState(null);
  const [manualRoundSelect, setManualRoundSelect] = useState(false);

  const [matches, setMatches] = useState([]);
  const [market, setMarket] = useState("1X2");

  const [bets, setBets] = useState([]);
  const [stake, setStake] = useState("");

  const [events, setEvents] = useState({});
  const [oddsFlash, setOddsFlash] = useState({});

  const [isOffline, setIsOffline] = useState(false);
  const [loadingMatches, setLoadingMatches] = useState(false);
  const [transitioningRound, setTransitioningRound] = useState(false);

  const [toast, setToast] = useState(null);
  const [now, setNow] = useState(Date.now());

  // ============================================================
  // REFS
  // ============================================================

  const mountedRef = useRef(false);

  const loadingRoundRef = useRef(false);
  const loadingRoundsRef = useRef(false);

  const loadingEventsRef = useRef(false);

  const liveUpdatesRef = useRef({});
  const liveEventsRef = useRef({});
  const prevOddsRef = useRef({});

  const inputRef = useRef(null);
  const toastTimerRef = useRef(null);
  const oddsFlashTimerRef = useRef(null);

  // ============================================================
  // POLLING
  // ============================================================

  // API = initial state + fallback synchronization.
  // Socket.IO = real-time updates.
  const ROUND_POLL_INTERVAL = 3000;
  const ROUNDS_REFRESH_INTERVAL = 5000;
  const EVENTS_POLL_INTERVAL = 1500;

  const MATCH_DELAY = 30000;

  // ============================================================
  // CLOCK
  // ============================================================

  useEffect(() => {
    mountedRef.current = true;

    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);

    return () => {
      mountedRef.current = false;
      clearInterval(timer);

      if (toastTimerRef.current) {
        clearTimeout(toastTimerRef.current);
      }

      if (oddsFlashTimerRef.current) {
        clearTimeout(oddsFlashTimerRef.current);
      }
    };
  }, []);

  // ============================================================
  // TOAST
  // ============================================================

  const showToast = useCallback(
    (message, type = "info") => {
      if (!mountedRef.current) {
        return;
      }

      setToast({
        message,
        type,
      });

      if (toastTimerRef.current) {
        clearTimeout(toastTimerRef.current);
      }

      toastTimerRef.current = setTimeout(() => {
        if (mountedRef.current) {
          setToast(null);
        }
      }, 2500);
    },
    []
  );

  // ============================================================
  // ROUND HELPERS
  // ============================================================

  const getRoundStatus = useCallback(
    (round) => {
      return String(
        round?.status || "SCHEDULED"
      ).toUpperCase();
    },
    []
  );

  const parseUTCtoLocal = useCallback(
    (value) => {
      return parseDate(value) || new Date();
    },
    []
  );

  const formatCountdown = useCallback(
    (round) => {
      if (!round) {
        return "";
      }

      if (
        typeof round.time_to_start ===
        "number"
      ) {
        const seconds = Math.max(
          0,
          Math.floor(
            round.time_to_start
          )
        );

        if (!seconds) {
          return getRoundStatus(
            round
          ) === "RUNNING"
            ? "LIVE"
            : "0:00";
        }

        return `${Math.floor(
          seconds / 60
        )}:${String(
          seconds % 60
        ).padStart(2, "0")}`;
      }

      const start =
        parseDate(
          round.start_time
        ) ||
        (() => {
          const open =
            parseDate(
              round.open_time
            );

          return open
            ? new Date(
                open.getTime() +
                  MATCH_DELAY
              )
            : null;
        })();

      if (!start) {
        return "";
      }

      const seconds = Math.max(
        0,
        Math.floor(
          (
            start.getTime() -
            now
          ) / 1000
        )
      );

      if (!seconds) {
        return getRoundStatus(
          round
        ) === "RUNNING"
          ? "LIVE"
          : "0:00";
      }

      return `${Math.floor(
        seconds / 60
      )}:${String(
        seconds % 60
      ).padStart(2, "0")}`;
    },
    [
      getRoundStatus,
      now,
    ]
  );

  // ============================================================
  // EVENT MERGING
  // ============================================================

  const mergeEvents = useCallback(
    (matchId, incoming = []) => {
      const id =
        normalizeId(matchId);

      if (
        !id ||
        !Array.isArray(incoming) ||
        !incoming.length
      ) {
        return;
      }

      const existing =
        liveEventsRef.current[id] ||
        [];

      const merged = [
        ...existing,
        ...incoming,
      ];

      const seen = new Set();

      const unique = merged.filter(
        (event, index) => {
          if (!event) {
            return false;
          }

          const key =
            getEventKey(
              event,
              index
            );

          if (
            seen.has(key)
          ) {
            return false;
          }

          seen.add(key);
          return true;
        }
      );

      const latest =
        unique.slice(-30);

      liveEventsRef.current[id] =
        latest;

      if (!mountedRef.current) {
        return;
      }

      setEvents((previous) => ({
        ...previous,
        [id]: latest,
      }));
    },
    []
  );

  // ============================================================
  // LOAD EVENTS
  // ============================================================

  const loadMatchEvents =
    useCallback(
      async (activeMatches) => {
        if (
          !Array.isArray(
            activeMatches
          ) ||
          !activeMatches.length ||
          loadingEventsRef.current
        ) {
          return;
        }

        loadingEventsRef.current =
          true;

        try {
          await Promise.all(
            activeMatches.map(
              async (match) => {
                const id =
                  normalizeId(
                    match?.id
                  );

                if (!id) {
                  return;
                }

                try {
                  const response =
                    await VirtualAPI.getEvents(
                      id
                    );

                  if (
                    !mountedRef.current
                  ) {
                    return;
                  }

                  const apiEvents =
                    Array.isArray(
                      response
                    )
                      ? response
                      : Array.isArray(
                          response?.events
                        )
                      ? response.events
                      : Array.isArray(
                          response?.data
                        )
                      ? response.data
                      : [];

                  if (
                    apiEvents.length
                  ) {
                    mergeEvents(
                      id,
                      apiEvents
                    );
                  }
                } catch (error) {
                  console.error(
                    `Failed loading events for match ${id}:`,
                    error
                  );
                }
              }
            )
          );
        } finally {
          loadingEventsRef.current =
            false;
        }
      },
      [mergeEvents]
    );

  // ============================================================
  // LOAD ROUNDS
  // ============================================================

  const refreshRounds =
    useCallback(
      async () => {
        if (
          loadingRoundsRef.current
        ) {
          return;
        }

        loadingRoundsRef.current =
          true;

        try {
          const response =
            await VirtualAPI.getRounds();

          if (
            !mountedRef.current
          ) {
            return;
          }

          const data =
            normalizeRoundsResponse(
              response
            );

          if (!data.length) {
            setRounds([]);
            setIsOffline(true);
            return;
          }

          setRounds(data);
          setIsOffline(false);

          const current =
            data.find(
              (round) =>
                normalizeId(
                  round.round ??
                    round.id
                ) ===
                normalizeId(
                  selectedRound
                )
            );

          if (!current) {
            const next =
              pickNextAvailableRound(
                data
              );

            if (next) {
              const id =
                next.round ??
                next.id;

              setSelectedRound(id);
              setHighlightedRound(id);
              setManualRoundSelect(
                false
              );
              setTransitioningRound(
                false
              );
            }

            return;
          }

          if (
            getRoundStatus(
              current
            ) === "FINISHED" &&
            !manualRoundSelect
          ) {
            const next =
              pickNextAvailableRound(
                data
              );

            if (
              next &&
              normalizeId(
                next.round ??
                  next.id
              ) !==
                normalizeId(
                  selectedRound
                )
            ) {
              const id =
                next.round ??
                next.id;

              setTransitioningRound(
                true
              );
              setSelectedRound(id);
              setHighlightedRound(
                id
              );
            }
          }
        } catch (error) {
          console.error(
            "Failed loading virtual rounds:",
            error
          );

          if (
            mountedRef.current
          ) {
            setIsOffline(true);
          }
        } finally {
          loadingRoundsRef.current =
            false;
        }
      },
      [
        getRoundStatus,
        manualRoundSelect,
        selectedRound,
      ]
    );

  useEffect(() => {
    refreshRounds();

    const timer =
      setInterval(
        refreshRounds,
        ROUNDS_REFRESH_INTERVAL
      );

    return () =>
      clearInterval(timer);
  }, [refreshRounds]);

  // ============================================================
  // RESET ROUND DATA
  // ============================================================

  useEffect(() => {
    if (
      selectedRound === null ||
      selectedRound === undefined
    ) {
      return;
    }

    liveUpdatesRef.current = {};
    liveEventsRef.current = {};
    prevOddsRef.current = {};

    setEvents({});
    setOddsFlash({});
    setMatches([]);
  }, [selectedRound]);

  // ============================================================
  // LOAD ROUND MATCHES
  // ============================================================

  const loadRoundMatches =
    useCallback(
      async () => {
        if (
          selectedRound === null ||
          selectedRound === undefined ||
          loadingRoundRef.current
        ) {
          return;
        }

        loadingRoundRef.current =
          true;

        if (
          mountedRef.current
        ) {
          setLoadingMatches(true);
        }

        try {
          const response =
            await VirtualAPI.getRoundMatches(
              selectedRound
            );

          if (
            !mountedRef.current
          ) {
            return;
          }

          const raw =
            normalizeMatchesResponse(
              response
            );

          const active =
            raw.filter(
              (match) =>
                !isFinishedMatch(
                  match
                )
            );

          // ======================================================
          // WHOLE ROUND FINISHED
          // ======================================================

          if (
            raw.length > 0 &&
            active.length === 0
          ) {
            const next =
              pickNextAvailableRound(
                rounds
              );

            if (
              next &&
              normalizeId(
                next.round ??
                  next.id
              ) !==
                normalizeId(
                  selectedRound
                )
            ) {
              const id =
                next.round ??
                next.id;

              setTransitioningRound(
                true
              );
              setSelectedRound(id);
              setHighlightedRound(
                id
              );
              setManualRoundSelect(
                false
              );

              return;
            }

            setMatches([]);
            return;
          }

          // ======================================================
          // EVENTS EMBEDDED IN MATCH
          // ======================================================

          active.forEach(
            (match) => {
              const history =
                extractMatchEvents(
                  match
                );

              if (
                history.length
              ) {
                mergeEvents(
                  match.id,
                  history
                );
              }
            }
          );

          // ======================================================
          // FETCH ACTUAL EVENT HISTORY
          // ======================================================

          loadMatchEvents(
            active
          );

          // ======================================================
          // ODDS FLASH
          // ======================================================

          const flash = {};

          active.forEach(
            (match) => {
              if (!match.odds) {
                return;
              }

              const id =
                normalizeId(
                  match.id
                );

              const previous =
                prevOddsRef.current[
                  id
                ] || {};

              const changes = {};

              Object.keys(
                match.odds
              ).forEach(
                (key) => {
                  if (
                    previous[key] !==
                      undefined &&
                    Number(
                      previous[key]
                    ) !==
                      Number(
                        match.odds[key]
                      )
                  ) {
                    changes[key] =
                      Number(
                        match.odds[
                          key
                        ]
                      ) >
                      Number(
                        previous[
                          key
                        ]
                      )
                        ? "up"
                        : "down";
                  }
                }
              );

              if (
                Object.keys(
                  changes
                ).length
              ) {
                flash[id] =
                  changes;
              }

              prevOddsRef.current[
                id
              ] = {
                ...match.odds,
              };
            }
          );

          if (
            Object.keys(flash)
              .length
          ) {
            setOddsFlash(
              flash
            );

            if (
              oddsFlashTimerRef.current
            ) {
              clearTimeout(
                oddsFlashTimerRef.current
              );
            }

            oddsFlashTimerRef.current =
              setTimeout(() => {
                if (
                  mountedRef.current
                ) {
                  setOddsFlash(
                    {}
                  );
                }
              }, 900);
          }

          // ======================================================
          // MERGE MATCH + SOCKET DATA
          // ======================================================

          const merged =
            active.map(
              (match) => {
                const id =
                  normalizeId(
                    match.id
                  );

                const socket =
                  liveUpdatesRef.current[
                    id
                  ];

                const socketEvents =
                  liveEventsRef.current[
                    id
                  ] || [];

                return {
                  ...match,
                  ...(socket || {}),
                  events:
                    socketEvents.length
                      ? socketEvents
                      : extractMatchEvents(
                          match
                        ),
                };
              }
            );

          setMatches(
            merged
          );

          setIsOffline(false);
          setTransitioningRound(
            false
          );
        } catch (error) {
          console.error(
            "Failed loading virtual matches:",
            error
          );

          if (
            mountedRef.current
          ) {
            setIsOffline(true);
          }
        } finally {
          loadingRoundRef.current =
            false;

          if (
            mountedRef.current
          ) {
            setLoadingMatches(
              false
            );
          }
        }
      },
      [
        loadMatchEvents,
        mergeEvents,
        rounds,
        selectedRound,
      ]
    );

  useEffect(() => {
    if (
      selectedRound === null ||
      selectedRound === undefined
    ) {
      return undefined;
    }

    loadRoundMatches();

    const timer =
      setInterval(
        loadRoundMatches,
        ROUND_POLL_INTERVAL
      );

    return () =>
      clearInterval(timer);
  }, [
    loadRoundMatches,
    selectedRound,
  ]);

  // ============================================================
  // LIVE EVENT POLLING
  // ============================================================

  useEffect(() => {
    const liveMatches =
      matches.filter(
        (match) =>
          isLiveMatch(match)
      );

    if (!liveMatches.length) {
      return undefined;
    }

    loadMatchEvents(
      liveMatches
    );

    const timer =
      setInterval(() => {
        const currentLiveMatches =
          matches.filter(
            (match) =>
              isLiveMatch(
                match
              )
          );

        if (
          currentLiveMatches.length
        ) {
          loadMatchEvents(
            currentLiveMatches
          );
        }
      }, EVENTS_POLL_INTERVAL);

    return () =>
      clearInterval(timer);
  }, [
    matches,
    loadMatchEvents,
  ]);

  // ============================================================
  // SOCKET.IO
  // ============================================================

  useEffect(() => {
    let active = true;

    try {
      VirtualSocket.connect();
    } catch (error) {
      console.error(
        "Virtual socket error:",
        error
      );
    }

    // ==========================================================
    // MATCH UPDATE
    // ==========================================================

    const handleUpdate =
      (payload) => {
        if (
          !active ||
          !payload
        ) {
          return;
        }

        const id =
          normalizeId(
            payload.match_id ??
              payload.matchId ??
              payload.match?.id ??
              payload.fixture_id ??
              payload.id
          );

        if (!id) {
          return;
        }

        const event =
          extractSocketEvent(
            payload
          );

        if (event) {
          mergeEvents(
            id,
            [event]
          );
        }

        const update = {
          ...(payload.match ||
            {}),
          ...payload,
        };

        delete update.event;

        const hasStatus =
          payload.status !==
            undefined ||
          payload.match?.status !==
            undefined;

        if (hasStatus) {
          update.status =
            normalizeStatus(
              payload.status ??
                payload.match
                  ?.status
            );
        }

        const hasScore =
          payload.home_score !==
            undefined ||
          payload.away_score !==
            undefined ||
          payload.homeScore !==
            undefined ||
          payload.awayScore !==
            undefined ||
          payload.score !==
            undefined ||
          payload.result !==
            undefined;

        if (hasScore) {
          const home =
            payload.home_score ??
            payload.homeScore;

          const away =
            payload.away_score ??
            payload.awayScore;

          if (
            home !==
              undefined &&
            away !==
              undefined
          ) {
            update.home_score =
              Number(home) ||
              0;

            update.away_score =
              Number(away) ||
              0;
          } else if (
            typeof payload.score ===
              "string"
          ) {
            const parts =
              payload.score.split(
                /[-:]/
              );

            if (
              parts.length >=
              2
            ) {
              update.home_score =
                Number(
                  parts[0]
                ) || 0;

              update.away_score =
                Number(
                  parts[1]
                ) || 0;
            }
          }
        }

        liveUpdatesRef.current[
          id
        ] = {
          ...liveUpdatesRef.current[
            id
          ],
          ...update,
        };

        if (
          normalizeStatus(
            update.status
          ) === "FINISHED"
        ) {
          setMatches(
            (previous) =>
              previous.filter(
                (match) =>
                  normalizeId(
                    match.id
                  ) !== id
              )
          );

          return;
        }

        setIsOffline(false);

        setMatches(
          (previous) =>
            previous.map(
              (match) => {
                if (
                  normalizeId(
                    match.id
                  ) !== id
                ) {
                  return match;
                }

                return {
                  ...match,
                  ...update,
                  events:
                    liveEventsRef
                      .current[id] ||
                    match.events ||
                    [],
                };
              }
            )
        );
      };

    // ==========================================================
    // MATCH EVENT
    // ==========================================================

    const handleEvent =
      (payload) => {
        if (
          !active ||
          !payload
        ) {
          return;
        }

        const id =
          normalizeId(
            payload.match_id ??
              payload.matchId ??
              payload.match?.id ??
              payload.event
                ?.match_id ??
              payload.match_event
                ?.match_id
          );

        if (!id) {
          return;
        }

        const event =
          extractSocketEvent(
            payload
          );

        if (!event) {
          return;
        }

        mergeEvents(
          id,
          [event]
        );
      };

    const stopUpdate =
      VirtualSocket.on(
        "virtual_match_update",
        handleUpdate
      );

    const stopLegacyUpdate =
      VirtualSocket.on(
        "match_update",
        handleUpdate
      );

    const stopEvent =
      VirtualSocket.on(
        "virtual_match_event",
        handleEvent
      );

    const stopLegacyEvent =
      VirtualSocket.on(
        "match_event",
        handleEvent
      );

    const stopFinished =
      VirtualSocket.on(
        "virtual_match_finished",
        (payload) => {
          if (!active) {
            return;
          }

          const id =
            normalizeId(
              payload?.match_id ??
                payload?.matchId ??
                payload?.id
            );

          if (id) {
            setMatches(
              (previous) =>
                previous.filter(
                  (match) =>
                    normalizeId(
                      match.id
                    ) !== id
                )
            );
          }
        }
      );

    return () => {
      active = false;

      stopUpdate?.();
      stopLegacyUpdate?.();
      stopEvent?.();
      stopLegacyEvent?.();
      stopFinished?.();
    };
  }, [mergeEvents]);

  // ============================================================
  // BETTING
  // ============================================================

  const toggleBet =
    useCallback(
      (
        match,
        selection,
        odd
      ) => {
        if (
          !match ||
          isLiveMatch(
            match
          ) ||
          isFinishedMatch(
            match
          )
        ) {
          if (
            isLiveMatch(
              match
            )
          ) {
            showToast(
              "This match is LIVE.",
              "error"
            );
          }

          return;
        }

        const id =
          `${normalizeId(
            match.id
          )}-${selection}`;

        if (
          bets.some(
            (bet) =>
              bet.id === id
          )
        ) {
          setBets(
            (previous) =>
              previous.filter(
                (bet) =>
                  bet.id !==
                  id
              )
          );

          return;
        }

        setBets(
          (previous) => [
            ...previous,
            {
              id,
              matchId:
                match.id,
              home:
                match.home,
              away:
                match.away,
              selection,
              odd: Number(odd),
            },
          ]
        );
      },
      [bets, showToast]
    );

  // ============================================================
  // COMBINED ODDS
  // ============================================================

  const combinedOdds =
    useMemo(() => {
      if (!bets.length) {
        return "0.00";
      }

      return bets
        .reduce(
          (total, bet) =>
            total *
            Number(
              bet.odd
            ),
          1
        )
        .toFixed(2);
    }, [bets]);

  // ============================================================
  // POTENTIAL WIN
  // ============================================================

  const potentialWin =
    useMemo(() => {
      const amount =
        Number(stake);

      if (
        !Number.isFinite(
          amount
        ) ||
        amount <= 0
      ) {
        return "0.00";
      }

      return (
        amount *
        Number(
          combinedOdds
        )
      ).toFixed(2);
    }, [
      combinedOdds,
      stake,
    ]);

  // ============================================================
  // PLACE BET
  // ============================================================

  const placeBet =
    useCallback(
      async () => {
        if (isOffline) {
          showToast(
            "No connection. Try again.",
            "error"
          );
          return;
        }

        if (!bets.length) {
          showToast(
            "Select at least one selection.",
            "error"
          );
          return;
        }

        const amount =
          Number(stake);

        if (
          !Number.isFinite(
            amount
          ) ||
          amount <= 0
        ) {
          showToast(
            "Enter a valid stake.",
            "error"
          );
          return;
        }

        const selections =
          bets.map(
            (bet) => ({
              match_id:
                bet.matchId,
              selection:
                bet.selection,
            })
          );

        try {
          const response =
            await VirtualAPI.placeBet(
              {
                stake: amount,
                selections,
                bets: selections,
              }
            );

          if (
            response?.success ===
            false
          ) {
            throw new Error(
              response.error ||
                "Bet failed."
            );
          }

          if (
            response?.data
              ?.success ===
            false
          ) {
            throw new Error(
              response.data
                .error ||
                response.data
                  .detail ||
                "Bet failed."
            );
          }

          showToast(
            "Bet placed successfully!",
            "success"
          );

          setBets([]);
          setStake("");

          updateBalance(
            (previous) =>
              Number(
                previous || 0
              ) - amount
          );

          reloadUser().catch(
            () => {}
          );
        } catch (error) {
          console.error(
            "Virtual bet failed:",
            error
          );

          showToast(
            error.message ||
              "Network error. Please try again.",
            "error"
          );
        }
      },
      [
        bets,
        isOffline,
        reloadUser,
        showToast,
        stake,
        updateBalance,
      ]
    );

  // ============================================================
  // MATCH TIMER
  // ============================================================

  const getTimer =
    useCallback(
      (match) => {
        if (!match) {
          return "";
        }

        const status =
          normalizeStatus(
            match.status
          );

        if (
          status ===
          "RUNNING"
        ) {
          const end =
            parseDate(
              match.end_time
            );

          if (end) {
            return `${Math.max(
              0,
              Math.ceil(
                (
                  end.getTime() -
                  now
                ) / 1000
              )
            )}s`;
          }

          if (
            match.time_to_end !==
              undefined &&
            match.time_to_end !==
              null
          ) {
            return `${Math.max(
              0,
              Math.ceil(
                Number(
                  match.time_to_end
                ) || 0
              )
            )}s`;
          }

          return "Live";
        }

        if (
          status === "OPEN"
        ) {
          const start =
            parseDate(
              match.start_time
            );

          if (start) {
            const seconds =
              Math.max(
                0,
                Math.ceil(
                  (
                    start.getTime() -
                    now
                  ) / 1000
                )
              );

            return seconds
              ? `${seconds}s`
              : "Starting";
          }
        }

        return "";
      },
      [now]
    );

  // ============================================================
  // MARKETS
  // ============================================================

  const getMarketButtons =
    useCallback(
      (odds) => {
        const safe =
          odds || {};

        if (
          market === "BTTS"
        ) {
          return [
            {
              key: "btts_yes",
              label: "Yes",
              odd: safe.btts_yes,
            },
            {
              key: "btts_no",
              label: "No",
              odd: safe.btts_no,
            },
          ];
        }

        if (
          market === "OU15"
        ) {
          return [
            {
              key: "over15",
              label: "O1.5",
              odd: safe.over15,
            },
            {
              key: "under15",
              label: "U1.5",
              odd: safe.under15,
            },
          ];
        }

        if (
          market === "OU25"
        ) {
          return [
            {
              key: "over25",
              label: "O2.5",
              odd: safe.over25,
            },
            {
              key: "under25",
              label: "U2.5",
              odd: safe.under25,
            },
          ];
        }

        return [
          {
            key: "home",
            label: "1",
            odd: safe.home,
          },
          {
            key: "draw",
            label: "X",
            odd: safe.draw,
          },
          {
            key: "away",
            label: "2",
            odd: safe.away,
          },
        ];
      },
      [market]
    );

  // ============================================================
  // SELECTED BET
  // ============================================================

  const isSelected =
    useCallback(
      (
        matchId,
        selection
      ) =>
        bets.some(
          (bet) =>
            normalizeId(
              bet.matchId
            ) ===
              normalizeId(
                matchId
              ) &&
            bet.selection ===
              selection
        ),
      [bets]
    );

  // ============================================================
  // UI
  // ============================================================

  return (
    <div className="virtualPage">

      <VirtualRounds
        rounds={rounds}
        selectedRound={
          selectedRound
        }
        highlightedRound={
          highlightedRound
        }
        getStatus={
          getRoundStatus
        }
        getCountdown={
          formatCountdown
        }
        normalizeId={
          normalizeId
        }
        parseUTCtoLocal={
          parseUTCtoLocal
        }
        onSelect={(id) => {
          setSelectedRound(
            id
          );
          setHighlightedRound(
            id
          );
          setManualRoundSelect(
            true
          );
          setTransitioningRound(
            false
          );
        }}
      />

      <div className="marketTabs">
        {[
          "1X2",
          "BTTS",
          "OU15",
          "OU25",
        ].map((name) => (
          <button
            key={name}
            type="button"
            className={
              market === name
                ? "active"
                : ""
            }
            onClick={() =>
              setMarket(
                name
              )
            }
          >
            {name}
          </button>
        ))}
      </div>

      <div className="matchList">

        {loadingMatches &&
          !matches.length &&
          !transitioningRound && (
            <VirtualLoading
              rows={5}
            />
          )}

        {transitioningRound && (
          <VirtualLoading
            rows={5}
          />
        )}

        {matches
          .filter(
            (match) =>
              !isFinishedMatch(
                match
              )
          )
          .map((match) => {
            const id =
              normalizeId(
                match.id
              );

            return (
              <VirtualMatch
                key={id}
                match={{
                  ...match,
                  events:
                    events[id] ||
                    extractMatchEvents(
                      match
                    ),
                }}
                odds={
                  match.odds ||
                  {}
                }
                flash={
                  oddsFlash[id] ||
                  {}
                }
                marketButtons={
                  getMarketButtons(
                    match.odds ||
                      {}
                  )
                }
                isSelected={
                  isSelected
                }
                onSelectBet={
                  toggleBet
                }
                getTimer={
                  getTimer
                }
                onOpen={() => {}}
              />
            );
          })}

        {!loadingMatches &&
          !transitioningRound &&
          !matches.length &&
          !isOffline && (
            <VirtualLoading
              rows={3}
            />
          )}

        {isOffline && (
          <VirtualLoading
            rows={4}
          />
        )}

      </div>

      <VirtualBetSlip
        bets={bets}
        stake={stake}
        setStake={setStake}
        inputRef={inputRef}
        combinedOdds={
          combinedOdds
        }
        potentialWin={
          potentialWin
        }
        placeBet={placeBet}
        isOffline={isOffline}
      />

      {toast && (
        <div
          style={{
            position: "fixed",
            bottom: "120px",
            left: "50%",
            transform:
              "translateX(-50%)",
            background:
              toast.type ===
              "success"
                ? "#16a34a"
                : toast.type ===
                  "error"
                ? "#dc2626"
                : "#334155",
            color: "#fff",
            padding:
              "12px 20px",
            borderRadius:
              "10px",
            fontWeight:
              "bold",
            boxShadow:
              "0 5px 20px rgba(0,0,0,0.3)",
            zIndex: 9999,
            maxWidth:
              "90vw",
            textAlign:
              "center",
          }}
        >
          {toast.message}
        </div>
      )}

    </div>
  );
}
