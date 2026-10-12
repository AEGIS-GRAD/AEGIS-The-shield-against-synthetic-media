import React, { ReactNode } from "react";
import { Construction, Sparkles, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

interface ComingSoonProps {
  title?: string;
  description?: string;
  variant?: "banner" | "overlay" | "badge" | "callout";
  className?: string;
  children?: ReactNode;
  tag?: string;
}

export function ComingSoon({
  title = "Not Yet Implemented",
  description = "This feature is currently under active development. Models and pipelines are being calibrated.",
  variant = "banner",
  className,
  children,
  tag = "UNDER CONSTRUCTION",
}: ComingSoonProps) {
  if (variant === "badge") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-mono font-bold uppercase tracking-wider",
          "bg-amber-500/15 text-amber-400 border border-amber-500/30",
          className
        )}
      >
        <Construction className="size-3 text-amber-400" />
        {tag}
      </span>
    );
  }

  if (variant === "callout") {
    return (
      <div
        className={cn(
          "flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-950/20 p-3.5 text-xs text-amber-200/90 backdrop-blur-sm",
          className
        )}
      >
        <Construction className="size-4 shrink-0 text-amber-400 mt-0.5" />
        <div className="flex-1 space-y-0.5">
          <div className="font-semibold text-amber-300 flex items-center gap-2">
            <span>{title}</span>
            <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
              {tag}
            </span>
          </div>
          <p className="text-[11px] text-amber-200/80 leading-relaxed">{description}</p>
        </div>
      </div>
    );
  }

  if (variant === "overlay") {
    return (
      <div className={cn("relative overflow-hidden rounded-xl group", className)}>
        {/* Underneath content disabled */}
        <div className="pointer-events-none opacity-40 select-none filter blur-[1px] transition-all">
          {children}
        </div>
        {/* Floating badge overlay */}
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center p-4 bg-background/60 backdrop-blur-sm border border-amber-500/30 rounded-xl text-center">
          <div className="size-9 rounded-xl bg-amber-500/20 border border-amber-500/40 flex items-center justify-center mb-2.5 shadow-lg shadow-amber-500/10">
            <Construction className="size-5 text-amber-400 animate-pulse" />
          </div>
          <h4 className="text-sm font-bold text-amber-300 font-mono tracking-tight">{title}</h4>
          <p className="mt-1 max-w-sm text-xs text-muted-foreground">{description}</p>
          <span className="mt-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-mono font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30">
            {tag}
          </span>
        </div>
      </div>
    );
  }

  // Default: banner
  return (
    <div
      className={cn(
        "relative rounded-xl border border-dashed border-amber-500/40 bg-gradient-to-r from-amber-950/20 via-background to-amber-950/20 p-5",
        className
      )}
    >
      <div className="flex items-start gap-3.5">
        <div className="size-8 rounded-lg bg-amber-500/15 border border-amber-500/30 flex items-center justify-center shrink-0 mt-0.5">
          <Construction className="size-4 text-amber-400" />
        </div>
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-bold text-amber-300">{title}</h4>
            <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[9px] font-mono font-semibold uppercase text-amber-300 border border-amber-500/30">
              {tag}
            </span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground leading-relaxed">{description}</p>
        </div>
      </div>
    </div>
  );
}
export default ComingSoon;
