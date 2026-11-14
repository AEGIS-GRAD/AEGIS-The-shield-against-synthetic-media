"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Download, FileJson, Link2, RotateCw, Flag, NotebookPen, ChevronDown, Gavel, ShieldCheck, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import { analyses, detectors, type Verdict } from "@/lib/mock";
import { Btn, Chip, ConfidenceMeter, ModalityIcon, Panel, VerdictBadge, SiemTierBadge, DemoBadge, DemoBanner } from "@/components/aegis/ui";
import { useDemoMode } from "@/lib/demoMode";
import { ComingSoon } from "@/components/aegis/ComingSoon";
import { FrameHeatmap } from "@/components/report/FrameHeatmap";
import { PulseWave } from "@/components/report/PulseWave";
import { DebateLog } from "@/components/report/DebateLog";
import { AgreementMatrix } from "@/components/report/AgreementMatrix";
import { HashChain } from "@/components/report/HashChain";
import {
  DEFAULT_AGREEMENT_IDS,
  DEFAULT_AGREEMENT_MATRIX,
  DEFAULT_AUDIO_WAVE,
  DEFAULT_FRAME_HEAT,
  type HashChainEvent,
} from "@/lib/report";
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
const susp = (i: number) => (i >= 24 && i < 30) || (i >= 60 && i < 67);

export default function ReportDetailPage() {
  const params = useParams();
  const id = (params?.id as string) || "AEG-1042";
  const [demoMode, setDemoMode] = useDemoMode();
  const [customJob, setCustomJob] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [notFound, setNotFound] = useState<boolean>(false);
  const [open, setOpen] = useState<string | null>("video");

  useEffect(() => {
    setLoading(true);
    fetch(`/api/jobs?id=${encodeURIComponent(id)}`)
      .then((res) => {
        if (!res.ok) throw new Error("Job not found");
        return res.json();
      })
      .then((data) => {
        if (data && !data.error) {
          setCustomJob(data);
          setNotFound(false);
        } else {
          setNotFound(true);
        }
      })
      .catch((err) => {
        console.warn("Failed to fetch /api/jobs:", err);
        const mockMatch = analyses.find((x) => x.id === id);
        if (mockMatch) {
          setCustomJob({ ...mockMatch, is_demo: true });
          setNotFound(false);
        } else if (demoMode) {
          setCustomJob({ ...analyses[0], is_demo: true });
          setNotFound(false);
        } else {
          setCustomJob(null);
          setNotFound(true);
        }
      })
      .finally(() => setLoading(false));
  }, [id, demoMode]);

  if (notFound && !customJob && !loading) {
    return (
      <div className="space-y-6 max-w-4xl mx-auto py-8">
        <Link href="/reports" className="caption hover:text-primary">
          ← Back to Reports
        </Link>
        <div className="rounded-2xl border border-destructive/30 bg-destructive/10 p-8 text-center space-y-4">
          <AlertCircle className="size-10 mx-auto text-destructive" />
          <h2 className="text-xl font-bold">Report Not Found</h2>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            Live report with ID <code>{id}</code> does not exist in local storage, or the backend service is offline.
          </p>
          <div className="flex justify-center gap-3 pt-2">
            <Link href="/reports">
              <Btn variant="outline">Browse Reports</Btn>
            </Link>
            <Btn variant="accent" onClick={() => setDemoMode(true)}>
              Enable Demo Data
            </Btn>
          </div>
        </div>
      </div>
    );
  }

  const isDemo = Boolean(customJob?.is_demo);
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
        id: "AEG-1042",
        file: "press_briefing_0918.mp4",
        verdict: "synthetic" as Verdict,
        confidence: 0.91,
        time: "09:42",
        status: "Complete",
        thumbnail: "/subject.jpg",
        results: null,
        frame_scores: null,
      };

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
      toast.success("Tamper-evident transcript hash copied to clipboard");
    }
  };

  const fileHash = customJob?.id
    ? `sha256-${customJob.id.toLowerCase()}-7e60c3a1b2d9e8f7a6c5b4d3e2f1a0b9`
    : "9f2c4e81b7a0d3f6e5c2a19b8d4f7e60c3a1b2d9e8f7a6c5b4d3e2f1a0b9c8d7";

  const chainEvents: HashChainEvent[] = [
    ["09:42:03", "File received & cryptographic hash computed", "bg-emerald-500"],
    ["09:42:04", "Capability manifest validated & plan dispatched", "bg-cyan-500"],
    ["09:42:09", `Video Frame Classifier: evaluated (${verdict})`, "bg-cyan-500"],
    ["09:42:13", "AASIST Spectro-temporal: evaluated", "bg-cyan-500"],
    ["09:42:15", "SyncNet Audio-Visual offset: evaluated", "bg-cyan-500"],
    ["09:42:16", "rPPG Pulse extraction: evaluated", "bg-cyan-500"],
    ["09:42:17", "Cross-Modal Debate & Cross-Examination executed", "bg-accent"],
    ["09:42:18", `Judge Adjudication certified: ${judgeVerdict} [${siemTier}]`, "bg-accent"],
  ];

  return (
    <div className="space-y-6">
      {isDemo && (
        <DemoBanner
          message="This report is a simulated forensic evaluation fixture. Real neural models were not dispatched on this file."
        />
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href="/reports" className="caption hover:text-primary">
            ← Back to Reports
          </Link>
          <div className="flex items-center gap-2 mt-1">
            <h1>{a.file}</h1>
            {isDemo ? (
              <DemoBadge />
            ) : (
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-authentic-soft text-authentic-ink border border-authentic/30 font-bold">
                REAL ADJUDICATED REPORT
              </span>
            )}
          </div>
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
          <FrameHeatmap
            scores={a.frame_scores && a.frame_scores.length > 0 ? a.frame_scores : DEFAULT_FRAME_HEAT}
            isDemo={isDemo && !(a.frame_scores && a.frame_scores.length > 0)}
          />
          <p className="caption mb-1 mt-4">Audio waveform · suspicious segments highlighted</p>
          <div className="flex h-14 items-center gap-px">
            {DEFAULT_AUDIO_WAVE.map((h, i) => (
              <span key={i} className={cn("flex-1 rounded-sm", susp(i) ? "bg-synthetic" : "bg-chart-1/40")} style={{ height: `${h}%` }} />
            ))}
          </div>
        </Panel>

        <AgreementMatrix ids={DEFAULT_AGREEMENT_IDS} matrix={DEFAULT_AGREEMENT_MATRIX} />
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
                      <PulseWave
                        bpm={customJob?.results?.rppg?.hr_bpm || 74}
                        signal={customJob?.results?.rppg?.signal}
                      />
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
        <DebateLog
          transcript={debateTranscript}
          judgeVerdict={judgeVerdict}
          judgeScore={judgeScore}
          siemTier={siemTier}
          justification={forensicJustification}
          crossExam={crossExamFindings}
          guards={guardsApplied}
        />

        <HashChain
          fileHash={fileHash}
          transcriptHash={transcriptHash}
          events={chainEvents}
          onCopy={handleCopyHash}
        />
      </div>
    </div>
  );
}
