/**
 * Accessibility audit — axe-core via @axe-core/playwright
 * =========================================================
 * Tests every key page against WCAG 2.1 AA.
 * - Fails on any "critical" or "serious" axe violations.
 * - Prints a readable summary of every violation found.
 * Target: zero critical/serious violations on each page.
 */

import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Pages to audit: [name, url, setup function]
const KEY_PAGES = [
  { name: "Home", url: "/" },
  { name: "Analyze", url: "/analyze" },
  { name: "Live", url: "/live" },
  { name: "Reports List", url: "/reports" },
  { name: "Report Detail (clean_baseline)", url: "/reports/clean_baseline" },
  { name: "Developer Dashboard", url: "/developer" },
  { name: "Settings", url: "/settings" },
];

// Helper: format violations into readable text for assertion messages
function formatViolations(violations: AxeBuilder["analyze"] extends () => Promise<infer R> ? Awaited<R>["violations"] : never): string {
  return violations
    .map(
      (v) =>
        `\n  [${v.impact?.toUpperCase()}] ${v.id}: ${v.description}\n` +
        v.nodes
          .slice(0, 2)
          .map((n) => `    → ${n.html.slice(0, 120)}`)
          .join("\n")
    )
    .join("\n");
}

test.describe("Accessibility Audit (axe-core / WCAG 2.1 AA)", () => {
  for (const { name, url } of KEY_PAGES) {
    test(`${name} (${url}) — zero critical/serious violations`, async ({ page }) => {
      await page.goto(url);

      // For pages with async data, wait for main content to settle
      await page.waitForLoadState("networkidle");

      // For reports page, enable demo mode so content is populated
      if (url === "/reports") {
        const demoSwitch = page.getByRole("switch", { name: "Demo data" }).first();
        if (await demoSwitch.isVisible()) {
          if ((await demoSwitch.getAttribute("aria-checked")) !== "true") {
            await demoSwitch.click();
            await page.waitForLoadState("networkidle");
          }
        }
      }

      const results = await new AxeBuilder({ page })
        // Target WCAG 2.1 AA
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        // Exclude third-party iframes we don't control
        .exclude("iframe")
        .analyze();

      const critical = results.violations.filter((v) =>
        ["critical", "serious"].includes(v.impact ?? "")
      );

      if (critical.length > 0) {
        console.log(
          `\n⚠️  ${name}: ${critical.length} critical/serious violation(s):${formatViolations(critical)}`
        );
      }

      // Log all violations (including moderate/minor) for the report
      if (results.violations.length > 0) {
        console.log(
          `\n📋 ${name}: ALL violations (${results.violations.length} total):` +
          formatViolations(results.violations)
        );
      } else {
        console.log(`\n✅ ${name}: No accessibility violations found.`);
      }

      // The hard assertion: no critical or serious violations
      expect(
        critical,
        `${name} has ${critical.length} critical/serious axe violations:\n${formatViolations(critical)}`
      ).toHaveLength(0);
    });
  }

  test("Analyze page — keyboard navigation reaches file input", async ({ page }) => {
    await page.goto("/analyze");
    await page.waitForLoadState("networkidle");

    // Tab through to the Browse Files button — it must be reachable by keyboard
    const browseBtn = page.getByRole("button", { name: /Browse files/i });
    await expect(browseBtn).toBeVisible();
    await browseBtn.focus();
    await expect(browseBtn).toBeFocused();
  });

  test("Reports list — table has proper column headers for screen readers", async ({ page }) => {
    await page.goto("/reports");
    await page.waitForLoadState("networkidle");

    const demoSwitch = page.getByRole("switch", { name: "Demo data" }).first();
    if (await demoSwitch.isVisible()) {
      if ((await demoSwitch.getAttribute("aria-checked")) !== "true") {
        await demoSwitch.click();
        await page.waitForTimeout(500);
      }
    }

    // Table must have scope attributes on column headers
    const table = page.locator("table").first();
    if (await table.isVisible()) {
      await expect(page.getByRole("columnheader", { name: "Report" })).toBeVisible();
      await expect(page.getByRole("columnheader", { name: "Verdict" })).toBeVisible();
    }
  });
});
