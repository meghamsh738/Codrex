import { expect, test, type Page } from "@playwright/test";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { dismissSwipeHint, installMockController, type MockCodexRun, type MockTmuxPane } from "./support/mockController";

const screenshotsDir = fileURLToPath(new URL("../../screenshots/", import.meta.url));
const launcherHtmlPath = fileURLToPath(new URL("../../launcher/Codrex.Launcher/Assets/launcher.html", import.meta.url));

const demoNow = Date.UTC(2026, 2, 14, 10, 45, 0);

const demoSessions = [
  {
    session: "demo_webapp",
    pane_id: "%7",
    cwd: "/home/demo/codrex-work/webapp",
    state: "running",
    current_command: "codex",
    snippet: "Drafting the launch checklist and release notes.",
    model: "gpt-5-codex",
    reasoning_effort: "high",
    screenText: [
      "Plan for today:",
      "- confirm remote desktop fallback",
      "- refresh the public screenshots",
      "- publish the beginner setup guide",
      "",
      "Working notes:",
      "1. Session paste handling is stable after chunked send.",
      "2. Desktop boost mode now restores wallpaper and visual settings cleanly.",
      "3. README refresh is next.",
    ].join("\n"),
  },
  {
    session: "demo_docs",
    pane_id: "%8",
    cwd: "/home/demo/codrex-work/docs",
    state: "idle",
    current_command: "bash",
    snippet: "Beginner guide outline ready for review.",
    model: "gpt-5",
    reasoning_effort: "medium",
    screenText: "README outline is ready.",
  },
];

const demoTmuxPanes: MockTmuxPane[] = [
  {
    session: "ops_shell",
    window_index: "0",
    pane_index: "0",
    pane_id: "%14",
    active: true,
    current_command: "bash",
    current_path: "/home/demo/codrex-work",
  },
  {
    session: "build_logs",
    window_index: "1",
    pane_index: "0",
    pane_id: "%15",
    active: false,
    current_command: "powershell.exe",
    current_path: "/mnt/d/codex-remote-ui",
  },
];

const demoRuns: MockCodexRun[] = [
  {
    id: "run_release_brief",
    status: "done",
    duration_s: 18.4,
    prompt: "Summarize the public launch state for the Codrex repository.",
    output: [
      "Launch summary:",
      "- public screenshots refreshed",
      "- beginner docs added",
      "- Telegram setup documented",
    ].join("\n"),
    exit_code: 0,
    created_at: demoNow - 70_000,
    finished_at: demoNow - 52_000,
  },
  {
    id: "run_remote_smoke",
    status: "done",
    duration_s: 9.7,
    prompt: "Validate the remote desktop controls after enabling boost mode.",
    output: "Remote control smoke check passed.",
    exit_code: 0,
    created_at: demoNow - 42_000,
    finished_at: demoNow - 33_000,
  },
];

async function ensureScreenshotsDir(): Promise<void> {
  await mkdir(screenshotsDir, { recursive: true });
}

async function captureTab(page: Page, fileName: string): Promise<void> {
  await ensureScreenshotsDir();
  await page.screenshot({
    path: fileURLToPath(new URL(`../../screenshots/${fileName}`, import.meta.url)),
    fullPage: true,
  });
}

test.describe.configure({ mode: "serial" });
test.use({
  viewport: { width: 1425, height: 980 },
  isMobile: false,
  hasTouch: false,
  deviceScaleFactor: 1,
  colorScheme: "light",
  reducedMotion: "reduce",
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });
});

