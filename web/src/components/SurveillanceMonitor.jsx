"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { playAlertChime } from "../utils/audioAlert";
import {
  Shield,
  ShieldAlert,
  ShieldOff,
  Activity,
  Camera,
  Wifi,
  AlertTriangle,
  Bell,
  BellOff,
  Clock,
  Cpu,
  Eye,
  Film,
  Mic,
  Video,
  Radio,
  Lock,
  Zap,
  BarChart2,
  X,
  CheckCircle2,
  ArrowLeft,
  Upload,
} from "lucide-react";

// ─── Constants ────────────────────────────────────────────────────────────────

const ALERT_THRESHOLD = 0.65;
const WARN_THRESHOLD = 0.45;
const HISTORY_WINDOW = 60;

const DETECTOR_CFG = [
  { key: "video", label: "Frame Classifier", model: "MobileNetV3 Edge", color: "#06b6d4", Icon: Film, base: 0.12, variance: 0.18 },
  { key: "rppg", label: "rPPG Pulse", model: "Forehead CHROM", color: "#f43f5e", Icon: Activity, base: 0.10, variance: 0.14 },
  { key: "aasist", label: "AASIST Audio", model: "GraphAttn", color: "#a855f7", Icon: Mic, base: 0.08, variance: 0.12 },
  { key: "syncnet", label: "SyncNet A-V", model: "TwoStream-CNN", color: "#14b8a6", Icon: Video, base: 0.09, variance: 0.16 },
];

const CAMERA_FEEDS = [
  { id: "WEBCAM", location: "Local Live Device (Task 3 rPPG)" },
  { id: "CAM-001", location: "Entrance Hall — Camera A" },
  { id: "CAM-002", location: "Corridor B — Camera 3" },
  { id: "CAM-003", location: "Control Room — Cam 2" },
  { id: "CAM-004", location: "Server Bay — Cam 1" },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function lerp(a, b, t) { return a + (b - a) * t; }

function nextScore(current, base, variance, injecting) {
  const target = injecting
    ? clamp(current + (Math.random() * 0.06 - 0.01), 0, 1)
    : clamp(base + (Math.random() - 0.5) * variance, 0, 1);
  return clamp(lerp(current, target, 0.25), 0, 1);
}

function fmtTime(d) {
  return (d || new Date()).toLocaleTimeString("en-US", { hour12: false });
}

function scoreColor(score) {
  if (score >= ALERT_THRESHOLD) return "#ef4444";
  if (score >= WARN_THRESHOLD) return "#f59e0b";
  return "#10b981";
}

function scoreLabel(score) {
  if (score >= ALERT_THRESHOLD) return "SYNTHETIC";
  if (score >= WARN_THRESHOLD) return "SUSPICIOUS";
  return "AUTHENTIC";
}

// ─── Sparkline ───────────────────────────────────────────────────────────────

function Sparkline({ history, width = 160, height = 36, color = "#06b6d4" }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || history.length < 2) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);
    const pad = 2;
    const w = width - pad * 2;
    const h = height - pad * 2;
    const pts = history.map((v, i) => ({
      x: pad + (i / (history.length - 1)) * w,
      y: pad + (1 - v) * h,
    }));
    const grad = ctx.createLinearGradient(0, 0, 0, height);
    grad.addColorStop(0, color + "55");
    grad.addColorStop(1, color + "00");
    ctx.beginPath();
    ctx.moveTo(pts[0].x, height);
    pts.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.lineTo(pts[pts.length - 1].x, height);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
    ctx.beginPath();
    pts.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.lineJoin = "round";
    ctx.stroke();
    // Alert threshold
    const thY = pad + (1 - ALERT_THRESHOLD) * h;
    ctx.beginPath();
    ctx.moveTo(pad, thY); ctx.lineTo(pad + w, thY);
    ctx.strokeStyle = "#ef444455";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.stroke();
    ctx.setLineDash([]);
  }, [history, width, height, color]);
  return <canvas ref={ref} style={{ width, height }} className="rounded" />;
}

// ─── Rolling Score Chart ──────────────────────────────────────────────────────

