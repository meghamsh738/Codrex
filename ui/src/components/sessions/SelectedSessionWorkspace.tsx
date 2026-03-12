import { memo, type RefObject } from "react";
import type { SessionInfo, SessionNoteInfo } from "../../types";

type StreamProfile = "fast" | "balanced" | "battery";
type OutputFeedState = "off" | "polling" | "connecting" | "live" | "error";

interface TranscriptChunkLike {
  id: string;
  text: string;
}

interface SelectedSessionWorkspaceProps {
  selectedSessionInfo: SessionInfo;
  outputFeedState: OutputFeedState;
  streamEnabled: boolean;
  streamProfile: StreamProfile;
  onToggleStream: () => void;
  onStreamProfileChange: (value: string) => void;
  sessionAutoFollow: boolean;
  sessionUnreadCount: number;
  onJumpToLive: () => void;
  sessionOutputRef: RefObject<HTMLPreElement | null>;
  onSessionOutputScroll: () => void;
  sessionTranscriptChunks: TranscriptChunkLike[];
  promptText: string;
  onPromptTextChange: (value: string) => void;
  canSendPrompt: boolean;
  sessionBusy: boolean;
  composerTelegramBusy: boolean;
  composerTelegramDisabledReason: string;
  onSendComposerToTelegram: () => void;
  onSendPrompt: () => void;
  sessionImageInputRef: RefObject<HTMLInputElement | null>;
  sessionImageFile: File | null;
  onSessionImageFileChange: (file: File | null) => void;
  sessionImagePrompt: string;
  onSessionImagePromptChange: (value: string) => void;
  onOpenImagePicker: () => void;
  onSendSessionImage: () => void;
  onRefreshSession: () => void;
  onSendEnter: () => void;
  onSendBackspace: () => void;
  onSendArrowKey: (key: "up" | "down" | "left" | "right") => void;
  onInterrupt: () => void;
  onCtrlC: () => void;
  onCloseSession: () => void;
  sessionNotesInfo: SessionNoteInfo | null;
  sessionNotesSavedLabel: string;
  sessionNotesBusy: boolean;
  sessionNotesLoading: boolean;
  onSaveSessionNotes: () => void;
  onAppendLatestToSessionNotes: () => void;
  onCopyLatestSessionResponse: () => void;
  hasLatestSessionResponse: boolean;
  onCopySessionNotes: () => void;
  onClearSessionNotes: () => void;
  sessionNotes: string;
  onSessionNotesChange: (value: string) => void;
  latestSessionResponseSnapshot: string;
}

interface SessionTranscriptPanelProps {
  outputFeedState: OutputFeedState;
  streamEnabled: boolean;
  sessionAutoFollow: boolean;
  sessionUnreadCount: number;
  onJumpToLive: () => void;
  sessionOutputRef: RefObject<HTMLPreElement | null>;
  onSessionOutputScroll: () => void;
  sessionTranscriptChunks: TranscriptChunkLike[];
}

const SessionTranscriptPanel = memo(function SessionTranscriptPanel({
  outputFeedState,
  streamEnabled,
  sessionAutoFollow,
  sessionUnreadCount,
  onJumpToLive,
  sessionOutputRef,
  onSessionOutputScroll,
  sessionTranscriptChunks,
}: SessionTranscriptPanelProps) {
  return (
    <div className="session-console-card session-console-primary">
      <div className="session-console-head">
        <div>
          <h3>Live Transcript</h3>
          <p className="small">
            {streamEnabled ? "Structured session stream over WebSocket." : "Polling snapshot fallback only."}
          </p>
        </div>
        <div className="session-console-meta">
          {!sessionAutoFollow && sessionUnreadCount > 0 ? (
            <button
              type="button"
              className="button soft compact button-light is-warn"
              onClick={onJumpToLive}
            >
              Jump to Live ({sessionUnreadCount})
            </button>
          ) : null}
          <span className={`mode-pill ${streamEnabled ? "mode-live" : "mode-muted"}`}>
            {streamEnabled ? outputFeedState : "polling only"}
          </span>
          <span className={`mode-pill ${sessionAutoFollow ? "mode-ready" : "mode-muted"}`}>
            {sessionAutoFollow ? "auto-follow" : "reader mode"}
          </span>
        </div>
      </div>
      <pre
        ref={sessionOutputRef}
        className="console session-console"
        onScroll={onSessionOutputScroll}
        data-testid="session-console"
      >
        {sessionTranscriptChunks.length > 0
          ? sessionTranscriptChunks.map((chunk) => <span key={chunk.id}>{chunk.text}</span>)
          : "(No screen output captured yet)"}
      </pre>
    </div>
  );
});

