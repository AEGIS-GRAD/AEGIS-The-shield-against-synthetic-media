"use client";

import React from "react";
import {
  ShieldCheck,
  ShieldAlert,
  ShieldQuestion,
  MinusCircle,
  Loader2,
  Music,
  Film,
  HeartPulse,
  MessageSquareOff,
  AlertTriangle,
  Info,
} from "lucide-react";

/**
 * DetectorResultsGrid
 * --------------------
 * Renders all four AEGIS detector results (video_classifier, rPPG, AASIST,
 * SyncNet) side by side for a single submitted file, and provides a top-level
 * Cross-Modal Disagreement / Consensus synthesis banner.
 */

const DETECTOR_META = {
  video_classifier: { icon: Film, label: "Video Classifier", modality: "Visual Frame Analysis" },
  rppg: { icon: HeartPulse, label: "rPPG", modality: "Heartbeat Consistency" },
  aasist: { icon: Music, label: "AASIST", modality: "Audio Spoof Detection" },
  syncnet: { icon: MessageSquareOff, label: "SyncNet", modality: "Lip-Sync Consistency" },
};

const NOT_APPLICABLE_FLAG = "not_applicable";

// confidence: 0.0 = Authentic, 1.0 = Synthetic (per schema)
function verdictFromConfidence(confidence) {
  if (confidence <= 0.35) return "authentic";
  if (confidence >= 0.65) return "synthetic";
  return "inconclusive";
}

const VERDICT_STYLES = {
  authentic: {
    icon: ShieldCheck,
    iconColor: "text-emerald-400",
    border: "border-emerald-800/50",
    bg: "bg-emerald-950/30",
    label: "Authentic",
    labelColor: "text-emerald-300",
  },
  synthetic: {
    icon: ShieldAlert,
    iconColor: "text-rose-400",
    border: "border-rose-800/50",
    bg: "bg-rose-950/30",
    label: "Synthetic",
    labelColor: "text-rose-300",
  },
  inconclusive: {
    icon: ShieldQuestion,
    iconColor: "text-amber-400",
    border: "border-amber-800/50",
    bg: "bg-amber-950/30",
    label: "Inconclusive",
    labelColor: "text-amber-300",
  },
};

function CardHeader({ Icon, label, modality }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="p-1.5 rounded-md bg-slate-800/80 border border-slate-700/60 text-slate-400 flex-shrink-0">
        <Icon className="w-4 h-4" />
      </div>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-200 truncate">{label}</p>
        <p className="text-[11px] text-slate-500 truncate">{modality}</p>
      </div>
    </div>
  );
}

