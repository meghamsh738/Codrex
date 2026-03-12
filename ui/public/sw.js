const VERSION = new URL(self.location.href).searchParams.get("v") || "dev";
const CACHE_NAME = `codrex-shell-${VERSION}`;
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
const CACHEABLE_PREFIXES = ["/assets/", "/icon", "/apple-touch-icon", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES)).catch(() => undefined),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key.startsWith("codrex-shell-") && key !== CACHE_NAME).map((key) => caches.delete(key))),
    ).then(() => self.clients.claim()),
  );
});

async function fetchAndCache(request) {
  const response = await fetch(request);
  if (response.ok) {
    const copy = response.clone();
    void caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)).catch(() => undefined);
  }
  return response;
}

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
      fetchAndCache(request).catch(async () => (await caches.match("/")) || Response.error()),
    );
    return;
  }

  const shouldCache = CACHEABLE_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));
  if (!shouldCache) {
    return;
  }

  event.respondWith(
    fetchAndCache(request).catch(async () => (await caches.match(request)) || Response.error()),
  );
});
