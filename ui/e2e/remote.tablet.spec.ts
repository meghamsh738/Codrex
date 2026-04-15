import { expect, test } from "@playwright/test";

import { dismissSwipeHint, installMockController } from "./support/mockController";

test.describe("tablet remote controls", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.clear();
      window.sessionStorage.clear();
    });
  });

  test("keeps tablet remote controls readable and shows fullscreen windows actions", async ({ page }) => {
    await installMockController(page, {
      desktopInfo: {
        enabled: true,
        width: 1920,
        height: 1080,
        perf_mode_enabled: true,
        perf_mode_active: true,
      },
    });

    await page.setViewportSize({ width: 1180, height: 820 });
    await page.goto("/?tab=remote", { waitUntil: "domcontentloaded" });
    await dismissSwipeHint(page);

    const remotePanel = page.getByTestId("tab-panel-remote");
    await expect(remotePanel.getByTestId("remote-win-start")).toBeVisible();
    await expect(remotePanel.getByTestId("remote-win-left")).toBeVisible();
    await expect(remotePanel.getByTestId("remote-win-right")).toBeVisible();
    await expect(remotePanel.getByTestId("remote-task-view")).toBeVisible();

    const overflow = await remotePanel.evaluate((node) => ({
      clientWidth: node.clientWidth,
      scrollWidth: node.scrollWidth,
    }));
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);

    await page.getByTestId("remote-fullscreen-toggle").click();
    await expect(page.getByTestId("remote-overlay-win")).toBeVisible();
    await expect(page.getByTestId("remote-overlay-win-left")).toBeVisible();
    await expect(page.getByTestId("remote-overlay-win-right")).toBeVisible();
    await expect(page.getByTestId("remote-overlay-switch-tab")).toBeVisible();
  });
});
