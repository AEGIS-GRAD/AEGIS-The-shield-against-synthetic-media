"use client";

import { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Check, Loader2, Clock, MinusCircle, XCircle, AlertTriangle, ArrowRight } from "lucide-react";
import { detectors, logs } from "@/lib/mock";
import { Btn, LogRow, ModalityIcon, PageHeader, Panel } from "@/components/aegis/ui";
import { useJobPolling } from "@/hooks/useJobPolling";
import { cn } from "@/lib/utils";

const steps = [
  "Uploaded",
  "Validated",
  "Orchestrator planning",
  "Detectors running",
  "Debate & verdict (Simulated)",
  "Report ready",
];
const plan: Record<string, { start: number; end: number; skip?: string; fail?: boolean }> = {
  video: { start: 3, end: 9 },
  rppg: { start: 3, end: 12 },
  syncnet: { start: 4, end: 8 },
  aasist: { start: 4, end: 6 },
  text: { start: 0, end: 0, skip: "Model not built yet (under calibration)" },
  image: { start: 0, end: 0, skip: "Model not built yet (Phase 3 training)" },
};

function ProcessingContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const file = searchParams.get("file") || "uploaded_media.mp4";
  const preset = searchParams.get("preset");
  const initialJobId = searchParams.get("jobId");
  const [t, setT] = useState(0);
  const [targetJobId, setTargetJobId] = useState(initialJobId || preset || "AEG-1042");
  const [pollJobId, setPollJobId] = useState<string | null>(initialJobId);
  const [backendFailed, setBackendFailed] = useState<boolean>(false);
  const [backendErrorDetail, setBackendErrorDetail] = useState<string>("");
  const [statusMessage, setStatusMessage] = useState<string | null>(
    preset ? `Month 2 Milestone Demo Preset: ${preset.replace(/_/g, " ").toUpperCase()}` : null
  );

  const { status: pollStatus, job: polledJob, error: pollError } = useJobPolling(pollJobId, {
    intervalMs: 750,
    maxAttempts: 20,
  });

  useEffect(() => {
    const uploadedFile = typeof window !== "undefined" ? (window as any).__currentAnalyzeFile : null;
    if (uploadedFile) {
      setStatusMessage("Dispatching to real models (EfficientNet-B0 + MobileNetV3)...");
      const fd = new FormData();
      fd.append("file", uploadedFile);

      fetch("http://localhost:8765/analyze_video", {
        method: "POST",
        body: fd,
      })
        .then((res) => {
          if (!res.ok) throw new Error("Inference service returned HTTP " + res.status);
          return res.json();
        })
        .then((data) => {
          if (data.id) {
            setTargetJobId(data.id);
            setStatusMessage(`Inference complete — Verdict: ${(data.verdict || "unknown").toUpperCase()}`);
            setPollJobId(data.id);
            setT(14);
          }
        })
        .catch((err) => {
          console.error("Real inference backend unreachable:", err);
          setBackendFailed(true);
          setBackendErrorDetail(err.message || "Failed to reach inference server at http://localhost:8765");
          setStatusMessage("Inference failed: Backend unreachable");
        });
      return;
    }

    if (!initialJobId) {
      // Demo preset simulation
      const id = setInterval(() => setT((x) => (x >= 16 ? x : x + 1)), 700);
      return () => clearInterval(id);
    }
  }, [initialJobId]);

  useEffect(() => {
    if (!pollJobId) return;
    if (pollStatus === "complete") {
      if (polledJob?.verdict) {
        setStatusMessage(`Report verified — Verdict: ${String(polledJob.verdict).toUpperCase()}`);
      }
      setT(16);
    } else if (pollStatus === "failed" || pollStatus === "timeout" || pollStatus === "error" || pollStatus === "not_found") {
      setBackendFailed(true);
      setBackendErrorDetail(pollError || `Job verification ended with status '${pollStatus}'`);
      setStatusMessage("Inference verification failed");
    }
  }, [pollJobId, pollStatus, polledJob, pollError]);

  useEffect(() => {
    const pollingConfirmed = pollJobId ? pollStatus === "complete" : true;
    if (t >= 16 && !backendFailed && pollingConfirmed) {
      const redirectTimer = setTimeout(() => {
        router.push(`/reports/${targetJobId}`);
      }, 1500);
      return () => clearTimeout(redirectTimer);
    }
  }, [t, targetJobId, backendFailed, pollJobId, pollStatus, router]);

  const step = t < 1 ? 0 : t < 2 ? 1 : t < 3 ? 2 : t < 12 ? 3 : t < 15 ? 4 : 5;
  const done = step === 5;
  const shown = logs.filter((l) => l.job === "AEG-1042").slice().reverse().slice(0, Math.min(8, Math.max(1, Math.floor(t / 1.6))));

  if (backendFailed) {
    return (
      <div className="space-y-6 max-w-2xl mx-auto py-8">
        <PageHeader
          title="Analysis Failed"
          subtitle={`Media file: ${file}`}
        />
        <div className="rounded-2xl border border-destructive/40 bg-destructive/10 p-6 space-y-4">
          <div className="flex items-center gap-3 text-destructive">
            <XCircle className="size-6 shrink-0" />
            <h3 className="text-base font-bold text-foreground">Backend Inference Unreachable</h3>
          </div>
          <p className="text-xs text-muted-foreground font-mono bg-background/60 p-3 rounded-lg border">
            {backendErrorDetail}
          </p>
          <p className="text-sm text-muted-foreground">
            A backend failure can never pass as a real analysis result. The inference server must be running at <code>http://localhost:8765</code> or <code>http://localhost:8000</code> to generate real forensic verdicts.
          </p>
          <div className="flex flex-wrap gap-3 pt-2">
            <Btn variant="primary" onClick={() => window.location.reload()}>
              Retry analysis
            </Btn>
            <Link href="/analyze">
              <Btn variant="outline">Back to Upload</Btn>
            </Link>
            <Link href="/reports/AEG-1042">
              <Btn variant="ghost" className="text-xs text-amber-500 hover:text-amber-400">
                Inspect sample demo report [Demo data] →
              </Btn>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Analysis in progress"
        subtitle={`${file} · Job ${targetJobId} ${statusMessage ? `· ${statusMessage}` : ""}`}
        actions={
          done ? (
            <Link href={`/reports/${targetJobId}`}>
              <Btn variant="accent">
                View report <ArrowRight className="size-4" />
              </Btn>
            </Link>
          ) : (
            <Link href="/analyze">
              <Btn variant="outline">Cancel</Btn>
            </Link>
          )
        }
      />

      <Panel className="mb-6">
        <ol className="flex flex-wrap items-center gap-y-3">
          {steps.map((s, i) => (
            <li key={s} className="flex flex-1 items-center gap-2 min-w-[140px]">
              <span
                className={cn(
                  "grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold transition-soft",
                  i < step || done
                    ? "bg-authentic text-primary-foreground"
                    : i === step
                    ? "bg-accent text-accent-foreground ring-4 ring-accent/20"
                    : "bg-muted text-muted-foreground"
                )}
              >
                {i < step || done ? <Check className="size-4" /> : i + 1}
              </span>
              <span className={cn("text-sm", i <= step ? "font-medium text-primary" : "text-muted-foreground")}>{s}</span>
              {i < steps.length - 1 && <span className={cn("mx-2 h-px flex-1", i < step ? "bg-authentic" : "bg-border")} />}
            </li>
          ))}
        </ol>
      </Panel>

      <div className="grid gap-6 xl:grid-cols-[1fr_440px]">
        <div className="space-y-4">
          {t >= 10 && t < 13 && (
            <div className="flex items-start gap-3 rounded-xl border border-inconclusive/40 bg-inconclusive-soft p-4 text-sm text-inconclusive-ink">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <div className="flex-1">
                <b>rPPG signal quality is low (0.38).</b> The detector will finish, but its weight in the verdict is reduced.
              </div>
              <Link href="/developer/logs" className="shrink-0 font-semibold underline">
                Why did this happen?
              </Link>
            </div>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            {detectors.map((d) => {
              const p = plan[d.id]!;
              const state = p.skip ? "skipped" : t < p.start ? "queued" : t < p.end ? "running" : "done";
              const pct = state === "done" ? 100 : state === "running" ? ((t - p.start) / (p.end - p.start)) * 100 : 0;
              const elapsed = state === "queued" || state === "skipped" ? null : ((Math.min(t, p.end) - p.start) * 0.7).toFixed(1);
              const S = { queued: Clock, running: Loader2, done: Check, skipped: MinusCircle, failed: XCircle }[state];
              return (
                <div key={d.id} className={cn("surface p-4", state === "skipped" && "bg-muted/50")}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 font-medium text-primary">
                      <ModalityIcon m={d.modality} />
                      {d.name}
                    </div>
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 text-xs font-medium capitalize",
                        state === "done" && "text-authentic-ink",
                        state === "running" && "text-accent",
                        state === "queued" && "text-muted-foreground",
                        state === "skipped" && "text-disabled"
                      )}
                    >
                      <S className={cn("size-3.5", state === "running" && "animate-spin")} />
                      {state}
                    </span>
                  </div>
                  <p className="caption mt-1">{d.model}</p>
                  {p.skip ? (
                    <p className="mt-3 text-xs text-muted-foreground">Reason: {p.skip}</p>
                  ) : (
                    <>
                      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
                        <div
                          className={cn("h-full rounded-full transition-all duration-700", state === "done" ? "bg-authentic" : "bg-accent")}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <div className="mono mt-2 flex justify-between text-muted-foreground">
                        <span>{elapsed ? `${elapsed}s elapsed` : "waiting"}</span>
                        <span>est. {d.latency}</span>
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <Panel
          title="Live log"
          subtitle="Last events for this job"
          action={
            <Link href="/developer/logs" className="text-xs font-medium text-accent hover:underline">
              Open full logs →
            </Link>
          }
        >
          <div className="max-h-[380px] overflow-y-auto">
            {shown.map((l) => (
              <LogRow key={l.ts + l.msg} {...l} compact />
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

export default function ProcessingPage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-muted-foreground">Loading analysis state...</div>}>
      <ProcessingContent />
    </Suspense>
  );
}
