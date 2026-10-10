"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Activity, Percent, Timer, Radio, BellRing, AlertTriangle, CheckCircle2, Upload } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { analyses, detectors, timeline, verdictsWeek } from "@/lib/mock";
import { ConfidenceMeter, KpiTile, ModalityIcon, Panel, StatusPill, VerdictBadge, Chip } from "@/components/aegis/ui";

export default function Dashboard() {
  const router = useRouter();

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <KpiTile label="Analyses today" value="128" delta="+12%" tone="good" icon={<Activity className="size-4" />} />
        <KpiTile label="Flagged synthetic" value="18.4%" delta="+2.1 pts" tone="bad" icon={<Percent className="size-4" />} />
        <KpiTile label="Avg pipeline latency" value="7.8s" delta="−0.6s" tone="good" icon={<Timer className="size-4" />} />
        <KpiTile label="Active live feeds" value="9" delta="of 9" icon={<Radio className="size-4" />} />
        <KpiTile label="Open alerts" value="3" delta="1 critical" tone="bad" icon={<BellRing className="size-4" />} />
      </div>

      <Panel
        title="Detector health"
        subtitle="Live status of each model in the pipeline"
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
          title="Recent analyses"
          subtitle="Click a row to open its forensic report"
          action={
            <Link href="/reports" className="text-xs font-medium text-accent hover:underline">
              All reports →
            </Link>
          }
        >
          <div className="-mx-5 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="caption border-b text-left">
                  <th className="px-5 py-2 font-medium">File</th>
                  <th className="font-medium">Verdict</th>
                  <th className="w-40 font-medium">Confidence</th>
                  <th className="font-medium">Time</th>
                  <th className="px-5 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {analyses.map((a) => (
                  <tr
                    key={a.id}
                    onClick={() => router.push(`/reports/${a.id}`)}
                    className="cursor-pointer border-b transition-soft last:border-0 hover:bg-secondary/60"
                  >
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <span className="grid size-9 place-items-center rounded-lg bg-primary-soft">
                          <ModalityIcon m={a.modality} className="text-primary" />
                        </span>
                        <div>
                          <div className="font-medium text-foreground">{a.file}</div>
                          <div className="mono text-[11px] text-muted-foreground">{a.id}</div>
                        </div>
                      </div>
                    </td>
                    <td><VerdictBadge verdict={a.verdict} size="sm" /></td>
                    <td className="pr-4"><ConfidenceMeter value={a.confidence} verdict={a.verdict} /></td>
                    <td className="mono text-muted-foreground">{a.time}</td>
                    <td className="px-5"><Chip tone={a.status === "Flagged" ? "warn" : "neutral"}>{a.status}</Chip></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="Activity timeline">
          <ol className="relative space-y-4 border-l pl-5">
            {timeline.map((e) => {
              const I = e.kind === "alert" ? AlertTriangle : e.kind === "done" ? CheckCircle2 : e.kind === "upload" ? Upload : Activity;
              const tone = e.kind === "alert" ? "bg-synthetic-soft text-synthetic-ink" : e.kind === "warn" ? "bg-inconclusive-soft text-inconclusive-ink" : e.kind === "done" ? "bg-authentic-soft text-authentic-ink" : "bg-info-soft text-info-ink";
              return (
                <li key={e.t + e.text} className="relative">
                  <span className={`absolute -left-[33px] grid size-6 place-items-center rounded-full ring-4 ring-card ${tone}`}><I className="size-3.5" /></span>
                  <div className="mono text-[11px] text-muted-foreground">{e.t}</div>
                  <div className="text-sm">{e.text}</div>
                </li>
              );
            })}
          </ol>
        </Panel>
      </div>

      <Panel title="Verdicts — last 7 days" subtitle="Stacked by outcome">
        <div className="h-60">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={verdictsWeek} barSize={28}>
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
