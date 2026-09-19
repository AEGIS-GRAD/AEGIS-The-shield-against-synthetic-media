"use client";

import React from "react";
import { Shield, RefreshCw } from "lucide-react";

export default function WorkstationHeader({ onReset, isRunning = false, activeMode = "simulation" }) {
  return (
    <header className="w-full border-b border-slate-800/80 bg-slate-950/70 backdrop-blur-xl sticky top-0 z-50 transition-all">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
        {/* Logo & Title */}
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500/20 via-sky-500/10 to-indigo-500/20 border border-cyan-500/30 shadow-lg shadow-cyan-500/10">
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
                Milestone 1 Demo
              </span>
            </div>
            <p className="text-xs text-slate-400 hidden sm:block">
              Agentic, Edge-Optimized Synthetic Media Verification
            </p>
          </div>
        </div>

        {/* Runtime Status & Actions */}
        <div className="flex items-center gap-3">
          {/* Active Mode Pill */}
          <div className="hidden md:flex items-center gap-2 px-3 py-1 rounded-lg bg-slate-900/90 border border-slate-800 text-xs font-mono">
            <span className={`w-2 h-2 rounded-full ${activeMode === "live" ? "bg-emerald-400 animate-pulse" : "bg-cyan-400"}`} />
            <span className="text-slate-400">Runtime:</span>
            <span className="text-slate-200 font-semibold">
              {activeMode === "live" ? "API Gateway (Live: 8081)" : "Simulated Microservices"}
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
              <span className="hidden sm:inline">New Analysis</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
