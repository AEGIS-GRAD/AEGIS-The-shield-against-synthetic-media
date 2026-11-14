import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AnalyzePage from "../page";
import {
  mockPush,
  resetNextMocks,
} from "@/test/mocks/next";

vi.mock("next/navigation", async () => {
  const { getNextNavigationMock } = await import("@/test/mocks/next");
  return getNextNavigationMock();
});

describe("AnalyzePage Upload Workstation (W7)", () => {
  beforeEach(() => {
    resetNextMocks();
    delete (window as any).__currentAnalyzeFile;
  });

  afterEach(() => {
    delete (window as any).__currentAnalyzeFile;
  });

  it("rejects unsupported file extensions, empty 0-byte files, and files over 100 MB", () => {
    const { container } = render(<AnalyzePage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();

    const exeFile = new File(["MZ"], "payload.exe", { type: "application/x-msdownload" });
    fireEvent.change(input, { target: { files: [exeFile] } });
    expect(screen.getByRole("alert")).toHaveTextContent(/not a supported type/i);
    expect(screen.getByRole("button", { name: /Run analysis/i })).toBeDisabled();

    const emptyFile = new File([], "empty.mp4", { type: "video/mp4" });
    fireEvent.change(input, { target: { files: [emptyFile] } });
    expect(screen.getByRole("alert")).toHaveTextContent(/empty \(0 bytes\)/i);

    const hugeFile = new File(["x"], "huge.mp4", { type: "video/mp4" });
    Object.defineProperty(hugeFile, "size", { value: 101 * 1024 * 1024 });
    fireEvent.change(input, { target: { files: [hugeFile] } });
    expect(screen.getByRole("alert")).toHaveTextContent(/101\.0 MB.*limit is 100 MB/i);
  });

  it("accepts a valid mp4 file via drag-and-drop and allows removing it", async () => {
    const user = userEvent.setup();
    const { container } = render(<AnalyzePage />);
    const dropzone = container.querySelector('[class*="border-dashed"]') as HTMLElement;
    const validFile = new File(["video-bytes"], "interview_sample.mp4", { type: "video/mp4" });

    fireEvent.dragOver(dropzone);
    fireEvent.drop(dropzone, { dataTransfer: { files: [validFile] } });

    expect(screen.getByText("interview_sample.mp4")).toBeInTheDocument();
    expect(screen.getByText("Ready for analysis")).toBeInTheDocument();

    const runBtn = screen.getByRole("button", { name: /Run analysis/i });
    expect(runBtn).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Remove file" }));
    expect(screen.queryByText("interview_sample.mp4")).toBeNull();
    expect(screen.getByRole("button", { name: /Run analysis/i })).toBeDisabled();
  });

  it("stores the uploaded file handle and pushes to processing route on Run analysis", async () => {
    const user = userEvent.setup();
    const { container } = render(<AnalyzePage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const clip = new File(["mp4-content"], "clip.mp4", { type: "video/mp4" });

    fireEvent.change(input, { target: { files: [clip] } });
    await user.click(screen.getByRole("button", { name: /Run analysis/i }));

    expect((window as any).__currentAnalyzeFile).toBe(clip);
    expect(mockPush).toHaveBeenCalledTimes(1);
    const dest = mockPush.mock.calls[0][0] as string;
    expect(dest).toMatch(/^\/analyze\/processing\?/);
    expect(dest).toContain("file=clip.mp4");
  });

  it("displays explicit modality roadmap notices when switching to Image and Text tabs", async () => {
    const user = userEvent.setup();
    render(<AnalyzePage />);

    await user.click(screen.getByRole("button", { name: /^Image\s*Planned$/i }));
    expect(screen.getByText("Image Deepfake Classifier (UnivFD CLIP)")).toBeInTheDocument();
    expect(screen.getByText("NOT YET TRAINED")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Text\s*Planned$/i }));
    expect(screen.getByText("Text Perplexity Detector (Binoculars)")).toBeInTheDocument();
    expect(screen.getByText("UNDER CALIBRATION")).toBeInTheDocument();
  });
});
