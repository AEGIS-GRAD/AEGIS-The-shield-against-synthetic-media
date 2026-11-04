"use client";

import { useEffect, useRef, useState } from "react";
import {
  Grid2x2,
  Grid3x3,
  Square,
  CheckCircle2,
  AlertTriangle,
  Fingerprint,
  Clock,
  Film,
  Network,
  Camera,
  Activity,
  Radio,
  Zap,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { cameras } from "@/lib/mock";
import { Chip, ConfidenceMeter, PageHeader, Panel } from "@/components/aegis/ui";
import { ComingSoon } from "@/components/aegis/ComingSoon";
import { cn } from "@/lib/utils";
import LiveAlertDetailModal from "@/components/LiveAlertDetailModal";

type Cam = (typeof cameras)[number] | {
  id: string;
  name: string;
  loc: string;
  status: "verified" | "analyzing" | "suspect";
  conf: number;
  lat: number;
  fps: number;
};

const ring = {
  verified: "ring-authentic",
  analyzing: "ring-inconclusive",
  suspect: "ring-synthetic",
} as const;
const statusLabel = {
  verified: "Verified",
  analyzing: "Analyzing",
  suspect: "Suspected manipulation",
} as const;
const verdictOf = {
  verified: "authentic",
  analyzing: "inconclusive",
  suspect: "synthetic",
} as const;
const positions = [
  "50% 50%", "20% 40%", "80% 30%", "40% 80%", "65% 60%", "10% 10%", "90% 90%", "30% 20%", "70% 75%",
];
const anomalies = [
  { i: 14, label: "Frame injection" },
  { i: 22, label: "Replayed footage" },
  { i: 31, label: "Timestamp mismatch" },
];

export default function LivePage() {
  const [grid, setGrid] = useState<1 | 4 | 9>(9);
  const [sel, setSel] = useState<Cam>(cameras[6]!);
  const [tick, setTick] = useState(0);
  const [activeAlert, setActiveAlert] = useState<any>(null);
  const [injecting, setInjecting] = useState(false);
  const [injectFeedback, setInjectFeedback] = useState<string | null>(null);

  const handleInjectAttack = async () => {
    const next = !injecting;
    setInjecting(next);
    if (next) {
      try {
        setInjectFeedback("Injecting attack...");
        const res = await fetch("http://localhost:8444/telemetry/inject", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ attack_type: "prnu_splice", camera_id: sel.id || "camera-001", frames: 30 }),
        });
        if (res.ok) {
          setInjectFeedback("Attack payload dispatched to gateway (:8444)");
        } else {
          setInjectFeedback("Gateway responded with status " + res.status);
        }
      } catch (err) {
        setInjectFeedback("Adversarial payload simulated (Gateway :8444 offline)");
      }
      setTimeout(() => setInjectFeedback(null), 4000);
    } else {
      setInjectFeedback(null);
    }
  };

  // ─── Webcam Mode States ──────────────────────────────────────────────────
  const [webcamMode, setWebcamMode] = useState(false);
  const [webcamConnected, setWebcamConnected] = useState(false);
  const [webcamFeedSrc, setWebcamFeedSrc] = useState<"backend" | "browser">("backend");
  const [webcamData, setWebcamData] = useState<{
    ready: boolean;
    score: number | null;
    mobilenet_score: number | null;
    rppg_score: number | null;
    hr_bpm: number | null;
    snr_db: number | null;
    window_sec: number;
    reason: string;
    fps: number;
    face_detected: boolean;
  }>({
    ready: false,
    score: null,
    mobilenet_score: null,
    rppg_score: null,
    hr_bpm: null,
    snr_db: null,
    window_sec: 0,
    reason: "Idle",
    fps: 0,
    face_detected: false,
  });
  const [webcamHistory, setWebcamHistory] = useState<number[]>(() => Array(40).fill(0.88));
  const browserVideoRef = useRef<HTMLVideoElement | null>(null);
  const browserStreamRef = useRef<MediaStream | null>(null);

  // Simulation tick for background mock feeds
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1500);
    return () => clearInterval(id);
  }, []);

  // Connect to SSE stream when webcam is active
  useEffect(() => {
    if (!webcamMode) {
      if (browserStreamRef.current) {
        browserStreamRef.current.getTracks().forEach((t) => t.stop());
        browserStreamRef.current = null;
      }
      setWebcamConnected(false);
      return;
    }

    if (webcamFeedSrc === "browser") {
      navigator.mediaDevices?.getUserMedia({ video: true })
        .then((s) => {
          browserStreamRef.current = s;
          if (browserVideoRef.current) browserVideoRef.current.srcObject = s;
        })
        .catch((e) => console.warn("Browser camera error:", e));
    }

    const es = new EventSource("http://localhost:8765/stream");
    es.onopen = () => setWebcamConnected(true);
    es.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data);
        setWebcamData(d);
        if (d.score !== null && d.score !== undefined) {
          const auth = Math.max(0.05, Math.min(0.98, 1 - Number(d.score)));
          setWebcamHistory((prev) => [...prev.slice(-39), auth]);
        }
      } catch (err) {
        console.error("SSE parse error", err);
      }
    };
    es.onerror = () => setWebcamConnected(false);

    return () => {
      es.close();
      if (browserStreamRef.current) {
        browserStreamRef.current.getTracks().forEach((t) => t.stop());
        browserStreamRef.current = null;
      }
    };
  }, [webcamMode, webcamFeedSrc]);

  const webcamCamObj: Cam = {
    id: "CAM-WEBCAM",
    name: "Local Webcam",
    loc: "Device 0 · Task 3 Live rPPG",
    status: webcamData.ready ? (webcamData.score !== null && webcamData.score > 0.5 ? "suspect" : "verified") : "analyzing",
    conf: webcamData.score !== null ? 1 - webcamData.score : 0.88,
    lat: 16,
    fps: Math.round(webcamData.fps || 15),
  };

  const isWebcamSel = sel.id === "CAM-WEBCAM";
  const allFeeds = webcamMode ? [webcamCamObj, ...cameras] : cameras;
  const shown = grid === 1 ? [sel] : allFeeds.slice(0, grid);
  const suspect = sel.status === "suspect";

  const series = isWebcamSel
    ? webcamHistory.map((v, i) => ({
        i,
        t: `-${40 - i}s`,
        v,
      }))
    : Array.from({ length: 40 }, (_, i) => {
        const base = suspect ? (i > 12 ? 0.35 : 0.9) : sel.conf;
        return {
          i,
          t: `-${40 - i}s`,
          v: Math.max(
            0.05,
            Math.min(
              1,
              base + Math.sin((i + tick) / 2) * 0.06 - (suspect && anomalies.some((a) => a.i === i) ? 0.2 : 0)
            )
          ),
        };
      });

  return (
    <div>
      <PageHeader
        title="Live Surveillance"
        subtitle={
          webcamMode
            ? "Task 3 Live Pipeline Active · Real-time sliding-window rPPG pulse analysis"
            : "9 feeds · sliding 4-second analysis window"
        }
        actions={
          <div className="flex items-center gap-3">
            {/* Adversarial Attack Injection Button */}
            <button
              onClick={handleInjectAttack}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-bold transition-soft cursor-pointer",
                injecting
                  ? "bg-synthetic-soft text-synthetic-ink border-synthetic/40 shadow-sm animate-pulse"
                  : "bg-card text-muted-foreground hover:bg-secondary hover:text-primary"
              )}
              title="Inject Deepfake Adversarial Attack Stream (PRNU Splice test on Gateway :8444)"
            >
              <Zap className={cn("size-3.5", injecting ? "text-synthetic animate-pulse" : "text-amber-500")} />
              {injecting ? "Stop Inject" : "Inject Attack"}
            </button>

            {/* Webcam Toggle Button */}
            <button
              onClick={() => {
                const next = !webcamMode;
                setWebcamMode(next);
                if (next) setSel(webcamCamObj);
                else setSel(cameras[6]!);
              }}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-bold transition-soft",
                webcamMode
                  ? "bg-authentic-soft text-authentic-ink border-authentic/40 shadow-sm"
                  : "bg-card text-muted-foreground hover:bg-secondary hover:text-primary"
              )}
              title="Connect webcam to test Task 3 streaming rPPG pipeline"
            >
              <Camera className="size-3.5" />
              {webcamMode ? "Webcam Active" : "Connect Webcam"}
            </button>

            {/* Grid layout switcher */}
            <div className="flex rounded-lg border bg-card p-0.5">
              {([[1, Square], [4, Grid2x2], [9, Grid3x3]] as const).map(([n, I]) => (
                <button
                  key={n}
                  onClick={() => setGrid(n)}
                  aria-label={`${n} feeds`}
                  className={cn(
                    "rounded-md p-2 transition-soft",
                    grid === n ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary"
                  )}
                >
                  <I className="size-4" />
                </button>
              ))}
            </div>
          </div>
        }
      />
      {injectFeedback && (
        <div className="mb-4 flex items-center justify-between rounded-lg border border-amber-300 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-950/20 px-3.5 py-2 text-xs text-amber-900 dark:text-amber-200">
          <div className="flex items-center gap-2">
            <Zap className="size-3.5 text-amber-600 dark:text-amber-400" />
            <span>{injectFeedback}</span>
          </div>
          <span className="text-[10px] font-mono uppercase text-amber-700 dark:text-amber-400">Target: {sel.id}</span>
        </div>
      )}

      {/* Grid of feeds */}
      <div className={cn("grid gap-4", grid === 1 ? "grid-cols-1" : grid === 4 ? "md:grid-cols-2" : "md:grid-cols-3")}>
        {shown.map((c, idx) => {
          const isCamWebcam = c.id === "CAM-WEBCAM";
          return (
            <button
              key={c.id}
              onClick={() => setSel(c)}
              className={cn(
                "group relative overflow-hidden rounded-xl text-left ring-[3px] ring-offset-2 ring-offset-background transition-soft",
                ring[c.status],
                sel.id === c.id && "shadow-lift"
              )}
            >
              {isCamWebcam ? (
                <div className="aspect-video w-full bg-black flex items-center justify-center overflow-hidden relative">
                  {webcamConnected && webcamFeedSrc === "backend" ? (
                    <img
                      src="http://localhost:8765/video_feed"
                      alt="Webcam rPPG feed"
                      className="w-full h-full object-contain"
                      onError={() => setWebcamFeedSrc("browser")}
                    />
                  ) : webcamFeedSrc === "browser" ? (
                    <video ref={browserVideoRef} autoPlay playsInline muted className="w-full h-full object-cover" />
                  ) : (
                    <div className="p-4 text-center">
                      <Camera className="size-8 text-authentic mx-auto mb-1 animate-pulse" />
                      <p className="text-xs font-semibold text-primary">Webcam Stream</p>
                      <p className="text-[10px] text-muted-foreground">Waiting for :8765/stream</p>
                    </div>
                  )}
                </div>
              ) : (
                <img
                  src="/cctv.jpg"
                  alt={`${c.name} feed`}
                  width={1280}
                  height={720}
                  className={cn("aspect-video w-full object-cover", c.status === "suspect" && "hue-rotate-15 saturate-150")}
                  style={{
                    objectPosition: positions[cameras.indexOf(c as any)] ?? positions[idx],
                    transform: "scale(1.4)",
                  }}
                />
              )}

              <div className="absolute inset-0 bg-gradient-to-t from-primary/80 via-transparent to-primary/30" />
              {c.status === "analyzing" && (
                <div className="pointer-events-none absolute inset-x-0 h-1/3 bg-gradient-to-b from-transparent via-inconclusive/20 to-transparent animate-scan" />
              )}
              <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-md bg-synthetic px-1.5 py-0.5 text-[10px] font-bold text-primary-foreground">
                <span className="size-1.5 rounded-full bg-primary-foreground animate-live" />
                {isCamWebcam ? "TASK 3 WEBCAM" : "LIVE"}
              </div>
              <div className="mono absolute right-3 top-3 flex gap-1 text-[10px]">
                <span className="rounded bg-card/90 px-1.5 py-0.5 text-primary">{c.lat}ms</span>
                <span className="rounded bg-card/90 px-1.5 py-0.5 text-primary">{c.fps}fps</span>
              </div>
              <div className="absolute inset-x-3 bottom-3 flex items-end justify-between text-primary-foreground">
                <div>
                  <div className="text-sm font-semibold">{c.name}</div>
                  <div className="text-[11px] opacity-80">
                    {c.id} · {c.loc}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[11px] opacity-80">{statusLabel[c.status]}</div>
                  <div className="mono font-semibold">{Math.round(c.conf * 100)}%</div>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Detail panel */}
      <div className="mt-6 grid gap-6 xl:grid-cols-[1fr_360px]">
        <Panel
          title={
            <span className="flex items-center gap-2">
              {sel.name} <Chip tone={suspect ? "bad" : sel.status === "analyzing" ? "warn" : "good"}>{statusLabel[sel.status]}</Chip>
              {isWebcamSel && <Chip tone="neutral">LIVE HARDWARE</Chip>}
            </span>
          }
          subtitle={`${sel.id} · ${sel.loc} · authenticity over time`}
        >
          {isWebcamSel && !webcamConnected && (
            <div className="mb-4 rounded-xl border border-inconclusive/40 bg-inconclusive-soft/50 p-3 text-xs flex items-center justify-between">
              <div>
                <b>Backend rPPG service not running.</b> Run the following in PowerShell to start the OpenCV pipeline:
                <code className="block mt-1 font-mono text-[11px] text-accent">
                  {'& "D:\\Gpu-shit\\nasa\\Scripts\\python.exe" -m uvicorn detectors.rppg.streaming.webcam_stream:app --port 8765'}
                </code>
              </div>
              <button
                onClick={() => setWebcamFeedSrc(webcamFeedSrc === "backend" ? "browser" : "backend")}
                className="shrink-0 ml-3 rounded border bg-card px-2 py-1 text-[11px] font-medium"
              >
                Use {webcamFeedSrc === "backend" ? "Browser Video" : "OpenCV Stream"}
              </button>
            </div>
          )}

          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series}>
                <CartesianGrid vertical={false} stroke="var(--color-border)" />
                <XAxis
                  dataKey="t"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  stroke="var(--color-muted-foreground)"
                  interval={7}
                />
                <YAxis
                  domain={[0, 1]}
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  stroke="var(--color-muted-foreground)"
                  tickFormatter={(v) => `${Math.round(v * 100)}%`}
                />
                <Tooltip
                  formatter={(v: number) => `${Math.round(v * 100)}%`}
                  contentStyle={{
                    borderRadius: 8,
                    border: "1px solid var(--color-border)",
                    fontSize: 12,
                  }}
                />
                <ReferenceLine y={0.5} stroke="var(--color-inconclusive)" strokeDasharray="4 4" />
                <Line
                  dataKey="v"
                  name="Authenticity"
                  stroke={isWebcamSel ? "var(--color-authentic)" : "var(--color-chart-1)"}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                {suspect &&
                  anomalies.map((a) => (
                    <ReferenceDot
                      key={a.i}
                      x={series[a.i]!.t}
                      y={series[a.i]!.v}
                      r={6}
                      fill="var(--color-synthetic)"
                      stroke="var(--color-card)"
                      strokeWidth={2}
                    />
                  ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          {!isWebcamSel && suspect && (
            <div className="mt-3 flex flex-wrap gap-2">
              {anomalies.map((a) => (
                <button
                  key={a.i}
                  onClick={() => {
                    setActiveAlert({
                      id: 800 + a.i,
                      camId: sel.id,
                      score: 0.88,
                      frameNum: 1420 + a.i * 12,
                      time: `Just now (${series[a.i]?.t || '-12s'})`,
                      verdict: "INTEGRITY_UNKNOWN",
                      integritySignals: {
                        hash_chain_ok: false,
                        last_hash: "0x3C1E...7A41 [SEVERED]",
                        prnu_ok: false,
                        prnu_pce: 18.2,
                        prnu_threshold: 50.0,
                        anomalies: [
                          `${a.label} detected at timestamp ${series[a.i]?.t || '-12s'}`,
                          "Hardware PRNU PCE 18.2 < 50.0 baseline (Sensor Splice)",
                        ],
                      },
                      aiSignals: {
                        mobilenet_score: 0.85,
                        rppg_score: 0.72,
                        hr_bpm: 84,
                        syncnet_score: 0.68,
                        face_detected: true,
                      },
                      manifestHash: `0x${Array.from({ length: 64 }, (_, idx) => ((idx * 19 + a.i * 7) % 16).toString(16)).join("")}`,
                    });
                  }}
                  className="inline-flex cursor-pointer hover:opacity-80 transition-opacity"
                >
                  <Chip tone="bad">
                    <AlertTriangle className="mr-1 size-3" />
                    {a.label} · {series[a.i]!.t} (Inspect Evidence →)
                  </Chip>
                </button>
              ))}
              <Chip tone="bad">Synthetic face replacement</Chip>
            </div>
          )}

          {isWebcamSel && webcamData.ready && (
            <div className="mt-3 flex flex-wrap gap-2">
              {webcamData.score !== null && webcamData.score > 0.5 ? (
                <Chip tone="bad">
                  <AlertTriangle className="mr-1 size-3" />
                  Elevated anomaly score: {(webcamData.score * 100).toFixed(1)}%
                </Chip>
              ) : (
                <>
                  <Chip tone="good">
                    Forehead Pulse Verified ({webcamData.hr_bpm ?? 75} BPM)
                  </Chip>
                  <Chip tone="good">
                    MobileNetV3 Edge Model: Real
                  </Chip>
                  <Chip tone="neutral">
                    Anti-Glare Forehead ROI Active
                  </Chip>
                </>
              )}
            </div>
          )}

          {/* Detector breakdown */}
          <div className="mt-5 grid gap-3 md:grid-cols-2">
            {[
              [
                "rPPG Pulse Detector",
                isWebcamSel
                  ? (webcamData.score !== null ? 1 - (webcamData.rppg_score ?? webcamData.score) : 0.88)
                  : (suspect ? 0.35 : 0.92),
                isWebcamSel
                  ? (webcamData.hr_bpm ? `${webcamData.hr_bpm} BPM · SNR ${webcamData.snr_db ?? 0} dB · Forehead ROI` : "Forehead skin chromatic tracking")
                  : "POS Chrominance bandpass"
              ],
              [
                "Video Classifier",
                isWebcamSel
                  ? (webcamData.mobilenet_score !== null && webcamData.mobilenet_score !== undefined ? 1 - webcamData.mobilenet_score : 0.94)
                  : (suspect ? 0.21 : 0.95),
                isWebcamSel
                  ? "MobileNetV3 Edge Model · FF++ fine-tuned"
                  : "Frame artifacts & blending"
              ],
              [
                "SyncNet",
                suspect ? 0.34 : 0.9,
                "AV speech synchronization"
              ],
              [
                "Frame continuity",
                suspect ? 0.18 : 0.97,
                "Optical flow temporal stability"
              ],
            ].map(([n, v, sub]) => (
              <div key={n as string} className="rounded-lg border p-3">
                <div className="mb-1 flex justify-between text-sm">
                  <span className="font-medium">{n}</span>
                  <span className="caption">authenticity</span>
                </div>
                <div className="caption mb-2 text-[11px] text-muted-foreground">{sub as string}</div>
                <ConfidenceMeter
                  value={v as number}
                  verdict={
                    verdictOf[(v as number) > 0.7 ? "verified" : (v as number) > 0.45 ? "analyzing" : "suspect"]
                  }
                />
              </div>
            ))}
          </div>
        </Panel>

        {/* Feed integrity panel with simulated marker */}
        <Panel
          title={
            <div className="flex items-center justify-between">
              <span>Feed integrity</span>
              <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-muted text-muted-foreground border">
                SIMULATED
              </span>
            </div>
          }
          subtitle="Transport & provenance checks"
        >
          <ComingSoon
            variant="callout"
            title="Integrity Pipeline [Simulated]"
            description="Cryptographic hardware attestation (Ed25519) and frame-hash sequence verification are modeled below for evaluation."
            className="mb-4"
          />
          <ul className="space-y-4 text-sm">
            {[
              [Fingerprint, "Stream signature", suspect ? "Mismatch at 09:44:02" : "Valid (Ed25519)", !suspect],
              [Clock, "Timestamp drift", suspect ? "+2.8 s vs NTP" : "+12 ms", !suspect],
              [Film, "Frame continuity", suspect ? "37 frames duplicated" : "No gaps", !suspect],
              [Network, "Network path", "3 hops · TLS 1.3", true],
              [CheckCircle2, "Encoder fingerprint", "Matches CAM registry", true],
            ].map(([I, k, v, ok]) => {
              const Icon = I as typeof Clock;
              return (
                <li key={k as string} className="flex items-start gap-3">
                  <span
                    className={cn(
                      "grid size-8 shrink-0 place-items-center rounded-lg",
                      ok ? "bg-authentic-soft text-authentic-ink" : "bg-synthetic-soft text-synthetic-ink"
                    )}
                  >
                    <Icon className="size-4" />
                  </span>
                  <div>
                    <div className="font-medium">{k as string}</div>
                    <div className="caption">{v as string}</div>
                  </div>
                </li>
              );
            })}
          </ul>
        </Panel>
      </div>

      {/* Fused Alert Detail Modal for Live Surveillance */}
      {activeAlert && (
        <LiveAlertDetailModal
          alert={activeAlert}
          onClose={() => setActiveAlert(null)}
          onAcknowledge={() => setActiveAlert(null)}
        />
      )}
    </div>
  );
}
