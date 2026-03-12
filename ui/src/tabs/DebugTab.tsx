import type { CodexRunDetail, CodexRunSummary } from "../types";

interface AppEventItem {
  id: string;
  at: number;
  level: "info" | "error";
  message: string;
}

interface IpcEventView {
  id: string;
  seq: number;
  at: number;
  channel: string;
  direction: string;
  method?: string;
  path: string;
  status?: number;
  durationMs?: number;
  detail?: string;
  requestBody?: string;
  responseBody?: string;
}

interface DebugTabProps {
  screenCardClassName: string;
  totalEvents: number;
  errorEvents: number;
  debugRuns: CodexRunSummary[];
  debugLoading: boolean;
  refreshDebugRuns: () => void;
  selectedRunId: string;
  setSelectedRunId: (id: string) => void;
  eventLog: AppEventItem[];
  ipcFilter: "all" | "http" | "sse" | "error";
  setIpcFilter: (value: "all" | "http" | "sse" | "error") => void;
  filteredIpcHistory: IpcEventView[];
  ipcSearch: string;
  setIpcSearch: (value: string) => void;
  onExportIpcHistory: () => void;
  ipcHistoryCount: number;
  onClearIpcHistory: () => void;
  selectedIpcEvent: IpcEventView | null;
  setSelectedIpcId: (id: string) => void;
  onCopySelectedIpc: () => void;
  selectedRunLoading: boolean;
  selectedRun: CodexRunDetail | null;
  formatClock: (value: number) => string;
}

