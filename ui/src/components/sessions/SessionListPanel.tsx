import { memo } from "react";
import type { SessionInfo } from "../../types";

interface SessionGroupView {
  project: string;
  items: SessionInfo[];
}

interface SessionListPanelProps {
  sessionsLoading: boolean;
  sessionsCount: number;
  recentClosedCount: number;
  filteredCount: number;
  visibleSessionCountLabel: string;
  sessionViewMode: "grouped" | "flat";
  groupedSessions: SessionGroupView[];
  filteredSessions: SessionInfo[];
  recentClosedSessions: SessionInfo[];
  selectedSession: string;
  sessionBusy: boolean;
  onSelectSession: (session: string) => void;
  onCloseSession: (session: string) => void;
  onResumeSession: (session: SessionInfo) => void;
  onReopenSession: (session: SessionInfo) => void;
  inferProjectFromCwd: (cwd: string) => string;
}

interface SessionCardProps {
  session: SessionInfo;
  selected: boolean;
  project: string;
  sessionBusy: boolean;
  mode: "live" | "closed";
  onSelectSession?: (session: string) => void;
  onCloseSession?: (session: string) => void;
  onResumeSession?: (session: SessionInfo) => void;
  onReopenSession?: (session: SessionInfo) => void;
}

const SessionCard = memo(function SessionCard({
  session,
  selected,
  project,
  sessionBusy,
  mode,
  onSelectSession,
  onCloseSession,
  onResumeSession,
  onReopenSession,
}: SessionCardProps) {
  const handleSelectSession = () => {
    onSelectSession?.(session.session);
  };
  const isClosed = mode === "closed";
  const statusLabel = isClosed ? "closed" : session.state;

  return (
    <div
      role={isClosed ? undefined : "button"}
      tabIndex={isClosed ? undefined : 0}
      aria-label={isClosed ? undefined : `Open ${session.session}`}
      className={`session-item ${selected ? "selected" : ""}${isClosed ? " session-item-closed" : ""}`}
      onClick={isClosed ? undefined : handleSelectSession}
      onKeyDown={isClosed ? undefined : (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          handleSelectSession();
        }
      }}
    >
      <div className="session-row">
        <strong>{session.session}</strong>
        <div className="session-row-actions">
          <span className={`state state-${statusLabel}`}>{statusLabel}</span>
          {isClosed ? (
            <div className="session-card-actions">
              {session.can_resume ? (
                <button
                  type="button"
                  className="button soft compact"
                  onClick={() => onResumeSession?.(session)}
                  disabled={sessionBusy}
                >
                  Resume
                </button>
              ) : (
                <button
                  type="button"
                  className="button soft compact"
                  onClick={() => onReopenSession?.(session)}
                  disabled={sessionBusy}
                >
                  Reopen
                </button>
              )}
            </div>
          ) : (
            <button
              type="button"
              className="session-close-chip"
              aria-label={`Close ${session.session}`}
              title={`Close ${session.session}`}
              onClick={(event) => {
                event.stopPropagation();
                onCloseSession?.(session.session);
              }}
              disabled={sessionBusy}
            >
              ×
            </button>
          )}
        </div>
      </div>
      <p className="session-snippet">{session.snippet || "No output yet."}</p>
      <small className="session-meta">
        <span>{project}</span>
        <span>{session.model || "default model"}</span>
        <span>{session.reasoning_effort || "default reasoning"}</span>
      </small>
      <small className="session-cwd">{session.cwd || "Unknown cwd"}</small>
    </div>
  );
});

export const SessionListPanel = memo(function SessionListPanel({
  sessionsLoading,
  sessionsCount,
  recentClosedCount,
  filteredCount,
  visibleSessionCountLabel,
  sessionViewMode,
  groupedSessions,
  filteredSessions,
  recentClosedSessions,
  selectedSession,
  sessionBusy,
  onSelectSession,
  onCloseSession,
  onResumeSession,
  onReopenSession,
  inferProjectFromCwd,
}: SessionListPanelProps) {
  return (
    <>
      <div className="session-subhead">
        <p>{visibleSessionCountLabel}</p>
        <p>Only the selected session stays live; background sessions use cached summaries. Recent closed: {recentClosedCount}.</p>
      </div>

      {sessionsLoading ? <p className="small">Loading sessions...</p> : null}
      {!sessionsLoading && sessionsCount === 0 && recentClosedCount === 0 ? (
        <div className="empty-state panel-empty">
          <h3>No sessions yet</h3>
          <p>Create one to start interacting with Codex from mobile.</p>
        </div>
      ) : null}
      {!sessionsLoading && sessionsCount > 0 && filteredCount === 0 ? (
        <div className="empty-state panel-empty">
          <h3>No matching sessions</h3>
          <p>Adjust search text or project filter.</p>
        </div>
      ) : null}

      {sessionViewMode === "grouped" ? (
        groupedSessions.map((group) => (
          <div key={group.project} className="session-group">
            <div className="session-group-head">
              <strong>{group.project}</strong>
              <span className="badge muted">{group.items.length}</span>
            </div>
            <div className="session-card-grid">
              {group.items.map((session) => (
                <SessionCard
                  key={session.session}
                  session={session}
                  selected={session.session === selectedSession}
                  project={inferProjectFromCwd(session.cwd)}
                  sessionBusy={sessionBusy}
                  mode="live"
                  onSelectSession={onSelectSession}
                  onCloseSession={onCloseSession}
                />
              ))}
            </div>
          </div>
        ))
      ) : (
        <div className="session-card-grid">
          {filteredSessions.map((session) => (
            <SessionCard
              key={session.session}
              session={session}
              selected={session.session === selectedSession}
              project={inferProjectFromCwd(session.cwd)}
              sessionBusy={sessionBusy}
              mode="live"
              onSelectSession={onSelectSession}
              onCloseSession={onCloseSession}
            />
          ))}
        </div>
      )}

      {recentClosedSessions.length > 0 ? (
        <div className="session-group">
          <div className="session-group-head">
            <strong>Recent Closed Sessions</strong>
            <span className="badge muted">{recentClosedSessions.length}</span>
          </div>
          <div className="session-card-grid">
            {recentClosedSessions.map((session) => (
              <SessionCard
                key={`closed_${session.session}`}
                session={session}
                selected={false}
                project={inferProjectFromCwd(session.cwd)}
                sessionBusy={sessionBusy}
                mode="closed"
                onResumeSession={onResumeSession}
                onReopenSession={onReopenSession}
              />
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
});
