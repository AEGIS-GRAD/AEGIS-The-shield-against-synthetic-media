"use client";

import { useState } from "react";
import { Activity } from "lucide-react";
import { toast } from "sonner";
import { Btn, Chip, ConfidenceMeter, EmptyState, JsonViewer, KpiTile, LogRow, PageHeader, Panel, Skeleton, StatusPill, Toggle, VerdictBadge } from "@/components/aegis/ui";

const swatches = [
  ["Background", "bg-background"],
  ["Surface", "bg-card"],
  ["Border", "bg-border"],
  ["Navy", "bg-primary"],
  ["Terracotta", "bg-accent"],
  ["Authentic", "bg-authentic"],
  ["Synthetic", "bg-synthetic"],
  ["Inconclusive", "bg-inconclusive"],
  ["Info", "bg-info"],
  ["Teal", "bg-chart-3"],
  ["Gold", "bg-chart-4"],
  ["Plum", "bg-chart-6"],
];

export default function DesignSystemPage() {
  const [on, setOn] = useState(true);

  return (
    <div className="space-y-6">
      <PageHeader title="Design system" subtitle="Warm Sand & Navy · Inter + JetBrains Mono" />
      <Panel title="Color">
        <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
          {swatches.map(([n, c]) => (
            <div key={n}>
              <div className={`h-14 rounded-lg border ${c}`} />
              <p className="caption mt-1">{n}</p>
            </div>
          ))}
        </div>
      </Panel>
      <Panel title="Typography">
        <h1>H1 — 28 Heading</h1>
        <h2 className="mt-2">H2 — 22 Section</h2>
        <h3 className="mt-2">H3 — 18 Card title</h3>
        <p className="mt-2">Body 14 — calm, forensic, easy to scan.</p>
        <p className="caption mt-1">Caption 12 — secondary info</p>
        <p className="mono mt-1">Mono 12.5 — sha256:9f2c4e81…</p>
      </Panel>
      <div className="grid gap-6 md:grid-cols-2">
        <Panel title="Verdicts & status">
          <div className="flex flex-wrap gap-2">
            <VerdictBadge verdict="authentic" />
            <VerdictBadge verdict="synthetic" />
            <VerdictBadge verdict="inconclusive" />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <StatusPill status="healthy" />
            <StatusPill status="degraded" />
            <StatusPill status="down" />
          </div>
          <div className="mt-4 space-y-2">
            <ConfidenceMeter value={0.91} verdict="synthetic" />
            <ConfidenceMeter value={0.52} verdict="inconclusive" />
          </div>
        </Panel>
        <Panel title="Controls">
          <div className="flex flex-wrap items-center gap-2">
            <Btn>Primary</Btn>
            <Btn variant="accent">Accent</Btn>
            <Btn variant="outline">Outline</Btn>
            <Btn variant="ghost">Ghost</Btn>
            <Toggle checked={on} onChange={setOn} label="Demo" />
          </div>
          <div className="mt-4 flex flex-wrap gap-1">
            <Chip>Neutral</Chip>
            <Chip tone="good">Good</Chip>
            <Chip tone="warn">Warn</Chip>
            <Chip tone="bad">Bad</Chip>
            <Chip tone="info">Info</Chip>
          </div>
          <Btn variant="outline" className="mt-4" onClick={() => toast.success("Analysis complete", { description: "AEG-1042 — Synthetic (91%)" })}>
            Show toast
          </Btn>
        </Panel>
        <KpiTile label="KPI tile" value="128" delta="+12%" tone="good" icon={<Activity className="size-4" />} />
        <Panel title="Loading skeleton">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="mt-2 h-4 w-1/2" />
          <Skeleton className="mt-2 h-20 w-full" />
        </Panel>
        <Panel title="Log rows">
          <LogRow ts="09:42:18.204" level="INFO" svc="judge" job="AEG-1042" msg="Final verdict=SYNTHETIC" />
          <LogRow ts="09:42:16.990" level="WARN" svc="debate" job="AEG-1042" msg="Conflict raised" />
          <LogRow ts="09:21:40.551" level="ERROR" svc="rppg" job="AEG-1039" msg="TimeoutError" />
        </Panel>
        <Panel title="JSON viewer">
          <JsonViewer data={{ verdict: "SYNTHETIC", confidence: 0.91, dissent: ["rppg"], signed: true }} />
        </Panel>
      </div>
      <EmptyState title="Empty state" text="Shown when a list has nothing to display." action={<Btn variant="outline">Upload a file</Btn>} />
    </div>
  );
}
