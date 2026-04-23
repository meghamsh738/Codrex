export type SessionState = "starting" | "idle" | "busy" | "running" | "waiting" | "done" | "error" | "recovering";
export type LoopPreset = "infinite" | "await-reply" | "completion-checks" | "max-turns-1" | "max-turns-2" | "max-turns-3";
export type LoopOverrideMode = "inherit" | "off" | LoopPreset;

export interface SessionLoopInfo {
  override_mode: LoopOverrideMode;
  effective_preset?: LoopPreset | null;
  remaining_turns?: number | null;
  awaiting_reply?: boolean;
  last_terminal_state?: string;
  last_terminal_at?: number;
  last_action?: string;
  last_action_detail?: string;
  last_action_at?: number;
  last_notification_at?: number;
  last_continue_at?: number;
  last_reply_at?: number;
  last_prompt_at?: number;
  last_snapshot?: string;
}

export interface LoopSettingsInfo {
  default_prompt: string;
  global_preset?: LoopPreset | null;
  completion_checks?: string[];
  telegram_configured?: boolean;
}

export interface LoopWorkerInfo {
  alive?: boolean;
  last_cycle_at?: number;
  last_telegram_poll_at?: number;
  last_error?: string;
  last_error_at?: number;
}

export interface AuthStatus {
  ok: boolean;
  auth_required: boolean;
  authenticated: boolean;
}

export type RouteProvider = "preferred" | "tailscale" | "netbird" | "lan" | "localhost" | "current" | "unknown";
export type RouteState = "connected" | "local_only" | "unavailable" | "unknown";

export interface RouteOriginInfo {
  provider: Exclude<RouteProvider, "preferred" | "current" | "unknown">;
  host: string;
  origin: string;
  label?: string;
  private?: boolean;
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
  desktop_stream_transport?: string;
  desktop_stream_fallback?: string;
  desktop_webrtc_available?: boolean;
  desktop_webrtc_enabled?: boolean;
  desktop_webrtc_detail?: string;
  available_origins?: RouteOriginInfo[];
  preferred_origin?: string;
  route_provider?: RouteProvider;
  route_state?: RouteState;
  controller_mode?: "controller-only" | "sessions-running";
  sessions_runtime_state?: "running" | "stopped" | "missing" | "unknown";
  sessions_runtime_detail?: string;
  sessions_runtime_distro?: string;
  sessions_runtime_can_start?: boolean;
  sessions_runtime_can_stop?: boolean;
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
  netbird_ip?: string;
  available_origins?: RouteOriginInfo[];
  preferred_origin?: string;
  route_provider?: RouteProvider;
  route_state?: RouteState;
  primary_mac?: string;
  wake_candidate_macs?: string[];
  wake_supported?: boolean;
}

export interface CodexRuntimeStatusResult extends BasicResult {
  state?: "running" | "stopped" | "missing" | "unknown";
  detail?: string;
  distro?: string;
  can_start?: boolean;
  can_stop?: boolean;
  profiles?: string[];
  default_profile?: string;
  cwd?: string;
  read_only?: boolean;
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
  busy_source?: "idle" | "desktop" | "sidecar";
  updated_at: number;
  last_seen_at?: number;
  snippet: string;
  model?: string;
  reasoning_effort?: string;
  active?: boolean;
  closed_at?: number;
  can_resume?: boolean;
  resume_id?: string;
  title?: string;
  raw_title?: string;
  raw_snippet?: string;
  source?: string;
  read_only?: boolean;
  loop?: SessionLoopInfo;
  desktop_codex_meta?: {
    kind?: "project" | "chat";
    source_label?: string;
    group_id?: string;
    group_label?: string;
    group_hint?: string;
    workspace_label?: string;
    workspace_hint?: string;
    workspace_path?: string;
    display_title?: string;
    full_title?: string;
    preview?: string;
    details?: string;
    git_branch?: string;
    git_origin_url?: string;
    agent_nickname?: string;
    agent_role?: string;
    launch_issue?: {
      active?: boolean;
      path?: string;
      path_label?: string;
    };
  };
}

