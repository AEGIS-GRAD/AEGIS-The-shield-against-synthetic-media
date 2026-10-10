"use client";

import { ShieldAlert, Lock, UserX, Fingerprint } from "lucide-react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Chip, KpiTile, Panel, StatusPill } from "@/components/aegis/ui";

const traffic = Array.from({ length: 24 }, (_, i) => ({
  h: `${i}:00`,
  ok: 200 + Math.round(Math.sin(i / 3) * 80 + i * 6),
  blocked: Math.round(10 + Math.abs(Math.cos(i)) * 30 + (i === 14 ? 90 : 0)),
}));

const events = [
  { t: "09:44:02", sev: "high", src: "203.0.113.42", rule: "Live feed signature mismatch — CAM-07", act: "Alerted" },
  { t: "09:31:17", sev: "med", src: "198.51.100.7", rule: "API key brute force (14 attempts)", act: "Blocked" },
  { t: "09:12:50", sev: "low", src: "10.0.4.22", rule: "Upload exceeded size limit", act: "Rejected" },
  { t: "08:58:09", sev: "med", src: "192.0.2.15", rule: "Adversarial perturbation pattern in upload", act: "Quarantined" },
  { t: "08:20:33", sev: "low", src: "10.0.4.9", rule: "Admin login from new device", act: "MFA challenged" },
];

export default function SecurityPage() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiTile label="SIEM alerts (24h)" value="27" delta="3 high" tone="bad" icon={<ShieldAlert className="size-4" />} />
        <KpiTile label="Blocked requests" value="1,284" delta="−8%" tone="good" icon={<Lock className="size-4" />} />
        <KpiTile label="Failed logins" value="41" delta="+12" tone="bad" icon={<UserX className="size-4" />} />
        <KpiTile label="Integrity checks passed" value="99.7%" icon={<Fingerprint className="size-4" />} />
      </div>
      <div className="grid gap-6 xl:grid-cols-3">
        <Panel className="xl:col-span-2" title="Request traffic" subtitle="Grafana · allowed vs blocked, last 24h">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={traffic}>
                <CartesianGrid vertical={false} stroke="var(--color-border)" />
                <XAxis dataKey="h" fontSize={11} tickLine={false} axisLine={false} stroke="var(--color-muted-foreground)" interval={3} />
                <YAxis fontSize={11} tickLine={false} axisLine={false} stroke="var(--color-muted-foreground)" />
                <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid var(--color-border)", fontSize: 12 }} />
                <Area dataKey="ok" name="Allowed" stroke="var(--color-chart-1)" fill="var(--color-chart-1)" fillOpacity={0.12} />
                <Area dataKey="blocked" name="Blocked" stroke="var(--color-chart-2)" fill="var(--color-chart-2)" fillOpacity={0.2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel title="Service status">
          <ul className="space-y-3 text-sm">
            {[["API gateway", "healthy"], ["Auth service", "healthy"], ["Evidence vault", "healthy"], ["SIEM forwarder", "degraded"], ["Grafana", "healthy"], ["Model registry", "healthy"]].map(([n, s]) => (
              <li key={n} className="flex items-center justify-between">
                <span>{n}</span>
                <StatusPill status={s as "healthy"} />
              </li>
            ))}
          </ul>
        </Panel>
      </div>
      <Panel title="SIEM event feed" subtitle="Correlated security events">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="caption border-b text-left">
                <th className="py-2 font-medium">Time</th>
                <th className="font-medium">Severity</th>
                <th className="font-medium">Source</th>
                <th className="font-medium">Rule</th>
                <th className="font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.t} className="border-b last:border-0">
                  <td className="mono py-3 text-muted-foreground">{e.t}</td>
                  <td>
                    <Chip tone={e.sev === "high" ? "bad" : e.sev === "med" ? "warn" : "info"}>
                      {e.sev.toUpperCase()}
                    </Chip>
                  </td>
                  <td className="mono">{e.src}</td>
                  <td>{e.rule}</td>
                  <td className="text-muted-foreground">{e.act}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
