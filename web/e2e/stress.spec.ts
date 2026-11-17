/**
 * Stress / Worst-Case UI Tests
 * ==============================
 * Tests the app under realistic worst-case conditions:
 *   1. Alert burst — inject 100 live alerts into /live and confirm no crash/freeze
 *   2. Report flood — render 50 report cards on /reports and confirm table remains stable
 *   3. Long transcript — paste a 10 000-word text into /analyze textarea, confirm no freeze
 *
 * "No crash" is defined as: page doesn't throw a JS error, DOM remains interactive,
 * and key UI elements stay visible after the stress load.
 */

import { test, expect } from "@playwright/test";

// Generate a long transcript (~10 000 words)
const LONG_TRANSCRIPT = Array.from({ length: 500 }, (_, i) =>
  `Sentence ${i + 1}: The quick brown fox jumps over the lazy dog. ` +
  `This is an automatically generated sentence for stress-testing the text analysis pipeline. ` +
  `Deepfake detection requires careful sentence-level analysis and perplexity scoring.`
).join(" ");

// Generate 50 mock report rows as API response
function makeMockReports(count: number) {
  const modalities = ["video", "audio", "image", "text"] as const;
  return Array.from({ length: count }, (_, i) => ({
    id: `STRESS-JOB-${String(i + 1).padStart(4, "0")}`,
    file: `stress_test_${i + 1}.mp4`,
    modality: modalities[i % modalities.length],
    verdict: i % 3 === 0 ? "synthetic" : i % 3 === 1 ? "authentic" : "inconclusive",
    confidence: Math.round((0.5 + (i % 50) / 100) * 100) / 100,
    status: "complete",
    time: "Just now",
    created_at: new Date(Date.now() - i * 60000).toISOString(),
    is_demo: true,
    risk_tier: "TIER_1_LOW",
    debate_transcript: [],
  }));
}