export interface SessionsMeta {
  total_sessions?: number;
  total_recent_closed?: number;
  background_mode?: string;
  summary_updated_at?: number;
}

export interface SessionsResult extends BasicResult {
  sessions?: SessionInfo[];
  recent_closed?: SessionInfo[];
  meta?: SessionsMeta;
}

export interface LoopStatusResult extends BasicResult {
  settings?: LoopSettingsInfo;
  worker?: LoopWorkerInfo;
}

export interface SessionCreateResult extends BasicResult {
  session?: string;
  cwd?: string;
  model?: string;
  reasoning_effort?: string;
  resume_last?: boolean;
  resume_id?: string;
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

export interface DesktopPasteImageResult extends BasicResult {
  saved_path?: string;
  paste_ok?: boolean;
  target_process?: string;
  target_family?: string;
  target_label?: string;
  paste_strategy?: string;
}

export interface SessionScreenResult extends BasicResult {
  session?: string;
  pane_id?: string;
  current_command?: string;
  state?: SessionState;
  text?: string;
  title?: string;
  read_only?: boolean;
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
  active_target_id?: string;
  alt_held?: boolean;
  perf_mode_enabled?: boolean;
  perf_mode_active?: boolean;
  desktop_stream_transport?: string;
  desktop_stream_fallback?: string;
  desktop_webrtc_available?: boolean;
  desktop_webrtc_enabled?: boolean;
  desktop_webrtc_detail?: string;
}

export interface DesktopTargetInfo {
  id: string;
  label: string;
  kind?: string;
  virtual?: boolean;
  physical?: boolean;
  privacy_compatible?: boolean;
  selected?: boolean;
  left?: number;
  top?: number;
  width?: number;
  height?: number;
}

export interface DesktopTargetsResult extends BasicResult {
  targets?: DesktopTargetInfo[];
  active_target?: DesktopTargetInfo | null;
  virtual_supported?: boolean;
  virtual_enabled?: boolean;
  detail?: string;
}

export interface PrivacyLockStatusResult extends BasicResult {
  supported?: boolean;
  detail?: string;
  default_mode?: string;
  pin_configured?: boolean;
  active?: boolean;
  mode?: string;
  display_scope?: string;
  owner_device_id?: string;
  owner_device_name?: string;
  locked_at?: number;
  updated_at?: number;
  helper_ready?: boolean;
  helper_error?: string;
  last_unlock_source?: string;
  soft_reveal_until?: number;
  virtual_target_available?: boolean;
  previous_target_id?: string;
  active_target_id?: string;
  virtual_target_id?: string;
}

export interface DesktopStreamCapabilitiesResult extends BasicResult {
  preferred_transport?: string;
  fallback_transport?: string;
  webrtc_available?: boolean;
  webrtc_enabled?: boolean;
  webrtc_detail?: string;
}

export interface DesktopWebrtcSessionDescription {
  type: string;
  sdp: string;
}

export interface DesktopWebrtcOfferResult extends BasicResult {
  session_id?: string;
  answer?: DesktopWebrtcSessionDescription;
  transport?: string;
  fallback?: string;
}

export interface DesktopModeResult extends BasicResult {
  enabled?: boolean;
  alt_held?: boolean;
  perf_mode_enabled?: boolean;
  perf_mode_active?: boolean;
}

export interface DesktopInputResult extends BasicResult {
  x?: number;
  y?: number;
  sent?: number;
  key?: string;
  delta?: number;
  path?: string;
  paths?: string[];
  count?: number;
  alt_held?: boolean;
  perf_mode_enabled?: boolean;
  perf_mode_active?: boolean;
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

export interface HostTransferResult extends BasicResult {
  saved_path?: string;
  target_dir?: string;
  destination_mode?: string;
  focused_path?: string;
  selected_path?: string;
  post_action?: "open" | "reveal" | "";
}

export interface OpenPathResult extends BasicResult {
  path?: string;
  normalized_path?: string;
  opened_path?: string;
  item_kind?: "file" | "directory";
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
