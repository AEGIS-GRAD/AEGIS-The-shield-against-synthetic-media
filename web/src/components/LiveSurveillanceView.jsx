"use client";
// impeccable-disable gray-on-color

import React, { useState, useEffect, useRef } from "react";
import TelemetryView from "./TelemetryView";
import {
  Radio,
  ShieldAlert,
  Video,
  Activity,
  CheckCircle2,
  AlertTriangle,
  Server,
  Clock,
  Lock,
  RefreshCw,
  Play,
  Pause,
  Sliders,
  Cpu,
  Maximize2,
  FileCode2,
  ExternalLink,
  ShieldCheck,
  Layers,
  Volume2,
  VolumeX,
  Eye,
  Camera,
  Flame,
  Zap,
} from "lucide-react";

const CAMERA_FEEDS = [
  {
    id: "cam-01",
    name: "Camera 01 — Perimeter Gate (RTSP)",
    location: "North Entrance Gate #4",
    resolution: "1080p @ 30fps",
    protocol: "mTLS Encrypted RTSP",
    simulatedType: "clean",
    hashChainStatus: "VALID",
    hashChainId: "0x9F4A...B82D",
    edgeNode: "Edge Node Alpha (Jetson Orin)",
  },
  {
    id: "cam-02",
    name: "Camera 02 — Main Lobby (WebRTC)",
    location: "Executive Lobby Concourse",
    resolution: "1080p @ 60fps",
    protocol: "WebRTC Security Stream",
    simulatedType: "deepfake",
    hashChainStatus: "VALID",
    hashChainId: "0x3C1E...7A41",
    edgeNode: "Edge Node Beta (NPU Gateway)",
  },
  {
    id: "cam-03",
    name: "Camera 03 — Press Briefing Feed",
    location: "Auditorium Pod 2",
    resolution: "4K @ 30fps",
    protocol: "TLS 1.3 Direct Feed",
    simulatedType: "manipulated",
    hashChainStatus: "WARNING",
    hashChainId: "0x7E90...4D12",
    edgeNode: "Edge Node Gamma (RPi NPU)",
  },
];

