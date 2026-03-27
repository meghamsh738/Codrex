interface RegisterServiceWorkerOptions {
  enabled?: boolean;
  serviceWorkerUrl?: string;
  buildId?: string;
}

const BUILD_STORAGE_KEY = "codrex.ui.build.v1";
const BUILD_RELOAD_KEY = "codrex.ui.build.reload.v1";
const CACHE_PREFIX = "codrex-shell-";

async function clearCodrexCaches(): Promise<void> {
  if (typeof window === "undefined" || !("caches" in window)) {
    return;
  }
  try {
    const keys = await window.caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith(CACHE_PREFIX)).map((key) => window.caches.delete(key)));
  } catch {
    // Cache cleanup is best effort only.
  }
}

async function unregisterCodrexWorkers(): Promise<void> {
  if (typeof navigator === "undefined" || !navigator.serviceWorker?.getRegistrations) {
    return;
  }
  try {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map((registration) => registration.unregister()));
  } catch {
    // Keep startup resilient when worker cleanup fails.
  }
}

async function ensureFreshBuild(buildId: string): Promise<boolean> {
  if (typeof window === "undefined") {
    return true;
  }
  const previousBuild = window.localStorage.getItem(BUILD_STORAGE_KEY);
  if (previousBuild && previousBuild !== buildId) {
    window.localStorage.setItem(BUILD_STORAGE_KEY, buildId);
    await unregisterCodrexWorkers();
    await clearCodrexCaches();
    if (window.sessionStorage.getItem(BUILD_RELOAD_KEY) !== buildId) {
      window.sessionStorage.setItem(BUILD_RELOAD_KEY, buildId);
      window.location.reload();
      return false;
    }
  }
  window.localStorage.setItem(BUILD_STORAGE_KEY, buildId);
  window.sessionStorage.removeItem(BUILD_RELOAD_KEY);
  return true;
}

export function registerServiceWorker(options: RegisterServiceWorkerOptions = {}): void {
  const { enabled = true, serviceWorkerUrl = "/sw.js", buildId = "dev" } = options;
  if (!enabled || typeof window === "undefined" || typeof navigator === "undefined") {
    return;
  }
  if (!("serviceWorker" in navigator)) {
    return;
  }

  const onLoad = () => {
    void (async () => {
      const shouldRegister = await ensureFreshBuild(buildId);
      if (!shouldRegister) {
        return;
      }
      const separator = serviceWorkerUrl.includes("?") ? "&" : "?";
      const versionedUrl = `${serviceWorkerUrl}${separator}v=${encodeURIComponent(buildId)}`;
      try {
        const registration = await navigator.serviceWorker.register(versionedUrl);
        void registration.update().catch(() => {
          // Background update checks are best effort only.
        });
      } catch {
        // Keep startup resilient when service worker registration fails.
      }
    })();
  };

  if (document.readyState === "complete") {
    onLoad();
    return;
  }

  window.addEventListener("load", onLoad, { once: true });
}
