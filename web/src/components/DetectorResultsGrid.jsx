"use client";

import React, { useState } from "react";
import {
  ShieldCheck,
  ShieldAlert,
  ShieldQuestion,
  MinusCircle,
  Loader2,
  Mic,
  Film,
  HeartPulse,
  Video,
  AlertTriangle,
  Info,
  Cpu,
  Clock,
  Download,
  Terminal,
  Gavel,
  Scale,
  Hash,
  Check,
  Copy,
  ChevronDown,
  ChevronUp,
  Layers,
  Shield,
} from "lucide-react";

const DETECTOR_META = {
  video_classifier: {
    label: "Video Frame Classifier",
    modality: "Visual Frame Boundary",
    icon: Film,
  },
  aasist: {
    label: "AASIST Audio Detector",
    modality: "Acoustic Graph Attention",
    icon: Mic,
  },
  rppg: {
    label: "rPPG Pulse Consistency",
    modality: "Physiological Blood Pulse",
    icon: HeartPulse,
  },
  syncnet: {
    label: "SyncNet Audio-Visual",
    modality: "Lip-Sync Alignment",
    icon: Video,
  },
};

const NOT_APPLICABLE_FLAG = "not_applicable";

function truncateMiddle(str, maxLength = 26) {
  if (!str || str.length <= maxLength) return str || "media_file";
  const extIndex = str.lastIndexOf(".");
  const ext = extIndex !== -1 ? str.slice(extIndex) : "";
  const nameWithoutExt = extIndex !== -1 ? str.slice(0, extIndex) : str;
  const available = maxLength - ext.length - 3;
  if (available <= 4) return str.slice(0, maxLength) + "...";
  const start = Math.ceil(available / 2);
  const end = Math.floor(available / 2);
  return `${nameWithoutExt.slice(0, start)}...${nameWithoutExt.slice(-end)}${ext}`;
}

function verdictFromConfidence(confidence) {
  if (confidence <= 0.35) return "authentic";
  if (confidence >= 0.65) return "synthetic";
  return "inconclusive";
}

const VERDICT_STYLES = {
  authentic: {
    icon: ShieldCheck,
    label: "AUTHENTIC",
    badge: "bg-emerald-100 text-emerald-800 border border-emerald-300 font-bold",
    barColor: "bg-emerald-600",
  },
  synthetic: {
    icon: ShieldAlert,
    label: "SYNTHETIC",
    badge: "bg-rose-100 text-rose-800 border border-rose-300 font-bold",
    barColor: "bg-rose-600",
  },
  inconclusive: {
    icon: ShieldQuestion,
    label: "INCONCLUSIVE",
    badge: "bg-amber-100 text-amber-800 border border-amber-300 font-bold",
    barColor: "bg-amber-600",
  },
};

