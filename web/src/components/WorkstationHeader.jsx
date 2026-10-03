"use client";

import React from "react";
import { Shield, RefreshCw, FileText, Radio } from "lucide-react";

export default function WorkstationHeader({
  onReset,
  isRunning = false,
  activeMode = "simulation",
  verificationMode = "offline",
  onModeChange,
}) {
  return (
    <header className="w-full border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-xl sticky top-0 z-50 transition-all shadow-xl">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
        {/* Logo & Title */}
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 via-sky-500/10 to-indigo-500/20 border border-cyan-500/30 shadow-lg shadow-cyan-500/10 shrink-0">
            <Shield className="w-5 h-5 text-cyan-400" />
            <span className="absolute -bottom-0.5 -right-0.5 flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-cyan-500" />
            </span>
          </div>

          <div>
            <div className="flex items-center gap-2">
              <span className="font-extrabold tracking-tight text-white text-base">AEGIS</span>
              <span className="text-[10px] font-mono font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-cyan-950/70 text-cyan-400 border border-cyan-800/50">
                Ver. 2.0 Workstation
              </span>
            </div>
            <p className="text-xs text-slate-400 hidden lg:block">
              Agentic, Edge-Optimized Synthetic Media Verification
            </p>
          </div>
        </div>

        {/* Center: Mode Switcher Segmented Control */}
        <div className="flex bg-slate-900/90 border border-slate-800 rounded-xl p-1 shadow-inner">
          <button
            onClick={() => onModeChange && onModeChange("offline")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all cursor-pointer ${
              verificationMode === "offline"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
            title="Switch to Offline File Verification Mode (Single-pass static media analysis)"
          >
            <FileText className="w-3.5 h-3.5 text-cyan-400" />
            <span>Offline File</span>
            <span className="hidden sm:inline-block text-[9px] px-1 py-0.2 rounded bg-cyan-950 text-cyan-400 border border-cyan-800/60 font-sans">
              Month 1
            </span>
          </button>

          <button
            onClick={() => onModeChange && onModeChange("live")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all cursor-pointer ${
              verificationMode === "live"
                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
            title="Switch to Live Surveillance Monitoring Mode (Continuous sliding-window check)"
          >
            <Radio className={`w-3.5 h-3.5 ${verificationMode === "live" ? "text-emerald-400 animate-pulse" : "text-slate-400"}`} />
            <span>Live Stream</span>
            <span className="hidden sm:inline-block text-[9px] px-1 py-0.2 rounded bg-emerald-950 text-emerald-400 border border-emerald-800/60 font-sans">
              Month 2
            </span>
          </button>
        </div>

        {/* Right Actions */}
        <div className="flex items-center gap-3">
          {/* Active Runtime Indicator */}
          <div className="hidden xl:flex items-center gap-2 px-3 py-1 rounded-lg bg-slate-900/90 border border-slate-800 text-xs font-mono">
            <span className={`w-2 h-2 rounded-full ${verificationMode === "live" ? "bg-emerald-400 animate-pulse" : "bg-cyan-400"}`} />
            <span className="text-slate-400">Mode:</span>
            <span className="text-slate-200 font-semibold">
              {verificationMode === "live" ? "Sliding-Window Stream" : "Single-Pass Verdict"}
            </span>
          </div>

          {/* Quick Reset */}
          {onReset && (
            <button
              onClick={onReset}
              disabled={isRunning}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-800 hover:border-slate-700 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              title="Reset current session and load new media"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Reset</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

