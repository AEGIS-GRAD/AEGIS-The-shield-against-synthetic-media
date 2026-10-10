"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Download, FileJson, Link2, RotateCw, Flag, NotebookPen, ChevronDown, Gavel, Info, Hash } from "lucide-react";
import { toast } from "sonner";
import { analyses, detectors, type Verdict } from "@/lib/mock";
import { Btn, Chip, ConfidenceMeter, ModalityIcon, Panel, VerdictBadge } from "@/components/aegis/ui";
import { cn } from "@/lib/utils";

type R = { id: string; p?: number; verdict?: Verdict; conf?: number; lat?: string; claim?: string; flags?: string[]; skip?: string; detail?: React.ReactNode };
const results: R[] = [
  { id: "video", p: 0.93, verdict: "synthetic", conf: 0.92, lat: "2.4s", claim: "1,450 frames scored; blending artifacts around the jawline in 83% of frames.", flags: ["Jaw blending", "Texture smoothing", "mean p=0.93"], detail: "EfficientNet-B0, frame-level. Final score is the mean of per-frame P(synthetic); max frame p=0.99 at 00:31." },
  { id: "rppg", p: 0.44, verdict: "inconclusive", conf: 0.38, lat: "3.1s", claim: "A weak pulse signal (~61 BPM) was found, but quality is too low to trust.", flags: ["Experimental heuristic", "Low light", "Quality 0.38"], detail: "pulse" },
  { id: "syncnet", p: 0.88, verdict: "synthetic", conf: 0.81, lat: "1.8s", claim: "Lips trail the audio by 4 frames (~160 ms) during speech.", flags: ["Offset +4 frames", "AV conf 2.1"], detail: "Audio-visual offset estimated over sliding 5-frame windows. Natural speech typically shows offset ≤ 1." },
  { id: "aasist", p: 0.81, verdict: "synthetic", conf: 0.79, lat: "0.9s", claim: "Voice shows vocoder artifacts in two segments.", flags: ["12.4–15.0s", "31.2–33.9s"], detail: "AASIST-L spectro-temporal graph attention. Highest spoof score in high-frequency bands." },
  { id: "text", skip: "No text modality in this file" },
  { id: "image", skip: "Frames already covered by the Video Classifier" },
];
const heat = Array.from({ length: 64 }, (_, i) => Math.min(1, 0.25 + Math.abs(Math.sin(i / 5)) * 0.6 + (i > 38 && i < 46 ? 0.3 : 0)));
const wave = Array.from({ length: 96 }, (_, i) => 20 + Math.abs(Math.sin(i * 0.9) * Math.cos(i / 7)) * 80);
const susp = (i: number) => (i >= 24 && i < 30) || (i >= 60 && i < 67);
const ids = ["video", "rppg", "syncnet", "aasist"];
const agree = [[1, 0.2, 0.9, 0.85], [0.2, 1, 0.25, 0.3], [0.9, 0.25, 1, 0.8], [0.85, 0.3, 0.8, 1]];
const debate = [
  { who: "Video Classifier", text: "Synthetic, p=0.93. Consistent jawline blending across 83% of frames.", tone: "bad" },
  { who: "SyncNet", text: "I agree. A 4-frame lip-sync lag is typical of face reenactment.", tone: "bad" },
  { who: "AASIST", text: "Voice is likely cloned — vocoder artifacts at 12–15s and 31–34s.", tone: "bad" },
  { who: "rPPG Heartbeat", text: "I see a pulse near 61 BPM, which leans authentic (p=0.44).", tone: "warn", conflict: true },
  { who: "Video Classifier", text: "Your signal quality is 0.38 in low light. Reenactment can also preserve source skin tone changes.", tone: "bad" },
];

