import { describe, it, expect } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import DetectorResultCard from "../DetectorResultCard";

describe("DetectorResultCard (W6a)", () => {
  it("renders skeleton card when isLoading is true", () => {
    render(<DetectorResultCard result={null} isLoading={true} />);
    const skel = screen.getByLabelText("Loading detector result");
    expect(skel).toHaveAttribute("aria-busy", "true");
  });

  it("renders empty placeholder when result is null and isLoading is false", () => {
    render(<DetectorResultCard result={null} isLoading={false} />);
    expect(screen.getByLabelText("No result available")).toBeInTheDocument();
    expect(screen.getByText(/Run analysis to see detector evidence/i)).toBeInTheDocument();
  });

  it("renders Manipulated, Authentic, and Inconclusive cards with evidence and latency", () => {
    const cases = [
      {
        label: "Manipulated",
        result: {
          verdict: "manipulated",
          confidence: 89,
          evidenceText: "Vocoder frequency discontinuities detected.",
          latencyMs: 512,
          detectorName: "AASIST v2",
          timestamp: "2026-09-15T16:46:30.000Z",
        },
      },
      {
        label: "Authentic",
        result: {
          verdict: "authentic",
          confidence: 92,
          evidenceText: "Facial landmark coherence within normal bounds.",
          latencyMs: 310,
          detectorName: "VideoDetector v1",
          timestamp: "2026-09-15T16:45:00.000Z",
        },
      },
      {
        label: "Inconclusive",
        result: {
          verdict: "inconclusive",
          confidence: 51,
          evidenceText: "Heavy motion blur limits pulse extraction.",
          latencyMs: 1120,
          detectorName: "rPPG Analyzer",
          timestamp: "2026-09-15T16:48:00.000Z",
        },
      },
    ];

    for (const tc of cases) {
      cleanup();
      render(<DetectorResultCard result={tc.result} />);
      expect(screen.getByText(tc.result.detectorName)).toBeInTheDocument();
      expect(screen.getByText(tc.label)).toBeInTheDocument();
      expect(screen.getByText(tc.result.evidenceText)).toBeInTheDocument();
      expect(screen.getByText(new RegExp(`${tc.result.latencyMs.toLocaleString()}\\s*ms`))).toBeInTheDocument();
    }
  });
});
