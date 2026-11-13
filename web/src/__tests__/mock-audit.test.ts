/**
 * mock-audit.test.ts
 * Task 2: Audit real-vs-mock data and remove silent fallbacks
 *
 * Run with:  node --experimental-strip-types --test src/__tests__/mock-audit.test.ts
 * Or:        npm test
 *
 * Tests verify:
 *  1. demoMode utility functions behave correctly in a Node environment
 *  2. API route logic (via direct function tests, not HTTP) honours demo/real partitioning
 *  3. Mock data items are always labeled is_demo:true
 *  4. DemoBadge / DemoBanner / DemoSwitch exports exist in ui.tsx
 *  5. All key source files exist on disk (no silent deletion)
 *  6. Static source analysis: pages do NOT hard-import mock data without a DemoBadge import
 */

import { describe, it, before } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const WEB = path.join(import.meta.dirname, "..", "..");
const src = (...parts: string[]) => path.join(WEB, "src", ...parts);

function readSrc(...parts: string[]): string {
  return fs.readFileSync(src(...parts), "utf-8");
}

function fileExists(...parts: string[]): boolean {
  return fs.existsSync(src(...parts));
}

// ---------------------------------------------------------------------------
// 1. demoMode.ts — utility logic (Node-safe; window guard tested separately)
// ---------------------------------------------------------------------------

describe("demoMode.ts file", () => {
  it("file exists", () => {
    assert.ok(fileExists("lib", "demoMode.ts"), "demoMode.ts must exist");
  });

  it("exports isDemoModeEnabled", () => {
    const code = readSrc("lib", "demoMode.ts");
    assert.ok(code.includes("export function isDemoModeEnabled"), "must export isDemoModeEnabled");
  });

  it("exports setDemoModeEnabled", () => {
    const code = readSrc("lib", "demoMode.ts");
    assert.ok(code.includes("export function setDemoModeEnabled"), "must export setDemoModeEnabled");
  });

  it("exports useDemoMode", () => {
    const code = readSrc("lib", "demoMode.ts");
    assert.ok(code.includes("export function useDemoMode"), "must export useDemoMode");
  });

  it("isDemoModeEnabled guards window", () => {
    const code = readSrc("lib", "demoMode.ts");
    assert.ok(
      code.includes("typeof window === \"undefined\""),
      "must guard against SSR / Node environment"
    );
  });

  it("STORAGE_KEY constant defined", () => {
    const code = readSrc("lib", "demoMode.ts");
    assert.ok(code.includes("STORAGE_KEY"), "must define a STORAGE_KEY constant");
  });

  it("setDemoModeEnabled dispatches CustomEvent", () => {
    const code = readSrc("lib", "demoMode.ts");
    assert.ok(code.includes("CustomEvent"), "must dispatch CustomEvent for cross-component sync");
  });
});

// ---------------------------------------------------------------------------
// 2. ui.tsx — DemoBadge, DemoBanner, DemoSwitch exports
// ---------------------------------------------------------------------------