function DetectorCard({ id, response }) {
  const meta = DETECTOR_META[id] ?? {
    label: id,
    modality: "Analysis",
    icon: Film,
  };
  const Icon = meta.icon;

  // 1. Pending / Analyzing
  if (response === null || response === undefined) {
    return (
      <div className="p-4 rounded-xl border border-slate-800/80 bg-slate-900/60 flex flex-col justify-between h-full">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg bg-slate-800/80 border border-slate-700/60 text-slate-400 flex-shrink-0">
            <Icon className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-slate-200 truncate">{meta.label}</p>
            <p className="text-[10px] text-slate-400 truncate font-mono">{meta.modality}</p>
          </div>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center py-6 space-y-2 text-center">
          <Loader2 className="w-5 h-5 text-cyan-400 animate-spin" />
          <p className="text-[10px] font-mono text-slate-400 uppercase tracking-wider">Awaiting Dispatch…</p>
        </div>
      </div>
    );
  }

  // 2. Real error
  if (response.error) {
    return (
      <div className="p-4 rounded-xl border border-rose-900/50 bg-rose-950/20 flex flex-col justify-between h-full">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg bg-rose-900/30 border border-rose-800/40 text-rose-400 flex-shrink-0">
            <Icon className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-slate-200 truncate">{meta.label}</p>
            <p className="text-[10px] text-rose-400/80 truncate font-mono">Execution Failure</p>
          </div>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center py-5 text-center space-y-1">
          <ShieldQuestion className="w-6 h-6 text-rose-400" />
          <p className="text-[11px] font-mono text-rose-300 line-clamp-2 px-1">{response.error}</p>
        </div>
      </div>
    );
  }

  // 3. Not Applicable (Modality Absent)
  const flags = response.evidence?.flags ?? [];
  if (flags.includes(NOT_APPLICABLE_FLAG)) {
    return (
      <div className="p-4 rounded-xl border border-dashed border-slate-800/80 bg-slate-950/40 opacity-60 flex flex-col justify-between h-full">
        <div>
          <div className="flex items-center gap-2.5 mb-3">
            <div className="p-2 rounded-lg bg-slate-800/60 border border-slate-700/40 text-slate-400 flex-shrink-0">
              <Icon className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-slate-300 truncate">{meta.label}</p>
              <p className="text-[10px] text-slate-400 truncate font-mono">{meta.modality}</p>
            </div>
          </div>
          <div className="flex flex-col items-center justify-center py-4 text-center space-y-1.5">
            <MinusCircle className="w-5 h-5 text-slate-400" />
            <span className="text-[10px] font-mono font-semibold uppercase tracking-wider text-slate-300 bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
              NOT APPLICABLE
            </span>
            <p className="text-[11px] text-slate-400 line-clamp-2 px-1">{response.evidence?.claim}</p>
          </div>
        </div>
        <div className="pt-2 border-t border-slate-800/40 text-[10px] font-mono text-slate-400 text-center">
          Modality Not In Media
        </div>
      </div>
    );
  }

  // 4. Completed Result
  const verdict = verdictFromConfidence(response.confidence);
  const style = VERDICT_STYLES[verdict];
  const VerdictIcon = style.icon;
  const confPercent = (response.confidence * 100).toFixed(1);

  return (
    <div className="p-4 rounded-xl border border-slate-800/90 bg-slate-900/60 hover:border-slate-700/90 transition-all flex flex-col justify-between h-full">
      <div className="space-y-3">
        {/* Card Header: Neutral icon & title */}
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg bg-slate-800/80 border border-slate-700/60 text-slate-300 flex-shrink-0">
            <Icon className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-slate-100 truncate">{meta.label}</p>
            <p className="text-[10px] text-slate-400 truncate font-mono">{meta.modality}</p>
          </div>
        </div>

        {/* Verdict Badge & Score */}
        <div className="flex items-center justify-between pt-0.5">
          <div className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-mono font-bold ${style.badge}`}>
            <VerdictIcon className="w-3.5 h-3.5" />
            <span>{style.label}</span>
          </div>

          <div className="text-right font-mono">
            <span className="text-[9px] uppercase text-slate-400 block">Synthetic Score</span>
            <span className="text-xs font-bold text-slate-200">{confPercent}%</span>
          </div>
        </div>

        {/* Quiet Confidence Bar */}
        <div className="space-y-1">
          <div className="w-full bg-slate-950/80 rounded-full h-1.5 overflow-hidden border border-slate-800/80">
            <div
              className={`h-full rounded-full ${style.barColor}`}
              style={{ width: `${Math.max(4, response.confidence * 100)}%` }}
            />
          </div>
        </div>

        {/* Evidence Claim (Fixed height for uniform vertical rhythm) */}
        <div className="bg-slate-950/60 rounded-lg p-2.5 border border-slate-800/60 text-[11px] font-mono text-slate-300 h-[48px] flex items-center">
          <p className="line-clamp-2">{response.evidence?.claim}</p>
        </div>
      </div>

      {/* Pinned Telemetry Footer */}
      <div className="mt-3 pt-2.5 border-t border-slate-800/60 flex items-center justify-between text-[10px] font-mono text-slate-400">
        <div className="flex items-center gap-1">
          <Cpu className="w-3 h-3 text-slate-400" />
          <span>{response.ram_usage_mb ? `${response.ram_usage_mb} MB` : "--"}</span>
        </div>
        <div className="flex items-center gap-1">
          <Clock className="w-3 h-3 text-slate-400" />
          <span className="text-slate-300 font-semibold">{response.latency_ms} ms</span>
        </div>
      </div>
    </div>
  );
}

/**
 * Unified Forensic Verdict Banner
 * Combines media metadata, consensus verdict, SIEM tier, and quick actions into ONE clean header
 */
function ForensicVerdictBanner({ detectorResponses, fileName, fileSize, onViewLogs, onExportJson }) {
  const [copiedHash, setCopiedHash] = useState(false);

  if (!detectorResponses) return null;

  const order = ["video_classifier", "rppg", "aasist", "syncnet"];
  const activeResults = [];

  order.forEach((id) => {
    const resp = detectorResponses[id];
    if (resp && !resp.error) {
      const flags = resp.evidence?.flags || [];
      if (!flags.includes(NOT_APPLICABLE_FLAG) && typeof resp.confidence === "number") {
        activeResults.push({
          id,
          label: DETECTOR_META[id]?.label || id,
          verdict: verdictFromConfidence(resp.confidence),
          confidence: resp.confidence,
        });
      }
    }
  });

  const authenticList = activeResults.filter((r) => r.verdict === "authentic");
  const syntheticList = activeResults.filter((r) => r.verdict === "synthetic");
  const hasDisagreement = authenticList.length > 0 && syntheticList.length > 0;

  // Month 2 Judge Agent properties
  const judgeVerdict = detectorResponses.judge_verdict;
  const judgeScore = typeof detectorResponses.judge_score === "number" ? detectorResponses.judge_score : null;
  const siemTier = detectorResponses.siem_alert_tier;
  const guardsApplied = detectorResponses.guards_applied || [];
  const justification = detectorResponses.forensic_justification;
  const transcriptHash = detectorResponses.debate_transcript_hash;
  const latencyMs = detectorResponses.adjudication_latency_ms;

  let bannerStyle = "border-emerald-300 bg-emerald-50/90 text-emerald-950 shadow-sm";
  let Icon = ShieldCheck;
  let iconColor = "text-emerald-700 bg-emerald-100 border-emerald-300";
  let title = judgeVerdict ? "Month 2 Judge-Agent: Certified Authentic" : "Cross-Modal Consensus: Authentic Media Verified";
  let verdictTag = judgeVerdict || "AUTHENTIC";
  let tagStyle = "bg-emerald-200 text-emerald-900 border-emerald-400 font-bold";
  let summary = justification || `All ${activeResults.length} active detectors agree media shows natural characteristics.`;

  const isSynthetic = judgeVerdict === "SYNTHETIC" || (!judgeVerdict && syntheticList.length > 0 && !hasDisagreement);
  const isDebate = judgeVerdict === "DEBATE_REQUIRED" || judgeVerdict === "INCONCLUSIVE" || (!judgeVerdict && hasDisagreement);
  const isIntegrityUnknown = judgeVerdict === "INTEGRITY_UNKNOWN";

  if (isIntegrityUnknown) {
    bannerStyle = "border-rose-400 bg-rose-50/95 text-rose-950 shadow-sm";
    Icon = AlertTriangle;
    iconColor = "text-rose-700 bg-rose-100 border-rose-300";
    title = "Month 2 Judge-Agent: Integrity Unknown (Provenance Violation)";
    verdictTag = "INTEGRITY UNKNOWN";
    tagStyle = "bg-rose-200 text-rose-950 border-rose-400 font-bold";
    summary = justification || "Hardware provenance or stream integrity verification failed. Authentic verdict disallowed under protocol.";
  } else if (isSynthetic) {
    bannerStyle = "border-rose-300 bg-rose-50/90 text-rose-950 shadow-sm";
    Icon = ShieldAlert;
    iconColor = "text-rose-700 bg-rose-100 border-rose-300";
    title = judgeVerdict ? "Month 2 Judge-Agent: Synthetic Manipulation Confirmed" : "Cross-Modal Consensus: Synthetic Media Detected";
    verdictTag = "SYNTHETIC";
    tagStyle = "bg-rose-200 text-rose-900 border-rose-400 font-bold";
    summary = justification || `Manipulation verified across active detectors (${syntheticList.map((r) => r.label.split(" ")[0]).join(", ")}).`;
  } else if (isDebate) {
    bannerStyle = "border-amber-300 bg-amber-50/90 text-amber-950 shadow-sm";
    Icon = AlertTriangle;
    iconColor = "text-amber-700 bg-amber-100 border-amber-300";
    title = judgeVerdict ? "Month 2 Judge-Agent: Contested Disagreement Adjudicated" : "Cross-Modal Disagreement Detected";
    verdictTag = judgeVerdict || "DEBATE REQUIRED";
    tagStyle = "bg-amber-200 text-amber-900 border-amber-400 font-bold";
    summary = justification || `Conflicting claims: ${authenticList.length} Authentic vs. ${syntheticList.length} Synthetic. Layer C Debate protocol activated.`;
  }

  const handleCopyHash = () => {
    if (transcriptHash) {
      navigator.clipboard?.writeText(transcriptHash);
      setCopiedHash(true);
      setTimeout(() => setCopiedHash(false), 2000);
    }
  };

  return (
    <div className={`p-5 rounded-2xl border ${bannerStyle} space-y-4`}>
      <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
        {/* Left: Verdict Status & Explanation */}
        <div className="flex items-start gap-3.5 min-w-0 flex-1">
          <div className={`p-2.5 rounded-xl border flex-shrink-0 mt-0.5 ${iconColor}`}>
            <Icon className="w-5 h-5" />
          </div>
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-extrabold text-base sm:text-lg text-slate-900 tracking-tight truncate">
                {title}
              </h3>
              <span className={`px-2.5 py-0.5 rounded text-[10px] font-mono font-bold border tracking-wider uppercase ${tagStyle}`}>
                {verdictTag}
              </span>
              {siemTier && (
                <span className={`px-2.5 py-0.5 rounded text-[10px] font-mono font-bold border tracking-wider uppercase ${
                  siemTier.includes("3") || siemTier.includes("CRITICAL")
                    ? "bg-rose-100 text-rose-800 border-rose-300"
                    : siemTier.includes("2") || siemTier.includes("ELEVATED")
                    ? "bg-amber-100 text-amber-800 border-amber-300"
                    : "bg-emerald-100 text-emerald-800 border-emerald-300"
                }`}>
                  {siemTier.replace(/_/g, " ")}
                </span>
              )}
              {judgeScore !== null && (
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-900 text-white">
                  Anomaly: {(judgeScore * 100).toFixed(1)}%
                </span>
              )}
            </div>

            <p className="text-xs text-slate-700 leading-relaxed font-sans">{summary}</p>

            {/* Applied Guards Chips */}
            {guardsApplied.length > 0 && (
              <div className="flex items-center gap-1.5 flex-wrap pt-1">
                <span className="text-[10px] font-mono font-bold text-slate-500 uppercase">Guards Enforced:</span>
                {guardsApplied.map((guard, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-white/80 text-slate-800 border border-slate-300 shadow-2xs"
                  >
                    <Shield className="w-3 h-3 text-cyan-600" />
                    {guard}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2 flex-shrink-0 self-end md:self-start">
          {onViewLogs && (
            <button
              onClick={onViewLogs}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono text-slate-700 hover:text-slate-900 bg-white hover:bg-slate-100 border border-slate-300 transition-colors cursor-pointer shadow-xs font-bold"
            >
              <Terminal className="w-3.5 h-3.5 text-slate-600" />
              <span>Pipeline Logs</span>
            </button>
          )}

          {onExportJson && (
            <button
              onClick={onExportJson}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono text-white bg-cyan-600 hover:bg-cyan-700 border border-cyan-600 transition-colors cursor-pointer shadow-xs font-bold"
            >
              <Download className="w-3.5 h-3.5 text-white" />
              <span>Export JSON</span>
            </button>
          )}
        </div>
      </div>

      {/* Sub-bar: Cryptographic Hash & Media Metadata */}
      <div className="pt-2.5 border-t border-slate-200/80 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-[11px] font-mono text-slate-600">
        <div className="flex items-center gap-2 min-w-0 truncate">
          <span className="text-slate-900 font-bold truncate" title={fileName}>
            {truncateMiddle(fileName, 32)}
          </span>
          {fileSize && (
            <>
              <span>•</span>
              <span className="font-semibold">{fileSize}</span>
            </>
          )}
          <span>•</span>
          <span className="text-slate-500 font-bold">
            {activeResults.length} Evaluated Modalities
          </span>
          {latencyMs && (
            <>
              <span>•</span>
              <span className="text-slate-600 font-bold">
                Adjudicated in {latencyMs.toFixed(2)}ms
              </span>
            </>
          )}
        </div>

        {transcriptHash && (
          <div className="flex items-center gap-1.5 text-[10px] text-slate-500 shrink-0">
            <Hash className="w-3 h-3 text-cyan-600" />
            <span className="hidden md:inline">Transcript Hash:</span>
            <span className="text-slate-700 font-bold truncate max-w-[160px]" title={transcriptHash}>
              {transcriptHash.slice(0, 14)}...{transcriptHash.slice(-8)}
            </span>
            <button
              onClick={handleCopyHash}
              className="p-1 hover:text-cyan-700 transition-colors cursor-pointer"
              title="Copy SHA-256 Hash"
            >
              {copiedHash ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * 3-Round Judge Agent Structured Debate Protocol Visualizer
 */
function JudgeDebateTimeline({ debateTranscript, crossExam, justification, transcriptHash }) {
  const [isOpen, setIsOpen] = useState(true);
  const [copied, setCopied] = useState(false);

  if (!debateTranscript || debateTranscript.length === 0) return null;

  const handleCopyHash = () => {
    if (transcriptHash) {
      navigator.clipboard?.writeText(transcriptHash);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const speakerMeta = {
    video_classifier: { name: "Video Classifier", icon: Film, color: "text-cyan-700 bg-cyan-100 border-cyan-300" },
    rppg: { name: "CHROM rPPG Pulse", icon: HeartPulse, color: "text-rose-700 bg-rose-100 border-rose-300" },
    syncnet: { name: "SyncNet Audio-Visual", icon: Video, color: "text-teal-700 bg-teal-100 border-teal-300" },
    aasist: { name: "AASIST Audio Spoof", icon: Mic, color: "text-violet-700 bg-violet-100 border-violet-300" },
    judge_agent: { name: "Judge Agent", icon: Gavel, color: "text-amber-800 bg-amber-100 border-amber-300" },
  };

  const rounds = [
    { num: 1, title: "Round 1: Initial Modal Claims", items: debateTranscript.filter((d) => d.round === 1) },
    { num: 2, title: "Round 2: Cross-Modal Cross-Examination", items: debateTranscript.filter((d) => d.round === 2) },
    { num: 3, title: "Round 3: Final Synthesis & Verdict Adjudication", items: debateTranscript.filter((d) => d.round === 3) },
  ].filter((r) => r.items.length > 0);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden animate-in fade-in duration-200">
      {/* Header Toggle */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-5 py-3.5 bg-slate-50/80 hover:bg-slate-100/80 border-b border-slate-200 transition-colors cursor-pointer text-left"
      >
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-amber-100 text-amber-800 border border-amber-300">
            <Scale className="w-4 h-4 text-amber-700" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-xs sm:text-sm font-bold text-slate-900 tracking-tight font-mono uppercase">
                Month 2 Judge-Agent Structured Debate Protocol
              </h3>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-100 text-amber-800 border border-amber-300">
                3-Round Cross-Examination
              </span>
            </div>
            <p className="text-[11px] text-slate-500 font-sans mt-0.5">
              Court-admissible multi-modal evidence arbitration with anti-default guardrails.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {transcriptHash && (
            <span className="hidden sm:inline-flex text-[10px] font-mono text-slate-400">
              SHA-256 Validated
            </span>
          )}
          {isOpen ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
        </div>
      </button>

      {/* Expandable Content */}
      {isOpen && (
        <div className="p-5 space-y-5">
          {/* Timeline of Rounds */}
          <div className="space-y-4">
            {rounds.map((round) => (
              <div key={round.num} className="space-y-2.5">
                <div className="flex items-center gap-2 border-b border-slate-100 pb-1.5">
                  <span className="flex items-center justify-center w-5 h-5 rounded-full bg-slate-200 text-slate-700 text-[10px] font-mono font-bold">
                    {round.num}
                  </span>
                  <span className="text-xs font-mono font-bold text-slate-800 uppercase tracking-wide">
                    {round.title}
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 pl-2 sm:pl-7">
                  {round.items.map((item, idx) => {
                    const meta = speakerMeta[item.speaker] || {
                      name: item.speaker,
                      icon: Gavel,
                      color: "text-slate-700 bg-slate-100 border-slate-300",
                    };
                    const SpeakerIcon = meta.icon;
                    const isSynth = item.polarity === "SYNTHETIC";
                    const isAuth = item.polarity === "AUTHENTIC";

                    return (
                      <div
                        key={idx}
                        className="p-3 rounded-xl border border-slate-200/80 bg-slate-50/60 space-y-2 flex flex-col justify-between"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span className={`p-1 rounded-md border text-xs shrink-0 ${meta.color}`}>
                              <SpeakerIcon className="w-3.5 h-3.5" />
                            </span>
                            <span className="text-xs font-bold text-slate-800 font-mono truncate">
                              {meta.name}
                            </span>
                          </div>

                          <span className={`px-2 py-0.5 rounded text-[9px] font-mono font-bold uppercase border shrink-0 ${
                            isSynth
                              ? "bg-rose-100 text-rose-800 border-rose-300"
                              : isAuth
                              ? "bg-emerald-100 text-emerald-800 border-emerald-300"
                              : "bg-slate-100 text-slate-600 border-slate-300"
                          }`}>
                            {item.polarity}
                          </span>
                        </div>

                        <p className="text-xs text-slate-700 leading-snug font-sans">
                          {item.claim}
                        </p>

                        {typeof item.confidence === "number" && item.confidence > 0 && (
                          <div className="pt-1.5 border-t border-slate-200/60 flex items-center justify-between text-[10px] font-mono text-slate-500">
                            <span>Claim Confidence:</span>
                            <span className="font-bold text-slate-700">{(item.confidence * 100).toFixed(0)}%</span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>

          {/* Adjudication Summary Box */}
          {justification && (
            <div className="p-4 rounded-xl border border-amber-200 bg-amber-50/60 space-y-2">
              <div className="flex items-center gap-2 text-xs font-mono font-bold text-amber-900 uppercase">
                <Gavel className="w-3.5 h-3.5 text-amber-700" />
                <span>Forensic Adjudication Justification</span>
              </div>
              <p className="text-xs text-slate-800 leading-relaxed font-sans">{justification}</p>
              {crossExam && (
                <p className="text-[11px] text-slate-600 font-mono italic">
                  Cross-Examination Finding: {crossExam}
                </p>
              )}
            </div>
          )}

          {/* Transcript SHA-256 Audit Bar */}
          {transcriptHash && (
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded-lg bg-slate-900 text-slate-300 text-xs font-mono">
              <div className="flex items-center gap-2 min-w-0">
                <Hash className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                <span className="text-slate-400 shrink-0">Tamper-Evident SHA-256 Hash:</span>
                <span className="text-cyan-300 font-bold truncate">{transcriptHash}</span>
              </div>
              <button
                onClick={handleCopyHash}
                className="flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] transition-colors shrink-0 cursor-pointer"
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                    <span className="text-emerald-400 font-bold">Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    <span>Copy Hash</span>
                  </>
                )}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function DetectorResultsGrid({
  detectorResponses,
  fileName,
  fileSize,
  onViewLogs,
  onExportJson,
}) {
  const order = ["video_classifier", "rppg", "aasist", "syncnet"];
  const completedCount = order.filter((id) => detectorResponses?.[id] && !detectorResponses[id].error).length;

  return (
    <div className="space-y-5 animate-in fade-in duration-200">
      {/* Consolidated Single Verdict Banner */}
      <ForensicVerdictBanner
        detectorResponses={detectorResponses}
        fileName={fileName}
        fileSize={fileSize}
        onViewLogs={onViewLogs}
        onExportJson={onExportJson}
      />

      {/* Month 2 Judge Agent Structured Debate Protocol Timeline */}
      <JudgeDebateTimeline
        debateTranscript={detectorResponses?.debate_transcript}
        crossExam={detectorResponses?.cross_examination_findings}
        justification={detectorResponses?.forensic_justification}
        transcriptHash={detectorResponses?.debate_transcript_hash}
      />

      {/* Grid Title Bar */}
      <div className="flex items-center justify-between pt-1">
        <h2 className="text-xs sm:text-sm font-bold text-slate-800 uppercase tracking-wider font-mono">
          Layer B Detector Breakdown
        </h2>
        <span className="text-[11px] font-mono text-slate-500 font-bold">
          {completedCount} of {order.length} Evaluated
        </span>
      </div>

      {/* 4-Detector Grid with Uniform Neutral Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {order.map((id) => (
          <DetectorCard key={id} id={id} response={detectorResponses?.[id]} />
        ))}
      </div>
    </div>
  );
}
