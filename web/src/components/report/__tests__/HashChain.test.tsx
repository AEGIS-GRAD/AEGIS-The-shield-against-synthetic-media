import { describe, it, expect, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { HashChain } from "../HashChain";
import type { HashChainEvent } from "@/lib/report";

describe("HashChain (W5)", () => {
  const fileHash = "sha256-aeg-9001-7e60c3a1b2d9e8f7";
  const transcriptHash = "0xabc123def4567890fedcba0987654321";
  const events: HashChainEvent[] = [
    ["09:42:03", "File received & cryptographic hash computed", "bg-emerald-500"],
    ["09:42:09", "Video Frame Classifier: evaluated (synthetic)", "bg-cyan-500"],
    ["09:42:18", "Judge Adjudication certified: SYNTHETIC [TIER_3_CRITICAL]", "bg-accent"],
  ];

  it("renders fileHash, transcriptHash, and VERIFIED badge", () => {
    render(<HashChain fileHash={fileHash} transcriptHash={transcriptHash} events={events} />);
    expect(screen.getByText(fileHash)).toBeInTheDocument();
    expect(screen.getByText(transcriptHash)).toBeInTheDocument();
    expect(screen.getByText("VERIFIED")).toBeInTheDocument();
  });

  it("renders timeline events in sequence with judge certification details", () => {
    const { container } = render(
      <HashChain fileHash={fileHash} transcriptHash={transcriptHash} events={events} />
    );
    const items = container.querySelectorAll("ol li");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("09:42:03");
    expect(items[2]).toHaveTextContent("Judge Adjudication certified: SYNTHETIC [TIER_3_CRITICAL]");
  });

  it("copies transcriptHash to clipboard and toggles Copy -> Copied -> Copy", async () => {
    vi.useFakeTimers();
    const writeSpy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);

    render(<HashChain fileHash={fileHash} transcriptHash={transcriptHash} events={events} />);
    const copyBtn = screen.getByRole("button", { name: /copy/i });
    expect(copyBtn).toHaveTextContent("Copy");

    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(writeSpy).toHaveBeenCalledWith(transcriptHash);
    expect(screen.getByRole("button", { name: /copied/i })).toHaveTextContent("Copied");

    act(() => {
      vi.advanceTimersByTime(2100);
    });
    expect(screen.getByRole("button", { name: /copy/i })).toHaveTextContent("Copy");
    writeSpy.mockRestore();
  });

  it("invokes custom onCopy handler when supplied", () => {
    const onCopy = vi.fn();
    render(
      <HashChain
        fileHash={fileHash}
        transcriptHash={transcriptHash}
        events={events}
        onCopy={onCopy}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /copy/i }));
    expect(onCopy).toHaveBeenCalledWith(transcriptHash);
  });
});

