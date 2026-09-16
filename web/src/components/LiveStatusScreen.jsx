"use client";
// impeccable-disable gray-on-color

import React, { useEffect, useState } from "react";
import {
  Film,
  Activity,
  Mic,
  Video,
  CheckCircle2,
  Clock,
  Loader2,
  SkipForward,
  Cpu,
  Layers,
  ArrowRight,
  ShieldCheck,
} from "lucide-react";

/**
 * Metadata configuration for each of the four AEGIS detectors
 */
const DETECTOR_META = {
  video_classifier: {
    name: "Video Frame Classifier",
    subtitle: "Spatial Artifact & Face Boundary Analysis",
    modelBadge: "EfficientNet-B0 • FF++ c23",
    modality: "Video",
    icon: Film,
    runningMsg: "Extracting frame slices & evaluating facial boundary artifacts...",
    completeMsg: "Frame-level convolutional pass completed.",
  },
  aasist: {
    name: "AASIST Audio Detector",
    subtitle: "Voice Cloning & Spectral Spoofing Analysis",
    modelBadge: "Graph Attention Network • ASVspoof",
    modality: "Audio",
    icon: Mic,
    runningMsg: "Analyzing SincNet filterbanks & spectral graph attention...",
    completeMsg: "Acoustic feature extraction & graph inference finished.",
  },
  rppg: {
    name: "rPPG Pulse Consistency",
    subtitle: "Biological Blood Volume Pulse Extraction",
    modelBadge: "CHROM Algorithm • 0.7-4.0 Hz",
    modality: "Physiological",
    icon: Activity,
    runningMsg: "Filtering facial skin micro-reflections & estimating BVP spectra...",
    completeMsg: "Cardiac rhythm frequency & spectral purity measured.",
  },
  syncnet: {
    name: "SyncNet Audio-Visual",
    subtitle: "Lip-Motion to Speech Phoneme Synchronization",
    modelBadge: "Two-Stream CNN • Temporal Offset",
    modality: "Multimodal",
    icon: Video,
    runningMsg: "Calculating cross-modal audio-lip distance across temporal offsets...",
    completeMsg: "Temporal alignment & lip-sync offset profile determined.",
  },
};

