"use client";

import { DemoBadge } from "@/components/aegis/ui";

export interface FrameHeatmapProps {
  scores: number[];
  isDemo?: boolean;
}

export function FrameHeatmap({ scores, isDemo = false }: FrameHeatmapProps) {
  return (
    <div>
      <div className="mb-1 mt-4 flex items-center justify-between gap-2">
        <p className="caption">Frame suspicion (sampled temporal frames)</p>
        {isDemo && <DemoBadge />}
      </div>
      {scores.length === 0 ? (
        <div
          data-testid="frame-heat-empty"
          className="flex h-6 items-center justify-center rounded border border-dashed text-xs text-muted-foreground"
        >
          No per-frame suspicion scores available.
        </div>
      ) : (
        <div className="flex h-6 gap-px overflow-hidden rounded">
          {scores.map((h, i) => {
            const clamped = Math.max(0.08, Math.min(1, Number.isFinite(h) ? h : 0));
            return (
              <span
                key={i}
                data-testid="frame-heat-bar"
                className="flex-1 bg-synthetic"
                style={{ opacity: clamped }}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

