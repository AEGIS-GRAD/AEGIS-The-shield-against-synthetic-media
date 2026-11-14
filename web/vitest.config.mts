import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    tsconfigPaths: true,
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    environmentOptions: {
      jsdom: {
        url: "http://localhost:3000",
      },
    },
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx,js,jsx}"],
    exclude: ["node_modules", ".next", "coverage", "test-results"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcovonly"],
      include: [
        "src/components/report/**/*.{ts,tsx}",
        "src/components/DetectorResultCard.jsx",
        "src/components/DetectorResultsGrid.jsx",
        "src/components/UploadPage.jsx",
        "src/hooks/**/*.{ts,tsx}",
        "src/lib/report.ts",
      ],
      thresholds: {
        "src/components/report/**": {
          lines: 80,
          functions: 80,
          statements: 80,
        },
        "src/hooks/useJobPolling.ts": {
          lines: 80,
          functions: 80,
          statements: 80,
        },
        "src/lib/report.ts": {
          lines: 80,
          functions: 80,
          statements: 80,
        },
      },
    },
  },
});

