import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgreementMatrix } from "../AgreementMatrix";
import { agreementFromScores } from "@/lib/report";

describe("AgreementMatrix (W4)", () => {
  const ids = ["video", "rppg", "syncnet", "aasist"];
  const matrix = [
    [1.0, 0.2, 0.9, 0.85],
    [0.2, 1.0, 0.25, 0.3],
    [0.9, 0.25, 1.0, 0.8],
    [0.85, 0.3, 0.8, 1.0],
  ];

  it("renders 16 cells for a 4x4 detector agreement grid", () => {
    render(<AgreementMatrix ids={ids} matrix={matrix} />);
    const cells = [];
    for (let r = 0; r < 4; r += 1) {
      for (let c = 0; c < 4; c += 1) {
        cells.push(screen.getByTestId(`agreement-cell-${r}-${c}`));
      }
    }
    expect(cells).toHaveLength(16);
    expect(screen.getByTestId("agreement-cell-0-0")).toHaveTextContent("1.00");
    expect(screen.getByTestId("agreement-cell-0-1")).toHaveTextContent("0.20");
  });

  it("marks values below default conflictThreshold (0.4) with amber conflict classes", () => {
    render(<AgreementMatrix ids={ids} matrix={matrix} />);
    expect(screen.getByTestId("agreement-cell-0-1")).toHaveClass("bg-inconclusive-soft", "text-inconclusive-ink");
    expect(screen.getByTestId("agreement-cell-0-2")).toHaveClass("bg-primary", "text-primary-foreground");
    expect(screen.getByTestId("agreement-cell-0-3")).toHaveClass("bg-primary", "text-primary-foreground");
  });

  it("respects a custom conflictThreshold prop", () => {
    render(<AgreementMatrix ids={ids} matrix={matrix} conflictThreshold={0.9} />);
    // 0.85 is >= 0.4 so normally primary, but < 0.9 so conflict under stricter threshold
    expect(screen.getByTestId("agreement-cell-0-3")).toHaveClass("bg-inconclusive-soft");
    expect(screen.getByTestId("agreement-cell-0-2")).toHaveClass("bg-primary");
  });

  it("renders matching column and row detector headers and rPPG limitation note", () => {
    render(<AgreementMatrix ids={ids} matrix={matrix} />);
    for (const id of ids) {
      expect(screen.getAllByText(id)).toHaveLength(2);
    }
    expect(screen.getByText(/Known limitation: rPPG is much less reliable/i)).toBeInTheDocument();
  });

  it("agreementFromScores computes a symmetric [0,1] matrix with 1.0 on diagonal", () => {
    const out = agreementFromScores(["a", "b", "c"], { a: 0.9, b: 0.1, c: 0.8 });
    expect(out).toEqual([
      [1, 0.2, 0.9],
      [0.2, 1, 0.3],
      [0.9, 0.3, 1],
    ]);
  });
});

