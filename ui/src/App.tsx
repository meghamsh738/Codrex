import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  addThreadRecordMessage,
  buildDesktopShotUrl,
  buildDesktopStreamUrl,
  buildPairConsumeUrl,
  buildPairQrPngUrl,
  buildSuggestedControllerUrl,
  buildWslDownloadUrl,
  bootstrapLocalAuth,
  applySessionProfile,
  closeSession,
  closeTmuxSession,
  createThreadRecord,
  createSessionWithOptions,
  createSharedFile,
  createTmuxSession,
  createPairCode,
  deleteThreadRecord,
  desktopClick,
  desktopScroll,
  desktopSendKey,
  desktopSendText,
  ctrlcSession,
  exchangePairCode,
  enterSession,
  getDesktopInfo,
  getAuthStatus,
  getCodexOptions,
  getCodexRun,
  getCodexRuns,
  getNetInfo,
  listSharedFiles,
  getTelegramStatus,
  getThreadStore,
  getTmuxHealth,
  getTmuxPaneScreen,
  getTmuxPanes,
  getSessionScreen,
  getSessions,
  interruptSession,
  interruptPane,
  login,
  logout,
  reportIpcEvent,
  sendSharedFileToTelegram,
  sendTelegramText,
  deleteSharedFile,
  sendSessionImage,
  sendToPane,
  sendToSession,
  setDesktopMode,
  setIpcObserver,
  startCodexExec,
  updateThreadRecord,
  uploadWslFile,
} from "./api";
import type {
  AuthStatus,
  CodexRunDetail,
  CodexRunSummary,
  DesktopInfoResult,
  NetInfo,
  SharedFileInfo,
  SessionInfo,
  ThreadInfo,
  ThreadMessageInfo,
  TmuxPaneInfo,
} from "./types";
import type { IpcEvent } from "./api";

type RouteHint = "lan" | "tailscale" | "current";
type MainTab = "sessions" | "threads" | "remote" | "pair" | "settings" | "debug";
type ThemeMode = "system" | "light" | "dark";
type ReasoningEffort = "minimal" | "low" | "medium" | "high" | "xhigh";
type SessionViewMode = "grouped" | "flat";
type StreamProfile = "fast" | "balanced" | "battery";
type TmuxShellProfile = "ubuntu" | "powershell" | "cmd";
type OutputFeedState = "off" | "polling" | "connecting" | "live" | "error";
type TabTransitionClass = "tab-still" | "tab-slide-left" | "tab-slide-right";
type DesktopStreamProfile = "responsive" | "balanced" | "saver" | "ultra" | "extreme";
type SessionImageDeliveryMode = "insert_path" | "desktop_clipboard" | "session_path";

type AppEventLevel = "info" | "error";
type InstallState = "hidden" | "ready" | "prompting" | "installed";

interface AppEventItem {
  id: string;
  at: number;
  level: AppEventLevel;
  message: string;
}

interface SessionGroup {
  project: string;
  items: SessionInfo[];
}

interface ChatThread {
  id: string;
  title: string;
  session: string;
  createdAt: number;
  updatedAt: number;
}

interface ThreadMessage {
  id: string;
  threadId: string;
  role: "user" | "assistant" | "system";
  text: string;
  at: number;
}

interface DeferredInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform?: string }>;
}

const TAB_ORDER: MainTab[] = ["sessions", "threads", "remote", "pair", "settings", "debug"];

const CONTROLLER_BASE_STORAGE = "codrex.ui.controller_base.v1";
const MODEL_STORAGE = "codrex.ui.model.v1";
const REASONING_EFFORT_STORAGE = "codrex.ui.reasoning_effort.v1";
const THEME_MODE_STORAGE = "codrex.ui.theme_mode.v1";
const SESSION_VIEW_STORAGE = "codrex.ui.session_view_mode.v1";
const STREAM_PROFILE_STORAGE = "codrex.ui.stream_profile.v1";
const STREAM_ENABLED_STORAGE = "codrex.ui.stream_enabled.v1";
const SWIPE_HINT_SEEN_STORAGE = "codrex.ui.swipe_hint_seen.v1";
const COMPACT_TRANSCRIPT_STORAGE = "codrex.ui.compact_transcript.v1";
const TOUCH_COMFORT_STORAGE = "codrex.ui.touch_comfort.v1";
const IMAGE_DELIVERY_MODE_STORAGE = "codrex.ui.image_delivery_mode.v1";
const STREAM_PROFILE_INTERVAL_MS: Record<StreamProfile, number> = {
  fast: 400,
  balanced: 800,
  battery: 1400,
};
const THREADS_STORAGE = "codrex.ui.threads.v2";
const THREAD_MESSAGES_STORAGE = "codrex.ui.thread_messages.v2";
const THREAD_MESSAGES_LEGACY_STORAGE = "codrex.ui.thread_messages.v1";
const DESKTOP_PROFILE_STREAM: Record<DesktopStreamProfile, { fps: number; level: number; scale: number; bw: boolean }> = {
  responsive: { fps: 8, level: 1, scale: 1, bw: false },
  balanced: { fps: 6, level: 2, scale: 2, bw: false },
  saver: { fps: 4, level: 3, scale: 3, bw: false },
  ultra: { fps: 3, level: 4, scale: 4, bw: true },
  extreme: { fps: 1.5, level: 6, scale: 6, bw: true },
};
const FALLBACK_MODELS = ["gpt-5-codex", "gpt-5", "gpt-5-mini", "gpt-4.1", "o4-mini"];
const FALLBACK_REASONING_EFFORTS: ReasoningEffort[] = ["minimal", "low", "medium", "high", "xhigh"];
const TMUX_SHELL_BOOT_COMMAND: Record<TmuxShellProfile, string> = {
  ubuntu: "",
  powershell: "powershell.exe -NoLogo",
  cmd: "cmd.exe",
};

function safeStorageGet(key: string): string {
  try {
    const store = window.localStorage as Storage | undefined;
    if (store && typeof store.getItem === "function") {
      return store.getItem(key) || "";
    }
  } catch {}
  return "";
}

function safeStorageSet(key: string, value: string): void {
  try {
    const store = window.localStorage as Storage | undefined;
    if (store && typeof store.setItem === "function") {
      store.setItem(key, value);
    }
  } catch {}
}

function safeStorageRemove(key: string): void {
  try {
    const store = window.localStorage as Storage | undefined;
    if (store && typeof store.removeItem === "function") {
      store.removeItem(key);
    }
  } catch {}
}

function prettyRouteLabel(route: RouteHint): string {
  if (route === "lan") {
    return "LAN";
  }
  if (route === "tailscale") {
    return "Tailscale";
  }
  return "Current Host";
}

function classifyControllerRoute(baseUrl: string, netInfo: NetInfo | null): "tailscale" | "lan" | "localhost" | "unknown" {
  const value = baseUrl.trim();
  if (!value) {
    return "unknown";
  }
  try {
    const candidate = value.startsWith("http://") || value.startsWith("https://") ? value : `http://${value}`;
    const host = new URL(candidate).hostname.toLowerCase();
    if (host === "localhost" || host === "127.0.0.1" || host === "::1") {
      return "localhost";
    }
    if (netInfo?.tailscale_ip && host === netInfo.tailscale_ip.toLowerCase()) {
      return "tailscale";
    }
    if (netInfo?.lan_ip && host === netInfo.lan_ip.toLowerCase()) {
      return "lan";
    }
  } catch {
    return "unknown";
  }
  return "unknown";
}

function getAdjacentTab(current: MainTab, direction: 1 | -1): MainTab {
  const index = TAB_ORDER.indexOf(current);
  if (index < 0) {
    return TAB_ORDER[0];
  }
  const nextIndex = Math.max(0, Math.min(TAB_ORDER.length - 1, index + direction));
  return TAB_ORDER[nextIndex] || TAB_ORDER[0];
}

function parseInitialTab(): MainTab {
  if (typeof window === "undefined") {
    return "sessions";
  }
  try {
    const url = new URL(window.location.href);
    const raw = (url.searchParams.get("tab") || "").trim().toLowerCase();
    if (raw === "sessions" || raw === "threads" || raw === "remote" || raw === "pair" || raw === "settings" || raw === "debug") {
      return raw;
    }
  } catch {}
  return "sessions";
}

function parsePort(): number {
  const fromEnv = Number.parseInt(import.meta.env.VITE_BACKEND_PORT || "", 10);
  if (Number.isInteger(fromEnv) && fromEnv > 0) {
    return fromEnv;
  }
  return 8787;
}

function formatClock(tsMs: number): string {
  try {
    return new Date(tsMs).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "";
  }
}

