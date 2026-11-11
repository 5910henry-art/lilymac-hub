// src/contexts/UserContext.jsx

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
} from "react";

import * as api from "../api/betsWallet";
import { getAuthToken, clearToken } from "../api/core";

const UserContext = createContext(null);

// ==================================================
// HELPERS
// ==================================================

function ensureArray(v) {
  if (!v) return [];

  if (Array.isArray(v)) return v;

  if (Array.isArray(v.data)) return v.data;

  if (Array.isArray(v.transactions)) {
    return v.transactions;
  }

  if (Array.isArray(v.history)) {
    return v.history;
  }

  if (Array.isArray(v.data?.transactions)) {
    return v.data.transactions;
  }

  if (Array.isArray(v.data?.data?.transactions)) {
    return v.data.data.transactions;
  }

  if (Array.isArray(v.data?.history)) {
    return v.data.history;
  }

  return [];
}

function extractPayload(res) {
  return res?.data?.data || res?.data || res || {};
}

function extractBalance(res, fallback = null) {
  const data = extractPayload(res);

  const value =
    data?.balance ??
    data?.user?.balance ??
    res?.balance ??
    res?.data?.balance ??
    fallback;

  if (value == null) return fallback;

  const numeric = Number(value);

  return Number.isFinite(numeric)
    ? numeric
    : fallback;
}

function extractBonusBalance(res, fallback = null) {
  const data = extractPayload(res);

  const value =
    data?.bonusBalance ??
    data?.bonus_balance ??
    data?.user?.bonusBalance ??
    data?.user?.bonus_balance ??
    res?.bonusBalance ??
    res?.bonus_balance ??
    fallback;

  if (value == null) return fallback;

  const numeric = Number(value);

  return Number.isFinite(numeric)
    ? numeric
    : fallback;
}

function sameArrayReferenceContents(a, b) {
  if (a === b) return true;

  if (!Array.isArray(a) || !Array.isArray(b)) {
    return false;
  }

  if (a.length !== b.length) {
    return false;
  }

  for (let i = 0; i < a.length; i += 1) {
    const oldItem = a[i];
    const newItem = b[i];

    if (
      oldItem === newItem
    ) {
      continue;
    }

    const oldId =
      oldItem?.id ??
      oldItem?.transaction_id ??
      oldItem?.checkout_request_id ??
      oldItem?.merchant_request_id ??
      null;

    const newId =
      newItem?.id ??
      newItem?.transaction_id ??
      newItem?.checkout_request_id ??
      newItem?.merchant_request_id ??
      null;

    if (
      oldId != null &&
      newId != null
    ) {
      if (String(oldId) !== String(newId)) {
        return false;
      }

      const oldStatus =
        oldItem?.status ??
        oldItem?.result_code ??
        "";

      const newStatus =
        newItem?.status ??
        newItem?.result_code ??
        "";

      if (
        String(oldStatus) !==
        String(newStatus)
      ) {
        return false;
      }

      const oldAmount =
        Number(oldItem?.amount) || 0;

      const newAmount =
        Number(newItem?.amount) || 0;

      if (oldAmount !== newAmount) {
        return false;
      }

      continue;
    }

    try {
      if (
        JSON.stringify(oldItem) !==
        JSON.stringify(newItem)
      ) {
        return false;
      }
    } catch {
      return false;
    }
  }

  return true;
}

// ==================================================
// PROVIDER
// ==================================================

