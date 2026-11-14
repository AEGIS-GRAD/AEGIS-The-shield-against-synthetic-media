"use client";

import { buildPulsePath } from "@/lib/report";

export interface PulseWaveProps {
  bpm?: number;
  signal?: number[];
}

export function PulseWave({ bpm = 74, signal }: PulseWaveProps) {
  const pathD = buildPulsePath(signal);

  return (
    <div className="mt-2">
      <svg viewBox="0 0 200 40" className="h-12 w-full" aria-label="rPPG pulse waveform">
        <path
          d={pathD}
          fill="none"
          stroke="var(--color-chart-2)"
          strokeWidth="1.5"
        />
      </svg>
      <p className="caption">Estimated {bpm} BPM · forehead chrominance pulse buffer.</p>
    </div>
  );
}

