import { expect, test } from "@playwright/test";

import { dismissSwipeHint, installMockController } from "./support/mockController";

test.describe("mobile Sessions flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.clear();
      window.sessionStorage.clear();
    });
  });

  test("renders a mobile session, loads output, and sends a prompt", async ({ page }, testInfo) => {
    const mock = await installMockController(page, {
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%7",
          cwd: "/home/megha/codrex-work/mobile-app",
          state: "running",
          current_command: "codex",
          snippet: "Generating release notes...",
          model: "gpt-5-codex",
          reasoning_effort: "high",
          screenText: "Generating release notes...\nStreaming mobile session output.",
        },
        {
          session: "codex_docs",
          pane_id: "%8",
          cwd: "/home/megha/codrex-work/docs",
          state: "idle",
          current_command: "bash",
          snippet: "No output yet.",
          model: "gpt-5",
          reasoning_effort: "medium",
          screenText: "Idle.",
        },
      ],
    });

    await page.goto("/", { waitUntil: "domcontentloaded" });
    await dismissSwipeHint(page);

    await expect(page.getByTestId("tab-panel-sessions")).toBeVisible();
    await expect(page.getByRole("button", { name: /codex_demo/i })).toBeVisible();

    await page.getByRole("button", { name: /codex_demo/i }).click();

    const sessionDetail = page.getByTestId("session-detail");
    await expect(sessionDetail).toContainText("codex_demo");
    await expect(sessionDetail.locator(".console")).toContainText("Streaming mobile session output.");

    const composer = page.getByRole("textbox", { name: "Prompt Composer" });
    await composer.fill("Summarize the latest build status.");
    await page.getByTestId("composer-send-prompt").click();

    await expect.poll(() => mock.promptRequests.length).toBe(1);
    await expect.poll(() => mock.promptRequests[0]?.session ?? "").toBe("codex_demo");
    await expect.poll(() => mock.promptRequests[0]?.prompt ?? "").toBe("Summarize the latest build status.");

    const notesInput = page.getByTestId("session-notes-input");
    await notesInput.fill("Release checklist");
    await page.getByRole("button", { name: "Save" }).click();
    await page.getByRole("button", { name: "Append Latest Response" }).click();
    await expect(notesInput).toContainText("Streaming mobile session output.");

    await testInfo.attach("sessions-mobile-shell", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });
  });

  test("shows the no-match empty state when the session filter excludes all sessions", async ({ page }) => {
    await installMockController(page, {
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%7",
          cwd: "/home/megha/codrex-work/mobile-app",
          state: "running",
          current_command: "codex",
          snippet: "Generating release notes...",
          model: "gpt-5-codex",
          reasoning_effort: "high",
          screenText: "Generating release notes...\nStreaming mobile session output.",
        },
      ],
    });

    await page.goto("/", { waitUntil: "domcontentloaded" });
    await dismissSwipeHint(page);

    await page.getByTestId("session-search-input").fill("missing-session-name");
    await expect(page.getByTestId("tab-panel-sessions")).toContainText("No matching sessions");
  });

  test("keeps the sessions workspace readable on tablet landscape without horizontal overflow", async ({ page }, testInfo) => {
    const mock = await installMockController(page, {
      sessions: [
        {
          session: "codex_demo",
          pane_id: "%7",
          cwd: "/home/megha/codrex-work/mobile-app",
          state: "running",
          current_command: "codex",
          snippet: "Generating release notes...",
          model: "gpt-5-codex",
          reasoning_effort: "high",
          screenText: "Generating release notes...\nStreaming mobile session output.\n\nChecklist:\n- Review build\n- Publish notes\n- Send rollout update",
        },
      ],
    });

    await page.setViewportSize({ width: 1180, height: 820 });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await dismissSwipeHint(page);

    await page.getByRole("button", { name: /codex_demo/i }).click();
    await page.getByTestId("session-pane-tab-files").click();
    await page.getByTestId("session-pane-tab-setup").click();
    await page.getByTestId("session-pane-tab-notes").click();

    const overflow = await page.getByTestId("session-detail").evaluate((node) => ({
      clientWidth: node.clientWidth,
      scrollWidth: node.scrollWidth,
    }));
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);

    await expect(page.getByTestId("session-console")).toContainText("Streaming mobile session output.");
    await expect.poll(() => mock.promptRequests.length).toBe(0);

    await testInfo.attach("sessions-tablet-landscape", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });
  });
});
