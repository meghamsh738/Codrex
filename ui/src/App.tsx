import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  addThreadRecordMessage,
  appendLatestSessionNotes,
  buildDesktopShotUrl,
  buildDesktopStreamUrl,
  buildPairConsumeUrl,
  buildPairQrPngUrl,
  buildSessionStreamUrl,
  buildSuggestedControllerUrl,
  buildWslDownloadUrl,
  bootstrapLocalAuth,
  closeSession,
  closeTmuxSession,
  createThreadRecord,
  createSessionWithOptions,
  createTmuxSession,
  createPairCode,
  desktopMove,
  detectControllerPort,
  deleteThreadRecord,
  desktopClick,
  desktopScroll,
  desktopSendKey,
  desktopSendText,
  ctrlcSession,
  exchangePairCode,
  enterSession,
  sendSessionKey,
  getAppRuntime,
  getDesktopInfo,
  getAuthStatus,
  getCodexOptions,
  getCodexRun,
  getCodexRuns,
  getNetInfo,
  getPowerStatus,
  getTelegramStatus,
  getThreadStore,
  getTmuxHealth,
  getTmuxPaneScreen,
  getTmuxPanes,
  getSessionNotes,
  getSessionScreen,
  getSessions,
  interruptSession,
  interruptPane,
  login,
  logout,
  reportIpcEvent,
  saveSessionNotes,
  sendPowerAction,
  sendSessionImage,
  sendToPaneKey,
  sendToPane,
  sendToSession,
  setDesktopMode,
  setIpcObserver,
  startCodexExec,
  updateThreadRecord,
  uploadWslFile,
} from "./api";
import type {
  AppRuntimeResult,
  AuthStatus,
  CodexRunDetail,
  CodexRunSummary,
  DesktopInfoResult,
  NetInfo,
  PowerStatusResult,
  SessionInfo,
  SessionNoteInfo,
  SessionStreamEvent,
  ThreadInfo,
  ThreadMessageInfo,
  TmuxPaneInfo,
} from "./types";
import type { IpcEvent } from "./api";
import { SelectedSessionWorkspace } from "./components/sessions/SelectedSessionWorkspace";
const PairTab = lazy(() => import("./tabs/PairTab"));
const SettingsTab = lazy(() => import("./tabs/SettingsTab"));
const DebugTab = lazy(() => import("./tabs/DebugTab"));

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
type PowerActionName = "lock" | "sleep" | "hibernate" | "restart" | "shutdown";

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

function buildTelegramSessionPrompt(): string {
  return [
    "Send the relevant generated output files for the current task to me via Telegram using the existing send program already available in this session.",
    "Do not search for Telegram bot keys or secret files.",
    "After sending, tell me exactly which paths you sent.",
  ].join(" ");
}

function waitForNextPaint(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof window === "undefined" || typeof window.requestAnimationFrame !== "function") {
      resolve();
      return;
    }
    window.requestAnimationFrame(() => resolve());
  });
}

