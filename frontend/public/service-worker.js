const CACHE_NAME = "lilymac-offline-v1";
const OFFLINE_PAGE = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.add(OFFLINE_PAGE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith("lilymac-offline-") && key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// Only intercept page navigations. Never cache API calls, authentication,
// account information, bets, wallet requests, or other application data.
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (
    request.method !== "GET" ||
    url.origin !== self.location.origin ||
    request.mode !== "navigate"
  ) {
    return;
  }

  event.respondWith(
    fetch(request).catch(async () => {
      const cached = await caches.match(OFFLINE_PAGE);
      return cached || new Response("You are offline.", {
        status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8" }
      });
    })
  );
});


// ============================================================
// WEB PUSH NOTIFICATIONS
// ============================================================

self.addEventListener("push", (event) => {
  let payload = {};

  try {
    payload = event.data ? event.data.json() : {};
  } catch (_) {
    payload = {
      body: event.data ? event.data.text() : ""
    };
  }

  const title = payload.title || "LilyMac VIP";
  const options = {
    body: payload.body || "You have a new VIP update.",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    data: {
      url: payload.url || "/vip"
    }
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  event.waitUntil((async () => {
    const target = new URL(
      event.notification.data?.url || "/vip",
      self.location.origin
    );

    if (target.origin !== self.location.origin) {
      return;
    }

    const windows = await self.clients.matchAll({
      type: "window",
      includeUncontrolled: true
    });

    for (const client of windows) {
      if ("focus" in client) {
        await client.focus();

        if ("navigate" in client) {
          await client.navigate(target.href);
        }

        return;
      }
    }

    await self.clients.openWindow(target.href);
  })());
});
