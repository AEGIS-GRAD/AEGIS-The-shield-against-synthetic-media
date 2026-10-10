"use client";

import { useState } from "react";
import { Plus, Send } from "lucide-react";
import { toast } from "sonner";
import { Btn, Chip, Panel, Toggle } from "@/components/aegis/ui";

const initial = [
  { id: 1, url: "https://newsroom.example.com/hooks/aegis", events: ["analysis.completed", "verdict.synthetic"], on: true, last: "200 · 2m ago" },
  { id: 2, url: "https://siem.example.org/ingest/aegis", events: ["live.alert", "security.event"], on: true, last: "200 · 40s ago" },
  { id: 3, url: "https://legal.example.com/case-intake", events: ["report.flagged"], on: false, last: "500 · 3h ago" },
];
const deliveries = [
  { t: "09:44:03", ev: "live.alert", code: 200, ms: 112 },
  { t: "09:42:19", ev: "analysis.completed", code: 200, ms: 98 },
  { t: "09:42:19", ev: "verdict.synthetic", code: 200, ms: 104 },
  { t: "06:12:44", ev: "report.flagged", code: 500, ms: 3020 },
];

export default function WebhooksPage() {
  const [hooks, setHooks] = useState(initial);

  return (
    <div className="space-y-6">
      <Panel
        title="Endpoints"
        subtitle="Signed with HMAC-SHA256 (X-Aegis-Signature)"
        action={<Btn variant="accent" onClick={() => toast.success("New endpoint added")}><Plus className="size-4" />Add endpoint</Btn>}
      >
        <ul className="divide-y">
          {hooks.map((h) => (
            <li key={h.id} className="flex flex-wrap items-center gap-4 py-3">
              <Toggle checked={h.on} onChange={(v) => setHooks(hooks.map((x) => (x.id === h.id ? { ...x, on: v } : x)))} label="Enable endpoint" />
              <div className="min-w-0 flex-1">
                <p className="mono truncate text-primary">{h.url}</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {h.events.map((e) => (
                    <Chip key={e}>{e}</Chip>
                  ))}
                </div>
              </div>
              <span className="caption">Last: {h.last}</span>
              <Btn variant="outline" onClick={() => toast.success("Test event sent", { description: h.url })}>
                <Send className="size-3.5" />Test
              </Btn>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="Recent deliveries">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="caption border-b text-left">
                <th className="py-2 font-medium">Time</th>
                <th className="font-medium">Event</th>
                <th className="font-medium">Response</th>
                <th className="font-medium">Duration</th>
              </tr>
            </thead>
            <tbody>
              {deliveries.map((d, i) => (
                <tr key={i} className="border-b last:border-0">
                  <td className="mono py-2.5 text-muted-foreground">{d.t}</td>
                  <td className="mono">{d.ev}</td>
                  <td>
                    <Chip tone={d.code === 200 ? "good" : "bad"}>{d.code}</Chip>
                  </td>
                  <td className="mono">{d.ms} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
