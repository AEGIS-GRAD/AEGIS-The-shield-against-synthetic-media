"use client";

import { useState } from "react";
import { Copy, Eye, EyeOff, Plus, RotateCw } from "lucide-react";
import { toast } from "sonner";
import { Btn, Chip, Panel } from "@/components/aegis/ui";

const keys = [
  { name: "Production Gateway", key: "aeg_live_7Hk2…f91Q", scope: "analyze, reports:read", created: "12 Aug 2026", used: "2 min ago" },
  { name: "SIEM & Telemetry Connector", key: "aeg_live_Qp81…0ZzA", scope: "live:read, security:read", created: "3 Sep 2026", used: "40 s ago" },
  { name: "Local Development & Staging", key: "aeg_test_m4Lx…88Bc", scope: "all", created: "1 Oct 2026", used: "yesterday" },
];

const sample = `curl -X POST http://localhost:8081/orchestrate \\
  -H "X-Internal-API-Key: aegis-secret-key-change-in-prod" \\
  -F "file=@press_briefing.mp4" \\
  -F "detectors=auto" -F "explain=true"`;

export default function ApiConfigPage() {
  const [shown, setShown] = useState<number | null>(null);

  return (
    <div className="space-y-6">
      <Panel title="API keys" action={<Btn variant="accent" onClick={() => toast.success("New API key generated")}><Plus className="size-4" />Create key</Btn>}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="caption border-b text-left">
                <th className="py-2 font-medium">Name</th>
                <th className="font-medium">Key</th>
                <th className="font-medium">Scopes</th>
                <th className="font-medium">Last used</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {keys.map((k, i) => (
                <tr key={k.name} className="border-b last:border-0">
                  <td className="py-3 font-medium">
                    {k.name}
                    <div className="caption">Created {k.created}</div>
                  </td>
                  <td className="mono">{shown === i ? k.key.replace("…", "x3Rt9WvB") : k.key}</td>
                  <td><Chip>{k.scope}</Chip></td>
                  <td className="text-muted-foreground">{k.used}</td>
                  <td className="text-right">
                    <button className="rounded p-1.5 hover:bg-secondary" aria-label="Show key" onClick={() => setShown(shown === i ? null : i)}>
                      {shown === i ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                    </button>
                    <button className="rounded p-1.5 hover:bg-secondary" aria-label="Copy key" onClick={() => toast.success("Key copied")}>
                      <Copy className="size-4" />
                    </button>
                    <button className="rounded p-1.5 hover:bg-secondary" aria-label="Rotate key" onClick={() => toast("Key rotated", { description: k.name })}>
                      <RotateCw className="size-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Limits & endpoint">
          <dl className="grid grid-cols-2 gap-4 text-sm">
            {[["Base URL", "http://localhost:8081"], ["Rate limit", "120 req / min"], ["Max upload", "100 MB"], ["Timeout", "60 s"], ["Default detectors", "auto"], ["Webhook retries", "5 (exp. backoff)"]].map(([k, v]) => (
              <div key={k}><dt className="caption">{k}</dt><dd className="mono mt-0.5">{v}</dd></div>
            ))}
          </dl>
        </Panel>
        <Panel title="Quick start">
          <pre className="mono overflow-auto rounded-lg border bg-muted/60 p-4 leading-relaxed text-xs">{sample}</pre>
        </Panel>
      </div>
    </div>
  );
}
