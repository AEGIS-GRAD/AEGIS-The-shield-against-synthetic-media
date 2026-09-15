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
} from "lucide-react";

/**
 * DetectorResultsGrid
 * --------------------
 * Renders all four AEGIS detector results (video_classifier, rPPG, AASIST,
 * SyncNet) side by side for a single submitted file, once the orchestrator
 * has returned them.
 *
 * IMPORTANT — schema note:
 * shared/json-api-contracts-schema/detector_response.schema.json is strict
 * and locked: the orchestrator rejects any response with fields outside the
 * schema. There is no dedicated "status" or "not_applicable" field.
 *
 * Convention used here (confirm with the backend/orchestrator team before
 * relying on it in production): a detector that cannot run on the given
 * media signals this through the existing `evidence.flags` array by
 * including the string "not_applicable", with a human-readable reason in
 * `evidence.claim`. This keeps every response 100% schema-valid.
 *
 * Real DetectorResponse shape (per shared/json-api-contracts-schema):
 * {
 *   job_id: string,
 *   confidence: number,       // 0.0 = Authentic, 1.0 = Synthetic
 *   raw_score: number,
 *   latency_ms: number,
 *   ram_usage_mb?: number,
 *   vram_usage_mb?: number,
 *   model_version: string,
 *   evidence: { claim: string, flags?: string[] }
 * }
 *
 * This component expects an array of { id, label, modality, response }
 * where `response` is either a DetectorResponse object above, `null`
 * (still processing), or a plain Error-like object with `.message` (the
 * detector call itself failed — a real error, distinct from not_applicable).
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
      <div className="p-5 rounded-xl border border-orange-900/50 bg-orange-950/20 flex flex-col h-full">
        <CardHeader Icon={Icon} label={meta.label} modality={meta.modality} />
        <div className="flex-1 flex flex-col items-center justify-center text-center py-6 space-y-2">
          <ShieldQuestion className="w-7 h-7 text-orange-400" />
          <p className="text-sm font-semibold text-orange-300">Detector Error</p>
          <p className="text-xs text-orange-400/70 max-w-[22ch]">{response.error}</p>
        </div>
      </div>
    );
  }

  // ---- Not applicable: signaled via evidence.flags, kept schema-valid ----
  const flags = response.evidence?.flags ?? [];
  if (flags.includes(NOT_APPLICABLE_FLAG)) {
    return (
      <div className="p-5 rounded-xl border border-dashed border-slate-800 bg-slate-900/40 flex flex-col h-full">
        <CardHeader Icon={Icon} label={meta.label} modality={meta.modality} />
        <div className="flex-1 flex flex-col items-center justify-center text-center py-6 space-y-2">
          <MinusCircle className="w-7 h-7 text-slate-600" />
          <p className="text-sm font-semibold text-slate-500">Not Applicable</p>
          <p className="text-xs text-slate-600 max-w-[22ch]">{response.evidence?.claim}</p>
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

export default function DetectorResultsGrid({ detectorResponses, fileName }) {
  // detectorResponses: { video_classifier: DetectorResponse|null, rppg: ..., aasist: ..., syncnet: ... }
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

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {order.map((id) => (
          <DetectorCard key={id} id={id} response={detectorResponses?.[id]} />
        ))}
      </div>
    </div>
  );
}