function formatFileSize(bytes: number): string {
  const value = Number.isFinite(bytes) ? Math.max(0, bytes) : 0;
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  if (value < 1024 * 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function parseThemeMode(raw: string): ThemeMode {
  if (raw === "light" || raw === "dark") {
    return raw;
  }
  return "dark";
}

function parseReasoningEffort(raw: string): ReasoningEffort {
  if (raw === "minimal" || raw === "low" || raw === "medium" || raw === "high" || raw === "xhigh") {
    return raw;
  }
  return "xhigh";
}

function allowedReasoningForModel(model: string, allOptions: ReasoningEffort[]): ReasoningEffort[] {
  const normalized = (model || "").trim().toLowerCase();
  if (normalized.includes("codex")) {
    const preferred: ReasoningEffort[] = ["low", "medium", "high"];
    const filtered = preferred.filter((item) => allOptions.includes(item));
    return filtered.length > 0 ? filtered : preferred;
  }
  return allOptions.length > 0 ? allOptions : FALLBACK_REASONING_EFFORTS;
}

function clampReasoningForModel(
  model: string,
  requested: ReasoningEffort,
  allOptions: ReasoningEffort[],
): ReasoningEffort {
  const allowed = allowedReasoningForModel(model, allOptions);
  if (allowed.includes(requested)) {
    return requested;
  }
  if (requested === "xhigh" && allowed.includes("high")) {
    return "high";
  }
  if (requested === "minimal" && allowed.includes("low")) {
    return "low";
  }
  return allowed[allowed.length - 1] || "high";
}

function parseSessionViewMode(raw: string): SessionViewMode {
  if (raw === "flat") {
    return "flat";
  }
  return "grouped";
}

function parseStreamProfile(raw: string): StreamProfile {
  if (raw === "fast" || raw === "battery") {
    return raw;
  }
  return "balanced";
}

function parseStreamEnabled(raw: string): boolean {
  const lowered = raw.trim().toLowerCase();
  if (lowered === "0" || lowered === "false" || lowered === "off") {
    return false;
  }
  if (lowered === "1" || lowered === "true" || lowered === "on") {
    return true;
  }
  return true;
}

function parseStoredToggle(raw: string): boolean | null {
  const lowered = raw.trim().toLowerCase();
  if (!lowered) {
    return null;
  }
  if (lowered === "0" || lowered === "false" || lowered === "off") {
    return false;
  }
  if (lowered === "1" || lowered === "true" || lowered === "on") {
    return true;
  }
  return null;
}

function parseSessionImageDeliveryMode(raw: string): SessionImageDeliveryMode {
  if (raw === "desktop_clipboard" || raw === "session_path") {
    return raw;
  }
  return "insert_path";
}

function preferCompactTranscriptDefault(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(max-width: 780px)").matches;
}

function preferTouchComfortDefault(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return true;
  }
  return window.matchMedia("(max-width: 1024px)").matches;
}

function makeThreadId(): string {
  return `thr_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function makeThreadMessageId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeThreadTitle(raw: string, session: string): string {
  const clean = raw.trim().replace(/\s+/g, " ");
  if (clean) {
    return clean.slice(0, 80);
  }
  return session ? `${session} thread` : "Untitled thread";
}

function inferProjectFromCwd(cwd: string): string {
  const value = (cwd || "").trim();
  if (!value) {
    return "Unknown";
  }
  const normalized = value.replace(/\\/g, "/").replace(/\/+$/g, "");
  if (!normalized) {
    return "Unknown";
  }
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length === 0) {
    return "Unknown";
  }
  return parts[parts.length - 1] || "Unknown";
}

function isCodexTmuxPane(pane: TmuxPaneInfo): boolean {
  const session = (pane.session || "").toLowerCase();
  const command = (pane.current_command || "").toLowerCase();
  return session.startsWith("codex_") || command === "codex";
}

function parseThreads(raw: string): ChatThread[] {
  if (!raw.trim()) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as ChatThread[];
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed
      .filter((thread) => thread && typeof thread.id === "string" && typeof thread.session === "string")
      .map((thread) => ({
        id: thread.id,
        title: normalizeThreadTitle(thread.title || "", thread.session || ""),
        session: thread.session,
        createdAt: Number.isFinite(thread.createdAt) ? thread.createdAt : Date.now(),
        updatedAt: Number.isFinite(thread.updatedAt) ? thread.updatedAt : Date.now(),
      }))
      .slice(0, 160);
  } catch {
    return [];
  }
}

function parseThreadMessageMap(raw: string): Record<string, ThreadMessage[]> {
  if (!raw.trim()) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw) as Record<string, ThreadMessage[]>;
    if (!parsed || typeof parsed !== "object") {
      return {};
    }
    const out: Record<string, ThreadMessage[]> = {};
    Object.entries(parsed).forEach(([threadId, items]) => {
      if (!threadId || !Array.isArray(items)) {
        return;
      }
      out[threadId] = items
        .filter((item) => item && typeof item.text === "string" && typeof item.role === "string")
        .map((item) => ({
          id: typeof item.id === "string" ? item.id : makeThreadMessageId(),
          threadId,
          role: item.role,
          text: item.text,
          at: Number.isFinite(item.at) ? item.at : Date.now(),
        }))
        .slice(-120);
    });
    return out;
  } catch {
    return {};
  }
}

function mapApiThread(thread: ThreadInfo): ChatThread {
  return {
    id: thread.id,
    title: normalizeThreadTitle(thread.title || "", thread.session || ""),
    session: thread.session || "",
    createdAt: Number.isFinite(thread.created_at) ? thread.created_at : Date.now(),
    updatedAt: Number.isFinite(thread.updated_at) ? thread.updated_at : Date.now(),
  };
}

function mapApiThreadMessageMap(raw: Record<string, ThreadMessageInfo[] | undefined>): Record<string, ThreadMessage[]> {
  const out: Record<string, ThreadMessage[]> = {};
  Object.entries(raw || {}).forEach(([threadId, items]) => {
    if (!threadId || !Array.isArray(items)) {
      return;
    }
    out[threadId] = items
      .filter((item) => item && typeof item.text === "string" && typeof item.role === "string")
      .map((item) => ({
        id: item.id,
        threadId,
        role: item.role,
        text: item.text,
        at: Number.isFinite(item.at) ? item.at : Date.now(),
      }))
      .slice(-120);
  });
  return out;
}

function parseLegacyThreadMessages(raw: string): Record<string, ThreadMessage[]> {
  if (!raw.trim()) {
    return {};
  }
  try {
    const parsed = JSON.parse(raw) as Record<string, Array<{ id?: string; role?: string; text?: string; at?: number }>>;
    if (!parsed || typeof parsed !== "object") {
      return {};
    }
    const out: Record<string, ThreadMessage[]> = {};
    Object.entries(parsed).forEach(([session, items]) => {
      if (!session || !Array.isArray(items)) {
        return;
      }
      const legacyThreadId = `legacy_${session}`;
      out[legacyThreadId] = items
        .filter((item) => item && typeof item.text === "string" && typeof item.role === "string")
        .map((item) => ({
          id: typeof item.id === "string" ? item.id : makeThreadMessageId(),
          threadId: legacyThreadId,
          role: item.role as ThreadMessage["role"],
          text: item.text || "",
          at: Number.isFinite(item.at) ? (item.at as number) : Date.now(),
        }))
        .slice(-120);
    });
    return out;
  } catch {
    return {};
  }
}

function migrateLegacyThreads(raw: string): { threads: ChatThread[]; messages: Record<string, ThreadMessage[]> } {
  const messagesByThread = parseLegacyThreadMessages(raw);
  const threads: ChatThread[] = Object.keys(messagesByThread).map((threadId) => {
    const session = threadId.replace(/^legacy_/, "") || "unknown";
    const items = messagesByThread[threadId] || [];
    const createdAt = items[0]?.at || Date.now();
    const updatedAt = items[items.length - 1]?.at || createdAt;
    const userSeed = items.find((item) => item.role === "user")?.text || "";
    return {
      id: threadId,
      title: normalizeThreadTitle(userSeed, session),
      session,
      createdAt,
      updatedAt,
    };
  });
  threads.sort((a, b) => b.updatedAt - a.updatedAt);
  return { threads, messages: messagesByThread };
}

function compactAssistantSnapshot(text: string): string {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter(Boolean);
  if (lines.length === 0) {
    return "";
  }
  const tail = lines.slice(-24).join("\n").trim();
  return tail.length > 1600 ? tail.slice(tail.length - 1600) : tail;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<MainTab>(() => parseInitialTab());
  const [tabTransitionClass, setTabTransitionClass] = useState<TabTransitionClass>("tab-still");
  const previousTabRef = useRef<MainTab>("sessions");

  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [tokenInput, setTokenInput] = useState("");
  const [authBusy, setAuthBusy] = useState(false);

  const [netInfo, setNetInfo] = useState<NetInfo | null>(null);
  const [routeHint, setRouteHint] = useState<RouteHint>("lan");
  const [controllerBase, setControllerBase] = useState(() => {
    const saved = safeStorageGet(CONTROLLER_BASE_STORAGE);
    return saved || "";
  });

  const [pairCode, setPairCode] = useState("");
  const [pairExpiry, setPairExpiry] = useState<number | null>(null);
  const [pairLink, setPairLink] = useState("");
  const [pairQrUrl, setPairQrUrl] = useState("");
  const [pairBusy, setPairBusy] = useState(false);

  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [selectedSession, setSelectedSession] = useState("");
  const [newSessionName, setNewSessionName] = useState("");
  const [newSessionCwd, setNewSessionCwd] = useState("");
  const [sessionQuery, setSessionQuery] = useState("");
  const [sessionProjectFilter, setSessionProjectFilter] = useState("all");
  const [sessionViewMode, setSessionViewMode] = useState<SessionViewMode>(() =>
    parseSessionViewMode(safeStorageGet(SESSION_VIEW_STORAGE)),
  );
  const [promptText, setPromptText] = useState("");
  const [modelOptions, setModelOptions] = useState<string[]>(FALLBACK_MODELS);
  const [reasoningEffortOptions, setReasoningEffortOptions] = useState<ReasoningEffort[]>(FALLBACK_REASONING_EFFORTS);
  const [selectedModel, setSelectedModel] = useState(() => safeStorageGet(MODEL_STORAGE) || FALLBACK_MODELS[0]);
  const [selectedReasoningEffort, setSelectedReasoningEffort] = useState<ReasoningEffort>(() =>
    parseReasoningEffort(safeStorageGet(REASONING_EFFORT_STORAGE)),
  );
  const [streamEnabled, setStreamEnabled] = useState<boolean>(() => parseStreamEnabled(safeStorageGet(STREAM_ENABLED_STORAGE)));
  const [streamProfile, setStreamProfile] = useState<StreamProfile>(() =>
    parseStreamProfile(safeStorageGet(STREAM_PROFILE_STORAGE)),
  );
  const [outputFeedState, setOutputFeedState] = useState<OutputFeedState>(() => (parseStreamEnabled(safeStorageGet(STREAM_ENABLED_STORAGE)) ? "polling" : "off"));
  const [screenText, setScreenText] = useState("");
  const [sessionBusy, setSessionBusy] = useState(false);
  const [sessionImageFile, setSessionImageFile] = useState<File | null>(null);
  const [sessionImagePrompt, setSessionImagePrompt] = useState("");
  const [sessionImageDeliveryMode, setSessionImageDeliveryMode] = useState<SessionImageDeliveryMode>(() =>
    parseSessionImageDeliveryMode(safeStorageGet(IMAGE_DELIVERY_MODE_STORAGE)),
  );
  const [sharedFiles, setSharedFiles] = useState<SharedFileInfo[]>([]);
  const [sharesLoading, setSharesLoading] = useState(true);
  const [telegramConfigured, setTelegramConfigured] = useState(false);
  const [telegramStatusLoading, setTelegramStatusLoading] = useState(true);
  const [shareBusy, setShareBusy] = useState(false);
  const [telegramTextBusy, setTelegramTextBusy] = useState(false);
  const [sharePathInput, setSharePathInput] = useState("");
  const [shareTitleInput, setShareTitleInput] = useState("");
  const [shareExpiresHours, setShareExpiresHours] = useState("24");
  const [consoleFocusMode, setConsoleFocusMode] = useState(false);

  const [threads, setThreads] = useState<ChatThread[]>(() => {
    const stored = parseThreads(safeStorageGet(THREADS_STORAGE));
    if (stored.length > 0) {
      return stored;
    }
    const migrated = migrateLegacyThreads(safeStorageGet(THREAD_MESSAGES_LEGACY_STORAGE));
    return migrated.threads;
  });
  const [activeThreadId, setActiveThreadId] = useState<string>(() => {
    const stored = parseThreads(safeStorageGet(THREADS_STORAGE));
    if (stored[0]?.id) {
      return stored[0].id;
    }
    const migrated = migrateLegacyThreads(safeStorageGet(THREAD_MESSAGES_LEGACY_STORAGE));
    return migrated.threads[0]?.id || "";
  });
  const [threadMessages, setThreadMessages] = useState<Record<string, ThreadMessage[]>>(() => {
    const stored = parseThreadMessageMap(safeStorageGet(THREAD_MESSAGES_STORAGE));
    if (Object.keys(stored).length > 0) {
      return stored;
    }
    const migrated = migrateLegacyThreads(safeStorageGet(THREAD_MESSAGES_LEGACY_STORAGE));
    return migrated.messages;
  });
  const [threadPrompt, setThreadPrompt] = useState("");
  const [threadTitleInput, setThreadTitleInput] = useState("");
  const [threadSessionInput, setThreadSessionInput] = useState("");
  const [threadSearch, setThreadSearch] = useState("");
  const [threadBusy, setThreadBusy] = useState(false);

  const [tmuxHealthState, setTmuxHealthState] = useState("loading");
  const [tmuxSessions, setTmuxSessions] = useState<string[]>([]);
  const [tmuxPanes, setTmuxPanes] = useState<TmuxPaneInfo[]>([]);
  const [tmuxSessionName, setTmuxSessionName] = useState("");
  const [tmuxShellProfile, setTmuxShellProfile] = useState<TmuxShellProfile>("ubuntu");
  const [selectedTmuxPane, setSelectedTmuxPane] = useState("");
  const [tmuxPrompt, setTmuxPrompt] = useState("");
  const [tmuxScreenText, setTmuxScreenText] = useState("");
  const [tmuxBusy, setTmuxBusy] = useState(false);
  const showLegacyThreadTools = false;

  const [desktopInfo, setDesktopInfo] = useState<DesktopInfoResult | null>(null);
  const [desktopEnabled, setDesktopEnabled] = useState(false);
  const [desktopProfile, setDesktopProfile] = useState<DesktopStreamProfile>("ultra");
  const [desktopKeyInput, setDesktopKeyInput] = useState("enter");
  const [desktopTextInput, setDesktopTextInput] = useState("");
  const [desktopStatus, setDesktopStatus] = useState("");
  const [desktopShotUrl, setDesktopShotUrl] = useState(() => buildDesktopShotUrl(DESKTOP_PROFILE_STREAM.ultra));
  const [desktopFocusPoint, setDesktopFocusPoint] = useState<{ x: number; y: number } | null>(null);

  const [execPrompt, setExecPrompt] = useState("");
  const [execBusy, setExecBusy] = useState(false);
  const [wslDownloadPath, setWslDownloadPath] = useState("");
  const [wslUploadDest, setWslUploadDest] = useState("");
  const [wslUploadFile, setWslUploadFile] = useState<File | null>(null);
  const [fileStatus, setFileStatus] = useState("");
  const [latestCaptureUrl, setLatestCaptureUrl] = useState("");

  const [ipcHistory, setIpcHistory] = useState<IpcEvent[]>([]);
  const [ipcFilter, setIpcFilter] = useState<"all" | "http" | "sse" | "error">("all");
  const [ipcSearch, setIpcSearch] = useState("");
  const [selectedIpcId, setSelectedIpcId] = useState("");
  const [showSwipeHint, setShowSwipeHint] = useState(() => {
    const seen = safeStorageGet(SWIPE_HINT_SEEN_STORAGE).trim().toLowerCase();
    return !(seen === "1" || seen === "true" || seen === "yes");
  });
  const [compactTranscript, setCompactTranscript] = useState<boolean>(() => {
    const stored = parseStoredToggle(safeStorageGet(COMPACT_TRANSCRIPT_STORAGE));
    return stored == null ? preferCompactTranscriptDefault() : stored;
  });
  const [touchComfortMode, setTouchComfortMode] = useState<boolean>(() => {
    const stored = parseStoredToggle(safeStorageGet(TOUCH_COMFORT_STORAGE));
    return stored == null ? preferTouchComfortDefault() : stored;
  });
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => parseThemeMode(safeStorageGet(THEME_MODE_STORAGE)));
  const [prefersDarkTheme, setPrefersDarkTheme] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  const [isOnline, setIsOnline] = useState(() =>
    typeof navigator !== "undefined" && typeof navigator.onLine === "boolean" ? navigator.onLine : true,
  );
  const [installPromptEvent, setInstallPromptEvent] = useState<DeferredInstallPromptEvent | null>(null);
  const [installState, setInstallState] = useState<InstallState>("hidden");
  const [showInstallGuide, setShowInstallGuide] = useState(false);

  const [statusMessage, setStatusMessage] = useState("Loading controller state...");
  const [errorMessage, setErrorMessage] = useState("");
  const [eventLog, setEventLog] = useState<AppEventItem[]>([]);
  const [debugRuns, setDebugRuns] = useState<CodexRunSummary[]>([]);
  const [debugLoading, setDebugLoading] = useState(true);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedRun, setSelectedRun] = useState<CodexRunDetail | null>(null);
  const [selectedRunLoading, setSelectedRunLoading] = useState(false);
  const screenShellRef = useRef<HTMLElement | null>(null);
  const sessionOutputRef = useRef<HTMLPreElement | null>(null);
  const desktopFrameRef = useRef<HTMLImageElement | null>(null);
  const threadLastAssistantAtRef = useRef<Record<string, number>>({});
  const localThreadsRef = useRef<ChatThread[]>([]);
  const localThreadMessagesRef = useRef<Record<string, ThreadMessage[]>>({});
  const threadMigrationAttemptedRef = useRef(false);
  const localBootstrapAttemptedRef = useRef(false);

  const backendPort = useMemo(parsePort, []);
  const selectedSessionPaneId = useMemo(() => {
    const match = sessions.find((session) => session.session === selectedSession);
    return match?.pane_id || "";
  }, [selectedSession, sessions]);
  const tailscaleRouteUnavailable = routeHint === "tailscale" && !netInfo?.tailscale_ip;
  const desktopStreamUrl = useMemo(() => {
    const profile = DESKTOP_PROFILE_STREAM[desktopProfile];
    return buildDesktopStreamUrl(profile);
  }, [desktopProfile]);
  const desktopInteractionDisabled = !desktopEnabled;
  const sessionAllowedReasoningOptions = useMemo(() => {
    return allowedReasoningForModel(selectedModel, reasoningEffortOptions);
  }, [reasoningEffortOptions, selectedModel]);
  const threadTmuxPanes = useMemo(() => {
    return tmuxPanes.filter((pane) => !isCodexTmuxPane(pane));
  }, [tmuxPanes]);
  const selectedTmuxPaneInfo = useMemo(() => {
    return threadTmuxPanes.find((pane) => pane.pane_id === selectedTmuxPane) || null;
  }, [selectedTmuxPane, threadTmuxPanes]);
  const activeThread = useMemo(() => {
    return threads.find((thread) => thread.id === activeThreadId) || null;
  }, [activeThreadId, threads]);
  const threadSession = activeThread?.session || "";
  const threadSessionMessages = useMemo(() => {
    if (!activeThreadId) {
      return [] as ThreadMessage[];
    }
    return threadMessages[activeThreadId] || [];
  }, [activeThreadId, threadMessages]);
  const filteredThreads = useMemo(() => {
    const needle = threadSearch.trim().toLowerCase();
    return [...threads]
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .filter((thread) => {
      if (!needle) {
        return true;
      }
      const haystack = `${thread.title} ${thread.session}`.toLowerCase();
      return haystack.includes(needle);
      });
  }, [threadSearch, threads]);
  const filteredIpcHistory = useMemo(() => {
    const needle = ipcSearch.trim().toLowerCase();
    return ipcHistory.filter((item) => {
      if (ipcFilter === "all") {
        // no-op
      } else if (ipcFilter === "error") {
        if (item.direction !== "error") {
          return false;
        }
      } else if (item.channel !== ipcFilter) {
        return false;
      }
      if (!needle) {
        return true;
      }
      const haystack = `${item.path} ${item.detail || ""} ${item.requestBody || ""} ${item.responseBody || ""}`.toLowerCase();
      return haystack.includes(needle);
    });
  }, [ipcFilter, ipcHistory, ipcSearch]);
  const selectedIpcEvent = useMemo(() => {
    if (!selectedIpcId) {
      return filteredIpcHistory[0] || null;
    }
    return filteredIpcHistory.find((item) => item.id === selectedIpcId) || null;
  }, [filteredIpcHistory, selectedIpcId]);

  const addEvent = useCallback((level: AppEventLevel, message: string) => {
    const trimmed = message.trim();
    if (!trimmed) {
      return;
    }
    setEventLog((current) => {
      const next: AppEventItem = {
        id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        at: Date.now(),
        level,
        message: trimmed,
      };
      return [next, ...current].slice(0, 120);
    });
  }, []);

  const setStatus = useCallback((message: string) => {
    setStatusMessage(message);
    setErrorMessage("");
    addEvent("info", message);
  }, [addEvent]);

  const setError = useCallback((message: string) => {
    setErrorMessage(message);
    addEvent("error", message);
  }, [addEvent]);

  const addIpc = useCallback((event: IpcEvent) => {
    setIpcHistory((current) => [event, ...current].slice(0, 800));
    setSelectedIpcId((current) => current || event.id);
  }, []);

  const addThreadMessage = useCallback(
    (
      threadId: string,
      role: ThreadMessage["role"],
      text: string,
      options?: { id?: string; at?: number },
    ): ThreadMessage | null => {
      const trimmed = text.trim();
      if (!threadId || !trimmed) {
        return null;
      }
      const nextEntry: ThreadMessage = {
        id: options?.id || makeThreadMessageId(),
        threadId,
        role,
        text: trimmed,
        at: options?.at || Date.now(),
      };
      setThreadMessages((current) => {
        const existing = current[threadId] || [];
        return {
          ...current,
          [threadId]: [...existing, nextEntry].slice(-120),
        };
      });
      setThreads((current) =>
        current.map((thread) =>
          thread.id === threadId
            ? {
                ...thread,
                updatedAt: Math.max(thread.updatedAt || 0, nextEntry.at),
              }
            : thread,
        ),
      );
      return nextEntry;
    },
    [],
  );

  const syncThreadMessage = useCallback(async (message: ThreadMessage) => {
    try {
      const response = await addThreadRecordMessage(message.threadId, {
        id: message.id,
        role: message.role,
        text: message.text,
        at: message.at,
      });
      if (!response.ok) {
        throw new Error(response.detail || response.error || "thread message sync failed");
      }
    } catch (error) {
      addEvent("error", `Thread message sync failed: ${(error as Error).message}`);
    }
  }, [addEvent]);

  const captureAssistantSnapshot = useCallback((session: string, fullText: string, targetThreadId?: string) => {
    const compact = compactAssistantSnapshot(fullText);
    if (!compact) {
      return;
    }
    const now = Date.now();
    const last = threadLastAssistantAtRef.current[session] || 0;
    if (now - last < 3500) {
      return;
    }
    threadLastAssistantAtRef.current[session] = now;
    const threadId = targetThreadId || activeThreadId;
    if (!threadId) {
      return;
    }
    const message = addThreadMessage(threadId, "assistant", compact);
    if (message) {
      void syncThreadMessage(message);
    }
  }, [activeThreadId, addThreadMessage, syncThreadMessage]);

  const createThread = useCallback(async (session: string, titleRaw: string) => {
    const sessionName = session.trim();
    if (!sessionName) {
      return "";
    }
    const createdAt = Date.now();
    const nextThread: ChatThread = {
      id: makeThreadId(),
      session: sessionName,
      title: normalizeThreadTitle(titleRaw, sessionName),
      createdAt,
      updatedAt: createdAt,
    };
    setThreads((current) => [nextThread, ...current]);
    setThreadMessages((current) => ({
      ...current,
      [nextThread.id]: current[nextThread.id] || [],
    }));
    setActiveThreadId(nextThread.id);
    try {
      const response = await createThreadRecord({
        id: nextThread.id,
        session: nextThread.session,
        title: nextThread.title,
      });
      if (!response.ok || !response.thread) {
        throw new Error(response.detail || response.error || "create thread failed");
      }
      const serverThread = mapApiThread(response.thread);
      setThreads((current) =>
        current.map((thread) => (thread.id === serverThread.id ? serverThread : thread)),
      );
    } catch (error) {
      addEvent("error", `Thread sync failed: ${(error as Error).message}`);
    }
    return nextThread.id;
  }, [addEvent]);

  const ensureThreadForSession = useCallback(
    async (session: string, titleHint = ""): Promise<string> => {
      const sessionName = session.trim();
      if (!sessionName) {
        return "";
      }
      if (activeThread && activeThread.session === sessionName) {
        return activeThread.id;
      }
      const existing = threads.find((thread) => thread.session === sessionName);
      if (existing) {
        return existing.id;
      }
      return await createThread(sessionName, titleHint);
    },
    [activeThread, createThread, threads],
  );

  const refreshAuth = useCallback(async () => {
    try {
      const response = await getAuthStatus();
      setAuth(response);
    } catch (error) {
      setError(`Could not read auth status: ${(error as Error).message}`);
    } finally {
      setAuthLoading(false);
    }
  }, [setError]);

  const refreshNet = useCallback(async () => {
    try {
      const response = await getNetInfo();
      setNetInfo(response);
    } catch (error) {
      setError(`Could not read network info: ${(error as Error).message}`);
    }
  }, [setError]);

  const refreshCodexOptions = useCallback(async () => {
    try {
      const response = await getCodexOptions();
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Could not read Codex options.");
      }

      const models = (response.models || []).filter((item): item is string => typeof item === "string" && !!item.trim());
      const nextModels = models.length > 0 ? models : FALLBACK_MODELS;
      setModelOptions(nextModels);
      const responseModel = (response.default_model || "").trim();
      const defaultModel = responseModel && nextModels.includes(responseModel) ? responseModel : nextModels[0];
      setSelectedModel((current) => {
        if (current && nextModels.includes(current)) {
          return current;
        }
        return defaultModel;
      });

      const rawEfforts = (response.reasoning_efforts || []).filter((item): item is ReasoningEffort =>
        item === "minimal" || item === "low" || item === "medium" || item === "high" || item === "xhigh",
      );
      const nextEfforts = rawEfforts.length > 0 ? rawEfforts : FALLBACK_REASONING_EFFORTS;
      setReasoningEffortOptions(nextEfforts);
      const responseEffort = parseReasoningEffort(response.default_reasoning_effort || "");
      const defaultEffort = nextEfforts.includes(responseEffort) ? responseEffort : nextEfforts[nextEfforts.length - 1];
      setSelectedReasoningEffort((current) => {
        if (nextEfforts.includes(current)) {
          return current;
        }
        return defaultEffort;
      });
    } catch (error) {
      addEvent("error", `Could not load model options: ${(error as Error).message}`);
      setModelOptions(FALLBACK_MODELS);
      setReasoningEffortOptions(FALLBACK_REASONING_EFFORTS);
      setSelectedModel((current) => current || FALLBACK_MODELS[0]);
      setSelectedReasoningEffort((current) => (FALLBACK_REASONING_EFFORTS.includes(current) ? current : "xhigh"));
    }
  }, [addEvent]);

  const refreshSessions = useCallback(async () => {
    try {
      const response = await getSessions();
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Failed to read sessions.");
      }
      const nextSessions = response.sessions || [];
      setSessions(nextSessions);
      setSelectedSession((current) => {
        if (current && nextSessions.some((s) => s.session === current)) {
          return current;
        }
        return nextSessions[0]?.session || "";
      });
    } catch (error) {
      const detail = (error as Error).message || "";
      const lowered = detail.toLowerCase();
      if (lowered.includes("login required") || lowered.includes("unauthorized")) {
        setActiveTab("settings");
        setStatus("Login required. Open Settings and sign in with your token.");
      } else {
        setError(`Could not read sessions: ${detail}`);
      }
    } finally {
      setSessionsLoading(false);
    }
  }, [setError, setStatus]);

  const refreshSharedFiles = useCallback(async () => {
    try {
      const response = await listSharedFiles();
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Failed to read shared files.");
      }
      setSharedFiles(response.items || []);
    } catch (error) {
      addEvent("error", `Could not load shared files: ${(error as Error).message}`);
    } finally {
      setSharesLoading(false);
    }
  }, [addEvent]);

  const refreshTelegramStatus = useCallback(async () => {
    try {
      const response = await getTelegramStatus();
      setTelegramConfigured(Boolean(response.ok && response.configured));
    } catch {
      setTelegramConfigured(false);
    } finally {
      setTelegramStatusLoading(false);
    }
  }, []);

  const refreshThreads = useCallback(async () => {
    try {
      let response = await getThreadStore();
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Failed to read threads.");
      }

      if (
        (response.threads || []).length === 0
        && !threadMigrationAttemptedRef.current
        && localThreadsRef.current.length > 0
      ) {
        threadMigrationAttemptedRef.current = true;
        try {
          for (const thread of localThreadsRef.current) {
            await createThreadRecord({
              id: thread.id,
              session: thread.session,
              title: thread.title,
            });
            for (const message of localThreadMessagesRef.current[thread.id] || []) {
              await addThreadRecordMessage(thread.id, {
                id: message.id,
                role: message.role,
                text: message.text,
                at: message.at,
              });
            }
          }
          response = await getThreadStore();
        } catch (error) {
          addEvent("error", `Thread migration failed: ${(error as Error).message}`);
        }
      }
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Failed to read threads.");
      }

      const nextThreads = (response.threads || []).map(mapApiThread).sort((a, b) => b.updatedAt - a.updatedAt);
      const nextMessages = mapApiThreadMessageMap(response.messages || {});
      setThreads(nextThreads);
      setThreadMessages(nextMessages);
      setActiveThreadId((current) => {
        if (current && nextThreads.some((thread) => thread.id === current)) {
          return current;
        }
        return nextThreads[0]?.id || "";
      });
    } catch (error) {
      addEvent("error", `Could not sync threads: ${(error as Error).message}`);
    }
  }, [addEvent]);

  const refreshDebugRuns = useCallback(async () => {
    try {
      const response = await getCodexRuns();
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Failed to read run history.");
      }
      const nextRuns = response.runs || [];
      setDebugRuns(nextRuns);
      setSelectedRunId((current) => {
        if (current && nextRuns.some((run) => run.id === current)) {
          return current;
        }
        return nextRuns[0]?.id || "";
      });
    } catch (error) {
      const detail = (error as Error).message || "";
      const lowered = detail.toLowerCase();
      if (lowered.includes("login required") || lowered.includes("unauthorized")) {
        setActiveTab("settings");
        setStatus("Login required. Open Settings and sign in with your token.");
      } else {
        setError(`Could not read run history: ${detail}`);
      }
    } finally {
      setDebugLoading(false);
    }
  }, [setError, setStatus]);

  const refreshTmuxState = useCallback(async () => {
    try {
      const [healthResponse, panesResponse] = await Promise.all([getTmuxHealth(), getTmuxPanes()]);
      if (healthResponse.ok) {
        setTmuxHealthState(healthResponse.state || "ok");
        setTmuxSessions(healthResponse.sessions || []);
      } else {
        setTmuxHealthState("error");
      }
      if (panesResponse.ok) {
        const items = panesResponse.panes || [];
        setTmuxPanes(items);
        const shellOnly = items.filter((pane) => !isCodexTmuxPane(pane));
        setSelectedTmuxPane((current) => {
          if (current && shellOnly.some((pane) => pane.pane_id === current)) {
            return current;
          }
          return shellOnly[0]?.pane_id || "";
        });
      } else {
        setTmuxPanes([]);
      }
    } catch (error) {
      setTmuxHealthState("error");
      setError(`Could not read tmux state: ${(error as Error).message}`);
    }
  }, [setError]);

  const refreshTmuxScreen = useCallback(async (paneId: string) => {
    if (!paneId) {
      setTmuxScreenText("");
      return;
    }
    try {
      const response = await getTmuxPaneScreen(paneId);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Failed to read pane.");
      }
      setTmuxScreenText(response.text || "");
    } catch (error) {
      setError(`Could not read tmux pane: ${(error as Error).message}`);
    }
  }, [setError]);

  const refreshDesktopState = useCallback(async () => {
    try {
      const response = await getDesktopInfo();
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop info unavailable.");
      }
      setDesktopInfo(response);
      if (typeof response.enabled === "boolean") {
        setDesktopEnabled(response.enabled);
        if (!response.enabled) {
          setDesktopFocusPoint(null);
        }
      }
    } catch (error) {
      setDesktopInfo(null);
      setDesktopStatus(`Desktop unavailable: ${(error as Error).message}`);
    }
  }, []);

  const refreshRunDetail = useCallback(async (runId: string) => {
    if (!runId) {
      setSelectedRun(null);
      return;
    }
    setSelectedRunLoading(true);
    try {
      const response = await getCodexRun(runId);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Failed to read run details.");
      }
      setSelectedRun(response);
    } catch (error) {
      setError(`Could not read run detail: ${(error as Error).message}`);
      setSelectedRun(null);
    } finally {
      setSelectedRunLoading(false);
    }
  }, [setError]);

  const refreshScreen = useCallback(async (session: string) => {
    if (!session) {
      setScreenText("");
      return;
    }
    try {
      const response = await getSessionScreen(session);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Failed to read session screen.");
      }
      setScreenText(response.text || "");
    } catch (error) {
      setError(`Could not read screen: ${(error as Error).message}`);
    }
  }, [setError]);

  useEffect(() => {
    void (async () => {
      await Promise.all([
        refreshAuth(),
        refreshCodexOptions(),
        refreshNet(),
        refreshSessions(),
        refreshSharedFiles(),
        refreshTelegramStatus(),
        refreshThreads(),
        refreshDebugRuns(),
        refreshTmuxState(),
        refreshDesktopState(),
      ]);
      setStatus("Connected. Ready.");
    })();
  }, [refreshAuth, refreshCodexOptions, refreshDebugRuns, refreshDesktopState, refreshNet, refreshSessions, refreshSharedFiles, refreshTelegramStatus, refreshThreads, refreshTmuxState, setStatus]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const nav = window.navigator as Navigator & { standalone?: boolean };
    const inStandalone =
      Boolean(window.matchMedia?.("(display-mode: standalone)")?.matches) || Boolean(nav.standalone);
    if (inStandalone) {
      setInstallState("installed");
    }
    setIsOnline(typeof nav.onLine === "boolean" ? nav.onLine : true);

    const handleBeforeInstall = (event: Event) => {
      if (typeof event.preventDefault === "function") {
        event.preventDefault();
      }
      setInstallPromptEvent(event as DeferredInstallPromptEvent);
      setInstallState("ready");
      setShowInstallGuide(false);
      addEvent("info", "Install prompt available.");
    };

    const handleAppInstalled = () => {
      setInstallPromptEvent(null);
      setInstallState("installed");
      setShowInstallGuide(false);
      setStatus("Codrex installed on this device.");
    };

    const handleOnline = () => {
      setIsOnline(true);
      setStatus("Connection restored.");
    };

    const handleOffline = () => {
      setIsOnline(false);
      setError("You are offline. Reconnect to continue controlling sessions.");
    };

    window.addEventListener("beforeinstallprompt", handleBeforeInstall as EventListener);
    window.addEventListener("appinstalled", handleAppInstalled);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("beforeinstallprompt", handleBeforeInstall as EventListener);
      window.removeEventListener("appinstalled", handleAppInstalled);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [addEvent, setError, setStatus]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onThemeChange = (event: MediaQueryListEvent) => {
      setPrefersDarkTheme(event.matches);
    };
    setPrefersDarkTheme(media.matches);
    media.addEventListener("change", onThemeChange);
    return () => {
      media.removeEventListener("change", onThemeChange);
    };
  }, []);

  useEffect(() => {
    setIpcObserver(addIpc);
    return () => {
      setIpcObserver(null);
    };
  }, [addIpc]);

  useEffect(() => {
    const node = sessionOutputRef.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [screenText, selectedSession]);

  useEffect(() => {
    safeStorageSet(THREADS_STORAGE, JSON.stringify(threads));
    localThreadsRef.current = threads;
  }, [threads]);

  useEffect(() => {
    safeStorageSet(THREAD_MESSAGES_STORAGE, JSON.stringify(threadMessages));
    localThreadMessagesRef.current = threadMessages;
  }, [threadMessages]);

  useEffect(() => {
    if (activeThreadId && threads.some((thread) => thread.id === activeThreadId)) {
      return;
    }
    setActiveThreadId(threads[0]?.id || "");
  }, [activeThreadId, threads]);

  useEffect(() => {
    if (threadSessionInput) {
      return;
    }
    if (selectedSession) {
      setThreadSessionInput(selectedSession);
    } else if (sessions[0]?.session) {
      setThreadSessionInput(sessions[0].session);
    }
  }, [selectedSession, sessions, threadSessionInput]);

  useEffect(() => {
    if (!threadSessionInput) {
      return;
    }
    if (sessions.some((session) => session.session === threadSessionInput)) {
      return;
    }
    setThreadSessionInput(selectedSession || sessions[0]?.session || "");
  }, [selectedSession, sessions, threadSessionInput]);

  useEffect(() => {
    if (selectedIpcId && filteredIpcHistory.some((event) => event.id === selectedIpcId)) {
      return;
    }
    setSelectedIpcId(filteredIpcHistory[0]?.id || "");
  }, [filteredIpcHistory, selectedIpcId]);

  useEffect(() => {
    const previousTab = previousTabRef.current;
    const previousIndex = TAB_ORDER.indexOf(previousTab);
    const currentIndex = TAB_ORDER.indexOf(activeTab);
    if (previousIndex >= 0 && currentIndex >= 0) {
      if (currentIndex > previousIndex) {
        setTabTransitionClass("tab-slide-left");
      } else if (currentIndex < previousIndex) {
        setTabTransitionClass("tab-slide-right");
      } else {
        setTabTransitionClass("tab-still");
      }
    }
    previousTabRef.current = activeTab;
  }, [activeTab]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const tapTargetSelector = "button, .nav-item, .chip-action, .seg-item, .session-item, .run-item";
    const handlePointerDown = (event: PointerEvent) => {
      if (event.pointerType && event.pointerType !== "touch") {
        return;
      }
      const target = event.target as Element | null;
      if (!target) {
        return;
      }
      const hit = target.closest(tapTargetSelector) as HTMLElement | null;
      if (!hit) {
        return;
      }
      hit.classList.remove("tap-flash");
      void hit.offsetWidth;
      hit.classList.add("tap-flash");
      window.setTimeout(() => {
        hit.classList.remove("tap-flash");
      }, 180);
    };
    window.addEventListener("pointerdown", handlePointerDown, { passive: true });
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
    };
  }, []);

  useEffect(() => {
    const node = screenShellRef.current;
    if (!node) {
      return;
    }

    let tracking = false;
    let startX = 0;
    let startY = 0;
    let startAt = 0;

    const ignoreSelector = "input, textarea, select, button, a, label, [role='button']";

    const beginSwipe = (x: number, y: number, target: Element | null) => {
      if (consoleFocusMode) {
        return;
      }
      if (target?.closest(ignoreSelector)) {
        return;
      }
      tracking = true;
      startX = x;
      startY = y;
      startAt = Date.now();
    };

    const endSwipe = (x: number, y: number) => {
      if (!tracking) {
        return;
      }
      tracking = false;
      const deltaX = x - startX;
      const deltaY = y - startY;
      const elapsedMs = Date.now() - startAt;
      if (elapsedMs > 700) {
        return;
      }
      if (Math.abs(deltaX) < 80 || Math.abs(deltaX) < Math.abs(deltaY) * 1.35) {
        return;
      }
      const direction: 1 | -1 = deltaX < 0 ? 1 : -1;
      const nextTab = getAdjacentTab(activeTab, direction);
      if (nextTab !== activeTab) {
        setActiveTab(nextTab);
        setShowSwipeHint(false);
        addEvent("info", `Switched to ${nextTab} tab via swipe.`);
      }
    };

    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType && event.pointerType !== "touch") {
        return;
      }
      beginSwipe(event.clientX, event.clientY, event.target as Element | null);
    };

    const onPointerUp = (event: PointerEvent) => {
      endSwipe(event.clientX, event.clientY);
    };

    const onTouchStart = (event: TouchEvent) => {
      const firstTouch = event.touches[0];
      if (!firstTouch) {
        return;
      }
      beginSwipe(firstTouch.clientX, firstTouch.clientY, event.target as Element | null);
    };

    const onTouchEnd = (event: TouchEvent) => {
      const firstTouch = event.changedTouches[0];
      if (!firstTouch) {
        endSwipe(startX, startY);
        return;
      }
      endSwipe(firstTouch.clientX, firstTouch.clientY);
    };

    const onPointerCancel = () => {
      tracking = false;
    };

    node.addEventListener("pointerdown", onPointerDown, { passive: true });
    node.addEventListener("pointerup", onPointerUp, { passive: true });
    node.addEventListener("pointercancel", onPointerCancel, { passive: true });
    node.addEventListener("pointerleave", onPointerCancel, { passive: true });
    node.addEventListener("touchstart", onTouchStart, { passive: true });
    node.addEventListener("touchend", onTouchEnd, { passive: true });
    node.addEventListener("touchcancel", onPointerCancel, { passive: true });

    return () => {
      node.removeEventListener("pointerdown", onPointerDown);
      node.removeEventListener("pointerup", onPointerUp);
      node.removeEventListener("pointercancel", onPointerCancel);
      node.removeEventListener("pointerleave", onPointerCancel);
      node.removeEventListener("touchstart", onTouchStart);
      node.removeEventListener("touchend", onTouchEnd);
      node.removeEventListener("touchcancel", onPointerCancel);
    };
  }, [activeTab, addEvent, consoleFocusMode]);

  useEffect(() => {
    const intervalMs = activeTab === "remote" ? 3500 : 2500;
    const interval = window.setInterval(() => {
      const shouldPollSessions = activeTab === "sessions" || activeTab === "threads" || activeTab === "pair";
      if (shouldPollSessions) {
        void refreshSessions();
      }

      if (activeTab === "sessions") {
        const liveStreamActive =
          streamEnabled &&
          !!selectedSessionPaneId &&
          (outputFeedState === "connecting" || outputFeedState === "live");
        if (selectedSession && !liveStreamActive) {
          void refreshScreen(selectedSession);
        }
        void refreshSharedFiles();
      }

      if (activeTab === "debug") {
        void refreshDebugRuns();
        if (selectedRunId) {
          void refreshRunDetail(selectedRunId);
        }
      }
      if (activeTab === "threads") {
        void refreshThreads();
        void refreshTmuxState();
        if (selectedTmuxPane) {
          void refreshTmuxScreen(selectedTmuxPane);
        }
      }
      if (activeTab === "remote") {
        void refreshDesktopState();
      }
    }, intervalMs);
    return () => window.clearInterval(interval);
  }, [
    activeTab,
    outputFeedState,
    refreshDesktopState,
    refreshDebugRuns,
    refreshRunDetail,
    refreshScreen,
    refreshSessions,
    refreshSharedFiles,
    refreshThreads,
    refreshTmuxScreen,
    refreshTmuxState,
    selectedRunId,
    selectedSession,
    selectedSessionPaneId,
    selectedTmuxPane,
    streamEnabled,
  ]);

  useEffect(() => {
    if (!selectedSession) {
      return;
    }
    void refreshScreen(selectedSession);
  }, [refreshScreen, selectedSession]);

  useEffect(() => {
    if (!selectedTmuxPane) {
      setTmuxScreenText("");
      return;
    }
    void refreshTmuxScreen(selectedTmuxPane);
  }, [refreshTmuxScreen, selectedTmuxPane]);

  useEffect(() => {
    if (activeTab !== "sessions" || !selectedSession) {
      setConsoleFocusMode(false);
    }
  }, [activeTab, selectedSession]);

  useEffect(() => {
    if (showSwipeHint) {
      return;
    }
    safeStorageSet(SWIPE_HINT_SEEN_STORAGE, "true");
  }, [showSwipeHint]);

  useEffect(() => {
    safeStorageSet(COMPACT_TRANSCRIPT_STORAGE, compactTranscript ? "true" : "false");
  }, [compactTranscript]);

  useEffect(() => {
    safeStorageSet(TOUCH_COMFORT_STORAGE, touchComfortMode ? "true" : "false");
  }, [touchComfortMode]);

  useEffect(() => {
    safeStorageSet(THEME_MODE_STORAGE, themeMode);
  }, [themeMode]);

  useEffect(() => {
    const resolved = themeMode === "system" ? (prefersDarkTheme ? "dark" : "light") : themeMode;
    if (typeof document !== "undefined") {
      document.documentElement.setAttribute("data-theme", resolved);
    }
  }, [prefersDarkTheme, themeMode]);

  useEffect(() => {
    if (!streamEnabled || activeTab !== "sessions" || !selectedSessionPaneId) {
      return;
    }
    if (typeof window === "undefined" || typeof window.EventSource !== "function") {
      setOutputFeedState("polling");
      return;
    }

    const intervalMs = STREAM_PROFILE_INTERVAL_MS[streamProfile];
    const streamUrl = `/tmux/pane/${encodeURIComponent(selectedSessionPaneId)}/stream?interval_ms=${intervalMs}&max_chars=25000`;
    let closed = false;
    setOutputFeedState("connecting");
    reportIpcEvent({
      channel: "sse",
      direction: "out",
      method: "GET",
      path: streamUrl,
      detail: "connect",
    });
    const source = new EventSource(streamUrl);

    source.addEventListener("hello", () => {
      if (!closed) {
        setOutputFeedState("live");
        reportIpcEvent({
          channel: "sse",
          direction: "in",
          method: "GET",
          path: streamUrl,
          status: 200,
          detail: "hello",
        });
      }
    });

    source.addEventListener("screen", (event: Event) => {
      if (closed) {
        return;
      }
      try {
        const payload = JSON.parse((event as MessageEvent).data || "{}") as { text?: string };
        if (typeof payload.text === "string") {
          setScreenText(payload.text);
          setOutputFeedState("live");
          if (threadSession === selectedSession) {
            captureAssistantSnapshot(selectedSession, payload.text);
          }
          reportIpcEvent({
            channel: "sse",
            direction: "in",
            method: "GET",
            path: streamUrl,
            status: 200,
            detail: `screen ${payload.text.length} chars`,
          });
        }
      } catch {
        setOutputFeedState("error");
        reportIpcEvent({
          channel: "sse",
          direction: "error",
          method: "GET",
          path: streamUrl,
          detail: "parse_error",
        });
      }
    });

    source.addEventListener("error", () => {
      if (closed) {
        return;
      }
      setOutputFeedState("error");
      reportIpcEvent({
        channel: "sse",
        direction: "error",
        method: "GET",
        path: streamUrl,
        detail: "stream_error",
      });
      try {
        source.close();
      } catch {}
    });

    return () => {
      closed = true;
      try {
        source.close();
      } catch {}
      setOutputFeedState(streamEnabled ? "polling" : "off");
    };
  }, [activeTab, captureAssistantSnapshot, selectedSession, selectedSessionPaneId, streamEnabled, streamProfile, threadSession]);

  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRun(null);
      return;
    }
    void refreshRunDetail(selectedRunId);
  }, [refreshRunDetail, selectedRunId]);

  useEffect(() => {
    if (controllerBase.trim()) {
      safeStorageSet(CONTROLLER_BASE_STORAGE, controllerBase.trim());
      return;
    }
    safeStorageRemove(CONTROLLER_BASE_STORAGE);
  }, [controllerBase]);

  useEffect(() => {
    const code = pairCode.trim();
    if (!code) {
      return;
    }
    try {
      const link = buildPairConsumeUrl(controllerBase, code);
      const qr = buildPairQrPngUrl(controllerBase, link);
      setPairLink(link);
      setPairQrUrl(qr);
    } catch {
      setPairLink("");
      setPairQrUrl("");
    }
  }, [controllerBase, pairCode]);

  useEffect(() => {
    if (controllerBase.trim()) {
      return;
    }
    const suggested = buildSuggestedControllerUrl(
      window.location.hostname || "127.0.0.1",
      backendPort,
      netInfo,
      routeHint,
    );
    setControllerBase(suggested);
  }, [backendPort, controllerBase, netInfo, routeHint]);

  useEffect(() => {
    safeStorageSet(MODEL_STORAGE, selectedModel);
  }, [selectedModel]);

  useEffect(() => {
    setSelectedReasoningEffort((current) => clampReasoningForModel(selectedModel, current, reasoningEffortOptions));
  }, [reasoningEffortOptions, selectedModel]);

  useEffect(() => {
    safeStorageSet(REASONING_EFFORT_STORAGE, selectedReasoningEffort);
  }, [selectedReasoningEffort]);

  useEffect(() => {
    safeStorageSet(IMAGE_DELIVERY_MODE_STORAGE, sessionImageDeliveryMode);
  }, [sessionImageDeliveryMode]);

  useEffect(() => {
    safeStorageSet(SESSION_VIEW_STORAGE, sessionViewMode);
  }, [sessionViewMode]);

  useEffect(() => {
    safeStorageSet(STREAM_PROFILE_STORAGE, streamProfile);
  }, [streamProfile]);

  useEffect(() => {
    safeStorageSet(STREAM_ENABLED_STORAGE, streamEnabled ? "true" : "false");
    if (!streamEnabled) {
      setOutputFeedState("off");
    } else if (outputFeedState === "off") {
      setOutputFeedState("polling");
    }
  }, [outputFeedState, streamEnabled]);

  useEffect(() => {
    const profile = DESKTOP_PROFILE_STREAM[desktopProfile];
    setDesktopShotUrl(buildDesktopShotUrl(profile));
  }, [desktopProfile]);

  const projectOptions = useMemo(() => {
    const unique = new Set<string>();
    sessions.forEach((session) => {
      unique.add(inferProjectFromCwd(session.cwd));
    });
    return Array.from(unique).sort((a, b) => a.localeCompare(b));
  }, [sessions]);

  useEffect(() => {
    if (sessionProjectFilter === "all") {
      return;
    }
    if (!projectOptions.includes(sessionProjectFilter)) {
      setSessionProjectFilter("all");
    }
  }, [projectOptions, sessionProjectFilter]);

  const filteredSessions = useMemo(() => {
    const needle = sessionQuery.trim().toLowerCase();
    return sessions.filter((session) => {
      const project = inferProjectFromCwd(session.cwd);
      if (sessionProjectFilter !== "all" && project !== sessionProjectFilter) {
        return false;
      }
      if (!needle) {
        return true;
      }
      const haystack = [
        session.session,
        session.cwd,
        session.current_command,
        session.snippet,
        project,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [sessionProjectFilter, sessionQuery, sessions]);

  const groupedSessions = useMemo<SessionGroup[]>(() => {
    const byProject = new Map<string, SessionInfo[]>();
    filteredSessions.forEach((session) => {
      const project = inferProjectFromCwd(session.cwd);
      const current = byProject.get(project) || [];
      current.push(session);
      byProject.set(project, current);
    });
    return Array.from(byProject.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([project, items]) => ({
        project,
        items: [...items].sort((a, b) => a.session.localeCompare(b.session)),
      }));
  }, [filteredSessions]);

  const selectedSessionInfo = sessions.find((session) => session.session === selectedSession) || null;
  const authSummary = authLoading
    ? "Checking auth..."
    : auth?.auth_required
      ? auth?.authenticated
        ? "Authenticated"
        : "Login required"
      : "Auth disabled";
  const networkSummary = `LAN ${netInfo?.lan_ip || "n/a"} | Tailscale ${netInfo?.tailscale_ip || "n/a"}`;
  const sessionCountLabel = `${sessions.length} session${sessions.length === 1 ? "" : "s"}`;
  const visibleSessionCountLabel = `${filteredSessions.length} visible`;
  const runningRuns = debugRuns.filter((run) => run.status === "running").length;
  const totalEvents = eventLog.length;
  const controlProfileSummary = `${selectedModel} | ${selectedReasoningEffort}`;
  const resolvedTheme = themeMode === "system" ? (prefersDarkTheme ? "dark" : "light") : themeMode;
  const controllerRouteKind = classifyControllerRoute(controllerBase, netInfo);
  const controllerRouteSummary =
    controllerRouteKind === "tailscale"
      ? "Tailscale route"
      : controllerRouteKind === "lan"
        ? "LAN route"
        : controllerRouteKind === "localhost"
          ? "Localhost route"
          : "Route unknown";
  const controllerRouteAdvice =
    controllerRouteKind === "tailscale"
      ? "Best for remote access over trusted private network."
      : controllerRouteKind === "lan"
        ? "Works on local Wi-Fi only; not reachable outside LAN."
        : controllerRouteKind === "localhost"
          ? "Phone/tablet cannot reach localhost. Use LAN or Tailscale."
          : "Set a valid base URL before generating pairing QR.";
  const outputFeedSummary = streamEnabled ? `${outputFeedState} / ${streamProfile}` : "polling only";
  const connectivitySummary = isOnline ? "Online" : "Offline";
  const installSummary = installState === "installed" ? "Installed" : installPromptEvent ? "Ready" : "Browser Menu";
  const canSendPrompt = promptText.trim().length > 0;
  const installButtonLabel =
    installState === "installed"
      ? "Installed"
      : installState === "ready"
        ? "Install App"
        : installState === "prompting"
          ? "Installing..."
          : "Install Help";
  const focusButtonLabel = consoleFocusMode ? "Exit Focus" : "Focus Console";
  const screenCardClassName = `card screen-card ${tabTransitionClass}`;

  const onHardRefresh = useCallback(async () => {
    setStatus("Syncing controller state...");
    await Promise.all([
      refreshAuth(),
      refreshCodexOptions(),
      refreshNet(),
      refreshSessions(),
      refreshSharedFiles(),
      refreshTelegramStatus(),
      refreshThreads(),
      refreshDebugRuns(),
      refreshTmuxState(),
      refreshDesktopState(),
    ]);
    if (selectedSession) {
      await refreshScreen(selectedSession);
    }
    if (selectedTmuxPane) {
      await refreshTmuxScreen(selectedTmuxPane);
    }
    if (selectedRunId) {
      await refreshRunDetail(selectedRunId);
    }
    setStatus("Synced.");
  }, [refreshAuth, refreshCodexOptions, refreshDebugRuns, refreshDesktopState, refreshNet, refreshRunDetail, refreshScreen, refreshSessions, refreshSharedFiles, refreshTelegramStatus, refreshThreads, refreshTmuxScreen, refreshTmuxState, selectedRunId, selectedSession, selectedTmuxPane, setStatus]);

  const onLogin = useCallback(async () => {
    if (!tokenInput.trim()) {
      setError("Enter your access token.");
      return;
    }
    setAuthBusy(true);
    try {
      const response = await login(tokenInput.trim());
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Invalid token.");
      }
      setTokenInput("");
      await refreshAuth();
      await refreshSessions();
      await refreshTelegramStatus();
      await refreshThreads();
      setStatus("Logged in.");
      setActiveTab("sessions");
    } catch (error) {
      setError(`Login failed: ${(error as Error).message}`);
    } finally {
      setAuthBusy(false);
    }
  }, [refreshAuth, refreshSessions, refreshTelegramStatus, refreshThreads, setError, setStatus, tokenInput]);

  const onBootstrapLocalAuth = useCallback(async () => {
    setAuthBusy(true);
    try {
      const response = await bootstrapLocalAuth();
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Local laptop auth is unavailable.");
      }
      await refreshAuth();
      await refreshSessions();
      await refreshTelegramStatus();
      await refreshThreads();
      setStatus("Local laptop authentication is active.");
      setActiveTab("sessions");
    } catch (error) {
      setError(`Local auth failed: ${(error as Error).message}`);
    } finally {
      setAuthBusy(false);
    }
  }, [refreshAuth, refreshSessions, refreshTelegramStatus, refreshThreads, setError, setStatus]);

  const onLogout = useCallback(async () => {
    setAuthBusy(true);
    try {
      await logout();
      await refreshAuth();
      setTelegramConfigured(false);
      setStatus("Logged out.");
      setActiveTab("settings");
    } catch (error) {
      setError(`Logout failed: ${(error as Error).message}`);
    } finally {
      setAuthBusy(false);
    }
  }, [refreshAuth, setError, setStatus]);

  useEffect(() => {
    if (authLoading || !auth?.auth_required || auth.authenticated) {
      return;
    }
    if (localBootstrapAttemptedRef.current) {
      return;
    }
    if (typeof window === "undefined") {
      return;
    }
    const host = (window.location.hostname || "").toLowerCase();
    if (!(host === "localhost" || host === "127.0.0.1" || host === "::1")) {
      return;
    }
    localBootstrapAttemptedRef.current = true;
    void onBootstrapLocalAuth();
  }, [auth, authLoading, onBootstrapLocalAuth]);

  const onRouteHintChange = useCallback((nextRoute: RouteHint) => {
    setRouteHint(nextRoute);
    const suggested = buildSuggestedControllerUrl(
      window.location.hostname || "127.0.0.1",
      backendPort,
      netInfo,
      nextRoute,
    );
    setControllerBase(suggested);
  }, [backendPort, netInfo]);

  const onGeneratePairing = useCallback(async () => {
    setPairBusy(true);
    try {
      const response = await createPairCode();
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Could not generate pairing code.");
      }

      const code = response.code || "";
      if (!code) {
        setPairCode("");
        setPairLink("");
        setPairQrUrl("");
        setPairExpiry(null);
        setStatus("Auth token is disabled. Pairing code is not required.");
        return;
      }

      const link = buildPairConsumeUrl(controllerBase, code);
      const qr = buildPairQrPngUrl(controllerBase, link);
      setPairCode(code);
      setPairExpiry(response.expires_in ?? null);
      setPairLink(link);
      setPairQrUrl(qr);
      setStatus("Pairing code generated.");
    } catch (error) {
      setError(`Pairing failed: ${(error as Error).message}`);
    } finally {
      setPairBusy(false);
    }
  }, [controllerBase, setError, setStatus]);

  const onPairExchange = useCallback(async () => {
    if (!pairCode.trim()) {
      setError("Pair code is empty.");
      return;
    }

    setPairBusy(true);
    try {
      const response = await exchangePairCode(pairCode.trim());
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Code exchange failed.");
      }
      await refreshAuth();
      setStatus("Pair exchange successful. This device is authenticated.");
    } catch (error) {
      setError(`Pair exchange failed: ${(error as Error).message}`);
    } finally {
      setPairBusy(false);
    }
  }, [pairCode, refreshAuth, setError, setStatus]);

  const onCopyPairLink = useCallback(async () => {
    if (!pairLink) {
      setError("Generate a pair link first.");
      return;
    }
    try {
      await navigator.clipboard.writeText(pairLink);
      setStatus("Pair link copied.");
    } catch (error) {
      setError(`Could not copy pair link: ${(error as Error).message}`);
    }
  }, [pairLink, setError, setStatus]);

  const onOpenPairLink = useCallback(() => {
    if (!pairLink) {
      setError("Generate a pair link first.");
      return;
    }
    window.open(pairLink, "_blank", "noopener,noreferrer");
  }, [pairLink, setError]);

  const onCreateSession = useCallback(async () => {
    setSessionBusy(true);
    try {
      const createReasoningEffort = clampReasoningForModel(selectedModel, selectedReasoningEffort, reasoningEffortOptions);
      const response = await createSessionWithOptions({
        name: newSessionName.trim(),
        cwd: newSessionCwd.trim(),
        model: selectedModel,
        reasoning_effort: createReasoningEffort,
      });
      if (!response.ok || !response.session) {
        throw new Error(response.detail || response.error || "Could not create session.");
      }
      setNewSessionName("");
      setNewSessionCwd("");
      setSelectedSession(response.session);
      setStreamEnabled(true);
      setOutputFeedState("polling");
      await refreshSessions();
      await refreshScreen(response.session);
      setActiveTab("sessions");
      setStatus(`Created ${response.session} (${response.model || selectedModel}, ${response.reasoning_effort || createReasoningEffort}).`);
    } catch (error) {
      setError(`Create session failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [
    newSessionCwd,
    newSessionName,
    refreshScreen,
    refreshSessions,
    reasoningEffortOptions,
    selectedModel,
    selectedReasoningEffort,
    setError,
    setStatus,
  ]);

  const onSendPrompt = useCallback(async () => {
    if (!selectedSession) {
      setError("Select a session first.");
      return;
    }
    const userPrompt = promptText.trim();
    if (!userPrompt) {
      setError("Prompt cannot be empty.");
      return;
    }

    setSessionBusy(true);
    try {
      const response = await sendToSession(selectedSession, userPrompt);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Prompt send failed.");
      }
      if (response.shared_file) {
        setPromptText("");
        setStatus(response.detail || `Shared ${response.shared_file.file_name} to mobile inbox.`);
        await refreshSharedFiles();
        await refreshSessions();
        return;
      }
      setPromptText("");
      const threadId = await ensureThreadForSession(selectedSession, userPrompt);
      if (threadId) {
        const message = addThreadMessage(threadId, "user", userPrompt);
        if (message) {
          void syncThreadMessage(message);
        }
      }
      setStatus(`Sent prompt to ${selectedSession}.`);
      await refreshScreen(selectedSession);
      await refreshSessions();
      window.setTimeout(async () => {
        try {
          const snapshot = await getSessionScreen(selectedSession);
          if (snapshot.ok && snapshot.text && threadId) {
            captureAssistantSnapshot(selectedSession, snapshot.text, threadId);
          }
        } catch {}
      }, 1200);
    } catch (error) {
      setError(`Send failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [addThreadMessage, captureAssistantSnapshot, ensureThreadForSession, promptText, refreshScreen, refreshSessions, refreshSharedFiles, selectedSession, setError, setStatus, syncThreadMessage]);

  const onSendEnter = useCallback(async () => {
    if (!selectedSession) {
      setError("Select a session first.");
      return;
    }
    setSessionBusy(true);
    try {
      const response = await enterSession(selectedSession);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Enter failed.");
      }
      setStatus(`Sent Enter to ${selectedSession}.`);
      await refreshScreen(selectedSession);
      await refreshSessions();
    } catch (error) {
      setError(`Enter failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [refreshScreen, refreshSessions, selectedSession, setError, setStatus]);

  const onInterrupt = useCallback(async () => {
    if (!selectedSession) {
      setError("Select a session first.");
      return;
    }
    setSessionBusy(true);
    try {
      const response = await interruptSession(selectedSession);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Interrupt failed.");
      }
      setStatus(`Interrupted ${selectedSession}.`);
      await refreshScreen(selectedSession);
      await refreshSessions();
    } catch (error) {
      setError(`Interrupt failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [refreshScreen, refreshSessions, selectedSession, setError, setStatus]);

  const onCtrlC = useCallback(async () => {
    if (!selectedSession) {
      setError("Select a session first.");
      return;
    }
    setSessionBusy(true);
    try {
      const response = await ctrlcSession(selectedSession);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Ctrl+C failed.");
      }
      setStatus(`Sent Ctrl+C to ${selectedSession}.`);
      await refreshScreen(selectedSession);
      await refreshSessions();
    } catch (error) {
      setError(`Ctrl+C failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [refreshScreen, refreshSessions, selectedSession, setError, setStatus]);

  const onInstallCta = useCallback(async () => {
    if (installState === "installed") {
      return;
    }
    if (!installPromptEvent) {
      setShowInstallGuide((current) => !current);
      return;
    }
    setShowInstallGuide(false);
    setInstallState("prompting");
    try {
      await installPromptEvent.prompt();
      const choice = await installPromptEvent.userChoice;
      if (choice?.outcome === "accepted") {
        setInstallPromptEvent(null);
        setInstallState("hidden");
        setStatus("Install accepted. Add Codrex from your home screen or app drawer.");
      } else {
        setInstallState("ready");
        setStatus("Install dismissed. Use Install Help to pin later.");
      }
    } catch (error) {
      setInstallState("ready");
      setError(`Install flow failed: ${(error as Error).message}`);
    }
  }, [installPromptEvent, installState, setError, setStatus]);

  const onCloseSession = useCallback(async () => {
    if (!selectedSession) {
      setError("Select a session first.");
      return;
    }
    setSessionBusy(true);
    try {
      const response = await closeSession(selectedSession);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Close failed.");
      }
      setStatus(`Closed ${selectedSession}.`);
      await refreshSessions();
      setScreenText("");
    } catch (error) {
      setError(`Close session failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [refreshSessions, selectedSession, setError, setStatus]);

  const onSendSessionImage = useCallback(async () => {
    if (!selectedSession) {
      setError("Select a session first.");
      return;
    }
    if (!sessionImageFile) {
      setError("Choose an image file first.");
      return;
    }
    setSessionBusy(true);
    try {
      const response = await sendSessionImage(selectedSession, sessionImageFile, sessionImagePrompt, {
        delivery_mode: sessionImageDeliveryMode,
      });
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Image send failed.");
      }
      setSessionImageFile(null);
      setSessionImagePrompt("");
      if (response.delivery_mode === "insert_path") {
        setStatus(`Image path inserted into ${selectedSession}. Continue typing your prompt, then press Send.`);
      } else if (response.delivery_mode === "desktop_clipboard" && response.paste_ok) {
        setStatus(`Image copied to desktop clipboard and pasted (Ctrl+V) to focused app for ${selectedSession}.`);
      } else {
        setStatus(`Image sent to ${selectedSession}.`);
      }
      await refreshScreen(selectedSession);
    } catch (error) {
      setError(`Send image failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [
    refreshScreen,
    selectedSession,
    sessionImageDeliveryMode,
    sessionImageFile,
    sessionImagePrompt,
    setError,
    setStatus,
  ]);

  const onCreateSharedFile = useCallback(async () => {
    const path = sharePathInput.trim();
    if (!path) {
      setError("Enter a file path to share.");
      return;
    }
    const expires = Number.parseInt(shareExpiresHours, 10);
    if (!Number.isFinite(expires) || expires <= 0) {
      setError("Expiry must be a positive number of hours.");
      return;
    }
    setShareBusy(true);
    try {
      const response = await createSharedFile({
        path,
        title: shareTitleInput.trim() || undefined,
        expires_hours: expires,
        created_by: selectedSession ? `session:${selectedSession}` : "manual",
      });
      if (!response.ok || !response.item) {
        throw new Error(response.detail || response.error || "Share creation failed.");
      }
      setSharePathInput("");
      setShareTitleInput("");
      setStatus(`Shared ${response.item.file_name}.`);
      await refreshSharedFiles();
    } catch (error) {
      setError(`Share failed: ${(error as Error).message}`);
    } finally {
      setShareBusy(false);
    }
  }, [refreshSharedFiles, selectedSession, setError, setStatus, shareExpiresHours, sharePathInput, shareTitleInput]);

  const onDeleteSharedFile = useCallback(async (itemId: string) => {
    if (!itemId) {
      return;
    }
    setShareBusy(true);
    try {
      const response = await deleteSharedFile(itemId);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Delete failed.");
      }
      setStatus("Shared file removed.");
      await refreshSharedFiles();
    } catch (error) {
      setError(`Delete failed: ${(error as Error).message}`);
    } finally {
      setShareBusy(false);
    }
  }, [refreshSharedFiles, setError, setStatus]);

  const onSendSharedToTelegram = useCallback(async (item: SharedFileInfo) => {
    if (!item?.id) {
      return;
    }
    setShareBusy(true);
    try {
      const response = await sendSharedFileToTelegram(item.id, item.title || item.file_name);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Telegram send failed.");
      }
      setStatus(response.detail || `Sent ${item.file_name} to Telegram.`);
    } catch (error) {
      setError(`Telegram send failed: ${(error as Error).message}`);
    } finally {
      setShareBusy(false);
    }
  }, [setError, setStatus]);

  const buildCodrexSendCommand = useCallback((includeTelegram: boolean) => {
    const path = sharePathInput.trim();
    if (!path) {
      return { ok: false as const, detail: "Enter a file path first to build command." };
    }
    const title = shareTitleInput.trim();
    const escapedPath = path.replace(/"/g, '\\"');
    const escapedTitle = title.replace(/"/g, '\\"');
    const parts: string[] = [`codrex-send "${escapedPath}"`];
    if (title) {
      parts.push(`--title "${escapedTitle}"`);
    }
    const expires = Number.parseInt(shareExpiresHours, 10);
    if (Number.isFinite(expires) && expires > 0) {
      parts.push(`--expires ${expires}`);
    }
    if (includeTelegram) {
      parts.push("--telegram");
      if (title) {
        parts.push(`--caption "${escapedTitle}"`);
      }
    }
    return { ok: true as const, cmd: parts.join(" ") };
  }, [shareExpiresHours, sharePathInput, shareTitleInput]);

  const onCopyShareCommand = useCallback(async () => {
    const built = buildCodrexSendCommand(false);
    if (!built.ok) {
      setError(built.detail);
      return;
    }
    try {
      await navigator.clipboard.writeText(built.cmd);
      setStatus("Share command copied.");
    } catch (error) {
      setError(`Could not copy command: ${(error as Error).message}`);
    }
  }, [buildCodrexSendCommand, setError, setStatus]);

  const onCopyShareLink = useCallback(async (item: SharedFileInfo) => {
    const base = (controllerBase || "").trim() || (typeof window !== "undefined" ? window.location.origin : "");
    const normalizedBase = base.replace(/\/$/, "");
    const path = item.download_url.startsWith("/") ? item.download_url : `/${item.download_url}`;
    const full = `${normalizedBase}${path}`;
    try {
      await navigator.clipboard.writeText(full);
      setStatus("Share link copied.");
    } catch (error) {
      setError(`Could not copy share link: ${(error as Error).message}`);
    }
  }, [controllerBase, setError, setStatus]);

  const onApplySessionProfile = useCallback(async () => {
    if (!selectedSession) {
      setError("Select a session first.");
      return;
    }
    setSessionBusy(true);
    try {
      const nextReasoningEffort = clampReasoningForModel(selectedModel, selectedReasoningEffort, reasoningEffortOptions);
      const response = await applySessionProfile(selectedSession, {
        model: selectedModel,
        reasoning_effort: nextReasoningEffort,
      });
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Profile apply failed.");
      }
      setStatus(
        `Applied ${response.model || selectedModel} / ${response.reasoning_effort || nextReasoningEffort} to ${selectedSession}.`,
      );
      await refreshScreen(selectedSession);
      await refreshSessions();
    } catch (error) {
      setError(`Profile apply failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [
    refreshScreen,
    refreshSessions,
    reasoningEffortOptions,
    selectedModel,
    selectedReasoningEffort,
    selectedSession,
    setError,
    setStatus,
  ]);

  const onCreateThread = useCallback(async () => {
    const sessionName = (threadSessionInput || selectedSession).trim();
    if (!sessionName) {
      setError("Pick a session to create a thread.");
      return;
    }
    const threadId = await createThread(sessionName, threadTitleInput);
    if (!threadId) {
      setError("Could not create thread.");
      return;
    }
    setThreadTitleInput("");
    setThreadSessionInput(sessionName);
    setStatus(`Created thread for ${sessionName}.`);
  }, [createThread, selectedSession, setError, setStatus, threadSessionInput, threadTitleInput]);

  const onRenameThread = useCallback(async () => {
    if (!activeThread) {
      setError("Select a thread first.");
      return;
    }
    const title = threadTitleInput.trim();
    if (!title) {
      setError("Enter a new thread title.");
      return;
    }
    setThreads((current) =>
      current.map((thread) =>
        thread.id === activeThread.id
          ? {
              ...thread,
              title: normalizeThreadTitle(title, thread.session),
              updatedAt: Date.now(),
            }
          : thread,
      ),
    );
    setThreadTitleInput("");
    try {
      const response = await updateThreadRecord(activeThread.id, { title });
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Rename sync failed.");
      }
    } catch (error) {
      addEvent("error", `Rename sync failed: ${(error as Error).message}`);
    }
    setStatus("Thread title updated.");
  }, [activeThread, addEvent, setError, setStatus, threadTitleInput]);

  const onDeleteThread = useCallback(async () => {
    if (!activeThread) {
      setError("Select a thread first.");
      return;
    }
    const deleteId = activeThread.id;
    setThreads((current) => current.filter((thread) => thread.id !== deleteId));
    setThreadMessages((current) => {
      const next = { ...current };
      delete next[deleteId];
      return next;
    });
    setActiveThreadId((current) => (current === deleteId ? "" : current));
    try {
      const response = await deleteThreadRecord(deleteId);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Delete sync failed.");
      }
    } catch (error) {
      addEvent("error", `Delete sync failed: ${(error as Error).message}`);
    }
    setStatus("Thread deleted.");
  }, [activeThread, addEvent, setError, setStatus]);

  const onSendThreadPrompt = useCallback(async () => {
    const sessionName = (activeThread?.session || threadSessionInput || selectedSession).trim();
    if (!sessionName) {
      setError("Select a session for thread chat.");
      return;
    }
    const prompt = threadPrompt.trim();
    if (!prompt) {
      setError("Thread prompt cannot be empty.");
      return;
    }
    let threadId = activeThreadId;
    if (!threadId) {
      threadId = await createThread(sessionName, threadTitleInput || prompt);
    }
    if (!threadId) {
      setError("Could not resolve target thread.");
      return;
    }
    setActiveThreadId(threadId);
    setThreadBusy(true);
    try {
      const response = await sendToSession(sessionName, prompt);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Thread send failed.");
      }
      const message = addThreadMessage(threadId, "user", prompt);
      if (message) {
        void syncThreadMessage(message);
      }
      setThreads((current) =>
        current.map((thread) =>
          thread.id === threadId
            ? {
                ...thread,
                title:
                  threadMessages[threadId]?.length
                    ? thread.title
                    : normalizeThreadTitle(threadTitleInput || prompt, thread.session),
                updatedAt: Date.now(),
              }
            : thread,
        ),
      );
      setThreadPrompt("");
      setStatus(`Sent thread prompt to ${sessionName}.`);
      const snapshot = await getSessionScreen(sessionName);
      if (snapshot.ok && snapshot.text) {
        captureAssistantSnapshot(sessionName, snapshot.text, threadId);
      }
    } catch (error) {
      setError(`Thread send failed: ${(error as Error).message}`);
    } finally {
      setThreadBusy(false);
    }
  }, [activeThread?.session, activeThreadId, addThreadMessage, captureAssistantSnapshot, createThread, selectedSession, setError, setStatus, syncThreadMessage, threadMessages, threadPrompt, threadSessionInput, threadTitleInput]);

  const onCaptureThreadSnapshot = useCallback(async () => {
    const sessionName = (activeThread?.session || threadSessionInput || selectedSession).trim();
    if (!sessionName) {
      setError("Select a session for snapshot.");
      return;
    }
    const threadId = activeThreadId || (await createThread(sessionName, threadTitleInput));
    if (!threadId) {
      setError("Create or select a thread first.");
      return;
    }
    setActiveThreadId(threadId);
    try {
      const snapshot = await getSessionScreen(sessionName);
      if (!snapshot.ok || !snapshot.text) {
        throw new Error(snapshot.detail || snapshot.error || "No screen output.");
      }
      captureAssistantSnapshot(sessionName, snapshot.text, threadId);
      setStatus("Assistant snapshot captured.");
    } catch (error) {
      setError(`Snapshot failed: ${(error as Error).message}`);
    }
  }, [activeThread?.session, activeThreadId, captureAssistantSnapshot, createThread, selectedSession, setError, setStatus, threadSessionInput, threadTitleInput]);

  const onCreateTmuxSession = useCallback(async () => {
    const requestedName = tmuxSessionName.trim();
    const bootCommand = TMUX_SHELL_BOOT_COMMAND[tmuxShellProfile];
    if (bootCommand && !requestedName) {
      setError("Set a tmux session name to apply PowerShell/CMD profile.");
      return;
    }

    setTmuxBusy(true);
    try {
      const response = await createTmuxSession(requestedName);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "tmux create failed.");
      }
      setTmuxSessionName("");
      await refreshTmuxState();

      if (bootCommand && requestedName) {
        const panesResponse = await getTmuxPanes(requestedName);
        const targetPane = panesResponse.ok ? (panesResponse.panes || [])[0]?.pane_id || "" : "";
        if (targetPane) {
          const bootResponse = await sendToPane(targetPane, bootCommand);
          if (!bootResponse.ok) {
            throw new Error(bootResponse.detail || bootResponse.error || "shell bootstrap failed.");
          }
          setSelectedTmuxPane(targetPane);
          await refreshTmuxScreen(targetPane);
        }
      }

      setStatus(
        bootCommand
          ? `tmux session created with ${tmuxShellProfile} shell profile.`
          : "tmux session created.",
      );
    } catch (error) {
      setError(`tmux create failed: ${(error as Error).message}`);
    } finally {
      setTmuxBusy(false);
    }
  }, [refreshTmuxScreen, refreshTmuxState, setError, setStatus, tmuxSessionName, tmuxShellProfile]);

  const onCloseTmuxSession = useCallback(async () => {
    const session = selectedTmuxPaneInfo?.session || "";
    if (!session) {
      setError("Select a tmux pane/session first.");
      return;
    }
    setTmuxBusy(true);
    try {
      const response = await closeTmuxSession(session);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "tmux close failed.");
      }
      await refreshTmuxState();
      setTmuxScreenText("");
      setStatus(`Closed tmux session ${session}.`);
    } catch (error) {
      setError(`tmux close failed: ${(error as Error).message}`);
    } finally {
      setTmuxBusy(false);
    }
  }, [refreshTmuxState, selectedTmuxPaneInfo?.session, setError, setStatus]);

  const onSendTmuxPrompt = useCallback(async () => {
    if (!selectedTmuxPane) {
      setError("Select a tmux pane first.");
      return;
    }
    const prompt = tmuxPrompt.trim();
    if (!prompt) {
      setError("Pane message cannot be empty.");
      return;
    }
    setTmuxBusy(true);
    try {
      const response = await sendToPane(selectedTmuxPane, prompt);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "tmux send failed.");
      }
      setTmuxPrompt("");
      setStatus("Message sent to tmux pane.");
      await refreshTmuxScreen(selectedTmuxPane);
    } catch (error) {
      setError(`tmux send failed: ${(error as Error).message}`);
    } finally {
      setTmuxBusy(false);
    }
  }, [refreshTmuxScreen, selectedTmuxPane, setError, setStatus, tmuxPrompt]);

  const onInterruptTmuxPane = useCallback(async () => {
    if (!selectedTmuxPane) {
      setError("Select a tmux pane first.");
      return;
    }
    setTmuxBusy(true);
    try {
      const response = await interruptPane(selectedTmuxPane);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "tmux interrupt failed.");
      }
      setStatus("Interrupt sent to pane.");
      await refreshTmuxScreen(selectedTmuxPane);
    } catch (error) {
      setError(`tmux interrupt failed: ${(error as Error).message}`);
    } finally {
      setTmuxBusy(false);
    }
  }, [refreshTmuxScreen, selectedTmuxPane, setError, setStatus]);

  const onToggleDesktopMode = useCallback(async () => {
    try {
      const response = await setDesktopMode(!desktopEnabled);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop mode request failed.");
      }
      const enabled = !!response.enabled;
      setDesktopEnabled(enabled);
      setDesktopStatus(enabled ? "Desktop control enabled." : "Desktop control disabled.");
      if (!enabled) {
        setDesktopFocusPoint(null);
      }
      if (enabled) {
        await refreshDesktopState();
      }
    } catch (error) {
      setError(`Desktop mode failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, refreshDesktopState, setError]);

  const onDesktopClick = useCallback(async (button: "left" | "right", double = false) => {
    if (!desktopEnabled) {
      setError("Desktop control is disabled. Enable Desktop first.");
      return;
    }
    try {
      const response = await desktopClick({ button, double });
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop click failed.");
      }
      setDesktopStatus(`${double ? "Double " : ""}${button} click sent.`);
    } catch (error) {
      setError(`Desktop click failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, setError]);

  const onDesktopScroll = useCallback(async (delta: number) => {
    if (!desktopEnabled) {
      setError("Desktop control is disabled. Enable Desktop first.");
      return;
    }
    try {
      const response = await desktopScroll(delta);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop scroll failed.");
      }
      setDesktopStatus(`Scroll ${delta < 0 ? "up" : "down"} sent.`);
    } catch (error) {
      setError(`Desktop scroll failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, setError]);

  const onDesktopSendText = useCallback(async () => {
    if (!desktopEnabled) {
      setError("Desktop control is disabled. Enable Desktop first.");
      return;
    }
    const text = desktopTextInput;
    if (!text) {
      setError("Desktop text is empty.");
      return;
    }
    try {
      if (desktopFocusPoint) {
        await desktopClick({ x: desktopFocusPoint.x, y: desktopFocusPoint.y, button: "left" });
      }
      const response = await desktopSendText(text);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop text failed.");
      }
      setDesktopTextInput("");
      setDesktopStatus("Desktop text sent.");
    } catch (error) {
      setError(`Desktop text failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, desktopFocusPoint, desktopTextInput, setError]);

  const onDesktopPasteClipboard = useCallback(async () => {
    if (!desktopEnabled) {
      setError("Desktop control is disabled. Enable Desktop first.");
      return;
    }
    let text = "";
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard && navigator.clipboard.readText) {
        text = await navigator.clipboard.readText();
      }
    } catch {
      text = "";
    }

    if (!text) {
      text = desktopTextInput;
    }
    if (!text) {
      setError("Clipboard is empty/unavailable. Paste text into the field, then send.");
      return;
    }
    try {
      if (desktopFocusPoint) {
        await desktopClick({ x: desktopFocusPoint.x, y: desktopFocusPoint.y, button: "left" });
      }
      const response = await desktopSendText(text);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop paste failed.");
      }
      setDesktopTextInput("");
      setDesktopStatus("Clipboard text sent to desktop.");
    } catch (error) {
      setError(`Desktop paste failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, desktopFocusPoint, desktopTextInput, setError]);

  const onSendRemoteTextToTelegram = useCallback(async () => {
    const text = desktopTextInput.trim();
    if (!text) {
      setError("Type text first.");
      return;
    }
    if (!telegramConfigured) {
      setError("Telegram delivery is not configured.");
      return;
    }
    setTelegramTextBusy(true);
    try {
      const response = await sendTelegramText(text);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Telegram send failed.");
      }
      setStatus(response.detail || "Sent to Telegram.");
    } catch (error) {
      setError(`Telegram send failed: ${(error as Error).message}`);
    } finally {
      setTelegramTextBusy(false);
    }
  }, [desktopTextInput, setError, setStatus, telegramConfigured]);

  const onDesktopFrameTap = useCallback(async (event: React.MouseEvent<HTMLImageElement>) => {
    if (!desktopEnabled) {
      setDesktopStatus("Desktop control is disabled. Enable Desktop first.");
      return;
    }
    if (!desktopInfo?.width || !desktopInfo?.height) {
      return;
    }
    const img = desktopFrameRef.current;
    if (!img) {
      return;
    }
    const rect = img.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return;
    }

    const normX = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const normY = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
    const targetX = Math.round(normX * desktopInfo.width);
    const targetY = Math.round(normY * desktopInfo.height);
    setDesktopFocusPoint({ x: targetX, y: targetY });

    try {
      const response = await desktopClick({ x: targetX, y: targetY, button: "left" });
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop tap failed.");
      }
      setDesktopStatus(`Focused desktop at ${targetX}, ${targetY}.`);
    } catch (error) {
      setError(`Desktop tap failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, desktopInfo?.height, desktopInfo?.width, setError]);

  const onDesktopSendKey = useCallback(async () => {
    if (!desktopEnabled) {
      setError("Desktop control is disabled. Enable Desktop first.");
      return;
    }
    try {
      const response = await desktopSendKey(desktopKeyInput);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop key failed.");
      }
      setDesktopStatus(`Key sent: ${desktopKeyInput}`);
    } catch (error) {
      setError(`Desktop key failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, desktopKeyInput, setError]);

  const onRefreshDesktopShot = useCallback(() => {
    const profile = DESKTOP_PROFILE_STREAM[desktopProfile];
    setDesktopShotUrl(buildDesktopShotUrl(profile));
    setStatus("Desktop shot refreshed.");
  }, [desktopProfile, setStatus]);

  const onRunExec = useCallback(async () => {
    const prompt = execPrompt.trim();
    if (!prompt) {
      setError("Exec prompt cannot be empty.");
      return;
    }
    setExecBusy(true);
    try {
      const response = await startCodexExec(prompt);
      if (!response.ok || !response.id) {
        throw new Error(response.detail || response.error || "Exec start failed.");
      }
      setExecPrompt("");
      setSelectedRunId(response.id);
      setActiveTab("debug");
      setStatus(`Started codex exec run ${response.id}.`);
      await refreshDebugRuns();
    } catch (error) {
      setError(`Exec start failed: ${(error as Error).message}`);
    } finally {
      setExecBusy(false);
    }
  }, [execPrompt, refreshDebugRuns, setError, setStatus]);

  const onDownloadWslFile = useCallback(() => {
    const path = wslDownloadPath.trim();
    if (!path) {
      setError("Enter a WSL file path first.");
      return;
    }
    const url = buildWslDownloadUrl(path);
    window.open(url, "_blank", "noopener,noreferrer");
    setStatus("Opened WSL file download.");
  }, [setError, setStatus, wslDownloadPath]);

  const onUploadWslFile = useCallback(async () => {
    if (!wslUploadFile) {
      setError("Choose a file to upload.");
      return;
    }
    try {
      setFileStatus("Uploading...");
      const response = await uploadWslFile(wslUploadFile, wslUploadDest);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Upload failed.");
      }
      setWslUploadFile(null);
      setWslUploadDest("");
      setFileStatus(`Uploaded: ${response.saved_path || "(unknown path)"}`);
      setStatus("WSL upload complete.");
    } catch (error) {
      setFileStatus("");
      setError(`Upload failed: ${(error as Error).message}`);
    }
  }, [setError, setStatus, wslUploadDest, wslUploadFile]);

  const onCaptureLatestShot = useCallback(() => {
    const profile = DESKTOP_PROFILE_STREAM[desktopProfile];
    setLatestCaptureUrl(buildDesktopShotUrl(profile));
    setStatus("Captured latest desktop screenshot.");
  }, [desktopProfile, setStatus]);

  const onClearIpcHistory = useCallback(() => {
    setIpcHistory([]);
    setSelectedIpcId("");
    setStatus("IPC history cleared.");
  }, [setStatus]);

  const onExportIpcHistory = useCallback(() => {
    if (ipcHistory.length === 0) {
      setError("No IPC history to export.");
      return;
    }
    try {
      const blob = new Blob([`${JSON.stringify(ipcHistory, null, 2)}\n`], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `codrex-ipc-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => {
        URL.revokeObjectURL(url);
      }, 500);
      setStatus("IPC history exported.");
    } catch (error) {
      setError(`Export failed: ${(error as Error).message}`);
    }
  }, [ipcHistory, setError, setStatus]);

  const onCopySelectedIpc = useCallback(async () => {
    if (!selectedIpcEvent) {
      setError("Select an IPC item first.");
      return;
    }
    try {
      await navigator.clipboard.writeText(JSON.stringify(selectedIpcEvent, null, 2));
      setStatus("IPC item copied.");
    } catch (error) {
      setError(`Copy failed: ${(error as Error).message}`);
    }
  }, [selectedIpcEvent, setError, setStatus]);

  const renderSessionButton = useCallback(
    (session: SessionInfo) => {
      const selected = session.session === selectedSession;
      return (
        <button
          key={session.session}
          type="button"
          className={`session-item ${selected ? "selected" : ""}`}
          onClick={() => setSelectedSession(session.session)}
        >
          <div className="session-row">
            <strong>{session.session}</strong>
            <span className={`state state-${session.state}`}>{session.state}</span>
          </div>
          <p>{session.snippet || "No output yet."}</p>
          <small>{session.cwd || "Unknown cwd"}</small>
        </button>
      );
    },
    [selectedSession],
  );

  const renderNavIcon = useCallback((tab: MainTab) => {
    if (tab === "sessions") {
      return (
        <svg viewBox="0 0 24 24" data-testid="nav-icon-sessions" aria-hidden="true">
          <rect x="3.5" y="4.5" width="17" height="15" rx="3" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path d="M7 9h4m-4 4h10" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      );
    }
    if (tab === "threads") {
      return (
        <svg viewBox="0 0 24 24" data-testid="nav-icon-threads" aria-hidden="true">
          <rect x="4" y="4.5" width="13" height="10" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path d="M8 9h5m-5 3h7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          <path d="M9 14.5 8 19l3.5-2.4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      );
    }
    if (tab === "remote") {
      return (
        <svg viewBox="0 0 24 24" data-testid="nav-icon-remote" aria-hidden="true">
          <rect x="3.5" y="5" width="17" height="11" rx="2.6" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path d="M9 19h6M12 16v3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          <path d="m8.5 10 3.2 2.2 4.3-3.2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      );
    }
    if (tab === "pair") {
      return (
        <svg viewBox="0 0 24 24" data-testid="nav-icon-pair" aria-hidden="true">
          <rect x="4" y="4" width="5" height="5" rx="1" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <rect x="15" y="4" width="5" height="5" rx="1" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <rect x="4" y="15" width="5" height="5" rx="1" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path d="M14 14h2v2h-2zm0 4h6m-2-4v6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      );
    }
    if (tab === "settings") {
      return (
        <svg viewBox="0 0 24 24" data-testid="nav-icon-settings" aria-hidden="true">
          <path d="M5 7h7m3 0h4M5 17h4m3 0h7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          <circle cx="14" cy="7" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <circle cx="9" cy="17" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.8" />
        </svg>
      );
    }
    return (
      <svg viewBox="0 0 24 24" data-testid="nav-icon-debug" aria-hidden="true">
        <path d="M6 8h12v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V8Z" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M9 8V5m6 3V5M4 11h2m12 0h2M10 13h4m-4 3h4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }, []);

  return (
    <div
      className={`app-shell${compactTranscript ? " compact-transcript" : ""}${touchComfortMode ? " touch-comfort" : ""}`}
    >
      <div className="app-bg" aria-hidden="true" />

      <header className="app-topbar">
        <div className="brand-cluster">
          <div className="brand-mark" aria-hidden="true">
            <img src="/icon.svg" alt="" />
          </div>
          <div>
            <p className="eyebrow">Codrex Remote</p>
            <h1>Mobile Control Surface</h1>
            <p className="subtitle">Native-feel controller for Codex sessions, thread tools, pairing, and remote desktop.</p>
          </div>
        </div>

        <div className="row top-actions">
          <button type="button" className="button soft compact" onClick={() => void onHardRefresh()}>
            Sync Now
          </button>
          <button
            type="button"
            className="button soft compact"
            data-testid="install-app-button"
            onClick={() => void onInstallCta()}
            disabled={installState === "installed" || installState === "prompting"}
          >
            {installButtonLabel}
          </button>
          <a className="button ghost" href="/?compact=1" target="_blank" rel="noreferrer">
            Legacy
          </a>
        </div>
        {showInstallGuide ? (
          <div className="install-guide" data-testid="install-guide">
            <strong>Install on Android</strong>
            <p>Open this page in Chrome, then tap menu and choose Add to Home screen or Install app.</p>
            <p className="small">If install is unavailable, use your Tailscale URL and refresh once.</p>
          </div>
        ) : null}
      </header>

      <section className="meta-strip">
        <div className="meta-chip">
          <span>Auth</span>
          <strong>{authSummary}</strong>
        </div>
        <div className="meta-chip">
          <span>Network</span>
          <strong>{networkSummary}</strong>
        </div>
        <div className="meta-chip">
          <span>Sessions</span>
          <strong>{sessionCountLabel}</strong>
        </div>
        <div className="meta-chip">
          <span>Debug</span>
          <strong>{runningRuns} running | {totalEvents} events</strong>
        </div>
        <div className="meta-chip">
          <span>Controls</span>
          <strong>{controlProfileSummary}</strong>
        </div>
        <div className="meta-chip">
          <span>Output</span>
          <strong>{outputFeedSummary}</strong>
        </div>
        <div className="meta-chip">
          <span>Connectivity</span>
          <strong>{connectivitySummary} | {installSummary}</strong>
        </div>
      </section>

      <section className="status-strip" aria-live="polite">
        <span className="status-pill">{statusMessage}</span>
        {errorMessage ? <span className="status-pill error">{errorMessage}</span> : null}
      </section>

      <main className="screen-shell" ref={screenShellRef} data-testid="screen-shell">
        {showSwipeHint ? (
          <div className="swipe-hint" data-testid="swipe-hint">
            <p>
              Tip: Swipe left or right anywhere in the content area to move between tabs.
            </p>
            <button
              type="button"
              className="button soft compact"
              data-testid="dismiss-swipe-hint"
              onClick={() => setShowSwipeHint(false)}
            >
              Got it
            </button>
          </div>
        ) : null}
        {activeTab === "sessions" ? (
          <section className={screenCardClassName} data-testid="tab-panel-sessions">
            <div className="card-head">
              <h2>Codex Sessions</h2>
              <div className="row">
                <span className="badge">Live polling</span>
                <span className="badge muted">{sessionCountLabel}</span>
              </div>
            </div>

            <div className="session-layout">
              <div className="session-list" role="list" aria-label="Codex sessions">
                <div className="row sticky-row">
                  <input
                    type="text"
                    data-testid="new-session-input"
                    value={newSessionName}
                    onChange={(event) => setNewSessionName(event.target.value)}
                    placeholder="New session name (optional)"
                  />
                  <input
                    type="text"
                    data-testid="new-session-cwd-input"
                    value={newSessionCwd}
                    onChange={(event) => setNewSessionCwd(event.target.value)}
                    placeholder="Session CWD (optional)"
                  />
                  <button
                    type="button"
                    className="button"
                    onClick={() => void onCreateSession()}
                    disabled={sessionBusy}
                  >
                    Create
                  </button>
                </div>

                <div className="row list-tools">
                  <input
                    type="text"
                    data-testid="session-search-input"
                    value={sessionQuery}
                    onChange={(event) => setSessionQuery(event.target.value)}
                    placeholder="Search sessions, project, cwd..."
                  />
                  <select
                    data-testid="session-project-filter"
                    value={sessionProjectFilter}
                    onChange={(event) => setSessionProjectFilter(event.target.value)}
                  >
                    <option value="all">All Projects</option>
                    {projectOptions.map((project) => (
                      <option key={project} value={project}>
                        {project}
                      </option>
                    ))}
                  </select>
                  <div className="segmented compact" role="group" aria-label="Session view">
                    <button
                      type="button"
                      className={`seg-item ${sessionViewMode === "grouped" ? "active" : ""}`}
                      onClick={() => setSessionViewMode("grouped")}
                    >
                      Grouped
                    </button>
                    <button
                      type="button"
                      className={`seg-item ${sessionViewMode === "flat" ? "active" : ""}`}
                      onClick={() => setSessionViewMode("flat")}
                    >
                      Flat
                    </button>
                  </div>
                </div>

                <p className="small">{visibleSessionCountLabel}</p>

                {sessionsLoading ? <p className="small">Loading sessions...</p> : null}
                {!sessionsLoading && sessions.length === 0 ? (
                  <div className="empty-state panel-empty">
                    <h3>No sessions yet</h3>
                    <p>Create one to start interacting with Codex from mobile.</p>
                  </div>
                ) : null}
                {!sessionsLoading && sessions.length > 0 && filteredSessions.length === 0 ? (
                  <div className="empty-state panel-empty">
                    <h3>No matching sessions</h3>
                    <p>Adjust search text or project filter.</p>
                  </div>
                ) : null}

                {sessionViewMode === "grouped"
                  ? groupedSessions.map((group) => (
                      <div key={group.project} className="session-group">
                        <div className="session-group-head">
                          <strong>{group.project}</strong>
                          <span className="badge muted">{group.items.length}</span>
                        </div>
                        {group.items.map((session) => renderSessionButton(session))}
                      </div>
                    ))
                  : filteredSessions.map((session) => renderSessionButton(session))}
              </div>

              <div className={`session-detail ${consoleFocusMode ? "console-focus-mode" : ""}`} data-testid="session-detail">
                {!selectedSessionInfo ? (
                  <div className="empty-state">
                    <h3>Select or create a session</h3>
                    <p>Screen output and prompt composer appear here.</p>
                  </div>
                ) : (
                  <>
                    <div className="detail-head">
                      <div>
                        <h3>{selectedSessionInfo.session}</h3>
                        <p className="small">
                          State: {selectedSessionInfo.state} | Command: {selectedSessionInfo.current_command || "(none)"}
                        </p>
                        <p className="small">
                          Model: <strong>{selectedSessionInfo.model || selectedModel}</strong> | Reasoning:{" "}
                          <strong>{selectedSessionInfo.reasoning_effort || selectedReasoningEffort}</strong>
                        </p>
                        <p className="small">
                          Refresh updates pane output. Interrupt sends Esc (soft stop), Ctrl+C sends terminal interrupt,
                          and Close ends the tmux session.
                        </p>
                      </div>
                    </div>

                    <div className="row output-controls">
                      <span className={`badge ${outputFeedState === "live" ? "" : "muted"}`}>
                        Output: {outputFeedState}
                      </span>
                      <button
                        type="button"
                        className="button soft compact"
                        data-testid="toggle-live-output"
                        onClick={() => setStreamEnabled((current) => !current)}
                      >
                        {streamEnabled ? "Live On" : "Live Off"}
                      </button>
                      <label className="field inline">
                        <span>Profile</span>
                        <select
                          data-testid="stream-profile-select"
                          value={streamProfile}
                          onChange={(event) => setStreamProfile(parseStreamProfile(event.target.value))}
                          disabled={!streamEnabled}
                        >
                          <option value="fast">Fast</option>
                          <option value="balanced">Balanced</option>
                          <option value="battery">Battery</option>
                        </select>
                      </label>
                      <button
                        type="button"
                        className="button soft compact"
                        data-testid="toggle-console-focus"
                        onClick={() => setConsoleFocusMode((current) => !current)}
                      >
                        {focusButtonLabel}
                      </button>
                    </div>

                    <div className="prompt-composer">
                      <label className="field">
                        <span>Prompt Composer</span>
                        <div className="composer-input-wrap">
                          <textarea
                            value={promptText}
                            onChange={(event) => setPromptText(event.target.value)}
                            rows={5}
                            placeholder="Type your prompt. Codrex will send Enter + Enter to submit."
                          />
                          <button
                            type="button"
                            className="composer-send-btn"
                            data-testid="composer-send-prompt"
                            aria-label={sessionBusy ? "Sending prompt" : "Send prompt"}
                            onClick={() => void onSendPrompt()}
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

                    <div className="quick-open-card">
                      <h3>Image Upload</h3>
                      <p className="small">Upload an image, then choose how to deliver it into your active Codex workflow.</p>
                      <div className="row">
                        <input
                          type="file"
                          accept="image/*"
                          onChange={(event) => setSessionImageFile(event.target.files?.[0] || null)}
                        />
                        <input
                          type="text"
                          value={sessionImagePrompt}
                          onChange={(event) => setSessionImagePrompt(event.target.value)}
                          placeholder="Optional instruction for this image"
                        />
                        <label className="field inline">
                          <span>Mode</span>
                          <select
                            value={sessionImageDeliveryMode}
                            onChange={(event) => setSessionImageDeliveryMode(parseSessionImageDeliveryMode(event.target.value))}
                          >
                            <option value="insert_path">Insert path in composer</option>
                            <option value="desktop_clipboard">Paste image (Ctrl+V)</option>
                            <option value="session_path">Send path as message</option>
                          </select>
                        </label>
                        <button type="button" className="button soft compact" onClick={() => void onSendSessionImage()} disabled={sessionBusy || !sessionImageFile}>
                          Send Image
                        </button>
                      </div>
                      <p className="small">
                        {sessionImageDeliveryMode === "insert_path"
                          ? "Inserts the local image path into Codex composer without submitting; continue typing and press Send."
                          : sessionImageDeliveryMode === "desktop_clipboard"
                            ? "Requires Codex input focused on laptop; copies image to clipboard and sends Ctrl+V."
                            : "Sends a path message directly to session transcript and submits immediately."}
                      </p>
                    </div>

                    {!telegramStatusLoading && !telegramConfigured ? (
                      <div className="quick-open-card" data-testid="shared-files-card">
                        <h3>Shared Files Inbox</h3>
                        <p className="small">
                          Deterministic route: send `codrex-send` command instead of relying on model memory.
                        </p>
                        <div className="row">
                          <input
                            type="text"
                            data-testid="share-path-input"
                            value={sharePathInput}
                            onChange={(event) => setSharePathInput(event.target.value)}
                            placeholder="/home/megha/codrex-work/output/result.png"
                          />
                          <input
                            type="text"
                            data-testid="share-title-input"
                            value={shareTitleInput}
                            onChange={(event) => setShareTitleInput(event.target.value)}
                            placeholder="Optional title"
                          />
                          <label className="field inline">
                            <span>Expires</span>
                            <select
                              data-testid="share-expiry-select"
                              value={shareExpiresHours}
                              onChange={(event) => setShareExpiresHours(event.target.value)}
                            >
                              <option value="1">1h</option>
                              <option value="24">24h</option>
                              <option value="72">72h</option>
                              <option value="168">7d</option>
                            </select>
                          </label>
                        </div>
                        <div className="row">
                          <button type="button" className="button soft compact" onClick={() => void onCopyShareCommand()}>
                            Copy `codrex-send`
                          </button>
                          <button type="button" className="button soft compact" onClick={() => void onCreateSharedFile()} disabled={shareBusy || !sharePathInput.trim()}>
                            Share Now
                          </button>
                          <button type="button" className="button soft compact" onClick={() => void refreshSharedFiles()}>
                            Refresh Inbox
                          </button>
                        </div>
                        <p className="small">
                          Example: <code>codrex-send "/home/megha/codrex-work/output/result.png" --title "Result" --expires 24</code>
                        </p>
                        {sharesLoading ? <p className="small">Loading shared files...</p> : null}
                        {!sharesLoading && sharedFiles.length === 0 ? (
                          <div className="empty-state panel-empty">
                            <h3>No shared files yet</h3>
                            <p>Run `codrex-send` from prompt composer or use Share Now above.</p>
                          </div>
                        ) : null}
                        {!sharesLoading && sharedFiles.length > 0 ? (
                          <div className="run-list" role="list" aria-label="Shared files inbox">
                            {sharedFiles.map((item) => (
                              <div key={item.id} className="run-item">
                                <div className="session-row">
                                  <strong>{item.title || item.file_name}</strong>
                                  <span className="badge muted">{formatFileSize(item.size_bytes)}</span>
                                </div>
                                <p>{item.file_name}</p>
                                <small>
                                  Added {formatClock(item.created_at)} | Expires {new Date(item.expires_at).toLocaleString()}
                                </small>
                                <div className="row">
                                  <button
                                    type="button"
                                    className="button soft compact"
                                    onClick={() => window.open(item.download_url, "_blank", "noopener,noreferrer")}
                                  >
                                    Open
                                  </button>
                                  <button type="button" className="button soft compact" onClick={() => void onSendSharedToTelegram(item)} disabled={shareBusy}>
                                    Send Telegram
                                  </button>
                                  <button type="button" className="button soft compact" onClick={() => void onCopyShareLink(item)}>
                                    Copy Link
                                  </button>
                                  <button type="button" className="button danger compact" onClick={() => void onDeleteSharedFile(item.id)} disabled={shareBusy}>
                                    Remove
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ) : null}

                    <label className="field">
                      <span>Live screen output</span>
                      <pre ref={sessionOutputRef} className="console">{screenText || "(No screen output captured yet)"}</pre>
                    </label>

                    <div className="session-action-dock" data-testid="session-action-dock">
                      <button
                        type="button"
                        className="button soft compact"
                        data-short="REF"
                        onClick={() => void refreshScreen(selectedSessionInfo.session)}
                      >
                        <span className="btn-text">Refresh</span>
                      </button>
                      <button type="button" className="button soft compact" data-short="ENT" onClick={() => void onSendEnter()} disabled={sessionBusy}>
                        <span className="btn-text">Enter</span>
                      </button>
                      <button type="button" className="button warn compact" data-short="INT" onClick={() => void onInterrupt()} disabled={sessionBusy}>
                        <span className="btn-text">Interrupt</span>
                      </button>
                      <button type="button" className="button danger compact" data-short="C^C" onClick={() => void onCtrlC()} disabled={sessionBusy}>
                        <span className="btn-text">Ctrl+C</span>
                      </button>
                      <button type="button" className="button danger compact" data-short="CLS" onClick={() => void onCloseSession()} disabled={sessionBusy}>
                        <span className="btn-text">Close</span>
                      </button>
                      <button type="button" className="button soft compact" data-short={consoleFocusMode ? "EXIT" : "FOC"} onClick={() => setConsoleFocusMode((current) => !current)}>
                        <span className="btn-text">{consoleFocusMode ? "Exit Focus" : "Focus"}</span>
                      </button>
                    </div>

                    <div className="quick-open-card">
                      <h3>Model Selection</h3>
                      <p className="small">Defaults for new sessions. Apply to current session only when you choose.</p>
                      <div className="row">
                        <label className="field inline">
                          <span>Model</span>
                          <select
                            data-testid="session-model-select"
                            value={selectedModel}
                            onChange={(event) => setSelectedModel(event.target.value)}
                          >
                            {modelOptions.map((model) => (
                              <option key={model} value={model}>
                                {model}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="field inline">
                          <span>Reasoning</span>
                          <select
                            data-testid="session-reasoning-select"
                            value={selectedReasoningEffort}
                            onChange={(event) => setSelectedReasoningEffort(parseReasoningEffort(event.target.value))}
                          >
                            {sessionAllowedReasoningOptions.map((effort) => (
                              <option key={effort} value={effort}>
                                {effort}
                              </option>
                            ))}
                          </select>
                        </label>
                        <button
                          type="button"
                          className="button soft compact"
                          onClick={() => void onApplySessionProfile()}
                          disabled={sessionBusy || !selectedSession}
                        >
                          Apply to Current Session
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>
          </section>
        ) : null}

        {activeTab === "threads" ? (
          <section className={screenCardClassName} data-testid="tab-panel-threads">
            <div className="card-head">
              <h2>Shell Sessions</h2>
              <div className="row">
                <span className="badge">tmux monitor</span>
                <span className="badge muted">tmux: {tmuxHealthState}</span>
              </div>
            </div>

            <div className="debug-layout full-width">
              <div className="debug-column">
                <div className="debug-block">
                  <h3>Tmux Session Monitor</h3>
                  <p className="small">
                    Track tmux panes and run Ubuntu, PowerShell, or CMD commands from one monitor.
                  </p>
                  <div className="row">
                    <button type="button" className="button soft compact" onClick={() => void refreshTmuxState()}>
                      Refresh
                    </button>
                    <span className="small">Sessions: {tmuxSessions.length}</span>
                    <span className="small">Panes: {threadTmuxPanes.length}</span>
                  </div>
                  <div className="row">
                    <input
                      type="text"
                      value={tmuxSessionName}
                      onChange={(event) => setTmuxSessionName(event.target.value)}
                      placeholder="New tmux session name (required for shell profile)"
                    />
                    <select value={tmuxShellProfile} onChange={(event) => setTmuxShellProfile(event.target.value as TmuxShellProfile)}>
                      <option value="ubuntu">Ubuntu shell</option>
                      <option value="powershell">PowerShell</option>
                      <option value="cmd">Command Prompt</option>
                    </select>
                    <button type="button" className="button" onClick={() => void onCreateTmuxSession()} disabled={tmuxBusy}>
                      Create
                    </button>
                  </div>
                  <label className="field">
                    <span>Pane</span>
                    <select
                      value={selectedTmuxPane}
                      onChange={(event) => setSelectedTmuxPane(event.target.value)}
                    >
                      <option value="">Select pane</option>
                      {threadTmuxPanes.map((pane) => (
                        <option key={pane.pane_id} value={pane.pane_id}>
                          {pane.session} | {pane.pane_id} | {pane.current_command}
                        </option>
                      ))}
                    </select>
                  </label>
                  {threadTmuxPanes.length === 0 ? (
                    <p className="small">No shell-only panes yet. Codex panes are hidden in this tab.</p>
                  ) : null}
                  <div className="row">
                    <button type="button" className="button soft compact" onClick={() => void refreshTmuxScreen(selectedTmuxPane)} disabled={!selectedTmuxPane}>
                      Pull Pane
                    </button>
                    <button type="button" className="button warn compact" onClick={() => void onInterruptTmuxPane()} disabled={tmuxBusy || !selectedTmuxPane}>
                      Interrupt
                    </button>
                    <button type="button" className="button danger compact" onClick={() => void onCloseTmuxSession()} disabled={tmuxBusy || !selectedTmuxPaneInfo}>
                      Close Session
                    </button>
                  </div>
                  <div className="row">
                    <input
                      type="text"
                      value={tmuxPrompt}
                      onChange={(event) => setTmuxPrompt(event.target.value)}
                      placeholder="Run command in selected pane"
                    />
                    <button type="button" className="button" onClick={() => void onSendTmuxPrompt()} disabled={tmuxBusy || !selectedTmuxPane}>
                      Send
                    </button>
                  </div>
                  <pre className="console">{tmuxScreenText || "(No pane output yet)"}</pre>
                </div>
              </div>

              {showLegacyThreadTools ? (
                <div className="debug-column">
                  <div className="debug-block">
                    <h3>One-shot `codex exec`</h3>
                    <p className="small">Run one-shot jobs and inspect output in Debug tab.</p>
                    <textarea
                      value={execPrompt}
                      onChange={(event) => setExecPrompt(event.target.value)}
                      rows={4}
                      placeholder="Describe a one-shot task for codex exec"
                    />
                    <button type="button" className="button" onClick={() => void onRunExec()} disabled={execBusy || !execPrompt.trim()}>
                      {execBusy ? "Starting..." : "Run Exec"}
                    </button>
                  </div>

                  <div className="debug-block">
                    <h3>WSL File Bridge</h3>
                    <div className="row">
                      <input
                        type="text"
                        value={wslDownloadPath}
                        onChange={(event) => setWslDownloadPath(event.target.value)}
                        placeholder="Relative file path to download"
                      />
                      <button type="button" className="button soft compact" onClick={onDownloadWslFile}>
                        Download
                      </button>
                    </div>
                    <div className="row">
                      <input type="file" onChange={(event) => setWslUploadFile(event.target.files?.[0] || null)} />
                      <input
                        type="text"
                        value={wslUploadDest}
                        onChange={(event) => setWslUploadDest(event.target.value)}
                        placeholder="Upload destination path (optional)"
                      />
                      <button type="button" className="button soft compact" onClick={() => void onUploadWslFile()} disabled={!wslUploadFile}>
                        Upload
                      </button>
                    </div>
                    {fileStatus ? <p className="small">{fileStatus}</p> : null}
                  </div>
                </div>
              ) : null}
            </div>

            {showLegacyThreadTools ? (
              <div className="quick-open-card">
                <h3>Codex Transcript Threads</h3>
                <p className="small">
                  Legacy transcript tools. Shell monitor above is the primary workspace for this tab.
                </p>
              </div>
            ) : null}

            {showLegacyThreadTools ? (
              <div className="session-layout">
              <div className="session-list">
                <div className="quick-open-card">
                  <h3>Create Thread</h3>
                  <label className="field">
                    <span>Session</span>
                    <select
                      data-testid="thread-session-input-select"
                      value={threadSessionInput}
                      onChange={(event) => setThreadSessionInput(event.target.value)}
                    >
                      <option value="">Select session</option>
                      {sessions.map((session) => (
                        <option key={session.session} value={session.session}>
                          {session.session}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Thread Title (optional)</span>
                    <input
                      type="text"
                      data-testid="thread-title-input"
                      value={threadTitleInput}
                      onChange={(event) => setThreadTitleInput(event.target.value)}
                      placeholder="Bug triage / release prep / TODOs"
                    />
                  </label>
                  <div className="row">
                    <button type="button" className="button" onClick={onCreateThread} disabled={!threadSessionInput}>
                      New Thread
                    </button>
                    <button type="button" className="button soft compact" onClick={onRenameThread} disabled={!activeThread || !threadTitleInput.trim()}>
                      Rename
                    </button>
                    <button type="button" className="button danger compact" onClick={onDeleteThread} disabled={!activeThread}>
                      Delete
                    </button>
                  </div>
                </div>
                <label className="field">
                  <span>Search Threads</span>
                  <input
                    type="text"
                    value={threadSearch}
                    onChange={(event) => setThreadSearch(event.target.value)}
                    placeholder="Search by title or session"
                  />
                </label>
                <div className="row">
                  <button
                    type="button"
                    className="button soft compact"
                    onClick={() => {
                      if (activeThread?.session) {
                        setSelectedSession(activeThread.session);
                        setActiveTab("sessions");
                      }
                    }}
                    disabled={!activeThread}
                  >
                    Open Session
                  </button>
                  <button
                    type="button"
                    className="button soft compact"
                    onClick={() => void onCaptureThreadSnapshot()}
                    disabled={!activeThread && !threadSessionInput}
                  >
                    Capture Snapshot
                  </button>
                </div>
                {filteredThreads.length === 0 ? (
                  <div className="empty-state panel-empty">
                    <h3>No threads yet</h3>
                    <p>Create your first thread to start a dedicated transcript.</p>
                  </div>
                ) : (
                  <div className="run-list" role="list" aria-label="Threads list">
                    {filteredThreads.map((thread) => {
                      const selected = thread.id === activeThreadId;
                      const messageCount = threadMessages[thread.id]?.length || 0;
                      return (
                        <button
                          key={thread.id}
                          type="button"
                          className={`run-item ${selected ? "selected" : ""}`}
                          data-testid={`thread-item-${thread.id}`}
                          onClick={() => {
                            setActiveThreadId(thread.id);
                            setThreadSessionInput(thread.session);
                            setThreadTitleInput(thread.title);
                          }}
                        >
                          <div className="session-row">
                            <strong>{thread.title}</strong>
                            <span className="badge muted">{messageCount}</span>
                          </div>
                          <p>{thread.session}</p>
                          <small>Updated {formatClock(thread.updatedAt)}</small>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="session-detail">
                {!activeThread ? (
                  <div className="empty-state">
                    <h3>Select or create a thread</h3>
                    <p>Each thread keeps a dedicated transcript tied to one Codex session.</p>
                  </div>
                ) : (
                  <>
                    <div className="detail-head">
                      <div>
                        <h3>{activeThread.title}</h3>
                        <p className="small">
                          Session: <strong>{activeThread.session}</strong> | Updated {formatClock(activeThread.updatedAt)}
                        </p>
                      </div>
                      <span className="badge muted">{threadSessionMessages.length} messages</span>
                    </div>
                    {threadSessionMessages.length === 0 ? (
                      <div className="empty-state panel-empty">
                        <h3>No messages yet</h3>
                        <p>Send a message to start this thread.</p>
                      </div>
                    ) : (
                      <div className="event-list" role="list" aria-label="Thread transcript">
                        {threadSessionMessages.map((msg) => (
                          <div
                            key={msg.id}
                            className={`event-item ${msg.role === "assistant" ? "thread-item-assistant" : "thread-item-user"}`}
                          >
                            <div className="session-row">
                              <strong>{msg.role.toUpperCase()}</strong>
                              <span className="small">{formatClock(msg.at)}</span>
                            </div>
                            <p>{msg.text}</p>
                          </div>
                        ))}
                      </div>
                    )}
                    <label className="field">
                      <span>Message</span>
                      <textarea
                        data-testid="thread-prompt-input"
                        value={threadPrompt}
                        onChange={(event) => setThreadPrompt(event.target.value)}
                        rows={6}
                        placeholder="Write a thread message for Codex."
                      />
                    </label>
                    <div className="row">
                      <button type="button" className="button" onClick={() => void onSendThreadPrompt()} disabled={threadBusy || !activeThread}>
                        {threadBusy ? "Sending..." : "Send Message"}
                      </button>
                      <button type="button" className="button soft compact" onClick={() => setThreadPrompt("")} disabled={threadBusy || !threadPrompt.trim()}>
                        Clear
                      </button>
                      <button
                        type="button"
                        className="button soft compact"
                        onClick={() => {
                          if (activeThread.session) {
                            setSelectedSession(activeThread.session);
                          }
                          setActiveTab("sessions");
                        }}
                        disabled={!activeThread.session}
                      >
                        Open Live Console
                      </button>
                    </div>
                    <label className="field">
                      <span>Live Session Snapshot</span>
                      <pre className="console">
                        {activeThread.session && activeThread.session === selectedSession
                          ? screenText || "(No live output yet)"
                          : "Open this session in Sessions tab to stream live output."}
                      </pre>
                    </label>
                  </>
                )}
              </div>
              </div>
            ) : null}
          </section>
        ) : null}

        {activeTab === "remote" ? (
          <section className={screenCardClassName} data-testid="tab-panel-remote">
            <div className="card-head">
              <h2>Remote Control</h2>
              <div className="row">
                <span className="badge">desktop + capture</span>
                <span className="badge muted">{desktopEnabled ? "desktop: on" : "desktop: off"}</span>
              </div>
            </div>

            <div className="debug-layout full-width">
              <div className="debug-column">
                <div className="debug-block">
                  <h3>Desktop Remote</h3>
                  <div className="row">
                    <button type="button" className={`button ${desktopEnabled ? "warn" : ""}`} onClick={() => void onToggleDesktopMode()}>
                      {desktopEnabled ? "Disable Desktop" : "Enable Desktop"}
                    </button>
                    <span className="small">
                      {desktopInfo?.width && desktopInfo?.height
                        ? `${desktopInfo.width}x${desktopInfo.height}`
                        : "Desktop unavailable"}
                    </span>
                  </div>
                  <label className="field">
                    <span>Stream Profile</span>
                    <select
                      value={desktopProfile}
                      onChange={(event) => setDesktopProfile(event.target.value as DesktopStreamProfile)}
                    >
                      <option value="responsive">Responsive</option>
                      <option value="balanced">Balanced</option>
                      <option value="saver">Saver</option>
                      <option value="ultra">Ultra (B/W, low data)</option>
                      <option value="extreme">Extreme (very low bandwidth)</option>
                    </select>
                  </label>
                  <p className="small">
                    Current profile:{" "}
                    <strong>
                      {DESKTOP_PROFILE_STREAM[desktopProfile].fps}fps / scale x{DESKTOP_PROFILE_STREAM[desktopProfile].scale}
                      {DESKTOP_PROFILE_STREAM[desktopProfile].bw ? " / grayscale" : ""}
                    </strong>
                  </p>
                  <p className="small">{desktopStatus || "Desktop controls are available only on Windows host."}</p>
                  <div className="pair-qr-wrap">
                    <img
                      ref={desktopFrameRef}
                      className="desktop-frame"
                      src={desktopEnabled ? desktopStreamUrl : desktopShotUrl}
                      alt="Desktop stream"
                      onClick={(event) => void onDesktopFrameTap(event)}
                    />
                  </div>
                  <p className="small">Tap/click the stream to focus target window before sending text or keys.</p>
                  <div className="row remote-mouse-controls">
                    <button type="button" className="button soft compact" data-short="L" onClick={() => void onDesktopClick("left")} disabled={desktopInteractionDisabled}>
                      <span className="btn-text">Left Click</span>
                    </button>
                    <button type="button" className="button soft compact" data-short="R" onClick={() => void onDesktopClick("right")} disabled={desktopInteractionDisabled}>
                      <span className="btn-text">Right Click</span>
                    </button>
                    <button type="button" className="button soft compact" data-short="2X" onClick={() => void onDesktopClick("left", true)} disabled={desktopInteractionDisabled}>
                      <span className="btn-text">Double</span>
                    </button>
                    <button type="button" className="button soft compact" data-short="UP" onClick={() => void onDesktopScroll(-240)} disabled={desktopInteractionDisabled}>
                      <span className="btn-text">Scroll Up</span>
                    </button>
                    <button type="button" className="button soft compact" data-short="DN" onClick={() => void onDesktopScroll(240)} disabled={desktopInteractionDisabled}>
                      <span className="btn-text">Scroll Down</span>
                    </button>
                  </div>
                  <div className="row remote-text-controls">
                    <input
                      type="text"
                      value={desktopTextInput}
                      onChange={(event) => setDesktopTextInput(event.target.value)}
                      placeholder="Type text on desktop"
                      disabled={desktopInteractionDisabled}
                    />
                    <button type="button" className="button soft compact" data-short="SEND" onClick={() => void onDesktopSendText()} disabled={desktopInteractionDisabled || !desktopTextInput}>
                      <span className="btn-text">Send Text</span>
                    </button>
                    <button type="button" className="button soft compact" data-short="PASTE" onClick={() => void onDesktopPasteClipboard()} disabled={desktopInteractionDisabled}>
                      <span className="btn-text">Paste Clipboard</span>
                    </button>
                    <button
                      type="button"
                      className="button soft compact"
                      data-short="TG"
                      onClick={() => void onSendRemoteTextToTelegram()}
                      disabled={!telegramConfigured || telegramTextBusy || !desktopTextInput.trim()}
                    >
                      <span className="btn-text">Send Telegram</span>
                    </button>
                  </div>
                  <div className="row remote-key-controls">
                    <select value={desktopKeyInput} onChange={(event) => setDesktopKeyInput(event.target.value)} disabled={desktopInteractionDisabled}>
                      <option value="enter">Enter</option>
                      <option value="backspace">Backspace</option>
                      <option value="delete">Delete</option>
                      <option value="esc">Esc</option>
                      <option value="tab">Tab</option>
                      <option value="up">Up</option>
                      <option value="down">Down</option>
                      <option value="left">Left</option>
                      <option value="right">Right</option>
                      <option value="alt+tab">Alt+Tab</option>
                      <option value="ctrl+a">Ctrl+A</option>
                      <option value="ctrl+c">Ctrl+C</option>
                      <option value="ctrl+v">Ctrl+V</option>
                    </select>
                    <button type="button" className="button soft compact" data-short="KEY" onClick={() => void onDesktopSendKey()} disabled={desktopInteractionDisabled}>
                      <span className="btn-text">Send Key</span>
                    </button>
                    <button type="button" className="button soft compact" data-short="SHOT" onClick={() => onRefreshDesktopShot()}>
                      <span className="btn-text">Refresh Shot</span>
                    </button>
                  </div>
                </div>

                <div className="debug-block">
                  <h3>Screenshot Capture</h3>
                  <p className="small">Capture one desktop frame using current stream profile (including low-data mode).</p>
                  <button type="button" className="button soft compact" onClick={onCaptureLatestShot}>
                    Capture Latest
                  </button>
                  {latestCaptureUrl ? (
                    <div className="pair-qr-wrap">
                      <img className="desktop-frame" src={latestCaptureUrl} alt="Latest screenshot" />
                    </div>
                  ) : (
                    <div className="empty-state panel-empty">
                      <h3>No capture yet</h3>
                      <p>Tap capture to preview `/shot` output here.</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </section>
        ) : null}

        {activeTab === "pair" ? (
          <section className={screenCardClassName} data-testid="tab-panel-pair">
            <div className="card-head">
              <h2>Pair Device</h2>
              <div className="row">
                <span className="badge">QR Flow</span>
                <span className="badge muted">{prettyRouteLabel(routeHint)}</span>
              </div>
            </div>

            <div className="pair-layout">
              <div className="stack">
                <p className="small">
                  Keep using Tailscale + token auth. QR exchange only grants this device the existing backend token context.
                </p>

                <label className="field">
                  <span>Route Hint</span>
                  <select
                    data-testid="pair-route-hint-select"
                    value={routeHint}
                    onChange={(event) => onRouteHintChange(event.target.value as RouteHint)}
                  >
                    <option value="lan">{prettyRouteLabel("lan")}</option>
                    <option value="tailscale">{prettyRouteLabel("tailscale")}</option>
                    <option value="current">{prettyRouteLabel("current")}</option>
                  </select>
                </label>

                <label className="field">
                  <span>Controller Base URL</span>
                  <input
                    type="text"
                    value={controllerBase}
                    onChange={(event) => setControllerBase(event.target.value)}
                    placeholder="http://192.168.x.x:8787"
                  />
                </label>

                <p className="small">
                  LAN: <strong>{netInfo?.lan_ip || "n/a"}</strong> | Tailscale: <strong>{netInfo?.tailscale_ip || "n/a"}</strong>
                </p>
                {tailscaleRouteUnavailable ? (
                  <p className="small warn">
                    Tailscale route is selected but no Tailscale IP is detected.
                  </p>
                ) : null}

                <div className="row">
                  <button type="button" className="button" onClick={() => void onGeneratePairing()} disabled={pairBusy}>
                    {pairBusy ? "Generating..." : "Generate QR"}
                  </button>
                  <button type="button" className="button soft compact" onClick={() => void refreshNet()}>
                    Refresh Routes
                  </button>
                  <button
                    type="button"
                    className="button soft compact"
                    onClick={() => void onPairExchange()}
                    disabled={pairBusy || !pairCode}
                  >
                    Exchange Here
                  </button>
                </div>
              </div>

              <div className="pair-preview">
                {pairCode ? (
                  <>
                    <p className="small">
                      Code: <code>{pairCode}</code>
                      {pairExpiry ? ` (expires in ${pairExpiry}s)` : ""}
                    </p>
                    <textarea data-testid="pair-link-text" readOnly value={pairLink} rows={3} />
                    <div className="row">
                      <button type="button" className="button soft compact" onClick={() => void onCopyPairLink()}>
                        Copy Link
                      </button>
                      <button type="button" className="button soft compact" onClick={onOpenPairLink}>
                        Open Link
                      </button>
                    </div>
                    {pairQrUrl ? (
                      <div className="pair-qr-wrap">
                        <img className="qr" src={pairQrUrl} alt="Pairing QR" />
                      </div>
                    ) : null}
                  </>
                ) : (
                  <div className="empty-state panel-empty">
                    <h3>No code generated</h3>
                    <p>Generate a pairing code to show a QR image for phone/tablet sign-in.</p>
                  </div>
                )}
              </div>
            </div>
          </section>
        ) : null}

        {activeTab === "settings" ? (
          <section className={screenCardClassName} data-testid="tab-panel-settings">
            <div className="card-head">
              <h2>Security & Settings</h2>
              {authLoading ? <span className="badge">Checking...</span> : <span className="badge">Auth</span>}
            </div>

            {!auth ? (
              <p className="small">Loading auth state...</p>
            ) : (
              <div className="settings-layout">
                <div className="stack">
                  <p className="small">
                    Required: <strong>{auth.auth_required ? "Yes" : "No"}</strong> | Authenticated:{" "}
                    <strong>{auth.authenticated ? "Yes" : "No"}</strong>
                  </p>

                  {auth.auth_required && !auth.authenticated ? (
                    <>
                      <div className="quick-open-card">
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

                  <div className="quick-open-card">
                    <h3>Android Usability</h3>
                    <p className="small">Tune touch targets and transcript density for phone/tablet usage.</p>
                    <div className="row">
                      <button
                        type="button"
                        className="button soft compact"
                        data-testid="toggle-touch-comfort"
                        onClick={() => setTouchComfortMode((current) => !current)}
                      >
                        Touch Comfort: {touchComfortMode ? "On" : "Off"}
                      </button>
                      <button
                        type="button"
                        className="button soft compact"
                        data-testid="toggle-compact-transcript"
                        onClick={() => setCompactTranscript((current) => !current)}
                      >
                        Compact Transcript: {compactTranscript ? "On" : "Off"}
                      </button>
                    </div>
                  </div>

                  <div className="quick-open-card">
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
                </div>

                <div className="stack">
                  <div className="quick-open-card settings-note">
                    <h3>Network Diagnostics</h3>
                    <p className="small">
                      Current route: <strong>{controllerRouteSummary}</strong>
                    </p>
                    <p className="small">{controllerRouteAdvice}</p>
                    <p className="small">Controller base: <code>{controllerBase || "(not set)"}</code></p>
                    <p className="small">Route hint: <strong>{prettyRouteLabel(routeHint)}</strong></p>
                    <p className="small">LAN: <strong>{netInfo?.lan_ip || "n/a"}</strong></p>
                    <p className="small">Tailscale: <strong>{netInfo?.tailscale_ip || "n/a"}</strong></p>
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

                  <div className="empty-state settings-note">
                    <h3>Remote safety checklist</h3>
                    <p>Use Tailscale/private network and keep token auth enabled on backend.</p>
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
        ) : null}

        {activeTab === "debug" ? (
          <section className={screenCardClassName} data-testid="tab-panel-debug">
            <div className="card-head">
              <h2>Debug Timeline</h2>
              <div className="row">
                <span className="badge">Events {totalEvents}</span>
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
                        <button
                          key={run.id}
                          type="button"
                          className={`run-item ${selected ? "selected" : ""}`}
                          onClick={() => setSelectedRunId(run.id)}
                        >
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
                            <span className={`badge ${evt.level === "error" ? "" : "muted"}`}>
                              {evt.level === "error" ? "Error" : "Info"}
                            </span>
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
                    <input
                      type="text"
                      value={ipcSearch}
                      onChange={(event) => setIpcSearch(event.target.value)}
                      placeholder="Search path, detail, payload..."
                    />
                    <button type="button" className="button soft compact" onClick={onExportIpcHistory} disabled={ipcHistory.length === 0}>
                      Export JSON
                    </button>
                    <button type="button" className="button soft compact" onClick={onClearIpcHistory} disabled={ipcHistory.length === 0}>
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
                        Status: <strong>{selectedRun.status}</strong> | Exit: <strong>{selectedRun.exit_code ?? "-"}</strong> | Duration:{" "}
                        <strong>{selectedRun.duration_s ?? "-"}</strong>
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
        ) : null}
      </main>

      <nav className="bottom-nav" aria-label="Primary navigation">
        <button
          type="button"
          data-testid="tab-sessions"
          className={`nav-item ${activeTab === "sessions" ? "active" : ""}`}
          onClick={() => setActiveTab("sessions")}
        >
          <span className="nav-icon">{renderNavIcon("sessions")}</span>
          <span className="nav-label">Sessions</span>
        </button>
        <button
          type="button"
          data-testid="tab-threads"
          className={`nav-item ${activeTab === "threads" ? "active" : ""}`}
          onClick={() => setActiveTab("threads")}
        >
          <span className="nav-icon">{renderNavIcon("threads")}</span>
          <span className="nav-label">Threads</span>
        </button>
        <button
          type="button"
          data-testid="tab-remote"
          className={`nav-item ${activeTab === "remote" ? "active" : ""}`}
          onClick={() => setActiveTab("remote")}
        >
          <span className="nav-icon">{renderNavIcon("remote")}</span>
          <span className="nav-label">Remote</span>
        </button>
        <button
          type="button"
          data-testid="tab-pair"
          className={`nav-item ${activeTab === "pair" ? "active" : ""}`}
          onClick={() => setActiveTab("pair")}
        >
          <span className="nav-icon">{renderNavIcon("pair")}</span>
          <span className="nav-label">Pair</span>
        </button>
        <button
          type="button"
          data-testid="tab-settings"
          className={`nav-item ${activeTab === "settings" ? "active" : ""}`}
          onClick={() => setActiveTab("settings")}
        >
          <span className="nav-icon">{renderNavIcon("settings")}</span>
          <span className="nav-label">Settings</span>
        </button>
        <button
          type="button"
          data-testid="tab-debug"
          className={`nav-item ${activeTab === "debug" ? "active" : ""}`}
          onClick={() => setActiveTab("debug")}
        >
          <span className="nav-icon">{renderNavIcon("debug")}</span>
          <span className="nav-label">Debug</span>
        </button>
      </nav>
    </div>
  );
}
