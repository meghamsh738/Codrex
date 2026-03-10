import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { registerServiceWorker } from "../pwa";

describe("registerServiceWorker", () => {
  const originalReadyState = document.readyState;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Object.defineProperty(document, "readyState", {
      configurable: true,
      value: originalReadyState,
    });
  });

  it("does nothing when disabled", () => {
    const register = vi.fn();
    vi.stubGlobal("navigator", { serviceWorker: { register } });

    registerServiceWorker({ enabled: false });

    expect(register).not.toHaveBeenCalled();
  });

  it("registers immediately once the document is already loaded", () => {
    const register = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { serviceWorker: { register } });
    Object.defineProperty(document, "readyState", {
      configurable: true,
      value: "complete",
    });

    registerServiceWorker({ enabled: true, serviceWorkerUrl: "/sw.js" });

    expect(register).toHaveBeenCalledWith("/sw.js");
  });

  it("waits for the load event before registering", () => {
    const register = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { serviceWorker: { register } });
    Object.defineProperty(document, "readyState", {
      configurable: true,
      value: "loading",
    });

    registerServiceWorker({ enabled: true, serviceWorkerUrl: "/sw.js" });
    expect(register).not.toHaveBeenCalled();

    window.dispatchEvent(new Event("load"));
    expect(register).toHaveBeenCalledWith("/sw.js");
  });
});