export default function LiveStatusScreen({
  file,
  statusData,
  onComplete,
}) {
  const [elapsed, setElapsed] = useState(0);

  // Live timer tick
  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed((prev) => prev + 100);
    }, 100);
    return () => clearInterval(timer);
  }, []);

  const formatElapsed = (ms) => {
    const sec = (ms / 1000).toFixed(1);
    return `${sec}s`;
  };

  const detectors = statusData?.detectors || {};
  const progressPercent = statusData?.progress_percent || 0;
  const isAllComplete = statusData?.overall_status === "completed";

  return (
    <div className="w-full space-y-8 animate-in fade-in duration-300">
      {/* Active Pipeline Header */}
      <div className="bg-slate-900/80 border border-slate-800/80 backdrop-blur-xl rounded-2xl p-6 shadow-2xl relative overflow-hidden">
        {/* Subtle top edge highlight */}
        <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-cyan-500/40 to-transparent" />

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="flex h-2.5 w-2.5 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-cyan-500"></span>
              </span>
              <span className="text-xs font-mono font-semibold uppercase tracking-wider text-cyan-400">
                Layer B • Real-Time Detector Orchestration
              </span>
            </div>
            <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
              <span className="truncate max-w-md">{file?.name || "Processing Media"}</span>
            </h2>
            <p className="text-xs text-slate-400 font-mono">
              Job ID: <span className="text-slate-300">{statusData?.job_id?.slice(0, 18)}...</span>
            </p>
          </div>

          {/* Progress & Live Latency Display */}
          <div className="flex items-center gap-4 bg-slate-950/60 border border-slate-800/60 rounded-xl px-4 py-2.5">
            <div className="text-right font-mono">
              <div className="text-[10px] uppercase text-slate-400 font-semibold tracking-wider">
                Total Elapsed
              </div>
              <div className="text-base font-bold text-cyan-400 flex items-center gap-1.5 justify-end">
                <Clock className="w-3.5 h-3.5 text-cyan-400" />
                <span>{formatElapsed(statusData?.elapsed_ms || elapsed)}</span>
              </div>
            </div>
            <div className="h-8 w-[1px] bg-slate-800" />
            <div className="text-right font-mono min-w-[60px]">
              <div className="text-[10px] uppercase text-slate-400 font-semibold tracking-wider">
                Progress
              </div>
              <div className="text-base font-bold text-slate-200">
                {progressPercent}%
              </div>
            </div>
          </div>
        </div>

        {/* Dynamic Progress Bar */}
        <div className="mt-5 space-y-1.5">
          <div className="w-full bg-slate-950/80 rounded-full h-2 overflow-hidden border border-slate-800/80">
            <div
              className="bg-gradient-to-r from-cyan-500 via-sky-400 to-emerald-400 h-full rounded-full transition-all duration-300 ease-out shadow-[0_0_12px_rgba(6,182,212,0.4)]"
              style={{ width: `${Math.max(5, progressPercent)}%` }}
            />
          </div>
          <div className="flex justify-between text-[11px] font-mono text-slate-400">
            <span>Dispatched via Rule-Based Policy</span>
            <span>
              {isAllComplete
                ? "All 4 Detectors Concluded"
                : "Parallel Evaluation Active"}
            </span>
          </div>
        </div>
      </div>

      {/* 4-Detector Live Status Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {Object.entries(DETECTOR_META).map(([key, meta]) => {
          const detectorState = detectors[key] || { status: "queued" };
          const Icon = meta.icon;
          const status = detectorState.status;

          // Status styling logic
          let statusBadge;
          let cardBorder;
          let statusMessage;

          if (status === "complete") {
            cardBorder = "border-emerald-500/30 bg-slate-900/70 hover:border-emerald-500/50";
            statusBadge = (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 shadow-[0_0_8px_rgba(16,185,129,0.15)]">
                <CheckCircle2 className="w-3.5 h-3.5" />
                COMPLETE
              </span>
            );
            statusMessage = detectorState.claim || meta.completeMsg;
          } else if (status === "running") {
            cardBorder = "border-cyan-500/50 bg-slate-900/90 shadow-[0_0_20px_rgba(6,182,212,0.12)] ring-1 ring-cyan-500/30";
            statusBadge = (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono font-semibold bg-cyan-500/15 text-cyan-300 border border-cyan-500/40">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-cyan-400" />
                ANALYZING
              </span>
            );
            statusMessage = meta.runningMsg;
          } else if (status === "skipped") {
            cardBorder = "border-slate-800/60 bg-slate-950/40 opacity-70";
            statusBadge = (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono font-semibold bg-slate-800/60 text-slate-400 border border-slate-700/40">
                <SkipForward className="w-3.5 h-3.5" />
                SKIPPED
              </span>
            );
            statusMessage = detectorState.claim || "Not applicable for this media modality.";
          } else {
            // Queued
            cardBorder = "border-slate-800/80 bg-slate-900/40";
            statusBadge = (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono font-semibold bg-slate-800/60 text-slate-400 border border-slate-700/50">
                <span className="w-2 h-2 rounded-full bg-amber-400/80 animate-pulse" />
                QUEUED
              </span>
            );
            statusMessage = detectorState.claim || "Awaiting execution dispatch...";
          }

          return (
            <div
              key={key}
              className={`border rounded-2xl p-5 transition-all duration-300 flex flex-col justify-between relative overflow-hidden backdrop-blur-md ${cardBorder}`}
            >
              <div>
                {/* Header: Title, Icon & Status */}
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div className="flex items-center gap-3">
                    <div
                      className={`p-2.5 rounded-xl border ${
                        status === "running"
                          ? "bg-cyan-500/15 border-cyan-500/40 text-cyan-300"
                          : status === "complete"
                          ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                          : "bg-slate-800/60 border-slate-700/50 text-slate-400"
                      }`}
                    >
                      <Icon className="w-5 h-5" />
                    </div>
                    <div>
                      <h3 className="text-base font-semibold text-slate-100 flex items-center gap-2">
                        {meta.name}
                      </h3>
                      <p className="text-xs text-slate-400 font-mono">
                        {meta.modelBadge}
                      </p>
                    </div>
                  </div>
                  <div>{statusBadge}</div>
                </div>

                {/* Subtitle */}
                <p className="text-xs text-slate-400 mb-3 font-sans">
                  {meta.subtitle}
                </p>

                {/* Live Action Message Box */}
                <div className="bg-slate-950/60 rounded-xl p-3 border border-slate-800/60 text-xs font-mono text-slate-300 min-h-[44px] flex items-center">
                  <span className="line-clamp-2">{statusMessage}</span>
                </div>
              </div>

              {/* Telemetry Footer */}
              <div className="mt-4 pt-3 border-t border-slate-800/60 flex items-center justify-between text-xs font-mono">
                <div className="flex items-center gap-1.5 text-slate-400">
                  <Cpu className="w-3.5 h-3.5 text-slate-400" />
                  <span>
                    {detectorState.ram_usage_mb
                      ? `${detectorState.ram_usage_mb} MB RAM`
                      : "Memory: --"}
                  </span>
                </div>

                <div className="flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-slate-400" />
                  <span
                    className={
                      status === "complete"
                        ? "text-emerald-400 font-bold"
                        : "text-slate-400"
                    }
                  >
                    {detectorState.latency_ms !== null && detectorState.latency_ms !== undefined
                      ? `${detectorState.latency_ms} ms`
                      : status === "running"
                      ? "Measuring..."
                      : "--"}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Action Footer: Auto-Transition or Manual Proceed */}
      {isAllComplete && (
        <div className="bg-gradient-to-r from-cyan-950/40 via-slate-900/80 to-emerald-950/40 border border-cyan-500/30 rounded-2xl p-5 flex flex-col sm:flex-row items-center justify-between gap-4 shadow-xl animate-in zoom-in-95 duration-300">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-emerald-400">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <h4 className="text-sm font-semibold text-slate-100">
                Inference Complete Across All Available Detectors
              </h4>
              <p className="text-xs text-slate-400 font-mono">
                Evidence extracted and normalized to AEGIS forensic contract.
              </p>
            </div>
          </div>

          <button
            onClick={onComplete}
            className="w-full sm:w-auto flex items-center justify-center gap-2 py-3 px-6 rounded-xl font-bold text-sm bg-gradient-to-r from-cyan-500 to-emerald-400 text-slate-950 hover:opacity-95 shadow-lg shadow-cyan-500/20 active:scale-[0.98] transition-all cursor-pointer"
          >
            <span>View 4-Detector Results Grid</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}