async function copyTextWithFallback(text: string): Promise<void> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall back to textarea-based copy when async clipboard is blocked.
    }
  }
  if (typeof document === "undefined") {
    throw new Error("Clipboard is not available in this context.");
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  const copied = typeof document.execCommand === "function" ? document.execCommand("copy") : false;
  document.body.removeChild(textarea);
  if (!copied) {
    throw new Error("Clipboard permission is unavailable.");
  }
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

interface TranscriptChunk {
  id: string;
  text: string;
}

const TAB_ORDER: MainTab[] = ["sessions", "threads", "remote", "pair", "settings", "debug"];

const CONTROLLER_BASE_STORAGE = "codrex.ui.controller_base.v1";
const REASONING_EFFORT_STORAGE = "codrex.ui.reasoning_effort.v1";
const THEME_MODE_STORAGE = "codrex.ui.theme_mode.v1";
const SESSION_VIEW_STORAGE = "codrex.ui.session_view_mode.v1";
const SESSION_SELECTED_STORAGE = "codrex.ui.selected_session.v1";
const SESSION_QUERY_STORAGE = "codrex.ui.session_query.v1";
const SESSION_PROJECT_FILTER_STORAGE = "codrex.ui.session_project_filter.v1";
const STREAM_PROFILE_STORAGE = "codrex.ui.stream_profile.v1";
const STREAM_ENABLED_STORAGE = "codrex.ui.stream_enabled.v1";
const SWIPE_HINT_SEEN_STORAGE = "codrex.ui.swipe_hint_seen.v1";
const COMPACT_TRANSCRIPT_STORAGE = "codrex.ui.compact_transcript.v1";
const TOUCH_COMFORT_STORAGE = "codrex.ui.touch_comfort.v1";
const THREADS_STORAGE = "codrex.ui.threads.v2";
const THREAD_MESSAGES_STORAGE = "codrex.ui.thread_messages.v2";
const THREAD_MESSAGES_LEGACY_STORAGE = "codrex.ui.thread_messages.v1";
const DESKTOP_PROFILE_STREAM: Record<DesktopStreamProfile, { fps: number; level: number; scale: number; bw: boolean }> = {
  responsive: { fps: 8, level: 1, scale: 1, bw: false },
  balanced: { fps: 6, level: 2, scale: 2, bw: false },
  saver: { fps: 4, level: 3, scale: 3, bw: false },
  ultra: { fps: 3, level: 2, scale: 3, bw: true },
  extreme: { fps: 2, level: 3, scale: 4, bw: true },
};
const SESSION_SUMMARY_POLL_MS = 3000;
const SESSION_SUMMARY_HIDDEN_POLL_MS = 9000;
const REMOTE_POLL_MS = 3500;
const REMOTE_HIDDEN_POLL_MS = 7000;
const DEFAULT_BACKGROUND_POLL_MS = 5000;
const SESSION_MUTATION_REVALIDATE_MS = 900;
const POWER_ACTION_LABELS: Record<"lock" | "sleep" | "hibernate" | "restart" | "shutdown", string> = {
  lock: "Lock",
  sleep: "Sleep",
  hibernate: "Hibernate",
  restart: "Restart",
  shutdown: "Shutdown",
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

function isLocalHostName(hostname: string): boolean {
  const host = (hostname || "").trim().toLowerCase();
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
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
  return detectControllerPort();
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

function reasoningEffortRank(value: ReasoningEffort): number {
  const order: ReasoningEffort[] = ["minimal", "low", "medium", "high", "xhigh"];
  const index = order.indexOf(value);
  return index >= 0 ? index : order.length - 1;
}

function strongerReasoningEffort(a: ReasoningEffort, b: ReasoningEffort): ReasoningEffort {
  return reasoningEffortRank(a) >= reasoningEffortRank(b) ? a : b;
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

const TRANSCRIPT_CHUNK_SIZE = 4096;

function chunkTranscript(text: string): TranscriptChunk[] {
  if (!text) {
    return [];
  }
  const chunks: TranscriptChunk[] = [];
  for (let index = 0; index < text.length; index += TRANSCRIPT_CHUNK_SIZE) {
    chunks.push({
      id: `chunk_${index}_${text.length}`,
      text: text.slice(index, index + TRANSCRIPT_CHUNK_SIZE),
    });
  }
  return chunks;
}

function transcriptToText(chunks: TranscriptChunk[]): string {
  return chunks.map((chunk) => chunk.text).join("");
}

function appendTranscriptChunks(chunks: TranscriptChunk[], text: string): TranscriptChunk[] {
  if (!text) {
    return chunks;
  }
  const next = chunks.slice();
  let remaining = text;
  while (remaining.length > 0) {
    const last = next[next.length - 1];
    if (last && last.text.length < TRANSCRIPT_CHUNK_SIZE) {
      const capacity = TRANSCRIPT_CHUNK_SIZE - last.text.length;
      const take = remaining.slice(0, capacity);
      next[next.length - 1] = {
        ...last,
        text: `${last.text}${take}`,
      };
      remaining = remaining.slice(take.length);
      continue;
    }
    const take = remaining.slice(0, TRANSCRIPT_CHUNK_SIZE);
    next.push({
      id: `chunk_${next.length}_${Date.now()}_${take.length}`,
      text: take,
    });
    remaining = remaining.slice(take.length);
  }
  return next;
}

function applySessionStreamEventToChunks(chunks: TranscriptChunk[], event: SessionStreamEvent): TranscriptChunk[] {
  if (!event.ok && event.type === "error") {
    return chunks;
  }
  if (event.type === "append") {
    return appendTranscriptChunks(chunks, event.text || "");
  }
  if (event.type === "snapshot" || event.type === "replace") {
    return chunkTranscript(event.text || "");
  }
  return chunks;
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
  const [routeHint, setRouteHint] = useState<RouteHint>("tailscale");
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
  const [sessionsMeta, setSessionsMeta] = useState<{ total_sessions?: number; background_mode?: string } | null>(null);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [selectedSession, setSelectedSession] = useState(() => safeStorageGet(SESSION_SELECTED_STORAGE));
  const [newSessionName, setNewSessionName] = useState("");
  const [newSessionCwd, setNewSessionCwd] = useState("");
  const [sessionQuery, setSessionQuery] = useState(() => safeStorageGet(SESSION_QUERY_STORAGE));
  const [sessionProjectFilter, setSessionProjectFilter] = useState(() => safeStorageGet(SESSION_PROJECT_FILTER_STORAGE) || "all");
  const [sessionViewMode, setSessionViewMode] = useState<SessionViewMode>(() =>
    parseSessionViewMode(safeStorageGet(SESSION_VIEW_STORAGE)),
  );
  const [promptText, setPromptText] = useState("");
  const [reasoningEffortOptions, setReasoningEffortOptions] = useState<ReasoningEffort[]>(FALLBACK_REASONING_EFFORTS);
  const [selectedModel, setSelectedModel] = useState(FALLBACK_MODELS[0]);
  const [selectedReasoningEffort, setSelectedReasoningEffort] = useState<ReasoningEffort>(() =>
    parseReasoningEffort(safeStorageGet(REASONING_EFFORT_STORAGE)),
  );
  const [streamEnabled, setStreamEnabled] = useState<boolean>(() => parseStreamEnabled(safeStorageGet(STREAM_ENABLED_STORAGE)));
  const [streamProfile, setStreamProfile] = useState<StreamProfile>(() =>
    parseStreamProfile(safeStorageGet(STREAM_PROFILE_STORAGE)),
  );
  const [outputFeedState, setOutputFeedState] = useState<OutputFeedState>(() => (parseStreamEnabled(safeStorageGet(STREAM_ENABLED_STORAGE)) ? "polling" : "off"));
  const [sessionTranscriptChunks, setSessionTranscriptChunks] = useState<TranscriptChunk[]>([]);
  const [sessionAutoFollow, setSessionAutoFollow] = useState(true);
  const [sessionUnreadCount, setSessionUnreadCount] = useState(0);
  const [sessionBusy, setSessionBusy] = useState(false);
  const [sessionImageFile, setSessionImageFile] = useState<File | null>(null);
  const [sessionImagePrompt, setSessionImagePrompt] = useState("");
  const sessionImageDeliveryMode: SessionImageDeliveryMode = "insert_path";
  const [sessionNotes, setSessionNotes] = useState("");
  const [sessionNotesInfo, setSessionNotesInfo] = useState<SessionNoteInfo | null>(null);
  const [sessionNotesLoading, setSessionNotesLoading] = useState(false);
  const [sessionNotesBusy, setSessionNotesBusy] = useState(false);
  const [telegramConfigured, setTelegramConfigured] = useState(false);
  const [composerTelegramBusy, setComposerTelegramBusy] = useState(false);
  const [pageVisible, setPageVisible] = useState(() =>
    typeof document === "undefined" ? true : !document.hidden,
  );

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
  const [showLegacyThreadTools, setShowLegacyThreadTools] = useState(false);

  const [desktopInfo, setDesktopInfo] = useState<DesktopInfoResult | null>(null);
  const [desktopEnabled, setDesktopEnabled] = useState(false);
  const [desktopProfile, setDesktopProfile] = useState<DesktopStreamProfile>("balanced");
  const [desktopKeyInput, setDesktopKeyInput] = useState("enter");
  const [desktopTextInput, setDesktopTextInput] = useState("");
  const [desktopStatus, setDesktopStatus] = useState("");
  const [desktopFocusPoint, setDesktopFocusPoint] = useState<{ x: number; y: number } | null>(null);
  const [desktopFullscreen, setDesktopFullscreen] = useState(false);
  const [desktopTrackpadMode, setDesktopTrackpadMode] = useState(true);
  const [powerStatus, setPowerStatus] = useState<PowerStatusResult | null>(null);
  const [powerBusy, setPowerBusy] = useState(false);
  const [powerConfirmAction, setPowerConfirmAction] = useState<PowerActionName | "">("");
  const [powerConfirmToken, setPowerConfirmToken] = useState("");
  const [powerConfirmExpiresIn, setPowerConfirmExpiresIn] = useState(0);

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
  const [appRuntime, setAppRuntime] = useState<AppRuntimeResult | null>(null);

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
  const sessionTranscriptRef = useRef<TranscriptChunk[]>([]);
  const sessionTranscriptCacheRef = useRef<Record<string, TranscriptChunk[]>>({});
  const sessionStreamQueueRef = useRef<SessionStreamEvent[]>([]);
  const sessionStreamFrameRef = useRef<number | null>(null);
  const sessionStreamSeqRef = useRef<Record<string, number>>({});
  const sessionsRefreshInFlightRef = useRef(false);
  const sessionScreenRefreshInFlightRef = useRef<Set<string>>(new Set());
  const scheduledSessionsRefreshRef = useRef<number | null>(null);
  const remoteStageRef = useRef<HTMLDivElement | null>(null);
  const desktopFrameRef = useRef<HTMLImageElement | null>(null);
  const desktopPointerRef = useRef<{ active: boolean; x: number; y: number; moved: boolean }>({
    active: false,
    x: 0,
    y: 0,
    moved: false,
  });
  const threadLastAssistantAtRef = useRef<Record<string, number>>({});
  const localThreadsRef = useRef<ChatThread[]>([]);
  const localThreadMessagesRef = useRef<Record<string, ThreadMessage[]>>({});
  const threadMigrationAttemptedRef = useRef(false);
  const localBootstrapAttemptedRef = useRef(false);
  const sessionImageInputRef = useRef<HTMLInputElement | null>(null);

  const backendPort = useMemo(parsePort, []);
  const browserHostname = typeof window !== "undefined" ? window.location.hostname || "127.0.0.1" : "127.0.0.1";
  const isLocalBrowser = isLocalHostName(browserHostname);
  const sessionTranscriptText = useMemo(() => transcriptToText(sessionTranscriptChunks), [sessionTranscriptChunks]);
  const latestSessionResponseSnapshot = useMemo(() => compactAssistantSnapshot(sessionTranscriptText), [sessionTranscriptText]);
  const tailscaleRouteUnavailable = routeHint === "tailscale" && !netInfo?.tailscale_ip;
  const desktopStreamUrl = useMemo(() => {
    const profile = DESKTOP_PROFILE_STREAM[desktopProfile];
    return buildDesktopStreamUrl(profile);
  }, [desktopProfile]);
  const desktopInteractionDisabled = !desktopEnabled;
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

  const refreshAppRuntime = useCallback(async () => {
    try {
      const response = await getAppRuntime();
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Could not read app runtime.");
      }
      setAppRuntime(response);
    } catch (error) {
      addEvent("error", `Could not read app runtime: ${(error as Error).message}`);
      setAppRuntime(null);
    }
  }, [addEvent]);

  const refreshPowerStatus = useCallback(async () => {
    try {
      const response = await getPowerStatus();
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Power status unavailable.");
      }
      setPowerStatus(response);
    } catch (error) {
      addEvent("error", `Could not read power status: ${(error as Error).message}`);
      setPowerStatus(null);
    }
  }, [addEvent]);

  const refreshCodexOptions = useCallback(async () => {
    try {
      const response = await getCodexOptions();
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Could not read Codex options.");
      }

      const models = (response.models || []).filter((item): item is string => typeof item === "string" && !!item.trim());
      const responseModel = (response.default_model || "").trim();
      const defaultModel = responseModel || models[0] || FALLBACK_MODELS[0];
      setSelectedModel(defaultModel);

      const rawEfforts = (response.reasoning_efforts || []).filter((item): item is ReasoningEffort =>
        item === "minimal" || item === "low" || item === "medium" || item === "high" || item === "xhigh",
      );
      const nextEfforts = rawEfforts.length > 0 ? rawEfforts : FALLBACK_REASONING_EFFORTS;
      setReasoningEffortOptions(nextEfforts);
      const responseEffort = parseReasoningEffort(response.default_reasoning_effort || "");
      const defaultEffort = nextEfforts.includes(responseEffort) ? responseEffort : nextEfforts[nextEfforts.length - 1];
      setSelectedReasoningEffort((current) => {
        if (nextEfforts.includes(current)) {
          // Upgrade older stored defaults (for example "medium") to the strongest controller default.
          return strongerReasoningEffort(current, defaultEffort);
        }
        return defaultEffort;
      });
    } catch (error) {
      addEvent("error", `Could not load Codex options: ${(error as Error).message}`);
      setReasoningEffortOptions(FALLBACK_REASONING_EFFORTS);
      setSelectedModel(FALLBACK_MODELS[0]);
      setSelectedReasoningEffort("xhigh");
    }
  }, [addEvent]);

  const refreshSessions = useCallback(async () => {
    if (sessionsRefreshInFlightRef.current) {
      return;
    }
    sessionsRefreshInFlightRef.current = true;
    try {
      const response = await getSessions();
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Failed to read sessions.");
      }
      const nextSessions = response.sessions || [];
      setSessionsMeta(response.meta || null);
      setSessions(nextSessions);
      setSelectedSession((current) => {
        if (current && nextSessions.some((s) => s.session === current)) {
          return current;
        }
        const stored = safeStorageGet(SESSION_SELECTED_STORAGE);
        if (stored && nextSessions.some((s) => s.session === stored)) {
          return stored;
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
      sessionsRefreshInFlightRef.current = false;
      setSessionsLoading(false);
    }
  }, [setError, setStatus]);

  const scheduleSessionsRefresh = useCallback((delayMs = SESSION_MUTATION_REVALIDATE_MS) => {
    if (typeof window === "undefined") {
      void refreshSessions();
      return;
    }
    if (scheduledSessionsRefreshRef.current != null) {
      window.clearTimeout(scheduledSessionsRefreshRef.current);
    }
    scheduledSessionsRefreshRef.current = window.setTimeout(() => {
      scheduledSessionsRefreshRef.current = null;
      void refreshSessions();
    }, delayMs);
  }, [refreshSessions]);

  const refreshSessionNotes = useCallback(async (session: string) => {
    if (!session) {
      setSessionNotes("");
      setSessionNotesInfo(null);
      setSessionNotesLoading(false);
      return;
    }
    try {
      const response = await getSessionNotes(session);
      if (!response.ok || !response.notes) {
        throw new Error(response.detail || response.error || "Failed to read session notes.");
      }
      setSessionNotes(response.notes.content || "");
      setSessionNotesInfo(response.notes);
    } catch (error) {
      addEvent("error", `Could not load session notes: ${(error as Error).message}`);
      setSessionNotes("");
      setSessionNotesInfo(null);
    } finally {
      setSessionNotesLoading(false);
    }
  }, [addEvent]);

  const refreshTelegramStatus = useCallback(async () => {
    try {
      const response = await getTelegramStatus();
      setTelegramConfigured(Boolean(response.ok && response.configured));
    } catch {
      setTelegramConfigured(false);
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

  useEffect(() => {
    if (!powerConfirmToken || powerConfirmExpiresIn <= 0) {
      if (powerConfirmToken && powerConfirmExpiresIn <= 0) {
        setPowerConfirmAction("");
        setPowerConfirmToken("");
      }
      return;
    }
    const timer = window.setTimeout(() => {
      setPowerConfirmExpiresIn((current) => (current > 0 ? current - 1 : 0));
    }, 1000);
    return () => {
      window.clearTimeout(timer);
    };
  }, [powerConfirmExpiresIn, powerConfirmToken]);

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
      setSessionTranscriptChunks([]);
      sessionStreamSeqRef.current = {};
      return;
    }
    if (sessionScreenRefreshInFlightRef.current.has(session)) {
      return;
    }
    sessionScreenRefreshInFlightRef.current.add(session);
    try {
      const response = await getSessionScreen(session);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Failed to read session screen.");
      }
      const nextText = response.text || "";
      const nextChunks = chunkTranscript(nextText);
      sessionTranscriptCacheRef.current[session] = nextChunks;
      if (session === selectedSession) {
        setSessionTranscriptChunks(nextChunks);
      }
      setSessionUnreadCount(0);
    } catch (error) {
      setError(`Could not read screen: ${(error as Error).message}`);
    } finally {
      sessionScreenRefreshInFlightRef.current.delete(session);
    }
  }, [selectedSession, setError]);

  const shouldUseLiveSessionStream = useCallback((session: string) => {
    return (
      !!session &&
      activeTab === "sessions" &&
      streamEnabled &&
      selectedSession === session &&
      (outputFeedState === "connecting" || outputFeedState === "live")
    );
  }, [activeTab, outputFeedState, selectedSession, streamEnabled]);

  const revalidateSessionAfterMutation = useCallback((session: string) => {
    if (!shouldUseLiveSessionStream(session)) {
      void refreshScreen(session);
    }
    scheduleSessionsRefresh();
  }, [refreshScreen, scheduleSessionsRefresh, shouldUseLiveSessionStream]);

  const flushSessionStreamQueue = useCallback(() => {
    sessionStreamFrameRef.current = null;
    const queued = sessionStreamQueueRef.current.splice(0);
    if (queued.length === 0) {
      return;
    }

    let nextChunks = sessionTranscriptRef.current;
    let didChange = false;
    let latestText = transcriptToText(nextChunks);

    queued.forEach((event) => {
      if (typeof event.seq === "number" && event.seq > 0) {
        sessionStreamSeqRef.current[event.session] = event.seq;
      }
      if (event.type === "snapshot" || event.type === "append" || event.type === "replace") {
        nextChunks = applySessionStreamEventToChunks(nextChunks, event);
        latestText = transcriptToText(nextChunks);
        didChange = true;
      }
    });

    if (!didChange) {
      return;
    }

    setSessionTranscriptChunks(nextChunks);
    if (threadSession === selectedSession) {
      captureAssistantSnapshot(selectedSession, latestText);
    }
    if (!sessionAutoFollow) {
      setSessionUnreadCount((current) => current + 1);
    }
  }, [captureAssistantSnapshot, selectedSession, sessionAutoFollow, threadSession]);

  useEffect(() => {
    void (async () => {
      await Promise.all([
        refreshAppRuntime(),
        refreshAuth(),
        refreshCodexOptions(),
        refreshNet(),
        refreshPowerStatus(),
        refreshSessions(),
        refreshTelegramStatus(),
        refreshThreads(),
        refreshDebugRuns(),
        refreshTmuxState(),
        refreshDesktopState(),
      ]);
      setStatus("Connected. Ready.");
    })();
  }, [refreshAppRuntime, refreshAuth, refreshCodexOptions, refreshDebugRuns, refreshDesktopState, refreshNet, refreshPowerStatus, refreshSessions, refreshTelegramStatus, refreshThreads, refreshTmuxState, setStatus]);

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
    return () => {
      if (scheduledSessionsRefreshRef.current != null && typeof window !== "undefined") {
        window.clearTimeout(scheduledSessionsRefreshRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    const onVisibilityChange = () => {
      setPageVisible(!document.hidden);
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

  useEffect(() => {
    sessionTranscriptRef.current = sessionTranscriptChunks;
    if (selectedSession) {
      sessionTranscriptCacheRef.current[selectedSession] = sessionTranscriptChunks;
    }
  }, [selectedSession, sessionTranscriptChunks]);

  useEffect(() => {
    const node = sessionOutputRef.current;
    if (!node) {
      return;
    }
    if (sessionAutoFollow) {
      node.scrollTop = node.scrollHeight;
      if (sessionUnreadCount) {
        setSessionUnreadCount(0);
      }
    }
  }, [selectedSession, sessionAutoFollow, sessionTranscriptChunks, sessionUnreadCount]);

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
      if (target?.closest(ignoreSelector)) {
        return;
      }
      if (target?.closest("[data-remote-gesture='true']")) {
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
  }, [activeTab, addEvent]);

  useEffect(() => {
    const intervalMs =
      !pageVisible
        ? activeTab === "remote"
          ? REMOTE_HIDDEN_POLL_MS
          : SESSION_SUMMARY_HIDDEN_POLL_MS
        : activeTab === "remote"
          ? REMOTE_POLL_MS
          : activeTab === "sessions"
            ? SESSION_SUMMARY_POLL_MS
            : DEFAULT_BACKGROUND_POLL_MS;
    const interval = window.setInterval(() => {
      const shouldPollSessions = activeTab === "sessions";
      if (shouldPollSessions) {
        void refreshSessions();
      }

      if (!pageVisible) {
        return;
      }

      if (activeTab === "sessions") {
        const liveStreamActive =
          streamEnabled &&
          !!selectedSession &&
          (outputFeedState === "connecting" || outputFeedState === "live");
        if (selectedSession && !liveStreamActive) {
          void refreshScreen(selectedSession);
        }
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
    refreshThreads,
    refreshTmuxScreen,
    refreshTmuxState,
    selectedRunId,
    selectedSession,
    selectedTmuxPane,
    streamEnabled,
    streamProfile,
    pageVisible,
  ]);

  useEffect(() => {
    if (!selectedSession) {
      setSessionTranscriptChunks([]);
      setSessionNotes("");
      setSessionNotesInfo(null);
      setSessionNotesLoading(false);
      return;
    }
    setSessionAutoFollow(true);
    setSessionUnreadCount(0);
    const cachedTranscript = sessionTranscriptCacheRef.current[selectedSession];
    if (cachedTranscript) {
      setSessionTranscriptChunks(cachedTranscript);
    } else {
      setSessionTranscriptChunks([]);
    }
    const canUseStreamBootstrap =
      activeTab === "sessions" &&
      streamEnabled &&
      typeof window !== "undefined" &&
      typeof window.WebSocket === "function";
    if (!canUseStreamBootstrap) {
      void refreshScreen(selectedSession);
    }
    setSessionNotesLoading(true);
    void refreshSessionNotes(selectedSession);
  }, [activeTab, refreshScreen, refreshSessionNotes, selectedSession, streamEnabled]);

  useEffect(() => {
    if (!selectedTmuxPane) {
      setTmuxScreenText("");
      return;
    }
    void refreshTmuxScreen(selectedTmuxPane);
  }, [refreshTmuxScreen, selectedTmuxPane]);

  useEffect(() => {
    const onFullscreenChange = () => {
      setDesktopFullscreen(Boolean(document.fullscreenElement));
    };
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);

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
    if (!streamEnabled || activeTab !== "sessions" || !selectedSession) {
      setOutputFeedState(streamEnabled ? "polling" : "off");
      return;
    }
    if (typeof window === "undefined" || typeof window.WebSocket !== "function") {
      setOutputFeedState("polling");
      return;
    }

    const streamUrl = buildSessionStreamUrl(selectedSession, {
      profile: streamProfile,
      since_seq: sessionStreamSeqRef.current[selectedSession] || 0,
    });
    let closed = false;
    setOutputFeedState("connecting");
    reportIpcEvent({
      channel: "ws",
      direction: "out",
      method: "GET",
      path: streamUrl,
      detail: "connect",
    });

    const socket = new WebSocket(streamUrl);

    const scheduleFlush = () => {
      if (sessionStreamFrameRef.current != null) {
        return;
      }
      sessionStreamFrameRef.current = window.requestAnimationFrame(() => {
        flushSessionStreamQueue();
      });
    };

    socket.onmessage = (message) => {
      if (closed) {
        return;
      }
      try {
        const payload = JSON.parse(message.data || "{}") as SessionStreamEvent;
        if (payload.type === "hello") {
          setOutputFeedState("live");
        } else if (payload.type === "status" && payload.detail === "waiting_for_pane") {
          setOutputFeedState("connecting");
        } else if (payload.type === "keepalive") {
          setOutputFeedState("live");
        } else if (payload.type === "error" || payload.ok === false) {
          setOutputFeedState("error");
        } else {
          setOutputFeedState("live");
        }

        if (payload.type === "snapshot" || payload.type === "append" || payload.type === "replace") {
          sessionStreamQueueRef.current.push(payload);
          scheduleFlush();
        }

        reportIpcEvent({
          channel: "ws",
          direction: payload.type === "error" || payload.ok === false ? "error" : "in",
          method: "GET",
          path: streamUrl,
          status: 200,
          detail: payload.type,
          responseBody: payload.text ? `${payload.type} ${payload.text.length} chars` : payload.detail,
        });
      } catch {
        setOutputFeedState("error");
        reportIpcEvent({
          channel: "ws",
          direction: "error",
          method: "GET",
          path: streamUrl,
          detail: "parse_error",
        });
      }
    };

    socket.onerror = () => {
      if (closed) {
        return;
      }
      setOutputFeedState("error");
      reportIpcEvent({
        channel: "ws",
        direction: "error",
        method: "GET",
        path: streamUrl,
        detail: "stream_error",
      });
    };

    socket.onclose = () => {
      if (closed) {
        return;
      }
      setOutputFeedState(streamEnabled ? "polling" : "off");
      reportIpcEvent({
        channel: "ws",
        direction: "error",
        method: "GET",
        path: streamUrl,
        detail: "closed",
      });
    };

    return () => {
      closed = true;
      if (sessionStreamFrameRef.current != null) {
        window.cancelAnimationFrame(sessionStreamFrameRef.current);
        sessionStreamFrameRef.current = null;
      }
      sessionStreamQueueRef.current = [];
      try {
        socket.close();
      } catch {}
      setOutputFeedState(streamEnabled ? "polling" : "off");
    };
  }, [activeTab, flushSessionStreamQueue, selectedSession, streamEnabled, streamProfile]);

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
    setSelectedReasoningEffort((current) => clampReasoningForModel(selectedModel, current, reasoningEffortOptions));
  }, [reasoningEffortOptions, selectedModel]);

  useEffect(() => {
    safeStorageSet(REASONING_EFFORT_STORAGE, selectedReasoningEffort);
  }, [selectedReasoningEffort]);

  useEffect(() => {
    safeStorageSet(SESSION_SELECTED_STORAGE, selectedSession);
  }, [selectedSession]);

  useEffect(() => {
    safeStorageSet(SESSION_QUERY_STORAGE, sessionQuery);
  }, [sessionQuery]);

  useEffect(() => {
    safeStorageSet(SESSION_PROJECT_FILTER_STORAGE, sessionProjectFilter);
  }, [sessionProjectFilter]);

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
    if (projectOptions.length === 0) {
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
  const powerWakeInstruction = (powerStatus?.wake_instruction || `${powerStatus?.wake_command || "/wake"} laptop`).trim();
  const powerRelayBadge = powerStatus?.relay_reachable
    ? "relay: reachable"
    : powerStatus?.wake_relay_configured
      ? "relay: offline"
      : "relay: unconfigured";
  const powerWakeReadiness = powerStatus?.wake_readiness || "partial";
  const powerWakeBadge = `wake: ${powerWakeReadiness}`;
  const powerWakeTransport = powerStatus?.wake_transport_hint || "unknown";
  const powerWakeWarning = (powerStatus?.wake_warning || "").trim();
  const sessionCountValue = sessionsMeta?.total_sessions || sessions.length;
  const sessionCountLabel = `${sessionCountValue} session${sessionCountValue === 1 ? "" : "s"}`;
  const visibleSessionCountLabel = `${filteredSessions.length} visible / ${sessionCountValue} total`;
  const runningRuns = debugRuns.filter((run) => run.status === "running").length;
  const totalEvents = eventLog.length;
  const errorEvents = eventLog.filter((evt) => evt.level === "error").length;
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
  const controllerRouteSeverity =
    controllerRouteKind === "tailscale"
      ? "ok"
      : controllerRouteKind === "lan"
        ? "caution"
        : "warn";
  const outputFeedSummary = streamEnabled ? `${outputFeedState} / ${streamProfile}` : "polling only";
  const connectivitySummary = isOnline ? "Online" : "Offline";
  const installSummary = installState === "installed" ? "Installed" : installPromptEvent ? "Ready" : "Browser Menu";
  const remoteControlSummary = desktopEnabled ? "Control enabled" : "View-only mode";
  const statusSnapshotSummary = errorMessage
    ? "Action required"
    : statusMessage.startsWith("Install ")
      ? "Install flow update"
      : statusMessage === "Ready."
        ? "Ready"
      : statusMessage;
  const canSendPrompt = promptText.trim().length > 0;
  const composerTelegramDisabledReason = !telegramConfigured
    ? "Telegram is not configured."
    : !selectedSession
      ? "Select a session first."
      : "";
  const sessionNotesSavedLabel = sessionNotesInfo?.updated_at ? `Saved ${formatClock(sessionNotesInfo.updated_at)}` : "Not saved yet";
  const hasLatestSessionResponse = Boolean(
    latestSessionResponseSnapshot.trim() || (sessionNotesInfo?.last_response_snapshot || "").trim(),
  );
  const desktopFocusSummary = desktopFocusPoint
    ? `Focused target: ${desktopFocusPoint.x}, ${desktopFocusPoint.y}`
    : "No desktop target focused yet. Tap the remote desktop once first.";
  const installButtonLabel =
    installState === "installed"
      ? "Installed"
      : installState === "ready"
        ? "Install App"
        : installState === "prompting"
          ? "Installing..."
          : "Install Help";
  const appVersionLabel = appRuntime?.version ? `v${appRuntime.version}` : "version unavailable";
  const appModeLabel = appRuntime?.ui_mode || "offline";
  const screenCardClassName = `card screen-card ${tabTransitionClass}`;

  const onHardRefresh = useCallback(async () => {
    setStatus("Syncing controller state...");
    await Promise.all([
      refreshAppRuntime(),
      refreshAuth(),
      refreshCodexOptions(),
      refreshNet(),
      refreshPowerStatus(),
      refreshSessions(),
      refreshTelegramStatus(),
      refreshThreads(),
      refreshDebugRuns(),
      refreshTmuxState(),
      refreshDesktopState(),
    ]);
    if (selectedSession) {
      await refreshScreen(selectedSession);
      await refreshSessionNotes(selectedSession);
    }
    if (selectedTmuxPane) {
      await refreshTmuxScreen(selectedTmuxPane);
    }
    if (selectedRunId) {
      await refreshRunDetail(selectedRunId);
    }
    setStatus("Synced.");
  }, [refreshAppRuntime, refreshAuth, refreshCodexOptions, refreshDebugRuns, refreshDesktopState, refreshNet, refreshPowerStatus, refreshRunDetail, refreshScreen, refreshSessionNotes, refreshSessions, refreshTelegramStatus, refreshThreads, refreshTmuxScreen, refreshTmuxState, selectedRunId, selectedSession, selectedTmuxPane, setStatus]);

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
    if ((nextRoute === "lan" || nextRoute === "current") && !isLocalBrowser) {
      setError("LAN/current routes are disabled on remote browsers. Keep route hint on Tailscale.");
      return;
    }
    setRouteHint(nextRoute);
    const suggested = buildSuggestedControllerUrl(
      browserHostname,
      backendPort,
      netInfo,
      nextRoute,
    );
    setControllerBase(suggested);
  }, [backendPort, browserHostname, isLocalBrowser, netInfo, setError]);

  const onGeneratePairing = useCallback(async () => {
    if ((routeHint === "lan" || routeHint === "current") && !isLocalBrowser) {
      setError("LAN/current pairing is allowed only from localhost browser. Switch to Tailscale route.");
      return;
    }
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
  }, [controllerBase, isLocalBrowser, routeHint, setError, setStatus]);

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
      scheduleSessionsRefresh(250);
      setActiveTab("sessions");
      setStatus(`Created ${response.session} (${response.reasoning_effort || createReasoningEffort}).`);
    } catch (error) {
      setError(`Create session failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [
    newSessionCwd,
    newSessionName,
    reasoningEffortOptions,
    scheduleSessionsRefresh,
    selectedModel,
    selectedReasoningEffort,
    setError,
    setStatus,
  ]);

  const onResumeLastSession = useCallback(async () => {
    setSessionBusy(true);
    try {
      const response = await createSessionWithOptions({
        name: newSessionName.trim(),
        cwd: newSessionCwd.trim(),
        reasoning_effort: clampReasoningForModel(selectedModel, selectedReasoningEffort, reasoningEffortOptions),
        resume_last: true,
      });
      if (!response.ok || !response.session) {
        throw new Error(response.detail || response.error || "Could not start resume session.");
      }
      setNewSessionName("");
      setNewSessionCwd("");
      setSelectedSession(response.session);
      setStreamEnabled(true);
      setOutputFeedState("polling");
      scheduleSessionsRefresh(250);
      setActiveTab("sessions");
      setStatus(`Started ${response.session} in resume-last mode.`);
    } catch (error) {
      setError(`Resume last failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [
    newSessionCwd,
    newSessionName,
    reasoningEffortOptions,
    scheduleSessionsRefresh,
    selectedModel,
    selectedReasoningEffort,
    setError,
    setStatus,
  ]);

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
      revalidateSessionAfterMutation(selectedSession);
    } catch (error) {
      setError(`Enter failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [revalidateSessionAfterMutation, selectedSession, setError, setStatus]);

  const onSendBackspace = useCallback(async () => {
    if (!selectedSession) {
      setError("Select a session first.");
      return;
    }
    setSessionBusy(true);
    try {
      const response = await sendSessionKey(selectedSession, "backspace");
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Backspace failed.");
      }
      setStatus(`Sent Backspace to ${selectedSession}.`);
      revalidateSessionAfterMutation(selectedSession);
    } catch (error) {
      setError(`Backspace failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [revalidateSessionAfterMutation, selectedSession, setError, setStatus]);

  const onSendArrowKey = useCallback(async (key: "up" | "down" | "left" | "right") => {
    if (!selectedSession) {
      setError("Select a session first.");
      return;
    }
    setSessionBusy(true);
    try {
      const response = await sendSessionKey(selectedSession, key);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Arrow key failed.");
      }
      setStatus(`Sent ${key} arrow to ${selectedSession}.`);
      revalidateSessionAfterMutation(selectedSession);
    } catch (error) {
      setError(`Arrow key failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [revalidateSessionAfterMutation, selectedSession, setError, setStatus]);

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
      revalidateSessionAfterMutation(selectedSession);
    } catch (error) {
      setError(`Interrupt failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [revalidateSessionAfterMutation, selectedSession, setError, setStatus]);

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
      revalidateSessionAfterMutation(selectedSession);
    } catch (error) {
      setError(`Ctrl+C failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [revalidateSessionAfterMutation, selectedSession, setError, setStatus]);

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
      const closingSession = selectedSession;
      setStatus(`Closed ${selectedSession}.`);
      setSessions((current) => current.filter((item) => item.session !== closingSession));
      sessionTranscriptCacheRef.current[closingSession] = [];
      setSessionTranscriptChunks([]);
      setSessionNotes("");
      setSessionNotesInfo(null);
      delete sessionStreamSeqRef.current[closingSession];
      setSelectedSession((current) => (current === closingSession ? "" : current));
      scheduleSessionsRefresh(200);
    } catch (error) {
      setError(`Close session failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [scheduleSessionsRefresh, selectedSession, setError, setStatus]);

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
      revalidateSessionAfterMutation(selectedSession);
    } catch (error) {
      setError(`Send image failed: ${(error as Error).message}`);
    } finally {
      setSessionBusy(false);
    }
  }, [
    revalidateSessionAfterMutation,
    selectedSession,
    sessionImageDeliveryMode,
    sessionImageFile,
    sessionImagePrompt,
    setError,
    setStatus,
  ]);

  const onSaveSessionNotes = useCallback(async () => {
    if (!selectedSession) {
      setError("Select a session first.");
      return;
    }
    setSessionNotesBusy(true);
    try {
      const response = await saveSessionNotes(selectedSession, {
        content: sessionNotes,
        last_response_snapshot: latestSessionResponseSnapshot,
      });
      if (!response.ok || !response.notes) {
        throw new Error(response.detail || response.error || "Could not save session notes.");
      }
      setSessionNotes(response.notes.content || "");
      setSessionNotesInfo(response.notes);
      setStatus(`Notes saved for ${selectedSession}.`);
    } catch (error) {
      setError(`Save notes failed: ${(error as Error).message}`);
    } finally {
      setSessionNotesBusy(false);
    }
  }, [latestSessionResponseSnapshot, selectedSession, sessionNotes, setError, setStatus]);

  const onAppendLatestToSessionNotes = useCallback(async () => {
    if (!selectedSession) {
      setError("Select a session first.");
      return;
    }
    setSessionNotesBusy(true);
    try {
      const response = await appendLatestSessionNotes(selectedSession);
      if (!response.ok || !response.notes) {
        throw new Error(response.detail || response.error || "Could not append latest response.");
      }
      setSessionNotes(response.notes.content || "");
      setSessionNotesInfo(response.notes);
      setStatus(response.detail || `Latest response appended to ${selectedSession} notes.`);
    } catch (error) {
      setError(`Append latest failed: ${(error as Error).message}`);
    } finally {
      setSessionNotesBusy(false);
    }
  }, [selectedSession, setError, setStatus]);

  const submitPromptText = useCallback(async (
    userPrompt: string,
    successMessage?: string,
    options?: {
      preserveComposer?: boolean;
    },
  ) => {
    const preserveComposer = options?.preserveComposer ?? false;
    if (!selectedSession) {
      setError("Select a session first.");
      return false;
    }
    const normalizedPrompt = userPrompt.trim();
    if (!normalizedPrompt) {
      setError("Prompt cannot be empty.");
      return false;
    }

    setSessionBusy(true);
    try {
      const response = await sendToSession(selectedSession, normalizedPrompt);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Prompt send failed.");
      }
      if (response.shared_file || response.session_file) {
        if (!preserveComposer) {
          setPromptText("");
        }
        setStatus(response.detail || `Attached ${(response.session_file || response.shared_file)?.file_name || "item"} to session files.`);
        scheduleSessionsRefresh();
        return true;
      }
      if (!preserveComposer) {
        setPromptText("");
      }
      const threadId = await ensureThreadForSession(selectedSession, normalizedPrompt);
      if (threadId) {
        const message = addThreadMessage(threadId, "user", normalizedPrompt);
        if (message) {
          void syncThreadMessage(message);
        }
      }
      setStatus(successMessage || `Sent prompt to ${selectedSession}.`);
      revalidateSessionAfterMutation(selectedSession);
      window.setTimeout(async () => {
        try {
          const snapshot = await getSessionScreen(selectedSession);
          if (snapshot.ok && snapshot.text && threadId) {
            captureAssistantSnapshot(selectedSession, snapshot.text, threadId);
          }
        } catch {}
      }, 1200);
      return true;
    } catch (error) {
      setError(`Send failed: ${(error as Error).message}`);
      return false;
    } finally {
      setSessionBusy(false);
    }
  }, [
    addThreadMessage,
    captureAssistantSnapshot,
    ensureThreadForSession,
    revalidateSessionAfterMutation,
    scheduleSessionsRefresh,
    selectedSession,
    setError,
    setStatus,
    syncThreadMessage,
  ]);

  const onSendPrompt = useCallback(async () => {
    await submitPromptText(promptText);
  }, [promptText, submitPromptText]);

  const onCopyLatestSessionResponse = useCallback(async () => {
    const text = latestSessionResponseSnapshot.trim() || (sessionNotesInfo?.last_response_snapshot || "").trim();
    if (!text) {
      setError("No recent Codex response is available to copy.");
      return;
    }
    try {
      await copyTextWithFallback(text);
      setStatus(`Latest response copied: ${text}`);
    } catch (error) {
      setError(`Copy latest response failed: ${(error as Error).message}`);
    }
  }, [latestSessionResponseSnapshot, sessionNotesInfo?.last_response_snapshot, setError, setStatus]);

  const onSendComposerToTelegram = useCallback(async () => {
    if (!selectedSession) {
      setError("Select a session first.");
      return;
    }
    if (!telegramConfigured) {
      setError("Telegram is not configured yet.");
      return;
    }
    const command = buildTelegramSessionPrompt();
    const existingDraft = promptText.trim();
    const combinedPrompt = existingDraft ? `${existingDraft}\n\n${command}` : command;
    flushSync(() => {
      setPromptText(combinedPrompt);
    });
    setStatus("Prepared Telegram instruction for the current task output.");
    setComposerTelegramBusy(true);
    try {
      await waitForNextPaint();
      const sent = await submitPromptText(
        combinedPrompt,
        "Asked Codex to send the relevant generated output files via Telegram.",
        { preserveComposer: true },
      );
      if (!sent) {
        setPromptText(combinedPrompt);
      }
    } catch (error) {
      setError(`Telegram send request failed: ${(error as Error).message}`);
      setPromptText(combinedPrompt);
    } finally {
      setComposerTelegramBusy(false);
    }
  }, [
    promptText,
    selectedSession,
    setError,
    setPromptText,
    submitPromptText,
    telegramConfigured,
  ]);

  const onCopySessionNotes = useCallback(async () => {
    const text = sessionNotes.trim();
    if (!text) {
      setError("Notes are empty.");
      return;
    }
    try {
      await copyTextWithFallback(text);
      setStatus("Session notes copied.");
    } catch (error) {
      setError(`Copy notes failed: ${(error as Error).message}`);
    }
  }, [sessionNotes, setError, setStatus]);

  const onClearSessionNotes = useCallback(() => {
    setSessionNotes("");
    setStatus("Notes cleared locally. Press Save to persist the empty note.");
  }, [setStatus]);

  const onSessionOutputScroll = useCallback(() => {
    const node = sessionOutputRef.current;
    if (!node) {
      return;
    }
    const nearBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 40;
    setSessionAutoFollow(nearBottom);
    if (nearBottom) {
      setSessionUnreadCount(0);
    }
  }, []);

  const onJumpToSessionLive = useCallback(() => {
    setSessionAutoFollow(true);
    setSessionUnreadCount(0);
  }, []);

  const onToggleSessionStream = useCallback(() => {
    setStreamEnabled((current) => !current);
  }, []);

  const onStreamProfileChange = useCallback((value: string) => {
    setStreamProfile(parseStreamProfile(value));
  }, []);

  const onPromptTextChange = useCallback((value: string) => {
    setPromptText(value);
  }, []);

  const onOpenSessionImagePicker = useCallback(() => {
    sessionImageInputRef.current?.click();
  }, []);

  const onSessionImageFileChange = useCallback((file: File | null) => {
    setSessionImageFile(file);
  }, []);

  const onSessionImagePromptChange = useCallback((value: string) => {
    setSessionImagePrompt(value);
  }, []);

  const onSessionNotesChange = useCallback((value: string) => {
    setSessionNotes(value);
  }, []);

  const onRefreshSelectedSession = useCallback(() => {
    if (!selectedSession) {
      return;
    }
    void refreshScreen(selectedSession);
  }, [refreshScreen, selectedSession]);

  const onComposerTelegramRequest = useCallback(() => {
    if (composerTelegramDisabledReason) {
      setError(composerTelegramDisabledReason);
      return;
    }
    void onSendComposerToTelegram();
  }, [composerTelegramDisabledReason, onSendComposerToTelegram, setError]);

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

  const onSendTmuxKey = useCallback(async (key: "up" | "down" | "left" | "right" | "enter") => {
    if (!selectedTmuxPane) {
      setError("Select a tmux pane first.");
      return;
    }
    setTmuxBusy(true);
    try {
      const response = await sendToPaneKey(selectedTmuxPane, key);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "tmux key failed.");
      }
      setStatus(`Sent ${key} key to pane.`);
      await refreshTmuxScreen(selectedTmuxPane);
    } catch (error) {
      setError(`tmux key failed: ${(error as Error).message}`);
    } finally {
      setTmuxBusy(false);
    }
  }, [refreshTmuxScreen, selectedTmuxPane, setError, setStatus]);

  const onResumeLastTmux = useCallback(async () => {
    if (!selectedTmuxPane) {
      setError("Select a tmux pane first.");
      return;
    }
    setTmuxBusy(true);
    try {
      const response = await sendToPane(selectedTmuxPane, "codex resume --last");
      if (!response.ok) {
        throw new Error(response.detail || response.error || "tmux resume failed.");
      }
      setStatus("Sent `codex resume --last` to pane.");
      await refreshTmuxScreen(selectedTmuxPane);
    } catch (error) {
      setError(`tmux resume failed: ${(error as Error).message}`);
    } finally {
      setTmuxBusy(false);
    }
  }, [refreshTmuxScreen, selectedTmuxPane, setError, setStatus]);

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
      setDesktopStatus(
        enabled
          ? "Desktop control enabled. Stream remains live."
          : "Desktop control disabled. View-only live stream remains active.",
      );
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
    if (!desktopFocusPoint) {
      setError("Tap the remote desktop once to focus the target app/window first.");
      return;
    }
    const text = desktopTextInput;
    if (!text) {
      setError("Desktop text is empty.");
      return;
    }
    try {
      const response = await desktopSendText(text);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop text failed.");
      }
      setDesktopTextInput("");
      setDesktopStatus(`Typed text into focused app at ${desktopFocusPoint.x}, ${desktopFocusPoint.y}.`);
    } catch (error) {
      setError(`Desktop text failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, desktopFocusPoint, desktopTextInput, setError]);

  const onDesktopPasteClipboard = useCallback(async () => {
    if (!desktopEnabled) {
      setError("Desktop control is disabled. Enable Desktop first.");
      return;
    }
    if (!desktopFocusPoint) {
      setError("Tap the remote desktop once to focus the target app/window first.");
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
      setDesktopTextInput(text);
      setDesktopStatus(`Loaded clipboard text into the remote text box for ${desktopFocusPoint.x}, ${desktopFocusPoint.y}.`);
    } catch (error) {
      setError(`Desktop paste failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, desktopFocusPoint, desktopTextInput, setError]);

  const mapDesktopPointFromClient = useCallback((clientX: number, clientY: number) => {
    if (!desktopInfo?.width || !desktopInfo?.height) {
      return null;
    }
    const img = desktopFrameRef.current;
    if (!img) {
      return null;
    }
    const rect = img.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return null;
    }
    const normX = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const normY = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    return {
      x: Math.round(normX * desktopInfo.width),
      y: Math.round(normY * desktopInfo.height),
    };
  }, [desktopInfo?.height, desktopInfo?.width]);

  const onDesktopMovePointer = useCallback(async (clientX: number, clientY: number) => {
    if (!desktopEnabled) {
      return;
    }
    const target = mapDesktopPointFromClient(clientX, clientY);
    if (!target) {
      return;
    }
    setDesktopFocusPoint(target);
    try {
      const response = await desktopMove(target.x, target.y);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop move failed.");
      }
      setDesktopStatus(`Pointer moved to ${target.x}, ${target.y}.`);
    } catch (error) {
      setError(`Desktop move failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, mapDesktopPointFromClient, setError]);

  const onDesktopWheel = useCallback(async (event: React.WheelEvent<HTMLImageElement>) => {
    if (!desktopEnabled) {
      return;
    }
    event.preventDefault();
    await onDesktopScroll(event.deltaY >= 0 ? 240 : -240);
  }, [desktopEnabled, onDesktopScroll]);

  const onDesktopPointerDown = useCallback((event: React.PointerEvent<HTMLImageElement>) => {
    if (!desktopEnabled) {
      return;
    }
    if (event.pointerType === "mouse" && !desktopTrackpadMode) {
      return;
    }
    desktopPointerRef.current = {
      active: true,
      x: event.clientX,
      y: event.clientY,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }, [desktopEnabled, desktopTrackpadMode]);

  const onDesktopPointerMove = useCallback(async (event: React.PointerEvent<HTMLImageElement>) => {
    if (!desktopEnabled || !desktopTrackpadMode || !desktopPointerRef.current.active) {
      return;
    }
    const state = desktopPointerRef.current;
    const delta = Math.abs(event.clientX - state.x) + Math.abs(event.clientY - state.y);
    if (delta < 8) {
      return;
    }
    desktopPointerRef.current = {
      active: true,
      x: event.clientX,
      y: event.clientY,
      moved: true,
    };
    await onDesktopMovePointer(event.clientX, event.clientY);
  }, [desktopEnabled, desktopTrackpadMode, onDesktopMovePointer]);

  const onDesktopPointerUp = useCallback(async (event: React.PointerEvent<HTMLImageElement>) => {
    const state = desktopPointerRef.current;
    desktopPointerRef.current = { active: false, x: 0, y: 0, moved: false };
    if (!desktopEnabled) {
      return;
    }
    const target = mapDesktopPointFromClient(event.clientX, event.clientY);
    if (!target) {
      return;
    }
    setDesktopFocusPoint(target);
    if (desktopTrackpadMode && state.moved) {
      setDesktopStatus(`Pointer focused at ${target.x}, ${target.y}.`);
      return;
    }
    try {
      const response = await desktopClick({ x: target.x, y: target.y, button: "left" });
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop tap failed.");
      }
      setDesktopStatus(`Focused desktop at ${target.x}, ${target.y}.`);
    } catch (error) {
      setError(`Desktop tap failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, desktopTrackpadMode, mapDesktopPointFromClient, setError]);

  const onDesktopContextMenu = useCallback(async (event: React.MouseEvent<HTMLImageElement>) => {
    if (!desktopEnabled) {
      return;
    }
    event.preventDefault();
    const target = mapDesktopPointFromClient(event.clientX, event.clientY);
    if (!target) {
      return;
    }
    setDesktopFocusPoint(target);
    try {
      const response = await desktopClick({ x: target.x, y: target.y, button: "right" });
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop right click failed.");
      }
      setDesktopStatus(`Right click sent at ${target.x}, ${target.y}.`);
    } catch (error) {
      setError(`Desktop right click failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, mapDesktopPointFromClient, setError]);

  const onDesktopFrameTap = useCallback(async (event: React.MouseEvent<HTMLImageElement>) => {
    if (!desktopEnabled) {
      setDesktopStatus("Desktop control is disabled. Enable Desktop first.");
      return;
    }
    if (desktopTrackpadMode) {
      return;
    }
    const target = mapDesktopPointFromClient(event.clientX, event.clientY);
    if (!target) {
      return;
    }
    setDesktopFocusPoint(target);
    try {
      const response = await desktopClick({ x: target.x, y: target.y, button: "left" });
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop tap failed.");
      }
      setDesktopStatus(`Focused desktop at ${target.x}, ${target.y}.`);
    } catch (error) {
      setError(`Desktop tap failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, desktopTrackpadMode, mapDesktopPointFromClient, setError]);

  const onToggleDesktopFullscreen = useCallback(async () => {
    try {
      if (!document.fullscreenElement) {
        await remoteStageRef.current?.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch (error) {
      setError(`Fullscreen failed: ${(error as Error).message}`);
    }
  }, [setError]);

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

  const onDesktopSendQuickKey = useCallback(async (key: string) => {
    if (!desktopEnabled) {
      setError("Desktop control is disabled. Enable Desktop first.");
      return;
    }
    try {
      const response = await desktopSendKey(key);
      if (!response.ok) {
        throw new Error(response.detail || response.error || "Desktop key failed.");
      }
      setDesktopKeyInput(key);
      setDesktopStatus(`Key sent: ${key}`);
    } catch (error) {
      setError(`Desktop key failed: ${(error as Error).message}`);
    }
  }, [desktopEnabled, setError]);

  const onRequestPowerAction = useCallback(async (action: PowerActionName, confirmToken = "") => {
    setPowerBusy(true);
    try {
      const response = await sendPowerAction(
        action,
        confirmToken ? { confirm_token: confirmToken } : undefined,
      );
      if (!response.ok) {
        if (response.error === "confirmation_required" && response.confirm_token) {
          setPowerConfirmAction(action);
          setPowerConfirmToken(response.confirm_token);
          setPowerConfirmExpiresIn(response.confirm_expires_in || 0);
          setStatus(response.detail || `Confirm ${POWER_ACTION_LABELS[action]} before sending it to the host.`);
          return;
        }
        throw new Error(response.detail || response.error || "Power action failed.");
      }
      setPowerConfirmAction("");
      setPowerConfirmToken("");
      setPowerConfirmExpiresIn(0);
      if (action === "lock") {
        setDesktopStatus(response.detail || "Laptop locked.");
        await refreshPowerStatus();
      }
      setStatus(response.detail || `${POWER_ACTION_LABELS[action]} sent.`);
    } catch (error) {
      setError(`Power action failed: ${(error as Error).message}`);
    } finally {
      setPowerBusy(false);
    }
  }, [refreshPowerStatus, setError, setStatus]);

  const onCancelPowerConfirmation = useCallback(() => {
    setPowerConfirmAction("");
    setPowerConfirmToken("");
    setPowerConfirmExpiresIn(0);
    setStatus("Pending power action canceled.");
  }, [setStatus]);

  const onCopyPowerValue = useCallback(async (value: string, label: string) => {
    const text = value.trim();
    if (!text) {
      setError(`No ${label.toLowerCase()} available to copy.`);
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setStatus(`${label} copied: ${text}`);
    } catch (error) {
      setError(`Copy failed: ${(error as Error).message}`);
    }
  }, [setError, setStatus]);

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
      const project = inferProjectFromCwd(session.cwd);
      const handleSelectSession = () => {
        setSelectedSession(session.session);
      };
      return (
        <div
          key={session.session}
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
                  if (sessionBusy) {
                    return;
                  }
                  setSelectedSession(session.session);
                  void (async () => {
                    setSessionBusy(true);
                    try {
                      const response = await closeSession(session.session);
                      if (!response.ok) {
                        throw new Error(response.detail || response.error || "Could not close session.");
                      }
                      const closingSession = session.session;
                      setStatus(`Closed ${session.session}.`);
                      setSessions((current) => current.filter((item) => item.session !== closingSession));
                      sessionTranscriptCacheRef.current[closingSession] = [];
                      if (selectedSession === closingSession) {
                        setSessionTranscriptChunks([]);
                        setSessionNotes("");
                        setSessionNotesInfo(null);
                        setSelectedSession("");
                      }
                      delete sessionStreamSeqRef.current[closingSession];
                      scheduleSessionsRefresh(200);
                    } catch (error) {
                      setError(`Close session failed: ${(error as Error).message}`);
                    } finally {
                      setSessionBusy(false);
                    }
                  })();
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
    },
    [closeSession, scheduleSessionsRefresh, selectedSession, sessionBusy, setError, setStatus],
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

  const primaryActions =
    activeTab === "sessions" ? (
      <>
        <button type="button" className="button compact" onClick={() => void onCreateSession()} disabled={sessionBusy}>
          New Session
        </button>
        <button type="button" className="button soft compact" onClick={() => void refreshSessions()}>
          Refresh List
        </button>
        <button type="button" className="button soft compact" onClick={() => setStreamEnabled((current) => !current)}>
          {streamEnabled ? "Live Output On" : "Live Output Off"}
        </button>
      </>
    ) : activeTab === "threads" ? (
      <>
        <button type="button" className="button compact" onClick={() => void refreshTmuxState()}>
          Refresh Monitor
        </button>
        <button type="button" className="button soft compact" onClick={() => setShowLegacyThreadTools((current) => !current)}>
          {showLegacyThreadTools ? "Hide Advanced Tools" : "Show Advanced Tools"}
        </button>
        <button type="button" className="button soft compact" onClick={() => void onResumeLastTmux()} disabled={tmuxBusy || !selectedTmuxPane}>
          Resume Last Pane
        </button>
      </>
    ) : activeTab === "remote" ? (
      <>
        <button type="button" className={`button compact ${desktopEnabled ? "warn" : ""}`} onClick={() => void onToggleDesktopMode()}>
          {desktopEnabled ? "Quick Disable Control" : "Quick Enable Control"}
        </button>
        <button type="button" className="button soft compact" onClick={onCaptureLatestShot}>
          Capture Screen
        </button>
        <button type="button" className="button soft compact" onClick={() => void refreshDesktopState()}>
          Refresh Remote
        </button>
      </>
    ) : activeTab === "pair" ? (
      <>
        <button type="button" className="button compact" onClick={() => void onGeneratePairing()} disabled={pairBusy}>
          {pairBusy ? "Quick Generating..." : "Quick Generate QR"}
        </button>
        <button type="button" className="button soft compact" onClick={() => void refreshNet()}>
          Refresh Routes
        </button>
        <button type="button" className="button soft compact" onClick={() => void onPairExchange()} disabled={pairBusy || !pairCode}>
          Exchange Here
        </button>
      </>
    ) : activeTab === "settings" ? (
      <>
        <button type="button" className="button compact" onClick={() => void refreshAuth()}>
          Refresh Auth
        </button>
        <button type="button" className="button soft compact" onClick={() => void refreshNet()}>
          Refresh Network
        </button>
        <button type="button" className="button soft compact" onClick={() => setTouchComfortMode((current) => !current)}>
          Touch Comfort: {touchComfortMode ? "On" : "Off"}
        </button>
      </>
    ) : (
      <>
        <button type="button" className="button compact" onClick={() => void refreshDebugRuns()}>
          Refresh Runs
        </button>
        <button type="button" className="button soft compact" onClick={onExportIpcHistory} disabled={ipcHistory.length === 0}>
          Export IPC
        </button>
        <button type="button" className="button soft compact" onClick={onClearIpcHistory} disabled={ipcHistory.length === 0}>
          Clear IPC
        </button>
      </>
    );

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
            <p className="subtitle">Main web app for Codex sessions, per-session notes, pairing, files, and browser-based remote control.</p>
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
          <a className="button ghost" href="/legacy" target="_blank" rel="noreferrer">
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

      <section className="meta-strip primary">
        <div className="meta-chip important">
          <span>Auth</span>
          <strong>{authSummary}</strong>
        </div>
        <div className="meta-chip important">
          <span>Network</span>
          <strong>{networkSummary}</strong>
        </div>
        <div className="meta-chip important">
          <span>Sessions</span>
          <strong>{sessionCountLabel}</strong>
        </div>
        <div className="meta-chip important">
          <span>Remote</span>
          <strong>{remoteControlSummary}</strong>
        </div>
        <div className="meta-chip important">
          <span>Build</span>
          <strong>{appVersionLabel} / {appModeLabel}</strong>
        </div>
      </section>

      <details className="meta-details">
        <summary>System Snapshot</summary>
        <div className="meta-strip secondary">
          <div className="meta-chip">
            <span>Status</span>
            <strong>{statusSnapshotSummary}</strong>
          </div>
          <div className="meta-chip">
            <span>Controls</span>
            <strong>Image insert path</strong>
          </div>
          <div className="meta-chip">
            <span>Output</span>
            <strong>{outputFeedSummary}</strong>
          </div>
          <div className="meta-chip">
            <span>Debug</span>
            <strong>{runningRuns} running | {totalEvents} events</strong>
          </div>
          <div className="meta-chip">
            <span>Connectivity</span>
            <strong>{connectivitySummary} | {installSummary}</strong>
          </div>
        </div>
      </details>

      <section className="status-strip" aria-live="polite">
        <span className={`status-pill ${errorMessage ? "error" : ""}`}>{errorMessage || statusMessage}</span>
        <span className="status-pill subtle">{connectivitySummary} | {outputFeedSummary}</span>
      </section>

      <main className="screen-shell" ref={screenShellRef} data-testid="screen-shell">
        <section className="action-strip" data-testid={`primary-actions-${activeTab}`}>
          <div className="action-strip-head">
            <strong>Primary Actions</strong>
            <span className="small">Focused controls for this tab</span>
          </div>
          <div className="action-strip-grid">{primaryActions}</div>
        </section>
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
                <span className="badge">Output {outputFeedState}</span>
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
                  <button
                    type="button"
                    className="button soft compact"
                    onClick={() => void onResumeLastSession()}
                    disabled={sessionBusy}
                  >
                    Resume Last
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

                <div className="session-summary-strip">
                  <p className="small">{visibleSessionCountLabel}</p>
                  <p className="small">
                    {sessionsMeta?.background_mode === "selected_only"
                      ? "Only the selected session stays live; background sessions use cached summaries."
                      : sessionCountLabel}
                  </p>
                </div>

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

                {sessionViewMode === "grouped" ? (
                  groupedSessions.map((group) => (
                    <div key={group.project} className="session-group">
                      <div className="session-group-head">
                        <strong>{group.project}</strong>
                        <span className="badge muted">{group.items.length}</span>
                      </div>
                      <div className="session-card-grid">{group.items.map((session) => renderSessionButton(session))}</div>
                    </div>
                  ))
                ) : (
                  <div className="session-card-grid">{filteredSessions.map((session) => renderSessionButton(session))}</div>
                )}
              </div>

              <div className="session-detail" data-testid="session-detail">
                {!selectedSessionInfo ? (
                  <div className="empty-state">
                    <h3>Select or create a session</h3>
                    <p>Screen output and prompt composer appear here.</p>
                  </div>
                ) : (
                  <SelectedSessionWorkspace
                    selectedSessionInfo={selectedSessionInfo}
                    outputFeedState={outputFeedState}
                    streamEnabled={streamEnabled}
                    streamProfile={streamProfile}
                    onToggleStream={onToggleSessionStream}
                    onStreamProfileChange={onStreamProfileChange}
                    sessionAutoFollow={sessionAutoFollow}
                    sessionUnreadCount={sessionUnreadCount}
                    onJumpToLive={onJumpToSessionLive}
                    sessionOutputRef={sessionOutputRef}
                    onSessionOutputScroll={onSessionOutputScroll}
                    sessionTranscriptChunks={sessionTranscriptChunks}
                    promptText={promptText}
                    onPromptTextChange={onPromptTextChange}
                    canSendPrompt={canSendPrompt}
                    sessionBusy={sessionBusy}
                    composerTelegramBusy={composerTelegramBusy}
                    composerTelegramDisabledReason={composerTelegramDisabledReason}
                    onSendComposerToTelegram={onComposerTelegramRequest}
                    onSendPrompt={onSendPrompt}
                    sessionImageInputRef={sessionImageInputRef}
                    sessionImageFile={sessionImageFile}
                    onSessionImageFileChange={onSessionImageFileChange}
                    sessionImagePrompt={sessionImagePrompt}
                    onSessionImagePromptChange={onSessionImagePromptChange}
                    onOpenImagePicker={onOpenSessionImagePicker}
                    onSendSessionImage={onSendSessionImage}
                    onRefreshSession={onRefreshSelectedSession}
                    onSendEnter={onSendEnter}
                    onSendBackspace={onSendBackspace}
                    onSendArrowKey={onSendArrowKey}
                    onInterrupt={onInterrupt}
                    onCtrlC={onCtrlC}
                    onCloseSession={onCloseSession}
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

            <div className="quick-open-card compact-card">
              <div className="row section-row">
                <div className="stack">
                  <h3>Advanced Utilities</h3>
                  <p className="small">Legacy transcript tools and one-shot utilities are hidden by default.</p>
                </div>
                <button
                  type="button"
                  className="button soft compact"
                  onClick={() => setShowLegacyThreadTools((current) => !current)}
                >
                  {showLegacyThreadTools ? "Hide Advanced Utilities" : "Show Advanced Utilities"}
                </button>
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
                      data-testid="threads-pane-select"
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
                    <button type="button" className="button soft compact" onClick={() => void onResumeLastTmux()} disabled={tmuxBusy || !selectedTmuxPane}>
                      Resume Last
                    </button>
                    <button type="button" className="button warn compact" onClick={() => void onInterruptTmuxPane()} disabled={tmuxBusy || !selectedTmuxPane}>
                      Interrupt
                    </button>
                    <button type="button" className="button danger compact" onClick={() => void onCloseTmuxSession()} disabled={tmuxBusy || !selectedTmuxPaneInfo}>
                      Close Session
                    </button>
                  </div>
                  <div className="row">
                    <button type="button" className="button soft compact" onClick={() => void onSendTmuxKey("up")} disabled={tmuxBusy || !selectedTmuxPane}>
                      Up
                    </button>
                    <button type="button" className="button soft compact" onClick={() => void onSendTmuxKey("down")} disabled={tmuxBusy || !selectedTmuxPane}>
                      Down
                    </button>
                    <button type="button" className="button soft compact" onClick={() => void onSendTmuxKey("left")} disabled={tmuxBusy || !selectedTmuxPane}>
                      Left
                    </button>
                    <button type="button" className="button soft compact" onClick={() => void onSendTmuxKey("right")} disabled={tmuxBusy || !selectedTmuxPane}>
                      Right
                    </button>
                    <button type="button" className="button soft compact" onClick={() => void onSendTmuxKey("enter")} disabled={tmuxBusy || !selectedTmuxPane}>
                      Enter
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
                          ? sessionTranscriptText || "(No live output yet)"
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
                <span className="badge muted">{desktopEnabled ? "control: on" : "control: off (view-only)"}</span>
              </div>
            </div>

            <div className="debug-layout full-width">
              <div className="debug-column">
                <div className="debug-block">
                  <h3>Desktop Remote</h3>
                  <div className={`mode-banner ${desktopEnabled ? "active" : "inactive"}`}>
                    <strong>{desktopEnabled ? "Control Enabled" : "View-only Mode"}</strong>
                    <span>{desktopEnabled ? "Tap stream and controls to interact." : "Live stream remains active. Input is locked for safety."}</span>
                  </div>
                  <div className="row">
                    <button type="button" className={`button ${desktopEnabled ? "warn" : ""}`} onClick={() => void onToggleDesktopMode()}>
                      {desktopEnabled ? "Disable Control" : "Enable Control"}
                    </button>
                    <button
                      type="button"
                      className="button soft compact"
                      data-testid="remote-fullscreen-toggle"
                      onClick={() => void onToggleDesktopFullscreen()}
                    >
                      {desktopFullscreen ? "Exit Fullscreen" : "Enter Fullscreen"}
                    </button>
                    <button
                      type="button"
                      className="button soft compact"
                      onClick={() => setDesktopTrackpadMode((current) => !current)}
                    >
                      Trackpad: {desktopTrackpadMode ? "On" : "Direct"}
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
                      <option value="ultra">Ultra (readable low-data)</option>
                      <option value="extreme">Extreme (lowest bandwidth, readable)</option>
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
                  <div className="remote-workspace">
                    <div className="remote-view-stack">
                      <div
                        ref={remoteStageRef}
                        className={`stream-wrap remote-stage${desktopFullscreen ? " fullscreen-active" : ""}`}
                        data-remote-gesture="true"
                        data-testid="remote-stage"
                      >
                        <div className="remote-stage-toolbar">
                          <span className="badge muted">{desktopTrackpadMode ? "Trackpad mode" : "Direct tap mode"}</span>
                          <span className="badge muted">{desktopFullscreen ? "Fullscreen" : "Windowed"}</span>
                        </div>
                        <img
                          ref={desktopFrameRef}
                          className="desktop-frame"
                          src={desktopStreamUrl}
                          alt="Desktop stream"
                          onClick={(event) => void onDesktopFrameTap(event)}
                          onContextMenu={(event) => void onDesktopContextMenu(event)}
                          onWheel={(event) => void onDesktopWheel(event)}
                          onPointerDown={(event) => void onDesktopPointerDown(event)}
                          onPointerMove={(event) => void onDesktopPointerMove(event)}
                          onPointerUp={(event) => void onDesktopPointerUp(event)}
                        />
                      </div>
                      <p className="small">
                        Live stream stays on in both modes. Fullscreen turns the browser into a tablet-friendly remote stage. Trackpad mode moves first and taps on release; Direct mode clicks exactly where you tap.
                      </p>
                    </div>

                    <div className="remote-control-stack">
                      <div className="remote-control-group">
                        <h4>Pointer Controls</h4>
                        <div className="row remote-mouse-controls">
                          <button type="button" className="button soft compact action-chip" data-short="L" onClick={() => void onDesktopClick("left")} disabled={desktopInteractionDisabled}>
                            <span className="btn-text">Left Click</span>
                          </button>
                          <button type="button" className="button soft compact action-chip" data-short="R" onClick={() => void onDesktopClick("right")} disabled={desktopInteractionDisabled}>
                            <span className="btn-text">Right Click</span>
                          </button>
                          <button type="button" className="button soft compact action-chip" data-short="2X" onClick={() => void onDesktopClick("left", true)} disabled={desktopInteractionDisabled}>
                            <span className="btn-text">Double</span>
                          </button>
                          <button type="button" className="button soft compact action-chip" data-short="UP" onClick={() => void onDesktopScroll(-240)} disabled={desktopInteractionDisabled}>
                            <span className="btn-text">Scroll Up</span>
                          </button>
                          <button type="button" className="button soft compact action-chip" data-short="DN" onClick={() => void onDesktopScroll(240)} disabled={desktopInteractionDisabled}>
                            <span className="btn-text">Scroll Down</span>
                          </button>
                        </div>
                      </div>
                      <div className="remote-control-group">
                        <h4>Text and Keyboard</h4>
                        <div className="row remote-text-controls">
                          <textarea
                            value={desktopTextInput}
                            onChange={(event) => setDesktopTextInput(event.target.value)}
                            rows={4}
                            placeholder={desktopFocusPoint ? "Type text for the focused desktop app" : "Tap the remote desktop to focus a target first"}
                            disabled={desktopInteractionDisabled}
                          />
                          <button
                            type="button"
                            className="button soft compact action-chip"
                            data-short="SEND"
                            onClick={() => void onDesktopSendText()}
                            disabled={desktopInteractionDisabled || !desktopTextInput || !desktopFocusPoint}
                          >
                            <span className="btn-text">Send Text</span>
                          </button>
                          <button
                            type="button"
                            className="button soft compact action-chip"
                            data-short="TYPE"
                            onClick={() => void onDesktopPasteClipboard()}
                            disabled={desktopInteractionDisabled || !desktopFocusPoint}
                            title={desktopFocusPoint ? "Load clipboard text into the remote text box." : "Tap the remote desktop once to focus a target first."}
                          >
                            <span className="btn-text">Paste Into Box</span>
                          </button>
                        </div>
                        <p className="small">{desktopFocusSummary}</p>
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
                            <option value="win+tab">Win+Tab</option>
                            <option value="alt+tab">Alt+Tab</option>
                            <option value="ctrl+a">Ctrl+A</option>
                            <option value="ctrl+c">Ctrl+C</option>
                            <option value="ctrl+v">Ctrl+V</option>
                          </select>
                          <button type="button" className="button soft compact action-chip" data-short="KEY" onClick={() => void onDesktopSendKey()} disabled={desktopInteractionDisabled}>
                            <span className="btn-glyph" aria-hidden="true">⌨</span>
                            <span className="btn-text">Send Key</span>
                          </button>
                        </div>
                        <div className="remote-shortcut-grid">
                          <div className="arrow-cluster" role="group" aria-label="Remote arrow keys">
                            <span className="arrow-cluster-gap" aria-hidden="true" />
                            <button type="button" className="button soft compact arrow-key" aria-label="Up" onClick={() => void onDesktopSendQuickKey("up")} disabled={desktopInteractionDisabled}>
                              <span className="btn-text" aria-hidden="true">↑</span>
                            </button>
                            <span className="arrow-cluster-gap" aria-hidden="true" />
                            <button type="button" className="button soft compact arrow-key" aria-label="Left" onClick={() => void onDesktopSendQuickKey("left")} disabled={desktopInteractionDisabled}>
                              <span className="btn-text" aria-hidden="true">←</span>
                            </button>
                            <button type="button" className="button soft compact arrow-key" aria-label="Down" onClick={() => void onDesktopSendQuickKey("down")} disabled={desktopInteractionDisabled}>
                              <span className="btn-text" aria-hidden="true">↓</span>
                            </button>
                            <button type="button" className="button soft compact arrow-key" aria-label="Right" onClick={() => void onDesktopSendQuickKey("right")} disabled={desktopInteractionDisabled}>
                              <span className="btn-text" aria-hidden="true">→</span>
                            </button>
                          </div>
                          <div className="remote-quickkeys" role="group" aria-label="Remote quick keys">
                            <button type="button" className="button soft compact action-chip" onClick={() => void onDesktopSendQuickKey("tab")} disabled={desktopInteractionDisabled}>
                              <span className="btn-glyph" aria-hidden="true">⇥</span>
                              <span className="btn-text">Tab</span>
                            </button>
                            <button type="button" className="button soft compact action-chip" onClick={() => void onDesktopSendQuickKey("esc")} disabled={desktopInteractionDisabled}>
                              <span className="btn-glyph" aria-hidden="true">⎋</span>
                              <span className="btn-text">Esc</span>
                            </button>
                            <button type="button" className="button soft compact action-chip" onClick={() => void onDesktopSendQuickKey("enter")} disabled={desktopInteractionDisabled}>
                              <span className="btn-glyph" aria-hidden="true">↵</span>
                              <span className="btn-text">Enter</span>
                            </button>
                            <button type="button" className="button soft compact action-chip" onClick={() => void onDesktopSendQuickKey("win+tab")} disabled={desktopInteractionDisabled}>
                              <span className="btn-text">All Tabs</span>
                            </button>
                            <button type="button" className="button soft compact action-chip" onClick={() => void onDesktopSendQuickKey("alt+tab")} disabled={desktopInteractionDisabled}>
                              <span className="btn-text">Switch Tab</span>
                            </button>
                            <button type="button" className="button soft compact action-chip" onClick={() => void onDesktopSendQuickKey("ctrl+c")} disabled={desktopInteractionDisabled}>
                              <span className="btn-text">Ctrl+C</span>
                            </button>
                            <button type="button" className="button soft compact action-chip" onClick={() => void onDesktopSendQuickKey("ctrl+v")} disabled={desktopInteractionDisabled}>
                              <span className="btn-text">Ctrl+V</span>
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
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

                <div className="debug-block" data-testid="power-card">
                  <div className="session-files-head">
                    <div>
                      <h3>Power Control</h3>
                      <p className="small">Shutdown controls live here. True boot-from-off is routed through the wake relay and Telegram.</p>
                    </div>
                    <button type="button" className="button soft compact" onClick={() => void refreshPowerStatus()} disabled={powerBusy}>
                      Refresh Power
                    </button>
                  </div>
                  <div className="row">
                    <span className="badge">{powerStatus?.online ? "host: online" : "host: unknown"}</span>
                    <span className="badge muted">{powerRelayBadge}</span>
                    <span className={`badge power-readiness ${powerWakeReadiness}`}>{powerWakeBadge}</span>
                  </div>
                  <p className="small">{powerStatus?.relay_detail || "Wake relay diagnostics are not available yet."}</p>
                  {powerWakeWarning && powerWakeReadiness !== "ready" ? (
                    <div className={`power-warning-banner ${powerWakeReadiness}`} data-testid="power-warning-banner">
                      <strong>Wake is best effort on this machine</strong>
                      <p>{powerWakeWarning}</p>
                    </div>
                  ) : null}
                  <div className="remote-power-grid">
                    {(powerStatus?.actions || []).map((actionName) => {
                      const powerAction = actionName as PowerActionName;
                      return (
                        <button
                          key={powerAction}
                          type="button"
                          className={`button compact ${powerAction === "shutdown" || powerAction === "restart" ? "warn" : "soft"}`}
                          data-testid={`power-action-${powerAction}`}
                          onClick={() => void onRequestPowerAction(powerAction)}
                          disabled={powerBusy}
                        >
                          {POWER_ACTION_LABELS[powerAction]}
                        </button>
                      );
                    })}
                  </div>
                  {powerConfirmAction && powerConfirmToken ? (
                    <div className="power-confirm-banner" data-testid="power-confirm-banner">
                      <strong>Confirm {POWER_ACTION_LABELS[powerConfirmAction]}</strong>
                      <span>This action is armed for {powerConfirmExpiresIn}s.</span>
                      <div className="row">
                        <button
                          type="button"
                          className="button warn compact"
                          data-testid="power-confirm-accept"
                          onClick={() => void onRequestPowerAction(powerConfirmAction, powerConfirmToken)}
                          disabled={powerBusy}
                        >
                          Confirm {POWER_ACTION_LABELS[powerConfirmAction]}
                        </button>
                        <button
                          type="button"
                          className="button soft compact"
                          data-testid="power-confirm-cancel"
                          onClick={onCancelPowerConfirmation}
                          disabled={powerBusy}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : null}
                  <div className="remote-power-diagnostics">
                    <label className="field">
                      <span>Wake Instruction</span>
                      <div className="row">
                        <input type="text" readOnly value={powerWakeInstruction} />
                        <button
                          type="button"
                          className="button soft compact"
                          onClick={() => void onCopyPowerValue(powerWakeInstruction, "Wake instruction")}
                        >
                          Copy
                        </button>
                      </div>
                    </label>
                    <label className="field">
                      <span>Primary MAC</span>
                      <div className="row">
                        <input type="text" readOnly value={powerStatus?.primary_mac || netInfo?.primary_mac || ""} />
                        <button
                          type="button"
                          className="button soft compact"
                          onClick={() => void onCopyPowerValue(powerStatus?.primary_mac || netInfo?.primary_mac || "", "Primary MAC")}
                        >
                          Copy
                        </button>
                      </div>
                    </label>
                    <p className="small">
                      Wake candidates: <strong>{(powerStatus?.wake_candidate_macs || netInfo?.wake_candidate_macs || []).join(", ") || "n/a"}</strong>
                    </p>
                    <p className="small">
                      Wake surface: <strong>{powerStatus?.wake_surface || "telegram"}</strong>. Preferred transport: <strong>{powerWakeTransport}</strong>. Use <strong>{powerWakeInstruction}</strong> from the dedicated wake bot when the laptop is off.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </section>
        ) : null}

        {activeTab === "pair" ? (
          <Suspense fallback={<section className={screenCardClassName} data-testid="tab-panel-pair"><p className="small">Loading pair tab...</p></section>}>
            <PairTab
              screenCardClassName={screenCardClassName}
              routeHint={routeHint}
              prettyRouteLabel={prettyRouteLabel}
              isLocalBrowser={isLocalBrowser}
              controllerBase={controllerBase}
              setControllerBase={setControllerBase}
              onRouteHintChange={onRouteHintChange}
              netInfo={netInfo}
              tailscaleRouteUnavailable={tailscaleRouteUnavailable}
              pairBusy={pairBusy}
              onGeneratePairing={() => void onGeneratePairing()}
              refreshNet={() => void refreshNet()}
              onPairExchange={() => void onPairExchange()}
              pairCode={pairCode}
              pairExpiry={pairExpiry}
              pairLink={pairLink}
              onCopyPairLink={() => void onCopyPairLink()}
              onOpenPairLink={onOpenPairLink}
              pairQrUrl={pairQrUrl}
            />
          </Suspense>
        ) : null}

        {activeTab === "settings" ? (
          <Suspense fallback={<section className={screenCardClassName} data-testid="tab-panel-settings"><p className="small">Loading settings...</p></section>}>
            <SettingsTab
              screenCardClassName={screenCardClassName}
              authLoading={authLoading}
              auth={auth}
              authBusy={authBusy}
              onBootstrapLocalAuth={() => void onBootstrapLocalAuth()}
              tokenInput={tokenInput}
              setTokenInput={setTokenInput}
              onLogin={() => void onLogin()}
              refreshAuth={() => void refreshAuth()}
              onLogout={() => void onLogout()}
              touchComfortMode={touchComfortMode}
              setTouchComfortMode={setTouchComfortMode}
              compactTranscript={compactTranscript}
              setCompactTranscript={setCompactTranscript}
              themeMode={themeMode}
              setThemeMode={setThemeMode}
              parseThemeMode={parseThemeMode}
              resolvedTheme={resolvedTheme}
              controllerRouteSummary={controllerRouteSummary}
              controllerRouteSeverity={controllerRouteSeverity}
              controllerRouteAdvice={controllerRouteAdvice}
              controllerBase={controllerBase}
              routeHint={routeHint}
              prettyRouteLabel={prettyRouteLabel}
              netInfo={netInfo}
              refreshNet={() => void refreshNet()}
            />
          </Suspense>
        ) : null}

        {activeTab === "debug" ? (
          <Suspense fallback={<section className={screenCardClassName} data-testid="tab-panel-debug"><p className="small">Loading debug timeline...</p></section>}>
            <DebugTab
              screenCardClassName={screenCardClassName}
              totalEvents={totalEvents}
              errorEvents={errorEvents}
              debugRuns={debugRuns}
              debugLoading={debugLoading}
              refreshDebugRuns={() => void refreshDebugRuns()}
              selectedRunId={selectedRunId}
              setSelectedRunId={setSelectedRunId}
              eventLog={eventLog}
              ipcFilter={ipcFilter}
              setIpcFilter={setIpcFilter}
              filteredIpcHistory={filteredIpcHistory}
              ipcSearch={ipcSearch}
              setIpcSearch={setIpcSearch}
              onExportIpcHistory={onExportIpcHistory}
              ipcHistoryCount={ipcHistory.length}
              onClearIpcHistory={onClearIpcHistory}
              selectedIpcEvent={selectedIpcEvent}
              setSelectedIpcId={setSelectedIpcId}
              onCopySelectedIpc={() => void onCopySelectedIpc()}
              selectedRunLoading={selectedRunLoading}
              selectedRun={selectedRun}
              formatClock={formatClock}
            />
          </Suspense>
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
