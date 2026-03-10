const CACHE_NAME = "codrex-shell-v1";
const SHELL_FILES = [
  "/",
  "/manifest.webmanifest",
  "/icon.svg",
  "/icon-192.png",
  "/icon-512.png",
  "/icon-maskable-192.png",
  "/icon-maskable-512.png",
  "/apple-touch-icon.png",
];
const STATIC_PREFIXES = ["/assets/", "/icon", "/apple-touch-icon", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES)).catch(() => undefined),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
    ).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          void caches.open(CACHE_NAME).then((cache) => cache.put("/", copy)).catch(() => undefined);
          return response;
        })
        .catch(async () => (await caches.match("/")) || Response.error()),
    );
    return;
  }

  const shouldCache = STATIC_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));
  if (!shouldCache) {
    return;
  }

  event.respondWith(
    caches.match(request).then(async (cached) => {
      if (cached) {
        return cached;
      }
      const response = await fetch(request);
      if (response.ok) {
        const copy = response.clone();
        void caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)).catch(() => undefined);
      }
      return response;
    }),
  );
});