function RollingScoreChart({ history, isAlert, isWarning }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || history.length < 2) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 600;
    const h = canvas.clientHeight || 176;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    const padL = 38, padR = 8, padT = 12, padB = 22;
    const cw = w - padL - padR;
    const ch = h - padT - padB;
    // Grid
    ctx.font = "10px monospace";
    ctx.fillStyle = "#475569";
    ctx.textAlign = "right";
    for (let i = 0; i <= 5; i++) {
      const v = i / 5;
      const cy = padT + (1 - v) * ch;
      ctx.beginPath(); ctx.moveTo(padL, cy); ctx.lineTo(padL + cw, cy);
      ctx.strokeStyle = "#1e293b"; ctx.lineWidth = 0.5; ctx.stroke();
      ctx.fillText((v * 100).toFixed(0) + "%", padL - 4, cy + 4);
    }
    // Threshold zones
    const alertY = padT + (1 - ALERT_THRESHOLD) * ch;
    const warnY = padT + (1 - WARN_THRESHOLD) * ch;
    const zA = ctx.createLinearGradient(0, padT, 0, alertY);
    zA.addColorStop(0, "#ef444415"); zA.addColorStop(1, "#ef444408");
    ctx.fillStyle = zA; ctx.fillRect(padL, padT, cw, alertY - padT);
    const zW = ctx.createLinearGradient(0, alertY, 0, warnY);
    zW.addColorStop(0, "#f59e0b10"); zW.addColorStop(1, "#f59e0b05");
    ctx.fillStyle = zW; ctx.fillRect(padL, alertY, cw, warnY - alertY);
    // Threshold labels
    ctx.font = "9px monospace"; ctx.textAlign = "left";
    ctx.fillStyle = "#ef444488"; ctx.fillText("ALERT 65%", padL + 4, alertY - 3);
    ctx.fillStyle = "#f59e0b88"; ctx.fillText("WARN 45%", padL + 4, warnY - 3);
    // Threshold lines
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(padL, alertY); ctx.lineTo(padL + cw, alertY);
    ctx.strokeStyle = "#ef444440"; ctx.lineWidth = 1; ctx.stroke();
    ctx.beginPath(); ctx.moveTo(padL, warnY); ctx.lineTo(padL + cw, warnY);
    ctx.strokeStyle = "#f59e0b40"; ctx.lineWidth = 0.75; ctx.stroke();
    ctx.setLineDash([]);
    // Data
    const pts = history.map((v, i) => ({
      x: padL + (i / (HISTORY_WINDOW - 1)) * cw,
      y: padT + (1 - v) * ch,
      v,
    }));
    const lineColor = isAlert ? "#ef4444" : isWarning ? "#f59e0b" : "#10b981";
    const grad = ctx.createLinearGradient(0, padT, 0, padT + ch);
    grad.addColorStop(0, lineColor + "40");
    grad.addColorStop(0.7, lineColor + "08");
    grad.addColorStop(1, lineColor + "00");
    ctx.beginPath();
    ctx.moveTo(pts[0].x, padT + ch);
    pts.forEach(p => ctx.lineTo(p.x, p.y));
    ctx.lineTo(pts[pts.length - 1].x, padT + ch);
    ctx.closePath(); ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath();
    pts.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
    ctx.strokeStyle = lineColor; ctx.lineWidth = 2;
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    ctx.shadowColor = lineColor; ctx.shadowBlur = isAlert ? 8 : 4;
    ctx.stroke(); ctx.shadowBlur = 0;
    // Alert dots
    pts.forEach(p => {
      if (p.v >= ALERT_THRESHOLD) {
        ctx.beginPath(); ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = "#ef4444"; ctx.shadowColor = "#ef4444"; ctx.shadowBlur = 6;
        ctx.fill(); ctx.shadowBlur = 0;
      }
    });
    // Latest marker
    const last = pts[pts.length - 1];
    ctx.beginPath(); ctx.arc(last.x, last.y, 4, 0, Math.PI * 2);
    ctx.fillStyle = lineColor; ctx.shadowColor = lineColor; ctx.shadowBlur = 10;
    ctx.fill(); ctx.shadowBlur = 0;
    // X-axis
    ctx.font = "9px monospace"; ctx.fillStyle = "#475569"; ctx.textAlign = "center";
    for (let i = 0; i <= 4; i++) {
      const frac = i / 4;
      ctx.fillText(`-${Math.round((1 - frac) * HISTORY_WINDOW)}s`, padL + frac * cw, padT + ch + 14);
    }
  }, [history, isAlert, isWarning]);
  return <canvas ref={ref} className="w-full h-full" />;
}

// ─── Fake Camera Feed ─────────────────────────────────────────────────────────

function FakeCameraFeed({ camId, score, isAlert, isWarning, active = true }) {
  const ref = useRef(null);
  const rafRef = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    if (!active) {
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#050b12";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.font = "12px monospace"; ctx.fillStyle = "#334155"; ctx.textAlign = "center";
      ctx.fillText("PAUSED", canvas.width / 2, canvas.height / 2);
      return;
    }
    const ctx = canvas.getContext("2d");
    let t = 0;
    function draw() {
      const w = canvas.width, h = canvas.height;
      // Noise background
      const imgData = ctx.createImageData(w, h);
      const data = imgData.data;
      for (let i = 0; i < data.length; i += 4) {
        const n = Math.random() * 8;
        data[i] = 10 + n; data[i + 1] = 12 + n; data[i + 2] = 18 + n; data[i + 3] = 255;
      }
      ctx.putImageData(imgData, 0, 0);
      // Face silhouette
      const cx = w * 0.5 + Math.sin(t * 0.02) * 4;
      const cy = h * 0.42;
      ctx.fillStyle = "#0f1a28"; ctx.fillRect(cx - 22, cy + 30, 44, 60);
      ctx.beginPath(); ctx.ellipse(cx, cy, 22, 28, 0, 0, Math.PI * 2);
      ctx.fillStyle = "#1a2a3a"; ctx.fill();
      ctx.fillStyle = "#2a4a6a";
      ctx.beginPath(); ctx.ellipse(cx - 7, cy - 2, 3, 2, 0, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.ellipse(cx + 7, cy - 2, 3, 2, 0, 0, Math.PI * 2); ctx.fill();
      // Scan line
      const scanY = (t * 1.5) % h;
      const sg = ctx.createLinearGradient(0, scanY - 6, 0, scanY + 6);
      sg.addColorStop(0, "rgba(6,182,212,0)"); sg.addColorStop(0.5, "rgba(6,182,212,0.07)"); sg.addColorStop(1, "rgba(6,182,212,0)");
      ctx.fillStyle = sg; ctx.fillRect(0, scanY - 6, w, 12);
      // Alert overlay
      if (isAlert) {
        const pulse = Math.sin(t * 0.15) * 0.5 + 0.5;
        ctx.fillStyle = `rgba(239,68,68,${0.06 + pulse * 0.08})`; ctx.fillRect(0, 0, w, h);
        ctx.strokeStyle = `rgba(239,68,68,${0.4 + pulse * 0.4})`; ctx.lineWidth = 2; ctx.strokeRect(1, 1, w - 2, h - 2);
      } else if (isWarning) {
        const pulse = Math.sin(t * 0.1) * 0.5 + 0.5;
        ctx.fillStyle = `rgba(245,158,11,${0.03 + pulse * 0.05})`; ctx.fillRect(0, 0, w, h);
        ctx.strokeStyle = `rgba(245,158,11,${0.3 + pulse * 0.3})`; ctx.lineWidth = 1.5; ctx.strokeRect(1, 1, w - 2, h - 2);
      }
      // Score text
      ctx.font = "bold 11px monospace"; ctx.fillStyle = scoreColor(score);
      ctx.textAlign = "right"; ctx.fillText(`${(score * 100).toFixed(1)}%`, w - 6, h - 8);
      // Cam ID
      ctx.font = "10px monospace"; ctx.fillStyle = "rgba(100,150,200,0.5)";
      ctx.textAlign = "left"; ctx.fillText(camId, 6, 14);
      // REC dot
      const recOn = Math.floor(t / 30) % 2 === 0;
      ctx.beginPath(); ctx.arc(w - 10, 10, 4, 0, Math.PI * 2);
      ctx.fillStyle = recOn ? "#ef4444" : "#7f1d1d"; ctx.fill();
      t++;
      rafRef.current = requestAnimationFrame(draw);
    }
    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [isAlert, isWarning, score, camId, active]);
  return (
    <canvas ref={ref} width={240} height={160} className="w-full h-full object-cover rounded-lg" />
  );
}

