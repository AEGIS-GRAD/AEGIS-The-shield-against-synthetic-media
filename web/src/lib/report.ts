import type { Verdict } from "@/lib/mock";

export interface DebateEntry {
  round: number;
  speaker: string;
  polarity: string;
  confidence: number;
  claim: string;
}

export interface FallbackDebateItem {
  who: string;
  text: string;
  tone?: string;
  conflict?: boolean;
}

export type HashChainEvent = [time: string, description: string, colorClass?: string];

export const DEFAULT_FRAME_HEAT: number[] = Array.from({ length: 64 }, (_, i) =>
  Math.min(1, 0.25 + Math.abs(Math.sin(i / 5)) * 0.6 + (i > 38 && i < 46 ? 0.3 : 0))
);

export const DEFAULT_AUDIO_WAVE: number[] = Array.from(
  { length: 96 },
  (_, i) => 20 + Math.abs(Math.sin(i * 0.9) * Math.cos(i / 7)) * 80
);

export const DEFAULT_AGREEMENT_IDS = ["video", "rppg", "syncnet", "aasist"];

export const DEFAULT_AGREEMENT_MATRIX: number[][] = [
  [1, 0.2, 0.9, 0.85],
  [0.2, 1, 0.25, 0.3],
  [0.9, 0.25, 1, 0.8],
  [0.85, 0.3, 0.8, 1],
];

export const DEFAULT_FALLBACK_DEBATE: FallbackDebateItem[] = [
  { who: "Video Classifier", text: "Synthetic, p=0.93. Consistent jawline blending across 83% of frames.", tone: "bad" },
  { who: "SyncNet", text: "I agree. A 4-frame lip-sync lag is typical of face reenactment.", tone: "bad" },
  { who: "AASIST", text: "Voice is likely cloned — vocoder artifacts at 12–15s and 31–34s.", tone: "bad" },
  { who: "rPPG Heartbeat", text: "I see a pulse near 61 BPM, which leans authentic (p=0.44).", tone: "warn", conflict: true },
  { who: "Video Classifier", text: "Your signal quality is 0.38 in low light. Reenactment can also preserve source skin tone changes.", tone: "bad" },
];

export function buildPulsePath(signal?: number[]): string {
  if (signal && signal.length >= 2) {
    const stepX = 200 / Math.max(1, signal.length - 1);
    const min = Math.min(...signal);
    const max = Math.max(...signal);
    const span = max - min || 1;
    return signal
      .map((val, idx) => {
        const x = Number((idx * stepX).toFixed(2));
        const normalized = (val - min) / span;
        const y = Number((32 - normalized * 24).toFixed(2));
        return `${idx === 0 ? "M" : "L"}${x} ${y}`;
      })
      .join(" ");
  }

  return (
    "M0 20 " +
    Array.from(
      { length: 40 },
      (_, i) => `L${i * 5} ${20 + Math.sin(i * 1.1) * 8 + Math.cos(i * 3.3) * 5}`
    ).join(" ")
  );
}

export function verdictFromConfidence(confidence: number): Verdict {
  if (confidence <= 0.35) return "authentic";
  if (confidence >= 0.65) return "synthetic";
  return "inconclusive";
}

export function agreementFromScores(ids: string[], scores: Record<string, number>): number[][] {
  return ids.map((rowId, rIdx) =>
    ids.map((colId, cIdx) => {
      if (rIdx === cIdx) return 1;
      const a = typeof scores[rowId] === "number" ? scores[rowId] : 0.5;
      const b = typeof scores[colId] === "number" ? scores[colId] : 0.5;
      return Number(Math.max(0, Math.min(1, 1 - Math.abs(a - b))).toFixed(2));
    })
  );
}

export function normaliseCrossExam(findings: string | string[] | null | undefined): string[] {
  if (!findings) return [];
  if (Array.isArray(findings)) {
    return findings.map((item) => String(item).trim()).filter(Boolean);
  }
  const trimmed = String(findings).trim();
  return trimmed ? [trimmed] : [];
}

