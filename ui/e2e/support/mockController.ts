import type { Page, Route } from "@playwright/test";

export interface MockSession {
  session: string;
  pane_id: string;
  cwd: string;
  state: string;
  current_command: string;
  snippet: string;
  model?: string;
  reasoning_effort?: string;
  screenText?: string;
}

export interface MockSessionFile {
  id: string;
  title: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  created_at: number;
  expires_at: number;
  created_by?: string;
  is_image?: boolean;
  item_kind?: "file" | "directory";
  source_kind?: string;
  wsl_path: string;
  download_url: string;
}

export interface MockThread {
  id: string;
  title: string;
  session: string;
  created_at: number;
  updated_at: number;
}

export interface MockThreadMessage {
  id: string;
  thread_id: string;
  role: "user" | "assistant" | "system";
  text: string;
  at: number;
}

export interface MockTmuxPane {
  session: string;
  window_index: string;
  pane_index: string;
  pane_id: string;
  active: boolean;
  current_command: string;
  current_path: string;
}

export interface MockCodexRun {
  id: string;
  status: "running" | "done" | "error";
  duration_s?: number | null;
  prompt?: string;
  created_at?: number;
  output?: string;
  exit_code?: number | null;
  finished_at?: number | null;
}

export interface MockControllerOptions {
  authRequired?: boolean;
  authenticated?: boolean;
  sessions?: MockSession[];
  telegramConfigured?: boolean;
  sessionFiles?: Record<string, MockSessionFile[]>;
  sessionNotes?: Record<string, string>;
  threads?: MockThread[];
  threadMessages?: Record<string, MockThreadMessage[]>;
  tmuxPanes?: MockTmuxPane[];
  tmuxPaneScreens?: Record<string, string>;
  desktopInfo?: Record<string, unknown>;
  desktopFrameSvg?: string;
  desktopShotSvg?: string;
  powerStatus?: Record<string, unknown>;
  pairCode?: string;
  pairExpiresIn?: number;
  codexRuns?: MockCodexRun[];
  codexRunDetails?: Record<string, MockCodexRun>;
}

export interface PromptRequest {
  session: string;
  prompt: string;
}

export interface TelegramSendRequest {
  session: string;
  fileId: string;
}

export interface MockControllerHandle {
  promptRequests: PromptRequest[];
  telegramSendRequests: TelegramSendRequest[];
}

function json(route: Route, payload: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: "application/json; charset=utf-8",
    body: JSON.stringify(payload),
  });
}

