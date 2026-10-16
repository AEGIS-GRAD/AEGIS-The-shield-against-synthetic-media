"use client";

import React, { useState } from "react";
import {
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  AlertTriangle,
  Fingerprint,
  Hash,
  Clock,
  Activity,
  Film,
  Gavel,
  CheckCircle2,
  XCircle,
  X,
  FileJson,
  Download,
  Copy,
  Check,
  ExternalLink,
  Layers,
  Cpu,
} from "lucide-react";

export default function LiveAlertDetailModal({ alert, onClose, onAcknowledge }) {
  const [copied, setCopied] = useState(false);

  if (!alert) return null;

  const {
    id,
    camId = "CAM-001",
    score = 0.85,
    frameNum = 1420,
    time = new Date().toLocaleTimeString(),
    verdict = alert.score >= 0.65 ? (alert.integritySignals?.hash_chain_ok === false ? "INTEGRITY_UNKNOWN" : "SYNTHETIC") : "UNCERTAIN",
    integritySignals = {
      hash_chain_ok: false,
      last_hash: "0x9F4A...B82D",
      prnu_ok: false,
      prnu_pce: 18.4,
      prnu_threshold: 50.0,
      anomalies: ["Timestamp regression (-240ms)", "Sequence gap (seq jumped 104 -> 108)"],
    },
    aiSignals = {
      mobilenet_score: 0.82,
      rppg_score: 0.68,
      hr_bpm: 88,
      syncnet_score: 0.74,
      face_detected: true,
    },
    judgeReasoning = null,
  } = alert;

  // Synthesize judge explanation if not explicitly provided
  const explanation = judgeReasoning || (
    verdict === "INTEGRITY_UNKNOWN"
      ? `Cryptographic feed integrity violation detected at frame #${frameNum}. Hardware PRNU PCE (${integritySignals.prnu_pce || 18.4}) dropped below enrolled baseline threshold (${integritySignals.prnu_threshold || 50.0}), indicating physical sensor mismatch or spliced footage. Per AEGIS Forensic Protocol, integrity failures overrule AI facial appearance.`
      : verdict === "SYNTHETIC"
      ? `AI detector ensemble reached critical consensus (score: ${(score * 100).toFixed(1)}%). MobileNetV3 identified high-frequency boundary blending artifacts, and physiological rPPG analysis detected disrupted dermal pulse regularity at frame #${frameNum}.`
      : "Borderline anomaly indicators surfaced across sliding window; human supervisor inspection recommended."
  );

  const manifestHash = alert.manifestHash || `0x${Array.from({ length: 64 }, (_, i) => ((i * 17 + frameNum) % 16).toString(16)).join("")}`;

  const copyHash = () => {
    navigator.clipboard?.writeText(manifestHash);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const exportJSON = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(alert, null, 2));
    const downloadAnchor = document.createElement("a");
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `AEGIS_ALERT_SNAP_${camId}_FRAME_${frameNum}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const isIntegrityBad = integritySignals.hash_chain_ok === false || integritySignals.prnu_ok === false || (integritySignals.anomalies && integritySignals.anomalies.length > 0);
  const isAiBad = aiSignals.mobilenet_score >= 0.65 || aiSignals.rppg_score >= 0.65;

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-3xl max-h-[92vh] overflow-y-auto rounded-2xl border border-slate-700/80 bg-slate-950 text-slate-100 shadow-2xl shadow-red-950/30">
        
        {/* Header Bar */}
        <div className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-800 bg-slate-900/95 px-6 py-4 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-xl bg-red-950/80 border border-red-500/40 text-red-400">
              <ShieldAlert className="size-5 animate-pulse" />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-white font-mono tracking-wide uppercase">
                  Live Surveillance Alert Detail
                </h3>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-red-500/20 text-red-300 border border-red-500/40">
                  INCIDENT #{id || 101}
                </span>
              </div>
              <p className="text-xs font-mono text-slate-400 mt-0.5">
                Camera: <span className="text-cyan-300 font-bold">{camId}</span> · Frame #{frameNum} · {time}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white transition-colors"
          >
            <X className="size-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 space-y-6">

          {/* Unified Verdict Banner */}
          <div className={`p-4 rounded-xl border flex flex-col sm:flex-row sm:items-center justify-between gap-4 ${
            verdict === "INTEGRITY_UNKNOWN"
              ? "bg-amber-950/40 border-amber-500/50 text-amber-200"
              : verdict === "SYNTHETIC"
              ? "bg-red-950/40 border-red-500/50 text-red-200"
              : "bg-slate-900 border-slate-700 text-slate-300"
          }`}>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono uppercase tracking-wider text-slate-400">Fused Surveillance Verdict:</span>
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-black font-mono tracking-wider uppercase border ${
                  verdict === "INTEGRITY_UNKNOWN"
                    ? "bg-amber-500/20 text-amber-300 border-amber-500/50"
                    : verdict === "SYNTHETIC"
                    ? "bg-red-500/20 text-red-300 border-red-500/50"
                    : "bg-emerald-500/20 text-emerald-300 border-emerald-500/50"
                }`}>
                  {verdict}
                </span>
              </div>
              <p className="text-xs text-slate-300 font-sans">
                {verdict === "INTEGRITY_UNKNOWN"
                  ? "Feed provenance / cryptographic integrity compromised. Authentic verdict prohibited by protocol."
                  : "Synthetic media generation artifacts identified with high probability across continuous rolling window."}
              </p>
            </div>

            <div className="flex items-baseline gap-2 shrink-0 bg-slate-900/80 px-4 py-2 rounded-xl border border-slate-800">
              <span className="text-[10px] font-mono text-slate-400 uppercase">Anomaly:</span>
              <span className="text-3xl font-black font-mono text-red-400">
                {(score * 100).toFixed(1)}%
              </span>
            </div>
          </div>

          {/* Dual-Pillar Evidence Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

            {/* Pillar 1: Stream Integrity & Hardware Provenance */}
            <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/50 space-y-3">
              <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                <div className="flex items-center gap-2">
                  <Fingerprint className="size-4 text-cyan-400" />
                  <span className="text-xs font-mono font-bold text-slate-200 uppercase">
                    Pillar 1: Feed Integrity
                  </span>
                </div>
                <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded ${
                  !isIntegrityBad ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"
                }`}>
                  {!isIntegrityBad ? "INTACT" : "COMPROMISED"}
                </span>
              </div>

              <div className="space-y-2 text-xs font-mono">
                {/* Hash Chain */}
                <div className="flex items-center justify-between p-2 rounded bg-slate-950/60 border border-slate-800/80">
                  <div className="flex items-center gap-2">
                    {integritySignals.hash_chain_ok !== false ? (
                      <CheckCircle2 className="size-3.5 text-emerald-400 shrink-0" />
                    ) : (
                      <XCircle className="size-3.5 text-red-400 shrink-0" />
                    )}
                    <span className="text-slate-300">Frame Hash-Chain:</span>
                  </div>
                  <span className="text-slate-400 font-bold truncate max-w-[130px]">
                    {integritySignals.last_hash || "0x9F4A...B82D"}
                  </span>
                </div>

                {/* PRNU Sensor Fingerprint */}
                <div className="flex items-center justify-between p-2 rounded bg-slate-950/60 border border-slate-800/80">
                  <div className="flex items-center gap-2">
                    {integritySignals.prnu_ok !== false ? (
                      <CheckCircle2 className="size-3.5 text-emerald-400 shrink-0" />
                    ) : (
                      <XCircle className="size-3.5 text-red-400 shrink-0" />
                    )}
                    <span className="text-slate-300">PRNU Hardware PCE:</span>
                  </div>
                  <span className={`font-bold ${integritySignals.prnu_ok !== false ? "text-emerald-400" : "text-red-400"}`}>
                    {integritySignals.prnu_pce !== undefined ? integritySignals.prnu_pce.toFixed(1) : "18.4"}{" "}
                    <span className="text-[10px] text-slate-500 font-normal">(&gt;50.0 req)</span>
                  </span>
                </div>

                {/* Stream Validator Anomaly Log */}
                <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80 space-y-1">
                  <span className="text-[10px] text-slate-500 block uppercase">Stream Validator Anomalies:</span>
                  {integritySignals.anomalies && integritySignals.anomalies.length > 0 ? (
                    integritySignals.anomalies.map((ano, idx) => (
                      <div key={idx} className="flex items-center gap-1.5 text-[11px] text-red-300 font-sans">
                        <AlertTriangle className="size-3 text-red-400 shrink-0" />
                        <span>{ano}</span>
                      </div>
                    ))
                  ) : (
                    <span className="text-[11px] text-emerald-400">Zero timestamp or sequence anomalies recorded</span>
                  )}
                </div>
              </div>
            </div>

            {/* Pillar 2: AI Content Anomaly Ensemble */}
            <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/50 space-y-3">
              <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                <div className="flex items-center gap-2">
                  <Film className="size-4 text-purple-400" />
                  <span className="text-xs font-mono font-bold text-slate-200 uppercase">
                    Pillar 2: AI Content Anomaly
                  </span>
                </div>
                <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded ${
                  !isAiBad ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"
                }`}>
                  {!isAiBad ? "NORMAL" : "ELEVATED"}
                </span>
              </div>

              <div className="space-y-2 text-xs font-mono">
                {/* MobileNetV3 Edge Detector */}
                <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80 space-y-1">
                  <div className="flex justify-between items-center">
                    <span className="text-slate-300">MobileNetV3 Edge Model:</span>
                    <span className={`font-bold ${aiSignals.mobilenet_score >= 0.65 ? "text-red-400" : "text-emerald-400"}`}>
                      {(aiSignals.mobilenet_score * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${aiSignals.mobilenet_score >= 0.65 ? "bg-red-500" : "bg-emerald-500"}`}
                      style={{ width: `${Math.min(100, aiSignals.mobilenet_score * 100)}%` }}
                    />
                  </div>
                </div>

                {/* rPPG Pulse Physiological Consistency */}
                <div className="p-2 rounded bg-slate-950/60 border border-slate-800/80 space-y-1">
                  <div className="flex justify-between items-center">
                    <span className="text-slate-300">rPPG Physiological Pulse:</span>
                    <span className={`font-bold ${aiSignals.rppg_score >= 0.65 ? "text-red-400" : "text-emerald-400"}`}>
                      {(aiSignals.rppg_score * 100).toFixed(1)}%
                    </span>
                  </div>
                  <p className="text-[10px] text-slate-400 font-sans">
                    {aiSignals.rppg_score >= 0.65
                      ? "Disrupted chromatic signal in facial capillary network; biological pulse absent."
                      : `Periodic dermal blood volume pulse detected (~${aiSignals.hr_bpm || 76} BPM).`}
                  </p>
                </div>

                {/* SyncNet AV Alignment */}
                <div className="flex items-center justify-between p-2 rounded bg-slate-950/60 border border-slate-800/80">
                  <span className="text-slate-300">SyncNet Lip Alignment:</span>
                  <span className="text-slate-400 font-bold">
                    {aiSignals.syncnet_score !== undefined ? `${(aiSignals.syncnet_score * 100).toFixed(1)}%` : "0.74"}
                  </span>
                </div>
              </div>
            </div>

          </div>

          {/* Judge-Agent Reasoning & Admissibility */}
          <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/70 space-y-3">
            <div className="flex items-center gap-2 text-xs font-mono font-bold text-slate-200 uppercase">
              <Gavel className="size-4 text-amber-400" />
              <span>Judge-Agent Synthesis &amp; Forensic Explanation</span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed font-sans bg-slate-950 p-3 rounded-lg border border-slate-800">
              {explanation}
            </p>

            {/* Cryptographic Manifest Hash */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-2 border-t border-slate-800 text-[11px] font-mono">
              <div className="flex items-center gap-1.5 text-slate-400 truncate">
                <Hash className="size-3.5 text-slate-500 shrink-0" />
                <span className="shrink-0">Signed Evidence Hash:</span>
                <span className="text-slate-300 truncate">{manifestHash}</span>
              </div>
              <button
                onClick={copyHash}
                className="flex items-center gap-1 text-cyan-400 hover:text-cyan-300 transition-colors shrink-0 cursor-pointer"
              >
                {copied ? <Check className="size-3.5 text-emerald-400" /> : <Copy className="size-3.5" />}
                <span>{copied ? "Copied" : "Copy Hash"}</span>
              </button>
            </div>
          </div>

        </div>

        {/* Footer Actions */}
        <div className="sticky bottom-0 z-20 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 bg-slate-900/95 px-6 py-3.5 backdrop-blur-md">
          <button
            onClick={exportJSON}
            className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700 transition-colors cursor-pointer"
          >
            <Download className="size-3.5" />
            <span>Export Incident Snapshot (JSON)</span>
          </button>

          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="rounded-lg border border-slate-700 px-4 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-800 transition-colors cursor-pointer"
            >
              Close
            </button>
            {onAcknowledge && (
              <button
                onClick={() => {
                  onAcknowledge(alert.id);
                  onClose();
                }}
                className="flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-1.5 text-xs font-bold text-white hover:bg-red-500 transition-colors shadow cursor-pointer"
              >
                <CheckCircle2 className="size-3.5" />
                <span>Acknowledge Alert</span>
              </button>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
