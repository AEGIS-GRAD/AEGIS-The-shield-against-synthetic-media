import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import ProcessingPage from "../page";
import {
  mockPush,
  resetNextMocks,
  setMockSearchParams,
} from "@/test/mocks/next";

vi.mock("next/navigation", async () => {
  const { getNextNavigationMock } = await import("@/test/mocks/next");
  return getNextNavigationMock();
});

describe("ProcessingPage Job Polling & Dispatch (W10)", () => {
  beforeEach(() => {
    resetNextMocks();
    delete (window as any).__currentAnalyzeFile;
  });

  afterEach(() => {
    delete (window as any).__currentAnalyzeFile;
  });

  it("dispatches upload to :8765, polls /api/jobs until Complete, and navigates to report", async () => {
    let pollCalls = 0;
    server.use(
      http.get("/api/jobs", () => {
        pollCalls += 1;
        if (pollCalls === 1) {
          return HttpResponse.json({ id: "AEG-LIVE-9001", status: "Running", is_demo: false });
        }
        return HttpResponse.json({
          id: "AEG-LIVE-9001",
          status: "Complete",
          verdict: "synthetic",
          is_demo: false,
        });
      })
    );

    setMockSearchParams({ file: "interview_clip_real.mp4" });
    (window as any).__currentAnalyzeFile = new File(["bytes"], "interview_clip_real.mp4", {
      type: "video/mp4",
    });

    render(<ProcessingPage />);

    await waitFor(
      () => expect(screen.getByText(/Report verified — Verdict: SYNTHETIC/i)).toBeInTheDocument(),
      { timeout: 2500 }
    );
    expect(pollCalls).toBe(2);

    await waitFor(
      () => expect(mockPush).toHaveBeenCalledWith("/reports/AEG-LIVE-9001"),
      { timeout: 3000 }
    );
  });

  it("shows Backend Inference Unreachable and never redirects when :8765 returns 500", async () => {
    let jobsPolled = 0;
    server.use(
      http.post("http://localhost:8765/analyze_video", () =>
        HttpResponse.json({ error: "GPU pipeline failed" }, { status: 500 })
      ),
      http.get("/api/jobs", () => {
        jobsPolled += 1;
        return HttpResponse.json({ id: "AEG-LIVE-9001", status: "Complete" });
      })
    );

    setMockSearchParams({ file: "broken.mp4" });
    (window as any).__currentAnalyzeFile = new File(["bytes"], "broken.mp4", {
      type: "video/mp4",
    });

    render(<ProcessingPage />);

    await waitFor(() =>
      expect(screen.getByText("Backend Inference Unreachable")).toBeInTheDocument()
    );
    expect(screen.getByText(/Inference service returned HTTP 500/i)).toBeInTheDocument();
    expect(jobsPolled).toBe(0);
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("fails loudly without redirecting if /api/jobs returns 404 for the submitted job", async () => {
    server.use(
      http.post("http://localhost:8765/analyze_video", () =>
        HttpResponse.json({ id: "AEG-GHOST-404", verdict: "authentic" })
      ),
      http.get("/api/jobs", () =>
        HttpResponse.json({ error: "Job not found", is_demo: false }, { status: 404 })
      )
    );

    setMockSearchParams({ file: "ghost.mp4" });
    (window as any).__currentAnalyzeFile = new File(["bytes"], "ghost.mp4", {
      type: "video/mp4",
    });

    render(<ProcessingPage />);

    await waitFor(() =>
      expect(screen.getByText("Backend Inference Unreachable")).toBeInTheDocument()
    );
    expect(screen.getByText(/AEG-GHOST-404 was not found/i)).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("renders Month 2 preset mode and skipped unbuilt modality notices when preset param is set", () => {
    setMockSearchParams({ file: "clean_interview.mp4", preset: "clean_baseline" });
    render(<ProcessingPage />);

    expect(screen.getByText(/Month 2 Milestone Demo Preset: CLEAN BASELINE/i)).toBeInTheDocument();
    expect(screen.getByText(/Model not built yet \(under calibration\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Model not built yet \(Phase 3 training\)/i)).toBeInTheDocument();
  });
});
