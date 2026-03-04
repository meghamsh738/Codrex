import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

const backendOrigin = process.env["VITE_BACKEND_ORIGIN"] ?? "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        id: "/",
        name: "Codrex Remote Controller",
        short_name: "Codrex",
        description: "Secure mobile control surface for Codrex sessions over Tailscale or trusted networks.",
        lang: "en-US",
        scope: "/",
        theme_color: "#0f766e",
        background_color: "#edf6ff",
        display: "standalone",
        display_override: ["standalone", "minimal-ui", "browser"],
        start_url: "/?source=pwa",
        icons: [
          {
            src: "/icon-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any"
          },
          {
            src: "/icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any"
          },
          {
            src: "/icon-maskable-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "maskable"
          },
          {
            src: "/icon-maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable"
          }
        ]
      }
    })
  ],
  server: {
    proxy: {
      "/auth": backendOrigin,
      "/net": backendOrigin,
      "/codex": backendOrigin,
      "/legacy": backendOrigin,
      "/desktop": backendOrigin,
      "/tmux": backendOrigin,
      "/wsl": backendOrigin
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
      "/wsl": backendOrigin
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"]
  }
});
