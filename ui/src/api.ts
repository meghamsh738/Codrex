import type {
  AppRuntimeResult,
  AuthStatus,
  BasicResult,
  BrowserListResult,
  CodexOptionsResult,
  CodexRuntimeStatusResult,
  CodexExecStartResult,
  CodexRunDetail,
  CodexRunsResult,
  DesktopStreamCapabilitiesResult,
  DesktopTargetsResult,
  DesktopWebrtcOfferResult,
  DesktopInfoResult,
  DesktopInputResult,
  DesktopPasteImageResult,
  DesktopModeResult,
  HostTransferResult,
  LoopOverrideMode,
  LoopPreset,
  LoopStatusResult,
  NetInfo,
  OpenPathResult,
  PairCreateResult,
  PowerActionResult,
  PowerStatusResult,
  PrivacyLockStatusResult,
  SessionCreateResult,
  SessionFilesResult,
  SessionProfileApplyResult,
  SessionImageResult,
  SessionNotesResult,
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
export type IpcChannel = "http" | "sse" | "ws";

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

async function parseJson<T>(res: Response): Promise<T | string> {
  const text = await res.text();
  if (!text) {
    return {} as T;
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    return text;
  }
}

interface RequestJsonInit extends RequestInit {
  timeoutMs?: number;
}

async function requestJson<T>(path: string, init?: RequestJsonInit): Promise<T> {
  const method = (init?.method || "GET").toUpperCase();
  const startedAt = Date.now();
  const bodyPreview = safePreview(init?.body);
  let didReceiveResponse = false;
  const timeoutMs = typeof init?.timeoutMs === "number" && init.timeoutMs > 0 ? init.timeoutMs : 0;
  const timeoutController = timeoutMs > 0 ? new AbortController() : null;
  const timeoutHandle = timeoutController
    ? window.setTimeout(() => {
      timeoutController.abort(new Error(`Request timed out after ${timeoutMs}ms`));
    }, timeoutMs)
    : null;

  emitIpcEvent({
    channel: "http",
    direction: "out",
    method,
    path,
    requestBody: bodyPreview,
  });

  try {
    const { timeoutMs: _timeoutMs, ...requestInit } = init || {};
    const response = await fetch(path, {
      credentials: "include",
      ...requestInit,
      signal: timeoutController?.signal || requestInit.signal,
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
      const detail = typeof payload === "string"
        ? payload.trim()
        : (payload as { detail?: string; error?: string } | undefined)?.detail
          || (payload as { detail?: string; error?: string } | undefined)?.error;
      throw new Error(detail || `Request failed (${response.status})`);
    }

    return payload as T;
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
  } finally {
    if (timeoutHandle != null) {
      window.clearTimeout(timeoutHandle);
    }
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
  route: "preferred" | "lan" | "tailscale" | "netbird" | "current",
): string {
  if (route === "preferred" && netInfo?.preferred_origin) {
    return netInfo.preferred_origin;
  }
  if (route === "netbird") {
    if (netInfo?.netbird_ip) {
      return `http://${netInfo.netbird_ip}:${port}`;
    }
    if (netInfo?.preferred_origin) {
      try {
        const preferred = new URL(netInfo.preferred_origin);
        if (preferred.hostname && preferred.hostname !== "127.0.0.1" && preferred.hostname !== "localhost") {
          return netInfo.preferred_origin;
        }
      } catch {
      }
    }
  }
  if (route === "lan") {
    if (netInfo?.lan_ip) {
      return `http://${netInfo.lan_ip}:${port}`;
    }
    if (netInfo?.netbird_ip) {
      return `http://${netInfo.netbird_ip}:${port}`;
    }
    if (netInfo?.tailscale_ip) {
      return `http://${netInfo.tailscale_ip}:${port}`;
    }
  }
  if (route === "tailscale") {
    if (netInfo?.tailscale_ip) {
      return `http://${netInfo.tailscale_ip}:${port}`;
    }
    if (netInfo?.netbird_ip) {
      return `http://${netInfo.netbird_ip}:${port}`;
    }
  }
  return `http://${hostname}:${port}`;
}

export function detectControllerPort(locationPort?: string): number {
  const fromEnv = Number.parseInt(import.meta.env.VITE_BACKEND_PORT || "", 10);
  if (Number.isInteger(fromEnv) && fromEnv > 0) {
    return fromEnv;
  }
  const rawLocationPort =
    typeof locationPort === "string"
      ? locationPort
      : typeof window !== "undefined"
        ? window.location.port || ""
        : "";
  const fromLocation = Number.parseInt(rawLocationPort, 10);
  if (Number.isInteger(fromLocation) && fromLocation > 0) {
    return fromLocation;
  }
  return 48787;
}

export function getAuthStatus(): Promise<AuthStatus> {
  return requestJson<AuthStatus>("/auth/status");
}

export function getAppRuntime(): Promise<AppRuntimeResult> {
  return requestJson<AppRuntimeResult>("/app/runtime");
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

export function getCodexRuntimeStatus(): Promise<CodexRuntimeStatusResult> {
  return requestJson<CodexRuntimeStatusResult>("/codex/runtime/status");
}

export function startCodexRuntime(): Promise<CodexRuntimeStatusResult> {
  return requestJson<CodexRuntimeStatusResult>("/codex/runtime/start", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function stopCodexRuntime(): Promise<CodexRuntimeStatusResult> {
  return requestJson<CodexRuntimeStatusResult>("/codex/runtime/stop", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
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
  resume_last?: boolean;
  resume_id?: string;
}): Promise<SessionCreateResult> {
  const payload: Record<string, string | boolean> = {};
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
  if (options.resume_last) {
    payload.resume_last = true;
  }
  if (options.resume_id && options.resume_id.trim()) {
    payload.resume_id = options.resume_id.trim();
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

export function sendSessionKey(session: string, key: "up" | "down" | "left" | "right" | "backspace"): Promise<BasicResult> {
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

export function buildSessionStreamUrl(
  session: string,
  options?: { profile?: "fast" | "balanced" | "battery"; since_seq?: number },
): string {
  const base =
    typeof window !== "undefined" && window.location
      ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
      : "ws://127.0.0.1";
  const url = new URL(`/codex/session/${encodeURIComponent(session)}/ws`, base);
  if (options?.profile) {
    url.searchParams.set("profile", options.profile);
  }
  if (typeof options?.since_seq === "number" && Number.isFinite(options.since_seq) && options.since_seq > 0) {
    url.searchParams.set("since_seq", String(options.since_seq));
  }
  return url.toString();
}

export function getWindowsRuntimeStatus(): Promise<CodexRuntimeStatusResult> {
  return requestJson<CodexRuntimeStatusResult>("/windows/runtime/status");
}

export function startWindowsRuntime(): Promise<CodexRuntimeStatusResult> {
  return requestJson<CodexRuntimeStatusResult>("/windows/runtime/start", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function stopWindowsRuntime(): Promise<CodexRuntimeStatusResult> {
  return requestJson<CodexRuntimeStatusResult>("/windows/runtime/stop", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function getWindowsSessions(): Promise<SessionsResult> {
  return requestJson<SessionsResult>("/windows/sessions");
}

export function createWindowsSessionWithOptions(options: {
  name?: string;
  cwd?: string;
  model?: string;
  reasoning_effort?: string;
  profile?: "codex" | "powershell" | "cmd";
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
  if (options.profile && options.profile.trim()) {
    payload.profile = options.profile.trim();
  }
  return requestJson<SessionCreateResult>("/windows/session", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function closeWindowsSession(session: string): Promise<SessionCloseResult> {
  return requestJson<SessionCloseResult>(`/windows/session/${encodeURIComponent(session)}`, {
    method: "DELETE",
  });
}

export function sendToWindowsSession(session: string, prompt: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/windows/session/${encodeURIComponent(session)}/send`, {
    method: "POST",
    headers: {
      "Content-Type": "text/plain",
    },
    body: prompt,
  });
}

export function interruptWindowsSession(session: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/windows/session/${encodeURIComponent(session)}/interrupt`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function enterWindowsSession(session: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/windows/session/${encodeURIComponent(session)}/enter`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function sendWindowsSessionKey(session: string, key: "up" | "down" | "left" | "right" | "backspace"): Promise<BasicResult> {
  return requestJson<BasicResult>(`/windows/session/${encodeURIComponent(session)}/key`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ key }),
  });
}

export function ctrlcWindowsSession(session: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/windows/session/${encodeURIComponent(session)}/ctrlc`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function getWindowsSessionScreen(session: string): Promise<SessionScreenResult> {
  return requestJson<SessionScreenResult>(`/windows/session/${encodeURIComponent(session)}/screen`);
}

export function buildWindowsSessionStreamUrl(
  session: string,
  options?: { profile?: "fast" | "balanced" | "battery"; since_seq?: number },
): string {
  const base =
    typeof window !== "undefined" && window.location
      ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
      : "ws://127.0.0.1";
  const url = new URL(`/windows/session/${encodeURIComponent(session)}/ws`, base);
  if (options?.profile) {
    url.searchParams.set("profile", options.profile);
  }
  if (typeof options?.since_seq === "number" && Number.isFinite(options.since_seq) && options.since_seq > 0) {
    url.searchParams.set("since_seq", String(options.since_seq));
  }
  return url.toString();
}

export function getDesktopCodexRuntimeStatus(): Promise<CodexRuntimeStatusResult> {
  return requestJson<CodexRuntimeStatusResult>("/desktop-codex/runtime/status");
}

export function getDesktopCodexSessions(): Promise<SessionsResult> {
  return requestJson<SessionsResult>("/desktop-codex/sessions");
}

export function getDesktopCodexSessionScreen(session: string): Promise<SessionScreenResult> {
  return requestJson<SessionScreenResult>(`/desktop-codex/session/${encodeURIComponent(session)}/screen`);
}

export function sendToDesktopCodexSession(session: string, prompt: string): Promise<BasicResult> {
  if (window.CodrexAndroidBridge?.postDesktopCodexPrompt) {
    try {
      const raw = window.CodrexAndroidBridge.postDesktopCodexPrompt(session, prompt);
      const payload = raw ? JSON.parse(raw) as BasicResult : ({ ok: false, detail: "Empty native response." } as BasicResult);
      return Promise.resolve(payload);
    } catch (error) {
      return Promise.reject(new Error(`Android shell send failed: ${(error as Error).message}`));
    }
  }
  return requestJson<BasicResult>(`/desktop-codex/session/${encodeURIComponent(session)}/send`, {
    method: "POST",
    timeoutMs: 60000,
    headers: {
      "Content-Type": "text/plain",
    },
    body: prompt,
  });
}

export function interruptDesktopCodexSession(session: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/desktop-codex/session/${encodeURIComponent(session)}/interrupt`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function openDesktopCodexSession(session: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/desktop-codex/session/${encodeURIComponent(session)}/open`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function refreshDesktopCodexSession(session: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/desktop-codex/session/${encodeURIComponent(session)}/refresh`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function buildDesktopCodexSessionStreamUrl(
  session: string,
  options?: { profile?: "fast" | "balanced" | "battery"; since_seq?: number },
): string {
  const base =
    typeof window !== "undefined" && window.location
      ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
      : "ws://127.0.0.1";
  const url = new URL(`/desktop-codex/session/${encodeURIComponent(session)}/ws`, base);
  if (options?.profile) {
    url.searchParams.set("profile", options.profile);
  }
  if (typeof options?.since_seq === "number" && Number.isFinite(options.since_seq) && options.since_seq > 0) {
    url.searchParams.set("since_seq", String(options.since_seq));
  }
  return url.toString();
}

export function getDesktopTargets(): Promise<DesktopTargetsResult> {
  return requestJson<DesktopTargetsResult>("/desktop/targets");
}

export function selectDesktopTarget(targetId: string): Promise<DesktopTargetsResult> {
  return requestJson<DesktopTargetsResult>("/desktop/targets/select", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ target_id: targetId }),
  });
}

export function setVirtualDesktopTarget(enabled: boolean): Promise<DesktopTargetsResult> {
  return requestJson<DesktopTargetsResult>("/desktop/targets/virtual", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ enabled }),
  });
}

export function getDesktopPrivacyLockStatus(): Promise<PrivacyLockStatusResult> {
  return requestJson<PrivacyLockStatusResult>("/desktop/privacy-lock/status");
}

export function updateDesktopPrivacyLockConfig(
  payload: {
    mode?: string;
    current_pin?: string;
    new_pin?: string;
    clear?: boolean;
  },
): Promise<PrivacyLockStatusResult> {
  return requestJson<PrivacyLockStatusResult>("/desktop/privacy-lock/config", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
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

export function listSessionFiles(session: string): Promise<SessionFilesResult> {
  return requestJson<SessionFilesResult>(`/codex/session/${encodeURIComponent(session)}/files`);
}

export function getSessionNotes(session: string): Promise<SessionNotesResult> {
  return requestJson<SessionNotesResult>(`/codex/session/${encodeURIComponent(session)}/notes`);
}

export function saveSessionNotes(
  session: string,
  payload: { content: string; last_response_snapshot?: string },
): Promise<SessionNotesResult> {
  return requestJson<SessionNotesResult>(`/codex/session/${encodeURIComponent(session)}/notes`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function appendLatestSessionNotes(session: string): Promise<SessionNotesResult> {
  return requestJson<SessionNotesResult>(`/codex/session/${encodeURIComponent(session)}/notes/append-latest`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function registerSessionFile(
  session: string,
  payload: { path: string; title?: string; allow_directory?: boolean; expires_hours?: number },
): Promise<SessionFilesResult> {
  return requestJson<SessionFilesResult>(`/codex/session/${encodeURIComponent(session)}/files/register`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function uploadSessionFile(session: string, file: File, title = ""): Promise<SessionFilesResult> {
  const formData = new FormData();
  formData.append("file", file);
  if (title.trim()) {
    formData.append("title", title.trim());
  }
  return requestJson<SessionFilesResult>(`/codex/session/${encodeURIComponent(session)}/files/upload`, {
    method: "POST",
    body: formData,
  });
}

export function deleteSessionFile(session: string, fileId: string): Promise<SessionFilesResult> {
  return requestJson<SessionFilesResult>(`/codex/session/${encodeURIComponent(session)}/files/${encodeURIComponent(fileId)}`, {
    method: "DELETE",
  });
}

export function sendSessionFileToTelegram(session: string, fileId: string, caption = ""): Promise<SessionFilesResult> {
  return requestJson<SessionFilesResult>(`/codex/session/${encodeURIComponent(session)}/files/${encodeURIComponent(fileId)}/telegram`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(caption.trim() ? { caption: caption.trim() } : {}),
  });
}

export function listBrowseEntries(root = "workspace", path = ""): Promise<BrowserListResult> {
  const query = new URLSearchParams();
  query.set("root", root);
  if (path.trim()) {
    query.set("path", path.trim());
  }
  return requestJson<BrowserListResult>(`/fs/list?${query.toString()}`);
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

export function getLoopStatus(): Promise<LoopStatusResult> {
  return requestJson<LoopStatusResult>("/loop/status");
}

export function updateLoopSettings(payload: {
  default_prompt?: string;
  global_preset?: "" | LoopPreset;
  completion_checks?: string[];
}): Promise<LoopStatusResult> {
  return requestJson<LoopStatusResult>("/loop/settings", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function updateSessionLoopMode(session: string, override_mode: LoopOverrideMode): Promise<BasicResult> {
  return requestJson<BasicResult>(`/loop/session/${encodeURIComponent(session)}/mode`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ override_mode }),
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

export function sendToPaneKey(paneId: string, key: "up" | "down" | "left" | "right" | "enter"): Promise<BasicResult> {
  return requestJson<BasicResult>(`/tmux/pane/${encodeURIComponent(paneId)}/key`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ key }),
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

export function getDesktopStreamCapabilities(): Promise<DesktopStreamCapabilitiesResult> {
  return requestJson<DesktopStreamCapabilitiesResult>("/desktop/stream/capabilities");
}

export function createDesktopWebrtcOffer(payload: {
  offer: { type: string; sdp: string };
  fps?: number;
  scale?: number;
  bw?: boolean;
}): Promise<DesktopWebrtcOfferResult> {
  return requestJson<DesktopWebrtcOfferResult>("/desktop/webrtc/offer", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function sendDesktopWebrtcIce(payload: {
  session_id: string;
  candidate: { candidate?: string; sdpMid?: string | null; sdpMLineIndex?: number | null };
}): Promise<BasicResult> {
  return requestJson<BasicResult>("/desktop/webrtc/ice", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function closeDesktopWebrtcSession(sessionId: string): Promise<BasicResult> {
  return requestJson<BasicResult>(`/desktop/webrtc/session/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

export function getPowerStatus(): Promise<PowerStatusResult> {
  return requestJson<PowerStatusResult>("/power/status");
}

export function sendPowerAction(
  action: "lock" | "sleep" | "hibernate" | "restart" | "shutdown",
  options?: { confirm_token?: string },
): Promise<PowerActionResult> {
  const payload: Record<string, string> = { action };
  if (options?.confirm_token && options.confirm_token.trim()) {
    payload.confirm_token = options.confirm_token.trim();
  }
  return requestJson<PowerActionResult>("/power/action", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function setDesktopMode(enabled: boolean): Promise<DesktopModeResult> {
  return requestJson<DesktopModeResult>("/desktop/mode", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ enabled }),
  });
}

export function setDesktopPerfMode(enabled: boolean): Promise<DesktopModeResult> {
  return requestJson<DesktopModeResult>("/desktop/perf", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ enabled }),
  });
}

export function desktopClick(params: {
  button?: "left" | "right";
  double?: boolean;
  x?: number;
  y?: number;
  action?: "click" | "down" | "up";
}): Promise<DesktopInputResult> {
  return requestJson<DesktopInputResult>("/desktop/input/click", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      button: params.button || "left",
      double: !!params.double,
      x: params.x,
      y: params.y,
      action: params.action || "click",
    }),
  });
}

export function desktopMove(x: number, y: number): Promise<DesktopInputResult> {
  return requestJson<DesktopInputResult>("/desktop/input/move", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ x, y }),
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

export function desktopGetSelectedPath(): Promise<DesktopInputResult> {
  return requestJson<DesktopInputResult>("/desktop/selection/path", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function buildDesktopStreamUrl(params?: {
  fps?: number;
  level?: number;
  scale?: number;
  bw?: boolean;
  format?: "png" | "jpeg";
  quality?: number;
}): string {
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
  if (params?.format === "jpeg" || params?.format === "png") {
    query.set("format", params.format);
  }
  if (typeof params?.quality === "number" && Number.isFinite(params.quality)) {
    query.set("quality", String(params.quality));
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

export function uploadHostFile(
  file: File,
  destination = "default",
  options?: { open_after?: boolean; reveal_after?: boolean },
): Promise<HostTransferResult> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("destination", destination.trim() || "default");
  if (typeof options?.open_after === "boolean") {
    formData.append("open_after", options.open_after ? "1" : "0");
  }
  if (typeof options?.reveal_after === "boolean") {
    formData.append("reveal_after", options.reveal_after ? "1" : "0");
  }
  return requestJson<HostTransferResult>("/host/files/upload", {
    method: "POST",
    body: formData,
  });
}

export function pasteDesktopImage(file: File): Promise<DesktopPasteImageResult> {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<DesktopPasteImageResult>("/desktop/paste/image", {
    method: "POST",
    body: formData,
  });
}

export function shareHostSelection(options?: {
  title?: string;
  expires_hours?: number;
  allow_directory?: boolean;
}): Promise<HostTransferResult> {
  const payload: Record<string, string | number | boolean> = {};
  if (options?.title?.trim()) {
    payload.title = options.title.trim();
  }
  if (typeof options?.expires_hours === "number" && Number.isFinite(options.expires_hours)) {
    payload.expires_hours = options.expires_hours;
  }
  if (typeof options?.allow_directory === "boolean") {
    payload.allow_directory = options.allow_directory;
  }
  return requestJson<HostTransferResult>("/host/files/share-selection", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function pickAndShareHostFile(options?: {
  title?: string;
  expires_hours?: number;
}): Promise<HostTransferResult> {
  const payload: Record<string, string | number> = {};
  if (options?.title?.trim()) {
    payload.title = options.title.trim();
  }
  if (typeof options?.expires_hours === "number" && Number.isFinite(options.expires_hours)) {
    payload.expires_hours = options.expires_hours;
  }
  return requestJson<HostTransferResult>("/host/files/pick-share", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

export function openHostPath(path: string): Promise<OpenPathResult> {
  return requestJson<OpenPathResult>("/host/open-path", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ path }),
  });
}

export function revealHostPath(path: string): Promise<OpenPathResult> {
  return requestJson<OpenPathResult>("/host/reveal-path", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ path }),
  });
}
