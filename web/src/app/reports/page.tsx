"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle } from "lucide-react";
import { analyses as mockAnalyses, type Verdict } from "@/lib/mock";
import { Chip, ConfidenceMeter, EmptyState, ModalityIcon, PageHeader, Panel, VerdictBadge, DemoBadge, DemoBanner, DemoSwitch } from "@/components/aegis/ui";
import { useDemoMode } from "@/lib/demoMode";
import { cn } from "@/lib/utils";

type ReportItem = {
  id: string;
  file: string;
  modality: any;
  verdict: Verdict;
  confidence: number;
  time: string;
  status: string;
  is_demo?: boolean;
};

export default function ReportsPage() {
  const [demoMode, setDemoMode] = useDemoMode();
  const [f, setF] = useState<Verdict | "all">("all");
  const [items, setItems] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [backendError, setBackendError] = useState<boolean>(false);

  useEffect(() => {
    setLoading(true);
    const query = demoMode ? "?demo=all" : "?demo=false";
    fetch(`/api/jobs${query}`)
      .then((r) => {
        if (!r.ok) throw new Error("Failed to reach /api/jobs");
        return r.json();
      })
      .then((data) => {
        setBackendError(false);
        if (Array.isArray(data)) {
          setItems(data);
        } else {
          setItems([]);
        }
      })
      .catch((err) => {
        console.warn("Backend error fetching reports:", err);
        setBackendError(true);
        if (demoMode) {
          setItems(mockAnalyses.map((a) => ({ ...a, is_demo: true })));
        } else {
          setItems([]);
        }
      })
      .finally(() => setLoading(false));
  }, [demoMode]);

  const rows = items.filter((a) => f === "all" || a.verdict === f);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reports"
        subtitle="Every verdict with its full chain of evidence."
        actions={
          <div className="flex items-center gap-3">
            <DemoSwitch checked={demoMode} onChange={setDemoMode} label="Demo data" />
          </div>
        }
      />

      {backendError && !demoMode && (
        <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-xs text-destructive-foreground flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <AlertCircle className="size-4 shrink-0 text-destructive" />
            <span>Backend service unreachable at <code>/api/jobs</code>. Live reports cannot be loaded. Toggle <strong>Demo data</strong> to preview evaluation fixtures.</span>
          </div>
          <DemoSwitch checked={demoMode} onChange={setDemoMode} />
        </div>
      )}

      {demoMode && (
        <DemoBanner
          message="Demo data active: Displaying simulated demonstration reports alongside live storage."
          onDisable={() => setDemoMode(false)}
        />
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2">
          {(["all", "authentic", "synthetic", "inconclusive"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setF(v)}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-sm font-medium capitalize transition-soft",
                f === v ? "border-accent bg-accent-soft text-accent" : "bg-card text-muted-foreground hover:text-primary"
              )}
            >
              {v}
            </button>
          ))}
        </div>
        <div className="text-xs text-muted-foreground font-mono">
          {items.filter(i => !i.is_demo).length} Real · {items.filter(i => i.is_demo).length} Demo
        </div>
      </div>

      <Panel>
        {rows.length === 0 && !loading ? (
          <EmptyState
            title={backendError && !demoMode ? "Backend offline" : "No reports found"}
            text={
              backendError && !demoMode
                ? "The reporting service is not responding. Start the backend or toggle Demo Data."
                : "Nothing matches this filter yet. Submit files in Analyze to generate live reports."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="caption border-b text-left">
                  <th className="py-2 font-medium">Report</th>
                  <th className="font-medium">Verdict</th>
                  <th className="w-44 font-medium">Confidence</th>
                  <th className="font-medium">Time</th>
                  <th className="font-medium">Type</th>
                  <th className="font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id} className="border-b last:border-0 hover:bg-secondary/60">
                    <td className="py-3">
                      <Link href={`/reports/${a.id}`} className="flex items-center gap-3">
                        <ModalityIcon m={a.modality} />
                        <div>
                          <div className="font-medium text-primary hover:text-accent">{a.file}</div>
                          <div className="mono text-[11px] text-muted-foreground">{a.id}</div>
                        </div>
                      </Link>
                    </td>
                    <td>
                      <VerdictBadge verdict={a.verdict} size="sm" />
                    </td>
                    <td className="pr-6">
                      <ConfidenceMeter value={a.confidence} verdict={a.verdict} />
                    </td>
                    <td className="mono text-muted-foreground">{a.time}</td>
                    <td>
                      {a.is_demo ? (
                        <DemoBadge />
                      ) : (
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-authentic-soft text-authentic-ink border border-authentic/30 font-bold">
                          REAL
                        </span>
                      )}
                    </td>
                    <td>
                      <Chip tone={a.status === "Flagged" ? "warn" : "neutral"}>{a.status}</Chip>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
