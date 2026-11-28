"use client";

import { cn } from "@/lib/utils";

export interface VideoTimelineProps {
    frameScores: number[];
    flaggedRange?: string | null;
    claim?: string | null;
}

/**
 * Renders a per-frame fake-probability timeline bar + the claim sentence
 * produced by the video classifier (Task 4).
 */
export function VideoTimeline({
    frameScores,
    flaggedRange,
    claim,
}: VideoTimelineProps) {
    if (!frameScores || frameScores.length === 0) return null;

    return (
        <div className="mt-4 space-y-2">
            {claim && (
                <p className="text-xs sm:text-sm text-foreground/90 leading-relaxed border-l-2 border-accent pl-3 italic">
                    {claim}
                </p>
            )}

            <div className="mb-1 flex items-center justify-between gap-2">
                <p className="caption">Per-frame fake probability (video classifier)</p>
                {flaggedRange && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-synthetic/20 text-synthetic-ink border border-synthetic/30">
                        Flagged: {flaggedRange}
                    </span>
                )}
            </div>

            {/* Timeline bar chart */}
            <div className="flex h-10 items-end gap-px overflow-hidden rounded border border-border bg-muted/30 px-1 py-1">
                {frameScores.map((score, i) => {
                    const clamped = Math.max(0, Math.min(1, isFinite(score) ? score : 0));
                    const isFlagged = clamped >= 0.65;
                    return (
                        <div
                            key={i}
                            data-testid="video-timeline-bar"
                            title={`Frame ${i}: ${(clamped * 100).toFixed(0)}%`}
                            className={cn(
                                "flex-1 rounded-sm transition-all",
                                isFlagged
                                    ? "bg-synthetic"
                                    : clamped >= 0.35
                                        ? "bg-inconclusive"
                                        : "bg-emerald-500/70"
                            )}
                            style={{ height: `${Math.max(8, clamped * 100)}%` }}
                        />
                    );
                })}
            </div>

            {/* Legend */}
            <div className="flex gap-3 text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-sm bg-synthetic" /> Fake ≥ 65%
                </span>
                <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-sm bg-inconclusive" /> Borderline 35-65%
                </span>
                <span className="flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-sm bg-emerald-500/70" /> Authentic &lt; 35%
                </span>
            </div>
        </div>
    );
}