import { memo } from "react";
import type { SessionInfo } from "../../types";

interface SessionGroupView {
  project: string;
  items: SessionInfo[];
}

interface SessionListPanelProps {
  sessionsLoading: boolean;
  sessionsCount: number;
  filteredCount: number;
  visibleSessionCountLabel: string;
  sessionViewMode: "grouped" | "flat";
  groupedSessions: SessionGroupView[];
  filteredSessions: SessionInfo[];
  selectedSession: string;
  sessionBusy: boolean;
  onSelectSession: (session: string) => void;
  onCloseSession: (session: string) => void;
  inferProjectFromCwd: (cwd: string) => string;
}

interface SessionCardProps {
  session: SessionInfo;
  selected: boolean;
  project: string;
  sessionBusy: boolean;
  onSelectSession: (session: string) => void;
  onCloseSession: (session: string) => void;
}

const SessionCard = memo(function SessionCard({
  session,
  selected,
  project,
  sessionBusy,
  onSelectSession,
  onCloseSession,
}: SessionCardProps) {
  const handleSelectSession = () => {
    onSelectSession(session.session);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`Open ${session.session}`}
      className={`session-item ${selected ? "selected" : ""}`}
      onClick={handleSelectSession}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          handleSelectSession();
        }
      }}
    >
      <div className="session-row">
        <strong>{session.session}</strong>
        <div className="session-row-actions">
          <span className={`state state-${session.state}`}>{session.state}</span>
          <button
            type="button"
            className="session-close-chip"
            aria-label={`Close ${session.session}`}
            title={`Close ${session.session}`}
            onClick={(event) => {
              event.stopPropagation();
              onCloseSession(session.session);
            }}
            disabled={sessionBusy}
          >
            ×
          </button>
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
  filteredCount,
  visibleSessionCountLabel,
  sessionViewMode,
  groupedSessions,
  filteredSessions,
  selectedSession,
  sessionBusy,
  onSelectSession,
  onCloseSession,
  inferProjectFromCwd,
}: SessionListPanelProps) {
  return (
    <>
      <div className="session-subhead">
        <p>{visibleSessionCountLabel}</p>
        <p>Only the selected session stays live; background sessions use cached summaries.</p>
      </div>

      {sessionsLoading ? <p className="small">Loading sessions...</p> : null}
      {!sessionsLoading && sessionsCount === 0 ? (
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
              onSelectSession={onSelectSession}
              onCloseSession={onCloseSession}
            />
          ))}
        </div>
      )}
    </>
  );
});
