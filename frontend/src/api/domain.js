// src/api/footballApi.js
// (Updated) includes normalizeLogoUrl + improved extractLogoFromTeam so crest URLs load via tunnel

import { makeRequester, BACKEND_FOOTBALL } from "./core.js";
const { requestRaw, request } = makeRequester(BACKEND_FOOTBALL);

// Toggle debug logs (set true temporarily when debugging)
const DEBUG = false;

// ---------- Teams / Logos helpers ----------
let teamMap = null; // numeric-id -> team object
let nameMap = null; // normalized name -> team object (first match)

// normalize helper used for name matching
function normalize(str = "") {
  return String(str || "")
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "")

    .replace(/[^\w]/g, "");
}

/**
 * Safe SVG -> data URI encoder
 * prefers base64 (btoa) in browser, falls back to URI-encoding if btoa absent
 */
function svgToDataUri(svg) {
  try {
    if (typeof btoa !== "undefined") {
      return `data:image/svg+xml;base64,${btoa(svg)}`;
    }
  } catch (e) {
    // fall through to URI encoding
  }
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

/**
 * Normalize logo URLs so they work when the site is opened via a tunnel (different origin).
 * - data: or inline svg => keep
 * - relative URLs (starting with '/') => keep (will resolve on current origin)
 * - localhost / 127.0.0.1 => rewrite to current origin + path
 * - upgrade http -> https if page is https
 * - otherwise return absolute URL unchanged
 *
 * (Optional) You can extend this to route external hosts through an image proxy
 * by returning `/image-proxy?url=${encodeURIComponent(url)}` for matching hosts.
 */
function normalizeLogoUrl(url) {
  if (!url) return null;

  // Keep data URIs and inline SVGs as-is
  if (typeof url === "string") {
    const t = url.trim();
    if (t.startsWith("data:") || t.startsWith("blob:") || t.startsWith("<svg")) {
      return url;
    }
  }

  try {
    // Relative paths are safe and resolve to current origin when loaded via tunnel
    if (url.startsWith("/")) return url;

    // Use window.location.origin as base for relative parsing
    const parsed = new URL(url, window.location.origin);

    // If URL points to localhost, rewrite to current origin so tunnel serves it
    if (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1") {
      return window.location.origin + parsed.pathname + parsed.search;
    }

    // If page is HTTPS and the image is HTTP, try upgrading to HTTPS to avoid mixed content
    if (window.location.protocol === "https:" && parsed.protocol === "http:") {
      parsed.protocol = "https:";
      return parsed.toString();
    }

    // Otherwise leave the URL as-is
    return parsed.toString();
  } catch (e) {
    // If parsing fails, return the original value (best-effort)
    return url;
  }
}

/**
 * Generate a simple badge-style SVG for a team name (offline fallback).
 * Produces visually distinct color from the team name.
 */
function generateFootballBadge(teamName = "FC") {
  const initials = (teamName || "FC")
    .split(/\s+/)
    .map((w) => (w ? w[0] : ""))
    .slice(0, 2)
    .join("")
    .toUpperCase() || "FC";

  const hash = [...String(teamName)].reduce((a, c) => a + c.charCodeAt(0), 0);
  const color = `hsl(${hash % 360},70%,45%)`;

  const svg = `
  <svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">
    <defs>
      <linearGradient id="g" x1="0" x2="1" y1="0" y2="1">
        <stop offset="0" stop-color="${color}" stop-opacity="0.95"/>
        <stop offset="1" stop-color="${color}" stop-opacity="0.8"/>
      </linearGradient>
    </defs>
    <rect width="120" height="120" rx="18" ry="18" fill="url(#g)" />
    <rect x="6" y="6" width="108" height="108" rx="14" ry="14" fill="none" stroke="white" stroke-width="4" opacity="0.18"/>
    <text x="50%" y="54%" font-size="44" fill="white" font-family="system-ui, Arial, sans-serif"
      text-anchor="middle" dominant-baseline="middle" font-weight="700">
      ${initials}
    </text>
  </svg>
  `;

  return svgToDataUri(svg);
}

/**
 * Normalize possible logo fields into a single URL string or data URI.
 * supports: crest, logo, badge, image, svg
 *
 * This version normalizes absolute URLs so logos load through the current origin
 * (fixes localhost URLs when site is accessed via tunnel).
 */
function extractLogoFromTeam(t) {
  if (!t) return null;

  // prefer inline svg content, then crest/logo fields
  const raw = t.svg || t.crest || t.logo || t.badge || t.image || null;
  if (!raw) return null;

  // Inline SVG content -> convert to data URI
  if (typeof raw === "string" && raw.trim().startsWith("<svg")) {
    return svgToDataUri(raw);
  }

  // If raw is already a data URI keep it
  if (typeof raw === "string" && raw.trim().startsWith("data:")) {
    return raw;
  }

  // Normalize logo URL (handles localhost -> tunnel origin, http->https, relative paths)
  return normalizeLogoUrl(raw);
}

// ---------- Load teams ----------
export async function loadTeams() {
  // return earlier if already loaded
  if (teamMap && Object.keys(teamMap).length) return teamMap;

  try {
    const r = await requestRaw("/teams");

    if (!r || !r.success) {
      if (DEBUG) console.warn("loadTeams: teams request failed", r);
      teamMap = {};
      nameMap = {};
      return teamMap;
    }

    const teams = r.data?.teams || [];
    teamMap = {};
    nameMap = {};

    teams.forEach((t) => {
      if (!t) return;

      // Ensure numeric ID keys to avoid "454" vs 454 mismatch
      const idNum = Number(t.id);
      if (!Number.isNaN(idNum)) {
        teamMap[idNum] = t;
      }

      // populate name-based lookup(s)
      const candidates = [
        t.name,
        t.short_name,
        t.shortName,
        t.tla,
        t.team_name,
        t.club_name,
      ].filter(Boolean);

      candidates.forEach((c) => {
        const key = normalize(c);
        if (key && !nameMap[key]) nameMap[key] = t;
      });

      // also map normalized full name once more (fallbacks)
      const full = normalize(t.name || "");
      if (full && !nameMap[full]) nameMap[full] = t;
    });

    if (DEBUG) {
      console.log("loadTeams: loaded teams count =", Object.keys(teamMap).length);
      console.log("loadTeams: sample keys =", Object.keys(teamMap).slice(0, 10));
    }

    return teamMap;
  } catch (err) {
    console.error("Error loading teams:", err);
    teamMap = {};
    nameMap = {};
    return teamMap;
  }
}

export async function ensureTeams() {
  if (!teamMap || !Object.keys(teamMap).length) await loadTeams();
}

// ---------- Robust logo lookup ----------
function getLogo(id, name) {
  // try numeric id lookup first (handles "454" and 454)
  const numericId = Number(id);
  if (!Number.isNaN(numericId) && teamMap && teamMap[numericId]) {
    const l = extractLogoFromTeam(teamMap[numericId]);
    if (l) return l;
  }

  // try name-based lookup
  if (name && nameMap) {
    const key = normalize(name);
    const t = nameMap[key];
    if (t) {
      const l = extractLogoFromTeam(t);
      if (l) return l;
    }

    // small fuzzy scan fallback (only when nameMap fails)
    const fallback = Object.values(teamMap || {}).find((tt) => {
      if (!tt) return false;
      return (
        normalize(tt.name) === key ||
        normalize(tt.short_name || tt.shortName || "") === key ||
        normalize(tt.tla || "") === key
      );
    });
    if (fallback) {
      const l = extractLogoFromTeam(fallback);
      if (l) return l;
    }
  }

  // last resort: generate badge for the team name (or generic FC)
  return generateFootballBadge(name || "FC");
}

// ---------- attach logos safely ----------
export function attachLogosSafe(
  item,
  homeNameKey = "home_team_name",
  awayNameKey = "away_team_name",
  homeIdKey = "home_team_id",
  awayIdKey = "away_team_id"
) {
  // if teamMap is not loaded yet, return generated defaults (not crashing)
  if (!teamMap || !Object.keys(teamMap).length) {
    return {
      ...item,
      home_logo: generateFootballBadge(item?.[homeNameKey] || "FC"),
      away_logo: generateFootballBadge(item?.[awayNameKey] || "FC"),
    };
  }

  const homeLogo = getLogo(item[homeIdKey], item[homeNameKey]);
  const awayLogo = getLogo(item[awayIdKey], item[awayNameKey]);

  return {
    ...item,
    home_logo: homeLogo,
    away_logo: awayLogo,
  };
}

// ---------- Matches / Predictions / Tips ----------
export async function getDashboard(filters = {}) {
  const qs = new URLSearchParams(filters).toString();
  return await request(`/dashboard${qs ? `?${qs}` : ""}`);
}

export async function getRecentMatches(params = {}) {
  const qs = new URLSearchParams(params).toString();
  const r = await request(`/matches/recent${qs ? `?${qs}` : ""}`);
  if (!r.success) return r;
  await ensureTeams();
  if (Array.isArray(r.data.matches))
    r.data.matches = r.data.matches.map((m) => attachLogosSafe(m));
  return r;
}

export async function getUpcomingMatches(params = {}) {
  const qs = new URLSearchParams(params).toString();
  const r = await request(`/matches/upcoming${qs ? `?${qs}` : ""}`);
  if (!r.success) return r;
  await ensureTeams();
  if (Array.isArray(r.data.matches))
    r.data.matches = r.data.matches.map((m) => attachLogosSafe(m));
  return r;
}

export async function getLiveMatches(params = {}) {
  const qs = new URLSearchParams(params).toString();
  const r = await request(`/matches/live${qs ? `?${qs}` : ""}`);
  if (!r.success) return r;
  await ensureTeams();
  if (Array.isArray(r.data.matches))
    r.data.matches = r.data.matches.map((m) => attachLogosSafe(m));
  return r;
}

export async function getAllMatches(params = {}) {
  const qs = new URLSearchParams(params).toString();
  const r = await request(`/matches${qs ? `?${qs}` : ""}`);
  if (!r.success) return r;
  await ensureTeams();
  if (Array.isArray(r.data.matches))
    r.data.matches = r.data.matches.map((m) => attachLogosSafe(m));
  return r;
}

// ---------- Predictions ----------
export async function getPredictionsLatest(params = {}) {
  const qs = new URLSearchParams(params).toString();

  const r = await request(`/predictions/latest${qs ? `?${qs}` : ""}`);

  // 🔥 DO NOT trust r.success (backend doesn't send it)
  if (!r) {
    return { success: false, data: { predictions: [] } };
  }

  await ensureTeams();

  // 🔥 normalize backend response safely
  const rawPredictions =
    r.data?.predictions ||   // if wrapped
    r.predictions ||
    [];

  const normalized = Array.isArray(rawPredictions)
    ? rawPredictions.map((p) =>
        attachLogosSafe(
          {
            ...p,
            utcDate: p.utcDate || p.utcdate, // 🔥 FIX DATE BUG
          },
          "home_team_name",
          "away_team_name"
        )
      )
    : [];

  return {
    success: true,
    data: {
      predictions: normalized,
    },
  };
}

export async function getGroupedPredictions({ home, away, match_id } = {}) {
  const params = new URLSearchParams();
  if (home) params.append("home", home);
  if (away) params.append("away", away);
  if (match_id) params.append("match_id", match_id);
  const qs = params.toString();
  const r = await request(`/predictions/match/grouped${qs ? `?${qs}` : ""}`);
  if (!r.success) return r;
  await ensureTeams();
  return r;
}

export async function getTipsDaily(date) {
  const r = await request(
    `/tips/daily${date ? `?date=${encodeURIComponent(date)}` : ""}`
  );
  if (!r.success) return r;
  await ensureTeams();
  if (Array.isArray(r.data.tips))
    r.data.tips = r.data.tips.map((t) => attachLogosSafe(t));
  return r;
}

export async function getTipsValue(status = "TIMED,SCHEDULED") {
  const r = await request(`/tips/value?status=${encodeURIComponent(status)}`);
  if (!r.success) return r;
  await ensureTeams();
  if (Array.isArray(r.data.tips))
    r.data.tips = r.data.tips.map((t) => attachLogosSafe(t));
  return r;
}

// ---------- Teams / Players / Lineups / Injuries ----------
export async function getTeams() {
  await ensureTeams();
  return { success: true, data: { teams: Object.values(teamMap || {}) } };
}

export async function getPlayers(params = {}) {
  const qs = new URLSearchParams(params).toString();
  return await request(`/players${qs ? `?${qs}` : ""}`);
}

export async function getLineups(params = {}) {
  const qs = new URLSearchParams(params).toString();
  return await request(`/lineups${qs ? `?${qs}` : ""}`);
}

export async function getInjuries(params = {}) {
  const qs = new URLSearchParams(params).toString();
  return await request(`/injuries${qs ? `?${qs}` : ""}`);
}

// ---------- H2H / Team overview ----------
export async function getH2H(home_team_id, away_team_id, limit = 5) {
  return await request(
    `/h2h?home_team_id=${home_team_id}&away_team_id=${away_team_id}&limit=${limit}`
  );
}

export async function getTeamMatchOverview(match_id, h2h_limit = 5, model_version = null) {
  let url = `/team-match-overview?match_id=${match_id}&h2h_limit=${h2h_limit}`;
  if (model_version) url += `&model_version=${model_version}`;
  return await request(url);
}

// ---------- Finished matches & bookmarks ----------
export async function getFinishedMatchesWithPredictions({ months = 2, limit } = {}) {
  const params = new URLSearchParams();
  if (months) params.append("months", String(months));
  if (limit) params.append("limit", String(limit));
  return await request(`/api/finished-matches-with-predictions?${params.toString()}`);
}

export async function getAllBookmarks(model_version = "") {
  const url = model_version ? `/bookmark/all?model_version=${encodeURIComponent(model_version)}` : "/bookmark/all";
  return await request(url);
}

// ---------- Accumulator ----------
export async function getAccumulator(params = {}) {
  const qs = new URLSearchParams(params).toString();
  const r = await request(`/accumulator${qs ? `?${qs}` : ""}`);
  if (!r.success) return { success: false, data: {} };
  await ensureTeams();

  // Normalize: convert each date key to an array
  const d = r.data || {};
  for (const key in d) {
    if (!Array.isArray(d[key])) {
      const val = d[key];
      const arr = [];
      if (val && typeof val === "object") {
        Object.values(val).forEach((v) => {
          if (Array.isArray(v)) arr.push(...v);
        });
      }
      d[key] = arr;
    }
  }

  return { ...r, data: d };
}
