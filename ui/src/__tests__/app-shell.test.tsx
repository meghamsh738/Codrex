import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import * as api from "../api";
import type { SessionInfo } from "../types";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    appendLatestSessionNotes: vi.fn(),
    buildDesktopShotUrl: vi.fn(() => "/desktop/shot?ts=1"),
    buildDesktopStreamUrl: vi.fn(() => "/desktop/stream?fps=3&level=3"),
    buildPairConsumeUrl: vi.fn(() => "http://controller/auth/pair/consume?code=abc123"),
    buildPairQrPngUrl: vi.fn(() => "http://controller/auth/pair/qr.png?data=abc123"),
    buildSessionStreamUrl: vi.fn(() => "ws://controller/codex/session/codex_demo/ws?profile=balanced"),
    buildScreenshotUrl: vi.fn(() => "/shot?ts=1"),
    buildSuggestedControllerUrl: vi.fn(() => "http://127.0.0.1:8787"),
    buildWslDownloadUrl: vi.fn(() => "/wsl/file?path=/tmp/demo.txt"),
    bootstrapLocalAuth: vi.fn(),
    closeSession: vi.fn(),
    closeTmuxSession: vi.fn(),
    createPairCode: vi.fn(),
    createSessionWithOptions: vi.fn(),
    createTmuxSession: vi.fn(),
    ctrlcSession: vi.fn(),
    deleteSessionFile: vi.fn(),
    desktopClick: vi.fn(),
    desktopMove: vi.fn(),
    desktopScroll: vi.fn(),
    desktopSendKey: vi.fn(),
    desktopSendText: vi.fn(),
    exchangePairCode: vi.fn(),
    getAppRuntime: vi.fn(),
    getAuthStatus: vi.fn(),
    getCodexOptions: vi.fn(),
    getCodexRun: vi.fn(),
    getCodexRuns: vi.fn(),
    getDesktopInfo: vi.fn(),
    getNetInfo: vi.fn(),
    getPowerStatus: vi.fn(),
    getTelegramStatus: vi.fn(),
    listBrowseEntries: vi.fn(),
    getSessionScreen: vi.fn(),
    getSessions: vi.fn(),
    getThreadStore: vi.fn(),
    getTmuxHealth: vi.fn(),
    getTmuxPaneScreen: vi.fn(),
    getTmuxPanes: vi.fn(),
    getSessionNotes: vi.fn(),
    interruptPane: vi.fn(),
    interruptSession: vi.fn(),
    listSessionFiles: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    reportIpcEvent: vi.fn(),
    registerSessionFile: vi.fn(),
    saveSessionNotes: vi.fn(),
    sendSessionFileToTelegram: vi.fn(),
    sendSessionImage: vi.fn(),
    sendPowerAction: vi.fn(),
    addThreadRecordMessage: vi.fn(),
    createThreadRecord: vi.fn(),
    deleteThreadRecord: vi.fn(),
    sendSessionKey: vi.fn(),
    sendToPaneKey: vi.fn(),
    sendToPane: vi.fn(),
    sendToSession: vi.fn(),
    setDesktopMode: vi.fn(),
    setIpcObserver: vi.fn(),
    startCodexExec: vi.fn(),
    updateThreadRecord: vi.fn(),
    uploadSessionFile: vi.fn(),
    uploadWslFile: vi.fn(),
  };
});

const getAuthStatusMock = vi.mocked(api.getAuthStatus);
const getAppRuntimeMock = vi.mocked(api.getAppRuntime);
const getCodexRunMock = vi.mocked(api.getCodexRun);
const getCodexRunsMock = vi.mocked(api.getCodexRuns);
const getCodexOptionsMock = vi.mocked(api.getCodexOptions);
const getNetInfoMock = vi.mocked(api.getNetInfo);
const getTelegramStatusMock = vi.mocked(api.getTelegramStatus);
const getSessionsMock = vi.mocked(api.getSessions);
const getSessionScreenMock = vi.mocked(api.getSessionScreen);
const listBrowseEntriesMock = vi.mocked(api.listBrowseEntries);
const listSessionFilesMock = vi.mocked(api.listSessionFiles);
const getThreadStoreMock = vi.mocked(api.getThreadStore);
const createSessionMock = vi.mocked(api.createSessionWithOptions);
const registerSessionFileMock = vi.mocked(api.registerSessionFile);
const deleteSessionFileMock = vi.mocked(api.deleteSessionFile);
const sendSessionFileToTelegramMock = vi.mocked(api.sendSessionFileToTelegram);
const createThreadRecordMock = vi.mocked(api.createThreadRecord);
const updateThreadRecordMock = vi.mocked(api.updateThreadRecord);
const deleteThreadRecordMock = vi.mocked(api.deleteThreadRecord);
const addThreadRecordMessageMock = vi.mocked(api.addThreadRecordMessage);
const loginMock = vi.mocked(api.login);
const bootstrapLocalAuthMock = vi.mocked(api.bootstrapLocalAuth);
const logoutMock = vi.mocked(api.logout);
const createPairCodeMock = vi.mocked(api.createPairCode);
const exchangePairCodeMock = vi.mocked(api.exchangePairCode);
const interruptSessionMock = vi.mocked(api.interruptSession);
const ctrlcSessionMock = vi.mocked(api.ctrlcSession);
const sendSessionKeyMock = vi.mocked(api.sendSessionKey);
const sendToSessionMock = vi.mocked(api.sendToSession);
const getTmuxHealthMock = vi.mocked(api.getTmuxHealth);
const getTmuxPanesMock = vi.mocked(api.getTmuxPanes);
const getTmuxPaneScreenMock = vi.mocked(api.getTmuxPaneScreen);
const getDesktopInfoMock = vi.mocked(api.getDesktopInfo);
const getPowerStatusMock = vi.mocked(api.getPowerStatus);
const setDesktopModeMock = vi.mocked(api.setDesktopMode);
const desktopClickMock = vi.mocked(api.desktopClick);
const desktopMoveMock = vi.mocked(api.desktopMove);
const desktopScrollMock = vi.mocked(api.desktopScroll);
const desktopSendTextMock = vi.mocked(api.desktopSendText);
const desktopSendKeyMock = vi.mocked(api.desktopSendKey);
const createTmuxSessionMock = vi.mocked(api.createTmuxSession);
const closeTmuxSessionMock = vi.mocked(api.closeTmuxSession);
const sendToPaneMock = vi.mocked(api.sendToPane);
const sendToPaneKeyMock = vi.mocked(api.sendToPaneKey);
const interruptPaneMock = vi.mocked(api.interruptPane);
const closeSessionMock = vi.mocked(api.closeSession);
const getSessionNotesMock = vi.mocked(api.getSessionNotes);
const saveSessionNotesMock = vi.mocked(api.saveSessionNotes);
const appendLatestSessionNotesMock = vi.mocked(api.appendLatestSessionNotes);
const sendSessionImageMock = vi.mocked(api.sendSessionImage);
const sendPowerActionMock = vi.mocked(api.sendPowerAction);
const uploadSessionFileMock = vi.mocked(api.uploadSessionFile);
const startCodexExecMock = vi.mocked(api.startCodexExec);
const setIpcObserverMock = vi.mocked(api.setIpcObserver);
const uploadWslFileMock = vi.mocked(api.uploadWslFile);
const clipboardWriteTextMock = vi.fn();

