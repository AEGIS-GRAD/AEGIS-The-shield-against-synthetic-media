// @vitest-environment node
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";

describe("API Route /api/jobs (W11)", () => {
  let tmpDir: string;
  let GET: (req: NextRequest) => Promise<Response>;
  let POST: (req: NextRequest) => Promise<Response>;

  beforeEach(async () => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "aegis-jobs-test-"));
    vi.spyOn(process, "cwd").mockReturnValue(tmpDir);
    vi.resetModules();
    const mod = await import("../route");
    GET = mod.GET;
    POST = mod.POST;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("persists posted real jobs with is_demo: false and retrieves them by id", async () => {
    const postReq = new NextRequest("http://localhost:3000/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        id: "AEG-TEST-777",
        file: "bench_clip.mp4",
        verdict: "authentic",
        confidence: 0.92,
      }),
    });

    const postRes = await POST(postReq);
    expect(postRes.status).toBe(201);
    const created = await postRes.json();
    expect(created.id).toBe("AEG-TEST-777");
    expect(created.is_demo).toBe(false);

    const getRes = await GET(new NextRequest("http://localhost:3000/api/jobs?id=AEG-TEST-777"));
    expect(getRes.status).toBe(200);
    const fetched = await getRes.json();
    expect(fetched.file).toBe("bench_clip.mp4");
    expect(fetched.is_demo).toBe(false);
    expect(fs.existsSync(path.join(tmpDir, ".jobs", "jobs.json"))).toBe(true);
  });

  it("flags preset and mock demo IDs as is_demo: true and returns 404 for unknown IDs", async () => {
    const presetRes = await GET(new NextRequest("http://localhost:3000/api/jobs?id=clean_baseline"));
    expect(presetRes.status).toBe(200);
    const presetBody = await presetRes.json();
    expect(presetBody.is_demo).toBe(true);
    expect(presetBody.verdict).toBe("authentic");

    const mockRes = await GET(new NextRequest("http://localhost:3000/api/jobs?id=AEG-1042"));
    expect(mockRes.status).toBe(200);
    expect((await mockRes.json()).is_demo).toBe(true);

    const missingRes = await GET(new NextRequest("http://localhost:3000/api/jobs?id=AEG-NONEXISTENT"));
    expect(missingRes.status).toBe(404);
    expect((await missingRes.json()).is_demo).toBe(false);
  });

  it("separates strict real lists (?demo=false), demo lists (?demo=true), and combined lists (?demo=all)", async () => {
    const emptyRealRes = await GET(new NextRequest("http://localhost:3000/api/jobs?demo=false"));
    expect(await emptyRealRes.json()).toEqual([]);

    await POST(
      new NextRequest("http://localhost:3000/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ id: "AEG-REAL-1", file: "real.mp4", verdict: "synthetic" }),
      })
    );

    const strictReal = await (await GET(new NextRequest("http://localhost:3000/api/jobs?demo=false"))).json();
    expect(strictReal).toHaveLength(1);
    expect(strictReal[0].id).toBe("AEG-REAL-1");
    expect(strictReal[0].is_demo).toBe(false);

    const demoOnly = await (await GET(new NextRequest("http://localhost:3000/api/jobs?demo=true"))).json();
    expect(demoOnly.length).toBeGreaterThan(0);
    expect(demoOnly.every((item: any) => item.is_demo === true)).toBe(true);

    const allJobs = await (await GET(new NextRequest("http://localhost:3000/api/jobs?demo=all"))).json();
    expect(allJobs[0].id).toBe("AEG-REAL-1");
    expect(allJobs[0].is_demo).toBe(false);
    expect(allJobs.some((item: any) => item.is_demo === true)).toBe(true);
  });

  it("computes real-only and empty aggregate stats when ?aggregate=true is requested", async () => {
    const emptyAgg = await (
      await GET(new NextRequest("http://localhost:3000/api/jobs?aggregate=true&demo=false"))
    ).json();
    expect(emptyAgg.total_analyses).toBe(0);
    expect(emptyAgg.synthetic_rate_pct).toBe(0);
    expect(emptyAgg.is_demo).toBe(false);

    await POST(
      new NextRequest("http://localhost:3000/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          id: "AEG-AGG-1",
          verdict: "synthetic",
          raw_results: [{ latency_ms: 600 }, { latency_ms: 400 }],
        }),
      })
    );
    await POST(
      new NextRequest("http://localhost:3000/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          id: "AEG-AGG-2",
          verdict: "authentic",
          raw_results: [{ latency_ms: 500 }],
        }),
      })
    );

    const realAgg = await (
      await GET(new NextRequest("http://localhost:3000/api/jobs?aggregate=true"))
    ).json();
    expect(realAgg.is_demo).toBe(false);
    expect(realAgg.total_analyses).toBe(2);
    expect(realAgg.synthetic_count).toBe(1);
    expect(realAgg.authentic_count).toBe(1);
    expect(realAgg.synthetic_rate_pct).toBe(50);
    expect(realAgg.avg_latency_ms).toBe(750);
  });

  it("returns 400 on malformed JSON payloads in POST", async () => {
    const badReq = new NextRequest("http://localhost:3000/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{not-valid-json",
    });

    const res = await POST(badReq);
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBeTruthy();
  });
});