test("captures sanitized public screenshots for the web UI tabs and launcher", async ({ page }) => {
  await installMockController(page, {
    telegramConfigured: true,
    sessions: demoSessions,
    sessionFiles: {
      demo_webapp: [
        {
          id: "sf_release",
          title: "Release Summary",
          file_name: "release-summary.md",
          mime_type: "text/markdown",
          size_bytes: 4096,
          created_at: demoNow - 15_000,
          expires_at: demoNow + 24 * 3600 * 1000,
          created_by: "session:demo_webapp",
          wsl_path: "/home/demo/codrex-work/output/release-summary.md",
          download_url: "/codex/session/demo_webapp/files/sf_release/download",
        },
      ],
    },
    sessionNotes: {
      demo_webapp: [
        "Release checklist",
        "- regenerate screenshots",
        "- recheck Telegram status",
        "- push sanitized README",
      ].join("\n"),
    },
    threads: [
      {
        id: "thread_release",
        title: "Release Coordination",
        session: "demo_webapp",
        created_at: demoNow - 90_000,
        updated_at: demoNow - 25_000,
      },
    ],
    threadMessages: {
      thread_release: [
        {
          id: "msg_1",
          thread_id: "thread_release",
          role: "user",
          text: "Prepare the public repo assets and docs refresh.",
          at: demoNow - 89_000,
        },
        {
          id: "msg_2",
          thread_id: "thread_release",
          role: "assistant",
          text: "Replacing screenshots with mocked captures and rewriting setup docs.",
          at: demoNow - 60_000,
        },
      ],
    },
    tmuxPanes: demoTmuxPanes,
    tmuxPaneScreens: {
      "%14": [
        "$ git status --short",
        " M README.md",
        " M app/server.py",
        " M ui/src/App.tsx",
        "?? screenshots/launcher-overview.png",
        "",
        "$ python3 -m unittest tests.test_run_wsl_bash",
        "OK",
      ].join("\n"),
      "%15": [
        "PS D:\\codex-remote-ui> .\\Codrex.cmd",
        "Launcher ready on http://127.0.0.1:48787",
        "Waiting for browser connections...",
      ].join("\n"),
    },
    desktopInfo: {
      enabled: true,
      width: 1440,
      height: 900,
      perf_mode_enabled: true,
      perf_mode_active: true,
    },
    powerStatus: {
      relay_detail: "Wake relay is reachable on the private network.",
      wake_instruction: "/wake codrex-laptop",
      wake_transport_hint: "ethernet",
    },
    pairCode: "PAIR-7821",
    pairExpiresIn: 120,
    codexRuns: demoRuns,
    codexRunDetails: Object.fromEntries(demoRuns.map((run) => [run.id, run])),
  });

  await page.goto("/?tab=sessions", { waitUntil: "domcontentloaded" });
  await dismissSwipeHint(page);
  await page.getByRole("button", { name: /open demo_webapp/i }).click();
  await page.getByTestId("session-action-dock").getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByTestId("session-console")).toContainText("Plan for today:");
  await captureTab(page, "webui-tab-sessions.png");

  await page.goto("/?tab=threads", { waitUntil: "domcontentloaded" });
  await dismissSwipeHint(page);
  await page.getByTestId("threads-pane-select").selectOption("%14");
  await page.getByRole("button", { name: "Pull Pane" }).click();
  await expect(page.getByText("$ git status --short")).toBeVisible();
  await captureTab(page, "webui-tab-threads.png");

  await page.goto("/?tab=remote", { waitUntil: "domcontentloaded" });
  await dismissSwipeHint(page);
  await expect(page.getByAltText("Desktop stream")).toBeVisible();
  await expect(page.getByText("Boost active")).toBeVisible();
  await captureTab(page, "webui-tab-remote.png");

  await page.goto("/?tab=pair", { waitUntil: "domcontentloaded" });
  await dismissSwipeHint(page);
  await page.getByTestId("tab-panel-pair").getByRole("button", { name: "Generate QR" }).click();
  await expect(page.getByTestId("pair-link-text")).toContainText("PAIR-7821");
  await captureTab(page, "webui-tab-pair.png");

  await page.goto("/?tab=settings", { waitUntil: "domcontentloaded" });
  await dismissSwipeHint(page);
  await expect(page.getByTestId("tab-panel-settings")).toContainText("Network Diagnostics");
  await captureTab(page, "webui-tab-settings.png");

  await page.goto("/?tab=debug", { waitUntil: "domcontentloaded" });
  await dismissSwipeHint(page);
  await expect(page.getByTestId("tab-panel-debug")).toContainText("run_release_brief");
  await expect(page.getByTestId("tab-panel-debug")).toContainText("Launch summary:");
  await captureTab(page, "webui-tab-debug.png");

  const launcherHtml = await readFile(launcherHtmlPath, "utf8");
  const launcherQr = [
    "data:image/svg+xml;charset=utf-8,",
    encodeURIComponent(`
      <svg xmlns="http://www.w3.org/2000/svg" width="420" height="420" viewBox="0 0 420 420">
        <rect width="420" height="420" rx="24" fill="#ffffff"/>
        <rect x="36" y="36" width="348" height="348" fill="#f7fafc" stroke="#d4dce8"/>
        <rect x="68" y="68" width="78" height="78" fill="#101828"/>
        <rect x="274" y="68" width="78" height="78" fill="#101828"/>
        <rect x="68" y="274" width="78" height="78" fill="#101828"/>
        <rect x="176" y="84" width="22" height="22" fill="#101828"/>
        <rect x="220" y="84" width="22" height="22" fill="#101828"/>
        <rect x="176" y="128" width="22" height="22" fill="#101828"/>
        <rect x="220" y="128" width="22" height="22" fill="#101828"/>
        <rect x="176" y="172" width="22" height="22" fill="#101828"/>
        <rect x="220" y="172" width="22" height="22" fill="#101828"/>
        <rect x="264" y="172" width="22" height="22" fill="#101828"/>
        <rect x="176" y="216" width="22" height="22" fill="#101828"/>
        <rect x="220" y="216" width="22" height="22" fill="#101828"/>
        <rect x="264" y="216" width="22" height="22" fill="#101828"/>
        <rect x="176" y="260" width="22" height="22" fill="#101828"/>
        <rect x="220" y="260" width="22" height="22" fill="#101828"/>
        <rect x="264" y="260" width="22" height="22" fill="#101828"/>
      </svg>
    `),
  ].join("");

  await page.setViewportSize({ width: 1560, height: 980 });
  await page.setContent(launcherHtml, { waitUntil: "domcontentloaded" });
  await page.evaluate((payload) => {
    const renderFn = (window as unknown as { render?: (state: Record<string, unknown>) => void }).render;
    if (typeof renderFn !== "function") {
      throw new Error("Launcher render function is unavailable.");
    }
    renderFn(payload);
  }, {
    appVersion: "v1.5.0",
    controllerPort: 48787,
    route: "tailscale",
    routeHost: "100.64.0.9",
    status: "running",
    pairDetail: "Scan the QR code on a phone or tablet to pair quickly.",
    pairLink: "http://100.64.0.9:48787/auth/pair/consume?code=PAIR-7821",
    qrImageUrl: launcherQr,
    qrVisible: true,
    advancedVisible: true,
    repoRev: "public-demo",
    logsDir: "%LocalAppData%\\Codrex\\remote-ui\\logs",
  });
  await expect(page.getByText("Codrex Launcher")).toBeVisible();
  await captureTab(page, "launcher-overview.png");
});
