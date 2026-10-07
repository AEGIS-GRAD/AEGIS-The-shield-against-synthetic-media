"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { Shield, RefreshCw, FileText, Radio, Camera, Terminal, AlertCircle } from "lucide-react";
import { logger } from "../api/systemLogger";

export default function WorkstationHeader({
  onReset,
  isRunning = false,
  activeMode = "simulation",
  verificationMode = "offline",
  onModeChange,
  onOpenLogs,
}) {
  const [errorCount, setErrorCount] = useState(0);

  useEffect(() => {
    setErrorCount(logger.getErrorCount());
    const unsub = logger.subscribe(() => {
      setErrorCount(logger.getErrorCount());
    });
    return () => unsub();
  }, []);

  return (
    <header className="w-full border-b border-slate-200 bg-white/90 backdrop-blur-xl sticky top-0 z-50 transition-all shadow-sm">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
        {/* Logo & Title */}
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center w-10 h-10 rounded-xl bg-cyan-50 border border-cyan-200 shadow-sm shrink-0">
            <Shield className="w-5 h-5 text-cyan-600" />
            <span className="absolute -bottom-0.5 -right-0.5 flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-cyan-500" />
            </span>
          </div>

          <div>
            <div className="flex items-center gap-2">
              <span className="font-extrabold tracking-tight text-slate-900 text-base">AEGIS</span>
              <span className="text-[10px] font-mono font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-cyan-100 text-cyan-800 border border-cyan-300">
                Ver. 2.0 Workstation
              </span>
            </div>
            <p className="text-xs text-slate-500 hidden lg:block">
              Agentic, Edge-Optimized Synthetic Media Verification
            </p>
          </div>
        </div>

        {/* Center: Mode Switcher Segmented Control */}
        <div className="flex bg-slate-100 border border-slate-200 rounded-xl p-1 shadow-inner">
          <button
            onClick={() => onModeChange && onModeChange("offline")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all cursor-pointer ${
              verificationMode === "offline"
                ? "bg-cyan-600 text-white shadow-sm border border-cyan-600"
                : "text-slate-600 hover:text-slate-900"
            }`}
            title="Switch to Offline File Verification Mode (Single-pass static media analysis)"
          >
            <FileText className={`w-3.5 h-3.5 ${verificationMode === "offline" ? "text-white" : "text-cyan-600"}`} />
            <span>Offline File</span>
            <span className={`hidden sm:inline-block text-[9px] px-1 py-0.2 rounded font-sans ${verificationMode === "offline" ? "bg-cyan-700 text-cyan-100" : "bg-slate-200 text-slate-700"}`}>
              Month 1
            </span>
          </button>

          <button
            onClick={() => onModeChange && onModeChange("live")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all cursor-pointer ${
              verificationMode === "live"
                ? "bg-emerald-600 text-white shadow-sm border border-emerald-600"
                : "text-slate-600 hover:text-slate-900"
            }`}
            title="Switch to Live Surveillance Monitoring Mode (Continuous sliding-window check)"
          >
            <Radio className={`w-3.5 h-3.5 ${verificationMode === "live" ? "text-white animate-pulse" : "text-emerald-600"}`} />
            <span>Live Stream</span>
            <span className={`hidden sm:inline-block text-[9px] px-1 py-0.2 rounded font-sans ${verificationMode === "live" ? "bg-emerald-700 text-emerald-100" : "bg-slate-200 text-slate-700"}`}>
              Month 2
            </span>
          </button>
        </div>

        {/* Right Actions */}
        <div className="flex items-center gap-2 sm:gap-3">
          {/* Active Runtime Indicator */}
          <div className="hidden xl:flex items-center gap-2 px-3 py-1 rounded-lg bg-slate-100 border border-slate-200 text-xs font-mono">
            <span className={`w-2 h-2 rounded-full ${verificationMode === "live" ? "bg-emerald-500 animate-pulse" : "bg-cyan-500"}`} />
            <span className="text-slate-500">Mode:</span>
            <span className="text-slate-800 font-bold">
              {verificationMode === "live" ? "Sliding-Window Stream" : "Single-Pass Verdict"}
            </span>
          </div>

          {/* System Logs & Diagnostics Tab Button */}
          {onOpenLogs && (
            <button
              onClick={onOpenLogs}
              className={`relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all cursor-pointer border ${
                errorCount > 0
                  ? "bg-rose-50 hover:bg-rose-100 text-rose-700 border-rose-300 animate-pulse"
                  : "bg-white hover:bg-slate-100 text-slate-700 border-slate-200 hover:border-cyan-500 shadow-xs"
              }`}
              title="Open System Diagnostic Logs & Error History"
            >
              <Terminal className="w-3.5 h-3.5 text-cyan-600" />
              <span className="hidden sm:inline">System Logs</span>
              {errorCount > 0 && (
                <span className="flex items-center justify-center w-4 h-4 rounded-full bg-rose-600 text-white text-[9px] font-bold">
                  {errorCount}
                </span>
              )}
            </button>
          )}

          {/* Live Surveillance nav link */}
          <Link
            href="/surveillance"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-cyan-50 hover:bg-cyan-100 text-cyan-800 border border-cyan-200 transition-all"
            title="Open Live Surveillance Monitor"
          >
            <Camera className="w-3.5 h-3.5 text-cyan-600" />
            <span className="hidden sm:inline">Live Surveillance</span>
          </Link>

          {/* Quick Reset */}
          {onReset && (
            <button
              onClick={onReset}
              disabled={isRunning}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-white hover:bg-slate-100 text-slate-700 border border-slate-200 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shadow-xs"
              title="Reset current session and load new media"
            >
              <RefreshCw className="w-3.5 h-3.5 text-slate-500" />
              <span className="hidden sm:inline">Reset</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

