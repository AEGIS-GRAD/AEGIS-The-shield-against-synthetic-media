"use client";

import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { detectors, reportJson } from "@/lib/mock";
import { JsonViewer, Panel, StatusPill } from "@/components/aegis/ui";

const series = Array.from({ length: 30 }, (_, i) => ({
  t: `${9 + Math.floor(i / 6)}:${String((i % 6) * 10).padStart(2, "0")}`,
  video: 2.2 + Math.sin(i / 4) * 0.3,
  rppg: 3 + Math.abs(Math.sin(i / 3)) * (i > 18 ? 3 : 1),
  syncnet: 1.7 + Math.cos(i / 5) * 0.2,
  aasist: 0.9 + Math.sin(i) * 0.1,
}));
const colors = ["var(--color-chart-1)", "var(--color-chart-2)", "var(--color-chart-3)", "var(--color-chart-4)"];

export default function TelemetryPage() {
  return (
    <div className="space-y-6">
      <Panel title="Detector p95 latency (s)" subtitle="Last 5 hours">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series}>
              <CartesianGrid vertical={false} stroke="var(--color-border)" />
              <XAxis dataKey="t" fontSize={11} tickLine={false} axisLine={false} stroke="var(--color-muted-foreground)" interval={4} />
              <YAxis fontSize={11} tickLine={false} axisLine={false} stroke="var(--color-muted-foreground)" />
              <Tooltip formatter={(v: number) => v.toFixed(2) + "s"} contentStyle={{ borderRadius: 8, border: "1px solid var(--color-border)", fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {["video", "rppg", "syncnet", "aasist"].map((k, i) => (
                <Line key={k} dataKey={k} stroke={colors[i]} strokeWidth={2} dot={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Panel>
      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Model inventory">
          <table className="w-full text-sm">
            <thead>
              <tr className="caption border-b text-left">
                <th className="py-2 font-medium">Detector</th>
                <th className="font-medium">Model</th>
                <th className="font-medium">Avg</th>
                <th className="font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {detectors.map((d) => (
                <tr key={d.id} className="border-b last:border-0">
                  <td className="py-2.5 font-medium">{d.name}</td>
                  <td className="mono text-muted-foreground">{d.model}</td>
                  <td className="mono">{d.latency}</td>
                  <td><StatusPill status={d.health} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Raw response" subtitle="Job AEG-1042 · judge output">
          <JsonViewer data={reportJson} />
        </Panel>
      </div>
    </div>
  );
}
