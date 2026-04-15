import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import * as api from "../api";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    addThreadRecordMessage: vi.fn(),
    appendLatestSessionNotes: vi.fn(),
    bootstrapLocalAuth: vi.fn(),
    buildDesktopShotUrl: vi.fn(() => "/desktop/shot?ts=1"),
    buildDesktopStreamUrl: vi.fn(() => "/desktop/stream?fps=3&level=3"),
    buildPairConsumeUrl: vi.fn(() => "http://controller/auth/pair/consume?code=abc123"),
    buildPairQrPngUrl: vi.fn(() => "http://controller/auth/pair/qr.png?data=abc123"),
    buildSessionStreamUrl: vi.fn(() => "ws://controller/codex/session/codex_demo/ws?profile=balanced"),
    buildSuggestedControllerUrl: vi.fn(() => "http://127.0.0.1:8787"),
    buildWslDownloadUrl: vi.fn(() => "/wsl/file?path=/tmp/demo.txt"),
    closeDesktopWebrtcSession: vi.fn(),
    closeSession: vi.fn(),
    closeTmuxSession: vi.fn(),
    createDesktopWebrtcOffer: vi.fn(),
    createPairCode: vi.fn(),
    createSessionWithOptions: vi.fn(),
    createThreadRecord: vi.fn(),
    createTmuxSession: vi.fn(),
    ctrlcSession: vi.fn(),
    deleteThreadRecord: vi.fn(),
    desktopClick: vi.fn(),
    desktopGetSelectedPath: vi.fn(),
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
    getCodexRuntimeStatus: vi.fn(),
    getDesktopInfo: vi.fn(),
    getNetInfo: vi.fn(),
    getPowerStatus: vi.fn(),
    getSessionNotes: vi.fn(),
    getSessionScreen: vi.fn(),
    getSessions: vi.fn(),
    getTelegramStatus: vi.fn(),
    getThreadStore: vi.fn(),
    getTmuxHealth: vi.fn(),
    getTmuxPaneScreen: vi.fn(),
    getTmuxPanes: vi.fn(),
    interruptPane: vi.fn(),
    interruptSession: vi.fn(),
    listSharedFiles: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    openHostPath: vi.fn(),
    reportIpcEvent: vi.fn(),
    saveSessionNotes: vi.fn(),
    sendPowerAction: vi.fn(),
    sendSessionImage: vi.fn(),
    sendSessionKey: vi.fn(),
    sendToPane: vi.fn(),
    sendToPaneKey: vi.fn(),
    sendToSession: vi.fn(),
    setDesktopMode: vi.fn(),
    setDesktopPerfMode: vi.fn(),
    setIpcObserver: vi.fn(),
    shareHostSelection: vi.fn(),
    startCodexExec: vi.fn(),
    startCodexRuntime: vi.fn(),
    stopCodexRuntime: vi.fn(),
    updateThreadRecord: vi.fn(),
    uploadHostFile: vi.fn(),
    uploadWslFile: vi.fn(),
  };
});

const getAuthStatusMock = vi.mocked(api.getAuthStatus);
const getAppRuntimeMock = vi.mocked(api.getAppRuntime);
const getCodexOptionsMock = vi.mocked(api.getCodexOptions);
const getCodexRuntimeStatusMock = vi.mocked(api.getCodexRuntimeStatus);
const getDesktopInfoMock = vi.mocked(api.getDesktopInfo);
const getNetInfoMock = vi.mocked(api.getNetInfo);
const getPowerStatusMock = vi.mocked(api.getPowerStatus);
const getSessionsMock = vi.mocked(api.getSessions);
const getTelegramStatusMock = vi.mocked(api.getTelegramStatus);
const listSharedFilesMock = vi.mocked(api.listSharedFiles);
const setDesktopModeMock = vi.mocked(api.setDesktopMode);
const desktopClickMock = vi.mocked(api.desktopClick);
const desktopSendTextMock = vi.mocked(api.desktopSendText);
const desktopGetSelectedPathMock = vi.mocked(api.desktopGetSelectedPath);
const uploadHostFileMock = vi.mocked(api.uploadHostFile);
const shareHostSelectionMock = vi.mocked(api.shareHostSelection);
const startCodexRuntimeMock = vi.mocked(api.startCodexRuntime);
const openHostPathMock = vi.mocked(api.openHostPath);

const clipboardWriteTextMock = vi.fn();
const clipboardReadTextMock = vi.fn();

