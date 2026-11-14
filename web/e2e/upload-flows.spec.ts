import { test, expect } from "@playwright/test";
import path from "path";

test.describe("Offline Analysis & Upload Flows", () => {
  const FIXTURES_DIR = path.join(__dirname, "fixtures");

  test("1. Video upload progresses through analysis pipeline to completed report", async ({ page }) => {
    // Intercept inference endpoint with deterministic response
    await page.route("**/analyze_video", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "JOB-VID-001",
          file: "sample-video.mp4",
          verdict: "synthetic",
          confidence: 0.92,
          status: "complete",
        }),
      });
    });

    // Intercept polling endpoint for this job
    await page.route("**/api/jobs*id=JOB-VID-001*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "JOB-VID-001",
          file: "sample-video.mp4",
          status: "complete",
          verdict: "synthetic",
          confidence: 0.92,
          is_demo: false,
          debate_transcript: [],
        }),
      });
    });

    await page.goto("/analyze");
    await expect(page.locator("h1")).toContainText("Offline Analysis");

    // Upload video file
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse files" }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(FIXTURES_DIR, "sample-video.mp4"));

    // Verify file card is rendered
    await expect(page.getByText("sample-video.mp4")).toBeVisible();
    await expect(page.getByRole("button", { name: "Run analysis" })).toBeEnabled();

    // Trigger analysis
    await page.getByRole("button", { name: "Run analysis" }).click();

    // Verify transition to processing page
    await expect(page).toHaveURL(/\/analyze\/processing/);

    // Click "View report" once inference finishes
    const viewReportBtn = page.getByRole("link", { name: /View report/i });
    await expect(viewReportBtn).toBeVisible({ timeout: 10000 });
    await viewReportBtn.click();

    // Confirm navigation to report detail
    await expect(page).toHaveURL(/\/reports\/JOB-VID-001/);
  });

  test("2. Audio upload validates acoustic file and progresses to analysis", async ({ page }) => {
    await page.route("**/analyze_video", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "JOB-AUD-002",
          file: "sample-audio.wav",
          verdict: "synthetic",
          confidence: 0.89,
        }),
      });
    });

    await page.goto("/analyze");

    // Upload audio file
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Browse files" }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(FIXTURES_DIR, "sample-audio.wav"));

    // Verify audio file card is rendered
    await expect(page.getByText("sample-audio.wav")).toBeVisible();
    const runBtn = page.getByRole("button", { name: "Run analysis" });
    await expect(runBtn).toBeEnabled();
    await runBtn.click();

    await expect(page).toHaveURL(/\/analyze\/processing/);
  });

  test("3. Image tab navigation and coming-soon / model status verification", async ({ page }) => {
    await page.goto("/analyze");

    // Click Image tab
    const imageTab = page.locator("button").filter({ hasText: /^Image/ }).first();
    await imageTab.click();

    // Verify either ComingSoon banner or image dropzone
    const hasImageInfo = await page.locator("text=Image Deepfake Classifier").isVisible();
    const hasDropzone = await page.locator("text=Drag & drop").isVisible();
    expect(hasImageInfo || hasDropzone).toBeTruthy();
  });

  test("4. Text tab navigation and text detector status verification", async ({ page }) => {
    await page.goto("/analyze");

    // Click Text tab
    const textTab = page.locator("button").filter({ hasText: /^Text/ }).first();
    await textTab.click();

    // Verify either ComingSoon banner or text area
    const hasTextInfo = await page.locator("text=Text Perplexity Detector").isVisible();
    const hasTextarea = await page.locator("textarea").isVisible();
    expect(hasTextInfo || hasTextarea).toBeTruthy();
  });

  test("5. Milestone Demo Presets execute deterministic multi-agent debate to report", async ({ page }) => {
    await page.goto("/analyze");

    // Locate preset cards
    const cleanBaselinePreset = page.getByText("Clean Baseline").first();
    await expect(cleanBaselinePreset).toBeVisible();

    // Directly click Report link on Clean Baseline preset
    const presetCard = page.locator("div.group").filter({ hasText: "Clean Baseline" });
    const reportLink = presetCard.getByRole("link", { name: /Report/i });
    await reportLink.click();

    // Should load the report for clean_baseline
    await expect(page).toHaveURL("/reports/clean_baseline");
    await expect(page.locator("h1")).toContainText(/clean_interview_broadcast\.mp4|Clean Baseline/i);
    await expect(page.getByText(/AUTHENTIC/i).first()).toBeVisible();
    await expect(page.getByText("TIER_1_LOW").first()).toBeVisible();
  });
});