function DetectorCard({ id, response }) {
  const meta = DETECTOR_META[id] ?? { icon: Film, label: id, modality: "" };
  const Icon = meta.icon;

  // ---- Still processing: response hasn't arrived yet ----
  if (response === null || response === undefined) {
    return (
      <div className="p-5 rounded-xl border border-slate-800 bg-slate-900/60 flex flex-col h-full">
        <CardHeader Icon={Icon} label={meta.label} modality={meta.modality} />
        <div className="flex-1 flex flex-col items-center justify-center text-center py-6 space-y-2">
          <Loader2 className="w-6 h-6 text-cyan-400 animate-spin" />
          <p className="text-sm font-medium text-slate-400">Analyzing…</p>
        </div>
      </div>
    );
  }

  // ---- Real failure: the detector call itself errored (network, crash, etc.) ----
  if (response.error) {
    return (
      <div className="p-5 rounded-xl border border-rose-900/60 bg-rose-950/20 flex flex-col h-full shadow-lg shadow-rose-950/30">
        <CardHeader Icon={Icon} label={meta.label} modality={meta.modality} />
        <div className="flex-1 flex flex-col items-center justify-center text-center py-5 space-y-2">
          <ShieldQuestion className="w-7 h-7 text-rose-400" />
          <p className="text-xs font-bold uppercase tracking-wider text-rose-300">Detector Execution Error</p>
          <p className="text-xs text-rose-300/80 max-w-[24ch] font-mono">{response.error}</p>
        </div>
      </div>
    );
  }

  // ---- Not applicable: signaled via evidence.flags, kept schema-valid ----
  const flags = response.evidence?.flags ?? [];
  if (flags.includes(NOT_APPLICABLE_FLAG)) {
    return (
      <div className="p-5 rounded-xl border border-dashed border-slate-800 bg-slate-950/40 opacity-70 flex flex-col h-full">
        <CardHeader Icon={Icon} label={meta.label} modality={meta.modality} />
        <div className="flex-1 flex flex-col items-center justify-center text-center py-5 space-y-2">
          <MinusCircle className="w-6 h-6 text-slate-500" />
          <span className="text-[11px] font-mono font-semibold uppercase tracking-wider text-slate-400 bg-slate-900/80 px-2 py-0.5 rounded border border-slate-800">
            NOT APPLICABLE
          </span>
          <p className="text-xs text-slate-500 max-w-[22ch]">{response.evidence?.claim}</p>
        </div>
      </div>
    );
  }

  // ---- Normal completed result ----
  const verdict = verdictFromConfidence(response.confidence);
  const style = VERDICT_STYLES[verdict];
  const VerdictIcon = style.icon;

  return (
    <div className={`p-5 rounded-xl border ${style.border} ${style.bg} flex flex-col h-full`}>
      <CardHeader Icon={Icon} label={meta.label} modality={meta.modality} />

      <div className="flex items-center gap-2.5 mt-4">
        <VerdictIcon className={`w-6 h-6 ${style.iconColor} flex-shrink-0`} />
        <span className={`text-lg font-bold tracking-wide uppercase ${style.labelColor}`}>
          {style.label}
        </span>
      </div>

      <p className="text-xs text-slate-400 mt-2 line-clamp-2">{response.evidence?.claim}</p>

      <div className="grid grid-cols-2 gap-3 mt-4 pt-3 border-t border-slate-800/60">
        <div>
          <span className="text-[10px] text-slate-500 block font-mono uppercase tracking-wide">
            Confidence
          </span>
          <span className="font-mono font-semibold text-slate-200 text-sm">
            {(response.confidence * 100).toFixed(1)}%
          </span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 block font-mono uppercase tracking-wide">
            Latency
          </span>
          <span className="font-mono font-semibold text-slate-200 text-sm">
            {response.latency_ms} ms
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * Top-level Synthesis Banner evaluating cross-modal consensus or disagreement.
 */
function CrossModalSynthesisBanner({ detectorResponses }) {
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

  if (activeResults.length === 0) return null;

  const authenticList = activeResults.filter((r) => r.verdict === "authentic");
  const syntheticList = activeResults.filter((r) => r.verdict === "synthetic");

  const hasDisagreement = authenticList.length > 0 && syntheticList.length > 0;

  if (hasDisagreement) {
    return (
      <div className="p-4 rounded-xl bg-amber-950/40 border border-amber-500/50 space-y-2 animate-in fade-in duration-200">
        <div className="flex items-center gap-2.5 text-amber-300">
          <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0" />
          <h3 className="font-bold text-sm uppercase tracking-wider">
            Cross-Modal Disagreement Detected
          </h3>
        </div>
        <div className="text-xs text-amber-200/90 font-mono space-y-1 pl-7">
          <p>
            <strong className="text-emerald-400">Authentic ({authenticList.length}):</strong>{" "}
            {authenticList.map((r) => r.label).join(", ")}
          </p>
          <p>
            <strong className="text-rose-400">Synthetic ({syntheticList.length}):</strong>{" "}
            {syntheticList.map((r) => r.label).join(", ")}
          </p>
          <p className="text-[11px] text-amber-400/80 pt-1">
            Note: Disagreeing modalities require Month 2 debate layer & fusion weighting for automated resolution.
          </p>
        </div>
      </div>
    );
  }

  if (syntheticList.length > 0) {
    return (
      <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-500/50 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <ShieldAlert className="w-6 h-6 text-rose-400 flex-shrink-0" />
          <div>
            <h3 className="font-bold text-sm text-rose-200 uppercase tracking-wider">
              Cross-Modal Consensus: Synthetic Media Detected
            </h3>
            <p className="text-xs text-rose-300/80 font-mono">
              Agreed across active detectors ({syntheticList.map((r) => r.label).join(", ")})
            </p>
          </div>
        </div>
        <span className="px-2.5 py-1 rounded text-xs font-mono font-bold bg-rose-900/60 text-rose-200 border border-rose-700">
          SYNTHETIC
        </span>
      </div>
    );
  }

  if (authenticList.length > 0) {
    return (
      <div className="p-4 rounded-xl bg-emerald-950/40 border border-emerald-500/50 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <ShieldCheck className="w-6 h-6 text-emerald-400 flex-shrink-0" />
          <div>
            <h3 className="font-bold text-sm text-emerald-200 uppercase tracking-wider">
              Cross-Modal Consensus: Authentic Media Verified
            </h3>
            <p className="text-xs text-emerald-300/80 font-mono">
              Agreed across active detectors ({authenticList.map((r) => r.label).join(", ")})
            </p>
          </div>
        </div>
        <span className="px-2.5 py-1 rounded text-xs font-mono font-bold bg-emerald-900/60 text-emerald-200 border border-emerald-700">
          AUTHENTIC
        </span>
      </div>
    );
  }

  return (
    <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-700 flex items-center gap-3">
      <Info className="w-5 h-5 text-slate-400 flex-shrink-0" />
      <p className="text-xs text-slate-300 font-mono">
        Detector output evaluated. Review individual detector evidence cards below.
      </p>
    </div>
  );
}

export default function DetectorResultsGrid({ detectorResponses, fileName }) {
  const order = ["video_classifier", "rppg", "aasist", "syncnet"];
  const completedCount = order.filter((id) => detectorResponses?.[id]).length;

  return (
    <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-300">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300">
          Detector Evidence
          {fileName && (
            <span className="text-slate-500 font-normal font-mono text-xs ml-2">{fileName}</span>
          )}
        </h2>
        <span className="text-xs text-slate-500 font-mono">
          {completedCount}/{order.length} completed
        </span>
      </div>

      {/* Top Cross-Modal Disagreement / Consensus Banner */}
      <CrossModalSynthesisBanner detectorResponses={detectorResponses} />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {order.map((id) => (
          <DetectorCard key={id} id={id} response={detectorResponses?.[id]} />
        ))}
      </div>
    </div>
  );
}
