"use client";

import { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Check, Loader2, Clock, MinusCircle, XCircle, AlertTriangle, ArrowRight } from "lucide-react";
import { detectors, logs } from "@/lib/mock";
import { Btn, LogRow, ModalityIcon, PageHeader, Panel } from "@/components/aegis/ui";
import { cn } from "@/lib/utils";

const steps = ["Uploaded", "Validated", "Orchestrator planning", "Detectors running", "Debate & verdict", "Report ready"];
const plan: Record<string, { start: number; end: number; skip?: string; fail?: boolean }> = {
  video: { start: 3, end: 9 },
  rppg: { start: 3, end: 12 },
  syncnet: { start: 4, end: 8 },
  aasist: { start: 4, end: 6 },
  text: { start: 0, end: 0, skip: "No text modality in file" },
  image: { start: 0, end: 0, skip: "Frames covered by Video Classifier" },
};

function ProcessingContent() {
  const searchParams = useSearchParams();
  const file = searchParams.get("file") || "press_briefing_0918.mp4";
  const [t, setT] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setT((x) => (x >= 16 ? x : x + 1)), 700);
    return () => clearInterval(id);
  }, []);

  const step = t < 1 ? 0 : t < 2 ? 1 : t < 3 ? 2 : t < 12 ? 3 : t < 15 ? 4 : 5;
  const done = step === 5;
  const shown = logs.filter((l) => l.job === "AEG-1042").slice().reverse().slice(0, Math.min(8, Math.max(1, Math.floor(t / 1.6))));

  return (
    <div>
      <PageHeader
        title="Analysis in progress"
        subtitle={`${file} · Job AEG-1042`}
        actions={
          done ? (
            <Link href="/reports/AEG-1042">
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
