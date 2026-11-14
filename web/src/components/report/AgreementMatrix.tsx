"use client";

import { Info } from "lucide-react";
import { Panel } from "@/components/aegis/ui";
import { cn } from "@/lib/utils";

export interface AgreementMatrixProps {
  ids: string[];
  matrix: number[][];
  conflictThreshold?: number;
}

export function AgreementMatrix({
  ids,
  matrix,
  conflictThreshold = 0.4,
}: AgreementMatrixProps) {
  return (
    <Panel title="Detector agreement" subtitle="1.0 = fully agree · amber = conflict">
      <div
        className={cn("grid gap-1 text-xs", ids.length === 4 && "grid-cols-[90px_repeat(4,1fr)]")}
        style={ids.length !== 4 ? { gridTemplateColumns: `90px repeat(${ids.length}, 1fr)` } : undefined}
      >
        <span />
        {ids.map((d) => (
          <span key={d} className="caption text-center capitalize">
            {d}
          </span>
        ))}
        {matrix.map((row, r) => (
          <div key={"row-" + r} className="contents">
            <span className="caption flex items-center capitalize">{ids[r]}</span>
            {row.map((v, c) => (
              <span
                key={r + "-" + c}
                data-testid={`agreement-cell-${r}-${c}`}
                className={cn(
                  "mono grid aspect-square place-items-center rounded-md text-xs",
                  v < conflictThreshold
                    ? "bg-inconclusive-soft text-inconclusive-ink"
                    : "bg-primary text-primary-foreground"
                )}
              >
                {v.toFixed(2)}
              </span>
            ))}
          </div>
        ))}
      </div>
      <div className="mt-5 rounded-lg border border-inconclusive/40 bg-inconclusive-soft p-3 text-sm text-inconclusive-ink flex items-start gap-2">
        <Info className="mt-0.5 size-4 shrink-0" />
        <div>
          Known limitation: rPPG is much less reliable in low light and compressed video. Its weight was reduced.
        </div>
      </div>
    </Panel>
  );
}

