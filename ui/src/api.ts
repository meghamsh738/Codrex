import type {
  AuthStatus,
  BasicResult,
  CodexOptionsResult,
  CodexExecStartResult,
  CodexRunDetail,
  CodexRunsResult,
  DesktopInfoResult,
  DesktopInputResult,
  DesktopModeResult,
  NetInfo,
  PairCreateResult,
  SessionCreateResult,
  SessionProfileApplyResult,
  SessionImageResult,
  SessionCloseResult,
  SessionScreenResult,
  SessionsResult,
  SharedFilesResult,
  TelegramStatusResult,
  TmuxHealthResult,
  TmuxPaneScreenResult,
  TmuxPanesResult,
  TmuxSessionResult,
  ThreadDeleteResult,
  ThreadMessageResult,
  ThreadRecordResult,
  ThreadsStoreResult,
  WslUploadResult,
} from "./types";

const JSON_HEADERS = {
  "Content-Type": "application/json",
};

export type IpcDirection = "out" | "in" | "error";
export type IpcChannel = "http" | "sse";

export interface IpcEvent {
  seq: number;
  id: string;
  at: number;
  channel: IpcChannel;
  direction: IpcDirection;
  method?: string;
  path: string;
  status?: number;
  durationMs?: number;
  ok?: boolean;
  detail?: string;
  requestBody?: string;
  responseBody?: string;
}

let ipcObserver: ((event: IpcEvent) => void) | null = null;
let ipcSequence = 0;

function safePreview(value: unknown, maxLength = 2400): string | undefined {
  if (value == null) {
    return undefined;
  }
  if (typeof FormData !== "undefined" && value instanceof FormData) {
    const parts: string[] = [];
    value.forEach((entry, key) => {
      if (typeof entry === "string") {
        parts.push(`${key}="${entry}"`);
      } else {
        parts.push(`${key}=[file name="${entry.name}" size=${entry.size}]`);
      }
    });
    const joined = parts.join(", ");
    return joined.length > maxLength ? `${joined.slice(0, maxLength)}...` : joined;
  }
  if (typeof value === "string") {
    return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value;
  }
  try {
    const json = JSON.stringify(value);
    return json.length > maxLength ? `${json.slice(0, maxLength)}...` : json;
  } catch {
    return undefined;
  }
}

function emitIpcEvent(partial: Omit<IpcEvent, "id" | "at" | "seq">): void {
  if (!ipcObserver) {
    return;
  }
  try {
    ipcSequence += 1;
    ipcObserver({
      ...partial,
      seq: ipcSequence,
      id: `ipc_${Date.now()}_${ipcSequence}`,
      at: Date.now(),
    });
  } catch {
    // Do not break requests due to observer issues.
  }
}

export function setIpcObserver(observer: ((event: IpcEvent) => void) | null): void {
  ipcObserver = observer;
}

export function reportIpcEvent(event: Omit<IpcEvent, "id" | "at" | "seq">): void {
  emitIpcEvent(event);
}

function normalizeBaseUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) {
    return "";
  }
  if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
    return trimmed.replace(/\/$/, "");
  }
  return `http://${trimmed}`.replace(/\/$/, "");
}

async function parseJson<T>(res: Response): Promise<T> {
  const text = await res.text();
  if (!text) {
    return {} as T;
  }
  return JSON.parse(text) as T;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || "GET").toUpperCase();
  const startedAt = Date.now();
  const bodyPreview = safePreview(init?.body);
  let didReceiveResponse = false;

  emitIpcEvent({
    channel: "http",
    direction: "out",
    method,
    path,
    requestBody: bodyPreview,
  });

  try {
    const response = await fetch(path, {
      credentials: "include",
      ...init,
    });
    didReceiveResponse = true;

    const payload = await parseJson<T>(response);
    const durationMs = Date.now() - startedAt;
    const responsePreview = safePreview(payload);

    emitIpcEvent({
      channel: "http",
      direction: response.ok ? "in" : "error",
      method,
      path,
      status: response.status,
      durationMs,
      ok: response.ok,
      responseBody: responsePreview,
    });

    if (!response.ok) {
      const detail = (payload as { detail?: string; error?: string } | undefined)?.detail
        || (payload as { detail?: string; error?: string } | undefined)?.error;
      throw new Error(detail || `Request failed (${response.status})`);
    }

    return payload;
  } catch (error) {
    if (!didReceiveResponse) {
      emitIpcEvent({
        channel: "http",
        direction: "error",
        method,
        path,
        durationMs: Date.now() - startedAt,
        ok: false,
        detail: (error as Error).message || "request_failed",
      });
    }
    throw error;
  }
}

