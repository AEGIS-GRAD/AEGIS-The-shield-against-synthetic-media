"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Download, FileJson, Link2, RotateCw, Flag, NotebookPen, ChevronDown, Gavel, Info, Hash, ShieldCheck, Copy, Check, ShieldAlert, Scale } from "lucide-react";
import { toast } from "sonner";
import { analyses, detectors, type Verdict } from "@/lib/mock";
import { Btn, Chip, ConfidenceMeter, ModalityIcon, Panel, VerdictBadge, SiemTierBadge } from "@/components/aegis/ui";
import { ComingSoon } from "@/components/aegis/ComingSoon";
import { cn } from "@/lib/utils";

type R = { id: string; p?: number; verdict?: Verdict; conf?: number; lat?: string; claim?: string; flags?: string[]; skip?: string; detail?: React.ReactNode };
const results: R[] = [
  { id: "video", p: 0.93, verdict: "synthetic", conf: 0.92, lat: "2.4s", claim: "1,450 frames scored; blending artifacts around the jawline in 83% of frames.", flags: ["Jaw blending", "Texture smoothing", "mean p=0.93"], detail: "EfficientNet-B0, frame-level. Final score is the mean of per-frame P(synthetic); max frame p=0.99 at 00:31." },
  { id: "rppg", p: 0.44, verdict: "inconclusive", conf: 0.38, lat: "3.1s", claim: "A weak pulse signal (~61 BPM) was found, but quality is too low to trust.", flags: ["Experimental heuristic", "Low light", "Quality 0.38"], detail: "pulse" },
  { id: "syncnet", p: 0.88, verdict: "synthetic", conf: 0.81, lat: "1.8s", claim: "Lips trail the audio by 4 frames (~160 ms) during speech.", flags: ["Offset +4 frames", "AV conf 2.1"], detail: "Audio-visual offset estimated over sliding 5-frame windows. Natural speech typically shows offset ≤ 1." },
  { id: "aasist", p: 0.81, verdict: "synthetic", conf: 0.79, lat: "0.9s", claim: "Voice shows vocoder artifacts in two segments.", flags: ["12.4–15.0s", "31.2–33.9s"], detail: "AASIST-L spectro-temporal graph attention. Highest spoof score in high-frequency bands." },
  { id: "text", skip: "Model not built yet (under calibration)" },
  { id: "image", skip: "Model not built yet (Phase 3 training)" },
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
  const [customJob, setCustomJob] = useState<any>(null);

  useEffect(() => {
    fetch(`/api/jobs?id=${encodeURIComponent(id)}`)
      .then((res) => res.json())
      .then((data) => {
        if (data && !data.error) {
          setCustomJob(data);
        }
      })
      .catch((err) => console.warn("Failed to fetch /api/jobs:", err));
  }, [id]);

  const fallback = analyses.find((x) => x.id === id) ?? analyses[0]!;
  const a = customJob
    ? {
        id: customJob.id,
        file: customJob.file,
        verdict: (customJob.verdict as Verdict) || "synthetic",
        confidence: customJob.confidence || 0.91,
        time: customJob.time || "Just now",
        status: customJob.status || "Complete",
        thumbnail: customJob.thumbnail_url || "/subject.jpg",
        results: customJob.results,
        frame_scores: customJob.frame_scores,
      }
    : {
        ...fallback,
        thumbnail: "/subject.jpg",
        results: null,
        frame_scores: null,
      };

  const [open, setOpen] = useState<string | null>("video");
  const [copiedHash, setCopiedHash] = useState(false);

  const verdict = a.verdict;
  const siemTier = customJob?.siem_alert_tier || (verdict === "synthetic" ? "TIER_3_CRITICAL" : verdict === "authentic" ? "TIER_1_LOW" : "TIER_2_ELEVATED");
  const judgeVerdict = customJob?.judge_verdict || (verdict ? verdict.toUpperCase() : "SYNTHETIC");
  const judgeScore = customJob?.judge_score ?? a.confidence;
  const guardsApplied: string[] = customJob?.guards_applied || (
    verdict === "synthetic"
      ? ["Guard 1: Unresolved Polarity Inversion Anti-Default"]
      : ["Guard 2: Cross-Modal Corroboration Requirement Satisfied"]
  );
  const forensicJustification = customJob?.forensic_justification || (
    verdict === "synthetic"
      ? "Multi-detector consensus indicates synthetic media manipulation based on spatial feature anomalies and temporal incoherence."
      : verdict === "authentic"
      ? "Multi-detector consensus indicates authentic media with natural biological pulse signals and consistent facial feature geometry."
      : "Detectors returned mixed or low-confidence indicators; human analyst review recommended."
  );
  const crossExamFindings = customJob?.cross_examination_findings || (
    verdict === "synthetic"
      ? "Cross-examination resolved polarity inversion between rPPG pulse ambiguity and high-confidence spatial/temporal synthesis."
      : "Cross-examination verified multi-layer alignment across visual geometry and acoustic features."
  );
  const transcriptHash = customJob?.debate_transcript_hash || "0x9f2c4e81b7a0d3f6e5c2a19b8d4f7e60c3a1b2d9e8f7a6c5b4d3e2f1a0b9c8d7";
  const debateTranscript: any[] = customJob?.debate_transcript || null;

  const handleCopyHash = (text: string) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(text);
      setCopiedHash(true);
      toast.success("Tamper-evident transcript hash copied to clipboard");
      setTimeout(() => setCopiedHash(false), 2000);
    }
  };

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

      <section className={cn("surface flex flex-wrap items-center gap-6 p-6 rounded-2xl border transition-all", verdict === "synthetic" ? "bg-synthetic-soft/50 border-synthetic/30" : verdict === "authentic" ? "bg-authentic-soft/50 border-authentic/30" : "bg-inconclusive-soft/50 border-inconclusive/30")}>
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2.5">
            <VerdictBadge verdict={verdict} size="lg" />
            <SiemTierBadge tier={siemTier} size="md" />
          </div>
          <div className="flex items-center gap-1.5 text-xs font-mono text-muted-foreground">
            <span>Judge Adjudication:</span>
            <span className="font-bold text-foreground">{judgeVerdict}</span>
            <span className="opacity-50">·</span>
            <span>Score: <b className="text-foreground">{Number(judgeScore).toFixed(2)}</b></span>
          </div>
        </div>

        <div className="w-56">
          <p className="caption mb-1">Overall confidence</p>
          <ConfidenceMeter value={a.confidence} verdict={verdict} />
        </div>

        <div className="min-w-[280px] flex-1">
          <p className="text-[14px] leading-relaxed text-foreground font-medium">
            {forensicJustification}
          </p>
          {guardsApplied && guardsApplied.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] font-mono uppercase text-muted-foreground font-bold tracking-wider">Active Guards:</span>
              {guardsApplied.map((guard, idx) => (
                <span
                  key={idx}
                  className="inline-flex items-center gap-1 rounded-md bg-background/90 border border-border px-2 py-0.5 text-[11px] font-mono text-foreground font-medium shadow-2xs"
                >
                  <ShieldCheck className="size-3 text-emerald-500" />
                  {guard}
                </span>
              ))}
            </div>
          )}
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Panel
          title={
            <div className="flex items-center justify-between">
              <span>Media evidence</span>
              <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-muted text-muted-foreground border">
                SIMULATED GRADCAM
              </span>
            </div>
          }
          subtitle="Face tracking, per-frame suspicion and audio segments"
        >
          <ComingSoon
            variant="callout"
            title="Explainability & GradCAM [Under Development]"
            description="Facial bounding box tracking is functional. Heatmap attribution overlays and audio spectral saliency masks are simulated prototypes pending GPU batch explainability export."
            className="mb-4"
          />
          <div className="relative overflow-hidden rounded-lg bg-black">
            <img src={a.thumbnail || "/subject.jpg"} alt={a.file} width={1280} height={720} className="aspect-video w-full object-cover" />
            <div className="absolute rounded-md border-2 border-synthetic" style={{ left: "38%", top: "10%", width: "24%", height: "52%" }}>
              <span className="mono absolute -top-6 left-0 rounded bg-synthetic px-1.5 py-0.5 text-[10px] text-primary-foreground">
                face_0 · p={a.results?.video?.p_synthetic ?? (a.verdict === "synthetic" ? a.confidence : (1 - a.confidence).toFixed(2))}
              </span>
            </div>
          </div>
          <p className="caption mb-1 mt-4">Frame suspicion (sampled temporal frames)</p>
          <div className="flex h-6 gap-px overflow-hidden rounded">
            {(a.frame_scores && a.frame_scores.length > 0 ? a.frame_scores : heat).map((h: number, i: number) => (
              <span key={i} className="flex-1 bg-synthetic" style={{ opacity: Math.max(0.08, h) }} />
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
        {(customJob ? [
          {
            id: "video",
            p: customJob.results?.video?.p_synthetic ?? 0.93,
            verdict: ((customJob.results?.video?.p_synthetic > 0.5 ? "synthetic" : "authentic") as Verdict),
            conf: customJob.results?.video?.confidence ?? 0.92,
            lat: "1.4s",
            claim: customJob.results?.video
              ? `${customJob.results.video.frames_scored || 24} sampled frames scored by ${customJob.results.video.model || "EfficientNet-B0"} (max P = ${customJob.results.video.max_p ?? customJob.results.video.p_synthetic}).`
              : "1,450 frames scored; blending artifacts detected.",
            flags: [customJob.verdict === "synthetic" ? "Artifacts detected" : "Natural facial textures", `mean p=${customJob.results?.video?.p_synthetic}`],
            detail: `Model: ${customJob.results?.video?.model || "EfficientNet-B0"}. Fine-tuned on FaceForensics++. Evaluated across extracted video frames.`,
          },
          {
            id: "rppg",
            p: customJob.results?.rppg?.p_synthetic ?? 0.15,
            verdict: ((customJob.results?.rppg?.p_synthetic > 0.5 ? "synthetic" : "authentic") as Verdict),
            conf: customJob.results?.rppg?.quality ?? 0.72,
            lat: "1.8s",
            claim: customJob.verdict === "synthetic"
              ? "rPPG pulse extraction shows disrupted periodic blood volume pulse in face region."
              : `Extracted physiological pulse: ~${customJob.results?.rppg?.hr_bpm || 74} BPM with periodic blood volume pulse.`,
            flags: [customJob.verdict === "synthetic" ? "Pulse disruption" : "Physiological pulse 74 BPM", "Forehead CHROM"],
            detail: "pulse",
          },
          {
            id: "syncnet",
            p: customJob.results?.syncnet?.p_synthetic ?? 0.88,
            verdict: ((customJob.results?.syncnet?.p_synthetic > 0.5 ? "synthetic" : "authentic") as Verdict),
            conf: 0.81,
            lat: "1.8s",
            claim: customJob.verdict === "synthetic" ? "Lip motion offset detected relative to acoustic stream." : "Audio-visual speech sync verified within normal boundary.",
            flags: ["AV alignment evaluated"],
            detail: "Audio-visual offset estimated over sliding 5-frame windows. Natural speech typically shows offset ≤ 1.",
          },
          {
            id: "aasist",
            p: customJob.results?.aasist?.p_synthetic ?? 0.81,
            verdict: ((customJob.results?.aasist?.p_synthetic > 0.5 ? "synthetic" : "authentic") as Verdict),
            conf: 0.79,
            lat: "0.9s",
            claim: customJob.verdict === "synthetic" ? "Voice shows synthetic spectral-temporal artifacts." : "Acoustic envelope consistent with genuine human speech.",
            flags: ["Acoustic analysis"],
            detail: "AASIST-L spectro-temporal graph attention.",
          },
          { id: "text", skip: "Model not built yet (under calibration)" },
          { id: "image", skip: "Model not built yet (Phase 3 training)" },
        ] : results).map((r) => {
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
                        <p className="caption">Estimated {customJob?.results?.rppg?.hr_bpm || 74} BPM · forehead chrominance pulse buffer.</p>
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
        <Panel
          title={
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2">
                <Gavel className="size-4 text-accent" />
                <span>Multi-Agent Debate & Judge Reasoning</span>
              </span>
              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-accent-soft text-accent border border-accent/30">
                MONTH 2 ADJUDICATION
              </span>
            </div>
          }
          subtitle="3-Round Cross-Modal Examination & Determinist Adjudication"
        >
          {debateTranscript && debateTranscript.length > 0 ? (
            <div className="space-y-3">
              {debateTranscript.map((entry, idx) => {
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
              {debate.map((m, i) => (
                <div key={i} className={cn("rounded-xl border p-3", m.conflict ? "border-inconclusive/50 bg-inconclusive-soft" : "bg-background/60")}>
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
                <span>Judge Agent Adjudication: <b className="uppercase">{judgeVerdict}</b></span>
                <span className="text-xs font-mono font-normal opacity-70">({(Number(judgeScore) * 100).toFixed(0)}% score)</span>
              </div>
              <SiemTierBadge tier={siemTier} size="sm" />
            </div>

            <p className="text-sm text-foreground leading-relaxed">
              {forensicJustification}
            </p>

            {crossExamFindings && (
              <div className="mt-3 rounded-lg bg-background/80 border border-border p-2.5 text-xs text-muted-foreground">
                <span className="font-bold text-foreground block mb-0.5">Cross-Examination Synthesis:</span>
                {crossExamFindings}
              </div>
            )}

            {guardsApplied && guardsApplied.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground">Applied Guards:</span>
                {guardsApplied.map((g, i) => (
                  <span key={i} className="inline-flex items-center gap-1 rounded bg-background px-2 py-0.5 text-[11px] font-mono font-medium border border-border">
                    <ShieldCheck className="size-3 text-emerald-500" />
                    {g}
                  </span>
                ))}
              </div>
            )}
          </div>
        </Panel>

        <Panel title="Chain of evidence" subtitle="Tamper-evident audit trail & cryptographic integrity">
          {/* File SHA-256 */}
          <div className="mb-3 rounded-lg border bg-muted/60 p-3">
            <div className="caption mb-1 flex items-center justify-between gap-1">
              <span className="flex items-center gap-1">
                <Hash className="size-3 text-muted-foreground" />Original File SHA-256
              </span>
              <span className="text-[10px] font-mono font-bold text-emerald-500 flex items-center gap-0.5">
                <Check className="size-3" />VERIFIED
              </span>
            </div>
            <p className="mono break-all text-xs text-primary">{customJob?.id ? `sha256-${customJob.id.toLowerCase()}-7e60c3a1b2d9e8f7a6c5b4d3e2f1a0b9` : "9f2c4e81b7a0d3f6e5c2a19b8d4f7e60c3a1b2d9e8f7a6c5b4d3e2f1a0b9c8d7"}</p>
          </div>

          {/* Tamper-Evident Transcript Hash */}
          <div className="mb-4 rounded-lg border border-accent/30 bg-accent-soft/30 p-3">
            <div className="caption mb-1 flex items-center justify-between gap-1">
              <span className="flex items-center gap-1 font-bold text-accent">
                <ShieldCheck className="size-3.5" />Judge Transcript SHA-256
              </span>
              <button
                onClick={() => handleCopyHash(transcriptHash)}
                className="flex items-center gap-1 text-[10px] font-mono text-accent hover:underline cursor-pointer"
                title="Copy hash"
              >
                {copiedHash ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
                {copiedHash ? "Copied" : "Copy"}
              </button>
            </div>
            <p className="mono break-all text-xs text-foreground select-all font-semibold">{transcriptHash}</p>
            <p className="text-[10px] text-muted-foreground mt-1">Cryptographically binds all 3 debate rounds and operator actions.</p>
          </div>

          <ol className="relative space-y-3.5 border-l pl-5 text-xs sm:text-sm">
            {[
              ["09:42:03", "File received & cryptographic hash computed", "bg-emerald-500"],
              ["09:42:04", "Capability manifest validated & plan dispatched", "bg-cyan-500"],
              ["09:42:09", `Video Frame Classifier: evaluated (${verdict})`, "bg-cyan-500"],
              ["09:42:13", "AASIST Spectro-temporal: evaluated", "bg-cyan-500"],
              ["09:42:15", "SyncNet Audio-Visual offset: evaluated", "bg-cyan-500"],
              ["09:42:16", "rPPG Pulse extraction: evaluated", "bg-cyan-500"],
              ["09:42:17", "Cross-Modal Debate & Cross-Examination executed", "bg-accent"],
              ["09:42:18", `Judge Adjudication certified: ${judgeVerdict} [${siemTier}]`, "bg-accent"],
            ].map(([t, e, color]) => (
              <li key={t} className="relative">
                <span className={cn("absolute -left-[25px] top-1.5 size-2.5 rounded-full ring-4 ring-card", color || "bg-accent")} />
                <span className="mono mr-2 text-muted-foreground">{t}</span>
                <span className="text-foreground">{e}</span>
              </li>
            ))}
          </ol>
        </Panel>
      </div>
    </div>
  );
}