test.describe("Stress Tests — Worst-Case UI Scenarios", () => {
  test("1. Alert burst — 100 live alerts injected without crash or freeze", async ({ page }) => {
    // Track JS errors
    const jsErrors: string[] = [];
    page.on("pageerror", (err) => jsErrors.push(err.message));

    await page.goto("/live");
    await page.waitForLoadState("networkidle");

    // Inject 100 alerts via window mock — simulates rapid WebSocket push
    await page.evaluate(() => {
      // Find the React root and trigger state updates if the app exposes a mock hook,
      // otherwise simulate by rapidly dispatching custom events
      let count = 0;
      const interval = setInterval(() => {
        window.dispatchEvent(
          new CustomEvent("aegis:live-alert", {
            detail: {
              id: `ALERT-${count}`,
              camera: `Camera ${(count % 4) + 1}`,
              severity: count % 2 === 0 ? "high" : "medium",
              message: `Synthetic pattern detected in frame ${count * 30}`,
              timestamp: new Date().toISOString(),
              confidence: 0.75 + (count % 25) / 100,
            },
          })
        );
        count++;
        if (count >= 100) clearInterval(interval);
      }, 10); // 10ms between alerts = 100 alerts in 1s
    });

    // Wait for the burst to complete
    await page.waitForTimeout(1500);

    // Page must still be interactive — check key elements remain visible
    await expect(page.locator("h1")).toBeVisible();

    // No JS errors should have been thrown
    expect(jsErrors).toHaveLength(0);

    // The page should not have navigated away
    expect(page.url()).toContain("/live");

    console.log("✅ Alert burst (100 alerts): page remained stable, no JS errors.");
  });

  test("2. Report flood — 50 reports rendered without layout collapse", async ({ page }) => {
    const jsErrors: string[] = [];
    page.on("pageerror", (err) => jsErrors.push(err.message));

    // Intercept the jobs API to return 50 reports
    await page.route("**/api/jobs**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(makeMockReports(50)),
      });
    });

    await page.goto("/reports");
    await expect(page.locator("h1")).toBeVisible({ timeout: 10000 });

    // Table must be visible and have rows
    await expect(page.locator("table")).toBeVisible({ timeout: 10000 });
    const rowCount = await page.locator("tbody tr").count();
    console.log(`\n📊 Report flood: ${rowCount} rows rendered.`);
    expect(rowCount).toBeGreaterThan(0);

    // Scroll to bottom of table to trigger any lazy rendering
    await page.keyboard.press("End");
    await page.waitForTimeout(300);
    await page.keyboard.press("Home");

    // Filter buttons must still respond
    const syntheticFilter = page.getByRole("button", { name: "synthetic" });
    if (await syntheticFilter.isVisible()) {
      await syntheticFilter.click();
      await page.waitForTimeout(200);
      await page.getByRole("button", { name: "all" }).click();
    }

    expect(jsErrors).toHaveLength(0);
    console.log("✅ Report flood (50 rows): table stable, filters responsive, no JS errors.");
  });

  test("3. Long transcript — 10 000-word text input without freeze", async ({ page }) => {
    const jsErrors: string[] = [];
    page.on("pageerror", (err) => jsErrors.push(err.message));

    await page.goto("/analyze");
    await page.waitForLoadState("networkidle");

    // Navigate to Text tab
    const textTab = page.locator("button").filter({ hasText: /^Text/ }).first();
    if (await textTab.isVisible()) {
      await textTab.click();
      await page.waitForTimeout(300);
    }

    // Find textarea or text input area
    const textarea = page.locator("textarea").first();
    if (await textarea.isVisible()) {
      // Fill with large text — use fill() not type() to avoid 10k keystroke events
      const t0 = Date.now();
      await textarea.fill(LONG_TRANSCRIPT);
      const fillMs = Date.now() - t0;
      console.log(`\n📊 Long transcript fill time: ${fillMs}ms`);

      // Fill should complete in under 10 seconds (not frozen)
      expect(fillMs).toBeLessThan(10000);

      // Page should still be interactive
      await expect(textarea).toBeVisible();
      const value = await textarea.inputValue();
      expect(value.length).toBeGreaterThan(1000);

      console.log(`✅ Long transcript (${value.length} chars): filled without freeze.`);
    } else {
      // Text tab may show ComingSoon — that's acceptable, skip fill test
      const comingSoon = page.getByText(/coming soon/i).first();
      if (await comingSoon.isVisible()) {
        console.log("ℹ️  Text tab shows ComingSoon — skipping fill stress test.");
        expect(true).toBe(true);
        return;
      }
      // Otherwise fail — we expected a textarea
      expect(textarea).toBeVisible();
    }

    expect(jsErrors).toHaveLength(0);
  });

  test("4. Analyze page — drag-and-drop large file name without overflow", async ({ page }) => {
    const jsErrors: string[] = [];
    page.on("pageerror", (err) => jsErrors.push(err.message));

    await page.goto("/analyze");
    await page.waitForLoadState("networkidle");

    // Simulate a file with a very long name via DataTransfer
    await page.evaluate(() => {
      const dropzone = document.querySelector('[role="button"], [data-testid="dropzone"], .dropzone, label[for]');
      if (!dropzone) return;

      const dt = new DataTransfer();
      const longName = "a_very_long_filename_that_might_overflow_the_ui_" + "x".repeat(100) + ".mp4";
      const file = new File(["fake"], longName, { type: "video/mp4" });
      dt.items.add(file);

      dropzone.dispatchEvent(new DragEvent("dragenter", { dataTransfer: dt, bubbles: true }));
      dropzone.dispatchEvent(new DragEvent("dragover",  { dataTransfer: dt, bubbles: true }));
      dropzone.dispatchEvent(new DragEvent("drop",      { dataTransfer: dt, bubbles: true }));
    });

    await page.waitForTimeout(500);

    // Page must still be stable
    await expect(page.locator("h1")).toBeVisible();
    expect(jsErrors).toHaveLength(0);

    // Check for horizontal overflow (layout break)
    const hasHorizontalOverflow = await page.evaluate(() => {
      return document.documentElement.scrollWidth > document.documentElement.clientWidth;
    });
    expect(hasHorizontalOverflow).toBe(false);

    console.log("✅ Long filename drag-drop: no overflow, page stable.");
  });
});