export function buildPairConsumeUrl(baseUrl: string, code: string): string {
  const normalized = normalizeBaseUrl(baseUrl);
  if (!normalized) {
    throw new Error("Controller base URL is required for pairing link generation.");
  }
  const url = new URL("/auth/pair/consume", normalized);
  url.searchParams.set("code", code);
  return url.toString();
}

export function buildPairQrPngUrl(baseUrl: string, data: string): string {
  const normalized = normalizeBaseUrl(baseUrl);
  if (!normalized) {
    throw new Error("Controller base URL is required for QR generation.");
  }
  const url = new URL("/auth/pair/qr.png", normalized);
  url.searchParams.set("data", data);
  return url.toString();
}

export function buildSuggestedControllerUrl(
  hostname: string,
  port: number,
  netInfo: NetInfo | null,
  route: "lan" | "tailscale" | "current",
): string {
  if (route === "lan") {
    if (netInfo?.lan_ip) {
      return `http://${netInfo.lan_ip}:${port}`;
    }
    if (netInfo?.tailscale_ip) {
      return `http://${netInfo.tailscale_ip}:${port}`;
    }
  }
  if (route === "tailscale") {
    if (netInfo?.tailscale_ip) {
      return `http://${netInfo.tailscale_ip}:${port}`;
    }
  }
  return `http://${hostname}:${port}`;
}

export function getAuthStatus(): Promise<AuthStatus> {
  return requestJson<AuthStatus>("/auth/status");
}

export function login(token: string): Promise<BasicResult> {
  return requestJson<BasicResult>("/auth/login", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ token }),
  });
}