function sse(route: Route, events: Array<{ event: string; data: unknown }>): Promise<void> {
  const body = events
    .map(({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
    .join("");
  return route.fulfill({
    status: 200,
    contentType: "text/event-stream; charset=utf-8",
    body,
    headers: {
      "cache-control": "no-cache",
      connection: "keep-alive",
    },
  });
}

function text(route: Route, body: string, contentType: string): Promise<void> {
  return route.fulfill({
    status: 200,
    contentType,
    body,
  });
}

function decodeSessionName(url: string): string {
  const match = url.match(/\/codex\/session\/([^/]+)\//);
  return match ? decodeURIComponent(match[1] || "") : "";
}

export async function installMockController(
  page: Page,
  options: MockControllerOptions = {},
): Promise<MockControllerHandle> {
  const sessions = options.sessions ?? [];
  const promptRequests: PromptRequest[] = [];
  const telegramSendRequests: TelegramSendRequest[] = [];
  const notesBySession = new Map<string, string>();
  const sessionFilesBySession = new Map(
    Object.entries(options.sessionFiles ?? {}),
  );
  const screenTextBySession = new Map(
    sessions.map((session) => [session.session, session.screenText ?? session.snippet ?? ""]),
  );
  const notesSeed = options.sessionNotes ?? {};
  const tmuxPanes = options.tmuxPanes ?? [];
  const tmuxPaneScreens = new Map(Object.entries(options.tmuxPaneScreens ?? {}));
  const threadMessages = options.threadMessages ?? {};
  const codexRuns = options.codexRuns ?? [];
  const codexRunDetails = options.codexRunDetails ?? {};

  Object.entries(notesSeed).forEach(([session, content]) => {
    notesBySession.set(session, content);
  });

  await page.route(/\/app\/runtime(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      version: "1.5.0",
      ui_mode: "built",
      build_present: true,
      controller_port: 48787,
      controller_origin: "http://127.0.0.1:48787",
    }),
  );

  await page.route(/\/auth\/status(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      auth_required: options.authRequired ?? true,
      authenticated: options.authenticated ?? true,
    }),
  );

  await page.route(/\/net\/info(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      lan_ip: "192.168.1.15",
      tailscale_ip: "100.64.0.9",
    }),
  );

  await page.route(/\/telegram\/status(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      configured: options.telegramConfigured ?? false,
      default_send: false,
      chat_id_masked: "",
      bot_token_masked: "",
      api_base: "https://api.telegram.org",
      max_file_mb: 45,
    }),
  );

  await page.route(/\/telegram\/send-text(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      detail: "Sent to Telegram.",
    }),
  );

  await page.route(/\/power\/status(?:\?.*)?$/, async (route) =>
    json(route, {
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
      ...(options.powerStatus ?? {}),
    }),
  );

  await page.route(/\/codex\/options(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      models: ["gpt-5-codex", "gpt-5"],
      default_model: "gpt-5-codex",
      reasoning_efforts: ["low", "medium", "high"],
      default_reasoning_effort: "high",
    }),
  );

  await page.route(/\/codex\/runs(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      runs: codexRuns.map(({ output: _output, exit_code: _exitCode, finished_at: _finishedAt, created_at: _createdAt, ...summary }) => summary),
    }),
  );

  await page.route(/\/codex\/run\/[^/]+(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const runId = decodeURIComponent(url.pathname.split("/").pop() || "");
    const detail = codexRunDetails[runId] ?? codexRuns.find((run) => run.id === runId);
    await json(route, {
      ok: true,
      id: runId,
      status: detail?.status ?? "done",
      duration_s: detail?.duration_s ?? 4.8,
      prompt: detail?.prompt ?? "Summarize the current release status.",
      output: detail?.output ?? "Release dry run complete.\n- 4 checks passed\n- 1 follow-up note drafted",
      exit_code: detail?.exit_code ?? 0,
      created_at: detail?.created_at ?? Date.now() - 45_000,
      finished_at: detail?.finished_at ?? Date.now() - 12_000,
    });
  });

  await page.route(/\/threads(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      threads: options.threads ?? [],
      messages: threadMessages,
    }),
  );

  await page.route(/\/tmux\/health(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      state: tmuxPanes.length > 0 ? "ok" : "empty",
      count: tmuxPanes.length,
      sessions: [...new Set(tmuxPanes.map((pane) => pane.session))],
    }),
  );

  await page.route(/\/tmux\/panes(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      panes: tmuxPanes,
    }),
  );

  await page.route(/\/tmux\/pane\/[^/]+\/screen(?:\?.*)?$/, async (route) => {
    const url = route.request().url();
    const paneMatch = url.match(/\/tmux\/pane\/([^/]+)\/screen/);
    const paneId = paneMatch ? decodeURIComponent(paneMatch[1] || "") : "%1";
    const pane = tmuxPanes.find((entry) => entry.pane_id === paneId);
    await json(route, {
      ok: true,
      pane_id: paneId,
      text: tmuxPaneScreens.get(paneId) ?? pane?.current_command ?? "",
    });
  });

  await page.route(/\/tmux\/pane\/.+\/stream(?:\?.*)?$/, async (route) => {
    const url = route.request().url();
    const paneMatch = url.match(/\/tmux\/pane\/([^/]+)\/stream/);
    const paneId = paneMatch ? decodeURIComponent(paneMatch[1] || "") : "%1";
    const session = sessions.find((entry) => entry.pane_id === paneId || encodeURIComponent(entry.pane_id) === paneMatch?.[1]);
    const text = session ? screenTextBySession.get(session.session) ?? "" : "";
    await sse(route, [
      {
        event: "hello",
        data: { ok: true, pane_id: paneId, interval_ms: 800, max_chars: 25000 },
      },
      {
        event: "screen",
        data: { ok: true, pane_id: paneId, seq: 1, ts: Date.now() / 1000, text },
      },
    ]);
  });

  await page.route(/\/desktop\/info(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      enabled: true,
      width: 1440,
      height: 900,
      alt_held: false,
      perf_mode_enabled: true,
      perf_mode_active: true,
      ...(options.desktopInfo ?? {}),
    }),
  );

  await page.route(/\/desktop\/stream(?:\?.*)?$/, async (route) =>
    text(
      route,
      options.desktopFrameSvg ?? `
<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="900" viewBox="0 0 1440 900">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="#0d1016"/>
      <stop offset="100%" stop-color="#161b24"/>
    </linearGradient>
  </defs>
  <rect width="1440" height="900" fill="url(#bg)"/>
  <rect x="0" y="0" width="1440" height="42" fill="#111722"/>
  <text x="24" y="27" fill="#d8e3f2" font-size="20" font-family="Segoe UI, Arial, sans-serif">Codrex Host Desktop</text>
  <rect x="92" y="90" width="980" height="620" rx="18" fill="#fbfdff" stroke="#8ba2bc" stroke-width="2"/>
  <rect x="92" y="90" width="980" height="48" rx="18" fill="#dbe9f7"/>
  <circle cx="124" cy="114" r="7" fill="#ff7f7f"/>
  <circle cx="148" cy="114" r="7" fill="#ffd166"/>
  <circle cx="172" cy="114" r="7" fill="#5dd39e"/>
  <text x="206" y="121" fill="#234" font-size="20" font-family="Segoe UI, Arial, sans-serif">Release Dashboard</text>
  <rect x="124" y="170" width="300" height="112" rx="14" fill="#0d1b2a"/>
  <text x="146" y="204" fill="#8bd3ff" font-size="18" font-family="Cascadia Code, Consolas, monospace">STATUS</text>
  <text x="146" y="242" fill="#ffffff" font-size="28" font-family="Segoe UI, Arial, sans-serif">Stream-ready profile</text>
  <text x="146" y="270" fill="#9fb3c8" font-size="18" font-family="Segoe UI, Arial, sans-serif">Reduced motion + black wallpaper</text>
  <rect x="450" y="170" width="580" height="420" rx="14" fill="#f6f8fb" stroke="#d3dce8"/>
  <text x="474" y="210" fill="#234" font-size="20" font-family="Segoe UI, Arial, sans-serif">Checklist</text>
  <text x="474" y="252" fill="#375a7f" font-size="18" font-family="Segoe UI, Arial, sans-serif">1. Validate remote stream readability</text>
  <text x="474" y="286" fill="#375a7f" font-size="18" font-family="Segoe UI, Arial, sans-serif">2. Confirm desktop boost mode is active</text>
  <text x="474" y="320" fill="#375a7f" font-size="18" font-family="Segoe UI, Arial, sans-serif">3. Restore full desktop after stop</text>
  <rect x="474" y="360" width="514" height="190" rx="14" fill="#0f1722"/>
  <text x="500" y="400" fill="#9de1ff" font-size="18" font-family="Cascadia Code, Consolas, monospace">codex_demo&gt; status</text>
  <text x="500" y="438" fill="#dce7f5" font-size="17" font-family="Cascadia Code, Consolas, monospace">mode: performance streaming</text>
  <text x="500" y="470" fill="#dce7f5" font-size="17" font-family="Cascadia Code, Consolas, monospace">wallpaper: black</text>
  <text x="500" y="502" fill="#dce7f5" font-size="17" font-family="Cascadia Code, Consolas, monospace">transparency: off</text>
  <text x="500" y="534" fill="#dce7f5" font-size="17" font-family="Cascadia Code, Consolas, monospace">animations: reduced</text>
  <rect x="1120" y="126" width="264" height="742" rx="22" fill="#111822" stroke="#25374a"/>
  <text x="1150" y="176" fill="#dfe8f3" font-size="24" font-family="Segoe UI, Arial, sans-serif">Pinned Actions</text>
  <rect x="1150" y="220" width="204" height="58" rx="14" fill="#1a2634"/>
  <rect x="1150" y="298" width="204" height="58" rx="14" fill="#1a2634"/>
  <rect x="1150" y="376" width="204" height="58" rx="14" fill="#1a2634"/>
  <text x="1170" y="257" fill="#9bd0ff" font-size="18" font-family="Segoe UI, Arial, sans-serif">Open Web UI</text>
  <text x="1170" y="335" fill="#9bd0ff" font-size="18" font-family="Segoe UI, Arial, sans-serif">Copy Pair Link</text>
  <text x="1170" y="413" fill="#9bd0ff" font-size="18" font-family="Segoe UI, Arial, sans-serif">Stop Host</text>
</svg>`,
      "image/svg+xml; charset=utf-8",
    ),
  );

  await page.route(/\/desktop\/shot(?:\?.*)?$/, async (route) =>
    text(
      route,
      options.desktopShotSvg ?? options.desktopFrameSvg ?? `
<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="900" viewBox="0 0 1440 900">
  <rect width="1440" height="900" fill="#0f1319"/>
  <text x="72" y="112" fill="#f0f5fb" font-size="42" font-family="Segoe UI, Arial, sans-serif">Codrex Remote Capture</text>
  <text x="72" y="170" fill="#8ba2bc" font-size="24" font-family="Segoe UI, Arial, sans-serif">Sanitized demo capture used for repository screenshots.</text>
</svg>`,
      "image/svg+xml; charset=utf-8",
    ),
  );

  await page.route(/\/desktop\/input\/move(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      x: 120,
      y: 80,
    }),
  );

  await page.route(/\/shares(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      items: [],
    }),
  );

  await page.route(/\/auth\/pair\/create(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      code: options.pairCode ?? "PAIR-7821",
      expires_in: options.pairExpiresIn ?? 120,
    }),
  );

  await page.route(/\/auth\/pair\/qr\.png(?:\?.*)?$/, async (route) =>
    text(
      route,
      `
<svg xmlns="http://www.w3.org/2000/svg" width="520" height="520" viewBox="0 0 520 520">
  <rect width="520" height="520" rx="24" fill="#ffffff"/>
  <rect x="28" y="28" width="464" height="464" fill="#f5f8fb" stroke="#d7dfeb"/>
  <rect x="56" y="56" width="96" height="96" fill="#101828"/>
  <rect x="368" y="56" width="96" height="96" fill="#101828"/>
  <rect x="56" y="368" width="96" height="96" fill="#101828"/>
  <rect x="184" y="72" width="24" height="24" fill="#101828"/>
  <rect x="232" y="72" width="24" height="24" fill="#101828"/>
  <rect x="280" y="72" width="24" height="24" fill="#101828"/>
  <rect x="184" y="120" width="24" height="24" fill="#101828"/>
  <rect x="232" y="120" width="24" height="24" fill="#101828"/>
  <rect x="280" y="120" width="24" height="24" fill="#101828"/>
  <rect x="184" y="184" width="24" height="24" fill="#101828"/>
  <rect x="232" y="184" width="24" height="24" fill="#101828"/>
  <rect x="280" y="184" width="24" height="24" fill="#101828"/>
  <rect x="328" y="184" width="24" height="24" fill="#101828"/>
  <rect x="184" y="232" width="24" height="24" fill="#101828"/>
  <rect x="280" y="232" width="24" height="24" fill="#101828"/>
  <rect x="328" y="232" width="24" height="24" fill="#101828"/>
  <rect x="232" y="280" width="24" height="24" fill="#101828"/>
  <rect x="280" y="280" width="24" height="24" fill="#101828"/>
  <rect x="328" y="280" width="24" height="24" fill="#101828"/>
  <rect x="184" y="328" width="24" height="24" fill="#101828"/>
  <rect x="232" y="328" width="24" height="24" fill="#101828"/>
  <rect x="280" y="328" width="24" height="24" fill="#101828"/>
  <rect x="328" y="328" width="24" height="24" fill="#101828"/>
  <rect x="368" y="328" width="24" height="24" fill="#101828"/>
  <text x="56" y="498" fill="#475467" font-size="20" font-family="Segoe UI, Arial, sans-serif">Demo pairing QR</text>
</svg>`,
      "image/svg+xml; charset=utf-8",
    ),
  );

  await page.route(/\/codex\/sessions(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      sessions: sessions.map(({ screenText: _screenText, ...session }) => session),
    }),
  );

  await page.route(/\/codex\/session\/[^/]+\/screen(?:\?.*)?$/, async (route) => {
    const sessionName = decodeSessionName(route.request().url());
    const session = sessions.find((entry) => entry.session === sessionName);
    await json(route, {
      ok: true,
      session: sessionName,
      pane_id: session?.pane_id ?? "%1",
      current_command: session?.current_command ?? "codex",
      state: session?.state ?? "idle",
      text: screenTextBySession.get(sessionName) ?? "",
    });
  });

  await page.route(/\/codex\/session\/[^/]+\/files(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      session: decodeSessionName(route.request().url()),
      items: sessionFilesBySession.get(decodeSessionName(route.request().url())) ?? [],
    }),
  );

  await page.route(/\/codex\/session\/[^/]+\/files\/[^/]+\/telegram(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const match = url.pathname.match(/\/codex\/session\/([^/]+)\/files\/([^/]+)\/telegram$/);
    telegramSendRequests.push({
      session: decodeURIComponent(match?.[1] ?? ""),
      fileId: decodeURIComponent(match?.[2] ?? ""),
    });
    await json(route, {
      ok: true,
      detail: "Sent to Telegram.",
    });
  });

  await page.route(/\/codex\/session\/[^/]+\/notes\/append-latest(?:\?.*)?$/, async (route) => {
    const sessionName = decodeSessionName(route.request().url());
    const screenText = screenTextBySession.get(sessionName) ?? "";
    const compact = screenText.split(/\r?\n/).map((line) => line.trimEnd()).filter(Boolean).slice(-24).join("\n");
    const existing = notesBySession.get(sessionName)?.trim();
    const next = existing ? `${existing}\n\n${compact}` : compact;
    notesBySession.set(sessionName, next);
    await json(route, {
      ok: true,
      session: sessionName,
      appended_text: compact,
      notes: {
        session: sessionName,
        content: next,
        created_at: Date.now(),
        updated_at: Date.now(),
        last_response_snapshot: compact,
      },
    });
  });

  await page.route(/\/codex\/session\/[^/]+\/notes(?:\?.*)?$/, async (route) => {
    const sessionName = decodeSessionName(route.request().url());
    if (route.request().method() === "POST") {
      const payload = route.request().postDataJSON() as { content?: string; last_response_snapshot?: string };
      const next = payload?.content ?? "";
      notesBySession.set(sessionName, next);
      await json(route, {
        ok: true,
        session: sessionName,
        notes: {
          session: sessionName,
          content: next,
          created_at: Date.now(),
          updated_at: Date.now(),
          last_response_snapshot: payload?.last_response_snapshot ?? "",
        },
      });
      return;
    }
    await json(route, {
      ok: true,
      session: sessionName,
      notes: {
        session: sessionName,
        content: notesBySession.get(sessionName) ?? "",
        created_at: Date.now(),
        updated_at: Date.now(),
        last_response_snapshot: "",
      },
    });
  });

  await page.route(/\/codex\/session\/[^/]+\/send(?:\?.*)?$/, async (route) => {
    const sessionName = decodeSessionName(route.request().url());
    const prompt = route.request().postData() ?? "";
    promptRequests.push({
      session: sessionName,
      prompt,
    });
    if (prompt.startsWith("/tgsend ")) {
      const firstFile = (sessionFilesBySession.get(sessionName) ?? []).find((item) => item.item_kind !== "directory");
      await json(route, {
        ok: true,
        session: sessionName,
        session_file: firstFile ?? null,
        detail: "Shared file added to mobile inbox and sent to Telegram.",
      });
      return;
    }
    await json(route, {
      ok: true,
      session: sessionName,
    });
  });

  return { promptRequests, telegramSendRequests };
}

export async function dismissSwipeHint(page: Page): Promise<void> {
  const hint = page.getByTestId("dismiss-swipe-hint");
  if (await hint.isVisible().catch(() => false)) {
    await hint.click();
  }
}
