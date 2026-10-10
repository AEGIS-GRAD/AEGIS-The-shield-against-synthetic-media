"use client";

import { useState } from "react";
import Link from "next/link";
import { analyses, type Verdict } from "@/lib/mock";
import { Chip, ConfidenceMeter, EmptyState, ModalityIcon, PageHeader, Panel, VerdictBadge } from "@/components/aegis/ui";
import { cn } from "@/lib/utils";

export default function ReportsPage() {
  const [f, setF] = useState<Verdict | "all">("all");
  const rows = analyses.filter((a) => f === "all" || a.verdict === f);

  return (
    <div>
      <PageHeader title="Reports" subtitle="Every verdict with its full chain of evidence." />
      <div className="mb-4 flex gap-2">
        {(["all", "authentic", "synthetic", "inconclusive"] as const).map((v) => (
          <button
            key={v}
            onClick={() => setF(v)}
            className={cn("rounded-lg border px-3 py-1.5 text-sm font-medium capitalize transition-soft", f === v ? "border-accent bg-accent-soft text-accent" : "bg-card text-muted-foreground hover:text-primary")}
          >
            {v}
          </button>
        ))}
      </div>
      <Panel>
        {rows.length === 0 ? (
          <EmptyState title="No reports" text="Nothing matches this filter yet." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="caption border-b text-left">
                  <th className="py-2 font-medium">Report</th>
                  <th className="font-medium">Verdict</th>
                  <th className="w-44 font-medium">Confidence</th>
                  <th className="font-medium">Time</th>
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
