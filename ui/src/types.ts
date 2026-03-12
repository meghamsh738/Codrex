export type SessionState = "starting" | "idle" | "busy" | "running" | "waiting" | "done" | "error" | "recovering";

export interface AuthStatus {
  ok: boolean;
  auth_required: boolean;
  authenticated: boolean;
}

export type AppRuntimeResult = Omit<BasicResult, "session_file"> & {
  version?: string;
  launcher_mode?: string;
  repo_root?: string;
  runtime_dir?: string;
  state_dir?: string;
  session_file?: string;
  session_present?: boolean;
  session?: Record<string, unknown> | null;
  controller_port?: number | null;
  controller_origin?: string;
  ui_mode?: string;
  build_present?: boolean;
};

export interface SharedFileInfo {
  id: string;
  title: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  created_at: number;
  expires_at: number;
  created_by?: string;
  is_image?: boolean;
  wsl_path: string;
  download_url: string;
  session?: string;
  item_kind?: "file" | "directory";
  source_kind?: string;
  windows_path?: string;
  display_path?: string;
}

export interface TelegramDeliveryResult {
  ok: boolean;
  error?: string;
  detail?: string;
  message_id?: number;
  chat_id?: string;
  file_name?: string;
  size_bytes?: number;
}

export interface BasicResult {
  ok: boolean;
  error?: string;
  detail?: string;
  shared_file?: SharedFileInfo;
  session_file?: SharedFileInfo | null;
  telegram?: TelegramDeliveryResult | null;
}

export interface SharedFilesResult extends BasicResult {
  items?: SharedFileInfo[];
  item?: SharedFileInfo;
  share_id?: string;
}

export interface TelegramStatusResult extends BasicResult {
  configured?: boolean;
  default_send?: boolean;
  chat_id_masked?: string;
  bot_token_masked?: string;
  api_base?: string;
  max_file_mb?: number;
}

export interface NetInfo {
  ok: boolean;
  lan_ip: string;
  tailscale_ip: string;
  primary_mac?: string;
  wake_candidate_macs?: string[];
  wake_supported?: boolean;
}

export interface PairCreateResult extends BasicResult {
  code?: string;
  expires_in?: number;
}

export interface SessionInfo {
  session: string;
  pane_id: string;
  current_command: string;
  cwd: string;
  state: SessionState;
  updated_at: number;
  last_seen_at?: number;
  snippet: string;
  model?: string;
  reasoning_effort?: string;
}

export interface SessionsMeta {
  total_sessions?: number;
  background_mode?: string;
}

export interface SessionsResult extends BasicResult {
  sessions?: SessionInfo[];
  meta?: SessionsMeta;
}

export interface SessionCreateResult extends BasicResult {
  session?: string;
  cwd?: string;
  model?: string;
  reasoning_effort?: string;
  resume_last?: boolean;
}

export interface SessionProfileApplyResult extends BasicResult {
  session?: string;
  model?: string;
  reasoning_effort?: string;
  applied_command?: string;
}

export interface CodexOptionsResult extends BasicResult {
  models?: string[];
  default_model?: string;
  reasoning_efforts?: string[];
  default_reasoning_effort?: string;
}

export interface SessionCloseResult extends BasicResult {
  session?: string;
}

export interface SessionImageResult extends BasicResult {
  session?: string;
  saved_path?: string;
  paste_attempted?: boolean;
  paste_ok?: boolean;
  paste_error?: string;
  delivery_mode?: "desktop_clipboard" | "session_path" | "insert_path";
}

export interface SessionScreenResult extends BasicResult {
  session?: string;
  pane_id?: string;
  current_command?: string;
  state?: SessionState;
  text?: string;
}

export interface TmuxHealthResult extends BasicResult {
  state?: "ok" | "empty" | "no_server";
  count?: number;
  sessions?: string[];
}

export interface TmuxSessionResult extends BasicResult {
  name?: string | null;
  session?: string;
}

export interface TmuxPaneInfo {
  session: string;
  window_index: string;
  pane_index: string;
  pane_id: string;
  active: boolean;
  current_command: string;
  current_path: string;
}

export interface TmuxPanesResult extends BasicResult {
  panes?: TmuxPaneInfo[];
}

