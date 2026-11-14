"use client";

import { Gavel, ShieldCheck } from "lucide-react";
import { Chip, Panel, SiemTierBadge } from "@/components/aegis/ui";
import {
  DEFAULT_FALLBACK_DEBATE,
  normaliseCrossExam,
  type DebateEntry,
  type FallbackDebateItem,
} from "@/lib/report";
import { cn } from "@/lib/utils";

export interface DebateLogProps {
  transcript?: DebateEntry[] | null;
  fallbackDebate?: FallbackDebateItem[];
  judgeVerdict: string;
  judgeScore: number | string;
  siemTier: string;
  justification: string;
  crossExam?: string | string[] | null;
  guards?: string[];
}

export function DebateLog({
  transcript,
  fallbackDebate = DEFAULT_FALLBACK_DEBATE,
  judgeVerdict,
  judgeScore,
  siemTier,
  justification,
  crossExam,
  guards = [],
}: DebateLogProps) {
  const crossExamList = normaliseCrossExam(crossExam);

  return (
    <Panel
      title={
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Gavel className="size-4 text-accent" />
            <span>Multi-Agent Debate &amp; Judge Reasoning</span>
          </span>
          <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-accent-soft text-accent border border-accent/30">
            MONTH 2 ADJUDICATION
          </span>
        </div>
      }
      subtitle="3-Round Cross-Modal Examination & Determinist Adjudication"
    >
      {transcript && transcript.length > 0 ? (
        <div className="space-y-3">
          {transcript.map((entry, idx) => {
            const isJudge = entry.speaker === "judge_agent";
            const isSynthetic = entry.polarity === "SYNTHETIC";
            const isAuthentic = entry.polarity === "AUTHENTIC";
            const isNA = entry.polarity === "NOT_APPLICABLE";

            return (
              <div
                key={idx}
                className={cn(
                  "rounded-xl border p-3.5 transition-all",
                  isJudge
                    ? "border-accent/40 bg-accent-soft/40 shadow-xs"
                    : isSynthetic
                    ? "border-synthetic/30 bg-synthetic-soft/30"
                    : isNA
                    ? "border-muted bg-muted/40 opacity-70"
                    : "border-border bg-card/60"
                )}
              >
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono uppercase font-bold px-1.5 py-0.2 rounded bg-muted text-muted-foreground border">
                      R{entry.round}
                    </span>
                    <span className="text-xs font-semibold capitalize text-foreground">
                      {entry.speaker.replace(/_/g, " ")}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {entry.confidence > 0 && (
                      <span className="text-[10px] font-mono text-muted-foreground">
                        conf: {(entry.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                    <span
                      className={cn(
                        "text-[10px] font-mono font-bold px-2 py-0.5 rounded uppercase tracking-wider",
                        isSynthetic
                          ? "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                          : isAuthentic
                          ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                          : "bg-muted text-muted-foreground border"
                      )}
                    >
                      {entry.polarity}
                    </span>
                  </div>
                </div>
                <p className="text-xs sm:text-sm text-foreground/90 leading-relaxed">{entry.claim}</p>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="space-y-3">
          {fallbackDebate.map((m, i) => (
            <div
              key={i}
              className={cn(
                "rounded-xl border p-3",
                m.conflict ? "border-inconclusive/50 bg-inconclusive-soft" : "bg-background/60"
              )}
            >
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-xs font-semibold text-primary">{m.who}</span>
                {m.conflict && <Chip tone="warn">Modal Conflict</Chip>}
              </div>
              <p className="text-sm">{m.text}</p>
            </div>
          ))}
        </div>
      )}

      {/* Judge Final Adjudication Box */}
      <div className="mt-4 rounded-xl border-2 border-primary bg-primary-soft p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2 pb-2 border-b border-border/40">
          <div className="flex items-center gap-2 font-bold text-primary text-sm sm:text-base">
            <Gavel className="size-4.5 text-accent" />
            <span>
              Judge Agent Adjudication: <b className="uppercase">{judgeVerdict}</b>
            </span>
            <span className="text-xs font-mono font-normal opacity-70">
              ({(Number(judgeScore) * 100).toFixed(0)}% score)
            </span>
          </div>
          <SiemTierBadge tier={siemTier} size="sm" />
        </div>

        <p className="text-sm text-foreground leading-relaxed">{justification}</p>

        {crossExamList.length > 0 && (
          <div className="mt-3 rounded-lg bg-background/80 border border-border p-2.5 text-xs text-muted-foreground">
            <span className="font-bold text-foreground block mb-0.5">Cross-Examination Synthesis:</span>
            {crossExamList.length === 1 ? (
              <span>{crossExamList[0]}</span>
            ) : (
              <ul className="list-disc pl-4 space-y-0.5">
                {crossExamList.map((finding, i) => (
                  <li key={i}>{finding}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {guards.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground">Applied Guards:</span>
            {guards.map((g, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 rounded bg-background px-2 py-0.5 text-[11px] font-mono font-medium border border-border"
              >
                <ShieldCheck className="size-3 text-emerald-500" />
                {g}
              </span>
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}