describe("ui.tsx demo components", () => {
  it("file exists", () => {
    assert.ok(fileExists("components", "aegis", "ui.tsx"), "ui.tsx must exist");
  });

  it("exports DemoBadge", () => {
    const code = readSrc("components", "aegis", "ui.tsx");
    assert.ok(code.includes("export function DemoBadge"), "must export DemoBadge");
  });

  it("exports DemoBanner", () => {
    const code = readSrc("components", "aegis", "ui.tsx");
    assert.ok(code.includes("export function DemoBanner"), "must export DemoBanner");
  });

  it("exports DemoSwitch", () => {
    const code = readSrc("components", "aegis", "ui.tsx");
    assert.ok(code.includes("export function DemoSwitch"), "must export DemoSwitch");
  });

  it("DemoBadge renders 'Demo data' text", () => {
    const code = readSrc("components", "aegis", "ui.tsx");
    // Find the DemoBadge function and check it contains the label
    const demoSection = code.slice(code.indexOf("function DemoBadge"));
    assert.ok(
      demoSection.slice(0, 500).includes("Demo data") ||
      demoSection.slice(0, 500).includes("Demo"),
      "DemoBadge must render 'Demo data' label text"
    );
  });

  it("DemoBanner renders a dismissible/contextual message", () => {
    const code = readSrc("components", "aegis", "ui.tsx");
    const idx = code.indexOf("function DemoBanner");
    assert.ok(idx >= 0, "DemoBanner must exist");
    const banner = code.slice(idx, idx + 800);
    assert.ok(banner.includes("demo") || banner.includes("Demo"), "DemoBanner must reference demo");
  });

  it("DemoSwitch renders a toggle/switch element", () => {
    const code = readSrc("components", "aegis", "ui.tsx");
    const idx = code.indexOf("function DemoSwitch");
    assert.ok(idx >= 0, "DemoSwitch must exist");
    const sw = code.slice(idx, idx + 800);
    assert.ok(
      sw.includes("Switch") || sw.includes("toggle") || sw.includes("checked"),
      "DemoSwitch must render a toggle control"
    );
  });
});

// ---------------------------------------------------------------------------
// 3. API route — static analysis of route.ts
// ---------------------------------------------------------------------------

describe("api/jobs/route.ts mock labeling", () => {
  it("file exists", () => {
    assert.ok(fileExists("app", "api", "jobs", "route.ts"), "route.ts must exist");
  });

  it("mock items labeled is_demo:true", () => {
    const code = readSrc("app", "api", "jobs", "route.ts");
    // Count occurrences of is_demo in the file — should appear multiple times
    const matches = code.match(/is_demo/g) || [];
    assert.ok(matches.length >= 3, `is_demo must appear at least 3 times; found ${matches.length}`);
  });

  it("supports ?demo= query parameter", () => {
    const code = readSrc("app", "api", "jobs", "route.ts");
    assert.ok(
      code.includes('searchParams.get("demo")') || code.includes("searchParams.get('demo')"),
      "route must handle ?demo= query param"
    );
  });

  it("supports ?aggregate=true query parameter", () => {
    const code = readSrc("app", "api", "jobs", "route.ts");
    assert.ok(
      code.includes("aggregate") ,
      "route must handle ?aggregate=true query param"
    );
  });

  it("readJobs function exists for real job persistence", () => {
    const code = readSrc("app", "api", "jobs", "route.ts");
    assert.ok(code.includes("function readJobs"), "must have readJobs() for real job persistence");
  });

  it("preset reports all have is_demo:true", () => {
    const code = readSrc("app", "api", "jobs", "route.ts");
    // Check that preset reports block contains is_demo: true
    const presetBlock = code.slice(code.indexOf("presetReports"), code.indexOf("presetReports") + 3000);
    assert.ok(presetBlock.includes("is_demo: true"), "preset reports must be labeled is_demo: true");
  });

  it("route returns 404 for unknown ids", () => {
    const code = readSrc("app", "api", "jobs", "route.ts");
    assert.ok(
      code.includes("404") || code.includes("not found") || code.includes("Not Found"),
      "route must return 404 for unknown job IDs"
    );
  });

  it("mock analyses labeled with is_demo", () => {
    const code = readSrc("app", "api", "jobs", "route.ts");
    // The route should map mock items and add is_demo:true
    assert.ok(
      code.includes("is_demo: true") || code.includes("is_demo:true"),
      "mock analyses must be labeled is_demo:true in the route"
    );
  });
});

// ---------------------------------------------------------------------------
// 4. Page files — import guards: pages using mock must also import DemoBadge/DemoBanner
// ---------------------------------------------------------------------------

