import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";
import { useJobPolling } from "../useJobPolling";

describe("useJobPolling (W9)", () => {
  it("stays idle with zero attempts when jobId is null or empty", () => {
    const { result: nullResult } = renderHook(() => useJobPolling(null));
    expect(nullResult.current.status).toBe("idle");
    expect(nullResult.current.attempts).toBe(0);
    expect(nullResult.current.job).toBeNull();

    const { result: emptyResult } = renderHook(() => useJobPolling(""));
    expect(emptyResult.current.status).toBe("idle");
    expect(emptyResult.current.attempts).toBe(0);
  });

  it("polls running states until Complete and returns the resolved job", async () => {
    let calls = 0;
    server.use(
      http.get("/api/jobs", () => {
        calls += 1;
        if (calls < 3) {
          return HttpResponse.json({ id: "AEG-POLL-1", status: "Running", is_demo: false });
        }
        return HttpResponse.json({
          id: "AEG-POLL-1",
          status: "Complete",
          verdict: "synthetic",
          is_demo: false,
        });
      })
    );

    const { result } = renderHook(() =>
      useJobPolling("AEG-POLL-1", { intervalMs: 15, maxAttempts: 6 })
    );

    await waitFor(() => expect(result.current.status).toBe("complete"), { timeout: 2000 });
    expect(calls).toBe(3);
    expect(result.current.attempts).toBe(3);
    expect(result.current.job?.verdict).toBe("synthetic");
    expect(result.current.error).toBeNull();
  });

  it("transitions to not_found immediately on HTTP 404 without extra retries", async () => {
    let calls = 0;
    server.use(
      http.get("/api/jobs", () => {
        calls += 1;
        return HttpResponse.json({ error: "Job not found", is_demo: false }, { status: 404 });
      })
    );

    const { result } = renderHook(() =>
      useJobPolling("AEG-MISSING", { intervalMs: 15, maxAttempts: 5 })
    );

    await waitFor(() => expect(result.current.status).toBe("not_found"));
    await new Promise((r) => setTimeout(r, 40));
    expect(calls).toBe(1);
    expect(result.current.error).toContain("AEG-MISSING");
  });

  it("transitions to failed when the backend job payload reports Failed status", async () => {
    server.use(
      http.get("/api/jobs", () =>
        HttpResponse.json({
          id: "AEG-FAIL-1",
          status: "Failed",
          error: "Decoder crashed on malformed moov atom",
        })
      )
    );

    const { result } = renderHook(() =>
      useJobPolling("AEG-FAIL-1", { intervalMs: 15, maxAttempts: 4 })
    );

    await waitFor(() => expect(result.current.status).toBe("failed"));
    expect(result.current.error).toBe("Decoder crashed on malformed moov atom");
  });

  it("stops and transitions to timeout when maxAttempts is exhausted", async () => {
    let calls = 0;
    server.use(
      http.get("/api/jobs", () => {
        calls += 1;
        return HttpResponse.json({ id: "AEG-SLOW", status: "Running" });
      })
    );

    const { result } = renderHook(() =>
      useJobPolling("AEG-SLOW", { intervalMs: 10, maxAttempts: 3 })
    );

    await waitFor(() => expect(result.current.status).toBe("timeout"), { timeout: 2000 });
    expect(calls).toBe(3);
    expect(result.current.attempts).toBe(3);
    expect(result.current.error).toContain("timed out after 3 attempts");
  });

  it("applies exponential backoff on transient failures and recovers or reaches error state", async () => {
    const scheduledDelays: number[] = [];
    const origSetTimeout = globalThis.setTimeout;
    const timeoutSpy = vi.spyOn(globalThis, "setTimeout").mockImplementation(((fn: any, ms?: number, ...args: any[]) => {
      if (typeof ms === "number" && ms >= 10) {
        scheduledDelays.push(ms);
      }
      return origSetTimeout(fn, ms, ...args);
    }) as typeof setTimeout);

    let calls = 0;
    server.use(
      http.get("/api/jobs", () => {
        calls += 1;
        if (calls <= 2) {
          return HttpResponse.json({ error: "Upstream unavailable" }, { status: 500 });
        }
        return HttpResponse.json({ id: "AEG-RECOVER", status: "Complete", is_demo: false });
      })
    );

    const { result } = renderHook(() =>
      useJobPolling("AEG-RECOVER", { intervalMs: 10, maxAttempts: 5, maxBackoffMs: 40 })
    );

    await waitFor(() => expect(result.current.status).toBe("complete"), { timeout: 2000 });
    expect(calls).toBe(3);
    expect(scheduledDelays).toEqual(expect.arrayContaining([20, 40]));

    timeoutSpy.mockRestore();

    server.use(http.get("/api/jobs", () => HttpResponse.error()));
    const { result: errResult } = renderHook(() =>
      useJobPolling("AEG-ERR", { intervalMs: 10, maxAttempts: 2, maxBackoffMs: 20 })
    );
    await waitFor(() => expect(errResult.current.status).toBe("error"), { timeout: 2000 });
    expect(errResult.current.attempts).toBe(2);
  });

  it("aborts in-flight requests and clears scheduled timers on unmount", async () => {
    let calls = 0;
    let wasAborted = false;

    server.use(
      http.get("/api/jobs", async ({ request }) => {
        calls += 1;
        request.signal.addEventListener("abort", () => {
          wasAborted = true;
        });
        await new Promise((r) => setTimeout(r, 80));
        return HttpResponse.json({ id: "AEG-UNMOUNT", status: "Running" });
      })
    );

    const { unmount } = renderHook(() =>
      useJobPolling("AEG-UNMOUNT", { intervalMs: 15, maxAttempts: 5 })
    );

    await waitFor(() => expect(calls).toBe(1));
    unmount();

    await new Promise((r) => setTimeout(r, 120));
    expect(wasAborted).toBe(true);
    expect(calls).toBe(1);
  });
});