export function bootstrapLocalAuth(): Promise<BasicResult> {
  return requestJson<BasicResult>("/auth/bootstrap/local", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function logout(): Promise<BasicResult> {
  return requestJson<BasicResult>("/auth/logout", {
    method: "POST",
  });
}

export function getNetInfo(): Promise<NetInfo> {
  return requestJson<NetInfo>("/net/info");
}

export function createPairCode(): Promise<PairCreateResult> {
  return requestJson<PairCreateResult>("/auth/pair/create", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function exchangePairCode(code: string): Promise<BasicResult> {
  return requestJson<BasicResult>("/auth/pair/exchange", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ code }),
  });
}

export function getSessions(): Promise<SessionsResult> {
  return requestJson<SessionsResult>("/codex/sessions");
}

export function createSession(name: string): Promise<SessionCreateResult> {
  return createSessionWithOptions({ name });
}

export function getCodexOptions(): Promise<CodexOptionsResult> {
  return requestJson<CodexOptionsResult>("/codex/options");
}

export function createSessionWithOptions(options: {
  name?: string;
  cwd?: string;
  model?: string;
  reasoning_effort?: string;
}): Promise<SessionCreateResult> {
  const payload: Record<string, string> = {};
  if (options.name && options.name.trim()) {
    payload.name = options.name.trim();
  }
  if (options.cwd && options.cwd.trim()) {
    payload.cwd = options.cwd.trim();
  }
  if (options.model && options.model.trim()) {
    payload.model = options.model.trim();
  }
  if (options.reasoning_effort && options.reasoning_effort.trim()) {
    payload.reasoning_effort = options.reasoning_effort.trim();
  }
  return requestJson<SessionCreateResult>("/codex/session", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function closeSession(session: string): Promise<SessionCloseResult> {
  return requestJson<SessionCloseResult>(`/codex/session/${encodeURIComponent(session)}`, {
    method: "DELETE",
  });
}

export function sendToSession(session: string, prompt: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/codex/session/${encodeURIComponent(session)}/send`, {
    method: "POST",
    headers: {
      "Content-Type": "text/plain",
    },
    body: prompt,
  });
}

export function applySessionProfile(
  session: string,
  options: { model?: string; reasoning_effort?: string },
): Promise<SessionProfileApplyResult> {
  const payload: Record<string, string> = {};
  if (options.model && options.model.trim()) {
    payload.model = options.model.trim();
  }
  if (options.reasoning_effort && options.reasoning_effort.trim()) {
    payload.reasoning_effort = options.reasoning_effort.trim();
  }
  return requestJson<SessionProfileApplyResult>(`/codex/session/${encodeURIComponent(session)}/profile`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function interruptSession(session: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/codex/session/${encodeURIComponent(session)}/interrupt`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function enterSession(session: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/codex/session/${encodeURIComponent(session)}/enter`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function sendSessionKey(session: string, key: "up" | "down" | "left" | "right"): Promise<BasicResult> {
  return requestJson<BasicResult>(`/codex/session/${encodeURIComponent(session)}/key`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ key }),
  });
}

export function ctrlcSession(session: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/codex/session/${encodeURIComponent(session)}/ctrlc`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function getSessionScreen(session: string): Promise<SessionScreenResult> {
  return requestJson<SessionScreenResult>(`/codex/session/${encodeURIComponent(session)}/screen`);
}

export function sendSessionImage(
  session: string,
  file: File,
  prompt: string,
  options?: { paste_desktop?: boolean; delivery_mode?: "desktop_clipboard" | "session_path" | "insert_path" },
): Promise<SessionImageResult> {
  const formData = new FormData();
  formData.append("file", file);
  if (prompt.trim()) {
    formData.append("prompt", prompt.trim());
  }
  if (typeof options?.paste_desktop === "boolean") {
    formData.append("paste_desktop", String(options.paste_desktop));
  }
  if (options?.delivery_mode) {
    formData.append("delivery_mode", options.delivery_mode);
  }
  return requestJson<SessionImageResult>(`/codex/session/${encodeURIComponent(session)}/image`, {
    method: "POST",
    body: formData,
  });
}

export function listSharedFiles(): Promise<SharedFilesResult> {
  return requestJson<SharedFilesResult>("/shares");
}

export function createSharedFile(payload: {
  path: string;
  title?: string;
  expires_hours?: number;
  created_by?: string;
}): Promise<SharedFilesResult> {
  return requestJson<SharedFilesResult>("/shares", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function deleteSharedFile(shareId: string): Promise<SharedFilesResult> {
  return requestJson<SharedFilesResult>(`/shares/${encodeURIComponent(shareId)}`, {
    method: "DELETE",
  });
}

export function getTelegramStatus(): Promise<TelegramStatusResult> {
  return requestJson<TelegramStatusResult>("/telegram/status");
}

export function sendSharedFileToTelegram(shareId: string, caption = ""): Promise<BasicResult> {
  return requestJson<BasicResult>(`/shares/${encodeURIComponent(shareId)}/telegram`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(caption.trim() ? { caption: caption.trim() } : {}),
  });
}

export function sendTelegramText(text: string): Promise<BasicResult> {
  return requestJson<BasicResult>("/telegram/send-text", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ text }),
  });
}

export function getCodexRuns(): Promise<CodexRunsResult> {
  return requestJson<CodexRunsResult>("/codex/runs");
}

export function getThreadStore(): Promise<ThreadsStoreResult> {
  return requestJson<ThreadsStoreResult>("/threads");
}

export function createThreadRecord(payload: { id?: string; session: string; title?: string }): Promise<ThreadRecordResult> {
  return requestJson<ThreadRecordResult>("/threads", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function updateThreadRecord(threadId: string, payload: { session?: string; title?: string }): Promise<ThreadRecordResult> {
  return requestJson<ThreadRecordResult>(`/threads/${encodeURIComponent(threadId)}`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function deleteThreadRecord(threadId: string): Promise<ThreadDeleteResult> {
  return requestJson<ThreadDeleteResult>(`/threads/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
  });
}

export function addThreadRecordMessage(
  threadId: string,
  payload: { id?: string; role: "user" | "assistant" | "system"; text: string; at?: number },
): Promise<ThreadMessageResult> {
  return requestJson<ThreadMessageResult>(`/threads/${encodeURIComponent(threadId)}/messages`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function getCodexRun(runId: string): Promise<CodexRunDetail> {
  return requestJson<CodexRunDetail>(`/codex/run/${encodeURIComponent(runId)}`);
}

export function startCodexExec(prompt: string): Promise<CodexExecStartResult> {
  return requestJson<CodexExecStartResult>("/codex/exec", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ prompt }),
  });
}

export function getTmuxHealth(): Promise<TmuxHealthResult> {
  return requestJson<TmuxHealthResult>("/tmux/health");
}

export function getTmuxPanes(session?: string): Promise<TmuxPanesResult> {
  if (!session || !session.trim()) {
    return requestJson<TmuxPanesResult>("/tmux/panes");
  }
  const params = new URLSearchParams();
  params.set("session", session.trim());
  return requestJson<TmuxPanesResult>(`/tmux/panes?${params.toString()}`);
}

export function getTmuxPaneScreen(paneId: string): Promise<TmuxPaneScreenResult> {
  return requestJson<TmuxPaneScreenResult>(`/tmux/pane/${encodeURIComponent(paneId)}/screen`);
}

export function createTmuxSession(name: string): Promise<TmuxSessionResult> {
  const payload: Record<string, string> = {};
  if (name.trim()) {
    payload.name = name.trim();
  }
  return requestJson<TmuxSessionResult>("/tmux/session", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function closeTmuxSession(session: string): Promise<TmuxSessionResult> {
  return requestJson<TmuxSessionResult>(`/tmux/session/${encodeURIComponent(session)}`, {
    method: "DELETE",
  });
}

export function sendToPane(paneId: string, text: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/tmux/pane/${encodeURIComponent(paneId)}/send`, {
    method: "POST",
    headers: {
      "Content-Type": "text/plain",
    },
    body: text,
  });
}

export function interruptPane(paneId: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/tmux/pane/${encodeURIComponent(paneId)}/ctrlc`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function getDesktopInfo(): Promise<DesktopInfoResult> {
  return requestJson<DesktopInfoResult>("/desktop/info");
}

export function setDesktopMode(enabled: boolean): Promise<DesktopModeResult> {
  return requestJson<DesktopModeResult>("/desktop/mode", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ enabled }),
  });
}

export function desktopClick(params: { button?: "left" | "right"; double?: boolean; x?: number; y?: number }): Promise<DesktopInputResult> {
  return requestJson<DesktopInputResult>("/desktop/input/click", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      button: params.button || "left",
      double: !!params.double,
      x: params.x,
      y: params.y,
    }),
  });
}

export function desktopScroll(delta: number): Promise<DesktopInputResult> {
  return requestJson<DesktopInputResult>("/desktop/input/scroll", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ delta }),
  });
}

export function desktopSendText(text: string): Promise<DesktopInputResult> {
  // Real typing path (no clipboard paste, no Enter key submit).
  return requestJson<DesktopInputResult>("/desktop/input/text", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ text }),
  });
}

export function desktopSendKey(key: string): Promise<DesktopInputResult> {
  return requestJson<DesktopInputResult>("/desktop/input/key", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ key }),
  });
}

export function buildDesktopStreamUrl(params?: { fps?: number; level?: number; scale?: number; bw?: boolean }): string {
  const query = new URLSearchParams();
  if (typeof params?.fps === "number" && Number.isFinite(params.fps)) {
    query.set("fps", String(params.fps));
  }
  if (typeof params?.level === "number" && Number.isFinite(params.level)) {
    query.set("level", String(params.level));
  }
  if (typeof params?.scale === "number" && Number.isFinite(params.scale)) {
    query.set("scale", String(params.scale));
  }
  if (params?.bw) {
    query.set("bw", "1");
  }
  const suffix = query.toString();
  return suffix ? `/desktop/stream?${suffix}` : "/desktop/stream";
}

export function buildDesktopShotUrl(params?: { level?: number; scale?: number; bw?: boolean }): string {
  const query = new URLSearchParams();
  if (typeof params?.level === "number" && Number.isFinite(params.level)) {
    query.set("level", String(params.level));
  }
  if (typeof params?.scale === "number" && Number.isFinite(params.scale)) {
    query.set("scale", String(params.scale));
  }
  if (params?.bw) {
    query.set("bw", "1");
  }
  query.set("ts", String(Date.now()));
  return `/desktop/shot?${query.toString()}`;
}

export function buildScreenshotUrl(): string {
  return `/shot?ts=${Date.now()}`;
}

export function buildWslDownloadUrl(path: string): string {
  const query = new URLSearchParams();
  query.set("path", path);
  return `/wsl/file?${query.toString()}`;
}

export function uploadWslFile(file: File, dest: string): Promise<WslUploadResult> {
  const formData = new FormData();
  formData.append("file", file);
  if (dest.trim()) {
    formData.append("dest", dest.trim());
  }
  return requestJson<WslUploadResult>("/wsl/upload", {
    method: "POST",
    body: formData,
  });
}
