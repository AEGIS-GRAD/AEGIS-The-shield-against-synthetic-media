import { http, HttpResponse } from "msw";
import {
  ORCHESTRATION_SUCCESS_RESPONSE,
  REAL_SYNTHETIC_JOB,
  type RealJobRecord,
} from "../fixtures/orchestrator";

export const defaultJobsStore: RealJobRecord[] = [REAL_SYNTHETIC_JOB];

export const handlers = [
  http.get("http://localhost:8000/health", () =>
    HttpResponse.json({
      status: "healthy",
      service: "orchestrator",
      active_detectors: ["video-classifier", "rppg", "aasist", "syncnet", "text"],
    })
  ),

  http.post("http://localhost:8000/orchestrate", async () =>
    HttpResponse.json(ORCHESTRATION_SUCCESS_RESPONSE)
  ),

  http.post("http://localhost:8765/analyze_video", async () =>
    HttpResponse.json({
      id: REAL_SYNTHETIC_JOB.id,
      verdict: REAL_SYNTHETIC_JOB.verdict,
      confidence: REAL_SYNTHETIC_JOB.confidence,
      status: "Complete",
    })
  ),

  http.get("http://localhost:8081/health", () =>
    HttpResponse.json({ status: "healthy", gateway: "nginx-tls" })
  ),

  http.get("/api/health", () =>
    HttpResponse.json({
      status: "healthy",
      service: "aegis-web",
      timestamp: new Date().toISOString(),
    })
  ),

  http.get("/api/jobs", ({ request }) => {
    const url = new URL(request.url);
    const id = url.searchParams.get("id");
    const demo = url.searchParams.get("demo");
    const aggregate = url.searchParams.get("aggregate");

    if (id) {
      const found = defaultJobsStore.find((j) => j.id === id);
      if (found) {
        return HttpResponse.json(found);
      }
      return HttpResponse.json({ error: "Job not found", is_demo: false }, { status: 404 });
    }

    if (aggregate === "true") {
      const synthetic = defaultJobsStore.filter((j) => j.verdict === "synthetic").length;
      const authentic = defaultJobsStore.filter((j) => j.verdict === "authentic").length;
      const inconclusive = defaultJobsStore.filter((j) => j.verdict === "inconclusive").length;
      const total = defaultJobsStore.length;
      return HttpResponse.json({
        is_demo: demo === "true",
        total_analyses: total,
        synthetic_count: synthetic,
        authentic_count: authentic,
        inconclusive_count: inconclusive,
        synthetic_rate_pct: total > 0 ? Math.round((synthetic / total) * 1000) / 10 : 0,
        avg_latency_ms: 1420,
        recent_analyses: defaultJobsStore.slice(0, 5),
      });
    }

    return HttpResponse.json(defaultJobsStore);
  }),

  http.post("/api/jobs", async ({ request }) => {
    const body = (await request.json()) as Partial<RealJobRecord>;
    return HttpResponse.json(
      { ...REAL_SYNTHETIC_JOB, ...body, is_demo: false },
      { status: 201 }
    );
  }),
];