interface SessionComposerPanelProps {
  promptText: string;
  onPromptTextChange: (value: string) => void;
  canSendPrompt: boolean;
  sessionBusy: boolean;
  composerTelegramBusy: boolean;
  composerTelegramDisabledReason: string;
  onSendComposerToTelegram: () => void;
  onSendPrompt: () => void;
  sessionImageInputRef: RefObject<HTMLInputElement | null>;
  sessionImageFile: File | null;
  onSessionImageFileChange: (file: File | null) => void;
  sessionImagePrompt: string;
  onSessionImagePromptChange: (value: string) => void;
  onOpenImagePicker: () => void;
  onSendSessionImage: () => void;
}

const SessionComposerPanel = memo(function SessionComposerPanel({
  promptText,
  onPromptTextChange,
  canSendPrompt,
  sessionBusy,
  composerTelegramBusy,
  composerTelegramDisabledReason,
  onSendComposerToTelegram,
  onSendPrompt,
  sessionImageInputRef,
  sessionImageFile,
  onSessionImageFileChange,
  sessionImagePrompt,
  onSessionImagePromptChange,
  onOpenImagePicker,
  onSendSessionImage,
}: SessionComposerPanelProps) {
  return (
    <div className="quick-open-card session-composer-shell">
      <div className="session-pane-head">
        <div>
          <h3>Prompt Composer</h3>
          <p className="small">Draft on the left, then keep one tap to send while the transcript stays visible.</p>
        </div>
        <span className={`mode-pill ${canSendPrompt ? "mode-ready" : "mode-muted"}`}>
          {canSendPrompt ? "ready to send" : "composer idle"}
        </span>
      </div>
      <div className="prompt-composer">
        <label className="field">
          <span>Prompt Composer</span>
          <div className="composer-input-wrap">
            <textarea
              value={promptText}
              onChange={(event) => onPromptTextChange(event.target.value)}
              rows={5}
              placeholder="Type your prompt. Codrex will send Enter + Enter to submit."
            />
            <div className="composer-action-stack">
              <div className="composer-action-row">
                <input
                  ref={sessionImageInputRef}
                  type="file"
                  accept="image/*"
                  data-testid="session-image-input"
                  className="sr-only"
                  onChange={(event) => onSessionImageFileChange(event.target.files?.[0] || null)}
                />
                <button
                  type="button"
                  className={`composer-icon-btn ${sessionImageFile ? "is-active" : ""}`}
                  data-testid="composer-image-picker"
                  aria-label={sessionImageFile ? `Selected image ${sessionImageFile.name}` : "Choose image"}
                  title={sessionImageFile ? `Selected image: ${sessionImageFile.name}` : "Choose an image to insert into the composer"}
                  onClick={onOpenImagePicker}
                >
                  <span className="composer-telegram-glyph" aria-hidden="true">🖼</span>
                </button>
                <button
                  type="button"
                  className="composer-telegram-btn"
                  data-testid="composer-send-telegram"
                  aria-label="Ask Codex to send via Telegram"
                  title={
                    composerTelegramDisabledReason
                    || "Append a Telegram send instruction for the current task output and send it through the active session."
                  }
                  onClick={onSendComposerToTelegram}
                  disabled={composerTelegramBusy || !!composerTelegramDisabledReason}
                >
                  <span className="composer-telegram-glyph" aria-hidden="true">✈</span>
                  <span className="composer-telegram-label">{composerTelegramBusy ? "Asking..." : "Telegram"}</span>
                </button>
              </div>
            </div>
            <button
              type="button"
              className="composer-send-btn"
              data-testid="composer-send-prompt"
              aria-label={sessionBusy ? "Sending prompt" : "Send prompt"}
              onClick={onSendPrompt}
              disabled={sessionBusy || !canSendPrompt}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M3 11.8 20.6 4.3a1 1 0 0 1 1.3 1.3L14.4 23.2a1 1 0 0 1-1.9-.3l-1-6-6-1a1 1 0 0 1-.3-1.9Z"
                  fill="currentColor"
                />
              </svg>
            </button>
          </div>
        </label>
      </div>
      {sessionImageFile ? (
        <div className="composer-media-inline" data-testid="composer-image-panel">
          <span className="mode-pill mode-ready">{sessionImageFile.name}</span>
          <input
            type="text"
            value={sessionImagePrompt}
            onChange={(event) => onSessionImagePromptChange(event.target.value)}
            placeholder="Optional image instruction"
          />
          <button
            type="button"
            className="button soft compact button-light is-active"
            onClick={onSendSessionImage}
            disabled={sessionBusy || !sessionImageFile}
          >
            Send Image
          </button>
        </div>
      ) : null}
    </div>
  );
});

