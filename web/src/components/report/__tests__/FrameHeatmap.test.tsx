import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FrameHeatmap } from "../FrameHeatmap";

describe("FrameHeatmap (W1)", () => {
  it("renders N bars for N input frame scores", () => {
    const scores = [0.15, 0.42, 0.78, 0.91, 0.33];
    render(<FrameHeatmap scores={scores} />);
    expect(screen.getAllByTestId("frame-heat-bar")).toHaveLength(scores.length);
  });

  it("enforces the 0.08 opacity floor for 0 and negative scores", () => {
    render(<FrameHeatmap scores={[0, -0.5, 0.02]} />);
    const bars = screen.getAllByTestId("frame-heat-bar");
    for (const bar of bars) {
      expect(bar).toHaveStyle({ opacity: "0.08" });
    }
  });

  it("clamps frame suspicion scores above 1.0 down to 1", () => {
    render(<FrameHeatmap scores={[1.8, 1.0]} />);
    const bars = screen.getAllByTestId("frame-heat-bar");
    expect(bars[0]).toHaveStyle({ opacity: "1" });
    expect(bars[1]).toHaveStyle({ opacity: "1" });
  });

  it("handles NaN safely at the 0.08 floor", () => {
    render(<FrameHeatmap scores={[Number.NaN]} />);
    expect(screen.getByTestId("frame-heat-bar")).toHaveStyle({ opacity: "0.08" });
  });

  it("renders an explicit empty fallback when scores array is empty", () => {
    render(<FrameHeatmap scores={[]} />);
    expect(screen.queryByTestId("frame-heat-bar")).toBeNull();
    expect(screen.getByTestId("frame-heat-empty")).toHaveTextContent(
      /no per-frame suspicion scores available/i
    );
  });

  it("shows DemoBadge only when isDemo is true", () => {
    const { rerender } = render(<FrameHeatmap scores={[0.2, 0.8]} isDemo={false} />);
    expect(screen.queryByText(/demo data/i)).toBeNull();

    rerender(<FrameHeatmap scores={[0.2, 0.8]} isDemo={true} />);
    expect(screen.getByText(/demo data/i)).toBeInTheDocument();
  });
});

