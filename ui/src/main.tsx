import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { registerServiceWorker } from "./pwa";
import "./styles.css";

registerServiceWorker({
  enabled: import.meta.env.PROD,
  buildId: import.meta.env.VITE_APP_BUILD,
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