// ─── Alert Toast ──────────────────────────────────────────────────────────────

function AlertToast({ alerts, onDismiss }) {
  if (!alerts.length) return null;
  return (
    <div className="fixed top-16 right-4 z-[100] flex flex-col gap-2 w-96">
      {alerts.slice(-3).map((a) => (
        <div key={a.id} className="flex items-start gap-3 p-3.5 rounded-xl border border-red-500/60 bg-red-950/95 backdrop-blur-xl shadow-2xl shadow-red-900/50 animate-in slide-in-from-right duration-300">
          <ShieldAlert className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5 animate-pulse" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between">
              <p className="text-xs font-black text-red-300 font-mono uppercase tracking-wider">CRITICAL THREAT — {a.camId}</p>
              <span className="text-[10px] text-red-400/80 font-mono">{a.time}</span>
            </div>
            <p className="text-[11px] text-red-200 font-mono mt-1 font-bold">
              Score: {(a.score * 100).toFixed(1)}% (Breached Threshold)
            </p>
            <p className="text-[10px] text-red-300/90 font-mono mt-0.5 bg-red-900/60 p-1.5 rounded border border-red-800/60">
              👉 {a.evidence || `PRNU fingerprint mismatch detected at frame #${a.frameNum || 1402}`}
            </p>
          </div>
          <button onClick={() => onDismiss(a.id)} className="text-red-400/60 hover:text-red-300 transition-colors cursor-pointer p-0.5">
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
    </div>
  );
}

// ─── Main SurveillanceMonitor ─────────────────────────────────────────────────

export default function SurveillanceMonitor() {
  const [scores, setScores] = useState(() => Object.fromEntries(CAMERA_FEEDS.map(c => [c.id, 0.12])));
  const [history, setHistory] = useState(() => Object.fromEntries(CAMERA_FEEDS.map(c => [c.id, Array(HISTORY_WINDOW).fill(0.12)])));
  const [detScores, setDetScores] = useState(() => Object.fromEntries(DETECTOR_CFG.map(d => [d.key, 0.1])));
  const [detHist, setDetHist] = useState(() => Object.fromEntries(DETECTOR_CFG.map(d => [d.key, Array(40).fill(0.1)])));
  const [alerts, setAlerts] = useState([]);
  const [muted, setMuted] = useState(false);
  const [paused, setPaused] = useState(false);
  const [selected, setSelected] = useState("CAM-001");
  const [injecting, setInjecting] = useState(false);
  const [injectCam, setInjectCam] = useState("CAM-001");
  const [alertCount, setAlertCount] = useState(0);
  const [uptime, setUptime] = useState(0);
  const [frameCount, setFrameCount] = useState(0);
  const frameCountRef = useRef(0);
  const [curTime, setCurTime] = useState("--:--:--");
  const [mounted, setMounted] = useState(false);

  // ─── Webcam Mode States ──────────────────────────────────────────────────
  const [webcamActive, setWebcamActive] = useState(false);
  const [webcamConnected, setWebcamConnected] = useState(false);
  const [feedMode, setFeedMode] = useState("backend"); // "backend" (MJPEG) | "browser" (getUserMedia)
  const [webcamData, setWebcamData] = useState({
    ready: false,
    score: null,
    hr_bpm: null,
    snr_db: null,
    window_sec: 0,
    reason: "Idle",
    fps: 0,
    face_detected: false,
  });
  const videoElemRef = useRef(null);
  const streamTrackRef = useRef(null);
  const eventSourceRef = useRef(null);
  const webcamDataRef = useRef(webcamData);
  useEffect(() => { webcamDataRef.current = webcamData; }, [webcamData]);

  // ─── SecDevOps Ingestion Gateway Telemetry State ─────────────────────────
  const [gatewayTelemetry, setGatewayTelemetry] = useState({
    connected: false,
    profile: "PROD",
    lastSeq: null,
    lastHash: "0x9F4A...B82D",
    lastPce: null,
    status: "VALID",
    threatType: null,
    action: null,
  });

  // Connect to SSE stream when webcam is active
  useEffect(() => {
    if (!webcamActive) {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      setWebcamConnected(false);
      if (streamTrackRef.current) {
        streamTrackRef.current.getTracks().forEach(t => t.stop());
        streamTrackRef.current = null;
      }
      return;
    }

    // Direct browser camera fallback if requested
    if (feedMode === "browser") {
      navigator.mediaDevices?.getUserMedia({ video: true })
        .then(stream => {
          streamTrackRef.current = stream;
          if (videoElemRef.current) {
            videoElemRef.current.srcObject = stream;
          }
        })
        .catch(err => {
          console.warn("Direct browser webcam access warning:", err);
        });
    }

    // Connect to Python rPPG service at localhost:8765/stream
    const es = new EventSource("http://localhost:8765/stream");
    eventSourceRef.current = es;

    es.onopen = () => {
      setWebcamConnected(true);
    };

    es.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data);
        setWebcamData(d);
        if (d.score !== null && d.score !== undefined) {
          const s = Number(d.score);
          const rScore = d.rppg_score !== null && d.rppg_score !== undefined ? Number(d.rppg_score) : s;
          const vScore = d.mobilenet_score !== null && d.mobilenet_score !== undefined ? Number(d.mobilenet_score) : 0.08;
          setScores(prev => ({
            ...prev,
            WEBCAM: s,
            ...(selected === "WEBCAM" ? { [selected]: s } : {})
          }));
          if (selected === "WEBCAM") {
            setDetScores(prev => ({
              ...prev,
              rppg: rScore,
              video: vScore,
            }));
          } else {
            setDetScores(prev => ({ ...prev, rppg: rScore }));
          }
        }
      } catch (err) {
        console.error("SSE parse error", err);
      }
    };

    es.onerror = () => {
      setWebcamConnected(false);
    };

    return () => {
      es.close();
      if (streamTrackRef.current) {
        streamTrackRef.current.getTracks().forEach(t => t.stop());
        streamTrackRef.current = null;
      }
    };
  }, [webcamActive, feedMode, selected]);

  // Connect to SecDevOps Gateway Telemetry stream at localhost:8444/telemetry/stream
  useEffect(() => {
    let es = null;
    try {
      es = new EventSource("http://localhost:8444/telemetry/stream");
      es.onopen = () => {
        setGatewayTelemetry(prev => ({ ...prev, connected: true }));
      };
      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.event === "CONNECTED") {
            setGatewayTelemetry(prev => ({
              ...prev,
              connected: true,
              profile: (data.profile || "PROD").toUpperCase(),
            }));
            return;
          }
          if (data.seq !== undefined) {
            setGatewayTelemetry({
              connected: true,
              profile: (data.profile || "PROD").toUpperCase(),
              lastSeq: data.seq,
              lastHash: data.hash || "0x9F4A...B82D",
              lastPce: data.prnu_pce !== undefined ? data.prnu_pce : null,
              status: data.status,
              threatType: data.threat_type || null,
              action: data.action || null,
            });

            if (data.status === "COMPROMISED" || data.status === "AUDIT_WARNING") {
              const id = ++alertIdRef.current;
              playAlertChime(muted);
              setAlerts(a => [...a.slice(-9), {
                id,
                camId: data.camera_id || selected,
                score: data.status === "COMPROMISED" ? 0.96 : 0.72,
                frameNum: data.seq,
                evidence: `${data.threat_type || 'Hardware Anomaly'}: ${data.detail || 'PRNU PCE below threshold'} (${data.action || 'SEVERED'})`,
                time: fmtTime(),
              }]);
              setAlertCount(c => c + 1);
            }
          }
        } catch (err) {
          // ignore keep-alive comments
        }
      };
      es.onerror = () => {
        setGatewayTelemetry(prev => ({ ...prev, connected: false }));
      };
    } catch (err) {
      // offline fallback
    }

    return () => {
      if (es) es.close();
    };
  }, [muted, selected]);

  const alertIdRef = useRef(0);
  const prevScores = useRef({});
  const scoresRef = useRef(scores);
  const detScoresRef = useRef(detScores);

  // Keep refs in sync
  useEffect(() => { scoresRef.current = scores; }, [scores]);
  useEffect(() => { detScoresRef.current = detScores; }, [detScores]);

  // Clock & uptime (client-only to prevent SSR hydration mismatch)
  useEffect(() => {
    setMounted(true);
    setCurTime(fmtTime());
    const t = setInterval(() => { setCurTime(fmtTime()); setUptime(u => u + 1); }, 1000);
    return () => clearInterval(t);
  }, []);

  // Main simulation tick (500ms)
  useEffect(() => {
    if (paused) return;
    const interval = setInterval(() => {
      frameCountRef.current += 1;
      const currentFrame = frameCountRef.current * 2;
      setFrameCount(frameCountRef.current);

      // Update camera scores
      setScores(prev => {
        const next = { ...prev };
        CAMERA_FEEDS.forEach(cam => {
          if (cam.id === "WEBCAM" && webcamActive && webcamDataRef.current.score !== null) {
            next["WEBCAM"] = Number(webcamDataRef.current.score);
          } else if (cam.id !== "WEBCAM") {
            const isInj = injecting && cam.id === injectCam;
            next[cam.id] = nextScore(prev[cam.id], 0.12, 0.20, isInj);
          }
        });
        // Threshold crossing alerts
        CAMERA_FEEDS.forEach(cam => {
          const was = prevScores.current[cam.id] || 0;
          const now = next[cam.id];
          if (now >= ALERT_THRESHOLD && was < ALERT_THRESHOLD) {
            const id = ++alertIdRef.current;
            playAlertChime(muted);
            setAlerts(a => [...a.slice(-9), {
              id,
              camId: cam.id,
              score: now,
              frameNum: currentFrame,
              evidence: `PRNU mismatch & rPPG pulse disruption detected at frame #${currentFrame}`,
              time: fmtTime()
            }]);
            setAlertCount(c => c + 1);
          }
        });
        prevScores.current = next;
        return next;
      });

      // Update rolling history using ref to avoid stale closure
      setHistory(prev => {
        const next = { ...prev };
        CAMERA_FEEDS.forEach(cam => {
          const s = scoresRef.current[cam.id] || 0;
          next[cam.id] = [...prev[cam.id].slice(-(HISTORY_WINDOW - 1)), s];
        });
        return next;
      });

      // Detector sub-scores
      setDetScores(prev => {
        const mainScore = scoresRef.current[selected] || 0;
        const next = { ...prev };
        DETECTOR_CFG.forEach(d => {
          if (selected === "WEBCAM" && webcamActive) {
            if (d.key === "rppg" && webcamDataRef.current.rppg_score !== null && webcamDataRef.current.rppg_score !== undefined) {
              next["rppg"] = Number(webcamDataRef.current.rppg_score);
            } else if (d.key === "video" && webcamDataRef.current.mobilenet_score !== null && webcamDataRef.current.mobilenet_score !== undefined) {
              next["video"] = Number(webcamDataRef.current.mobilenet_score);
            } else {
              const isInj = injecting && selected === injectCam;
              next[d.key] = nextScore(prev[d.key], d.base + mainScore * 0.3, d.variance, isInj);
            }
          } else {
            const isInj = injecting && selected === injectCam;
            next[d.key] = nextScore(prev[d.key], d.base + mainScore * 0.5, d.variance, isInj);
          }
        });
        return next;
      });

      setDetHist(prev => {
        const next = { ...prev };
        DETECTOR_CFG.forEach(d => {
          next[d.key] = [...prev[d.key].slice(-39), detScoresRef.current[d.key] || 0];
        });
        return next;
      });
    }, 500);
    return () => clearInterval(interval);
  }, [paused, injecting, injectCam, selected, muted, webcamActive]);

  const dismissAlert = useCallback((id) => setAlerts(a => a.filter(x => x.id !== id)), []);

  const selScore = scores[selected] || 0;
  const selHist = history[selected] || [];
  const isAlert = selScore >= ALERT_THRESHOLD;
  const isWarn = selScore >= WARN_THRESHOLD && !isAlert;

  const fmtUptime = (s) => {
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  };

  return (
    <div className="min-h-screen bg-[#080c13] text-slate-100 flex flex-col select-none overflow-x-hidden">
      {/* Alert Toasts */}
      <AlertToast alerts={alerts} onDismiss={dismissAlert} />

      {/* ── Header ── */}
      <header className={`flex-shrink-0 h-14 flex items-center px-4 gap-4 border-b border-slate-800/80 bg-slate-950/90 backdrop-blur-xl sticky top-0 z-50 transition-all ${isAlert ? "shadow-[0_1px_0_0_rgba(239,68,68,0.25)]" : ""}`}>
        {/* Brand */}
        <div className="flex items-center gap-2.5">
          <div className={`relative w-8 h-8 rounded-lg flex items-center justify-center border transition-all ${isAlert ? "bg-red-500/20 border-red-500/50 shadow-[0_0_12px_rgba(239,68,68,0.35)]" : "bg-cyan-500/15 border-cyan-500/30"}`}>
            {isAlert ? <ShieldAlert className="w-4 h-4 text-red-400" /> : <Shield className="w-4 h-4 text-cyan-400" />}
            <span className="absolute -top-0.5 -right-0.5 flex h-2 w-2">
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${isAlert ? "bg-red-400" : "bg-cyan-400"}`} />
              <span className={`relative inline-flex rounded-full h-2 w-2 ${isAlert ? "bg-red-500" : "bg-cyan-500"}`} />
            </span>
          </div>
          <div className="leading-tight">
            <div className="flex items-center gap-1.5">
              <span className="font-extrabold text-sm text-white tracking-tight">AEGIS</span>
              <span className="text-[9px] font-mono font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded bg-cyan-950/70 text-cyan-400 border border-cyan-800/50">SOC Monitor</span>
            </div>
            <p className="text-[10px] text-slate-500 hidden sm:block">Live Surveillance — Deepfake Detection</p>
          </div>
        </div>

        {/* Status pill */}
        <div className={`hidden md:flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-mono transition-all ${isAlert ? "bg-red-950/60 border-red-500/40 text-red-300 shadow-[0_0_16px_rgba(239,68,68,0.15)]" : isWarn ? "bg-amber-950/60 border-amber-500/40 text-amber-300" : "bg-slate-900/80 border-slate-800 text-emerald-400"}`}>
          {isAlert ? <><ShieldAlert className="w-3.5 h-3.5 text-red-400" /> THREAT DETECTED — {selected}</> : isWarn ? <><AlertTriangle className="w-3.5 h-3.5 text-amber-400" /> ELEVATED ANOMALY — {selected}</> : <><CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> ALL FEEDS NOMINAL</>}
        </div>

        {/* Gateway Telemetry Status Pill */}
        <div className={`hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[11px] font-mono transition-all ${
          gatewayTelemetry.connected
            ? gatewayTelemetry.profile === "PROD"
              ? "bg-emerald-950/60 border-emerald-500/40 text-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.2)]"
              : "bg-cyan-950/60 border-cyan-500/40 text-cyan-300"
            : "bg-slate-900 border-slate-800 text-slate-500"
        }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${gatewayTelemetry.connected ? "bg-emerald-400 animate-pulse" : "bg-slate-600"}`} />
          <span>GATEWAY: {gatewayTelemetry.connected ? gatewayTelemetry.profile : "STANDALONE"}</span>
        </div>

        <div className="flex-1" />

        {/* Stats */}
        <div className="hidden lg:flex items-center gap-4 text-[11px] font-mono text-slate-400">
          <span className="flex items-center gap-1" suppressHydrationWarning>
            <Clock className="w-3 h-3 text-slate-500" />
            {mounted ? curTime : "--:--:--"}
          </span>
          <span className="flex items-center gap-1" suppressHydrationWarning>
            <Activity className="w-3 h-3 text-emerald-400" />
            {mounted ? fmtUptime(uptime) : "00:00:00"}
          </span>
          <span className="flex items-center gap-1"><Camera className="w-3 h-3 text-cyan-400" /> {CAMERA_FEEDS.length} FEEDS</span>
          <span className="flex items-center gap-1"><Bell className="w-3 h-3 text-amber-400" /> {alertCount} ALERTS</span>
        </div>

        {/* Navigation & Controls */}
        <div className="flex items-center gap-2">
          {/* Webcam Connect Button (Task 3 rPPG) */}
          <button
            onClick={() => {
              const next = !webcamActive;
              setWebcamActive(next);
              if (next) setSelected("WEBCAM");
            }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold border transition-all cursor-pointer ${
              webcamActive
                ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.3)] animate-pulse"
                : "bg-slate-900 border-slate-800 text-slate-300 hover:text-white hover:border-slate-700"
            }`}
            title="Connect Live Webcam (Task 3 Streaming rPPG Pipeline)"
          >
            <Camera className="w-3.5 h-3.5 text-emerald-400" />
            <span className="hidden sm:inline">{webcamActive ? "WEBCAM ACTIVE" : "CONNECT WEBCAM"}</span>
          </button>

          <Link
            href="/"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-900 border border-slate-800 text-slate-300 hover:text-white hover:border-slate-700 transition-all cursor-pointer"
            title="Return to Forensic Upload Workstation"
          >
            <Upload className="w-3.5 h-3.5 text-cyan-400" />
            <span className="hidden sm:inline">Upload Workstation</span>
          </Link>
          <button
            onClick={() => {
              const next = !injecting;
              setInjecting(next);
              if (next) {
                // Trigger real penetration attack stream via Gateway Telemetry API on :8444
                fetch("http://localhost:8444/telemetry/inject", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ attack_type: "prnu_splice", camera_id: "camera-001", frames: 30 })
                }).catch(() => {});
              }
            }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold border transition-all cursor-pointer ${injecting ? "bg-red-500/20 border-red-500/50 text-red-300 shadow-[0_0_12px_rgba(239,68,68,0.2)] animate-pulse" : "bg-slate-900 border-slate-800 text-slate-300 hover:text-white hover:border-slate-700"}`}
            title="Inject Deepfake Adversarial Attack Stream"
          >
            <Zap className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">{injecting ? "STOP INJECT" : "INJECT"}</span>
          </button>
          <button onClick={() => setMuted(v => !v)} className="p-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:border-slate-700 transition-all cursor-pointer" title={muted ? "Unmute" : "Mute alerts"}>
            {muted ? <BellOff className="w-4 h-4" /> : <Bell className="w-4 h-4" />}
          </button>
          <button onClick={() => setPaused(v => !v)} className="p-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:border-slate-700 transition-all cursor-pointer" title={paused ? "Resume" : "Pause"}>
            {paused ? <Radio className="w-4 h-4 text-amber-400" /> : <Eye className="w-4 h-4" />}
          </button>
        </div>
      </header>

      {/* ── Main Grid ── */}
      <div className="flex-1 grid grid-cols-1 xl:grid-cols-[1fr_340px] min-h-0">

        {/* Left column */}
        <div className="flex flex-col gap-4 p-4 min-h-0">

          {/* Primary feed + score panel */}
          <div className={`rounded-2xl overflow-hidden border transition-all duration-500 ${isAlert ? "border-red-500/60 shadow-[0_0_40px_rgba(239,68,68,0.18)]" : isWarn ? "border-amber-500/40 shadow-[0_0_24px_rgba(245,158,11,0.1)]" : "border-slate-800/70"}`}>
            {isAlert && <div className="absolute inset-0 pointer-events-none bg-red-500/5 animate-pulse z-10" />}
            <div className="flex flex-col lg:flex-row">

              {/* Camera canvas / live webcam */}
              <div className="relative flex-1 bg-[#060c14] min-h-[240px] lg:min-h-[300px] flex items-center justify-center overflow-hidden">
                {selected === "WEBCAM" ? (
                  <div className="relative w-full h-full min-h-[260px] flex items-center justify-center bg-black">
                    {webcamConnected && feedMode === "backend" ? (
                      <img
                        src="http://localhost:8765/video_feed"
                        alt="Live Webcam rPPG Feed"
                        className="w-full h-full object-contain max-h-[460px]"
                        onError={() => {
                          setFeedMode("browser");
                        }}
                      />
                    ) : feedMode === "browser" ? (
                      <video
                        ref={videoElemRef}
                        autoPlay
                        playsInline
                        muted
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="flex flex-col items-center justify-center p-6 text-center text-slate-400">
                        <Camera className="w-10 h-10 text-cyan-400 mb-2.5 animate-pulse" />
                        <h4 className="text-sm font-bold text-white mb-1">Webcam Service Disconnected</h4>
                        <p className="text-xs text-slate-400 max-w-md mb-3">
                          Waiting for rPPG stream at <span className="font-mono text-cyan-300">http://localhost:8765/stream</span>
                        </p>
                        <div className="rounded-lg bg-slate-900 border border-slate-800 p-2.5 text-left font-mono text-[10px] text-slate-300 max-w-lg mb-3">
                          <p className="text-slate-500 mb-0.5"># Run in PowerShell:</p>
                          <code className="text-emerald-400 selection:bg-emerald-900 break-all">
                            {'& "D:\\Gpu-shit\\nasa\\Scripts\\python.exe" -m uvicorn detectors.rppg.streaming.webcam_stream:app --port 8765'}
                          </code>
                        </div>
                        <button
                          onClick={() => setFeedMode("browser")}
                          className="px-3 py-1.5 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-mono transition-all"
                        >
                          Switch to Direct Browser Webcam
                        </button>
                      </div>
                    )}

                    {/* Stream source mode toggle */}
                    <div className="absolute top-3 right-3 z-20 flex items-center gap-1 bg-black/80 backdrop-blur-md px-2 py-1 rounded-md border border-slate-700/60 text-[10px] font-mono">
                      <span className="text-slate-400">FEED:</span>
                      <button
                        onClick={() => setFeedMode("backend")}
                        className={`px-1.5 py-0.5 rounded transition-all ${feedMode === "backend" ? "bg-cyan-500/30 text-cyan-300 font-bold" : "text-slate-400 hover:text-white"}`}
                      >
                        OpenCV + MTCNN
                      </button>
                      <span className="text-slate-600">|</span>
                      <button
                        onClick={() => setFeedMode("browser")}
                        className={`px-1.5 py-0.5 rounded transition-all ${feedMode === "browser" ? "bg-cyan-500/30 text-cyan-300 font-bold" : "text-slate-400 hover:text-white"}`}
                      >
                        Browser Cam
                      </button>
                    </div>

                    {/* rPPG Live HUD overlay badge */}
                    <div className="absolute bottom-3 left-3 z-20 flex flex-wrap items-center gap-2">
                      <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-950/90 border border-emerald-500/40 text-[10px] font-mono font-bold text-emerald-300">
                        <span className="size-1.5 rounded-full bg-emerald-400 animate-ping" />
                        LIVE WEBCAM
                      </span>
                      <span className="px-2 py-0.5 rounded-full bg-black/70 border border-slate-700 text-[10px] font-mono text-cyan-300">
                        HR: {webcamData.hr_bpm ? `${webcamData.hr_bpm} BPM` : (webcamData.ready ? "Detecting" : "Warming up...")}
                      </span>
                      <span className="px-2 py-0.5 rounded-full bg-black/70 border border-slate-700 text-[10px] font-mono text-slate-300">
                        SNR: {webcamData.snr_db ? `${webcamData.snr_db} dB` : "--"}
                      </span>
                      <span className="px-2 py-0.5 rounded-full bg-black/70 border border-slate-700 text-[10px] font-mono text-slate-400">
                        Window: {webcamData.window_sec ? `${webcamData.window_sec.toFixed(1)}s` : "0.0s"}
                      </span>
                      {webcamData.face_detected && (
                        <span className="px-2 py-0.5 rounded-full bg-emerald-950/80 border border-emerald-500/30 text-[9px] font-mono text-emerald-400">
                          FACE LOCKED
                        </span>
                      )}
                    </div>
                  </div>
                ) : (
                  <>
                    <FakeCameraFeed camId={selected} score={selScore} isAlert={isAlert} isWarning={isWarn} active={!paused} />

                    {/* Alert badge */}
                    {isAlert && (
                      <div className="absolute top-3 left-1/2 -translate-x-1/2 flex items-center gap-2 px-4 py-1.5 rounded-full bg-red-950/90 border border-red-500/60 backdrop-blur-sm z-20 animate-pulse">
                        <ShieldAlert className="w-4 h-4 text-red-400" />
                        <span className="text-xs font-bold text-red-300 font-mono uppercase tracking-wider">DEEPFAKE DETECTED</span>
                      </div>
                    )}

                    {/* LIVE badge */}
                    <div className="absolute bottom-3 left-3 z-20 flex items-center gap-2">
                      <span className="flex h-2 w-2 relative">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                      </span>
                      <span className="text-[10px] font-mono text-emerald-400/80 bg-black/50 px-2 py-0.5 rounded-full">
                        LIVE · {CAMERA_FEEDS.find(c => c.id === selected)?.location}
                      </span>
                    </div>
                  </>
                )}
              </div>

              {/* Score sidebar */}
              <div className={`w-full lg:w-52 flex-shrink-0 flex flex-col gap-4 p-4 border-t lg:border-t-0 lg:border-l transition-colors ${isAlert ? "border-red-900/60 bg-red-950/20" : "border-slate-800/60 bg-slate-900/60"}`}>
                <div>
                  <p className="text-[10px] font-mono uppercase tracking-widest text-slate-500">Anomaly Score</p>
                  <div
                    className={`text-4xl font-black mt-1 tabular-nums transition-all ${isAlert ? "text-red-400" : isWarn ? "text-amber-400" : "text-emerald-400"}`}
                    style={{ textShadow: isAlert ? "0 0 20px rgba(239,68,68,0.5)" : undefined }}
                  >
                    {(selScore * 100).toFixed(1)}<span className="text-lg font-bold">%</span>
                  </div>
                  <div className={`mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono font-bold border ${isAlert ? "bg-red-500/15 text-red-300 border-red-500/40" : isWarn ? "bg-amber-500/15 text-amber-300 border-amber-500/40" : "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"}`}>
                    {isAlert ? <ShieldOff className="w-3 h-3" /> : isWarn ? <AlertTriangle className="w-3 h-3" /> : <CheckCircle2 className="w-3 h-3" />}
                    {scoreLabel(selScore)}
                  </div>
                </div>

                {/* Score bar */}
                <div className="space-y-1">
                  <div className="flex justify-between text-[9px] font-mono text-slate-500">
                    <span>0%</span><span>WARN</span><span>ALERT</span><span>100%</span>
                  </div>
                  <div className="h-3 rounded-full bg-slate-800 overflow-hidden relative">
                    <div
                      className="absolute left-0 top-0 h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${selScore * 100}%`,
                        background: isAlert ? "linear-gradient(90deg,#f97316,#ef4444)" : isWarn ? "linear-gradient(90deg,#10b981,#f59e0b)" : "linear-gradient(90deg,#10b981,#06b6d4)",
                        boxShadow: isAlert ? "0 0 10px rgba(239,68,68,0.6)" : "none",
                      }}
                    />
                    <div className="absolute top-0 h-full w-px bg-amber-500/60" style={{ left: `${WARN_THRESHOLD * 100}%` }} />
                    <div className="absolute top-0 h-full w-px bg-red-500/60" style={{ left: `${ALERT_THRESHOLD * 100}%` }} />
                  </div>
                </div>

                {/* Meta */}
                <div className="space-y-2 text-[11px] font-mono">
                  {[
                    { label: "Camera", val: selected },
                    { label: "Gateway", val: gatewayTelemetry.connected ? gatewayTelemetry.profile : "STANDALONE", danger: gatewayTelemetry.status === "COMPROMISED" },
                    { label: "Hash Chain", val: gatewayTelemetry.lastHash ? `${gatewayTelemetry.lastHash.slice(0, 10)}...` : "0x9F4A...B82D" },
                    { label: "PRNU Sensor", val: gatewayTelemetry.lastPce !== null && gatewayTelemetry.lastPce !== undefined ? `PCE ${gatewayTelemetry.lastPce.toFixed(1)}` : "Verified" },
                    { label: "Frames", val: gatewayTelemetry.lastSeq !== null ? String(gatewayTelemetry.lastSeq) : String(frameCount * 2) },
                    { label: "Alerts", val: String(alertCount), danger: alertCount > 0 },
                    { label: "Threshold", val: `${(ALERT_THRESHOLD * 100).toFixed(0)}%` },
                  ].map(({ label, val, danger }) => (
                    <div key={label} className="flex justify-between">
                      <span className="text-slate-500">{label}</span>
                      <span className={danger ? "text-red-400 font-bold" : "text-slate-300"}>{val}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Rolling anomaly chart */}
          <div className={`rounded-2xl border overflow-hidden transition-all duration-500 ${isAlert ? "border-red-900/60 bg-slate-900/80 shadow-[0_0_24px_rgba(239,68,68,0.08)]" : "border-slate-800/60 bg-slate-900/60"}`}>
            <div className="flex items-center justify-between px-4 pt-3 pb-2 border-b border-slate-800/60">
              <div className="flex items-center gap-2">
                <BarChart2 className="w-4 h-4 text-slate-400" />
                <span className="text-xs font-mono font-semibold text-slate-300">Rolling Anomaly Score — {selected}</span>
                <span className="text-[9px] font-mono text-slate-500">({HISTORY_WINDOW}s window)</span>
              </div>
              <div className="flex items-center gap-3 text-[10px] font-mono text-slate-500">
                <span>— Alert 65%</span>
                <span>— Warn 45%</span>
              </div>
            </div>
            <div className="h-44 px-1 py-1">
              <RollingScoreChart history={selHist} isAlert={isAlert} isWarning={isWarn} />
            </div>
          </div>

          {/* Detector sub-score sparklines */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {DETECTOR_CFG.map(d => {
              const s = detScores[d.key] || 0;
              const h = detHist[d.key] || [];
              const bad = s >= ALERT_THRESHOLD;
              const wrn = s >= WARN_THRESHOLD;
              const Icon = d.Icon;
              return (
                <div key={d.key} className={`rounded-xl border p-3 transition-all duration-300 ${bad ? "border-red-900/60 bg-red-950/20 shadow-[0_0_16px_rgba(239,68,68,0.08)]" : "border-slate-800/60 bg-slate-900/50"}`}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-1.5">
                      <Icon className="w-3.5 h-3.5" style={{ color: d.color }} />
                      <span className="text-[10px] font-mono font-semibold text-slate-300">{d.label}</span>
                    </div>
                    <span className="text-sm font-black tabular-nums" style={{ color: bad ? "#ef4444" : wrn ? "#f59e0b" : d.color }}>
                      {(s * 100).toFixed(0)}%
                    </span>
                  </div>
                  <Sparkline history={h} width={160} height={36} color={bad ? "#ef4444" : d.color} />
                  <p className="text-[9px] font-mono text-slate-500 mt-1">{d.model}</p>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Right sidebar ── */}
        <div className="hidden xl:flex flex-col border-l border-slate-800/60 bg-slate-950/50 min-h-0">

          {/* Camera grid */}
          <div className="p-4 border-b border-slate-800/60">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Camera className="w-4 h-4 text-slate-400" />
                <span className="text-xs font-mono font-semibold text-slate-300">CAMERA GRID</span>
              </div>
              <span className="text-[10px] font-mono text-slate-500">{CAMERA_FEEDS.length} ACTIVE</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {CAMERA_FEEDS.map(cam => {
                const s = scores[cam.id] || 0;
                const bad = s >= ALERT_THRESHOLD;
                const wrn = s >= WARN_THRESHOLD;
                const isSel = cam.id === selected;
                return (
                  <button
                    key={cam.id}
                    onClick={() => { setSelected(cam.id); setInjectCam(cam.id); }}
                    className={`relative rounded-lg overflow-hidden cursor-pointer transition-all duration-300 ${isSel ? (bad ? "ring-2 ring-red-500 shadow-[0_0_16px_rgba(239,68,68,0.3)]" : "ring-2 ring-cyan-500 shadow-[0_0_12px_rgba(6,182,212,0.2)]") : "opacity-70 hover:opacity-100"}`}
                  >
                    <div className="aspect-[4/3] bg-[#060c14] flex items-center justify-center">
                      {cam.id === "WEBCAM" ? (
                        webcamActive && webcamConnected && feedMode === "backend" ? (
                          <img src="http://localhost:8765/video_feed" alt="Webcam Thumb" className="w-full h-full object-cover" />
                        ) : (
                          <div className="flex flex-col items-center justify-center p-2 text-center">
                            <Camera className="w-6 h-6 text-emerald-400 mb-1" />
                            <span className="text-[10px] font-mono text-emerald-300">WEBCAM</span>
                            <span className="text-[8px] font-mono text-slate-400">{webcamActive ? (webcamConnected ? "STREAMING" : "CONNECTING") : "STANDBY"}</span>
                          </div>
                        )
                      ) : (
                        <FakeCameraFeed camId={cam.id} score={s} isAlert={bad} isWarning={wrn} active={!paused} />
                      )}
                    </div>
                    <div className={`absolute bottom-0 left-0 right-0 px-1.5 py-1 flex items-center justify-between text-[9px] font-mono ${bad ? "bg-red-950/80 text-red-300" : wrn ? "bg-amber-950/80 text-amber-300" : "bg-black/60 text-slate-300"}`}>
                      <span>{cam.id}</span>
                      <span>{(s * 100).toFixed(0)}%</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}