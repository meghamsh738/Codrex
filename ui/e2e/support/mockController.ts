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

export interface MockControllerOptions {
  authRequired?: boolean;
  authenticated?: boolean;
  sessions?: MockSession[];
  telegramConfigured?: boolean;
}

export interface PromptRequest {
  session: string;
  prompt: string;
}

export interface MockControllerHandle {
  promptRequests: PromptRequest[];
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
  const notesBySession = new Map<string, string>();
  const screenTextBySession = new Map(
    sessions.map((session) => [session.session, session.screenText ?? session.snippet ?? ""]),
  );

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
      runs: [],
    }),
  );

  await page.route(/\/threads(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      threads: [],
      messages: {},
    }),
  );

  await page.route(/\/tmux\/health(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      state: "ok",
      count: 0,
      sessions: [],
    }),
  );

  await page.route(/\/tmux\/panes(?:\?.*)?$/, async (route) =>
    json(route, {
      ok: true,
      panes: [],
    }),
  );

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
      width: 1440,
      height: 900,
    }),
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
      items: [],
    }),
  );

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
    promptRequests.push({
      session: sessionName,
      prompt: route.request().postData() ?? "",
    });
    await json(route, {
      ok: true,
      session: sessionName,
    });
  });

  return { promptRequests };
}

export async function dismissSwipeHint(page: Page): Promise<void> {
  const hint = page.getByTestId("dismiss-swipe-hint");
  if (await hint.isVisible().catch(() => false)) {
    await hint.click();
  }
}
