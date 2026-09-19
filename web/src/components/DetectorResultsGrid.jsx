"use client";

import React from "react";
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
    badge: "bg-emerald-950/70 text-emerald-400 border border-emerald-800/60",
    barColor: "bg-emerald-500",
  },
  synthetic: {
    icon: ShieldAlert,
    label: "SYNTHETIC",
    badge: "bg-rose-950/70 text-rose-400 border border-rose-800/60",
    barColor: "bg-rose-500",
  },
  inconclusive: {
    icon: ShieldQuestion,
    label: "INCONCLUSIVE",
    badge: "bg-amber-950/70 text-amber-400 border border-amber-800/60",
    barColor: "bg-amber-500",
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
 * Combines media metadata, consensus verdict, and quick actions into ONE clean header
 */
function ForensicVerdictBanner({ detectorResponses, fileName, fileSize, onViewLogs, onExportJson }) {
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

  let bannerStyle = "border-emerald-500/40 bg-emerald-950/20";
  let Icon = ShieldCheck;
  let iconColor = "text-emerald-400 bg-emerald-500/10 border-emerald-500/30";
  let title = "Cross-Modal Consensus: Authentic Media Verified";
  let verdictTag = "AUTHENTIC";
  let tagStyle = "bg-emerald-950/80 text-emerald-300 border-emerald-700/60";
  let summary = `All ${activeResults.length} active detectors agree media shows natural characteristics.`;

  if (hasDisagreement) {
    bannerStyle = "border-amber-500/40 bg-amber-950/20";
    Icon = AlertTriangle;
    iconColor = "text-amber-400 bg-amber-500/10 border-amber-500/30";
    title = "Cross-Modal Disagreement Detected";
    verdictTag = "DEBATE REQUIRED";
    tagStyle = "bg-amber-950/80 text-amber-300 border-amber-700/60";
    summary = `Conflicting claims: ${authenticList.length} Authentic vs. ${syntheticList.length} Synthetic. Layer C Debate queued.`;
  } else if (syntheticList.length > 0) {
    bannerStyle = "border-rose-500/40 bg-rose-950/20";
    Icon = ShieldAlert;
    iconColor = "text-rose-400 bg-rose-500/10 border-rose-500/30";
    title = "Cross-Modal Consensus: Synthetic Media Detected";
    verdictTag = "SYNTHETIC";
    tagStyle = "bg-rose-950/80 text-rose-300 border-rose-700/60";
    summary = `Agreed across active detectors (${syntheticList.map((r) => r.label.split(" ")[0]).join(", ")}).`;
  }

  return (
    <div className={`p-4 sm:p-5 rounded-xl border ${bannerStyle} space-y-3`}>
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Left: Verdict Status */}
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <div className={`p-2.5 rounded-xl border flex-shrink-0 ${iconColor}`}>
            <Icon className="w-5 h-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-bold text-sm sm:text-base text-slate-100 truncate">
                {title}
              </h3>
              <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${tagStyle}`}>
                {verdictTag}
              </span>
            </div>
            <p className="text-xs text-slate-300 mt-0.5 line-clamp-1">{summary}</p>
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2 flex-shrink-0 self-end md:self-center">
          {onViewLogs && (
            <button
              onClick={onViewLogs}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono text-slate-300 hover:text-white bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 transition-colors cursor-pointer"
            >
              <Terminal className="w-3.5 h-3.5 text-slate-400" />
              <span>Logs</span>
            </button>
          )}

          {onExportJson && (
            <button
              onClick={onExportJson}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono text-slate-100 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 transition-colors cursor-pointer"
            >
              <Download className="w-3.5 h-3.5 text-cyan-400" />
              <span>Export JSON</span>
            </button>
          )}
        </div>
      </div>

      {/* Sub-bar: Clean Media Details */}
      <div className="pt-2 border-t border-slate-800/50 flex items-center justify-between text-[11px] font-mono text-slate-400">
        <div className="flex items-center gap-2 min-w-0 truncate">
          <span className="text-slate-300 font-semibold truncate" title={fileName}>
            {truncateMiddle(fileName, 32)}
          </span>
          {fileSize && (
            <>
              <span>•</span>
              <span>{fileSize}</span>
            </>
          )}
        </div>
        <span className="text-slate-400 flex-shrink-0 ml-2">
          {activeResults.length} Active Modalities
        </span>
      </div>
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

      {/* Grid Title Bar (Clean, single-line) */}
      <div className="flex items-center justify-between pt-1">
        <h2 className="text-xs sm:text-sm font-bold text-slate-200 uppercase tracking-wider font-mono">
          Layer B Detector Breakdown
        </h2>
        <span className="text-[11px] font-mono text-slate-400">
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
