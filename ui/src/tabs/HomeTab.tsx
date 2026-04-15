import type { ReactNode } from "react";

interface HomeTabProps {
  screenCardClassName: string;
  compactMode: boolean;
  routeHeadline: string;
  routeDetail: string;
  preferredOrigin: string;
  sessionCountLabel: string;
  sessionsRuntimeState: string;
  sessionsRuntimeDetail: string;
  sessionsCanStart: boolean;
  sessionsCanStop: boolean;
  sessionsBusy: boolean;
  desktopSummary: string;
  desktopTransportSummary: string;
  transferWorkspace: ReactNode;
  onOpenRemote: () => void;
  onOpenSessions: () => void;
  onStartSessions: () => void;
  onStopSessions: () => void;
  onOpenPair: () => void;
  onOpenSettings: () => void;
  onOpenThreads: () => void;
  onOpenDebug: () => void;
  onOpenLegacy: () => void;
}

function HomeIcon({ kind }: { kind: "remote" | "route" | "sessions" | "transfer" | "settings" | "threads" | "debug" | "legacy" }) {
  if (kind === "remote") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="3.5" y="5" width="17" height="11" rx="2.6" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M9 19h6M12 16v3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <path d="m8.5 10 3.2 2.2 4.3-3.2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "route") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4.5 8.5h8.8a3.2 3.2 0 1 0 0-6.4H10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <path d="M19.5 15.5h-8.8a3.2 3.2 0 1 0 0 6.4H14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <path d="M8.8 8.5 15.2 15.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "sessions") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="3.5" y="4.5" width="17" height="15" rx="3" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M7 9h4m-4 4h10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "transfer") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6 8h12m-12 8h12M8.8 5.5 6 8l2.8 2.5m6.4 3 2.8 2.5-2.8 2.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (kind === "settings") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M12 3.8v2.5m0 11.4v2.5m8.2-8.2h-2.5M6.3 12H3.8m14.1-5.9-1.8 1.8M7.9 16.1l-1.8 1.8m0-11.8 1.8 1.8m8.2 8.2 1.8 1.8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "threads") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="4" y="4.5" width="13" height="10" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M8 9h5m-5 3h7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <path d="M9 14.5 8 19l3.5-2.4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "debug") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M7.5 6.2h9A2.8 2.8 0 0 1 19.3 9v5.2a4.8 4.8 0 0 1-4.8 4.8h-5A4.8 4.8 0 0 1 4.7 14.2V9a2.8 2.8 0 0 1 2.8-2.8Z" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M9.3 3.8h5.4M8 11h.01M16 11h.01" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6.5 6.5h11v11h-11z" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M9 9h6v6H9z" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

