// src/contexts/BetslipContext.jsx

import React, {
  createContext,
  useContext,
  useState,
  useMemo,
  useEffect,
  useCallback,
} from "react";

const BetslipContext = createContext(null);

const BETSLIP_STORAGE_KEY = "betslip";
const MATCH_EXPIRY_MS = 3 * 60 * 60 * 1000;
const MIN_STAKE = 1;

// =========================================================
// HELPERS
// =========================================================

function getMatchId(match) {
  return (
    match?.match_id ??
    match?.id ??
    null
  );
}

function normalizeMarket(value) {
  return String(value || "")
    .trim()
    .toLowerCase();
}

function normalizeSelection(value) {
  return String(value || "")
    .trim()
    .toUpperCase();
}

function getBetMarket(bet) {
  return (
    bet?.market ??
    bet?.betMarket ??
    bet?.match?.market ??
    ""
  );
}

function isSameSelection(
  existing,
  matchId,
  market
) {
  const existingMatchId =
    getMatchId(existing?.match);

  const existingMarket =
    getBetMarket(existing);

  return (
    String(existingMatchId) ===
      String(matchId) &&
    normalizeMarket(existingMarket) ===
      normalizeMarket(market)
  );
}

function normalizeStoredBetslip(value) {
  if (!Array.isArray(value)) {
    return [];
  }

  return value;
}

// =========================================================
// PROVIDER
// =========================================================

