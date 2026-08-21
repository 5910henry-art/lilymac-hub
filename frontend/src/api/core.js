/* src/api/core.js */

export const DEFAULT_TIMEOUT = 15000;

// ============================================================
// BACKEND URLS
// ============================================================
// Vercel frontend -> Render backend
//
// You can still override these with VITE_* environment variables.
// ============================================================

const BACKEND_BASE =
  import.meta.env.VITE_BACKEND_URL ||
  "https://lilymac-hub.onrender.com";

export const BACKEND_FOOTBALL =
  import.meta.env.VITE_FOOTBALL_API_URL ||
  `${BACKEND_BASE}/app`;

export const BACKEND_ADMIN =
  import.meta.env.VITE_ADMIN_API_URL ||
  `${BACKEND_BASE}/vipadmin`;

export const BACKEND_BET =
  import.meta.env.VITE_BET_API_URL ||
  `${BACKEND_BASE}/bet`;

// ============================================================
// AUTH TOKEN
// ============================================================

let authToken = null;

if (typeof localStorage !== "undefined") {
  const stored =
    localStorage.getItem("token") ||
    localStorage.getItem("auth_token") ||
    localStorage.getItem("vip_token");

  if (stored) {
    authToken = stored;
  }
}

export function getAuthToken() {
  if (authToken) return authToken;

  if (typeof localStorage === "undefined") {
    return null;
  }

  return (
    localStorage.getItem("token") ||
    localStorage.getItem("auth_token") ||
    localStorage.getItem("vip_token") ||
    null
  );
}

export function setToken(token) {
  authToken = token || null;

  if (typeof localStorage !== "undefined") {
    if (token) {
      localStorage.setItem("token", token);
    } else {
      localStorage.removeItem("token");
      localStorage.removeItem("auth_token");
      localStorage.removeItem("vip_token");
    }
  }
}

export function clearToken() {
  authToken = null;

  if (typeof localStorage !== "undefined") {
    localStorage.removeItem("token");
    localStorage.removeItem("auth_token");
    localStorage.removeItem("vip_token");
  }
}

// ============================================================
// TOKEN REFRESH
// ============================================================

let refreshing = false;

async function refreshToken() {
  if (refreshing) return null;

  refreshing = true;

  try {
    const token = getAuthToken();

    if (!token) {
      refreshing = false;
      return null;
    }

    const res = await fetch(`${BACKEND_BET}/refresh`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    if (!res.ok) {
      throw new Error("refresh failed");
    }

    const data = await res.json();

    if (data.token) {
      setToken(data.token);
      refreshing = false;
      return data.token;
    }
  } catch {
    clearToken();
  }

  refreshing = false;
  return null;
}

// ============================================================
// FETCH WITH TIMEOUT
// ============================================================

async function timeoutFetch(ms, fetchFn) {
  const controller = new AbortController();

  const id = setTimeout(() => {
    controller.abort();
  }, ms);

  return fetchFn(controller.signal).finally(() => {
    clearTimeout(id);
  });
}

// ============================================================
// RAW FETCH
// ============================================================

export async function rawFetch(
  method,
  fullUrl,
  { headers = {}, body = null, timeout = DEFAULT_TIMEOUT } = {}
) {
  const options = {
    method,
    headers,
  };

  if (body != null) {
    if (
      typeof body === "object" &&
      !(body instanceof FormData)
    ) {
      options.body = JSON.stringify(body);

      options.headers = {
        ...headers,
        "Content-Type": "application/json",
      };
    } else {
      options.body = body;
    }
  }

  // Debug stake validation
  if (fullUrl.includes("/place_bet") && body) {
    try {
      const payload =
        typeof body === "string"
          ? JSON.parse(body)
          : body;

      if (
        !payload.stake ||
        Number(payload.stake) < 1
      ) {
        console.warn(
          "⚠️ Attempting to place bet with invalid stake:",
          payload
        );
      }
    } catch {}
  }

  return timeoutFetch(timeout, (signal) =>
    fetch(fullUrl, {
      ...options,
      signal,
    })
  );
}

// ============================================================
// REQUESTER
// ============================================================

export function makeRequester(baseUrl) {
  const base = String(baseUrl).replace(/\/+$/, "");

  async function requestRawFor(
    path,
    opts = {},
    retry = true
  ) {
    const url = path.startsWith("/")
      ? `${base}${path}`
      : `${base}/${path}`;

    const headers = {
      ...(opts.headers || {}),
    };

    const token = getAuthToken();

    if (
      token &&
      !headers.Authorization
    ) {
      headers.Authorization = `Bearer ${token}`;
    }

    try {
      const res = await rawFetch(
        opts.method || "GET",
        url,
        {
          ...opts,
          headers,
        }
      );

      const text = await res.text();

      let data = null;

      try {
        data = text
          ? JSON.parse(text)
          : text;
      } catch {
        data = text;
      }

      // ------------------------------------------------------
      // TOKEN EXPIRED
      // ------------------------------------------------------

      if (
        res.status === 401 &&
        retry
      ) {
        const newToken =
          await refreshToken();

        if (newToken) {
          headers.Authorization =
            `Bearer ${newToken}`;

          return requestRawFor(
            path,
            {
              ...opts,
              headers,
            },
            false
          );
        }

        clearToken();
      }

      // ------------------------------------------------------
      // ERROR
      // ------------------------------------------------------

      if (!res.ok) {
        const err =
          typeof data === "object"
            ? data.error ||
              JSON.stringify(data)
            : data ||
              res.statusText;

        return {
          success: false,
          status: res.status,
          error: err,
        };
      }

      // ------------------------------------------------------
      // SUCCESS
      // ------------------------------------------------------

      return {
        success: true,
        status: res.status,
        data,
      };
    } catch (err) {
      return {
        success: false,
        error:
          err.message ||
          "Network error",
      };
    }
  }

  async function request(
    path,
    method = "GET",
    body = null,
    token = null
  ) {
    const headers = token
      ? {
          Authorization: `Bearer ${token}`,
        }
      : {};

    return requestRawFor(path, {
      method,
      body,
      headers,
    });
  }

  return {
    requestRaw: requestRawFor,
    request,
  };
}

// ============================================================
// ROUTE -> BACKEND
// ============================================================

function resolveBackend(path) {
  // Admin / VIP API
  if (
    path.startsWith("/vip") ||
    path.startsWith("/admin")
  ) {
    return BACKEND_ADMIN;
  }

  // Betting / authentication API
  const betPaths = [
    "/login",
    "/signup",
    "/balance",
    "/deposit",
    "/withdraw",
    "/place_bet",
    "/refresh",
    "/me",
    "/transactions",
    "/tickets",
    "/my_bets",
    "/cashout",
    "/profit",
    "/profit_history",
    "/stats",
    "/odds",
    "/markets",
  ];

  if (
    betPaths.some((p) =>
      path.startsWith(p)
    )
  ) {
    return BACKEND_BET;
  }

  // Football / virtual API
  return BACKEND_FOOTBALL;
}

// ============================================================
// PUBLIC REQUEST FUNCTIONS
// ============================================================

export async function requestRaw(
  path,
  opts = {}
) {
  const backend =
    resolveBackend(path);

  const requester =
    makeRequester(backend);

  return requester.requestRaw(
    path,
    opts
  );
}

export async function request(
  path,
  method = "GET",
  body = null,
  token = null
) {
  const backend =
    resolveBackend(path);

  const requester =
    makeRequester(backend);

  return requester.request(
    path,
    method,
    body,
    token
  );
}
