"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Activity, Percent, Timer, Radio, BellRing, AlertTriangle, CheckCircle2, Upload, AlertCircle } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { analyses as mockAnalyses, detectors, timeline as mockTimeline, verdictsWeek as mockVerdictsWeek } from "@/lib/mock";
import { ConfidenceMeter, KpiTile, ModalityIcon, Panel, StatusPill, VerdictBadge, Chip, DemoBadge, DemoBanner, DemoSwitch } from "@/components/aegis/ui";
import { useDemoMode } from "@/lib/demoMode";

export default function Dashboard() {
  const router = useRouter();
  const [demoMode, setDemoMode] = useDemoMode();
  const [realJobs, setRealJobs] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [backendError, setBackendError] = useState<boolean>(false);

  useEffect(() => {
    setLoading(true);
    fetch("/api/jobs?demo=false")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to reach /api/jobs");
        return res.json();
      })
      .then((data) => {
        setBackendError(false);
        if (Array.isArray(data)) {
          setRealJobs(data);
        } else {
          setRealJobs([]);
        }
      })
      .catch((err) => {
        console.warn("Backend unavailable for dashboard:", err);
        setBackendError(true);
        setRealJobs([]);
      })
      .finally(() => setLoading(false));
  }, []);

  // Compute real aggregates if real jobs are available and demo mode is not forced
  const hasRealData = realJobs.length > 0 && !demoMode;
  const activeDataset = hasRealData ? realJobs : demoMode ? mockAnalyses.map(a => ({ ...a, is_demo: true })) : [];

  // Metrics computation
  const totalAnalyses = hasRealData ? realJobs.length : demoMode ? 128 : 0;
  const syntheticCount = hasRealData
    ? realJobs.filter((j) => (j.verdict || "").toLowerCase() === "synthetic").length
    : demoMode
    ? 24
    : 0;
  const syntheticRate = totalAnalyses > 0 ? ((syntheticCount / totalAnalyses) * 100).toFixed(1) + "%" : "0.0%";

  // Latency computation
  let totalLatencyMs = 0;
  let latencyCount = 0;
  if (hasRealData) {
    for (const j of realJobs) {
      const lat = j.raw_result?.raw_results?.reduce((acc: number, r: any) => acc + (r.latency_ms || 0), 0) || j.latency_ms;
      if (lat && typeof lat === "number") {
        totalLatencyMs += lat;
        latencyCount++;
      }
    }
  }
  const avgLatencyStr = hasRealData
    ? latencyCount > 0
      ? (totalLatencyMs / latencyCount / 1000).toFixed(1) + "s"
      : "1.2s"
    : demoMode
    ? "7.8s"
    : "—";

  // Critical alerts count
  const openAlertsCount = hasRealData
    ? realJobs.filter((j) => {
        const tier = (j.siem_alert_tier || "").toUpperCase();
        return tier.includes("CRITICAL") || tier.includes("TIER_3") || tier.includes("P1");
      }).length
    : demoMode
    ? 3
    : 0;

  // Real weekly bucket calculation
  const computedWeek = (() => {
    if (!hasRealData) return demoMode ? mockVerdictsWeek : [];
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const buckets: Record<string, { day: string; authentic: number; synthetic: number; inconclusive: number }> = {};
    for (const d of days) {
      buckets[d] = { day: d, authentic: 0, synthetic: 0, inconclusive: 0 };
    }
    for (const j of realJobs) {
      const d = j.timestamp ? new Date(j.timestamp) : new Date();
      const dayName = days[d.getDay()];
      const v = (j.verdict || "inconclusive").toLowerCase();
      if (v === "synthetic") buckets[dayName].synthetic++;
      else if (v === "authentic") buckets[dayName].authentic++;
      else buckets[dayName].inconclusive++;
    }
    return Object.values(buckets);
  })();

  // Real timeline calculation
  const computedTimeline = (() => {
    if (!hasRealData) return demoMode ? mockTimeline : [];
    return realJobs.slice(0, 6).map((j) => {
      const isSyn = (j.verdict || "").toLowerCase() === "synthetic";
      return {
        t: j.time || "Recently",
        kind: isSyn ? "alert" : "done",
        text: `${j.file || "Job " + j.id} adjudicated as ${j.verdict ? j.verdict.toUpperCase() : "COMPLETE"} (${Math.round((j.confidence || 0.8) * 100)}%)`,
      };
    });
  })();

  return (
    <div className="space-y-6">
      {/* Top Controls Bar with Demo Data Switch */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl border bg-card/60 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">Data Source:</span>
          {hasRealData ? (
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-authentic-soft text-authentic-ink border border-authentic/30 font-bold">
              REAL LIVE METRICS ({realJobs.length} reports)
            </span>
          ) : demoMode ? (
            <DemoBadge label="Demo data active" />
          ) : (
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-muted text-muted-foreground border">
              EMPTY LIVE STORE
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <DemoSwitch checked={demoMode} onChange={setDemoMode} label="Toggle Demo Data" />
        </div>
      </div>

      {backendError && !demoMode && (
        <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-xs text-destructive-foreground flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <AlertCircle className="size-4 shrink-0 text-destructive" />
            <span>Backend service unreachable at <code>/api/jobs</code>. Live metrics could not be loaded. Toggle <strong>Demo data</strong> above to preview with simulated fixtures.</span>
          </div>
        </div>
      )}

      {demoMode && (
        <DemoBanner
          message="Overview is displaying simulated demonstration data and mock aggregates. Toggle off above to view real forensic reports."
          onDisable={() => setDemoMode(false)}
        />
      )}

      {/* KPI Tiles */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <KpiTile
          label="Analyses recorded"
          value={totalAnalyses.toString()}
          delta={hasRealData ? "Live database" : demoMode ? "Mock baseline" : "Zero live jobs"}
          tone="good"
          icon={<Activity className="size-4" />}
        />
        <KpiTile
          label="Flagged synthetic"
          value={syntheticRate}
          delta={hasRealData ? `${syntheticCount} of ${totalAnalyses}` : demoMode ? "Demo ratio" : "0 flagged"}
          tone={syntheticCount > 0 ? "bad" : "good"}
          icon={<Percent className="size-4" />}
        />
        <KpiTile
          label="Avg pipeline latency"
          value={avgLatencyStr}
          delta={hasRealData ? "Per-detector mean" : demoMode ? "Simulated" : "No runs"}
          tone="good"
          icon={<Timer className="size-4" />}
        />
        <KpiTile
          label="Active live feeds"
          value={demoMode ? "9" : "0"}
          delta={demoMode ? "Demo cameras" : "Live feeds"}
          icon={<Radio className="size-4" />}
        />
        <KpiTile
          label="Open alerts"
          value={openAlertsCount.toString()}
          delta={openAlertsCount > 0 ? "High severity" : "No open alerts"}
          tone={openAlertsCount > 0 ? "bad" : "good"}
          icon={<BellRing className="size-4" />}
        />
      </div>

      <Panel
        title={
          <div className="flex items-center gap-2">
            <span>Detector health</span>
            {demoMode && <DemoBadge />}
          </div>
        }
        subtitle="Status of each model in the pipeline"
        action={
          <Link href="/developer/security" className="text-xs font-medium text-accent hover:underline">
            Details →
          </Link>
        }
      >
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {detectors.map((d) => (
            <div key={d.id} className="rounded-lg border bg-background/60 p-3">
              <div className="flex items-center gap-2 text-sm font-medium text-primary">
                <ModalityIcon m={d.modality} />
                {d.name}
              </div>
              <div className="mt-2 flex items-center justify-between">
                <StatusPill status={d.health} />
                <span className="mono text-muted-foreground">{d.latency}</span>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <div className="grid gap-6 xl:grid-cols-3">
        <Panel
          className="xl:col-span-2"
          title={
            <div className="flex items-center gap-2">
              <span>Recent analyses</span>
              {demoMode && <DemoBadge />}
              {hasRealData && (
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-authentic-soft text-authentic-ink border border-authentic/30 font-bold">
                  REAL LIVE JOBS
                </span>
              )}
            </div>
          }
          subtitle="Click a row to open its forensic report"
          action={
            <Link href="/reports" className="text-xs font-medium text-accent hover:underline">
              All reports →
            </Link>
          }
        >
          {activeDataset.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground border border-dashed rounded-xl">
              No live analysis reports recorded yet. Navigate to <Link href="/analyze" className="text-accent underline">Analyze</Link> to submit content.
            </div>
          ) : (
            <div className="-mx-5 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="caption border-b text-left">
                    <th className="px-5 py-2 font-medium">File</th>
                    <th className="font-medium">Verdict</th>
                    <th className="w-40 font-medium">Confidence</th>
                    <th className="font-medium">Time</th>
                    <th className="px-5 font-medium">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {activeDataset.map((a: any) => (
                    <tr
                      key={a.id}
                      onClick={() => router.push(`/reports/${a.id}`)}
                      className="cursor-pointer border-b transition-soft last:border-0 hover:bg-secondary/60"
                    >
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-3">
                          <span className="grid size-9 place-items-center rounded-lg bg-primary-soft">
                            <ModalityIcon m={a.modality || "video"} className="text-primary" />
                          </span>
                          <div>
                            <div className="font-medium text-foreground">{a.file}</div>
                            <div className="mono text-[11px] text-muted-foreground">{a.id}</div>
                          </div>
                        </div>
                      </td>
                      <td><VerdictBadge verdict={a.verdict || "inconclusive"} size="sm" /></td>
                      <td className="pr-4"><ConfidenceMeter value={a.confidence || 0.5} verdict={a.verdict || "inconclusive"} /></td>
                      <td className="mono text-muted-foreground">{a.time || "Recent"}</td>
                      <td className="px-5">
                        {a.is_demo ? (
                          <DemoBadge />
                        ) : (
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-authentic-soft text-authentic-ink border border-authentic/30 font-bold">
                            REAL
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel
          title={
            <div className="flex items-center gap-2">
              <span>Activity timeline</span>
              {demoMode && <DemoBadge />}
            </div>
          }
        >
          {computedTimeline.length === 0 ? (
            <div className="p-6 text-center text-xs text-muted-foreground">
              No recent timeline activity.
            </div>
          ) : (
            <ol className="relative space-y-4 border-l pl-5">
              {computedTimeline.map((e, idx) => {
                const I = e.kind === "alert" ? AlertTriangle : e.kind === "done" ? CheckCircle2 : e.kind === "upload" ? Upload : Activity;
                const tone = e.kind === "alert" ? "bg-synthetic-soft text-synthetic-ink" : e.kind === "warn" ? "bg-inconclusive-soft text-inconclusive-ink" : e.kind === "done" ? "bg-authentic-soft text-authentic-ink" : "bg-info-soft text-info-ink";
                return (
                  <li key={idx} className="relative">
                    <span className={`absolute -left-[33px] grid size-6 place-items-center rounded-full ring-4 ring-card ${tone}`}><I className="size-3.5" /></span>
                    <div className="mono text-[11px] text-muted-foreground">{e.t}</div>
                    <div className="text-sm">{e.text}</div>
                  </li>
                );
              })}
            </ol>
          )}
        </Panel>
      </div>

      <Panel
        title={
          <div className="flex items-center gap-2">
            <span>Verdicts — last 7 days</span>
            {demoMode && <DemoBadge />}
            {hasRealData && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-authentic-soft text-authentic-ink border border-authentic/30 font-bold">
                REAL AGGREGATES
              </span>
            )}
          </div>
        }
        subtitle="Stacked by outcome"
      >
        <div className="h-60">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={computedWeek} barSize={28}>
              <CartesianGrid vertical={false} stroke="var(--color-border)" />
              <XAxis dataKey="day" tickLine={false} axisLine={false} fontSize={12} stroke="var(--color-muted-foreground)" />
              <YAxis tickLine={false} axisLine={false} fontSize={12} stroke="var(--color-muted-foreground)" />
              <Tooltip cursor={{ fill: "var(--color-secondary)" }} contentStyle={{ borderRadius: 8, border: "1px solid var(--color-border)", fontSize: 12 }} />
              <Bar dataKey="authentic" stackId="a" fill="var(--color-authentic)" name="Authentic" />
              <Bar dataKey="inconclusive" stackId="a" fill="var(--color-inconclusive)" name="Inconclusive" />
              <Bar dataKey="synthetic" stackId="a" fill="var(--color-synthetic)" name="Synthetic" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>
    </div>
  );
}
