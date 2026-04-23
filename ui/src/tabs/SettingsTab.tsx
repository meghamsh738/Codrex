import type { Dispatch, SetStateAction } from "react";
import type { AuthStatus, DesktopTargetInfo, LoopPreset, LoopWorkerInfo, NetInfo } from "../types";

type RouteHint = "preferred" | "lan" | "tailscale" | "netbird" | "current";
type ThemeMode = "system" | "light" | "dark";

interface SettingsTabProps {
  screenCardClassName: string;
  authLoading: boolean;
  auth: AuthStatus | null;
  authBusy: boolean;
  onBootstrapLocalAuth: () => void;
  tokenInput: string;
  setTokenInput: (value: string) => void;
  onLogin: () => void;
  refreshAuth: () => void;
  onLogout: () => void;
  touchComfortMode: boolean;
  setTouchComfortMode: Dispatch<SetStateAction<boolean>>;
  compactTranscript: boolean;
  setCompactTranscript: Dispatch<SetStateAction<boolean>>;
  themeMode: ThemeMode;
  setThemeMode: (mode: ThemeMode) => void;
  parseThemeMode: (value: string) => ThemeMode;
  resolvedTheme: string;
  controllerRouteSummary: string;
  controllerRouteSeverity: string;
  controllerRouteAdvice: string;
  controllerBase: string;
  routeHint: RouteHint;
  prettyRouteLabel: (route: RouteHint) => string;
  netInfo: NetInfo | null;
  refreshNet: () => void;
  desktopTargets: DesktopTargetInfo[];
  activeDesktopTargetId: string;
  desktopTargetsBusy: boolean;
  desktopTargetsDetail: string;
  refreshDesktopTargets: () => void;
  onSelectDesktopTarget: (targetId: string) => void;
  loopSettingsBusy: boolean;
  loopDefaultPrompt: string;
  setLoopDefaultPrompt: Dispatch<SetStateAction<string>>;
  loopChecksText: string;
  setLoopChecksText: Dispatch<SetStateAction<string>>;
  loopGlobalPreset: "" | LoopPreset;
  setLoopGlobalPreset: Dispatch<SetStateAction<"" | LoopPreset>>;
  loopTelegramConfigured: boolean;
  loopWorker: LoopWorkerInfo | null;
  onRefreshLoopStatus: () => void;
  onSaveLoopSettings: () => void;
}