export default function HomeTab({
  screenCardClassName,
  compactMode,
  routeHeadline,
  routeDetail,
  preferredOrigin,
  sessionCountLabel,
  sessionsRuntimeState,
  sessionsRuntimeDetail,
  sessionsCanStart,
  sessionsCanStop,
  sessionsBusy,
  desktopSummary,
  desktopTransportSummary,
  transferWorkspace,
  onOpenRemote,
  onOpenSessions,
  onStartSessions,
  onStopSessions,
  onOpenPair,
  onOpenSettings,
  onOpenThreads,
  onOpenDebug,
  onOpenLegacy,
}: HomeTabProps) {
  if (compactMode) {
    return (
      <section className={`${screenCardClassName} home-screen compact-home-screen compact-home-menu-screen`} data-testid="tab-panel-home">
        <div className="home-compact-header">
          <p className="home-kicker">Codrex</p>
          <h2>Your laptop, in reach.</h2>
          <p className="home-header-copy">Remote, sessions, and transfers.</p>
        </div>

        <div className="home-menu-board">
        <div className="home-menu-stack">
          <button type="button" className="home-menu-item home-menu-item-primary" onClick={onOpenRemote}>
            <span className="home-menu-icon" aria-hidden="true"><HomeIcon kind="remote" /></span>
            <span className="home-menu-copy">
              <strong>Remote</strong>
              <span>Open your desktop.</span>
            </span>
          </button>

          <button type="button" className="home-menu-item" onClick={onOpenSessions}>
            <span className="home-menu-icon" aria-hidden="true"><HomeIcon kind="sessions" /></span>
            <span className="home-menu-copy">
              <strong>Sessions</strong>
              <span>Ubuntu runtime and work.</span>
            </span>
          </button>

          <details className="home-inline-transfer">
            <summary>
              <span className="home-menu-icon" aria-hidden="true"><HomeIcon kind="transfer" /></span>
              <span className="home-menu-copy">
                <strong>Transfers</strong>
                <span>Move files both ways.</span>
              </span>
            </summary>
            <div className="home-inline-transfer-body">
              {transferWorkspace}
            </div>
          </details>

          <button type="button" className="home-menu-item" onClick={onOpenPair}>
            <span className="home-menu-icon" aria-hidden="true"><HomeIcon kind="route" /></span>
            <span className="home-menu-copy">
              <strong>Pair device</strong>
              <span>Add another device.</span>
            </span>
          </button>
        </div>
        </div>

        <div className="home-support-board" aria-label="Quick resume">
          <button type="button" className="home-support-item" onClick={onOpenRemote}>
            <span className="home-support-icon" aria-hidden="true"><HomeIcon kind="remote" /></span>
            <span className="home-support-copy">
              <span className="home-support-kicker">Resume last</span>
              <strong>Jump back into Remote</strong>
              <span>{desktopSummary}</span>
            </span>
          </button>
          <button type="button" className="home-support-item" onClick={onOpenSessions}>
            <span className="home-support-icon" aria-hidden="true"><HomeIcon kind="sessions" /></span>
            <span className="home-support-copy">
              <span className="home-support-kicker">Recent session</span>
              <strong>Continue in Sessions</strong>
              <span>{sessionsRuntimeState} / {sessionCountLabel}</span>
            </span>
          </button>
        </div>

        <details className="home-advanced">
          <summary>Advanced</summary>
          <div className="home-advanced-facts">
            <div className="home-fact">
              <span>Route</span>
              <strong>{routeHeadline}</strong>
            </div>
            <div className="home-fact">
              <span>Origin</span>
              <strong>{preferredOrigin || "Not ready"}</strong>
            </div>
            <div className="home-fact">
              <span>Remote</span>
              <strong>{desktopTransportSummary}</strong>
            </div>
          </div>
          <div className="home-advanced-grid">
            <button type="button" className="button soft compact" onClick={onOpenSettings}>
              <span className="btn-glyph" aria-hidden="true"><HomeIcon kind="settings" /></span>
              Settings
            </button>
            <button type="button" className="button soft compact" onClick={onOpenThreads}>
              <span className="btn-glyph" aria-hidden="true"><HomeIcon kind="threads" /></span>
              Threads
            </button>
            <button type="button" className="button soft compact" onClick={onOpenDebug}>
              <span className="btn-glyph" aria-hidden="true"><HomeIcon kind="debug" /></span>
              Debug
            </button>
            <button type="button" className="button soft compact" onClick={onOpenLegacy}>
              <span className="btn-glyph" aria-hidden="true"><HomeIcon kind="legacy" /></span>
              Legacy
            </button>
          </div>
        </details>
      </section>
    );
  }

  return (
    <section className={`${screenCardClassName} home-screen`} data-testid="tab-panel-home">
      <div className="home-header-strip">
        <div>
          <p className="home-kicker">Codrex</p>
          <h2>Remote Control</h2>
          <p className="home-header-copy">Direct access to your laptop, sessions, and transfers without extra setup noise.</p>
        </div>
        <div className="home-header-meta">
          <span>{sessionCountLabel}</span>
          <span>{sessionsRuntimeState}</span>
        </div>
      </div>

      <div className="home-grid">
        <section className="home-hero">
          <div className="home-hero-copywrap">
            <span className="home-hero-icon" aria-hidden="true"><HomeIcon kind="route" /></span>
            <div>
              <p className="home-kicker">Connection</p>
              <h3>{routeHeadline}</h3>
              <p className="home-copy">{routeDetail}</p>
              <p className="home-origin">{preferredOrigin || "No private route origin detected yet."}</p>
            </div>
          </div>
          <div className="home-hero-actions">
            <button type="button" className="button" onClick={onOpenRemote}>
              <span className="btn-glyph" aria-hidden="true"><HomeIcon kind="remote" /></span>
              Resume Remote
            </button>
            <button type="button" className="button soft compact" onClick={onOpenPair}>
              <span className="btn-glyph" aria-hidden="true"><HomeIcon kind="route" /></span>
              Pair Device
            </button>
          </div>
          <div className="home-hero-summary" aria-label="Current state">
            <span className="badge muted">{desktopSummary}</span>
            <span className="badge muted">{sessionsRuntimeState}</span>
            <span className="badge muted">{sessionCountLabel}</span>
          </div>
        </section>

        <section className="home-card home-command-card">
          <div className="home-card-head">
            <div className="home-card-heading">
              <span className="home-card-icon remote" aria-hidden="true"><HomeIcon kind="remote" /></span>
              <div>
              <p className="home-kicker">Remote</p>
              <h3>Live Desktop</h3>
              </div>
            </div>
            <span className="badge muted">{desktopSummary}</span>
          </div>
          <p className="home-copy">{desktopTransportSummary}</p>
          <p className="home-card-note">Open the live stage directly when you want control, not setup.</p>
          <div className="home-card-actions">
            <button type="button" className="button" onClick={onOpenRemote}>
              <span className="btn-glyph" aria-hidden="true"><HomeIcon kind="remote" /></span>
              Enter Remote
            </button>
          </div>
        </section>

        <section className="home-card home-command-card">
          <div className="home-card-head">
            <div className="home-card-heading">
              <span className="home-card-icon sessions" aria-hidden="true"><HomeIcon kind="sessions" /></span>
              <div>
              <p className="home-kicker">Sessions</p>
              <h3>Session Runtime</h3>
              </div>
            </div>
            <span className={`badge muted state-${sessionsRuntimeState.toLowerCase()}`}>{sessionCountLabel}</span>
          </div>
          <p className="home-copy">{sessionsRuntimeDetail}</p>
          <p className="home-card-note">WSL stays manual so the controller remains light at startup.</p>
          <div className="home-card-actions">
            <button type="button" className="button" onClick={onOpenSessions}>
              <span className="btn-glyph" aria-hidden="true"><HomeIcon kind="sessions" /></span>
              Open Sessions
            </button>
            {sessionsCanStart ? (
              <button type="button" className="button soft compact" onClick={onStartSessions} disabled={sessionsBusy}>
                {sessionsBusy ? "Starting..." : "Start Sessions"}
              </button>
            ) : null}
            {sessionsCanStop ? (
              <button type="button" className="button soft compact" onClick={onStopSessions} disabled={sessionsBusy}>
                {sessionsBusy ? "Stopping..." : "Stop Sessions"}
              </button>
            ) : null}
          </div>
        </section>

        <section className="home-card home-transfer-card">
          {transferWorkspace}
        </section>
      </div>

      <details className="home-advanced">
        <summary>Advanced</summary>
        <div className="home-advanced-facts">
          <div className="home-fact">
            <span>Route</span>
            <strong>{routeHeadline}</strong>
          </div>
          <div className="home-fact">
            <span>Origin</span>
            <strong>{preferredOrigin || "Not ready"}</strong>
          </div>
          <div className="home-fact">
            <span>Remote</span>
            <strong>{desktopTransportSummary}</strong>
          </div>
        </div>
        <div className="home-advanced-grid">
          <button type="button" className="button soft compact" onClick={onOpenSettings}>
            <span className="btn-glyph" aria-hidden="true"><HomeIcon kind="settings" /></span>
            Settings
          </button>
          <button type="button" className="button soft compact" onClick={onOpenThreads}>
            <span className="btn-glyph" aria-hidden="true"><HomeIcon kind="threads" /></span>
            Threads
          </button>
          <button type="button" className="button soft compact" onClick={onOpenDebug}>
            <span className="btn-glyph" aria-hidden="true"><HomeIcon kind="debug" /></span>
            Debug
          </button>
          <button type="button" className="button soft compact" onClick={onOpenLegacy}>
            <span className="btn-glyph" aria-hidden="true"><HomeIcon kind="legacy" /></span>
            Legacy
          </button>
        </div>
      </details>
    </section>
  );
}
