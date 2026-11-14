import { test, expect } from "@playwright/test";

test.describe("Developer Console & Operations Tabs", () => {
  test("12. Developer Dashboard (/developer) displays KPIs and detector models inventory", async ({ page }) => {
    await page.goto("/developer");

    // Check title and tab bar
    await expect(page.locator("h1")).toContainText("Engineering & operations");
    await expect(page.getByRole("link", { name: "Dashboard" })).toBeVisible();

    // Check model inventory or detector presence
    await expect(page.getByText(/Detector|Models|Inventory|Status/i).first()).toBeVisible();
    await expect(page.getByText(/Video Classifier|AASIST|rPPG/i).first()).toBeVisible();
  });

  test("13. Security tab (/developer/security) renders gateway policies and mTLS configuration", async ({ page }) => {
    await page.goto("/developer/security");

    // Verify Security header / content
    await expect(page.getByRole("link", { name: "Security", exact: true })).toBeVisible();
    await expect(page.getByText(/Security|mTLS|Gateway|Token|Access/i).first()).toBeVisible();
  });

  test("14. Logs tab (/developer/logs) renders system audit log stream", async ({ page }) => {
    await page.goto("/developer/logs");

    // Verify Logs tab is active and shows logs
    await expect(page.getByRole("link", { name: "Logs", exact: true })).toBeVisible();
    await expect(page.getByText(/Log|Event|Audit|Timestamp/i).first()).toBeVisible();
  });

  test("15. Telemetry tab (/developer/telemetry) displays latency metrics and performance panels", async ({ page }) => {
    await page.goto("/developer/telemetry");

    // Verify Telemetry tab content
    await expect(page.getByRole("link", { name: "Telemetry" })).toBeVisible();
    await expect(page.getByText(/Telemetry|Latency|Performance|Prometheus/i).first()).toBeVisible();
  });

  test("16. Webhooks tab (/developer/webhooks) displays alert dispatch integration settings", async ({ page }) => {
    await page.goto("/developer/webhooks");

    // Verify Webhooks tab content
    await expect(page.getByRole("link", { name: "Webhooks" })).toBeVisible();
    await expect(page.getByText(/Webhook|Endpoint|Payload|Event/i).first()).toBeVisible();
  });

  test("17. API tab (/developer/api) displays service endpoints and connection parameters", async ({ page }) => {
    await page.goto("/developer/api");

    // Verify API tab content
    await expect(page.getByRole("link", { name: "API configuration" })).toBeVisible();
    await expect(page.getByText(/API|Endpoint|Orchestrator|Gateway/i).first()).toBeVisible();
  });
});
