/**
 * modality_flows.test.ts
 * Task 1: Enable the Image and Text tabs and test their flows.
 *
 * Run with: npm test
 */

import { describe, it, expect } from "vitest";
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
    expect(
      fileExists("components", "aegis", "FrequencySpectrumView.tsx"),
      "FrequencySpectrumView.tsx must exist"
    ).toBe(true);
    const code = readSrc("components", "aegis", "FrequencySpectrumView.tsx");
    expect(
      code.includes("export function FrequencySpectrumView"),
      "Must export FrequencySpectrumView"
    ).toBe(true);
    expect(
      code.includes("frequency_anomaly") && code.includes("exif_missing"),
      "Must display frequency_anomaly and exif_missing signals"
    ).toBe(true);
  });

  it("PerSentenceHighlightView component exists and exports correctly", () => {
    expect(
      fileExists("components", "aegis", "PerSentenceHighlightView.tsx"),
      "PerSentenceHighlightView.tsx must exist"
    ).toBe(true);
    const code = readSrc("components", "aegis", "PerSentenceHighlightView.tsx");
    expect(
      code.includes("export function PerSentenceHighlightView"),
      "Must export PerSentenceHighlightView"
    ).toBe(true);
    expect(
      code.includes("low_sentence_length_variation") && code.includes("low_vocabulary_diversity"),
      "Must display stylometric variation and lexical diversity signals"
    ).toBe(true);
  });

  it("UploadPage enables Image and Text tabs and removes ComingSoon barriers", () => {
    const code = readSrc("app", "analyze", "page.tsx");
    expect(
      code.includes("FrequencySpectrumView") && code.includes("PerSentenceHighlightView"),
      "Analyze page must import and render frequency and per-sentence components"
    ).toBe(true);
    expect(
      !code.includes("Planned"),
      "Hardcoded 'Planned' disabled tab badge should be removed"
    ).toBe(true);
    expect(
      code.includes("Load AI Essay") && code.includes("Load Human Text"),
      "Must provide quick-load sample actions for text analysis"
    ).toBe(true);
  });

  it("Mock detectors catalog registers Community Forensics and Desklib models", () => {
    const code = readSrc("lib", "mock.ts");
    expect(
      code.includes("Community Forensics"),
      "Image detector model must be Community Forensics"
    ).toBe(true);
    expect(
      code.includes("Desklib DeBERTa-v3"),
      "Text detector model must be Desklib DeBERTa-v3"
    ).toBe(true);
  });

  it("Processing page orchestrator plan includes image and text execution", () => {
    const code = readSrc("app", "analyze", "processing", "page.tsx");
    expect(
      !code.includes("Model not built yet"),
      "Processing plan must no longer mark image or text as 'Model not built yet'"
    ).toBe(true);
  });
});
