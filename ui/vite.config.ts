import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import packageJson from "./package.json";

const backendOrigin = process.env["VITE_BACKEND_ORIGIN"] ?? "http://127.0.0.1:8787";
const appBuild = `${packageJson.version}-${Date.now()}`;

export default defineConfig({
  define: {
    "import.meta.env.VITE_APP_BUILD": JSON.stringify(appBuild),
  },
  plugins: [react()],
  server: {
    proxy: {
      "/auth": backendOrigin,
      "/net": backendOrigin,
      "/codex": backendOrigin,
      "/legacy": backendOrigin,
      "/desktop": backendOrigin,
      "/tmux": backendOrigin,
      "/wsl": backendOrigin,
      "/shares": backendOrigin,
      "/share": backendOrigin,
      "/telegram": backendOrigin
    }
  },
  preview: {
    proxy: {
      "/auth": backendOrigin,
      "/net": backendOrigin,
      "/codex": backendOrigin,
      "/legacy": backendOrigin,
      "/desktop": backendOrigin,
      "/tmux": backendOrigin,
      "/wsl": backendOrigin,
      "/shares": backendOrigin,
      "/share": backendOrigin,
      "/telegram": backendOrigin
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "src/**/*.spec.ts", "src/**/*.spec.tsx"],
    exclude: [
      "e2e/**",
      "playwright.config.*",
      "test-results/**",
      "playwright-report/**",
      "e2e/**/*.spec.ts",
      "e2e/**/*.spec.tsx",
    ],
  }
});