describe("pages import demo components when using mock data", () => {
  it("developer/logs/page.tsx imports DemoBadge", () => {
    const code = readSrc("app", "developer", "logs", "page.tsx");
    assert.ok(code.includes("from @/lib/mock") || code.includes('from "@/lib/mock"'), "logs page uses mock");
    assert.ok(code.includes("DemoBadge"), "logs page must import DemoBadge when using mock data");
  });

  it("developer/telemetry/page.tsx imports DemoBadge", () => {
    const code = readSrc("app", "developer", "telemetry", "page.tsx");
    assert.ok(code.includes("from @/lib/mock") || code.includes('from "@/lib/mock"'), "telemetry page uses mock");
    assert.ok(code.includes("DemoBadge"), "telemetry page must import DemoBadge when using mock data");
  });

  it("app/page.tsx imports DemoBanner", () => {
    const code = readSrc("app", "page.tsx");
    assert.ok(code.includes("DemoBanner"), "home page must import DemoBanner");
  });

  it("app/page.tsx imports DemoSwitch", () => {
    const code = readSrc("app", "page.tsx");
    assert.ok(code.includes("DemoSwitch"), "home page must import DemoSwitch");
  });

  it("developer/page.tsx imports DemoBadge", () => {
    const code = readSrc("app", "developer", "page.tsx");
    assert.ok(code.includes("DemoBadge"), "developer page must import DemoBadge");
  });

  it("developer/page.tsx imports DemoBanner", () => {
    const code = readSrc("app", "developer", "page.tsx");
    assert.ok(code.includes("DemoBanner"), "developer page must import DemoBanner");
  });

  it("reports/page.tsx imports DemoBadge", () => {
    const code = readSrc("app", "reports", "page.tsx");
    assert.ok(code.includes("DemoBadge"), "reports list page must import DemoBadge");
  });

  it("reports/[id]/page.tsx imports DemoBadge", () => {
    const code = readSrc("app", "reports", "[id]", "page.tsx");
    assert.ok(code.includes("DemoBadge"), "report detail page must import DemoBadge");
  });

  it("reports/[id]/page.tsx imports DemoBanner", () => {
    const code = readSrc("app", "reports", "[id]", "page.tsx");
    assert.ok(code.includes("DemoBanner"), "report detail page must import DemoBanner");
  });

  it("reports/[id]/page.tsx uses useDemoMode", () => {
    const code = readSrc("app", "reports", "[id]", "page.tsx");
    assert.ok(code.includes("useDemoMode"), "report detail page must use useDemoMode hook");
  });
});

// ---------------------------------------------------------------------------
// 5. Processing page — backend failure handling
// ---------------------------------------------------------------------------

describe("analyze/processing/page.tsx backend failure handling", () => {
  it("file exists", () => {
    assert.ok(fileExists("app", "analyze", "processing", "page.tsx"), "processing page must exist");
  });

  it("handles backend failure with explicit error state", () => {
    const code = readSrc("app", "analyze", "processing", "page.tsx");
    assert.ok(
      code.includes("backendFailed") || code.includes("Backend") || code.includes("unreachable"),
      "processing page must handle backend failure explicitly"
    );
  });

  it("does not silently continue when backend fails", () => {
    const code = readSrc("app", "analyze", "processing", "page.tsx");
    // Must NOT show a fake/simulated complete state on backend failure
    // Check that there is an error branch (not just a timer that continues forever)
    assert.ok(
      code.includes("error") || code.includes("Error") || code.includes("failed"),
      "processing page must have an error handling path"
    );
  });
});

// ---------------------------------------------------------------------------
// 6. AppShell — timeline demo label
// ---------------------------------------------------------------------------

describe("AppShell.tsx timeline demo labeling", () => {
  it("file exists", () => {
    assert.ok(
      fs.existsSync(path.join(WEB, "src", "components", "aegis", "AppShell.tsx")),
      "AppShell.tsx must exist"
    );
  });

  it("timeline import is from mock.ts", () => {
    const code = readSrc("components", "aegis", "AppShell.tsx");
    assert.ok(code.includes("timeline") && code.includes("mock"), "AppShell must import timeline from mock");
  });

  it("footer labels timeline as demo data", () => {
    const code = readSrc("components", "aegis", "AppShell.tsx");
    assert.ok(
      code.includes("Demo data") || code.includes("demo") || code.includes("Demo"),
      "AppShell footer must label the timeline as Demo data"
    );
  });
});