export default function SettingsTab({
  screenCardClassName,
  authLoading,
  auth,
  authBusy,
  onBootstrapLocalAuth,
  tokenInput,
  setTokenInput,
  onLogin,
  refreshAuth,
  onLogout,
  touchComfortMode,
  setTouchComfortMode,
  compactTranscript,
  setCompactTranscript,
  themeMode,
  setThemeMode,
  parseThemeMode,
  resolvedTheme,
  controllerRouteSummary,
  controllerRouteSeverity,
  controllerRouteAdvice,
  controllerBase,
  routeHint,
  prettyRouteLabel,
  netInfo,
  refreshNet,
  desktopTargets,
  activeDesktopTargetId,
  desktopTargetsBusy,
  desktopTargetsDetail,
  refreshDesktopTargets,
  onSelectDesktopTarget,
  loopSettingsBusy,
  loopDefaultPrompt,
  setLoopDefaultPrompt,
  loopChecksText,
  setLoopChecksText,
  loopGlobalPreset,
  setLoopGlobalPreset,
  loopTelegramConfigured,
  loopWorker,
  onRefreshLoopStatus,
  onSaveLoopSettings,
}: SettingsTabProps) {
  return (
    <section className={`${screenCardClassName} settings-screen settings-shell`} data-testid="tab-panel-settings">
      <div className="card-head settings-head">
        <h2>Security & Settings</h2>
        {authLoading ? <span className="badge">Checking...</span> : <span className="badge">Auth</span>}
      </div>

      {!auth ? (
        <p className="small">Loading auth state...</p>
      ) : (
      <div className="settings-layout settings-shell-grid">
          <div className="stack settings-stack settings-shell-column">
            <p className="small">
              Required: <strong>{auth.auth_required ? "Yes" : "No"}</strong> | Authenticated: <strong>{auth.authenticated ? "Yes" : "No"}</strong>
            </p>

            {auth.auth_required && !auth.authenticated ? (
              <>
              <div className="quick-open-card settings-card settings-block settings-auth">
                <h3>Laptop Quick Auth</h3>
                <p className="small">If this page is opened on localhost from your laptop, use one-tap local auth.</p>
                <button type="button" className="button" onClick={() => void onBootstrapLocalAuth()} disabled={authBusy}>
                  {authBusy ? "Authorizing..." : "Use Local Laptop Auth"}
                </button>
                </div>
                <label className="field">
                  <span>Access Token</span>
                  <input
                    type="password"
                    value={tokenInput}
                    onChange={(event) => setTokenInput(event.target.value)}
                    placeholder="Paste CODEX_AUTH_TOKEN"
                  />
                </label>
                <button type="button" className="button" onClick={() => void onLogin()} disabled={authBusy}>
                  {authBusy ? "Logging in..." : "Login"}
                </button>
                <p className="small">Use token login when local quick auth is unavailable.</p>
              </>
            ) : (
              <div className="row">
                <button type="button" className="button" onClick={() => void refreshAuth()}>
                  Recheck
                </button>
                <button type="button" className="button danger compact" onClick={() => void onLogout()} disabled={authBusy}>
                  Logout
                </button>
              </div>
            )}

            <div className="quick-open-card settings-card settings-block">
              <h3>Android Usability</h3>
              <p className="small">Tune touch targets and transcript density for phone/tablet usage.</p>
              <div className="row">
                <button type="button" className="button soft compact" data-testid="toggle-touch-comfort" onClick={() => setTouchComfortMode((current) => !current)}>
                  Touch Comfort: {touchComfortMode ? "On" : "Off"}
                </button>
                <button type="button" className="button soft compact" data-testid="toggle-compact-transcript" onClick={() => setCompactTranscript((current) => !current)}>
                  Compact Transcript: {compactTranscript ? "On" : "Off"}
                </button>
              </div>
            </div>

            <div className="quick-open-card settings-card settings-block">
              <h3>Theme</h3>
              <p className="small">Choose visual theme for laptop, Android, and tablet.</p>
              <label className="field">
                <span>Theme Mode</span>
                <select data-testid="theme-select" value={themeMode} onChange={(event) => setThemeMode(parseThemeMode(event.target.value))}>
                  <option value="dark">Dark</option>
                  <option value="light">Light</option>
                </select>
              </label>
              <p className="small">Active theme: <strong>{resolvedTheme}</strong></p>
            </div>

            <div className="quick-open-card settings-card settings-loop">
              <h3>Loop Control</h3>
              <p className="small">Loopndroll-style continuation for Codex sessions, reusing the existing Telegram bot.</p>
              <label className="field">
                <span>Global Mode</span>
                <select
                  value={loopGlobalPreset}
                  onChange={(event) => setLoopGlobalPreset(event.target.value as "" | LoopPreset)}
                  disabled={loopSettingsBusy}
                >
                  <option value="">Off</option>
                  <option value="infinite">Infinite</option>
                  <option value="await-reply">Await Reply</option>
                  <option value="completion-checks">Completion Checks</option>
                  <option value="max-turns-1">Max Turns 1</option>
                  <option value="max-turns-2">Max Turns 2</option>
                  <option value="max-turns-3">Max Turns 3</option>
                </select>
              </label>
              <label className="field">
                <span>Default Follow-up Prompt</span>
                <textarea
                  value={loopDefaultPrompt}
                  onChange={(event) => setLoopDefaultPrompt(event.target.value)}
                  rows={5}
                  disabled={loopSettingsBusy}
                  placeholder="Continue working until the task is actually done..."
                />
              </label>
              <label className="field">
                <span>Completion Checks</span>
                <textarea
                  value={loopChecksText}
                  onChange={(event) => setLoopChecksText(event.target.value)}
                  rows={4}
                  disabled={loopSettingsBusy}
                  placeholder={"pnpm test\npnpm run lint\npnpm run typecheck"}
                />
              </label>
              <p className="small">
                Telegram configured: <strong>{loopTelegramConfigured ? "Yes" : "No"}</strong> | Worker alive: <strong>{loopWorker?.alive ? "Yes" : "No"}</strong>
              </p>
              {loopWorker?.last_error ? <p className="small severity warn">{loopWorker.last_error}</p> : null}
              <div className="row">
                <button type="button" className="button soft compact" onClick={() => void onRefreshLoopStatus()} disabled={loopSettingsBusy}>
                  Refresh Loop
                </button>
                <button type="button" className="button" onClick={() => void onSaveLoopSettings()} disabled={loopSettingsBusy}>
                  {loopSettingsBusy ? "Saving..." : "Save Loop Settings"}
                </button>
              </div>
              <p className="small">Telegram commands: <code>/status</code>, <code>/list</code>, <code>/mode ...</code>, <code>/reply ...</code>.</p>
            </div>
          </div>

          <div className="stack settings-stack settings-shell-column">
            <div className="quick-open-card settings-note settings-panel">
              <h3>Connection Details</h3>
              <p className="small">Current route: <strong>{controllerRouteSummary}</strong></p>
              <p className={`small severity ${controllerRouteSeverity}`}>{controllerRouteAdvice}</p>
              <p className="small">Controller base: <code>{controllerBase || "(not set)"}</code></p>
              <p className="small">Route hint: <strong>{prettyRouteLabel(routeHint)}</strong></p>
              <p className="small">LAN: <strong>{netInfo?.lan_ip || "n/a"}</strong></p>
              <p className="small">Tailscale: <strong>{netInfo?.tailscale_ip || "n/a"}</strong></p>
              <p className="small">NetBird: <strong>{netInfo?.netbird_ip || "n/a"}</strong></p>
              <p className="small">Preferred origin: <strong>{netInfo?.preferred_origin || "n/a"}</strong></p>
              <p className="small">Browser origin: <code>{typeof window !== "undefined" ? window.location.origin : "n/a"}</code></p>
              <div className="row">
                <button type="button" className="button soft compact" onClick={() => void refreshNet()}>
                  Refresh Network
                </button>
                <button type="button" className="button soft compact" onClick={() => void refreshAuth()}>
                  Refresh Auth
                </button>
              </div>
            </div>

            <div className="quick-open-card settings-note settings-panel">
              <h3>Display Target</h3>
              <p className="small">
                Remote capture and input bind to the selected display target instead of assuming the visible laptop panel.
              </p>
              <label className="field">
                <span>Active Target</span>
                <select
                  value={activeDesktopTargetId}
                  onChange={(event) => onSelectDesktopTarget(event.target.value)}
                  disabled={desktopTargetsBusy || desktopTargets.length === 0}
                >
                  {desktopTargets.length === 0 ? <option value="">No targets detected</option> : null}
                  {desktopTargets.map((target) => (
                    <option key={target.id} value={target.id}>
                      {target.label} {target.virtual ? "(virtual)" : target.physical ? "(physical)" : ""}
                    </option>
                  ))}
                </select>
              </label>
              {desktopTargetsDetail ? <p className="small">{desktopTargetsDetail}</p> : null}
              <div className="row">
                <button type="button" className="button soft compact" onClick={() => void refreshDesktopTargets()} disabled={desktopTargetsBusy}>
                  {desktopTargetsBusy ? "Refreshing..." : "Refresh Targets"}
                </button>
              </div>
            </div>

            <div className="empty-state settings-note settings-checklist">
              <h3>Remote safety checklist</h3>
              <p>Use a private route and keep token auth enabled on backend.</p>
              <ul className="safety-list">
                <li>Avoid exposing backend ports directly to public internet.</li>
                <li>Use QR pairing for mobile sign-in instead of sharing raw token.</li>
                <li>Rotate token if devices are lost or shared.</li>
              </ul>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
