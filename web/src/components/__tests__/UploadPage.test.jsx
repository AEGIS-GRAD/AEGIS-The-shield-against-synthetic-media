import { describe, it, expect } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import UploadPage from "../UploadPage";

describe("UploadPage Workstation (W8)", () => {
  it("validates MIME allowlist and 100 MB limit while keeping submit disabled on invalid files", () => {
    const { container } = render(<UploadPage />);
    const fileInput = container.querySelector("#media-file-input");
    const submitBtn = screen.getByRole("button", { name: /Submit for Detection/i });

    expect(submitBtn).toBeDisabled();

    const pdfFile = new File(["%PDF"], "document.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput, { target: { files: [pdfFile] } });
    expect(screen.getByText(/Unsupported file type/i)).toBeInTheDocument();
    expect(submitBtn).toBeDisabled();

    const bigVideo = new File(["x"], "large_stream.mp4", { type: "video/mp4" });
    Object.defineProperty(bigVideo, "size", { value: 105 * 1024 * 1024 });
    fireEvent.change(fileInput, { target: { files: [bigVideo] } });
    expect(screen.getByText(/exceeds the maximum allowed limit of 100 MB/i)).toBeInTheDocument();
    expect(submitBtn).toBeDisabled();
  });

  it("supports drag-and-drop selection and file removal", async () => {
    const user = userEvent.setup();
    const { container } = render(<UploadPage />);
    const dropzone = container.querySelector('[class*="border-dashed"]');
    const validClip = new File(["video"], "suspect_anchor.mp4", { type: "video/mp4" });

    fireEvent.dragOver(dropzone);
    fireEvent.drop(dropzone, { dataTransfer: { files: [validClip] } });

    expect(screen.getByText("suspect_anchor.mp4")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Submit for Detection/i })).toBeEnabled();

    await user.click(screen.getByTitle("Remove file"));
    expect(screen.queryByText("suspect_anchor.mp4")).toBeNull();
    expect(screen.getByRole("button", { name: /Submit for Detection/i })).toBeDisabled();
  });

  it("submits valid media against MSW orchestrator and transitions to DetectorResultsGrid", async () => {
    const user = userEvent.setup();
    const { container } = render(<UploadPage />);
    const fileInput = container.querySelector("#media-file-input");
    const validClip = new File(["mp4-bytes"], "evidence_clip.mp4", { type: "video/mp4" });

    fireEvent.change(fileInput, { target: { files: [validClip] } });
    await user.click(screen.getByRole("button", { name: /Submit for Detection/i }));

    await waitFor(() =>
      expect(screen.getByText("All 4 Detectors Concluded")).toBeInTheDocument()
    );
    await user.click(screen.getByRole("button", { name: /View Forensic Results Grid/i }));

    expect(
      screen.getByText(/Judge-Agent: Synthetic Manipulation Confirmed/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText("Spatial deepfake artifacts detected in facial crops.")
    ).toBeInTheDocument();
  });

  it("surfaces a loud error without silent demo fallback when orchestrator health or dispatch fails", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("http://localhost:8000/health", () => HttpResponse.error())
    );

    const { container } = render(<UploadPage />);
    const fileInput = container.querySelector("#media-file-input");
    const clip = new File(["mp4"], "offline_check.mp4", { type: "video/mp4" });

    fireEvent.change(fileInput, { target: { files: [clip] } });
    await user.click(screen.getByRole("button", { name: /Submit for Detection/i }));

    await waitFor(() =>
      expect(screen.getByText(/Backend Pipeline \/ Execution Error/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/BACKEND OFFLINE/i)).toBeInTheDocument();
    expect(screen.queryByText(/Judge-Agent:/i)).toBeNull();

    server.use(
      http.get("http://localhost:8000/health", () =>
        HttpResponse.json({ status: "healthy" })
      ),
      http.post("http://localhost:8000/orchestrate", () =>
        HttpResponse.json({ detail: "GPU worker OOM" }, { status: 500 })
      )
    );

    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    await user.click(screen.getByRole("button", { name: /Submit for Detection/i }));
    await waitFor(() =>
      expect(screen.getByText(/ORCHESTRATOR HTTP 500/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/GPU worker OOM/i)).toBeInTheDocument();
    expect(screen.queryByText(/Judge-Agent:/i)).toBeNull();
  });
});