interface SessionActionDockProps {
  sessionBusy: boolean;
  onRefreshSession: () => void;
  onSendEnter: () => void;
  onSendBackspace: () => void;
  onSendArrowKey: (key: "up" | "down" | "left" | "right") => void;
  onInterrupt: () => void;
  onCtrlC: () => void;
  onCloseSession: () => void;
}

const SessionActionDock = memo(function SessionActionDock({
  sessionBusy,
  onRefreshSession,
  onSendEnter,
  onSendBackspace,
  onSendArrowKey,
  onInterrupt,
  onCtrlC,
  onCloseSession,
}: SessionActionDockProps) {
  return (
    <div className="session-action-dock" data-testid="session-action-dock">
      <div className="session-action-group session-action-group-wide" role="group" aria-label="Session utility controls">
        <button
          type="button"
          className="button soft compact action-chip button-light"
          data-short="REF"
          onClick={onRefreshSession}
        >
          <span className="btn-glyph" aria-hidden="true">↻</span>
          <span className="btn-text">Refresh</span>
        </button>
        <button type="button" className="button soft compact action-chip button-light is-active" data-short="ENT" onClick={onSendEnter} disabled={sessionBusy}>
          <span className="btn-glyph" aria-hidden="true">↵</span>
          <span className="btn-text">Enter</span>
        </button>
        <button type="button" className="button soft compact action-chip button-light" data-short="⌫" onClick={onSendBackspace} disabled={sessionBusy}>
          <span className="btn-glyph" aria-hidden="true">⌫</span>
          <span className="btn-text">Backspace</span>
        </button>
      </div>
      <div className="arrow-cluster" role="group" aria-label="Session arrow keys">
        <span className="arrow-cluster-gap" aria-hidden="true" />
        <button type="button" className="button soft compact arrow-key button-light" data-short="UP" aria-label="Up" onClick={() => onSendArrowKey("up")} disabled={sessionBusy}>
          <span className="btn-text" aria-hidden="true">↑</span>
        </button>
        <span className="arrow-cluster-gap" aria-hidden="true" />
        <button type="button" className="button soft compact arrow-key button-light" data-short="LT" aria-label="Left" onClick={() => onSendArrowKey("left")} disabled={sessionBusy}>
          <span className="btn-text" aria-hidden="true">←</span>
        </button>
        <button type="button" className="button soft compact arrow-key button-light" data-short="DN" aria-label="Down" onClick={() => onSendArrowKey("down")} disabled={sessionBusy}>
          <span className="btn-text" aria-hidden="true">↓</span>
        </button>
        <button type="button" className="button soft compact arrow-key button-light" data-short="RT" aria-label="Right" onClick={() => onSendArrowKey("right")} disabled={sessionBusy}>
          <span className="btn-text" aria-hidden="true">→</span>
        </button>
      </div>
      <div className="session-action-group" role="group" aria-label="Session safety controls">
        <button type="button" className="button warn compact action-chip button-light is-warn" data-short="INT" onClick={onInterrupt} disabled={sessionBusy}>
          <span className="btn-text">Interrupt</span>
        </button>
        <button type="button" className="button danger compact action-chip button-light is-danger" data-short="C^C" onClick={onCtrlC} disabled={sessionBusy}>
          <span className="btn-text">Ctrl+C</span>
        </button>
        <button type="button" className="button danger compact action-chip button-light is-danger" data-short="CLS" onClick={onCloseSession} disabled={sessionBusy}>
          <span className="btn-text">Close</span>
        </button>
      </div>
    </div>
  );
});

