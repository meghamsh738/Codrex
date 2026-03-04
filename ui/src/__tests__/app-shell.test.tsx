import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import * as api from "../api";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    buildDesktopShotUrl: vi.fn(() => "/desktop/shot?ts=1"),
    buildDesktopStreamUrl: vi.fn(() => "/desktop/stream?fps=3&level=3"),
    buildPairConsumeUrl: vi.fn(() => "http://controller/auth/pair/consume?code=abc123"),
    buildPairQrPngUrl: vi.fn(() => "http://controller/auth/pair/qr.png?data=abc123"),
    buildScreenshotUrl: vi.fn(() => "/shot?ts=1"),
    buildSuggestedControllerUrl: vi.fn(() => "http://127.0.0.1:8787"),
    buildWslDownloadUrl: vi.fn(() => "/wsl/file?path=/tmp/demo.txt"),
    bootstrapLocalAuth: vi.fn(),
    closeSession: vi.fn(),
    closeTmuxSession: vi.fn(),
    createPairCode: vi.fn(),
    createSharedFile: vi.fn(),
    createSessionWithOptions: vi.fn(),
    createTmuxSession: vi.fn(),
    ctrlcSession: vi.fn(),
    desktopClick: vi.fn(),
    desktopScroll: vi.fn(),
    desktopSendKey: vi.fn(),
    desktopSendText: vi.fn(),
    exchangePairCode: vi.fn(),
    getAuthStatus: vi.fn(),
    getCodexOptions: vi.fn(),
    getCodexRun: vi.fn(),
    getCodexRuns: vi.fn(),
    getDesktopInfo: vi.fn(),
    getNetInfo: vi.fn(),
    getTelegramStatus: vi.fn(),
    getSessionScreen: vi.fn(),
    getSessions: vi.fn(),
    getThreadStore: vi.fn(),
    getTmuxHealth: vi.fn(),
    getTmuxPaneScreen: vi.fn(),
    getTmuxPanes: vi.fn(),
    interruptPane: vi.fn(),
    interruptSession: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    listSharedFiles: vi.fn(),
    reportIpcEvent: vi.fn(),
    sendSharedFileToTelegram: vi.fn(),
    sendTelegramText: vi.fn(),
    deleteSharedFile: vi.fn(),
    sendSessionImage: vi.fn(),
    addThreadRecordMessage: vi.fn(),
    createThreadRecord: vi.fn(),
    deleteThreadRecord: vi.fn(),
    sendSessionKey: vi.fn(),
    sendToPane: vi.fn(),
    sendToSession: vi.fn(),
    setDesktopMode: vi.fn(),
    setIpcObserver: vi.fn(),
    startCodexExec: vi.fn(),
    updateThreadRecord: vi.fn(),
    uploadWslFile: vi.fn(),
  };
});

const getAuthStatusMock = vi.mocked(api.getAuthStatus);
const getCodexRunMock = vi.mocked(api.getCodexRun);
const getCodexRunsMock = vi.mocked(api.getCodexRuns);
const getCodexOptionsMock = vi.mocked(api.getCodexOptions);
const getNetInfoMock = vi.mocked(api.getNetInfo);
const getTelegramStatusMock = vi.mocked(api.getTelegramStatus);
const getSessionsMock = vi.mocked(api.getSessions);
const getSessionScreenMock = vi.mocked(api.getSessionScreen);
const getThreadStoreMock = vi.mocked(api.getThreadStore);
const createSessionMock = vi.mocked(api.createSessionWithOptions);
const createSharedFileMock = vi.mocked(api.createSharedFile);
const deleteSharedFileMock = vi.mocked(api.deleteSharedFile);
const listSharedFilesMock = vi.mocked(api.listSharedFiles);
const sendSharedFileToTelegramMock = vi.mocked(api.sendSharedFileToTelegram);
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
const setDesktopModeMock = vi.mocked(api.setDesktopMode);
const desktopClickMock = vi.mocked(api.desktopClick);
const desktopScrollMock = vi.mocked(api.desktopScroll);
const desktopSendTextMock = vi.mocked(api.desktopSendText);
const desktopSendKeyMock = vi.mocked(api.desktopSendKey);
const createTmuxSessionMock = vi.mocked(api.createTmuxSession);
const closeTmuxSessionMock = vi.mocked(api.closeTmuxSession);
const sendToPaneMock = vi.mocked(api.sendToPane);
const interruptPaneMock = vi.mocked(api.interruptPane);
const closeSessionMock = vi.mocked(api.closeSession);
const sendSessionImageMock = vi.mocked(api.sendSessionImage);
const startCodexExecMock = vi.mocked(api.startCodexExec);
const uploadWslFileMock = vi.mocked(api.uploadWslFile);
const setIpcObserverMock = vi.mocked(api.setIpcObserver);

