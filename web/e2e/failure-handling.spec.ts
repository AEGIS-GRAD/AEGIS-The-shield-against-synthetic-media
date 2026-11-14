import { test, expect } from "@playwright/test";
import path from "path";

test.describe("Failure Cases & Honest Error Handling (No Silent Demo Fallbacks)", () => {
  const FIXTURES_DIR = path.join(__dirname, "fixtures");

  test("18. Stopped backend on /reports renders honest offline error alert rather than fabricating demo reports", async ({ page }) => {
    // Disable demo mode in storage
    await page.addInitScript(() => {
      localStorage.setItem("aegis_demo_mode", "false");
    });

    // Simulate backend being completely down
    await page.route("**/api/jobs*", async (route) => {
      await route.abort("connectionrefused");
    });

    await page.goto("/reports");

    // Must display honest error alert banner
    const alertBanner = page.locator('[role="alert"]').filter({ hasText: /Backend service unreachable|Backend offline/i });
    await expect(alertBanner.first()).toBeVisible({ timeout: 7000 });

    // Confirm UI shows honest "Backend offline" empty state
    await expect(page.getByText(/Backend offline|The reporting service is not responding/i).first()).toBeVisible();

    // Confirm it does NOT silently fabricate mock analyses
    const rows = page.locator("tbody tr");
    expect(await rows.count()).toBe(0);
  });

  test("19. Stopped inference detector on /analyze/processing displays honest failure banner instead of fake progress", async ({ page }) => {
    // Simulate inference detector failure
    await page.route("**/analyze_video", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: "Detector service unavailable: detector_video_classifier connection refused" }),
      });
    });

    await page.goto("/analyze");

    // Upload video
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse files" }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(FIXTURES_DIR, "sample-video.mp4"));

    // Run analysis
    await page.getByRole("button", { name: "Run analysis" }).click();

    // Verify error page appears honestly
    await expect(page).toHaveURL(/\/analyze\/processing/);
    await expect(page.locator("h1")).toContainText(/Analysis Failed/i);
    await expect(page.getByRole("heading", { name: "Backend Inference Unreachable" })).toBeVisible();
    await expect(page.getByText(/Inference service returned HTTP 503/i)).toBeVisible();
    await expect(page.getByText(/A backend failure can never pass as a real analysis result/i)).toBeVisible();
  });

  test("20. Non-existent job ID renders explicit 404 rather than silent mock data", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("aegis_demo_mode", "false");
    });

    // Mock 404 for unknown job
    await page.route("**/api/jobs?id=NON_EXISTENT_JOB_999", async (route) => {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ error: "Job not found", is_demo: false }),
      });
    });

    await page.goto("/reports/NON_EXISTENT_JOB_999");

    // Verify honest error state
    await expect(page.getByRole("heading", { name: "Report Not Found" })).toBeVisible({ timeout: 7000 });
    await expect(page.getByText(/does not exist in local storage, or the backend service is offline/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Enable Demo Data" })).toBeVisible();
  });
});