function setupDefaultMocks() {
  window.localStorage.clear();

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
    controller_mode: "controller-only",
    sessions_runtime_state: "stopped",
    sessions_runtime_detail: "Ubuntu runtime is stopped.",
    sessions_runtime_can_start: true,
    sessions_runtime_can_stop: false,
    preferred_origin: "http://192.168.1.15:8787",
    route_provider: "lan",
    route_state: "local_only",
    desktop_stream_transport: "fallback",
    desktop_stream_fallback: "multipart_png",
  });
  getCodexOptionsMock.mockResolvedValue({
    ok: true,
    models: ["gpt-5-codex"],
    default_model: "gpt-5-codex",
    reasoning_efforts: ["low", "medium", "high"],
    default_reasoning_effort: "high",
  });
  getCodexRuntimeStatusMock.mockResolvedValue({
    ok: true,
    state: "stopped",
    detail: "Ubuntu runtime is stopped.",
    can_start: true,
    can_stop: false,
    distro: "Ubuntu",
  });
  getNetInfoMock.mockResolvedValue({
    ok: true,
    lan_ip: "192.168.1.15",
    tailscale_ip: "100.64.0.9",
    netbird_ip: "100.90.0.4",
    preferred_origin: "http://192.168.1.15:8787",
    route_provider: "lan",
    route_state: "local_only",
  });
  getTelegramStatusMock.mockResolvedValue({ ok: true, configured: false });
  listSharedFilesMock.mockResolvedValue({ ok: true, items: [] });
  getSessionsMock.mockResolvedValue({ ok: true, sessions: [] });
  getDesktopInfoMock.mockResolvedValue({
    ok: true,
    enabled: false,
    width: 1920,
    height: 1080,
    desktop_stream_transport: "fallback",
    desktop_stream_fallback: "multipart_png",
  });
  getPowerStatusMock.mockResolvedValue({
    ok: true,
    online: true,
    actions: ["lock", "sleep", "shutdown"],
    confirm_required_actions: ["sleep", "shutdown"],
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

  setDesktopModeMock.mockResolvedValue({ ok: true, enabled: false });
  desktopClickMock.mockResolvedValue({ ok: true });
  desktopSendTextMock.mockResolvedValue({ ok: true });
  desktopGetSelectedPathMock.mockResolvedValue({
    ok: true,
    path: "D:\\Reports\\result.png",
    paths: ["D:\\Reports\\result.png"],
    count: 1,
  });
  uploadHostFileMock.mockResolvedValue({
    ok: true,
    saved_path: "C:\\Users\\megha\\Downloads\\Codrex Transfers\\notes.txt",
    target_dir: "C:\\Users\\megha\\Downloads\\Codrex Transfers",
    detail: "Uploaded to C:\\Users\\megha\\Downloads\\Codrex Transfers",
  });
  shareHostSelectionMock.mockResolvedValue({
    ok: true,
    selected_path: "D:\\Reports\\result.png",
    detail: "Shared host selection: D:\\Reports\\result.png",
  });
  startCodexRuntimeMock.mockResolvedValue({
    ok: true,
    state: "running",
    detail: "Ubuntu runtime started.",
    can_start: false,
    can_stop: true,
    distro: "Ubuntu",
  });
  openHostPathMock.mockResolvedValue({ ok: true, detail: "Opened file." });
}

describe("app shell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clipboardWriteTextMock.mockReset();
    clipboardWriteTextMock.mockResolvedValue(undefined);
    clipboardReadTextMock.mockReset();
    clipboardReadTextMock.mockResolvedValue("");
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: clipboardWriteTextMock,
        readText: clipboardReadTextMock,
      },
    });
    setupDefaultMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("defaults to the home tab with the simplified primary navigation", async () => {
    render(<App />);

    expect(await screen.findByTestId("tab-panel-home")).toBeInTheDocument();
    expect(screen.getByTestId("tab-home")).toBeInTheDocument();
    expect(screen.getByTestId("tab-sessions")).toBeInTheDocument();
    expect(screen.getByTestId("tab-remote")).toBeInTheDocument();
    expect(screen.queryByTestId("tab-pair")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tab-settings")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tab-debug")).not.toBeInTheDocument();
  });

  it("opens the sessions tab from home and shows the runtime-off state", async () => {
    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-sessions"));
    const panel = await screen.findByTestId("tab-panel-sessions");
    expect(panel).toBeInTheDocument();
    expect(screen.getByText("Sessions are offline")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start Ubuntu / Sessions" })).toBeInTheDocument();
  });

  it("starts the sessions runtime from the home card", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Start Sessions" }));

    await waitFor(() => {
      expect(startCodexRuntimeMock).toHaveBeenCalled();
    });
  });

  it("opens the remote tab and keeps advanced controls hidden by default", async () => {
    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));
    const panel = await screen.findByTestId("tab-panel-remote");
    expect(panel).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Keyboard" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Files" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "More" }).length).toBeGreaterThan(0);
    expect(within(panel).queryByRole("button", { name: "Left Click" })).not.toBeInTheDocument();
    expect(within(panel).queryByTestId("remote-host-upload-input")).not.toBeInTheDocument();
  });

  it("reveals keyboard controls only when the keyboard panel is opened", async () => {
    getDesktopInfoMock.mockResolvedValue({
      ok: true,
      enabled: true,
      width: 1920,
      height: 1080,
      desktop_stream_transport: "fallback",
      desktop_stream_fallback: "multipart_png",
    });
    setDesktopModeMock.mockResolvedValue({ ok: true, enabled: true });

    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));
    await screen.findByRole("button", { name: "Disable Control" });
    const panel = await screen.findByTestId("tab-panel-remote");
    fireEvent.click(screen.getAllByRole("button", { name: "Keyboard" }).at(-1)!);

    expect(await within(panel).findByRole("button", { name: "Paste Text" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Hide Keyboard" }).at(-1)!);
    await waitFor(() => {
      expect(within(panel).queryByRole("button", { name: "Paste Text" })).not.toBeInTheDocument();
    });
  });

  it("reveals file transfer controls only when the files panel is opened", async () => {
    getDesktopInfoMock.mockResolvedValue({
      ok: true,
      enabled: true,
      width: 1920,
      height: 1080,
      desktop_stream_transport: "fallback",
      desktop_stream_fallback: "multipart_png",
    });
    setDesktopModeMock.mockResolvedValue({ ok: true, enabled: true });

    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));
    await screen.findByRole("button", { name: "Disable Control" });
    const panel = await screen.findByTestId("tab-panel-remote");
    fireEvent.click(screen.getAllByRole("button", { name: "Files" }).at(-1)!);

    expect(await within(panel).findByTestId("remote-host-upload-input")).toBeInTheDocument();
    expect(within(panel).getByTestId("remote-selected-path")).toBeInTheDocument();
  });

  it("uploads a host transfer file from the files panel", async () => {
    getDesktopInfoMock.mockResolvedValue({
      ok: true,
      enabled: true,
      width: 1920,
      height: 1080,
      desktop_stream_transport: "fallback",
      desktop_stream_fallback: "multipart_png",
    });
    setDesktopModeMock.mockResolvedValue({ ok: true, enabled: true });

    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));
    await screen.findByRole("button", { name: "Disable Control" });
    const panel = await screen.findByTestId("tab-panel-remote");
    fireEvent.click(screen.getAllByRole("button", { name: "Files" }).at(-1)!);

    const uploadInput = await within(panel).findByTestId("remote-host-upload-input");
    fireEvent.change(uploadInput, {
      target: { files: [new File(["hello"], "notes.txt", { type: "text/plain" })] },
    });
    fireEvent.click(within(panel).getByTestId("remote-host-upload-button"));

    await waitFor(() => {
      expect(uploadHostFileMock).toHaveBeenCalled();
    });
  });

  it("copies the focused explorer path from the files panel", async () => {
    getDesktopInfoMock.mockResolvedValue({
      ok: true,
      enabled: true,
      width: 1920,
      height: 1080,
      desktop_stream_transport: "fallback",
      desktop_stream_fallback: "multipart_png",
    });
    setDesktopModeMock.mockResolvedValue({ ok: true, enabled: true });

    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));
    await screen.findByRole("button", { name: "Disable Control" });
    const panel = await screen.findByTestId("tab-panel-remote");
    fireEvent.click(screen.getAllByRole("button", { name: "Files" }).at(-1)!);

    const remotePathPanel = await within(panel).findByTestId("remote-selected-path");
    fireEvent.click(within(remotePathPanel).getByRole("button", { name: "Copy Focused Path" }));

    await waitFor(() => {
      expect(desktopGetSelectedPathMock).toHaveBeenCalled();
      expect(clipboardWriteTextMock).toHaveBeenCalledWith("D:\\Reports\\result.png");
    });
  });

  it("reveals advanced remote controls only when the more panel is opened", async () => {
    getDesktopInfoMock.mockResolvedValue({
      ok: true,
      enabled: true,
      width: 1920,
      height: 1080,
      desktop_stream_transport: "fallback",
      desktop_stream_fallback: "multipart_png",
    });
    setDesktopModeMock.mockResolvedValue({ ok: true, enabled: true });

    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));
    await screen.findByRole("button", { name: "Disable Control" });
    const panel = await screen.findByTestId("tab-panel-remote");
    fireEvent.click(screen.getAllByRole("button", { name: "More" }).at(-1)!);

    expect(await within(panel).findByRole("button", { name: "Left Click" })).toBeInTheDocument();
    expect(within(panel).getByText("Power Control")).toBeInTheDocument();
  });

  it("still blocks disabled pointer actions when control is off", async () => {
    render(<App />);

    fireEvent.click(await screen.findByTestId("tab-remote"));
    const panel = await screen.findByTestId("tab-panel-remote");
    fireEvent.click(screen.getAllByRole("button", { name: "More" }).at(-1)!);

    const leftClickButton = await within(panel).findByRole("button", { name: "Left Click" });
    expect(leftClickButton).toBeDisabled();
    fireEvent.click(leftClickButton);
    expect(desktopClickMock).not.toHaveBeenCalled();
  });
});
