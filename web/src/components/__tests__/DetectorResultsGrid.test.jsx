import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import DetectorResultsGrid from "../DetectorResultsGrid";
import { verdictFromConfidence } from "@/lib/report";

describe("DetectorResultsGrid (W6b)", () => {
  const baseResponses = {
    video_classifier: {
      confidence: 0.91,
      latency_ms: 1420,
      ram_usage_mb: 610,
      evidence: { claim: "Jaw blending artifacts", flags: ["jaw_blending"] },
    },
    rppg: {
      confidence: 0.5,
      latency_ms: 820,
      ram_usage_mb: 420,
      evidence: { claim: "Low illumination attenuated pulse", flags: ["low_light"] },
    },
    aasist: {
      confidence: 0.5,
      latency_ms: 5,
      ram_usage_mb: 0,
      evidence: { claim: "Zero audio stream detected", flags: ["not_applicable"] },
    },
    syncnet: {
      error: "Stream container decode timeout",
    },
  };

  it("renders all 4 core detectors with pending, error, not_applicable, and scored states", () => {
    render(
      <DetectorResultsGrid
        detectorResponses={{
          video_classifier: baseResponses.video_classifier,
          rppg: null,
          aasist: baseResponses.aasist,
          syncnet: baseResponses.syncnet,
        }}
        fileName="interview.mp4"
        fileSize="4.2 MB"
      />
    );

    expect(screen.getByText("Video Frame Classifier")).toBeInTheDocument();
    expect(screen.getByText("rPPG Pulse Consistency")).toBeInTheDocument();
    expect(screen.getByText("AASIST Audio Detector")).toBeInTheDocument();
    expect(screen.getByText("SyncNet Audio-Visual")).toBeInTheDocument();

    expect(screen.getByText(/Awaiting Dispatch/i)).toBeInTheDocument();
    expect(screen.getByText("NOT APPLICABLE")).toBeInTheDocument();
    expect(screen.getByText("Stream container decode timeout")).toBeInTheDocument();
    expect(screen.getByText("91.0%")).toBeInTheDocument();
  });

  it("maps confidence thresholds accurately: <=0.35 AUTHENTIC, 0.36..0.64 INCONCLUSIVE, >=0.65 SYNTHETIC", () => {
    expect(verdictFromConfidence(0.35)).toBe("authentic");
    expect(verdictFromConfidence(0.5)).toBe("inconclusive");
    expect(verdictFromConfidence(0.65)).toBe("synthetic");

    render(
      <DetectorResultsGrid
        detectorResponses={{
          video_classifier: { ...baseResponses.video_classifier, confidence: 0.7 },
          rppg: { ...baseResponses.rppg, confidence: 0.5 },
          aasist: { ...baseResponses.rppg, confidence: 0.3 },
          syncnet: { ...baseResponses.video_classifier, confidence: 0.85 },
        }}
        fileName="clip.mp4"
        fileSize="2.1 MB"
      />
    );

    expect(screen.getAllByText("SYNTHETIC").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("INCONCLUSIVE")).toBeInTheDocument();
    expect(screen.getByText("AUTHENTIC")).toBeInTheDocument();
  });

  it("truncates long filenames in the middle while preserving extension and renders evaluated count", () => {
    render(
      <DetectorResultsGrid
        detectorResponses={{
          video_classifier: baseResponses.video_classifier,
          rppg: baseResponses.rppg,
          aasist: baseResponses.aasist,
          syncnet: baseResponses.syncnet,
        }}
        fileName="youtube_4k_broadcast_deepfake_test_clip_2026_final_export.mp4"
        fileSize="18.4 MB"
      />
    );

    expect(screen.getByText("3 of 4 Evaluated")).toBeInTheDocument();
    const bannerName = screen.getByTitle("youtube_4k_broadcast_deepfake_test_clip_2026_final_export.mp4");
    expect(bannerName.textContent).toContain("...");
    expect(bannerName.textContent).toMatch(/\.mp4$/);
  });

  it("renders Month 2 Judge Agent metadata and debate timeline when present", () => {
    render(
      <DetectorResultsGrid
        detectorResponses={{
          ...baseResponses,
          judge_verdict: "SYNTHETIC",
          judge_score: 0.89,
          siem_alert_tier: "TIER_3_CRITICAL",
          forensic_justification: "Corroborated synthetic facial blending.",
          guards_applied: ["Guard 1: Polarity Anti-Default"],
          debate_transcript: [
            { round: 1, speaker: "video_classifier", polarity: "SYNTHETIC", confidence: 0.91, claim: "Jaw blending" },
          ],
          debate_transcript_hash: "0xdeadbeef1234",
        }}
        fileName="clip.mp4"
        fileSize="1.0 MB"
      />
    );

    expect(screen.getByText(/Judge-Agent: Synthetic Manipulation Confirmed/i)).toBeInTheDocument();
    expect(screen.getAllByText("Corroborated synthetic facial blending.").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("0xdeadbeef1234")).toBeInTheDocument();
  });
});
