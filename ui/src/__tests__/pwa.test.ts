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

  it("registers immediately once the document is already loaded", async () => {
    const register = vi.fn().mockResolvedValue(undefined);
    const getRegistrations = vi.fn().mockResolvedValue([]);
    vi.stubGlobal("navigator", { serviceWorker: { register, getRegistrations } });
    Object.defineProperty(document, "readyState", {
      configurable: true,
      value: "complete",
    });

    registerServiceWorker({ enabled: true, serviceWorkerUrl: "/sw.js", buildId: "build-1" });
    await Promise.resolve();
    await Promise.resolve();

    expect(register).toHaveBeenCalledWith("/sw.js?v=build-1");
  });

  it("waits for the load event before registering", async () => {
    const register = vi.fn().mockResolvedValue(undefined);
    const getRegistrations = vi.fn().mockResolvedValue([]);
    vi.stubGlobal("navigator", { serviceWorker: { register, getRegistrations } });
    Object.defineProperty(document, "readyState", {
      configurable: true,
      value: "loading",
    });

    registerServiceWorker({ enabled: true, serviceWorkerUrl: "/sw.js", buildId: "build-1" });
    expect(register).not.toHaveBeenCalled();

    window.dispatchEvent(new Event("load"));
    await Promise.resolve();
    await Promise.resolve();
    expect(register).toHaveBeenCalledWith("/sw.js?v=build-1");
  });
});