export interface TmuxPaneScreenResult extends BasicResult {
  pane_id?: string;
  text?: string;
}

export interface DesktopInfoResult extends BasicResult {
  enabled?: boolean;
  left?: number;
  top?: number;
  width?: number;
  height?: number;
}

export interface DesktopModeResult extends BasicResult {
  enabled?: boolean;
}

export interface DesktopInputResult extends BasicResult {
  x?: number;
  y?: number;
  sent?: number;
  key?: string;
  delta?: number;
}

export interface PowerStatusResult extends BasicResult {
  online?: boolean;
  actions?: string[];
  confirm_required_actions?: string[];
  wake_surface?: string;
  wake_command?: string;
  wake_instruction?: string;
  wake_readiness?: "ready" | "partial" | "unsupported";
  wake_warning?: string;
  wake_transport_hint?: "ethernet" | "wifi" | "unknown";
  wake_relay_configured?: boolean;
  relay_reachable?: boolean;
  relay_detail?: string;
  primary_mac?: string;
  wake_candidate_macs?: string[];
  wake_supported?: boolean;
}

export interface PowerActionResult extends BasicResult {
  action?: string;
  accepted?: boolean;
  confirm_required?: boolean;
  confirm_token?: string;
  confirm_expires_in?: number;
  scheduled_at?: number;
}

export interface WslUploadResult extends BasicResult {
  saved_path?: string;
}

export interface SessionFilesResult extends BasicResult {
  session?: string;
  items?: SharedFileInfo[];
  item?: SharedFileInfo;
  deleted_source?: boolean;
}

export interface SessionNoteInfo {
  session: string;
  content: string;
  created_at: number;
  updated_at: number;
  last_response_snapshot?: string;
}

export interface SessionNotesResult extends BasicResult {
  session?: string;
  notes?: SessionNoteInfo;
  appended_text?: string;
}

export interface BrowserRootInfo {
  id: string;
  label: string;
  path: string;
}

export interface BrowserEntryInfo {
  name: string;
  kind: "file" | "directory";
  display_path: string;
  wsl_path: string;
  windows_path?: string;
  size_bytes: number;
  mtime: number;
}

export interface BrowserListResult extends BasicResult {
  root?: BrowserRootInfo;
  roots?: BrowserRootInfo[];
  current_path?: string;
  current_relative_path?: string;
  display_path?: string;
  windows_path?: string;
  items?: BrowserEntryInfo[];
}

export type SessionStreamEventType = "hello" | "snapshot" | "append" | "replace" | "status" | "keepalive" | "error";

export interface SessionStreamEvent {
  ok?: boolean;
  session: string;
  pane_id: string;
  seq: number;
  type: SessionStreamEventType;
  text: string;
  detail?: string;
  ts?: number;
  profile?: string;
  state?: SessionState;
  current_command?: string;
}

export type ThreadRole = "user" | "assistant" | "system";

export interface ThreadInfo {
  id: string;
  title: string;
  session: string;
  created_at: number;
  updated_at: number;
}

export interface ThreadMessageInfo {
  id: string;
  thread_id: string;
  role: ThreadRole;
  text: string;
  at: number;
}

export interface ThreadsStoreResult extends BasicResult {
  threads?: ThreadInfo[];
  messages?: Record<string, ThreadMessageInfo[]>;
}

export interface ThreadRecordResult extends BasicResult {
  thread?: ThreadInfo;
}

export interface ThreadDeleteResult extends BasicResult {
  thread_id?: string;
}

export interface ThreadMessageResult extends BasicResult {
  message?: ThreadMessageInfo;
}

export type CodexRunStatus = "running" | "done" | "error";

export interface CodexRunSummary {
  id: string;
  status: CodexRunStatus;
  duration_s?: number | null;
  prompt?: string;
}

export interface CodexRunsResult extends BasicResult {
  runs?: CodexRunSummary[];
}

export interface CodexRunDetail extends BasicResult, CodexRunSummary {
  created_at?: number;
  output?: string;
  exit_code?: number | null;
  finished_at?: number | null;
}

export interface CodexExecStartResult extends BasicResult {
  id?: string;
}