export default function ReportDetailPage() {
  const params = useParams();
  const id = (params?.id as string) || "AEG-1042";
  const a = analyses.find((x) => x.id === id) ?? analyses[0]!;
  const [open, setOpen] = useState<string | null>("video");
  const verdict = a.verdict;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href="/reports" className="caption hover:text-primary">
            ← Back to Reports
          </Link>
          <h1 className="mt-1">{a.file}</h1>
          <p className="mono mt-1 text-muted-foreground">{a.id} · analyzed today {a.time}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Btn variant="primary" onClick={() => toast.success("PDF report is downloading")}><Download className="size-4" />PDF report</Btn>
          <Btn variant="outline" onClick={() => toast.success("JSON exported")}><FileJson className="size-4" />Export JSON</Btn>
          <Btn variant="outline" onClick={() => toast.success("Shareable link copied")}><Link2 className="size-4" />Copy link</Btn>
          <Link href="/analyze"><Btn variant="outline"><RotateCw className="size-4" />Re-run</Btn></Link>
          <Btn variant="outline" onClick={() => toast("Flagged for review")}><Flag className="size-4" />Flag</Btn>
          <Btn variant="ghost" onClick={() => toast("Case notes opened")}><NotebookPen className="size-4" />Notes</Btn>
        </div>
      </div>

      <section className={cn("surface flex flex-wrap items-center gap-8 p-6", verdict === "synthetic" ? "bg-synthetic-soft/50" : verdict === "authentic" ? "bg-authentic-soft/50" : "bg-inconclusive-soft/50")}>
        <VerdictBadge verdict={verdict} size="lg" />
        <div className="w-56">
          <p className="caption mb-1">Overall confidence</p>
          <ConfidenceMeter value={a.confidence} verdict={verdict} />
        </div>
        <p className="min-w-[280px] flex-1 text-[15px] leading-relaxed">
          {verdict === "synthetic"
            ? "This video is very likely AI-manipulated: the face shows blending artifacts, lips are out of sync with the voice, and the voice itself appears cloned."
            : verdict === "authentic"
            ? "No signs of manipulation were found across the detectors that ran."
            : "Detectors disagree; a human reviewer should examine this file."}
        </p>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Panel title="Media evidence" subtitle="Face tracking, per-frame suspicion and audio segments">
          <div className="relative overflow-hidden rounded-lg bg-black">
            <img src="/subject.jpg" alt="Analyzed video frame" width={1280} height={720} className="aspect-video w-full object-cover" />
            <div className="absolute rounded-md border-2 border-synthetic" style={{ left: "38%", top: "10%", width: "24%", height: "52%" }}>
              <span className="mono absolute -top-6 left-0 rounded bg-synthetic px-1.5 py-0.5 text-[10px] text-primary-foreground">face_0 · p=0.93</span>
            </div>
          </div>
          <p className="caption mb-1 mt-4">Frame suspicion (00:00 → 00:48)</p>
          <div className="flex h-6 gap-px overflow-hidden rounded">
            {heat.map((h, i) => (
              <span key={i} className="flex-1 bg-synthetic" style={{ opacity: h }} />
            ))}
          </div>
          <p className="caption mb-1 mt-4">Audio waveform · suspicious segments highlighted</p>
          <div className="flex h-14 items-center gap-px">
            {wave.map((h, i) => (
              <span key={i} className={cn("flex-1 rounded-sm", susp(i) ? "bg-synthetic" : "bg-chart-1/40")} style={{ height: `${h}%` }} />
            ))}
          </div>
        </Panel>

        <Panel title="Detector agreement" subtitle="1.0 = fully agree · amber = conflict">
          <div className="grid grid-cols-[90px_repeat(4,1fr)] gap-1 text-xs">
            <span />
            {ids.map((d) => (
              <span key={d} className="caption text-center capitalize">{d}</span>
            ))}
            {agree.map((row, r) => (
              <div key={"row-" + r} className="contents">
                <span className="caption flex items-center capitalize">{ids[r]}</span>
                {row.map((v, c) => (
                  <span
                    key={r + "-" + c}
                    className={cn(
                      "mono grid aspect-square place-items-center rounded-md text-xs",
                      v < 0.4 ? "bg-inconclusive-soft text-inconclusive-ink" : "bg-primary text-primary-foreground"
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
            <div>Known limitation: rPPG is much less reliable in low light and compressed video. Its weight was reduced.</div>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {results.map((r) => {
          const d = detectors.find((x) => x.id === r.id)!;
          const isOpen = open === r.id;
          return (
            <div key={r.id} className={cn("surface p-4", r.skip && "bg-muted/50")}>
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 font-semibold text-primary">
                  <ModalityIcon m={d.modality} />
                  {d.name}
                </span>
                {r.verdict ? <VerdictBadge verdict={r.verdict} size="sm" /> : <Chip>Not run</Chip>}
              </div>
              {r.skip ? (
                <p className="caption mt-3">Reason: {r.skip}</p>
              ) : (
                <>
                  <div className="mono mt-3 grid grid-cols-3 gap-2 text-muted-foreground">
                    <span>P(syn) <b className="text-foreground">{r.p}</b></span>
                    <span>conf <b className="text-foreground">{r.conf}</b></span>
                    <span>{r.lat}</span>
                  </div>
                  <p className="mt-3 text-sm">{r.claim}</p>
                  <div className="mt-3 flex flex-wrap gap-1">
                    {r.flags!.map((f) => (
                      <Chip key={f} tone={f.includes("Experimental") ? "warn" : "neutral"}>{f}</Chip>
                    ))}
                  </div>
                  <button onClick={() => setOpen(isOpen ? null : r.id)} className="mt-3 flex items-center gap-1 text-xs font-medium text-accent">
                    Details <ChevronDown className={cn("size-3.5 transition-soft", isOpen && "rotate-180")} />
                  </button>
                  {isOpen && (
                    r.detail === "pulse" ? (
                      <div className="mt-2">
                        <svg viewBox="0 0 200 40" className="h-12 w-full">
                          <path
                            d={"M0 20 " + Array.from({ length: 40 }, (_, i) => `L${i * 5} ${20 + Math.sin(i * 1.1) * 8 + Math.cos(i * 3.3) * 5}`).join(" ")}
                            fill="none"
                            stroke="var(--color-chart-2)"
                            strokeWidth="1.5"
                          />
                        </svg>
                        <p className="caption">Estimated 61 BPM · signal quality 0.38 · experimental heuristic, not evidential on its own.</p>
                      </div>
                    ) : (
                      <p className="caption mt-2">{r.detail}</p>
                    )
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Panel title="Debate & judge reasoning">
          <div className="space-y-3">
            {debate.map((m, i) => (
              <div key={i} className={cn("rounded-xl border p-3", m.conflict ? "border-inconclusive/50 bg-inconclusive-soft" : "bg-background/60")}>
                <div className="mb-1 flex items-center gap-2 text-xs font-semibold text-primary">
                  {m.who}
                  {m.conflict && <Chip tone="warn">Conflict</Chip>}
                </div>
                <p className="text-sm">{m.text}</p>
              </div>
            ))}
            <div className="rounded-xl border-2 border-primary bg-primary-soft p-4">
              <div className="mb-1 flex items-center gap-2 font-semibold text-primary">
                <Gavel className="size-4" />Judge — final verdict: Synthetic (91%)
              </div>
              <p className="text-sm">Three independent detectors agree with strong evidence across face, lip-sync and voice. The only dissent (rPPG) is low quality and experimental, so it is down-weighted.</p>
            </div>
          </div>
        </Panel>

        <Panel title="Chain of evidence">
          <div className="mb-4 rounded-lg border bg-muted/60 p-3">
            <div className="caption mb-1 flex items-center gap-1">
              <Hash className="size-3" />SHA-256 of original file
            </div>
            <p className="mono break-all text-primary">9f2c4e81b7a0d3f6e5c2a19b8d4f7e60c3a1b2d9e8f7a6c5b4d3e2f1a0b9c8d7</p>
          </div>
          <ol className="relative space-y-3 border-l pl-5 text-sm">
            {[["09:42:03", "File received & hashed"], ["09:42:04", "Orchestrator plan: 4 detectors"], ["09:42:09", "Video Classifier: synthetic 0.93"], ["09:42:13", "AASIST: synthetic 0.81"], ["09:42:15", "SyncNet: offset +4"], ["09:42:16", "Conflict raised by rPPG"], ["09:42:18", "Judge verdict signed"]].map(([t, e]) => (
              <li key={t} className="relative">
                <span className="absolute -left-[25px] top-1.5 size-2.5 rounded-full bg-accent ring-4 ring-card" />
                <span className="mono mr-2 text-muted-foreground">{t}</span>
                {e}
              </li>
            ))}
          </ol>
        </Panel>
      </div>
    </div>
  );
}
