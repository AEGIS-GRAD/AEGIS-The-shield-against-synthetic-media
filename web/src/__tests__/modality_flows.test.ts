/**
 * modality_flows.test.ts
 * Task 1: Enable the Image and Text tabs and test their flows.
 *
 * Run with: npm test
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.join(import.meta.dirname, "..", "..");
const src = (...parts: string[]) => path.join(WEB, "src", ...parts);

function readSrc(...parts: string[]): string {
  return fs.readFileSync(src(...parts), "utf-8");
}

function fileExists(...parts: string[]): boolean {
  return fs.existsSync(src(...parts));
}

describe("Task 1: Image and Text Modality UI & Flows", () => {
  it("FrequencySpectrumView component exists and exports correctly", () => {
    assert.ok(
      fileExists("components", "aegis", "FrequencySpectrumView.tsx"),
      "FrequencySpectrumView.tsx must exist"
    );
    const code = readSrc("components", "aegis", "FrequencySpectrumView.tsx");
    assert.ok(
      code.includes("export function FrequencySpectrumView"),
      "Must export FrequencySpectrumView"
    );
    assert.ok(
      code.includes("frequency_anomaly") && code.includes("exif_missing"),
      "Must display frequency_anomaly and exif_missing signals"
    );
  });

  it("PerSentenceHighlightView component exists and exports correctly", () => {
    assert.ok(
      fileExists("components", "aegis", "PerSentenceHighlightView.tsx"),
      "PerSentenceHighlightView.tsx must exist"
    );
    const code = readSrc("components", "aegis", "PerSentenceHighlightView.tsx");
    assert.ok(
      code.includes("export function PerSentenceHighlightView"),
      "Must export PerSentenceHighlightView"
    );
    assert.ok(
      code.includes("low_sentence_length_variation") && code.includes("low_vocabulary_diversity"),
      "Must display stylometric variation and lexical diversity signals"
    );
  });

  it("UploadPage enables Image and Text tabs and removes ComingSoon barriers", () => {
    const code = readSrc("app", "analyze", "page.tsx");
    assert.ok(
      code.includes("FrequencySpectrumView") && code.includes("PerSentenceHighlightView"),
      "Analyze page must import and render frequency and per-sentence components"
    );
    assert.ok(
      !code.includes("Planned"),
      "Hardcoded 'Planned' disabled tab badge should be removed"
    );
    assert.ok(
      code.includes("Load AI Essay") && code.includes("Load Human Text"),
      "Must provide quick-load sample actions for text analysis"
    );
  });

  it("Mock detectors catalog registers Community Forensics and Desklib models", () => {
    const code = readSrc("lib", "mock.ts");
    assert.ok(
      code.includes("Community Forensics"),
      "Image detector model must be Community Forensics"
    );
    assert.ok(
      code.includes("Desklib DeBERTa-v3"),
      "Text detector model must be Desklib DeBERTa-v3"
    );
  });

  it("Processing page orchestrator plan includes image and text execution", () => {
    const code = readSrc("app", "analyze", "processing", "page.tsx");
    assert.ok(
      !code.includes("Model not built yet"),
      "Processing plan must no longer mark image or text as 'Model not built yet'"
    );
  });
});
