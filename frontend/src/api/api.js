// src/api/api.js
// MUST be first (eslint import/first)

import * as core from "./core";
import * as domain from "./domain";
import * as authVipAdmin from "./authVipAdmin";
import * as betsWallet from "./betsWallet";

// Re-export everything
export * from "./core";
export * from "./domain";
export * from "./authVipAdmin";
export * from "./betsWallet";

/* ------------------------------------------------
   Compatibility aliases (for existing frontend)
------------------------------------------------ */

// Dashboard
export const fetchDashboard = domain.getDashboard;

// Teams
export const getTeams = domain.getTeams;

// Predictions
export const getLatestPredictions = domain.getPredictionsLatest;

// Football helpers (these are inside domain.js)
export const loadTeams = domain.loadTeams;
export const attachLogosSafe = domain.attachLogosSafe;
export const getPlayers = domain.getPlayers;
export const getLineups = domain.getLineups;
export const getInjuries = domain.getInjuries;
export const getH2H = domain.getH2H;

// Results wrapper: combines matches with predictions
export async function getFinishedMatchesWithPredictions() {
  const matchesRes = await domain.getFinishedMatchesWithPredictions();
  if (!matchesRes?.success) return { success: false, data: [] };

  const predictionsRes = await domain.getPredictionsLatest();
  if (!predictionsRes?.success) return matchesRes;

  const map = {};

  predictionsRes.data?.predictions?.forEach((p) => {
    map[p.fixture_id] = p;
  });

  matchesRes.data.matches = matchesRes.data.matches.map((m) => ({
    ...m,
    prediction: map[m.id] || null
  }));

  return matchesRes;
}

// Default export
export default {
  ...core,
  ...domain,
  ...authVipAdmin,
  ...betsWallet,
  fetchDashboard,
  getTeams,
  getLatestPredictions,
  getFinishedMatchesWithPredictions,
  loadTeams,
  attachLogosSafe,
  getPlayers,
  getLineups,
  getInjuries,
  getH2H
};