export function UserProvider({ children }) {
  const [user, setUser] = useState(null);

  const [balance, setBalance] = useState(0);

  const [bonusBalance, setBonusBalance] =
    useState(0);

  const [transactions, setTransactions] =
    useState([]);

  const [balanceHistory, setBalanceHistory] =
    useState([]);

  const [loadingUser, setLoadingUser] =
    useState(true);

  const mountedRef = useRef(false);

  const silentRefreshInProgressRef =
    useRef(false);

  // ==================================================
  // APPLY USER DATA
  // ==================================================

  const applyUserData = useCallback(
    (res) => {
      if (!res?.success || !res?.data) {
        return false;
      }

      const data = extractPayload(res);

      const nextUser =
        data?.user ??
        null;

      const nextBalance =
        extractBalance(
          res,
          0
        );

      const nextBonus =
        extractBonusBalance(
          res,
          null
        );

      const nextTransactions =
        ensureArray(
          data?.transactions ??
            res?.transactions
        );

      setUser(
        nextUser
      );

      setBalance(
        nextBalance
      );

      if (nextBonus != null) {
        setBonusBalance(
          nextBonus
        );
      }

      if (
        Array.isArray(
          nextTransactions
        )
      ) {
        setTransactions(
          (prev) =>
            sameArrayReferenceContents(
              prev,
              nextTransactions
            )
              ? prev
              : nextTransactions
        );
      }

      return true;
    },
    []
  );

  // ==================================================
  // FULL USER RELOAD
  //
  // Used for initial authentication/user loading.
  // This is intentionally allowed to show loading.
  // ==================================================

  const reloadUser = useCallback(
    async () => {
      setLoadingUser(true);

      try {
        const token =
          getAuthToken();

        if (!token) {
          throw new Error(
            "No auth token"
          );
        }

        // --------------------------------------------
        // PROFILE
        // --------------------------------------------

        const res =
          await api.getMe();

        console.log(
          "reloadUser /me response:",
          res
        );

        if (
          !res?.success ||
          !res?.data
        ) {
          throw new Error(
            "Invalid /me response"
          );
        }

        const data =
          extractPayload(res);

        setUser(
          data?.user ??
            null
        );

        const nextBalance =
          extractBalance(
            res,
            0
          );

        setBalance(
          nextBalance
        );

        const nextBonus =
          extractBonusBalance(
            res,
            null
          );

        if (
          nextBonus != null
        ) {
          setBonusBalance(
            nextBonus
          );
        }

        // --------------------------------------------
        // WALLET DATA
        // --------------------------------------------

        const [
          txRes,
          histRes,
        ] =
          await Promise.all([
            api
              .getTransactions()
              .catch(
                () => null
              ),

            api
              .getBalanceHistory()
              .catch(
                () => null
              ),
          ]);

        const nextTransactions =
          ensureArray(
            txRes
          );

        const nextHistory =
          ensureArray(
            histRes
          );

        setTransactions(
          (prev) =>
            sameArrayReferenceContents(
              prev,
              nextTransactions
            )
              ? prev
              : nextTransactions
        );

        setBalanceHistory(
          (prev) =>
            sameArrayReferenceContents(
              prev,
              nextHistory
            )
              ? prev
              : nextHistory
        );

        return true;
      } catch (err) {
        console.error(
          "Failed to load user:",
          err
        );

        clearToken();

        setUser(null);
        setBalance(0);
        setBonusBalance(0);
        setTransactions([]);
        setBalanceHistory([]);

        return false;
      } finally {
        setLoadingUser(false);
      }
    },
    []
  );

  // ==================================================
  // SILENT WALLET REFRESH
  //
  // IMPORTANT:
  // This does NOT set loadingUser(true).
  //
  // Therefore the rest of the application does not
  // display a user-loading state while wallet data is
  // being refreshed.
  // ==================================================

  const refreshWalletSilently =
    useCallback(
      async () => {
        if (
          silentRefreshInProgressRef.current
        ) {
          return false;
        }

        if (!getAuthToken()) {
          return false;
        }

        silentRefreshInProgressRef.current =
          true;

        try {
          const [
            balanceRes,
            txRes,
            histRes,
          ] =
            await Promise.all([
              api
                .getBalance()
                .catch(
                  () => null
                ),

              api
                .getTransactions()
                .catch(
                  () => null
                ),

              api
                .getBalanceHistory()
                .catch(
                  () => null
                ),
            ]);

          // ------------------------------------------
          // BALANCE
          // ------------------------------------------

          const nextBalance =
            extractBalance(
              balanceRes,
              null
            );

          if (
            nextBalance != null
          ) {
            setBalance(
              (prev) =>
                Number(prev) ===
                Number(nextBalance)
                  ? prev
                  : nextBalance
            );
          }

          // ------------------------------------------
          // BONUS
          // ------------------------------------------

          const nextBonus =
            extractBonusBalance(
              balanceRes,
              null
            );

          if (
            nextBonus != null
          ) {
            setBonusBalance(
              (prev) =>
                Number(prev) ===
                Number(nextBonus)
                  ? prev
                  : nextBonus
            );
          }

          // ------------------------------------------
          // TRANSACTIONS
          // ------------------------------------------

          const nextTransactions =
            ensureArray(
              txRes
            );

          setTransactions(
            (prev) =>
              sameArrayReferenceContents(
                prev,
                nextTransactions
              )
                ? prev
                : nextTransactions
          );

          // ------------------------------------------
          // BALANCE HISTORY
          // ------------------------------------------

          const nextHistory =
            ensureArray(
              histRes
            );

          setBalanceHistory(
            (prev) =>
              sameArrayReferenceContents(
                prev,
                nextHistory
              )
                ? prev
                : nextHistory
          );

          return true;
        } catch (err) {
          console.error(
            "Silent wallet refresh failed:",
            err
          );

          return false;
        } finally {
          silentRefreshInProgressRef.current =
            false;
        }
      },
      []
    );

  // ==================================================
  // DEPOSIT
  // ==================================================

  const deposit =
    useCallback(
      async (amount) => {
        const res =
          await api.mpesaDeposit(
            amount
          );

        if (
          !res?.success
        ) {
          throw new Error(
            res?.error ||
              res?.message ||
              "Deposit failed"
          );
        }

        /*
         * DO NOT call reloadUser().
         *
         * STK Push being accepted does not necessarily
         * mean the M-PESA payment has completed.
         *
         * Keep the current UI alive.
         */

        const responseBalance =
          extractBalance(
            res,
            null
          );

        if (
          responseBalance != null
        ) {
          setBalance(
            responseBalance
          );
        }

        /*
         * Refresh wallet information silently.
         *
         * No loadingUser=true.
         * No full user reload.
         */
        window.setTimeout(
          () => {
            refreshWalletSilently();
          },
          1200
        );

        return res;
      },
      [
        refreshWalletSilently,
      ]
    );

  // ==================================================
  // WITHDRAW
  // ==================================================

  const withdraw =
    useCallback(
      async (amount) => {
        const res =
          await api.withdraw(
            amount
          );

        if (
          !res?.success
        ) {
          throw new Error(
            res?.error ||
              res?.message ||
              "Withdraw failed"
          );
        }

        /*
         * Use updated balance if backend provides it.
         */
        const responseBalance =
          extractBalance(
            res,
            null
          );

        if (
          responseBalance != null
        ) {
          setBalance(
            responseBalance
          );
        }

        /*
         * Update wallet silently.
         * Never trigger the global user-loading state.
         */
        window.setTimeout(
          () => {
            refreshWalletSilently();
          },
          300
        );

        return res;
      },
      [
        refreshWalletSilently,
      ]
    );

  // ==================================================
  // BALANCE UPDATE
  // ==================================================

  const updateBalance =
    useCallback(
      (newBalance) => {
        /*
         * Support:
         *
         * updateBalance(500)
         *
         * and:
         *
         * updateBalance({
         *   balance: 500,
         *   bonusBalance: 50
         * })
         */

        if (
          typeof newBalance ===
          "object" &&
          newBalance !== null
        ) {
          if (
            newBalance.balance != null
          ) {
            const numeric =
              Number(
                newBalance.balance
              );

            if (
              Number.isFinite(
                numeric
              )
            ) {
              setBalance(
                numeric
              );
            }
          }

          if (
            newBalance.bonusBalance !=
            null
          ) {
            const numeric =
              Number(
                newBalance.bonusBalance
              );

            if (
              Number.isFinite(
                numeric
              )
            ) {
              setBonusBalance(
                numeric
              );
            }
          }

          return;
        }

        const numeric =
          Number(
            newBalance
          );

        if (
          Number.isFinite(
            numeric
          )
        ) {
          setBalance(
            numeric
          );
        }
      },
      []
    );

  // ==================================================
  // TRANSACTIONS
  // ==================================================

  const updateTransactions =
    useCallback(
      (newTxOrArray) => {
        if (
          !newTxOrArray
        ) {
          return;
        }

        setTransactions(
          (prev) => {
            if (
              Array.isArray(
                newTxOrArray
              )
            ) {
              return sameArrayReferenceContents(
                prev,
                newTxOrArray
              )
                ? prev
                : [
                    ...newTxOrArray,
                  ];
            }

            const newId =
              newTxOrArray?.id ??
              newTxOrArray?.transaction_id ??
              newTxOrArray?.checkout_request_id ??
              newTxOrArray?.merchant_request_id;

            if (
              newId != null
            ) {
              const exists =
                prev.some(
                  (tx) => {
                    const txId =
                      tx?.id ??
                      tx?.transaction_id ??
                      tx?.checkout_request_id ??
                      tx?.merchant_request_id;

                    return (
                      txId != null &&
                      String(txId) ===
                        String(newId)
                    );
                  }
                );

              if (exists) {
                return prev;
              }
            }

            return [
              newTxOrArray,
              ...prev,
            ];
          }
        );
      },
      []
    );

  // ==================================================
  // BALANCE HISTORY
  // ==================================================

  const updateBalanceHistory =
    useCallback(
      (newHistOrArray) => {
        if (
          !newHistOrArray
        ) {
          return;
        }

        setBalanceHistory(
          (prev) => {
            if (
              Array.isArray(
                newHistOrArray
              )
            ) {
              return sameArrayReferenceContents(
                prev,
                newHistOrArray
              )
                ? prev
                : [
                    ...newHistOrArray,
                  ];
            }

            return [
              newHistOrArray,
              ...prev,
            ];
          }
        );
      },
      []
    );

  // ==================================================
  // INITIAL LOAD
  // ==================================================

  useEffect(() => {
    if (
      mountedRef.current
    ) {
      return;
    }

    mountedRef.current = true;

    reloadUser();
  }, [
    reloadUser,
  ]);

  // ==================================================
  // CONTEXT VALUE
  // ==================================================

  const contextValue =
    useMemo(
      () => ({
        user,

        balance,

        bonusBalance,

        transactions,

        balanceHistory,

        loadingUser,

        setUser,

        setBalance,

        setBonusBalance,

        reloadUser,

        refreshWalletSilently,

        deposit,

        withdraw,

        updateBalance,

        updateTransactions,

        updateBalanceHistory,
      }),
      [
        user,
        balance,
        bonusBalance,
        transactions,
        balanceHistory,
        loadingUser,

        reloadUser,
        refreshWalletSilently,

        deposit,
        withdraw,

        updateBalance,
        updateTransactions,
        updateBalanceHistory,
      ]
    );

  return (
    <UserContext.Provider
      value={contextValue}
    >
      {children}
    </UserContext.Provider>
  );
}

// ==================================================
// HOOK
// ==================================================

export function useUser() {
  const context =
    useContext(
      UserContext
    );

  if (!context) {
    throw new Error(
      "useUser must be used inside a UserProvider"
    );
  }

  return context;
}
