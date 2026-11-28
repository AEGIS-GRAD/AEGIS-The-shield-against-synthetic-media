import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { VideoTimeline } from "../VideoTimeline";

describe("VideoTimeline (Task 4)", () => {
    it("renders N bars for N frame scores", () => {
        const scores = [0.1, 0.4, 0.8, 0.9, 0.3, 0.2, 0.7, 0.6, 0.5, 0.15];
        render(<VideoTimeline frameScores={scores} />);
        expect(screen.getAllByTestId("video-timeline-bar")).toHaveLength(scores.length);
    });

    it("renders nothing when frameScores is empty", () => {
        const { container } = render(<VideoTimeline frameScores={[]} />);
        expect(container.firstChild).toBeNull();
    });

    it("renders nothing when frameScores is undefined", () => {
        // @ts-ignore testing runtime safety
        const { container } = render(<VideoTimeline frameScores={undefined} />);
        expect(container.firstChild).toBeNull();
    });

    it("shows the claim sentence when provided", () => {
        render(
            <VideoTimeline
                frameScores={[0.8, 0.9]}
                claim="Blending artifacts detected around the face region in frames 0-10 (strong confidence)."
            />
        );
        expect(screen.getByText(/blending artifacts/i)).toBeInTheDocument();
    });

    it("shows the flagged range badge when provided", () => {
        render(
            <VideoTimeline
                frameScores={[0.8, 0.9]}
                flaggedRange="frames 20-60"
            />
        );
        expect(screen.getByText(/frames 20-60/i)).toBeInTheDocument();
    });

    it("does NOT show flagged range badge when flaggedRange is null", () => {
        render(<VideoTimeline frameScores={[0.1, 0.2]} flaggedRange={null} />);
        expect(screen.queryByText(/flagged/i)).toBeNull();
    });

    it("high-score bars use the synthetic colour class", () => {
        render(<VideoTimeline frameScores={[0.9]} />);
        const bar = screen.getByTestId("video-timeline-bar");
        expect(bar.className).toMatch(/bg-synthetic/);
    });

    it("low-score bars use the authentic colour class", () => {
        render(<VideoTimeline frameScores={[0.1]} />);
        const bar = screen.getByTestId("video-timeline-bar");
        expect(bar.className).toMatch(/bg-emerald/);
    });

    it("borderline bars use the inconclusive colour class", () => {
        render(<VideoTimeline frameScores={[0.5]} />);
        const bar = screen.getByTestId("video-timeline-bar");
        expect(bar.className).toMatch(/bg-inconclusive/);
    });

    it("NaN score is treated as 0 and bar still renders", () => {
        render(<VideoTimeline frameScores={[NaN]} />);
        const bar = screen.getByTestId("video-timeline-bar");
        // 0 → authentic class
        expect(bar.className).toMatch(/bg-emerald/);
    });
});