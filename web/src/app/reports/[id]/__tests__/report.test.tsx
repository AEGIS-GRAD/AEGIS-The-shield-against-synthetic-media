import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import ReportDetailPage from "../page";
import {
  resetNextMocks,
  setMockParams,
} from "@/test/mocks/next";
import { REAL_SYNTHETIC_JOB } from "@/test/fixtures/orchestrator";

vi.mock("next/navigation", async () => {
  const { getNextNavigationMock } = await import("@/test/mocks/next");
  return getNextNavigationMock();
});

describe("ReportDetailPage Integration (W13)", () => {
  beforeEach(() => {
    resetNextMocks();
    localStorage.clear();
  });

  it("renders a real adjudicated report without demo banners even when demo preference is stored", async () => {
    localStorage.setItem("aegis_demo_mode_enabled", "true");
    setMockParams({ id: REAL_SYNTHETIC_JOB.id });

    render(<ReportDetailPage />);

    await waitFor(() =>
      expect(screen.getByText("interview_clip_real.mp4")).toBeInTheDocument()
    );
    expect(screen.getByText("REAL ADJUDICATED REPORT")).toBeInTheDocument();
    expect(
      screen.queryByText(/This report is a simulated forensic evaluation fixture/i)
    ).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();

    expect(screen.getByText(/Frame suspicion \(sampled temporal frames\)/i)).toBeInTheDocument();
    expect(screen.getByText("Detector agreement")).toBeInTheDocument();
    expect(screen.getByText("Multi-Agent Debate & Judge Reasoning")).toBeInTheDocument();
    expect(screen.getByText("Chain of evidence")).toBeInTheDocument();
  });

  it("shows the Demo data banner and badge when loading a simulated demo or preset report", async () => {
    server.use(
      http.get("/api/jobs", () =>
        HttpResponse.json({
          ...REAL_SYNTHETIC_JOB,
          id: "clean_baseline",
          file: "clean_interview_broadcast.mp4",
          verdict: "authentic",
          judge_verdict: "AUTHENTIC",
          is_demo: true,
        })
      )
    );
    setMockParams({ id: "clean_baseline" });

    render(<ReportDetailPage />);

    await waitFor(() =>
      expect(screen.getByText("clean_interview_broadcast.mp4")).toBeInTheDocument()
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      /simulated forensic evaluation fixture/i
    );
    expect(screen.getAllByText("Demo data").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("REAL ADJUDICATED REPORT")).toBeNull();
  });

  it("renders Report Not Found when id is missing and demo mode is disabled, then switches when enabled", async () => {
    const user = userEvent.setup();
    setMockParams({ id: "AEG-UNKNOWN-999" });

    render(<ReportDetailPage />);

    await waitFor(() =>
      expect(screen.getByText("Report Not Found")).toBeInTheDocument()
    );
    expect(screen.getByText("AEG-UNKNOWN-999")).toBeInTheDocument();

    const enableBtn = screen.getByRole("button", { name: /Enable Demo Data/i });
    await user.click(enableBtn);

    await waitFor(() =>
      expect(screen.getAllByText("Demo data").length).toBeGreaterThanOrEqual(1)
    );
    expect(localStorage.getItem("aegis_demo_mode_enabled")).toBe("true");
  });
});