export function BetslipProvider({
  children,
}) {
  const [betslip, setBetslip] =
    useState(() => {
      try {
        const saved =
          localStorage.getItem(
            BETSLIP_STORAGE_KEY
          );

        if (!saved) {
          return [];
        }

        return normalizeStoredBetslip(
          JSON.parse(saved)
        );
      } catch {
        return [];
      }
    });

  const [totalStake, setTotalStake] =
    useState(MIN_STAKE);

  // =======================================================
  // SYNC ACROSS TABS
  // =======================================================

  useEffect(() => {
    const syncTabs = (event) => {
      if (
        event.key !==
        BETSLIP_STORAGE_KEY
      ) {
        return;
      }

      try {
        const newData = JSON.parse(
          event.newValue || "[]"
        );

        const nextBetslip =
          normalizeStoredBetslip(
            newData
          );

        setBetslip((previous) => {
          if (
            JSON.stringify(previous) ===
            JSON.stringify(nextBetslip)
          ) {
            return previous;
          }

          return nextBetslip;
        });
      } catch {
        // Ignore malformed storage.
      }
    };

    window.addEventListener(
      "storage",
      syncTabs
    );

    return () => {
      window.removeEventListener(
        "storage",
        syncTabs
      );
    };
  }, []);

  // =======================================================
  // PERSIST BETSLIP
  // =======================================================

  useEffect(() => {
    try {
      localStorage.setItem(
        BETSLIP_STORAGE_KEY,
        JSON.stringify(betslip)
      );
    } catch {
      // Ignore storage failures.
    }
  }, [betslip]);

  // =======================================================
  // AUTO-EXPIRE
  // =======================================================

  useEffect(() => {
    if (!betslip.length) {
      return;
    }

    const now = Date.now();

    const filtered = betslip.filter(
      (bet) => {
        const kickoff =
          bet?.match?.kickoff ??
          bet?.match?.match_time;

        if (!kickoff) {
          return true;
        }

        const kickoffTime =
          new Date(kickoff).getTime();

        if (
          Number.isNaN(kickoffTime)
        ) {
          return true;
        }

        return (
          kickoffTime +
            MATCH_EXPIRY_MS >
          now
        );
      }
    );

    if (
      filtered.length !==
      betslip.length
    ) {
      setBetslip(filtered);
    }
  }, [betslip]);

  // =======================================================
  // CHECK PICKED
  // =======================================================

  const isPicked = useCallback(
    (matchId, selection) => {
      if (
        matchId == null ||
        !selection
      ) {
        return false;
      }

      return betslip.some((bet) => {
        const betMatchId =
          getMatchId(bet?.match);

        return (
          String(betMatchId) ===
            String(matchId) &&
          normalizeSelection(
            bet.selection
          ) ===
            normalizeSelection(selection)
        );
      });
    },
    [betslip]
  );

  // =======================================================
  // ADD ACCUMULATOR SELECTIONS
  // =======================================================

  const addBetslipSelections =
    useCallback(
      (selections = []) => {
        if (!Array.isArray(selections)) {
          return {
            added: 0,
            skipped: 0,
          };
        }

        let added = 0;
        let skipped = 0;

        setBetslip((previous) => {
          const next = [...previous];

          selections.forEach((item) => {
            const match =
              item?.match || {};

            const matchId =
              getMatchId(match);

            const market =
              item?.market || "";

            const selection =
              item?.selection || "";

            if (
              matchId == null ||
              !selection
            ) {
              skipped += 1;
              return;
            }

            const duplicate =
              next.some((existing) =>
                isSameSelection(
                  existing,
                  matchId,
                  market
                )
              );

            if (duplicate) {
              skipped += 1;
              return;
            }

            /*
             * IMPORTANT:
             * Accumulator selections intentionally
             * contain NO odds.
             */
            next.push({
              id: matchId,

              match: {
                id: matchId,
                match_id: matchId,
                home_team:
                  match.home_team || "",
                away_team:
                  match.away_team || "",
                match_time:
                  match.match_time || "",
                kickoff:
                  match.match_time || "",
                league:
                  match.league || "",
              },

              market,

              selection,

              stake: 0,

              addedAt: Date.now(),
            });

            added += 1;
          });

          return next;
        });

        return {
          added,
          skipped,
        };
      },
      []
    );

  // =======================================================
  // TOGGLE NORMAL BET
  // =======================================================

  const toggleBetslip =
    useCallback(
      (
        match,
        selection,
        odds,
        market = ""
      ) => {
        const matchId =
          getMatchId(match);

        if (matchId == null) {
          return;
        }

        setBetslip((previous) => {
          const existingIndex =
            previous.findIndex(
              (bet) =>
                isSameSelection(
                  bet,
                  matchId,
                  market
                )
            );

          const betData = {
            id: matchId,

            match: {
              ...match,
              id: matchId,
              match_id: matchId,
            },

            market,

            selection,

            odds: Number(
              odds ?? 0
            ),

            addedAt: Date.now(),
          };

          // Same match + same market
          if (existingIndex !== -1) {
            return previous.filter(
              (_, index) =>
                index !==
                existingIndex
            );
          }

          /*
           * Keep compatibility with the
           * existing normal match selection
           * behaviour.
           *
           * A different market can coexist.
           */
          return [
            ...previous,
            betData,
          ];
        });
      },
      []
    );

  // =======================================================
  // REMOVE BET
  // =======================================================

  const removeBet = useCallback(
    (matchId, market = null) => {
      setBetslip((previous) => {
        if (!market) {
          return previous.filter(
            (bet) =>
              String(
                getMatchId(
                  bet?.match
                )
              ) !==
              String(matchId)
          );
        }

        return previous.filter(
          (bet) =>
            !isSameSelection(
              bet,
              matchId,
              market
            )
        );
      });
    },
    []
  );

  // =======================================================
  // CLEAR
  // =======================================================

  const clearBetslip =
    useCallback(() => {
      setBetslip([]);
      setTotalStake(MIN_STAKE);
    }, []);

  // =======================================================
  // COMBINED ODDS
  // =======================================================

  const combinedOdds = useMemo(() => {
    if (!betslip.length) {
      return 0;
    }

    return betslip.reduce(
      (accumulator, bet) => {
        const odds =
          Number(bet?.odds);

        /*
         * Accumulator selections may not
         * contain odds. Treat those as 1
         * rather than producing NaN.
         */
        if (
          !Number.isFinite(odds) ||
          odds <= 0
        ) {
          return accumulator;
        }

        return (
          accumulator * odds
        );
      },
      1
    );
  }, [betslip]);

  // =======================================================
  // POTENTIAL WIN
  // =======================================================

  const potentialWin = useMemo(() => {
    if (
      !totalStake ||
      !combinedOdds
    ) {
      return 0;
    }

    return (
      totalStake *
      combinedOdds
    ).toFixed(2);
  }, [
    totalStake,
    combinedOdds,
  ]);

  // =======================================================
  // BACKEND PAYLOAD
  // =======================================================

  const getPayload =
    useCallback(() => {
      const stake = Math.max(
        Number(totalStake) || 0,
        MIN_STAKE
      );

      if (!betslip.length) {
        return {};
      }

      // Single selection
      if (betslip.length === 1) {
        const bet =
          betslip[0];

        return {
          match_id:
            getMatchId(
              bet?.match
            ),

          selection:
            bet.selection,

          stake,
        };
      }

      /*
       * IMPORTANT:
       * Do NOT send client_odds.
       *
       * The backend receives only the
       * match and selection information.
       */
      return {
        stake,

        selections:
          betslip.map(
            (bet) => ({
              match_id:
                getMatchId(
                  bet?.match
                ),

              selection:
                bet.selection,
            })
          ),
      };
    }, [
      betslip,
      totalStake,
    ]);

  // =======================================================
  // CONTEXT
  // =======================================================

  const contextValue = useMemo(
    () => ({
      betslip,

      setBetslip,

      toggleBetslip,

      addBetslipSelections,

      removeBet,

      clearBetslip,

      isPicked,

      combinedOdds,

      totalStake,

      setTotalStake,

      potentialWin,

      getPayload,
    }),
    [
      betslip,
      toggleBetslip,
      addBetslipSelections,
      removeBet,
      clearBetslip,
      isPicked,
      combinedOdds,
      totalStake,
      potentialWin,
      getPayload,
    ]
  );

  return (
    <BetslipContext.Provider
      value={contextValue}
    >
      {children}
    </BetslipContext.Provider>
  );
}

// =========================================================
// HOOK
// =========================================================

export function useBetslip() {
  const context =
    useContext(
      BetslipContext
    );

  if (!context) {
    throw new Error(
      "useBetslip must be used inside BetslipProvider"
    );
  }

  return context;
}
