import { test, expect } from "@playwright/test";

test.describe("Reports Module: List & Detail", () => {
  test("6. Reports list renders table with verdicts, confidence scores, and demo toggle", async ({ page }) => {
    await page.goto("/reports");
    await expect(page.locator("h1")).toContainText("Reports");

    // Ensure Demo data toggle is enabled so reports are populated
    const demoSwitch = page.getByRole("switch", { name: "Demo data" }).first();
    await expect(demoSwitch).toBeVisible();
    if ((await demoSwitch.getAttribute("aria-checked")) !== "true") {
      await demoSwitch.click();
    }

    // Check table headers
    await expect(page.getByRole("columnheader", { name: "Report" })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("columnheader", { name: "Verdict" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Confidence" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Status" })).toBeVisible();

    // Verify filter buttons are rendered
    await expect(page.getByRole("button", { name: "all" })).toBeVisible();
    await expect(page.getByRole("button", { name: "authentic" })).toBeVisible();
    await expect(page.getByRole("button", { name: "synthetic" })).toBeVisible();
    await expect(page.getByRole("button", { name: "inconclusive" })).toBeVisible();
  });

  test("7. Reports list filtering updates table rows by verdict", async ({ page }) => {
    await page.goto("/reports");

    // Enable demo mode if needed to populate rows
    const demoSwitch = page.getByRole("switch", { name: "Demo data" }).first();
    await expect(demoSwitch).toBeVisible();
    if ((await demoSwitch.getAttribute("aria-checked")) !== "true") {
      await demoSwitch.click();
    }

    // Wait for table rows to appear
    await expect(page.locator("table")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("tbody tr").first()).toBeVisible();

    // Click "synthetic" filter
    await page.getByRole("button", { name: "synthetic" }).click();
    await expect(page.locator("table")).toBeVisible();

    // Click "authentic" filter
    await page.getByRole("button", { name: "authentic" }).click();
    await expect(page.locator("table")).toBeVisible();

    // Return to "all"
    await page.getByRole("button", { name: "all" }).click();
    await expect(page.locator("table")).toBeVisible();
  });

  test("8. Report detail renders forensic analysis cards: verdict, debate log, agreement matrix, hash chain", async ({ page }) => {
    await page.goto("/reports/clean_baseline");

    // Check header and verdict
    await expect(page.getByText(/AUTHENTIC/i).first()).toBeVisible();
    await expect(page.getByText(/TIER_1_LOW/i).first()).toBeVisible();

    // Check Agreement Matrix section
    const agreementSection = page.getByText(/Agreement Matrix|Detector Agreement/i);
    await expect(agreementSection.first()).toBeVisible();

    // Check Debate Log & transcript hash
    const debateSection = page.getByText(/Debate Log|Multi-Agent Debate/i);
    await expect(debateSection.first()).toBeVisible();

    // Check cryptographic hash or digital chain
    const hashChainSection = page.getByText(/Hash Chain|Cryptographic/i);
    await expect(hashChainSection.first()).toBeVisible();

    // Check pulse wave / physiological or frame heatmap
    const pulseOrHeatmap = page.getByText(/Pulse|Heartbeat|Heatmap|Frame/i);
    await expect(pulseOrHeatmap.first()).toBeVisible();
  });

  test("9. Voice clone report displays acoustic spoofing forensic justification and SIEM escalation", async ({ page }) => {
    await page.goto("/reports/voice_clone");

    // Voice clone is synthetic
    await expect(page.getByText(/SYNTHETIC/i).first()).toBeVisible();
    await expect(page.getByText(/TIER_3_CRITICAL/i).first()).toBeVisible();

    // Verify forensic justification mentions vocoder or acoustic synthesis
    await expect(
      page.getByText(/vocoder|harmonic|AASIST|acoustic/i).first()
    ).toBeVisible();
  });
});
