import type { ReactNode } from "react";
import React from "react";
import {
  ShieldCheck, ShieldAlert, ShieldQuestion, Video, AudioLines, Image as ImageIcon, FileText, Inbox,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Health, Level, Modality, Verdict } from "@/lib/mock";

const verdictMap = {
  authentic: { label: "Authentic", icon: ShieldCheck, cls: "bg-authentic-soft text-authentic-ink border-authentic/30", bar: "bg-authentic" },
  synthetic: { label: "Synthetic", icon: ShieldAlert, cls: "bg-synthetic-soft text-synthetic-ink border-synthetic/30", bar: "bg-synthetic" },
  inconclusive: { label: "Inconclusive", icon: ShieldQuestion, cls: "bg-inconclusive-soft text-inconclusive-ink border-inconclusive/40", bar: "bg-inconclusive" },
};

export function VerdictBadge({ verdict, size = "md" }: { verdict: Verdict; size?: "sm" | "md" | "lg" }) {
  const v = verdictMap[verdict];
  const Icon = v.icon;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border font-semibold", v.cls,
      size === "sm" && "px-2 py-0.5 text-[11px]", size === "md" && "px-2.5 py-1 text-xs", size === "lg" && "px-4 py-2 text-lg")}>
      <Icon className={size === "lg" ? "size-6" : "size-3.5"} />
      {v.label}
    </span>
  );
}

export function ConfidenceMeter({ value, verdict, label = true }: { value: number; verdict: Verdict; label?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full transition-soft", verdictMap[verdict].bar)} style={{ width: `${value * 100}%` }} />
      </div>
      {label && <span className="mono w-10 text-right text-muted-foreground">{Math.round(value * 100)}%</span>}
    </div>
  );
}

export function StatusPill({ status, label }: { status: Health; label?: string }) {
  const m = {
    healthy: ["bg-authentic-soft text-authentic-ink", "bg-authentic", "Healthy"],
    degraded: ["bg-inconclusive-soft text-inconclusive-ink", "bg-inconclusive", "Degraded"],
    down: ["bg-synthetic-soft text-synthetic-ink", "bg-synthetic", "Down"],
  }[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium", m[0])}>
      <span className={cn("size-1.5 rounded-full", m[1], status !== "healthy" && "animate-live")} />
      {label ?? m[2]}
    </span>
  );
}

export function ModalityIcon({ m, className }: { m: Modality; className?: string }) {
  const I = { video: Video, audio: AudioLines, image: ImageIcon, text: FileText }[m];
  return <I className={cn("size-4 text-muted-foreground", className)} aria-label={m} />;
}

export function Panel({ title, subtitle, action, children, className }: {
  title?: ReactNode; subtitle?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={cn("surface p-5", className)}>
      {(title || action) && (
        <header className="mb-4 flex items-start justify-between gap-4">
          <div>
            {title && <h3 className="text-[15px]">{title}</h3>}
            {subtitle && <p className="caption mt-0.5">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function KpiTile({ label, value, delta, icon, tone = "neutral" }: {
  label: string; value: string; delta?: string; icon: ReactNode; tone?: "neutral" | "good" | "bad";
}) {
  return (
    <div className="surface flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between">
        <span className="caption font-medium">{label}</span>
        <span className="grid size-8 place-items-center rounded-lg bg-primary-soft text-primary">{icon}</span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-[26px] font-semibold tracking-tight text-primary">{value}</span>
        {delta && (
          <span className={cn("text-xs font-medium", tone === "good" && "text-authentic-ink", tone === "bad" && "text-synthetic-ink", tone === "neutral" && "text-muted-foreground")}>
            {delta}
          </span>
        )}
      </div>
    </div>
  );
}

const levelCls: Record<Level, string> = {
  DEBUG: "text-disabled",
  INFO: "text-info-ink",
  WARN: "text-inconclusive-ink",
  ERROR: "text-synthetic-ink",
};

export function LogRow({ ts, level, svc, job, msg, compact }: { ts: string; level: Level; svc: string; job?: string; msg: string; compact?: boolean }) {
  return (
    <div className={cn("mono flex gap-3 border-b border-border/60 py-1.5 last:border-0", level === "ERROR" && "bg-synthetic-soft/60")}>
      <span className="shrink-0 text-muted-foreground">{compact ? ts.slice(0, 8) : ts}</span>
      <span className={cn("w-11 shrink-0 font-semibold", levelCls[level])}>{level}</span>
      <span className="w-20 shrink-0 text-primary">{svc}</span>
      {!compact && job && <span className="w-20 shrink-0 text-accent">{job}</span>}
      <span className="min-w-0 truncate text-foreground">{msg}</span>
    </div>
  );
}

export function JsonViewer({ data }: { data: unknown }) {
  const html = JSON.stringify(data, null, 2)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?/g, (m, str, colon) => {
      if (str) return colon ? `<span class="text-primary">${str}</span>${colon}` : `<span class="text-authentic-ink">${str}</span>`;
      return `<span class="text-accent">${m}</span>`;
    });
  return (
    <pre className="mono overflow-auto rounded-lg border bg-muted/60 p-4 leading-relaxed" dangerouslySetInnerHTML={{ __html: html }} />
  );
}

export function EmptyState({ title, text, action }: { title: string; text: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed bg-muted/40 px-6 py-10 text-center">
      <span className="grid size-11 place-items-center rounded-full bg-card text-muted-foreground shadow-soft"><Inbox className="size-5" /></span>
      <p className="mt-3 font-semibold text-primary">{title}</p>
      <p className="caption mt-1 max-w-xs">{text}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Chip({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "warn" | "bad" | "good" | "info" }) {
  return (
    <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium",
      tone === "neutral" && "bg-secondary text-secondary-foreground",
      tone === "warn" && "bg-inconclusive-soft text-inconclusive-ink",
      tone === "bad" && "bg-synthetic-soft text-synthetic-ink",
      tone === "good" && "bg-authentic-soft text-authentic-ink",
      tone === "info" && "bg-info-soft text-info-ink")}>
      {children}
    </span>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="mt-1 text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Btn({ children, variant = "primary", className, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "accent" | "outline" | "ghost" }) {
  return (
    <button {...p} className={cn("inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-soft disabled:cursor-not-allowed disabled:opacity-50",
      variant === "primary" && "bg-primary text-primary-foreground hover:bg-primary/90",
      variant === "accent" && "bg-accent text-accent-foreground shadow-soft hover:bg-accent/90",
      variant === "outline" && "border bg-card text-primary hover:bg-secondary",
      variant === "ghost" && "text-primary hover:bg-secondary", className)}>
      {children}
    </button>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)}
      className={cn("relative h-5 w-9 shrink-0 rounded-full transition-soft", checked ? "bg-accent" : "bg-border")}>
      <span className={cn("absolute top-0.5 size-4 rounded-full bg-card shadow-soft transition-soft", checked ? "left-[18px]" : "left-0.5")} />
    </button>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} />;
}
