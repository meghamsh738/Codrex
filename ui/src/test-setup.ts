import "@testing-library/jest-dom/vitest";

function ensureStorageShape(storageName: "localStorage" | "sessionStorage"): void {
  const installFallback = () => {
    const state = new Map<string, string>();
    const fallback: Storage = {
      get length() {
        return state.size;
      },
      clear() {
        state.clear();
      },
      getItem(key: string) {
        return state.has(key) ? state.get(key) || null : null;
      },
      key(index: number) {
        return Array.from(state.keys())[index] || null;
      },
      removeItem(key: string) {
        state.delete(key);
      },
      setItem(key: string, value: string) {
        state.set(String(key), String(value));
      },
    };
    Object.defineProperty(window, storageName, {
      configurable: true,
      writable: true,
      value: fallback,
    });
  };

  try {
    const current = window[storageName] as Storage;
    if (
      !current ||
      typeof current.getItem !== "function" ||
      typeof current.setItem !== "function" ||
      typeof current.removeItem !== "function" ||
      typeof current.clear !== "function"
    ) {
      installFallback();
    }
  } catch {
    installFallback();
  }
}

ensureStorageShape("localStorage");
ensureStorageShape("sessionStorage");