function setupDefaultMocks(): void {
  window.localStorage.removeItem("codrex.ui.controller_base.v1");
  window.localStorage.removeItem("codrex.ui.stream_enabled.v1");
  window.localStorage.removeItem("codrex.ui.selected_session.v1");
  window.localStorage.removeItem("codrex.ui.session_query.v1");
  window.localStorage.removeItem("codrex.ui.session_project_filter.v1");
  window.localStorage.removeItem("codrex.ui.session_workspace_pane.v1");
  window.localStorage.removeItem("codrex.ui.threads.v2");
  window.localStorage.removeItem("codrex.ui.thread_messages.v2");
  window.localStorage.removeItem("codrex.ui.thread_messages.v1");

  getAuthStatusMock.mockResolvedValue({
    ok: true,
    auth_required: true,
    authenticated: false,
  });
  getAppRuntimeMock.mockResolvedValue({
    ok: true,
    version: "1.5.0",
    ui_mode: "built",
    build_present: true,
    controller_port: 48787,
    controller_origin: "http://127.0.0.1:48787",
  });
  getNetInfoMock.mockResolvedValue({
    ok: true,
    lan_ip: "192.168.1.15",
    tailscale_ip: "100.64.0.9",
  });
  getTelegramStatusMock.mockResolvedValue({
    ok: true,
    configured: false,
  });
  getSessionsMock.mockResolvedValue({
    ok: true,
    sessions: [],
  });
  getCodexRunsMock.mockResolvedValue({
    ok: true,
    runs: [],
  });
  getCodexOptionsMock.mockResolvedValue({
    ok: true,
    models: ["gpt-5-codex", "gpt-5"],
    default_model: "gpt-5-codex",
    reasoning_efforts: ["low", "medium", "high"],
    default_reasoning_effort: "high",
  });
  getCodexRunMock.mockResolvedValue({
    ok: true,
    id: "run-1",
    status: "done",
    prompt: "sample",
    output: "ok",
    duration_s: 1.2,
    exit_code: 0,
  });
  getSessionScreenMock.mockResolvedValue({
    ok: true,
    text: "",
  });
  listSessionFilesMock.mockResolvedValue({
    ok: true,
    items: [],
  });
  getSessionNotesMock.mockResolvedValue({
    ok: true,
    session: "codex_demo",
    notes: {
      session: "codex_demo",
      content: "",
      created_at: Date.now(),
      updated_at: Date.now(),
      last_response_snapshot: "",
    },
  });
  saveSessionNotesMock.mockResolvedValue({
    ok: true,
    session: "codex_demo",
    notes: {
      session: "codex_demo",
      content: "Saved note",
      created_at: Date.now(),
      updated_at: Date.now(),
      last_response_snapshot: "Latest output",
    },
  });
  appendLatestSessionNotesMock.mockResolvedValue({
    ok: true,
    session: "codex_demo",
    appended_text: "Latest output",
    notes: {
      session: "codex_demo",
      content: "Latest output",
      created_at: Date.now(),
      updated_at: Date.now(),
      last_response_snapshot: "Latest output",
    },
  });
  sendSessionFileToTelegramMock.mockResolvedValue({
    ok: true,
    detail: "Sent to Telegram.",
  });
  listBrowseEntriesMock.mockResolvedValue({
    ok: true,
    root: {
      id: "workspace",
      label: "Workspace",
      path: "/home/megha/codrex-work",
    },
    roots: [
      {
        id: "workspace",
        label: "Workspace",
        path: "/home/megha/codrex-work",
      },
    ],
    current_path: "/home/megha/codrex-work",
    current_relative_path: "",
    display_path: "/home/megha/codrex-work",
    windows_path: "",
    items: [],
  });
  getThreadStoreMock.mockResolvedValue({
    ok: true,
    threads: [],
    messages: {},
  });
  getTmuxHealthMock.mockResolvedValue({
    ok: true,
    state: "ok",
    sessions: [],
  });
  getTmuxPanesMock.mockResolvedValue({
    ok: true,
    panes: [],
  });
  getTmuxPaneScreenMock.mockResolvedValue({
    ok: true,
    text: "",
  });
  getDesktopInfoMock.mockResolvedValue({
    ok: true,
    width: 0,
    height: 0,
  });
  getPowerStatusMock.mockResolvedValue({
    ok: true,
    online: true,
    actions: ["lock", "sleep", "hibernate", "restart", "shutdown"],
    confirm_required_actions: ["sleep", "hibernate", "restart", "shutdown"],
    wake_surface: "telegram",
    wake_command: "/wake",
    wake_instruction: "/wake laptop",
    wake_readiness: "ready",
    wake_warning: "",
    wake_transport_hint: "ethernet",
    wake_relay_configured: true,
    relay_reachable: true,
    relay_detail: "Relay reachable.",
    primary_mac: "AA:BB:CC:DD:EE:FF",
    wake_candidate_macs: ["AA:BB:CC:DD:EE:FF"],
    wake_supported: true,
  });

  createSessionMock.mockResolvedValue({ ok: true, session: "dev-main" });
  registerSessionFileMock.mockResolvedValue({
    ok: true,
    item: {
      id: "sf_1",
      title: "Attached",
      file_name: "demo.png",
      mime_type: "image/png",
      size_bytes: 1024,
      created_at: Date.now(),
      expires_at: Date.now() + 24 * 3600 * 1000,
      created_by: "session:codex_demo",
      is_image: true,
      wsl_path: "/home/megha/codrex-work/demo.png",
      download_url: "/codex/session/codex_demo/files/sf_1/download",
    },
  });
  deleteSessionFileMock.mockResolvedValue({ ok: true });
  loginMock.mockResolvedValue({ ok: true });
  bootstrapLocalAuthMock.mockResolvedValue({
    ok: false,
    error: "forbidden",
    detail: "Local bootstrap is only allowed from localhost hostnames.",
  });
  logoutMock.mockResolvedValue({ ok: true });
  createPairCodeMock.mockResolvedValue({ ok: true, code: "abc123", expires_in: 60 });
  exchangePairCodeMock.mockResolvedValue({ ok: true });
  interruptSessionMock.mockResolvedValue({ ok: true });
  ctrlcSessionMock.mockResolvedValue({ ok: true });
  sendSessionKeyMock.mockResolvedValue({ ok: true });
  sendToSessionMock.mockResolvedValue({ ok: true });
  setDesktopModeMock.mockResolvedValue({ ok: true, enabled: false });
  desktopClickMock.mockResolvedValue({ ok: true });
  desktopMoveMock.mockResolvedValue({ ok: true, x: 100, y: 80 });
  desktopScrollMock.mockResolvedValue({ ok: true });
  desktopSendTextMock.mockResolvedValue({ ok: true });
  desktopSendKeyMock.mockResolvedValue({ ok: true });
  createTmuxSessionMock.mockResolvedValue({ ok: true });
  closeTmuxSessionMock.mockResolvedValue({ ok: true });
  sendToPaneMock.mockResolvedValue({ ok: true });
  sendToPaneKeyMock.mockResolvedValue({ ok: true });
  interruptPaneMock.mockResolvedValue({ ok: true });
  closeSessionMock.mockResolvedValue({ ok: true });
  sendSessionImageMock.mockResolvedValue({ ok: true });
  uploadSessionFileMock.mockResolvedValue({ ok: true, item: undefined });
  startCodexExecMock.mockResolvedValue({ ok: true, id: "run-2" });
  uploadWslFileMock.mockResolvedValue({ ok: true, saved_path: "/tmp/uploaded.txt" });
  setIpcObserverMock.mockImplementation(() => {});
  createThreadRecordMock.mockImplementation(async (payload) => ({
    ok: true,
    thread: {
      id: payload.id || "thr_auto",
      title: payload.title || "Untitled",
      session: payload.session,
      created_at: Date.now(),
      updated_at: Date.now(),
    },
  }));
  updateThreadRecordMock.mockResolvedValue({ ok: true });
  deleteThreadRecordMock.mockResolvedValue({ ok: true });
  addThreadRecordMessageMock.mockResolvedValue({ ok: true });
}