export default function LiveSurveillanceView() {
  const [selectedCam, setSelectedCam] = useState(CAMERA_FEEDS[0]);
  const [isPlaying, setIsPlaying] = useState(true);
  const [windowSize, setWindowSize] = useState(16); // 16-frame sliding window
  const [emaAlpha, setEmaAlpha] = useState(0.25);
  const [confidenceHistory, setConfidenceHistory] = useState([
    0.12, 0.15, 0.11, 0.14, 0.18, 0.16, 0.22, 0.19, 0.25, 0.21, 0.18, 0.24, 0.20, 0.26, 0.22, 0.19
  ]);
  const [eventLogs, setEventLogs] = useState([]);
  const [tick, setTick] = useState(0);
  const [currentScore, setCurrentScore] = useState(0.18);
  const [emaScore, setEmaScore] = useState(0.18);
  const [processedFrames, setProcessedFrames] = useState(14820);
  const [fps, setFps] = useState(29.8);

  // Live sliding-window loop simulation
  useEffect(() => {
    if (!isPlaying) return;

    const interval = setInterval(() => {
      setTick((t) => t + 1);
      setProcessedFrames((count) => count + 1);

      // Simulate streaming scores based on feed type
      let baseNoise = (Math.random() - 0.48) * 0.08;
      let newScore = currentScore;

      if (selectedCam.simulatedType === "clean") {
        newScore = Math.max(0.04, Math.min(0.32, 0.15 + baseNoise));
      } else if (selectedCam.simulatedType === "deepfake") {
        // High synthetic anomaly
        newScore = Math.max(0.68, Math.min(0.98, 0.85 + baseNoise));
      } else {
        // Fluctuate / manipulated
        newScore = Math.max(0.35, Math.min(0.82, 0.58 + (Math.sin(tick * 0.5) * 0.25)));
      }

      newScore = Number(newScore.toFixed(3));
      setCurrentScore(newScore);

      // Compute Exponential Moving Average (EMA)
      const nextEma = Number((emaAlpha * newScore + (1 - emaAlpha) * emaScore).toFixed(3));
      setEmaScore(nextEma);

      // Push to sliding-window history buffer
      setConfidenceHistory((prev) => {
        const updated = [...prev.slice(1), nextEma];
        return updated;
      });

      // Generate periodic SOC alerts if score crosses synthetic threshold (0.65)
      if (nextEma > 0.65 && (tick % 8 === 0 || eventLogs.length === 0)) {
        const timestamp = new Date().toLocaleTimeString();
        const newLog = {
          id: `${Date.now()}-${Math.random()}`,
          timestamp,
          level: "CRITICAL",
          cam: selectedCam.id,
          message: `Sliding-window threshold alert: EMA score ${nextEma} > 0.65 (SYNTHETIC FLAGGED)`,
          hash: selectedCam.hashChainId,
        };
        setEventLogs((logs) => [newLog, ...logs.slice(0, 19)]);
      } else if (tick % 15 === 0) {
        const timestamp = new Date().toLocaleTimeString();
        const newLog = {
          id: `${Date.now()}-${Math.random()}`,
          timestamp,
          level: "INFO",
          cam: selectedCam.id,
          message: `Frame cluster verified. Hash chain integrity: VALID. FPS: ${(29.5 + Math.random() * 0.8).toFixed(1)}`,
          hash: selectedCam.hashChainId,
        };
        setEventLogs((logs) => [newLog, ...logs.slice(0, 19)]);
      }

      setFps((29.4 + Math.random() * 0.9).toFixed(1));
    }, 600);

    return () => clearInterval(interval);
  }, [isPlaying, selectedCam, currentScore, emaScore, emaAlpha, tick, eventLogs]);

  // SVG Chart Dimensions & Paths
  const chartHeight = 110;
  const chartWidth = 500;
  const points = confidenceHistory.map((val, idx) => {
    const x = (idx / (confidenceHistory.length - 1)) * chartWidth;
    const y = chartHeight - val * chartHeight;
    return `${x},${y}`;
  }).join(" ");

  const areaPath = `M 0,${chartHeight} L ${points} L ${chartWidth},${chartHeight} Z`;

  const isSynthetic = emaScore >= 0.65;
  const isAuthentic = emaScore <= 0.35;

  // Mock status data for integrated TelemetryView component
  const mockTelemetryStatus = {
    overall_status: isPlaying ? "processing" : "complete",
    detectors: {
      video_classifier: {
        status: "complete",
        latency_ms: Math.round(18 + Math.random() * 8),
        ram_usage_mb: 210.4,
      },
      aasist: {
        status: selectedCam.id === "cam-02" ? "complete" : "skipped",
        latency_ms: selectedCam.id === "cam-02" ? Math.round(24 + Math.random() * 6) : 0,
        ram_usage_mb: 145.2,
      },
      rppg: {
        status: "complete",
        latency_ms: Math.round(38 + Math.random() * 12),
        ram_usage_mb: 180.8,
      },
      syncnet: {
        status: selectedCam.id === "cam-02" ? "complete" : "skipped",
        latency_ms: selectedCam.id === "cam-02" ? Math.round(45 + Math.random() * 15) : 0,
        ram_usage_mb: 260.1,
      },
    },
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300 w-full">
      {/* Informational Mode Banner */}
      <div className="p-4 rounded-2xl bg-gradient-to-r from-emerald-950/60 via-slate-900/90 to-amber-950/50 border border-emerald-500/30 backdrop-blur-xl shadow-xl flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-start gap-3.5">
          <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 shrink-0 mt-0.5 md:mt-0">
            <Radio className="w-5 h-5 animate-pulse text-emerald-400" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-base font-bold text-white tracking-tight">
                Live Surveillance Monitoring Mode
              </h2>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 uppercase tracking-wider flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                Sliding-Window Continuous Verification
              </span>
            </div>
            <p className="text-xs text-slate-300 mt-1 max-w-3xl leading-relaxed">
              Unlike static single-pass file uploads, live surveillance evaluates incoming camera streams using a <strong>rolling sliding window</strong>. Confidence scores update continuously via Exponential Moving Average (EMA) with real-time frame hash-chain validation.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0 self-end md:self-center">
          <div className="text-right hidden sm:block">
            <div className="text-[10px] font-mono text-slate-400 uppercase">Ingestion Protocol</div>
            <div className="text-xs font-mono font-semibold text-emerald-400">{selectedCam.protocol}</div>
          </div>
          <button
            onClick={() => setIsPlaying(!isPlaying)}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-xl font-mono text-xs font-bold transition-all cursor-pointer shadow-lg ${
              isPlaying
                ? "bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40"
                : "bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40"
            }`}
          >
            {isPlaying ? (
              <>
                <Pause className="w-3.5 h-3.5 fill-amber-300" />
                <span>Pause Stream</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-emerald-300" />
                <span>Resume Stream</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Main Grid Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        
        {/* Left Column: Live Video Canvas & Feed Selector (7 Cols) */}
        <div className="lg:col-span-7 space-y-5">
          
          {/* Stream Feed Selector Tabs */}
          <div className="p-2 rounded-xl bg-slate-900/90 border border-slate-800 flex flex-col sm:flex-row gap-2">
            {CAMERA_FEEDS.map((cam) => {
              const isSelected = selectedCam.id === cam.id;
              return (
                <button
                  key={cam.id}
                  onClick={() => {
                    setSelectedCam(cam);
                    setConfidenceHistory([0.15, 0.14, 0.16, 0.15, 0.18, 0.17, 0.15, 0.16, 0.15, 0.17, 0.16, 0.15, 0.18, 0.16, 0.15, 0.17]);
                  }}
                  className={`flex-1 p-2.5 rounded-lg text-left transition-all cursor-pointer border ${
                    isSelected
                      ? "bg-slate-800/90 text-white border-emerald-500/50 shadow-md"
                      : "bg-slate-950/40 text-slate-400 hover:text-slate-200 border-transparent hover:border-slate-800"
                  }`}
                >
                  <div className="flex items-center justify-between text-xs font-bold truncate">
                    <span className="truncate">{cam.name.split("—")[0]}</span>
                    <span className={`w-2 h-2 rounded-full ${isSelected ? "bg-emerald-400 animate-pulse" : "bg-slate-600"}`} />
                  </div>
                  <div className="text-[10px] font-mono text-slate-400 mt-0.5 truncate">
                    {cam.location}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Live Stream Simulation Canvas */}
          <div className="relative rounded-2xl bg-slate-950 border border-slate-800 overflow-hidden shadow-2xl group">
            
            {/* Simulated Surveillance Camera Video Container */}
            <div className="relative aspect-video w-full bg-slate-950 flex flex-col items-center justify-center overflow-hidden">
              
              {/* Dynamic Visual Feed Canvas Simulation */}
              <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_60%_at_50%_50%,rgba(16,185,129,0.08),rgba(0,0,0,0.95))] pointer-events-none" />
              
              {/* Simulated Camera Video Grid / Crosshair Overlay */}
              <div className="absolute inset-0 opacity-25 bg-[linear-gradient(to_right,#1e293b_1px,transparent_1px),linear-gradient(to_bottom,#1e293b_1px,transparent_1px)] bg-[size:32px_32px]" />
              
              {/* Animated Face Bounding Box Scanner */}
              <div className="relative z-10 w-48 h-48 sm:w-56 sm:h-56 rounded-2xl border-2 border-emerald-400/70 bg-emerald-500/5 flex flex-col items-center justify-between p-3 shadow-2xl transition-all duration-300">
                <div className="w-full flex justify-between text-[10px] font-mono text-emerald-400">
                  <span>FACIAL BBOX #01</span>
                  <span>CONF: 99.4%</span>
                </div>

                {/* Center Target Pointer */}
                <div className="flex flex-col items-center justify-center space-y-1 my-auto text-center">
                  <Camera className="w-8 h-8 text-emerald-400 animate-pulse" />
                  <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-emerald-300">
                    {selectedCam.simulatedType === "deepfake" ? (
                      <span className="text-rose-400 bg-rose-950/80 px-2 py-0.5 rounded border border-rose-800">
                        SYNTHETIC BOUNDARY DETECTED
                      </span>
                    ) : selectedCam.simulatedType === "manipulated" ? (
                      <span className="text-amber-300 bg-amber-950/80 px-2 py-0.5 rounded border border-amber-800">
                        TEMPORAL FLICKER DETECTED
                      </span>
                    ) : (
                      <span className="text-emerald-400 bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-800">
                        AUTHENTIC BIOMETRIC PULSE
                      </span>
                    )}
                  </span>
                </div>

                {/* Bottom BBox Info */}
                <div className="w-full flex justify-between text-[10px] font-mono text-emerald-400/90 border-t border-emerald-500/30 pt-1">
                  <span>rPPG Pulse: 72 BPM</span>
                  <span>SyncNet: OK</span>
                </div>

                {/* BBox Corner Markers */}
                <span className="absolute -top-1 -left-1 w-3 h-3 border-t-2 border-l-2 border-emerald-400" />
                <span className="absolute -top-1 -right-1 w-3 h-3 border-t-2 border-r-2 border-emerald-400" />
                <span className="absolute -bottom-1 -left-1 w-3 h-3 border-b-2 border-l-2 border-emerald-400" />
                <span className="absolute -bottom-1 -right-1 w-3 h-3 border-b-2 border-r-2 border-emerald-400" />
              </div>

              {/* Stream OSD Overlay (Top) */}
              <div className="absolute top-3 left-3 right-3 flex items-center justify-between text-xs font-mono bg-slate-950/80 backdrop-blur-md px-3 py-1.5 rounded-xl border border-slate-800 z-20">
                <div className="flex items-center gap-2">
                  <span className={`w-2.5 h-2.5 rounded-full ${isPlaying ? "bg-rose-500 animate-ping" : "bg-amber-500"}`} />
                  <span className="font-bold text-white uppercase">{selectedCam.name}</span>
                </div>
                <div className="flex items-center gap-3 text-slate-300 text-[11px]">
                  <span>{selectedCam.resolution}</span>
                  <span className="text-emerald-400 font-bold">{fps} FPS</span>
                </div>
              </div>

              {/* Stream OSD Overlay (Bottom) */}
              <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between text-[11px] font-mono bg-slate-950/80 backdrop-blur-md px-3 py-1.5 rounded-xl border border-slate-800 z-20">
                <div className="flex items-center gap-2 text-slate-300">
                  <ShieldCheck className="w-4 h-4 text-cyan-400" />
                  <span>Hash Chain: <code className="text-cyan-300">{selectedCam.hashChainId}</code></span>
                </div>
                <span className="text-slate-400">
                  Total Frames: <strong className="text-slate-200">{processedFrames.toLocaleString()}</strong>
                </span>
              </div>
            </div>
          </div>

          {/* Camera Details Card */}
          <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs font-mono">
            <div>
              <span className="text-slate-400 block text-[10px] uppercase">Node Host</span>
              <span className="text-slate-200 font-semibold">{selectedCam.edgeNode}</span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px] uppercase">Location</span>
              <span className="text-slate-200 font-semibold">{selectedCam.location}</span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px] uppercase">Verification Method</span>
              <span className="text-emerald-400 font-semibold">Sliding-Window EMA</span>
            </div>
          </div>
        </div>

        {/* Right Column: Sliding-Window Trajectory & Real-Time SOC Alerts (5 Cols) */}
        <div className="lg:col-span-5 space-y-5">
          
          {/* Sliding-Window Risk Trajectory Card */}
          <div className="p-5 rounded-2xl bg-slate-900/90 border border-slate-800 backdrop-blur-xl shadow-2xl space-y-4">
            
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <Activity className="w-4 h-4 text-emerald-400" />
                  Rolling Synthetic Risk Trajectory
                </h3>
                <p className="text-[11px] text-slate-400 font-mono mt-0.5">
                  16-Frame Sliding Window • EMA ($\alpha = 0.25$)
                </p>
              </div>

              <div className="text-right">
                <span className={`text-xl font-extrabold font-mono ${isSynthetic ? "text-rose-400" : isAuthentic ? "text-emerald-400" : "text-amber-400"}`}>
                  {(emaScore * 100).toFixed(1)}%
                </span>
                <span className="text-[10px] text-slate-400 block font-mono">EMA Confidence</span>
              </div>
            </div>

            {/* Verdict Status Box */}
            <div className={`p-3 rounded-xl border font-mono text-xs flex items-center justify-between ${
              isSynthetic
                ? "bg-rose-950/60 border-rose-800/80 text-rose-300"
                : isAuthentic
                ? "bg-emerald-950/60 border-emerald-800/80 text-emerald-300"
                : "bg-amber-950/60 border-amber-800/80 text-amber-300"
            }`}>
              <div className="flex items-center gap-2">
                {isSynthetic ? (
                  <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                ) : (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                )}
                <div>
                  <div className="font-bold uppercase tracking-wider">
                    {isSynthetic ? "HIGH SYNTHETIC RISK (FLAGGED)" : isAuthentic ? "STREAM VERIFIED AUTHENTIC" : "BORDERLINE / UNCERTAIN FLICKER"}
                  </div>
                  <div className="text-[10px] opacity-80 font-sans">
                    {isSynthetic
                      ? "Sliding-window EMA exceeded 0.65 threshold across consecutive frames."
                      : "Temporal pulse and facial boundaries fall within authentic physiological parameters."}
                  </div>
                </div>
              </div>
            </div>

            {/* SVG Line Graph for Sliding Window */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-[10px] font-mono text-slate-400 px-1">
                <span>Synthetic Threshold (0.65)</span>
                <span>Buffer Size: 16 Frames</span>
              </div>

              <div className="relative w-full h-28 bg-slate-950 rounded-xl border border-slate-800/80 p-2 overflow-hidden">
                {/* 0.65 Threshold Reference Line */}
                <div
                  className="absolute left-0 right-0 border-b border-dashed border-rose-500/60 z-10"
                  style={{ top: `${(1 - 0.65) * 100}%` }}
                >
                  <span className="absolute right-2 -top-4 text-[9px] font-mono text-rose-400 bg-slate-950 px-1 rounded">
                    0.65 THRESHOLD
                  </span>
                </div>

                <svg className="w-full h-full overflow-visible" viewBox={`0 0 ${chartWidth} ${chartHeight}`} preserveAspectRatio="none">
                  <defs>
                    <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={isSynthetic ? "#f43f5e" : "#10b981"} stopOpacity="0.4" />
                      <stop offset="100%" stopColor={isSynthetic ? "#f43f5e" : "#10b981"} stopOpacity="0.0" />
                    </linearGradient>
                  </defs>
                  
                  {/* Area fill */}
                  <path d={areaPath} fill="url(#chartGradient)" />
                  
                  {/* Line path */}
                  <polyline
                    fill="none"
                    stroke={isSynthetic ? "#f43f5e" : "#10b981"}
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    points={points}
                  />

                  {/* Current Active Dot */}
                  <circle
                    cx={chartWidth}
                    cy={chartHeight - emaScore * chartHeight}
                    r="5"
                    fill={isSynthetic ? "#f43f5e" : "#10b981"}
                    className="animate-ping"
                  />
                  <circle
                    cx={chartWidth}
                    cy={chartHeight - emaScore * chartHeight}
                    r="4"
                    fill="#ffffff"
                  />
                </svg>
              </div>
            </div>

            {/* Sliding-Window Controls */}
            <div className="pt-2 border-t border-slate-800/80 grid grid-cols-2 gap-3 text-xs font-mono">
              <div>
                <label className="text-[10px] text-slate-400 block uppercase mb-1">Window Size (Frames)</label>
                <select
                  value={windowSize}
                  onChange={(e) => setWindowSize(Number(e.target.value))}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1 text-slate-200 focus:outline-none focus:border-emerald-500"
                >
                  <option value={8}>8 Frames (Fast Alert)</option>
                  <option value={16}>16 Frames (Standard)</option>
                  <option value={32}>32 Frames (High Stability)</option>
                </select>
              </div>

              <div>
                <label className="text-[10px] text-slate-400 block uppercase mb-1">EMA Weight ($\alpha$)</label>
                <select
                  value={emaAlpha}
                  onChange={(e) => setEmaAlpha(Number(e.target.value))}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1 text-slate-200 focus:outline-none focus:border-emerald-500"
                >
                  <option value={0.15}>0.15 (Heavy Smoothing)</option>
                  <option value={0.25}>0.25 (Balanced)</option>
                  <option value={0.4}>0.40 (Fast Response)</option>
                </select>
              </div>
            </div>
          </div>

          {/* Real-Time Security Operations Center (SOC) Alert Log */}
          <div className="p-4 rounded-2xl bg-slate-900/90 border border-slate-800 space-y-3">
            <div className="flex items-center justify-between border-b border-slate-800/80 pb-2.5">
              <div className="flex items-center gap-2 text-xs font-bold text-slate-200 uppercase font-mono">
                <ShieldAlert className="w-4 h-4 text-rose-400" />
                <span>Live SOC Alert Stream</span>
              </div>
              <span className="text-[10px] font-mono text-slate-400">
                Auto-Updating Log ({eventLogs.length})
              </span>
            </div>

            <div className="space-y-2 max-h-48 overflow-y-auto pr-1 text-[11px] font-mono">
              {eventLogs.length === 0 ? (
                <div className="py-6 text-center text-slate-500 text-xs">
                  Monitoring feed... Waiting for alert triggers.
                </div>
              ) : (
                eventLogs.map((log) => (
                  <div
                    key={log.id}
                    className={`p-2.5 rounded-lg border flex items-start justify-between gap-2 transition-all ${
                      log.level === "CRITICAL"
                        ? "bg-rose-950/40 border-rose-800/50 text-rose-200"
                        : "bg-slate-950/60 border-slate-800 text-slate-300"
                    }`}
                  >
                    <div className="space-y-0.5">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-slate-400">{log.timestamp}</span>
                        <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold ${
                          log.level === "CRITICAL" ? "bg-rose-500/20 text-rose-300 border border-rose-500/30" : "bg-emerald-500/20 text-emerald-300"
                        }`}>
                          {log.level}
                        </span>
                        <span className="text-[10px] text-slate-400 uppercase">{log.cam}</span>
                      </div>
                      <p className="text-xs">{log.message}</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

        </div>
      </div>

      {/* Integrated Live Telemetry Dashboard */}
      <div className="pt-4 border-t border-slate-800/80">
        <TelemetryView statusData={mockTelemetryStatus} />
      </div>
    </div>
  );
}
