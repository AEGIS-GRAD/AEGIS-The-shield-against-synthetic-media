/**
 * Visual Regression Snapshots
 * ============================
 * Full-page screenshots of key pages compared against stored baselines.
 *
 * FIRST RUN (create baseline):
 *   npx playwright test e2e/snapshots.spec.ts --update-snapshots
 *
 * SUBSEQUENT RUNS (regression check):
 *   npx playwright test e2e/snapshots.spec.ts
 *
 * Baselines are stored in e2e/snapshots/ and committed to git.
 * A failing pixel-diff means a visual regression — review the diff image
 * in playwright-report/ and either fix the regression or update the baseline.
 */

import { test, expect } from "@playwright/test";

// Allow up to 0.5% pixel difference (anti-aliasing / font rendering variance)
const SNAPSHOT_OPTIONS = {
  maxDiffPixelRatio: 0.005,
  threshold: 0.1, // per-pixel colour tolerance 0–1
};

test.describe("Visual Regression Snapshots", () => {
  test("Home page — full-page snapshot", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    // Stabilise any animated elements
    await page.waitForTimeout(500);
    await expect(page).toHaveScreenshot("home.png", {
      fullPage: true,
      ...SNAPSHOT_OPTIONS,
    });
  });

  test("Analyze page — full-page snapshot", async ({ page }) => {
    await page.goto("/analyze");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await expect(page).toHaveScreenshot("analyze.png", {
      fullPage: true,
      ...SNAPSHOT_OPTIONS,
    });
  });

  test("Reports list — full-page snapshot (demo data on)", async ({ page }) => {
    await page.goto("/reports");
    await page.waitForLoadState("networkidle");

    const demoSwitch = page.getByRole("switch", { name: "Demo data" }).first();
    if (await demoSwitch.isVisible()) {
      if ((await demoSwitch.getAttribute("aria-checked")) !== "true") {
        await demoSwitch.click();
        await page.waitForTimeout(600);
      }
    }

    await page.waitForTimeout(400);
    await expect(page).toHaveScreenshot("reports-list.png", {
      fullPage: true,
      ...SNAPSHOT_OPTIONS,
    });
  });

  test("Report detail (clean_baseline) — full-page snapshot", async ({ page }) => {
    await page.goto("/reports/clean_baseline");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await expect(page).toHaveScreenshot("report-detail-clean-baseline.png", {
      fullPage: true,
      ...SNAPSHOT_OPTIONS,
    });
  });

  test("Live page — full-page snapshot", async ({ page }) => {
    await page.goto("/live");
    await page.waitForLoadState("networkidle");
    // Freeze any animated chart/pulse to get stable snapshot
    await page.addStyleTag({
      content: `
        *, *::before, *::after {
          animation-duration: 0s !important;
          transition-duration: 0s !important;
        }
      `,
    });
    await page.waitForTimeout(400);
    await expect(page).toHaveScreenshot("live.png", {
      fullPage: true,
      ...SNAPSHOT_OPTIONS,
    });
  });

  test("Settings page — full-page snapshot", async ({ page }) => {
    await page.goto("/settings");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(300);
    await expect(page).toHaveScreenshot("settings.png", {
      fullPage: true,
      ...SNAPSHOT_OPTIONS,
    });
  });

  // Mobile viewport snapshots (375px wide)
  test.describe("Mobile (375px) snapshots", () => {
    test.use({ viewport: { width: 375, height: 812 } });

    test("Home — mobile snapshot", async ({ page }) => {
      await page.goto("/");
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(500);
      await expect(page).toHaveScreenshot("home-mobile.png", {
        fullPage: true,
        ...SNAPSHOT_OPTIONS,
      });
    });

    test("Analyze — mobile snapshot", async ({ page }) => {
      await page.goto("/analyze");
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(400);
      await expect(page).toHaveScreenshot("analyze-mobile.png", {
        fullPage: true,
        ...SNAPSHOT_OPTIONS,
      });
    });
  });
});
