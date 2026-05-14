// src/api/vipAdminApi.js
import { makeRequester, BACKEND_ADMIN } from "./core.js";

const { request } = makeRequester(BACKEND_ADMIN);
/**
 * VIP / Admin API client
 * - Uses its own backend base URL
 * - Returns { success, data, status, error }
 */

// ---------- Helper ----------
const vipRequest = async (path, options = {}) => {
  try {
    const res = await request(
      path,
      options.method || "GET",
      options.body ?? null,
      options.token ?? null
    );
    return res;
  } catch (err) {
    console.error(`[VIP API ERROR] ${path}`, err);
    return { success: false, error: err?.message || String(err) };
  }
};

const qsFor = (params = {}) => {
  const s = new URLSearchParams(params).toString();
  return s ? `?${s}` : "";
};

// ---------- VIP ----------
export const vipRegister = ({ name, number, subscription }) =>
  vipRequest("/vip/register", { method: "POST", body: { name, number, subscription } });

export const vipLogin = (number) =>
  vipRequest("/vip/login", { method: "POST", body: { number } });

export const vipMe = (token) =>
  vipRequest("/vip/me", { method: "GET", token });

export const vipUpgrade = (token, plan) =>
  vipRequest("/vip/upgrade", { method: "POST", body: { plan }, token });

export const vipPicks = (token) =>
  vipRequest("/vip/picks", { method: "GET", token });

export const vipQuota = (token) =>
  vipRequest("/vip/quota", { method: "GET", token });

// ---------- Admin ----------
export const adminLogin = (username, password) =>
  vipRequest("/admin/login", { method: "POST", body: { username, password } });

export const adminListVips = (token) =>
  vipRequest("/admin/vips", { method: "GET", token });

export const adminListPendingVips = (token) =>
  vipRequest("/admin/vips/pending", { method: "GET", token });

export const adminApproveVip = (token, vip_id) =>
  vipRequest(`/admin/vips/approve/${vip_id}`, { method: "POST", token });

export const adminDeclineVip = (token, vip_id) =>
  vipRequest(`/admin/vips/decline/${vip_id}`, { method: "POST", token });

export const adminListUpgradeRequests = (token) =>
  vipRequest("/admin/vip-upgrades", { method: "GET", token });

export const adminApproveUpgrade = (token, req_id) =>
  vipRequest(`/admin/vip-upgrades/approve/${req_id}`, { method: "POST", token });

export const adminDeclineUpgrade = (token, req_id) =>
  vipRequest(`/admin/vip-upgrades/decline/${req_id}`, { method: "POST", token });

export const adminPreviewVipPicks = (token, days = 3) =>
  vipRequest(`/admin/vip-picks/preview${qsFor({ days })}`, { method: "GET", token });

export const adminDistributeVipPicks = (token, payload) =>
  vipRequest("/admin/vip-picks/distribute", { method: "POST", body: payload, token });

export const adminClearAllVipPicks = (token) =>
  vipRequest("/admin/vip-picks/clear", { method: "POST", token });

export const adminClearVipPicksForNumber = (token, number) =>
  vipRequest(`/admin/vip-picks/clear/${encodeURIComponent(number)}`, { method: "POST", token });