describe("app shell tabs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clipboardWriteTextMock.mockReset();
    clipboardWriteTextMock.mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: clipboardWriteTextMock,
        readText: vi.fn().mockResolvedValue(""),
      },
    });
    setupDefaultMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("switches between tab panels", async () => {
    render(<App />);

    const sessionsPanel = await screen.findByTestId("tab-panel-sessions");
    expect(sessionsPanel).toBeInTheDocument();
    expect(sessionsPanel).toHaveClass("tab-still");
    expect(screen.getByTestId("nav-icon-sessions")).toBeInTheDocument();
    expect(screen.getByTestId("nav-icon-threads")).toBeInTheDocument();
    expect(screen.getByTestId("nav-icon-remote")).toBeInTheDocument();
    expect(screen.getByTestId("nav-icon-pair")).toBeInTheDocument();
    expect(screen.getByTestId("nav-icon-settings")).toBeInTheDocument();
    expect(screen.getByTestId("nav-icon-debug")).toBeInTheDocument();
    expect(screen.queryByTestId("tab-tools")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("tab-pair"));
    const pairPanel = await screen.findByTestId("tab-panel-pair");
    expect(pairPanel).toBeInTheDocument();
    await waitFor(() => {
      expect(pairPanel).toHaveClass("tab-slide-left");
    });

    fireEvent.click(screen.getByTestId("tab-settings"));
    const settingsPanel = await screen.findByTestId("tab-panel-settings");
    expect(settingsPanel).toBeInTheDocument();
    await waitFor(() => {
      expect(settingsPanel).toHaveClass("tab-slide-left");
    });

    fireEvent.click(screen.getByTestId("tab-debug"));
    const debugPanel = await screen.findByTestId("tab-panel-debug");
    expect(debugPanel).toBeInTheDocument();
    await waitFor(() => {
      expect(debugPanel).toHaveClass("tab-slide-left");
    });

    fireEvent.click(screen.getByTestId("tab-sessions"));
    const sessionsPanelReturn = await screen.findByTestId("tab-panel-sessions");
    expect(sessionsPanelReturn).toBeInTheDocument();
    await waitFor(() => {
      expect(sessionsPanelReturn).toHaveClass("tab-slide-right");
    });
  });

  it("disables remote desktop controls when desktop mode is off", async () => {
    getDesktopInfoMock.mockResolvedValue({
      ok: true,
      enabled: false,
      width: 1920,
      height: 1080,
    });
    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));

    const leftClickButton = await screen.findByRole("button", { name: "Left Click" });
    expect(leftClickButton).toBeDisabled();
    fireEvent.click(leftClickButton);
    expect(desktopClickMock).not.toHaveBeenCalled();

    expect(screen.getByRole("button", { name: "Send Text" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send Key" })).toBeDisabled();
    const streamImage = screen.getByAltText("Desktop stream") as HTMLImageElement;
    expect(streamImage.src).toContain("/desktop/stream");
  });

  it("sends remote text from remote tab via direct typing", async () => {
    getDesktopInfoMock.mockResolvedValue({
      ok: true,
      enabled: true,
      width: 1920,
      height: 1080,
    });
    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));
    await screen.findByRole("button", { name: "Disable Control" });
    fireEvent.click(screen.getByRole("button", { name: "Trackpad: On" }));
    const streamImage = screen.getByAltText("Desktop stream");
    Object.defineProperty(streamImage, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 0,
        top: 0,
        width: 960,
        height: 540,
        right: 960,
        bottom: 540,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }),
    });
    fireEvent.click(streamImage, { clientX: 120, clientY: 80 });

    fireEvent.change(screen.getByPlaceholderText("Type text for the focused desktop app"), {
      target: { value: "Remote quick note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send Text" }));

    await waitFor(() => {
      expect(desktopSendTextMock).toHaveBeenCalledWith("Remote quick note");
    });
    expect(desktopClickMock).toHaveBeenCalledTimes(1);
    expect(desktopSendKeyMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Send Telegram" })).not.toBeInTheDocument();
  });

  it("types clipboard text without re-clicking the desktop target", async () => {
    getDesktopInfoMock.mockResolvedValue({
      ok: true,
      enabled: true,
      width: 1920,
      height: 1080,
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: clipboardWriteTextMock,
        readText: vi.fn().mockResolvedValue("Clipboard payload"),
      },
    });

    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));
    await screen.findByRole("button", { name: "Disable Control" });
    fireEvent.click(screen.getByRole("button", { name: "Trackpad: On" }));
    const streamImage = screen.getByAltText("Desktop stream");
    Object.defineProperty(streamImage, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 0,
        top: 0,
        width: 960,
        height: 540,
        right: 960,
        bottom: 540,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }),
    });
    fireEvent.click(streamImage, { clientX: 140, clientY: 100 });
    desktopClickMock.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Paste Into Box" }));

    await waitFor(() => {
      expect(screen.getByDisplayValue("Clipboard payload")).toBeInTheDocument();
    });
    expect(desktopSendTextMock).not.toHaveBeenCalled();
    expect(desktopClickMock).not.toHaveBeenCalled();
  });

  it("sends remote arrow quick keys from the tablet control cluster", async () => {
    getDesktopInfoMock.mockResolvedValue({
      ok: true,
      enabled: true,
      width: 1920,
      height: 1080,
    });
    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));
    const remotePanel = await screen.findByTestId("tab-panel-remote");
    await within(remotePanel).findByRole("button", { name: "Disable Control" });

    fireEvent.click(within(remotePanel).getByRole("button", { name: "Up" }));

    await waitFor(() => {
      expect(desktopSendKeyMock).toHaveBeenCalledWith("up");
    });
  });

  it("sends all-tabs and switch-tab quick keys from remote tab", async () => {
    getDesktopInfoMock.mockResolvedValue({
      ok: true,
      enabled: true,
      width: 1920,
      height: 1080,
    });
    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));
    const remotePanel = await screen.findByTestId("tab-panel-remote");
    await within(remotePanel).findByRole("button", { name: "Disable Control" });

    fireEvent.click(within(remotePanel).getByRole("button", { name: "All Tabs" }));
    fireEvent.click(within(remotePanel).getByRole("button", { name: "Switch Tab" }));

    await waitFor(() => {
      expect(desktopSendKeyMock).toHaveBeenCalledWith("win+tab");
      expect(desktopSendKeyMock).toHaveBeenCalledWith("alt+tab");
    });
  });

  it("arms and confirms destructive power actions from remote tab", async () => {
    sendPowerActionMock
      .mockResolvedValueOnce({
        ok: false,
        action: "shutdown",
        error: "confirmation_required",
        detail: "Confirm shutdown before it is sent to the host.",
        confirm_required: true,
        confirm_token: "tok_123",
        confirm_expires_in: 30,
      })
      .mockResolvedValueOnce({
        ok: true,
        action: "shutdown",
        accepted: true,
        detail: "Power action scheduled.",
      });

    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));
    expect(await screen.findByTestId("power-card")).toBeInTheDocument();
    expect(screen.getByDisplayValue("/wake laptop")).toBeInTheDocument();
    expect(screen.getByDisplayValue("AA:BB:CC:DD:EE:FF")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("power-action-shutdown"));

    const confirmBanner = await screen.findByTestId("power-confirm-banner");
    expect(confirmBanner).toHaveTextContent("Confirm Shutdown");

    fireEvent.click(screen.getByTestId("power-confirm-accept"));

    await waitFor(() => {
      expect(sendPowerActionMock).toHaveBeenNthCalledWith(1, "shutdown", undefined);
      expect(sendPowerActionMock).toHaveBeenNthCalledWith(2, "shutdown", { confirm_token: "tok_123" });
    });

    await waitFor(() => {
      expect(screen.queryByTestId("power-confirm-banner")).not.toBeInTheDocument();
    });
  });

  it("shows wake warning when host readiness is unsupported", async () => {
    getPowerStatusMock.mockResolvedValueOnce({
      ok: true,
      online: true,
      actions: ["lock", "sleep", "hibernate", "restart", "shutdown"],
      confirm_required_actions: ["sleep", "hibernate", "restart", "shutdown"],
      wake_surface: "telegram",
      wake_command: "/wake",
      wake_instruction: "/wake laptop",
      wake_readiness: "unsupported",
      wake_warning: "Wake is not confirmed on this host. An Ethernet adapter exists, but Windows is not exposing Wake-on-Magic-Packet yet.",
      wake_transport_hint: "ethernet",
      wake_relay_configured: true,
      relay_reachable: true,
      relay_detail: "Relay reachable.",
      primary_mac: "AA:BB:CC:DD:EE:FF",
      wake_candidate_macs: ["AA:BB:CC:DD:EE:FF"],
      wake_supported: true,
    });

    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));

    const warningBanner = await screen.findByTestId("power-warning-banner");
    expect(warningBanner).toHaveTextContent("Wake is best effort on this machine");
    expect(warningBanner).toHaveTextContent("Windows is not exposing Wake-on-Magic-Packet yet.");
    expect(screen.getByText("wake: unsupported")).toBeInTheDocument();
    expect(screen.getByText(/Preferred transport:/)).toHaveTextContent("ethernet");
  });

  it("creates a session from sessions tab", async () => {
    render(<App />);

    await screen.findByTestId("tab-panel-sessions");

    fireEvent.change(screen.getByTestId("new-session-input"), {
      target: { value: "review-session" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalledWith({
        name: "review-session",
        cwd: "",
        reasoning_effort: "high",
      });
    });
  });

  it("starts resume-last session from sessions tab", async () => {
    createSessionMock.mockResolvedValueOnce({
      ok: true,
      session: "codex_resume_demo",
      resume_last: true,
    });
    render(<App />);
    await screen.findByTestId("tab-panel-sessions");

    fireEvent.change(screen.getByTestId("new-session-input"), {
      target: { value: "resume-session" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resume Last" }));

    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalledWith({
        name: "resume-session",
        cwd: "",
        reasoning_effort: "high",
        resume_last: true,
      });
    });
  });

  it("redirects to settings tab on unauthorized sessions fetch", async () => {
    getSessionsMock.mockRejectedValueOnce(new Error("Login required."));
    render(<App />);

    expect(await screen.findByTestId("tab-panel-settings")).toBeInTheDocument();
  });

  it("shows install help and handles deferred install prompt", async () => {
    render(<App />);

    const installButton = await screen.findByTestId("install-app-button");
    expect(installButton).toHaveTextContent("Install Help");

    fireEvent.click(installButton);
    expect(screen.getByTestId("install-guide")).toBeInTheDocument();

    const promptMock = vi.fn().mockResolvedValue(undefined);
    const installEvent = new Event("beforeinstallprompt") as Event & {
      prompt: () => Promise<void>;
      userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform?: string }>;
    };
    Object.defineProperty(installEvent, "prompt", { configurable: true, value: promptMock });
    Object.defineProperty(installEvent, "userChoice", {
      configurable: true,
      value: Promise.resolve({ outcome: "dismissed" as const }),
    });

    fireEvent(window, installEvent);
    expect(screen.getByTestId("install-app-button")).toHaveTextContent("Install App");

    fireEvent.click(screen.getByTestId("install-app-button"));
    await waitFor(() => {
      expect(promptMock).toHaveBeenCalledTimes(1);
    });

    expect(await screen.findByText("Install dismissed. Use Install Help to pin later.")).toBeInTheDocument();
  });

  it("renders a single pairing qr flow in pair tab", async () => {
    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-pair"));
    expect(await screen.findByTestId("tab-panel-pair")).toBeInTheDocument();

    expect(screen.queryByTestId("mobile-open-url")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Generate QR" }));
    expect(await screen.findByAltText("Pairing QR")).toBeInTheDocument();
  });

  it("updates pairing link when route hint changes", async () => {
    vi.mocked(api.buildSuggestedControllerUrl).mockImplementation((_hostname, _port, _netInfo, route) => {
      if (route === "tailscale") {
        return "http://100.64.0.9:8787";
      }
      return "http://192.168.1.15:8787";
    });
    vi.mocked(api.buildPairConsumeUrl).mockImplementation((baseUrl, code) => `${baseUrl}/auth/pair/consume?code=${code}`);
    vi.mocked(api.buildPairQrPngUrl).mockImplementation(
      (baseUrl, data) => `${baseUrl}/auth/pair/qr.png?data=${encodeURIComponent(data)}`,
    );

    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-pair"));
    fireEvent.click(screen.getByRole("button", { name: "Generate QR" }));

    await waitFor(() => {
      expect((screen.getByTestId("pair-link-text") as HTMLTextAreaElement).value).toBe(
        "http://100.64.0.9:8787/auth/pair/consume?code=abc123",
      );
    });

    fireEvent.change(screen.getByTestId("pair-route-hint-select"), {
      target: { value: "lan" },
    });

    await waitFor(() => {
      expect((screen.getByTestId("pair-link-text") as HTMLTextAreaElement).value).toBe(
        "http://192.168.1.15:8787/auth/pair/consume?code=abc123",
      );
    });
  });

  it("groups sessions by project and supports project filter", async () => {
    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_alpha",
          pane_id: "%1",
          current_command: "codex",
          cwd: "/home/megha/project-alpha",
          state: "idle",
          updated_at: Date.now(),
          snippet: "",
        },
        {
          session: "codex_beta",
          pane_id: "%2",
          current_command: "codex",
          cwd: "/home/megha/project-beta",
          state: "busy",
          updated_at: Date.now(),
          snippet: "",
        },
      ],
    });

    render(<App />);

    const projectFilter = await screen.findByTestId("session-project-filter");
    expect(within(projectFilter).getByRole("option", { name: "project-alpha" })).toBeInTheDocument();
    expect(within(projectFilter).getByRole("option", { name: "project-beta" })).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("session-project-filter"), {
      target: { value: "project-alpha" },
    });
    const sessionList = screen.getByRole("list", { name: "Codex sessions" });
    expect(await within(sessionList).findByRole("button", { name: /open codex_alpha/i })).toBeInTheDocument();
    expect(within(sessionList).queryByRole("button", { name: /open codex_beta/i })).not.toBeInTheDocument();
  });

  it("restores selected session and filter state after reload", async () => {
    window.localStorage.setItem("codrex.ui.selected_session.v1", "codex_beta");
    window.localStorage.setItem("codrex.ui.session_project_filter.v1", "project-beta");
    window.localStorage.setItem("codrex.ui.session_query.v1", "beta");

    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_alpha",
          pane_id: "%1",
          current_command: "node",
          cwd: "/home/megha/project-alpha",
          state: "idle",
          updated_at: Date.now(),
          snippet: "",
        },
        {
          session: "codex_beta",
          pane_id: "%2",
          current_command: "node",
          cwd: "/home/megha/project-beta",
          state: "running",
          updated_at: Date.now(),
          snippet: "Latest cached line",
        },
      ],
      meta: {
        total_sessions: 2,
        background_mode: "selected_only",
      },
    });

    render(<App />);

    const projectFilter = await screen.findByTestId("session-project-filter");
    expect((projectFilter as HTMLSelectElement).value).toBe("project-beta");
    expect((screen.getByTestId("session-search-input") as HTMLInputElement).value).toBe("beta");

    const sessionList = screen.getByRole("list", { name: "Codex sessions" });
    const betaCard = await within(sessionList).findByRole("button", { name: /open codex_beta/i });
    expect(betaCard.className).toContain("selected");
    expect(screen.getByText("1 visible / 2 total")).toBeInTheDocument();
  });

  it("closes a session directly from its session card", async () => {
    const alphaSession: SessionInfo = {
      session: "codex_alpha",
      pane_id: "%1",
      current_command: "codex",
      cwd: "/home/megha/project-alpha",
      state: "idle",
      updated_at: Date.now(),
      snippet: "Alpha output",
    };
    const betaSession: SessionInfo = {
      session: "codex_beta",
      pane_id: "%2",
      current_command: "codex",
      cwd: "/home/megha/project-beta",
      state: "running",
      updated_at: Date.now(),
      snippet: "Beta output",
    };

    getSessionsMock
      .mockResolvedValueOnce({
        ok: true,
        sessions: [alphaSession, betaSession],
        meta: {
          total_sessions: 2,
          background_mode: "selected_only",
        },
      })
      .mockResolvedValue({
        ok: true,
        sessions: [betaSession],
        meta: {
          total_sessions: 1,
          background_mode: "selected_only",
        },
      });

    render(<App />);

    const sessionList = await screen.findByRole("list", { name: "Codex sessions" });
    expect(await within(sessionList).findByRole("button", { name: /open codex_alpha/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close codex_alpha" }));

    await waitFor(() => {
      expect(closeSessionMock).toHaveBeenCalledWith("codex_alpha");
    });

    await waitFor(() => {
      expect(within(sessionList).queryByRole("button", { name: /open codex_alpha/i })).not.toBeInTheDocument();
    });
    expect(within(sessionList).getByRole("button", { name: /open codex_beta/i })).toBeInTheDocument();
  });

  it("sends prompt text directly to session", async () => {
    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%1",
          current_command: "codex",
          cwd: "/home/megha/work",
          state: "idle",
          updated_at: Date.now(),
          snippet: "",
        },
      ],
    });

    render(<App />);

    expect(await screen.findByTestId("composer-send-prompt")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Type your prompt. Codrex will send Enter + Enter to submit."), {
      target: { value: "Create a release checklist" },
    });
    fireEvent.click(screen.getByTestId("composer-send-prompt"));

    await waitFor(() => {
      expect(sendToSessionMock).toHaveBeenCalled();
    });

    const latestCall = sendToSessionMock.mock.calls.at(-1);
    expect(latestCall?.[0]).toBe("codex_demo");
    expect(latestCall?.[1]).toBe("Create a release checklist");
  });

  it("saves notes and appends the latest response inside the sessions workspace", async () => {
    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%1",
          current_command: "codex",
          cwd: "/home/megha/work",
          state: "idle",
          updated_at: Date.now(),
          snippet: "Assistant ready",
        },
      ],
    });
    getSessionScreenMock.mockResolvedValue({
      ok: true,
      text: "Plan heading\n\nFirst action\nSecond action",
    });

    render(<App />);

    const notesInput = await screen.findByTestId("session-notes-input");
    await screen.findByText(/Plan heading/);
    await waitFor(() => {
      expect(notesInput).toHaveValue("");
    });
    fireEvent.change(notesInput, { target: { value: "Ship checklist" } });
    expect(notesInput).toHaveValue("Ship checklist");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(saveSessionNotesMock).toHaveBeenCalledWith("codex_demo", {
        content: "Ship checklist",
        last_response_snapshot: "Plan heading\nFirst action\nSecond action",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Append Latest Response" }));

    await waitFor(() => {
      expect(appendLatestSessionNotesMock).toHaveBeenCalledWith("codex_demo");
    });
  });

  it("shows a notes-only lower pane for sessions", async () => {
    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%1",
          current_command: "codex",
          cwd: "/home/megha/work",
          state: "idle",
          updated_at: Date.now(),
          snippet: "Assistant ready",
        },
      ],
    });

    render(<App />);

    expect(await screen.findByTestId("session-notes-panel")).toBeVisible();
    expect(screen.queryByTestId("session-files-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("session-setup-panel")).not.toBeInTheDocument();
  });

  it("sends arrow key to session from action dock", async () => {
    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%1",
          current_command: "codex",
          cwd: "/home/megha/work",
          state: "idle",
          updated_at: Date.now(),
          snippet: "",
        },
      ],
    });

    render(<App />);
    const actionDock = await screen.findByTestId("session-action-dock");
    fireEvent.click(within(actionDock).getByRole("button", { name: "Up" }));

    await waitFor(() => {
      expect(sendSessionKeyMock).toHaveBeenCalledWith("codex_demo", "up");
    });
  });

  it("sends backspace to session from action dock", async () => {
    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%1",
          current_command: "codex",
          cwd: "/home/megha/work",
          state: "idle",
          updated_at: Date.now(),
          snippet: "",
        },
      ],
    });

    render(<App />);
    const actionDock = await screen.findByTestId("session-action-dock");
    fireEvent.click(within(actionDock).getByRole("button", { name: "Backspace" }));

    await waitFor(() => {
      expect(sendSessionKeyMock).toHaveBeenCalledWith("codex_demo", "backspace");
    });
  });

  it("asks Codex to send the relevant generated output files via Telegram from the composer action", async () => {
    getAuthStatusMock.mockResolvedValue({
      ok: true,
      auth_required: true,
      authenticated: true,
    });
    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%1",
          current_command: "codex",
          cwd: "/home/megha/work",
          state: "idle",
          updated_at: Date.now(),
          snippet: "Assistant ready",
        },
      ],
    });
    getTelegramStatusMock.mockResolvedValue({
      ok: true,
      configured: true,
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /open codex_demo/i }));

    const composer = screen.getByRole("textbox", { name: /Prompt Composer/i });
    fireEvent.change(composer, { target: { value: "Please review the plot first." } });

    const telegramButton = await screen.findByTestId("composer-send-telegram");
    fireEvent.click(telegramButton);

    await waitFor(() => {
      expect(sendToSessionMock).toHaveBeenCalledTimes(1);
    });
    const [sessionName, prompt] = sendToSessionMock.mock.calls[0] || [];
    expect(sessionName).toBe("codex_demo");
    expect(prompt).toContain("Please review the plot first.");
    expect(prompt).toContain("Send the relevant generated output files for the current task to me via Telegram");
    expect(prompt).toContain("Do not search for Telegram bot keys or secret files.");
    expect(prompt).toContain("tell me exactly which paths you sent");
    expect(composer).toHaveValue(prompt);
  });

  it("keeps the Telegram action available without showing the old helper bubble", async () => {
    getAuthStatusMock.mockResolvedValue({
      ok: true,
      auth_required: true,
      authenticated: true,
    });
    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%1",
          current_command: "codex",
          cwd: "/home/megha/work",
          state: "idle",
          updated_at: Date.now(),
          snippet: "Assistant ready",
        },
      ],
    });
    getTelegramStatusMock.mockResolvedValue({
      ok: true,
      configured: true,
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /open codex_demo/i }));

    const telegramButton = await screen.findByTestId("composer-send-telegram");
    expect(telegramButton).not.toBeDisabled();
    expect(screen.queryByTestId("composer-telegram-hint")).not.toBeInTheDocument();
  });

  it("copies notes and latest response with the shared clipboard helper", async () => {
    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%1",
          current_command: "codex",
          cwd: "/home/megha/work",
          state: "idle",
          updated_at: Date.now(),
          snippet: "Assistant ready",
        },
      ],
    });
    getSessionScreenMock.mockResolvedValue({
      ok: true,
      text: "Summary heading\n\nFirst action\nSecond action",
    });

    render(<App />);
    const notesInput = await screen.findByTestId("session-notes-input");
    fireEvent.change(notesInput, { target: { value: "Release checklist" } });

    fireEvent.click(screen.getByRole("button", { name: "Copy Notes" }));
    await waitFor(() => {
      expect(clipboardWriteTextMock).toHaveBeenCalledWith("Release checklist");
    });

    fireEvent.click(screen.getByRole("button", { name: "Copy Latest Response" }));
    await waitFor(() => {
      expect(clipboardWriteTextMock).toHaveBeenCalledWith("Summary heading\nFirst action\nSecond action");
    });
  });

  it("shows a compact image picker in the composer area", async () => {
    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%1",
          current_command: "codex",
          cwd: "/home/megha/work",
          state: "idle",
          updated_at: Date.now(),
          snippet: "",
        },
      ],
    });
    getTelegramStatusMock.mockResolvedValueOnce({
      ok: true,
      configured: true,
    });

    render(<App />);
    expect(await screen.findByTestId("composer-image-picker")).toBeVisible();
    expect(screen.getByTestId("session-image-input")).toBeInTheDocument();
    expect(screen.queryByTestId("session-image-mode-select")).not.toBeInTheDocument();
  });

  it("enables live output automatically when creating a session", async () => {
    window.localStorage.setItem("codrex.ui.stream_enabled.v1", "false");
    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%1",
          current_command: "codex",
          cwd: "/home/megha/work",
          state: "idle",
          updated_at: Date.now(),
          snippet: "",
        },
      ],
    });

    render(<App />);

    await screen.findByTestId("tab-panel-sessions");
    expect(screen.getByTestId("toggle-live-output")).toHaveTextContent("Live Off");
    fireEvent.change(screen.getByTestId("new-session-input"), { target: { value: "auto-live-session" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalledWith({
        name: "auto-live-session",
        cwd: "",
        reasoning_effort: "high",
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId("toggle-live-output")).toHaveTextContent("Live On");
    });
  });

  it("sends prompt from composer send icon", async () => {
    getSessionsMock.mockResolvedValue({
      ok: true,
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%1",
          current_command: "codex",
          cwd: "/home/megha/work",
          state: "idle",
          updated_at: Date.now(),
          snippet: "",
        },
      ],
    });

    render(<App />);

    expect(await screen.findByTestId("composer-send-prompt")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Type your prompt. Codrex will send Enter + Enter to submit."), {
      target: { value: "Review latest logs and summarize key errors." },
    });
    fireEvent.click(screen.getByTestId("composer-send-prompt"));

    await waitFor(() => {
      expect(sendToSessionMock).toHaveBeenCalled();
    });

    const latestCall = sendToSessionMock.mock.calls.at(-1);
    expect(latestCall?.[0]).toBe("codex_demo");
    expect(latestCall?.[1]).toContain("Review latest logs and summarize key errors.");
  });

  it("supports swipe gestures to switch tabs", async () => {
    render(<App />);

    const shell = await screen.findByTestId("screen-shell");
    expect(await screen.findByTestId("tab-panel-sessions")).toBeInTheDocument();

    fireEvent.touchStart(shell, {
      touches: [{ identifier: 1, target: shell, clientX: 320, clientY: 140 }],
    });
    fireEvent.touchEnd(shell, {
      changedTouches: [{ identifier: 1, target: shell, clientX: 120, clientY: 150 }],
    });
    expect(await screen.findByTestId("tab-panel-threads")).toBeInTheDocument();

    fireEvent.touchStart(shell, {
      touches: [{ identifier: 1, target: shell, clientX: 110, clientY: 140 }],
    });
    fireEvent.touchEnd(shell, {
      changedTouches: [{ identifier: 1, target: shell, clientX: 320, clientY: 145 }],
    });
    expect(await screen.findByTestId("tab-panel-sessions")).toBeInTheDocument();
    expect(screen.queryByTestId("swipe-hint")).not.toBeInTheDocument();
  });

  it("keeps threads focused on tmux monitor without codex session thread controls", async () => {
    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-threads"));
    await screen.findByTestId("tab-panel-threads");
    expect(screen.getByText("Tmux Session Monitor")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show Legacy Panels" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("thread-session-input-select")).not.toBeInTheDocument();
    expect(screen.queryByText("Codex Transcript Threads")).not.toBeInTheDocument();
  });

  it("sends resume-last command to selected tmux pane", async () => {
    getTmuxPanesMock.mockResolvedValue({
      ok: true,
      panes: [
        {
          session: "shell_ops",
          window_index: "0",
          pane_index: "1",
          pane_id: "%2",
          active: true,
          current_command: "bash",
          current_path: "/home/megha/work",
        },
      ],
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId("tab-threads"));
    await screen.findByTestId("tab-panel-threads");

    fireEvent.change(screen.getByTestId("threads-pane-select"), {
      target: { value: "%2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resume Last" }));

    await waitFor(() => {
      expect(sendToPaneMock).toHaveBeenCalledWith("%2", "codex resume --last");
    });
  });

  it("sends arrow and enter keys to selected tmux pane", async () => {
    getTmuxPanesMock.mockResolvedValue({
      ok: true,
      panes: [
        {
          session: "shell_ops",
          window_index: "0",
          pane_index: "1",
          pane_id: "%2",
          active: true,
          current_command: "bash",
          current_path: "/home/megha/work",
        },
      ],
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId("tab-threads"));
    await screen.findByTestId("tab-panel-threads");

    fireEvent.change(screen.getByTestId("threads-pane-select"), {
      target: { value: "%2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Up" }));

    await waitFor(() => {
      expect(sendToPaneKeyMock).toHaveBeenCalledWith("%2", "up");
    });

    fireEvent.click(screen.getByRole("button", { name: "Enter" }));
    await waitFor(() => {
      expect(sendToPaneKeyMock).toHaveBeenCalledWith("%2", "enter");
    });
  });

  it("filters Codex panes out of Threads tmux pane selector", async () => {
    getTmuxPanesMock.mockResolvedValue({
      ok: true,
      panes: [
        {
          session: "codex_demo",
          window_index: "0",
          pane_index: "0",
          pane_id: "%1",
          active: true,
          current_command: "codex",
          current_path: "/home/megha/work",
        },
        {
          session: "shell_ops",
          window_index: "0",
          pane_index: "1",
          pane_id: "%2",
          active: false,
          current_command: "bash",
          current_path: "/home/megha/work",
        },
      ],
    });

    render(<App />);
    fireEvent.click(await screen.findByTestId("tab-threads"));
    await screen.findByTestId("tab-panel-threads");

    const paneSelect = screen.getByLabelText("Pane");
    expect(within(paneSelect).queryByRole("option", { name: /codex_demo/i })).not.toBeInTheDocument();
    expect(within(paneSelect).getByRole("option", { name: /shell_ops/i })).toBeInTheDocument();
  });

  it("renders IPC tracing controls in debug tab", async () => {
    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-debug"));
    expect(await screen.findByTestId("tab-panel-debug")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Search path, detail, payload...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export JSON" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Clear" })).toBeDisabled();
  });

  it("applies touch feedback class on tap", async () => {
    render(<App />);

    const syncButton = await screen.findByRole("button", { name: "Sync Now" });
    fireEvent.pointerDown(syncButton, { pointerType: "touch", clientX: 20, clientY: 20 });
    expect(syncButton).toHaveClass("tap-flash");
  });

  it("shows swipe hint once and persists dismissal", async () => {
    window.localStorage.removeItem("codrex.ui.swipe_hint_seen.v1");

    const firstRender = render(<App />);
    expect(await screen.findByTestId("swipe-hint")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("dismiss-swipe-hint"));
    await waitFor(() => {
      expect(screen.queryByTestId("swipe-hint")).not.toBeInTheDocument();
    });
    expect(window.localStorage.getItem("codrex.ui.swipe_hint_seen.v1")).toBe("true");

    firstRender.unmount();
    render(<App />);
    await screen.findByTestId("tab-panel-sessions");
    expect(screen.queryByTestId("swipe-hint")).not.toBeInTheDocument();
  });
});