export default function DebugTab({
  screenCardClassName,
  totalEvents,
  errorEvents,
  debugRuns,
  debugLoading,
  refreshDebugRuns,
  selectedRunId,
  setSelectedRunId,
  eventLog,
  ipcFilter,
  setIpcFilter,
  filteredIpcHistory,
  ipcSearch,
  setIpcSearch,
  onExportIpcHistory,
  ipcHistoryCount,
  onClearIpcHistory,
  selectedIpcEvent,
  setSelectedIpcId,
  onCopySelectedIpc,
  selectedRunLoading,
  selectedRun,
  formatClock,
}: DebugTabProps) {
  return (
    <section className={screenCardClassName} data-testid="tab-panel-debug">
      <div className="card-head">
        <h2>Debug Timeline</h2>
        <div className="row">
          <span className="badge">Events {totalEvents}</span>
          <span className={`badge ${errorEvents > 0 ? "warn" : "muted"}`}>Errors {errorEvents}</span>
          <span className="badge muted">Runs {debugRuns.length}</span>
          <button type="button" className="button soft compact" onClick={() => void refreshDebugRuns()}>
            Refresh Runs
          </button>
        </div>
      </div>

      <div className="debug-layout">
        <div className="debug-column">
          <div className="debug-block">
            <h3>Controller Runs</h3>
            {debugLoading ? <p className="small">Loading run history...</p> : null}
            {!debugLoading && debugRuns.length === 0 ? (
              <div className="empty-state panel-empty">
                <h3>No runs yet</h3>
                <p>Run history appears here when `/codex/exec` jobs are used.</p>
              </div>
            ) : null}
            <div className="run-list" role="list" aria-label="Codex exec runs">
              {debugRuns.map((run) => {
                const selected = run.id === selectedRunId;
                return (
                  <button key={run.id} type="button" className={`run-item ${selected ? "selected" : ""}`} onClick={() => setSelectedRunId(run.id)}>
                    <div className="session-row">
                      <strong>{run.id}</strong>
                      <span className={`state state-${run.status}`}>{run.status}</span>
                    </div>
                    <p>{run.prompt || "(no prompt)"}</p>
                    <small>Duration: {run.duration_s ?? "-"}</small>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="debug-block">
            <h3>App Event Timeline</h3>
            {eventLog.length === 0 ? (
              <p className="small">No events yet.</p>
            ) : (
              <div className="event-list" role="list" aria-label="Application events">
                {eventLog.map((evt) => (
                  <div key={evt.id} className={`event-item ${evt.level === "error" ? "error" : ""}`}>
                    <div className="session-row">
                      <strong>{formatClock(evt.at)}</strong>
                      <span className={`badge ${evt.level === "error" ? "" : "muted"}`}>{evt.level === "error" ? "Error" : "Info"}</span>
                    </div>
                    <p>{evt.message}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="debug-block">
            <div className="card-head">
              <h3>IPC History</h3>
              <div className="row">
                <select value={ipcFilter} onChange={(event) => setIpcFilter(event.target.value as "all" | "http" | "sse" | "error")}>
                  <option value="all">All</option>
                  <option value="http">HTTP</option>
                  <option value="sse">SSE</option>
                  <option value="error">Errors</option>
                </select>
                <span className="badge muted">{filteredIpcHistory.length}</span>
              </div>
            </div>
            <div className="row">
              <input type="text" value={ipcSearch} onChange={(event) => setIpcSearch(event.target.value)} placeholder="Search path, detail, payload..." />
              <button type="button" className="button soft compact" onClick={onExportIpcHistory} disabled={ipcHistoryCount === 0}>
                Export JSON
              </button>
              <button type="button" className="button soft compact" onClick={onClearIpcHistory} disabled={ipcHistoryCount === 0}>
                Clear
              </button>
            </div>
            {filteredIpcHistory.length === 0 ? (
              <p className="small">No IPC events for this filter.</p>
            ) : (
              <div className="event-list" role="list" aria-label="IPC history">
                {filteredIpcHistory.slice(0, 240).map((evt) => (
                  <button
                    key={evt.id}
                    type="button"
                    className={`event-item ${evt.direction === "error" ? "error" : ""} ${selectedIpcEvent?.id === evt.id ? "selected" : ""}`}
                    onClick={() => setSelectedIpcId(evt.id)}
                  >
                    <div className="session-row">
                      <strong>{formatClock(evt.at)}</strong>
                      <span className={`badge ${evt.direction === "error" ? "" : "muted"}`}>
                        #{evt.seq} {evt.channel.toUpperCase()} {evt.direction.toUpperCase()}
                      </span>
                    </div>
                    <p>
                      [{evt.method || "GET"}] {evt.path}
                      {typeof evt.status === "number" ? ` | status ${evt.status}` : ""}
                      {typeof evt.durationMs === "number" ? ` | ${evt.durationMs}ms` : ""}
                    </p>
                    {evt.detail ? <p>{evt.detail}</p> : null}
                  </button>
                ))}
              </div>
            )}
            {selectedIpcEvent ? (
              <div className="quick-open-card">
                <div className="detail-head">
                  <h3>Selected IPC Event</h3>
                  <button type="button" className="button soft compact" onClick={() => void onCopySelectedIpc()}>
                    Copy
                  </button>
                </div>
                <p className="small">
                  #{selectedIpcEvent.seq} | {selectedIpcEvent.channel.toUpperCase()} {selectedIpcEvent.direction.toUpperCase()} | {formatClock(selectedIpcEvent.at)}
                </p>
                <label className="field">
                  <span>Request Body</span>
                  <pre className="console">{selectedIpcEvent.requestBody || "(none)"}</pre>
                </label>
                <label className="field">
                  <span>Response Body</span>
                  <pre className="console">{selectedIpcEvent.responseBody || "(none)"}</pre>
                </label>
              </div>
            ) : null}
          </div>
        </div>

        <div className="debug-column">
          <div className="debug-block">
            <h3>Selected Run Detail</h3>
            {!selectedRunId ? (
              <div className="empty-state panel-empty">
                <h3>Select a run</h3>
                <p>Choose a run from the list to inspect full output and exit code.</p>
              </div>
            ) : selectedRunLoading ? (
              <p className="small">Loading run detail...</p>
            ) : !selectedRun ? (
              <p className="small">Run details unavailable.</p>
            ) : (
              <div className="stack">
                <p className="small">
                  Status: <strong>{selectedRun.status}</strong> | Exit: <strong>{selectedRun.exit_code ?? "-"}</strong> | Duration: <strong>{selectedRun.duration_s ?? "-"}</strong>
                </p>
                <label className="field">
                  <span>Prompt</span>
                  <textarea readOnly rows={4} value={selectedRun.prompt || ""} />
                </label>
                <label className="field">
                  <span>Output</span>
                  <pre className="console">{selectedRun.output || "(no output captured)"}</pre>
                </label>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
