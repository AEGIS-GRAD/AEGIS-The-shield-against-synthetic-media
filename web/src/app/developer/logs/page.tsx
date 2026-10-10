"use client";

import { useState, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Search, X } from "lucide-react";
import { logs, type Level } from "@/lib/mock";
import { EmptyState, LogRow, Panel } from "@/components/aegis/ui";
import { cn } from "@/lib/utils";

const levels: Level[] = ["DEBUG", "INFO", "WARN", "ERROR"];

function LogsContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const job = searchParams.get("job");
  const [q, setQ] = useState("");
  const [on, setOn] = useState<Level[]>(levels);
  const rows = logs.filter((l) => (!job || l.job === job) && on.includes(l.level) && (l.msg + l.svc).toLowerCase().includes(q.toLowerCase()));

  return (
    <Panel>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-72">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter messages or service…"
            className="h-9 w-full rounded-lg border bg-background pl-9 pr-3 text-sm outline-none focus:border-accent"
          />
        </div>
        <div className="flex gap-1">
          {levels.map((l) => (
            <button
              key={l}
              onClick={() => setOn(on.includes(l) ? on.filter((x) => x !== l) : [...on, l])}
              className={cn("mono rounded-md border px-2 py-1 text-xs", on.includes(l) ? "border-primary bg-primary-soft text-primary font-medium" : "text-disabled")}
            >
              {l}
            </button>
          ))}
        </div>
        {job && (
          <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-3 py-1 text-xs font-medium text-accent">
            Job {job}
            <button aria-label="Clear job filter" onClick={() => router.push("/developer/logs")}>
              <X className="size-3.5" />
            </button>
          </span>
        )}
        <span className="caption ml-auto">{rows.length} entries</span>
      </div>
      <div className="rounded-lg border bg-background/60 px-3 py-1">
        {rows.length ? (
          rows.map((l, idx) => <LogRow key={l.ts + idx} {...l} />)
        ) : (
          <div className="py-6">
            <EmptyState title="No matching logs" text="Try widening the level filter or clearing the search." />
          </div>
        )}
      </div>
    </Panel>
  );
}

export default function LogsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-muted-foreground">Loading logs...</div>}>
      <LogsContent />
    </Suspense>
  );
}