interface SessionNotesPanelProps {
  sessionNotesInfo: SessionNoteInfo | null;
  sessionNotesSavedLabel: string;
  sessionNotesBusy: boolean;
  sessionNotesLoading: boolean;
  onSaveSessionNotes: () => void;
  onAppendLatestToSessionNotes: () => void;
  onCopyLatestSessionResponse: () => void;
  hasLatestSessionResponse: boolean;
  onCopySessionNotes: () => void;
  onClearSessionNotes: () => void;
  sessionNotes: string;
  onSessionNotesChange: (value: string) => void;
  latestSessionResponseSnapshot: string;
}

const SessionNotesPanel = memo(function SessionNotesPanel({
  sessionNotesInfo,
  sessionNotesSavedLabel,
  sessionNotesBusy,
  sessionNotesLoading,
  onSaveSessionNotes,
  onAppendLatestToSessionNotes,
  onCopyLatestSessionResponse,
  hasLatestSessionResponse,
  onCopySessionNotes,
  onClearSessionNotes,
  sessionNotes,
  onSessionNotesChange,
  latestSessionResponseSnapshot,
}: SessionNotesPanelProps) {
  return (
    <section className="session-secondary-shell">
      <div className="session-secondary-card">
        <div className="session-pane-head">
          <div>
            <h3>Notes</h3>
            <p className="small">Keep plans, checkpoints, and captured Codex replies attached to this session.</p>
          </div>
          <span className={`mode-pill ${sessionNotesInfo?.updated_at ? "mode-ready" : "mode-muted"}`}>
            {sessionNotesSavedLabel}
          </span>
        </div>
        <div className="session-pane-card" data-testid="session-notes-panel">
          <div className="row">
            <button
              type="button"
              className="button soft compact button-light is-active"
              onClick={onSaveSessionNotes}
              disabled={sessionNotesBusy || sessionNotesLoading}
            >
              {sessionNotesBusy ? "Saving..." : "Save"}
            </button>
            <button
              type="button"
              className="button soft compact button-light"
              onClick={onAppendLatestToSessionNotes}
              disabled={sessionNotesBusy || sessionNotesLoading}
            >
              Append Latest Response
            </button>
            <button
              type="button"
              className="button soft compact button-light"
              onClick={onCopyLatestSessionResponse}
              disabled={!hasLatestSessionResponse}
            >
              Copy Latest Response
            </button>
            <button
              type="button"
              className="button soft compact button-light"
              onClick={onCopySessionNotes}
              disabled={!sessionNotes.trim()}
            >
              Copy Notes
            </button>
            <button
              type="button"
              className="button danger compact button-light is-danger"
              onClick={onClearSessionNotes}
              disabled={sessionNotesBusy || sessionNotesLoading || !sessionNotes.trim()}
            >
              Clear Notes
            </button>
          </div>
          <div className="session-pane-scroll">
            {sessionNotesLoading ? <p className="small">Loading notes...</p> : null}
            {!sessionNotesLoading && !sessionNotes.trim() ? (
              <div className="empty-state panel-empty">
                <h3>No notes yet</h3>
                <p>Use this space for plans, checklists, or summaries from the current Codex session.</p>
              </div>
            ) : null}
            <label className="field">
              <span>Notes</span>
              <textarea
                data-testid="session-notes-input"
                value={sessionNotes}
                onChange={(event) => onSessionNotesChange(event.target.value)}
                rows={12}
                placeholder="Write session notes here. Save keeps them attached to this Codex session."
              />
            </label>
            <p className="small">
              Latest response snapshot: <strong>{latestSessionResponseSnapshot ? "available" : "not captured yet"}</strong>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
});

export const SelectedSessionWorkspace = memo(function SelectedSessionWorkspace({
  selectedSessionInfo,
  outputFeedState,
  streamEnabled,
  streamProfile,
  onToggleStream,
  onStreamProfileChange,
  sessionAutoFollow,
  sessionUnreadCount,
  onJumpToLive,
  sessionOutputRef,
  onSessionOutputScroll,
  sessionTranscriptChunks,
  promptText,
  onPromptTextChange,
  canSendPrompt,
  sessionBusy,
  composerTelegramBusy,
  composerTelegramDisabledReason,
  onSendComposerToTelegram,
  onSendPrompt,
  sessionImageInputRef,
  sessionImageFile,
  onSessionImageFileChange,
  sessionImagePrompt,
  onSessionImagePromptChange,
  onOpenImagePicker,
  onSendSessionImage,
  onRefreshSession,
  onSendEnter,
  onSendBackspace,
  onSendArrowKey,
  onInterrupt,
  onCtrlC,
  onCloseSession,
  sessionNotesInfo,
  sessionNotesSavedLabel,
  sessionNotesBusy,
  sessionNotesLoading,
  onSaveSessionNotes,
  onAppendLatestToSessionNotes,
  onCopyLatestSessionResponse,
  hasLatestSessionResponse,
  onCopySessionNotes,
  onClearSessionNotes,
  sessionNotes,
  onSessionNotesChange,
  latestSessionResponseSnapshot,
}: SelectedSessionWorkspaceProps) {
  return (
    <>
      <div className="detail-head">
        <div>
          <h3>{selectedSessionInfo.session}</h3>
          <p className="small">
            State: {selectedSessionInfo.state} | Command: {selectedSessionInfo.current_command || "(none)"}
          </p>
          <p className="small">
            Refresh updates pane output. Interrupt sends Esc (soft stop), Ctrl+C sends terminal interrupt,
            and Close ends the tmux session.
          </p>
        </div>
      </div>

      <div className="row output-controls session-composer-card">
        <span className={`badge ${outputFeedState === "live" ? "" : "muted"}`}>
          Output: {outputFeedState}
        </span>
        <button
          type="button"
          className={`button soft compact button-light ${streamEnabled ? "is-active" : ""}`}
          data-testid="toggle-live-output"
          onClick={onToggleStream}
        >
          {streamEnabled ? "Live On" : "Live Off"}
        </button>
        <label className="field inline">
          <span>Profile</span>
          <select
            data-testid="stream-profile-select"
            value={streamProfile}
            onChange={(event) => onStreamProfileChange(event.target.value)}
            disabled={!streamEnabled}
          >
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="battery">Battery</option>
          </select>
        </label>
      </div>

      <div className="session-workspace">
        <section className="session-live-shell">
          <SessionTranscriptPanel
            outputFeedState={outputFeedState}
            streamEnabled={streamEnabled}
            sessionAutoFollow={sessionAutoFollow}
            sessionUnreadCount={sessionUnreadCount}
            onJumpToLive={onJumpToLive}
            sessionOutputRef={sessionOutputRef}
            onSessionOutputScroll={onSessionOutputScroll}
            sessionTranscriptChunks={sessionTranscriptChunks}
          />

          <SessionComposerPanel
            promptText={promptText}
            onPromptTextChange={onPromptTextChange}
            canSendPrompt={canSendPrompt}
            sessionBusy={sessionBusy}
            composerTelegramBusy={composerTelegramBusy}
            composerTelegramDisabledReason={composerTelegramDisabledReason}
            onSendComposerToTelegram={onSendComposerToTelegram}
            onSendPrompt={onSendPrompt}
            sessionImageInputRef={sessionImageInputRef}
            sessionImageFile={sessionImageFile}
            onSessionImageFileChange={onSessionImageFileChange}
            sessionImagePrompt={sessionImagePrompt}
            onSessionImagePromptChange={onSessionImagePromptChange}
            onOpenImagePicker={onOpenImagePicker}
            onSendSessionImage={onSendSessionImage}
          />

          <SessionActionDock
            sessionBusy={sessionBusy}
            onRefreshSession={onRefreshSession}
            onSendEnter={onSendEnter}
            onSendBackspace={onSendBackspace}
            onSendArrowKey={onSendArrowKey}
            onInterrupt={onInterrupt}
            onCtrlC={onCtrlC}
            onCloseSession={onCloseSession}
          />
        </section>

        <SessionNotesPanel
          sessionNotesInfo={sessionNotesInfo}
          sessionNotesSavedLabel={sessionNotesSavedLabel}
          sessionNotesBusy={sessionNotesBusy}
          sessionNotesLoading={sessionNotesLoading}
          onSaveSessionNotes={onSaveSessionNotes}
          onAppendLatestToSessionNotes={onAppendLatestToSessionNotes}
          onCopyLatestSessionResponse={onCopyLatestSessionResponse}
          hasLatestSessionResponse={hasLatestSessionResponse}
          onCopySessionNotes={onCopySessionNotes}
          onClearSessionNotes={onClearSessionNotes}
          sessionNotes={sessionNotes}
          onSessionNotesChange={onSessionNotesChange}
          latestSessionResponseSnapshot={latestSessionResponseSnapshot}
        />
      </div>
    </>
  );
});
