"use client";

import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ShieldCheck,
  ShieldAlert,
  HelpCircle,
  Clock,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types (JSDoc — no TS compiler needed, but provides IDE inference)
// ---------------------------------------------------------------------------
/**
 * @typedef {"authentic" | "manipulated" | "inconclusive"} Verdict
 *
 * @typedef {Object} DetectorResult
 * @property {Verdict}  verdict
 * @property {number}   confidence   – 0–100
 * @property {string}   evidenceText – short explanation
 * @property {number}   latencyMs    – processing time in ms
 * @property {string}   detectorName – e.g. "VideoDetector v1"
 * @property {string}   timestamp    – ISO string
 */

// ---------------------------------------------------------------------------
// Design tokens – mirroring the existing palette exactly
// ---------------------------------------------------------------------------
const VERDICT_CONFIG = {
  authentic: {
    Icon: ShieldCheck,
    label: "Authentic",
    // badge
    badgeBg: "bg-emerald-950/60",
    badgeBorder: "border-emerald-800/50",
    badgeText: "text-emerald-300",
    iconColor: "text-emerald-400",
    // card accent
    cardBorder: "border-emerald-800/40",
    cardBg: "bg-emerald-950/20",
    // bar
    barColor: "bg-emerald-500",
    barGlow: "shadow-emerald-500/40",
  },
  manipulated: {
    Icon: ShieldAlert,
    label: "Manipulated",
    badgeBg: "bg-rose-950/60",
    badgeBorder: "border-rose-800/50",
    badgeText: "text-rose-300",
    iconColor: "text-rose-400",
    cardBorder: "border-rose-800/40",
    cardBg: "bg-rose-950/20",
    barColor: "bg-rose-500",
    barGlow: "shadow-rose-500/40",
  },
  inconclusive: {
    Icon: HelpCircle,
    label: "Inconclusive",
    badgeBg: "bg-amber-950/60",
    badgeBorder: "border-amber-800/50",
    badgeText: "text-amber-300",
    iconColor: "text-amber-400",
    cardBorder: "border-amber-800/40",
    cardBg: "bg-amber-950/20",
    barColor: "bg-amber-500",
    barGlow: "shadow-amber-500/40",
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatTimestamp(iso) {
  try {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Animated confidence progress bar with count-up percentage */
function ConfidenceBar({ confidence, verdict }) {
  const [displayValue, setDisplayValue] = useState(0);
  const cfg = VERDICT_CONFIG[verdict] ?? VERDICT_CONFIG.inconclusive;

  // Count-up animation synced with bar fill (~800ms ease-out)
  useEffect(() => {
    let start = null;
    const duration = 800;
    const target = confidence;

    function step(timestamp) {
      if (!start) start = timestamp;
      const elapsed = timestamp - start;
      const progress = Math.min(elapsed / duration, 1);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplayValue(Math.round(eased * target));
      if (progress < 1) requestAnimationFrame(step);
    }

    const raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [confidence]);

  return (
    <div className="space-y-1.5">
      {/* Label row */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
          Confidence
        </span>
        <span className={`text-sm font-mono font-bold tabular-nums ${cfg.badgeText}`}>
          {displayValue}%
        </span>
      </div>

      {/* Track */}
      <div className="relative h-2 w-full rounded-full bg-slate-800/80 overflow-hidden">
        <motion.div
          className={`absolute inset-y-0 left-0 rounded-full ${cfg.barColor}`}
          initial={{ width: "0%" }}
          animate={{ width: `${confidence}%` }}
          transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>
    </div>
  );
}

/** Pill-shaped verdict badge with icon + entrance animation */
function VerdictBadge({ verdict }) {
  const cfg = VERDICT_CONFIG[verdict] ?? VERDICT_CONFIG.inconclusive;
  const { Icon } = cfg;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.88 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className={`
        inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-semibold
        border ${cfg.badgeBg} ${cfg.badgeBorder} ${cfg.badgeText}
      `}
    >
      <Icon className={`w-4 h-4 ${cfg.iconColor} flex-shrink-0`} />
      {cfg.label}
    </motion.div>
  );
}

/** Small monospace latency badge — bottom-right */
function LatencyBadge({ latencyMs }) {
  return (
    <div className="flex justify-end">
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700/50 text-[10px] font-mono text-slate-500">
        <Clock className="w-3 h-3 text-slate-600" />
        {latencyMs.toLocaleString()} ms
      </span>
    </div>
  );
}

/** Skeleton shimmer — matches populated card dimensions exactly */
function CardSkeleton() {
  return (
    <div
      className="
        relative w-full max-w-[420px] rounded-2xl border border-slate-800/80
        bg-[#111827]/80 backdrop-blur-xl p-6 shadow-2xl shadow-black/50
        overflow-hidden
      "
      aria-busy="true"
      aria-label="Loading detector result"
    >
      {/* Shimmer sweep */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "linear-gradient(90deg, transparent 0%, rgba(148,163,184,0.07) 50%, transparent 100%)",
          animation: "aegis-shimmer 1.6s infinite",
        }}
      />

      <div className="space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="h-3.5 w-32 rounded-full bg-slate-800" />
          <div className="h-3 w-16 rounded-full bg-slate-800" />
        </div>
        {/* Verdict badge */}
        <div className="h-8 w-28 rounded-full bg-slate-800" />
        {/* Confidence bar */}
        <div className="space-y-1.5">
          <div className="flex justify-between">
            <div className="h-2.5 w-16 rounded bg-slate-800" />
            <div className="h-2.5 w-8 rounded bg-slate-800" />
          </div>
          <div className="h-2 w-full rounded-full bg-slate-800" />
        </div>
        {/* Evidence text */}
        <div className="space-y-1.5 pt-1">
          <div className="h-2.5 w-full rounded bg-slate-800" />
          <div className="h-2.5 w-5/6 rounded bg-slate-800" />
          <div className="h-2.5 w-4/6 rounded bg-slate-800" />
        </div>
        {/* Latency */}
        <div className="flex justify-end">
          <div className="h-4 w-16 rounded bg-slate-800" />
        </div>
      </div>
    </div>
  );
}

/** Empty / no-result state */
function CardEmpty() {
  return (
    <div
      className="
        w-full max-w-[420px] rounded-2xl border border-dashed border-slate-800
        bg-[#111827]/60 backdrop-blur-xl p-8 shadow-xl shadow-black/30
        flex flex-col items-center justify-center gap-3 text-center min-h-[200px]
      "
      aria-label="No result available"
    >
      <div className="p-3 rounded-full bg-slate-800/60 border border-slate-700/50">
        <HelpCircle className="w-6 h-6 text-slate-600" />
      </div>
      <p className="text-sm font-medium text-slate-500">No result available</p>
      <p className="text-xs text-slate-600 font-mono">
        Run analysis to see detector evidence
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stagger animation variants
// ---------------------------------------------------------------------------
const containerVariants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.07,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.3, ease: "easeOut" },
  },
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * DetectorResultCard
 *
 * @param {Object}  props
 * @param {DetectorResult|null} props.result     – pass null for empty state
 * @param {boolean}             props.isLoading  – renders skeleton when true
 */
export default function DetectorResultCard({ result, isLoading = false }) {
  // Loading state
  if (isLoading) return <CardSkeleton />;

  // Empty state
  if (!result) return <CardEmpty />;

  const cfg = VERDICT_CONFIG[result.verdict] ?? VERDICT_CONFIG.inconclusive;

  return (
    <AnimatePresence mode="wait">
      <motion.article
        key={result.detectorName + result.timestamp}
        className={`
          group relative w-full max-w-[420px] rounded-2xl border shadow-2xl shadow-black/50
          backdrop-blur-xl p-6
          transition-all duration-150 ease-out
          hover:-translate-y-0.5 hover:shadow-[0_28px_48px_rgba(0,0,0,0.6)]
          ${cfg.cardBorder} ${cfg.cardBg}
          bg-[#111827]/80
        `}
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        aria-label={`Detector result from ${result.detectorName}: ${cfg.label}`}
      >
        {/* Subtle accent glow strip — top edge */}
        <div
          className={`absolute inset-x-0 top-0 h-px rounded-t-2xl opacity-60 ${cfg.barColor}`}
        />

        <motion.div
          className="space-y-4"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          {/* ── Header: detector name + timestamp ── */}
          <motion.div
            variants={itemVariants}
            className="flex items-start justify-between gap-2"
          >
            <p className="text-sm font-semibold text-slate-200 leading-tight">
              {result.detectorName}
            </p>
            <time
              dateTime={result.timestamp}
              className="text-[10px] font-mono text-slate-500 flex-shrink-0 mt-0.5"
              suppressHydrationWarning
            >
              {formatTimestamp(result.timestamp)}
            </time>
          </motion.div>

          {/* ── Verdict badge ── */}
          <motion.div variants={itemVariants}>
            <VerdictBadge verdict={result.verdict} />
          </motion.div>

          {/* ── Confidence bar ── */}
          <motion.div variants={itemVariants}>
            <ConfidenceBar
              confidence={result.confidence}
              verdict={result.verdict}
            />
          </motion.div>

          {/* ── Evidence text ── */}
          <motion.p
            variants={itemVariants}
            className="text-xs text-slate-400 leading-relaxed border-t border-slate-800/60 pt-3"
          >
            {result.evidenceText}
          </motion.p>

          {/* ── Latency badge ── */}
          <motion.div variants={itemVariants}>
            <LatencyBadge latencyMs={result.latencyMs} />
          </motion.div>
        </motion.div>
      </motion.article>
    </AnimatePresence>
  );
}

// ---------------------------------------------------------------------------
// Demo / preview — renders skeleton, empty, and three sample cards
// ---------------------------------------------------------------------------

/** @type {DetectorResult[]} */
const SAMPLE_RESULTS = [
  {
    verdict: "authentic",
    confidence: 91,
    evidenceText:
      "Frame-level analysis found no temporal inconsistencies. Facial landmark coherence across all 240 sampled frames within expected biological variance. No compression artifact anomalies detected.",
    latencyMs: 342,
    detectorName: "VideoDetector v1",
    // Fixed ISO strings keep SSR and client in sync (no hydration mismatch)
    timestamp: "2026-09-15T16:45:00.000Z",
  },
  {
    verdict: "manipulated",
    confidence: 87,
    evidenceText:
      "High-frequency spectral blending artifacts detected in phoneme transitions at 0:04–0:07. Lip-sync divergence score 0.74 (threshold: 0.55). Audio waveform shows GAN-typical smoothing near silence boundaries.",
    latencyMs: 518,
    detectorName: "AASIST v2 · SyncNet",
    timestamp: "2026-09-15T16:46:30.000Z",
  },
  {
    verdict: "inconclusive",
    confidence: 54,
    evidenceText:
      "rPPG pulse signal partially recoverable — heavy motion blur in 38% of frames limits physiological signal extraction. Confidence below decision threshold; manual review recommended.",
    latencyMs: 1204,
    detectorName: "rPPG Analyzer v1",
    timestamp: "2026-09-15T16:48:00.000Z",
  },
];

/**
 * DetectorResultCardDemo
 *
 * Drop this on any page/route to visually verify the component standalone.
 * Shows: skeleton, empty, authentic, manipulated, and inconclusive states.
 */
export function DetectorResultCardDemo() {
  return (
    <>
      <section className="min-h-screen bg-[#0b0f17] text-slate-100 py-16 px-4 sm:px-8 space-y-12">
        {/* Background radial gradient — matches UploadPage */}
        <div className="fixed inset-0 bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(120,119,198,0.15),rgba(255,255,255,0))] pointer-events-none" />

        <div className="relative max-w-5xl mx-auto space-y-12">
          {/* Page header */}
          <div className="text-center space-y-3">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider bg-cyan-950/60 border border-cyan-800/40 text-cyan-400">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
              Component Preview
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight text-white">
              DetectorResultCard
            </h1>
            <p className="text-slate-400 text-sm max-w-md mx-auto">
              Standalone preview — all states rendered simultaneously for visual
              verification before wiring to the results page.
            </p>
          </div>

          {/* ── Section: Loading & Empty ── */}
          <div className="space-y-4">
            <h2 className="text-xs font-mono uppercase tracking-widest text-slate-500 border-b border-slate-800 pb-2">
              Skeleton &amp; Empty States
            </h2>
            <div className="flex flex-wrap gap-6">
              <DetectorResultCard result={null} isLoading={true} />
              <DetectorResultCard result={null} isLoading={false} />
            </div>
          </div>

          {/* ── Section: Populated cards ── */}
          <div className="space-y-4">
            <h2 className="text-xs font-mono uppercase tracking-widest text-slate-500 border-b border-slate-800 pb-2">
              Populated States — Authentic · Manipulated · Inconclusive
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
              {SAMPLE_RESULTS.map((r) => (
                <DetectorResultCard
                  key={r.detectorName}
                  result={r}
                  isLoading={false}
                />
              ))}
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
