// src/api/betsWallet.js
import { request, setToken, clearToken } from "./core.js";

// --------------------------------------------------
// AUTH
// --------------------------------------------------
export const login = async (phone, password) => {
  const res = await request("/login", "POST", { phone, password });
  const token = res?.data?.data?.token || res?.data?.token || res?.token || null;
  if (token) setToken(token);
  return res;
};

export const signup = async (phone, password) => {
  const res = await request("/signup", "POST", { phone, password });
  const token = res?.data?.data?.token || res?.data?.token || res?.token || null;
  if (token) setToken(token);
  return res;
};

export const logout = () => {
  clearToken();
  return { success: true };
};

// --------------------------------------------------
// USER / PROFILE
// --------------------------------------------------
export const getMe = async () => {
  const res = await request("/me");
  if (!res?.success) return res;

  const payload = res.data?.data || res.data || {};
  return {
    ...res,
    data: {
      user: payload.user || null,
      balance: payload.balance ?? 0,
      transactions: payload.transactions ?? [],
      total_bets: payload.total_bets ?? 0,
    },
  };
};

export const changePassword = (old_password, new_password) =>
  request("/change_password", "POST", { old_password, new_password });

export const resetPassword = (phone, new_password) =>
  request("/reset_password", "POST", { phone, new_password });

export const deleteAccount = () => request("/delete_account", "DELETE");

// --------------------------------------------------
// WALLET
// --------------------------------------------------
export const getBalance = () => request("/balance");
export const deposit = (amount) => request("/deposit", "POST", { amount });
export const withdraw = (amount) => request("/withdraw", "POST", { amount });
export const getTransactions = () => request("/transactions");
export const getBalanceHistory = () => request("/balance_history");

// --------------------------------------------------
// BETTING
// --------------------------------------------------
export const placeBet = (payload) => {
  if (!payload) throw new Error("No payload provided");

  if (payload.stake == null || Number(payload.stake) < 1) {
    payload.stake = 1;
  }

  if (
    Array.isArray(payload.selections) &&
    payload.selections.length === 1 &&
    !payload.match_id
  ) {
    const single = payload.selections[0];
    payload.match_id = single.match_id;
    payload.selection = single.selection;
    delete payload.selections;
  }

  return request("/place_bet", "POST", payload);
};

const normalizeMyBetsResponse = (res) => {
  const data = res?.data?.data || res?.data || res || {};

  const normalizeSlip = (slip) => ({
    ...slip,
    current_cashout: slip?.current_cashout ?? null,
    selections: Array.isArray(slip?.selections) ? slip.selections : [],
  });

  const normalizeSingleBet = (bet) => ({
    ...bet,
    current_cashout: bet?.current_cashout ?? null,
  });

  return {
    ...res,
    page: data.page ?? 1,
    per_page: data.per_page ?? 20,
    total_betslips: data.total_betslips ?? 0,
    betslips: Array.isArray(data.betslips) ? data.betslips.map(normalizeSlip) : [],
    single_bets: Array.isArray(data.single_bets)
      ? data.single_bets.map(normalizeSingleBet)
      : [],
  };
};

export const getMyBets = async () => {
  const res = await request("/my_bets");
  if (!res?.success) return res;
  return normalizeMyBetsResponse(res);
};

// ---------- Tickets ----------
export const getTickets = () => request("/tickets");
export const getTicket = (id) => request(`/ticket/${id}`);

// --------------------------------------------------
// CASHOUT
// --------------------------------------------------
export const cashout = (bet_id) => request(`/cashout/${bet_id}`, "POST");

// --------------------------------------------------
// MATCHES
// --------------------------------------------------
export const getMarkets = (match_id) => request(`/markets/${match_id}`);
export const getOdds = (match_id) => request(`/odds/${match_id}`);

// --------------------------------------------------
// STATS
// --------------------------------------------------
export const getStats = () => request("/stats");
export const getProfit = () => request("/profit");
export const getProfitHistory = () => request("/profit_history");

// --------------------------------------------------
// ADMIN
// --------------------------------------------------
export const gradeMatch = (match_id, result) =>
  request("/admin/grade_match", "POST", { match_id, result });

export const adminTickets = () => request("/admin/tickets");
export const adminUsers = () => request("/admin/users");
export const creditUser = (user_id, amount) =>
  request("/admin/credit", "POST", { user_id, amount });

// --------------------------------------------------
// SYSTEM
// --------------------------------------------------
export const healthCheck = () => request("/health");
