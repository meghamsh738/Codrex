interface RegisterServiceWorkerOptions {
  enabled?: boolean;
  serviceWorkerUrl?: string;
}

export function registerServiceWorker(options: RegisterServiceWorkerOptions = {}): void {
  const { enabled = true, serviceWorkerUrl = "/sw.js" } = options;
  if (!enabled || typeof window === "undefined" || typeof navigator === "undefined") {
    return;
  }
  if (!("serviceWorker" in navigator)) {
    return;
  }

  const onLoad = () => {
    void navigator.serviceWorker.register(serviceWorkerUrl).catch(() => {
      // Keep startup resilient when service worker registration fails.
    });
  };

  if (document.readyState === "complete") {
    onLoad();
    return;
  }

  window.addEventListener("load", onLoad, { once: true });
}
