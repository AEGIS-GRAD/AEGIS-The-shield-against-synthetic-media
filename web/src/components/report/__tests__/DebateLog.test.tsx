import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DebateLog } from "../DebateLog";
import { REAL_SYNTHETIC_JOB } from "@/test/fixtures/orchestrator";

describe("DebateLog (W3)", () => {
  const baseProps = {
    transcript: REAL_SYNTHETIC_JOB.debate_transcript,
    judgeVerdict: "SYNTHETIC",
    judgeScore: 0.91,
    siemTier: "TIER_3_CRITICAL",
    justification: REAL_SYNTHETIC_JOB.forensic_justification,
    crossExam: REAL_SYNTHETIC_JOB.cross_examination_findings,
    guards: REAL_SYNTHETIC_JOB.guards_applied,
  };

  it("renders every debate round R1 through R3 and formats underscores in speaker names", () => {
    render(<DebateLog {...baseProps} />);
    expect(screen.getAllByText(/^R1$/)).toHaveLength(2);
    expect(screen.getByText("R2")).toBeInTheDocument();
    expect(screen.getByText("R3")).toBeInTheDocument();
    expect(screen.getByText("video classifier")).toBeInTheDocument();
    expect(screen.getByText("judge agent")).toBeInTheDocument();
  });

  it("applies distinct badge styling for SYNTHETIC, AUTHENTIC, and NOT_APPLICABLE polarities", () => {
    render(
      <DebateLog
        {...baseProps}
        transcript={[
          { round: 1, speaker: "aasist", polarity: "SYNTHETIC", confidence: 0.95, claim: "Vocoder match" },
          { round: 1, speaker: "rppg", polarity: "AUTHENTIC", confidence: 0.88, claim: "Natural pulse" },
          { round: 2, speaker: "syncnet", polarity: "NOT_APPLICABLE", confidence: 0, claim: "No audio stream" },
        ]}
      />
    );
    const synBadges = screen.getAllByText("SYNTHETIC");
    expect(synBadges[0]).toHaveClass("text-rose-400");
    expect(screen.getByText("AUTHENTIC")).toHaveClass("text-emerald-400");
    expect(screen.getByText("NOT_APPLICABLE")).toHaveClass("text-muted-foreground");
  });

  it("displays confidence percentage when > 0 and omits it when 0", () => {
    render(
      <DebateLog
        {...baseProps}
        transcript={[
          { round: 1, speaker: "aasist", polarity: "SYNTHETIC", confidence: 0.95, claim: "Spoof found" },
          { round: 1, speaker: "syncnet", polarity: "NOT_APPLICABLE", confidence: 0, claim: "No audio" },
        ]}
      />
    );
    expect(screen.getByText("conf: 95%")).toBeInTheDocument();
    expect(screen.queryByText("conf: 0%")).toBeNull();
  });

  it("renders the Judge Agent adjudication box with verdict, percentage score, SIEM tier, and guards", () => {
    render(<DebateLog {...baseProps} />);
    expect(screen.getByText(/Judge Agent Adjudication:/i)).toBeInTheDocument();
    expect(screen.getByText("(91% score)")).toBeInTheDocument();
    expect(screen.getByText(/SIEM TIER 3 — CRITICAL/i)).toBeInTheDocument();
    expect(screen.getByText("Guard 1: Unresolved Polarity Inversion Anti-Default")).toBeInTheDocument();
    expect(screen.getByText("Guard 2: Cross-Modal Corroboration Requirement Satisfied")).toBeInTheDocument();
  });

  it("renders crossExam safely whether passed as an array of findings or a single string", () => {
    const { rerender } = render(
      <DebateLog
        {...baseProps}
        crossExam={["Finding alpha", "Finding beta"]}
      />
    );
    expect(screen.getByText("Finding alpha")).toBeInTheDocument();
    expect(screen.getByText("Finding beta")).toBeInTheDocument();

    rerender(
      <DebateLog
        {...baseProps}
        crossExam="Single string synthesis note from preset"
      />
    );
    expect(screen.getByText("Single string synthesis note from preset")).toBeInTheDocument();
  });

  it("omits the cross-examination box when crossExam is null or empty", () => {
    render(<DebateLog {...baseProps} crossExam={null} />);
    expect(screen.queryByText(/Cross-Examination Synthesis:/i)).toBeNull();
  });

  it("falls back to default debate messages with Modal Conflict chip when transcript is null", () => {
    render(<DebateLog {...baseProps} transcript={null} />);
    expect(screen.getByText("Modal Conflict")).toBeInTheDocument();
    expect(screen.getByText("rPPG Heartbeat")).toBeInTheDocument();
  });
});
