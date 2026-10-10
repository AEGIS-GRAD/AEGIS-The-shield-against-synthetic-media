"use client";

import { useEffect, useState } from "react";
import { Grid2x2, Grid3x3, Square, CheckCircle2, AlertTriangle, Fingerprint, Clock, Film, Network } from "lucide-react";
import { CartesianGrid, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { cameras } from "@/lib/mock";
import { Chip, ConfidenceMeter, PageHeader, Panel } from "@/components/aegis/ui";
import { cn } from "@/lib/utils";

type Cam = (typeof cameras)[number];
const ring = { verified: "ring-authentic", analyzing: "ring-inconclusive", suspect: "ring-synthetic" } as const;
const statusLabel = { verified: "Verified", analyzing: "Analyzing", suspect: "Suspected manipulation" } as const;
const verdictOf = { verified: "authentic", analyzing: "inconclusive", suspect: "synthetic" } as const;
const positions = ["50% 50%", "20% 40%", "80% 30%", "40% 80%", "65% 60%", "10% 10%", "90% 90%", "30% 20%", "70% 75%"];
const anomalies = [
  { i: 14, label: "Frame injection" },
  { i: 22, label: "Replayed footage" },
  { i: 31, label: "Timestamp mismatch" },
];

export default function LivePage() {
  const [grid, setGrid] = useState<1 | 4 | 9>(9);
  const [sel, setSel] = useState<Cam>(cameras[6]!);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1500);
    return () => clearInterval(id);
  }, []);

  const shown = grid === 1 ? [sel] : cameras.slice(0, grid);
  const suspect = sel.status === "suspect";
  const series = Array.from({ length: 40 }, (_, i) => {
    const base = suspect ? (i > 12 ? 0.35 : 0.9) : sel.conf;
    return {
      i,
      t: `-${40 - i}s`,
      v: Math.max(0.05, Math.min(1, base + Math.sin((i + tick) / 2) * 0.06 - (suspect && anomalies.some((a) => a.i === i) ? 0.2 : 0))),
    };
  });

  return (
    <div>
      <PageHeader
        title="Live Surveillance"
        subtitle="9 feeds · sliding 4-second analysis window"
        actions={
          <div className="flex rounded-lg border bg-card p-0.5">
            {([[1, Square], [4, Grid2x2], [9, Grid3x3]] as const).map(([n, I]) => (
              <button
                key={n}
                onClick={() => setGrid(n)}
                aria-label={`${n} feeds`}
                className={cn("rounded-md p-2 transition-soft", grid === n ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary")}
              >
                <I className="size-4" />
              </button>
            ))}
          </div>
        }
      />

      <div className={cn("grid gap-4", grid === 1 ? "grid-cols-1" : grid === 4 ? "md:grid-cols-2" : "md:grid-cols-3")}>
        {shown.map((c, idx) => (
          <button
            key={c.id}
            onClick={() => setSel(c)}
            className={cn("group relative overflow-hidden rounded-xl text-left ring-[3px] ring-offset-2 ring-offset-background transition-soft", ring[c.status], sel.id === c.id && "shadow-lift")}
          >
            <img
              src="/cctv.jpg"
              alt={`${c.name} feed`}
              width={1280}
              height={720}
              className={cn("aspect-video w-full object-cover", c.status === "suspect" && "hue-rotate-15 saturate-150")}
              style={{ objectPosition: positions[cameras.indexOf(c)] ?? positions[idx], transform: "scale(1.4)" }}
            />
            <div className="absolute inset-0 bg-gradient-to-t from-primary/80 via-transparent to-primary/30" />
            {c.status === "analyzing" && (
              <div className="pointer-events-none absolute inset-x-0 h-1/3 bg-gradient-to-b from-transparent via-inconclusive/20 to-transparent animate-scan" />
            )}
            <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-md bg-synthetic px-1.5 py-0.5 text-[10px] font-bold text-primary-foreground">
              <span className="size-1.5 rounded-full bg-primary-foreground animate-live" />LIVE
            </div>
            <div className="mono absolute right-3 top-3 flex gap-1 text-[10px]">
              <span className="rounded bg-card/90 px-1.5 py-0.5 text-primary">{c.lat}ms</span>
              <span className="rounded bg-card/90 px-1.5 py-0.5 text-primary">{c.fps}fps</span>
            </div>
            <div className="absolute inset-x-3 bottom-3 flex items-end justify-between text-primary-foreground">
              <div>
                <div className="text-sm font-semibold">{c.name}</div>
                <div className="text-[11px] opacity-80">{c.id} · {c.loc}</div>
              </div>
              <div className="text-right">
                <div className="text-[11px] opacity-80">{statusLabel[c.status]}</div>
                <div className="mono font-semibold">{Math.round(c.conf * 100)}%</div>
              </div>
            </div>
          </button>
        ))}
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[1fr_360px]">
        <Panel
          title={
            <span className="flex items-center gap-2">
              {sel.name} <Chip tone={suspect ? "bad" : sel.status === "analyzing" ? "warn" : "good"}>{statusLabel[sel.status]}</Chip>
            </span>
          }
          subtitle={`${sel.id} · ${sel.loc} · authenticity over time`}
        >
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series}>
                <CartesianGrid vertical={false} stroke="var(--color-border)" />
                <XAxis dataKey="t" fontSize={11} tickLine={false} axisLine={false} stroke="var(--color-muted-foreground)" interval={7} />
                <YAxis domain={[0, 1]} fontSize={11} tickLine={false} axisLine={false} stroke="var(--color-muted-foreground)" tickFormatter={(v) => `${Math.round(v * 100)}%`} />
                <Tooltip formatter={(v: number) => `${Math.round(v * 100)}%`} contentStyle={{ borderRadius: 8, border: "1px solid var(--color-border)", fontSize: 12 }} />
                <ReferenceLine y={0.5} stroke="var(--color-inconclusive)" strokeDasharray="4 4" />
                <Line dataKey="v" name="Authenticity" stroke="var(--color-chart-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
                {suspect && anomalies.map((a) => (
                  <ReferenceDot key={a.i} x={series[a.i]!.t} y={series[a.i]!.v} r={6} fill="var(--color-synthetic)" stroke="var(--color-card)" strokeWidth={2} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
          {suspect && (
            <div className="mt-3 flex flex-wrap gap-2">
              {anomalies.map((a) => (
                <Chip key={a.i} tone="bad">
                  <AlertTriangle className="mr-1 size-3" />{a.label} · {series[a.i]!.t}
                </Chip>
              ))}
              <Chip tone="bad">Synthetic face replacement</Chip>
            </div>
          )}
          <div className="mt-5 grid gap-3 md:grid-cols-2">
            {[["Video Classifier", suspect ? 0.21 : 0.95], ["SyncNet", suspect ? 0.34 : 0.9], ["Frame continuity", suspect ? 0.18 : 0.97], ["Replay detector", suspect ? 0.29 : 0.96]].map(([n, v]) => (
              <div key={n as string} className="rounded-lg border p-3">
                <div className="mb-2 flex justify-between text-sm">
                  <span>{n}</span>
                  <span className="caption">authenticity</span>
                </div>
                <ConfidenceMeter value={v as number} verdict={verdictOf[(v as number) > 0.7 ? "verified" : (v as number) > 0.45 ? "analyzing" : "suspect"]} />
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Feed integrity" subtitle="Transport & provenance checks">
          <ul className="space-y-4 text-sm">
            {[
              [Fingerprint, "Stream signature", suspect ? "Mismatch at 09:44:02" : "Valid (Ed25519)", !suspect],
              [Clock, "Timestamp drift", suspect ? "+2.8 s vs NTP" : "+12 ms", !suspect],
              [Film, "Frame continuity", suspect ? "37 frames duplicated" : "No gaps", !suspect],
              [Network, "Network path", "3 hops · TLS 1.3", true],
              [CheckCircle2, "Encoder fingerprint", "Matches CAM registry", true],
            ].map(([I, k, v, ok]) => {
              const Icon = I as typeof Clock;
              return (
                <li key={k as string} className="flex items-start gap-3">
                  <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", ok ? "bg-authentic-soft text-authentic-ink" : "bg-synthetic-soft text-synthetic-ink")}>
                    <Icon className="size-4" />
                  </span>
                  <div>
                    <div className="font-medium">{k as string}</div>
                    <div className="caption">{v as string}</div>
                  </div>
                </li>
              );
            })}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
