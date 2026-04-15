import { useId, useRef } from "react";

import type { SharedFileInfo } from "../../types";

type TransferVariant = "home" | "remote";
type HostTransferMode = "default" | "focused";
type HostTransferPostAction = "none" | "open" | "reveal";

export interface TransferWorkspaceItem extends SharedFileInfo {
  activityLabel: string;
  activityDetail: string;
}

interface TransferWorkspaceProps {
  variant: TransferVariant;
  desktopSelectedPath: string;
  desktopPathSummary: string;
  desktopInteractionDisabled: boolean;
  hostTransferFileName: string;
  hostTransferMode: HostTransferMode;
  hostTransferBusy: boolean;
  hostTransferStatus: string;
  lastHostTransferPath: string;
  recentItems: TransferWorkspaceItem[];
  onCopyFocusedPath: () => void;
  onChooseHostTransferFile: (file: File | null) => void;
  onHostTransferModeChange: (mode: HostTransferMode) => void;
  onUploadHostTransfer: (postAction?: HostTransferPostAction) => void;
  onPickAndShareLaptopFile: () => void;
  onShareFocusedHostSelection: () => void;
  onOpenHostPath: (path: string) => void;
  onRevealHostPath: (path: string) => void;
}

function TransferIcon({ kind }: { kind: "inbox" | "device" | "laptop" | "share" | "folder" | "send" }) {
  if (kind === "device") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="7" y="3.5" width="10" height="17" rx="2.3" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <path d="M10 6.2h4m-6 11.6h8" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "laptop") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="5.4" y="5.4" width="13.2" height="9.2" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <path d="M3.8 17.8h16.4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "share") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="7" cy="12" r="2.1" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <circle cx="17" cy="7" r="2.1" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <circle cx="17" cy="17" r="2.1" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <path d="m8.8 11 6.1-2.8m-6.1 4.8 6.1 2.8" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "folder") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 7.2h5l1.7 2H20v7.8A2 2 0 0 1 18 19H6a2 2 0 0 1-2-2Z" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      </svg>
    );
  }
  if (kind === "send") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="m4.2 12 14.8-6.2-3.4 6.2 3.4 6.2Z" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
        <path d="M4.2 12H15" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 8h12m-12 8h12M8.8 5.5 6 8l2.8 2.5m6.4 3 2.8 2.5-2.8 2.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function TransferWorkspace({
  variant,
  desktopSelectedPath,
  desktopPathSummary,
  desktopInteractionDisabled,
  hostTransferFileName,
  hostTransferMode,
  hostTransferBusy,
  hostTransferStatus,
  lastHostTransferPath,
  recentItems,
  onCopyFocusedPath,
  onChooseHostTransferFile,
  onHostTransferModeChange,
  onUploadHostTransfer,
  onPickAndShareLaptopFile,
  onShareFocusedHostSelection,
  onOpenHostPath,
  onRevealHostPath,
}: TransferWorkspaceProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const fileInputId = useId();
  const focusedDestinationDisabled = desktopInteractionDisabled && hostTransferMode === "focused";
  const hasRecentItems = recentItems.length > 0;

  return (
    <section
      className={`transfer-workspace transfer-workspace-${variant}`}
      data-testid={variant === "remote" ? "remote-transfer-center" : "home-transfer-center"}
    >
      <div className="transfer-workspace-head">
        <div>
          <p className="transfer-kicker">Transfers</p>
          <h4>Transfer Center</h4>
          <p className="small">
            {variant === "remote"
              ? "Keep laptop file exchange close to the live stage without leaving Remote."
              : "Handle device and laptop file exchange from one quiet task surface."}
          </p>
        </div>
        <div className="transfer-head-stats" aria-hidden="true">
          <div className="transfer-stat-card">
            <strong>{hostTransferFileName ? "Ready" : "Idle"}</strong>
            <span>{hostTransferFileName || "Choose a file from the device"}</span>
          </div>
          <div className="transfer-stat-card">
            <strong>{recentItems.length}</strong>
            <span>recent jobs</span>
          </div>
        </div>
      </div>

      <div className="transfer-workspace-grid">
        <article className="transfer-surface">
          <div className="transfer-surface-head">
            <span className="transfer-surface-icon device"><TransferIcon kind="device" /></span>
            <div>
              <h5>Device to Laptop</h5>
              <p className="small">Receive a file on Windows, then optionally open it or reveal it in Explorer immediately.</p>
            </div>
          </div>

          <div className="transfer-file-picker">
            <input
              id={fileInputId}
              ref={fileInputRef}
              type="file"
              className="sr-only"
              data-testid={variant === "remote" ? "remote-host-upload-input" : "home-host-upload-input"}
              onChange={(event) => onChooseHostTransferFile(event.target.files?.[0] || null)}
              disabled={hostTransferBusy}
            />
            <button
              type="button"
              className={`button ${hostTransferFileName ? "soft" : ""} compact transfer-picker-button`}
              onClick={() => fileInputRef.current?.click()}
              disabled={hostTransferBusy}
            >
              <span className="btn-glyph" aria-hidden="true"><TransferIcon kind="inbox" /></span>
              <span className="btn-text">{hostTransferFileName ? "Change Device File" : "Choose Device File"}</span>
            </button>
            <label className="transfer-file-label" htmlFor={fileInputId}>
              {hostTransferFileName || "No file selected yet"}
            </label>
          </div>

          <div className="transfer-mode-segment" role="group" aria-label="Host transfer destination">
            <button
              type="button"
              className={`button soft compact ${hostTransferMode === "default" ? "active" : ""}`}
              onClick={() => onHostTransferModeChange("default")}
              disabled={hostTransferBusy}
            >
              Downloads\Codrex Transfers
            </button>
            <button
              type="button"
              className={`button soft compact ${hostTransferMode === "focused" ? "active" : ""}`}
              onClick={() => onHostTransferModeChange("focused")}
              disabled={hostTransferBusy}
            >
              Send Here
            </button>
          </div>

          <div className="transfer-action-strip">
            <button
              type="button"
              className="button compact"
              data-testid={variant === "remote" ? "remote-host-upload-button" : "home-host-upload-button"}
              onClick={() => onUploadHostTransfer("none")}
              disabled={hostTransferBusy || !hostTransferFileName || focusedDestinationDisabled}
            >
              <span className="btn-glyph" aria-hidden="true"><TransferIcon kind="send" /></span>
              <span className="btn-text">Send To Host</span>
            </button>
            <button
              type="button"
              className="button soft compact"
              onClick={() => onUploadHostTransfer("open")}
              disabled={hostTransferBusy || !hostTransferFileName || focusedDestinationDisabled}
            >
              <span className="btn-glyph" aria-hidden="true"><TransferIcon kind="laptop" /></span>
              <span className="btn-text">Open On Host</span>
            </button>
            <button
              type="button"
              className="button soft compact"
              onClick={() => onUploadHostTransfer("reveal")}
              disabled={hostTransferBusy || !hostTransferFileName || focusedDestinationDisabled}
            >
              <span className="btn-glyph" aria-hidden="true"><TransferIcon kind="folder" /></span>
              <span className="btn-text">Reveal In Explorer</span>
            </button>
          </div>
        </article>

        <article className="transfer-surface">
          <div className="transfer-surface-head">
            <span className="transfer-surface-icon laptop"><TransferIcon kind="laptop" /></span>
            <div>
              <h5>Laptop to Device</h5>
              <p className="small">Publish a laptop file or the current Explorer selection so the tablet can download it immediately.</p>
            </div>
          </div>

          <div
            className={`remote-path-browser-copy transfer-inline-strip${variant === "remote" ? "" : " home-transfer-path"}`}
            data-testid={variant === "remote" ? "remote-selected-path" : "home-selected-path"}
          >
            <input
              type="text"
              readOnly
              value={desktopSelectedPath || ""}
              placeholder="No focused Explorer selection copied yet"
              aria-label="Selected host path"
            />
            <button
              type="button"
              className="button soft compact action-chip"
              onClick={onCopyFocusedPath}
              disabled={desktopInteractionDisabled}
            >
              <span className="btn-glyph" aria-hidden="true"><TransferIcon kind="folder" /></span>
              <span className="btn-text">Copy Focused Path</span>
            </button>
          </div>
          <p className="small remote-path-browser-folder">{desktopPathSummary}</p>

          <div className="transfer-action-stack">
            <button
              type="button"
              className="button soft compact"
              data-testid={variant === "remote" ? "remote-host-picker-share" : "home-host-picker-share"}
              onClick={onPickAndShareLaptopFile}
              disabled={hostTransferBusy}
            >
              <span className="btn-glyph" aria-hidden="true"><TransferIcon kind="share" /></span>
              <span className="btn-text">Choose From Laptop</span>
            </button>
            <button
              type="button"
              className="button soft compact"
              data-testid={variant === "remote" ? "remote-host-share-selection" : "home-host-share-selection"}
              onClick={onShareFocusedHostSelection}
              disabled={hostTransferBusy || desktopInteractionDisabled}
            >
              <span className="btn-glyph" aria-hidden="true"><TransferIcon kind="folder" /></span>
              <span className="btn-text">Share Focused Selection</span>
            </button>
          </div>
        </article>
      </div>

      {hostTransferStatus ? (
        <div className="transfer-status-banner">
          <span className="transfer-status-dot" aria-hidden="true" />
          <span>{hostTransferStatus}</span>
        </div>
      ) : null}

      {lastHostTransferPath ? (
        <div className="transfer-quick-actions">
          <button type="button" className="button soft compact" onClick={() => onOpenHostPath(lastHostTransferPath)}>
            <span className="btn-glyph" aria-hidden="true"><TransferIcon kind="laptop" /></span>
            <span className="btn-text">Open Latest On Host</span>
          </button>
          <button type="button" className="button soft compact" onClick={() => onRevealHostPath(lastHostTransferPath)}>
            <span className="btn-glyph" aria-hidden="true"><TransferIcon kind="folder" /></span>
            <span className="btn-text">Reveal Latest</span>
          </button>
        </div>
      ) : null}

      <div className="transfer-history">
        <div className="transfer-history-head">
          <div>
            <p className="transfer-kicker">Recent jobs</p>
            <h5>Activity</h5>
          </div>
        </div>
        {hasRecentItems ? (
          <div className="transfer-history-list">
            {recentItems.map((item) => (
              <article key={item.id} className="transfer-history-item">
                <div className="transfer-history-main">
                  <span className="mode-pill">{item.activityLabel}</span>
                  <strong>{item.file_name}</strong>
                  <span className="small">{item.activityDetail}</span>
                </div>
                <div className="transfer-history-actions">
                  {item.download_url ? (
                    <a className="button soft compact" href={item.download_url} download={item.file_name}>
                      <span className="btn-glyph" aria-hidden="true"><TransferIcon kind="device" /></span>
                      <span className="btn-text">Download</span>
                    </a>
                  ) : null}
                  {item.windows_path ? (
                    <>
                      <button type="button" className="button soft compact" onClick={() => onOpenHostPath(item.windows_path || "")}>
                        <span className="btn-glyph" aria-hidden="true"><TransferIcon kind="laptop" /></span>
                        <span className="btn-text">Open</span>
                      </button>
                      <button type="button" className="button soft compact" onClick={() => onRevealHostPath(item.windows_path || "")}>
                        <span className="btn-glyph" aria-hidden="true"><TransferIcon kind="folder" /></span>
                        <span className="btn-text">Reveal</span>
                      </button>
                    </>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="transfer-empty-state">
            <span className="transfer-empty-icon" aria-hidden="true"><TransferIcon kind="inbox" /></span>
            <div>
              <strong>No transfer jobs yet</strong>
              <p className="small">The first upload or shared selection will appear here with direct reopen actions.</p>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