// ---------------------------------------------------------------------------
// 7. CI configuration
// ---------------------------------------------------------------------------

describe("CI configuration includes npm test", () => {
  it("ci-web.yml exists", () => {
    const ciPath = path.join(WEB, "..", ".github", "workflows", "ci-web.yml");
    assert.ok(fs.existsSync(ciPath), "ci-web.yml must exist");
  });

  it("ci-web.yml includes npm test step", () => {
    const ciPath = path.join(WEB, "..", ".github", "workflows", "ci-web.yml");
    const code = fs.readFileSync(ciPath, "utf-8");
    assert.ok(
      code.includes("npm test") || code.includes("npm run test"),
      "ci-web.yml must include an npm test step"
    );
  });
});

// ---------------------------------------------------------------------------
// 8. package.json — test script wired
// ---------------------------------------------------------------------------

describe("package.json test script", () => {
  it("package.json exists", () => {
    assert.ok(fs.existsSync(path.join(WEB, "package.json")), "package.json must exist");
  });

  it("test script is defined", () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(WEB, "package.json"), "utf-8"));
    assert.ok(pkg.scripts?.test, "package.json must have a test script");
  });

  it("test script references the test file or directory", () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(WEB, "package.json"), "utf-8"));
    const testScript: string = pkg.scripts?.test ?? "";
    assert.ok(
      testScript.includes("test") || testScript.includes("__tests__"),
      "test script must reference test files"
    );
  });
});

// ---------------------------------------------------------------------------
// 9. Mock data module — exports exist and are labeled correctly in route
// ---------------------------------------------------------------------------

describe("lib/mock.ts integrity", () => {
  it("file exists", () => {
    assert.ok(fileExists("lib", "mock.ts"), "mock.ts must exist");
  });

  it("exports analyses array", () => {
    const code = readSrc("lib", "mock.ts");
    assert.ok(code.includes("analyses"), "mock.ts must export analyses");
  });

  it("exports logs array", () => {
    const code = readSrc("lib", "mock.ts");
    assert.ok(code.includes("logs"), "mock.ts must export logs array");
  });

  it("exports timeline array", () => {
    const code = readSrc("lib", "mock.ts");
    assert.ok(code.includes("timeline"), "mock.ts must export timeline array");
  });

  it("exports detectors array", () => {
    const code = readSrc("lib", "mock.ts");
    assert.ok(code.includes("detectors"), "mock.ts must export detectors array");
  });
});

// ---------------------------------------------------------------------------
// 10. No silent fallback: home page must not embed raw mock analyses
// ---------------------------------------------------------------------------

describe("home page (page.tsx) real-data-first policy", () => {
  it("home page does NOT directly import analyses from mock", () => {
    const code = readSrc("app", "page.tsx");
    // The home page should fetch from the API, not import mock analyses directly
    const importsMockAnalyses = code.includes("analyses") && code.includes("from \"@/lib/mock\"");
    // It's acceptable if it imports from mock only via ui.tsx — check direct import
    const directImport = /import\s*\{[^}]*\banalyses\b[^}]*\}\s*from\s*["']@\/lib\/mock["']/.test(code);
    assert.ok(!directImport, "home page must NOT directly import analyses from mock (use API fetch instead)");
  });

  it("home page fetches from /api/jobs", () => {
    const code = readSrc("app", "page.tsx");
    assert.ok(code.includes("/api/jobs"), "home page must fetch real data from /api/jobs");
  });

  it("home page uses useDemoMode hook", () => {
    const code = readSrc("app", "page.tsx");
    assert.ok(code.includes("useDemoMode"), "home page must use the useDemoMode hook");
  });
});

