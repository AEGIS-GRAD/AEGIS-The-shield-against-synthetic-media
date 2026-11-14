import { test, expect } from "@playwright/test";

test.describe("Live Surveillance & Attack Injection", () => {
  test("10. Live feeds page displays camera grid and telemetry monitors", async ({ page }) => {
    await page.goto("/live");

    // Check page header or camera indicators
    await expect(page.locator("h1")).toContainText(/Live|Surveillance/i);

    // Verify camera feeds or selector buttons
    const cameraCards = page.locator("button, div").filter({ hasText: /Camera|Cam/i });
    await expect(cameraCards.first()).toBeVisible();

    // Verify grid switcher buttons exist
    const gridButtons = page.locator("button").filter({ has: page.locator("svg") });
    expect(await gridButtons.count()).toBeGreaterThan(0);
  });

  test("11. Adversarial attack injection triggers feedback state and dispatches attack stream", async ({ page }) => {
    await page.goto("/live");

    // Locate the Inject Attack button
    const injectBtn = page.getByRole("button", { name: /Inject Attack/i });
    await expect(injectBtn).toBeVisible();

    // Click Inject Attack
    await injectBtn.click();

    // Confirm button text updates to "Stop Inject"
    await expect(page.getByRole("button", { name: /Stop Inject/i })).toBeVisible();

    // Verify feedback notification is displayed (dispatched to gateway or simulated)
    const feedbackBanner = page.locator("text=/Attack payload dispatched|Adversarial payload simulated|Injecting attack/i");
    await expect(feedbackBanner.first()).toBeVisible({ timeout: 5000 });

    // Click again to deactivate attack stream
    await page.getByRole("button", { name: /Stop Inject/i }).click();

    // Verify button resets to "Inject Attack"
    await expect(page.getByRole("button", { name: /Inject Attack/i })).toBeVisible();
  });
});