function setupDefaultMocks(): void {
  window.localStorage.removeItem("codrex.ui.controller_base.v1");
  window.localStorage.removeItem("codrex.ui.stream_enabled.v1");
  window.localStorage.removeItem("codrex.ui.threads.v2");
  window.localStorage.removeItem("codrex.ui.thread_messages.v2");
  window.localStorage.removeItem("codrex.ui.thread_messages.v1");

  getAuthStatusMock.mockResolvedValue({
    ok: true,
    auth_required: true,
    authenticated: false,
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
  listSharedFilesMock.mockResolvedValue({
    ok: true,
    items: [],
  });
  sendSharedFileToTelegramMock.mockResolvedValue({
    ok: true,
    detail: "Sent to Telegram.",
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

  createSessionMock.mockResolvedValue({ ok: true, session: "dev-main" });
  createSharedFileMock.mockResolvedValue({
    ok: true,
    item: {
      id: "shr_1",
      title: "Shared",
      file_name: "demo.png",
      mime_type: "image/png",
      size_bytes: 1024,
      created_at: Date.now(),
      expires_at: Date.now() + 24 * 3600 * 1000,
      created_by: "session:codex_demo",
      is_image: true,
      wsl_path: "/home/megha/codrex-work/demo.png",
      download_url: "/share/file/shr_1",
    },
  });
  deleteSharedFileMock.mockResolvedValue({ ok: true });
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
  desktopScrollMock.mockResolvedValue({ ok: true });
  desktopSendTextMock.mockResolvedValue({ ok: true });
  desktopSendKeyMock.mockResolvedValue({ ok: true });
  createTmuxSessionMock.mockResolvedValue({ ok: true });
  closeTmuxSessionMock.mockResolvedValue({ ok: true });
  sendToPaneMock.mockResolvedValue({ ok: true });
  interruptPaneMock.mockResolvedValue({ ok: true });
  closeSessionMock.mockResolvedValue({ ok: true });
  sendSessionImageMock.mockResolvedValue({ ok: true });
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

    fireEvent.change(screen.getByPlaceholderText("Type text on desktop"), {
      target: { value: "Remote quick note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send Text" }));

    await waitFor(() => {
      expect(desktopSendTextMock).toHaveBeenCalledWith("Remote quick note");
    });
    expect(desktopSendKeyMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Send Telegram" })).not.toBeInTheDocument();
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
        model: "gpt-5-codex",
        reasoning_effort: "high",
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
    expect(await within(sessionList).findByRole("button", { name: /codex_alpha/i })).toBeInTheDocument();
    expect(within(sessionList).queryByRole("button", { name: /codex_beta/i })).not.toBeInTheDocument();
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

    expect(await screen.findByText("Prompt Composer")).toBeInTheDocument();

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

  it("creates a shared file from sessions panel", async () => {
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
    await screen.findByTestId("shared-files-card");

    fireEvent.change(screen.getByTestId("share-path-input"), {
      target: { value: "/home/megha/codrex-work/output/result.png" },
    });
    fireEvent.change(screen.getByTestId("share-title-input"), {
      target: { value: "Result Plot" },
    });
    fireEvent.change(screen.getByTestId("share-expiry-select"), {
      target: { value: "72" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Share Now" }));

    await waitFor(() => {
      expect(createSharedFileMock).toHaveBeenCalledWith({
        path: "/home/megha/codrex-work/output/result.png",
        title: "Result Plot",
        expires_hours: 72,
        created_by: "session:codex_demo",
      });
    });
  });

  it("sends a shared file to telegram from the inbox", async () => {
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
    listSharedFilesMock.mockResolvedValue({
      ok: true,
      items: [
        {
          id: "shr_abc",
          title: "Result Plot",
          file_name: "result.png",
          mime_type: "image/png",
          size_bytes: 2048,
          created_at: Date.now(),
          expires_at: Date.now() + 24 * 3600 * 1000,
          created_by: "session:codex_demo",
          is_image: true,
          wsl_path: "/home/megha/codrex-work/output/result.png",
          download_url: "/share/file/shr_abc",
        },
      ],
    });

    render(<App />);
    await screen.findByTestId("shared-files-card");

    fireEvent.click(screen.getByRole("button", { name: "Send Telegram" }));

    await waitFor(() => {
      expect(sendSharedFileToTelegramMock).toHaveBeenCalledWith("shr_abc", "Result Plot");
    });
  });

  it("hides shared files inbox when telegram is configured", async () => {
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
    expect(screen.queryByTestId("shared-files-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("telegram-direct-delivery-card")).not.toBeInTheDocument();
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
        model: "gpt-5-codex",
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

    expect(await screen.findByText("Prompt Composer")).toBeInTheDocument();

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
