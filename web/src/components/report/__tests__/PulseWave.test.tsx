import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PulseWave } from "../PulseWave";
import { buildPulsePath } from "@/lib/report";

describe("PulseWave (W2)", () => {
  it("renders SVG waveform with a valid path d attribute", () => {
    const { container } = render(<PulseWave bpm={71} />);
    const svg = container.querySelector("svg[aria-label='rPPG pulse waveform']");
    expect(svg).not.toBeNull();
    const path = svg?.querySelector("path");
    expect(path).not.toBeNull();
    const d = path?.getAttribute("d") || "";
    expect(d.startsWith("M0 ")).toBe(true);
    expect(d).toContain("L5 ");
  });

  it("renders the provided bpm prop in the caption", () => {
    render(<PulseWave bpm={68} />);
    expect(screen.getByText(/Estimated 68 BPM/i)).toBeInTheDocument();
  });

  it("falls back to default 74 BPM when bpm prop is omitted", () => {
    render(<PulseWave />);
    expect(screen.getByText(/Estimated 74 BPM/i)).toBeInTheDocument();
  });

  it("buildPulsePath returns deterministic SVG path strings", () => {
    const first = buildPulsePath();
    const second = buildPulsePath();
    expect(first).toBe(second);
    expect(first.split("L")).toHaveLength(41);
  });

  it("buildPulsePath normalizes custom pulse signals including flat arrays", () => {
    const customPath = buildPulsePath([0.1, 0.5, 0.9]);
    expect(customPath).toBe("M0 32 L100 20 L200 8");

    const flatPath = buildPulsePath([42, 42, 42]);
    expect(flatPath).toBe("M0 32 L100 32 L200 32");
  });
});

