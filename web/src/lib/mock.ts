export type Verdict = "authentic" | "synthetic" | "inconclusive";
export type Modality = "video" | "audio" | "image" | "text";
export type Health = "healthy" | "degraded" | "down";
export type Level = "DEBUG" | "INFO" | "WARN" | "ERROR";

export const detectors = [
  { id: "video", name: "Video Classifier", model: "EfficientNet-B0", modality: "video" as Modality, latency: "2.4s", health: "healthy" as Health },
  { id: "rppg", name: "rPPG Heartbeat", model: "POS + band-pass", modality: "video" as Modality, latency: "3.1s", health: "degraded" as Health },
  { id: "syncnet", name: "SyncNet", model: "SyncNet v2", modality: "video" as Modality, latency: "1.8s", health: "healthy" as Health },
  { id: "aasist", name: "AASIST", model: "AASIST-L", modality: "audio" as Modality, latency: "0.9s", health: "healthy" as Health },
  { id: "text", name: "Text Detector", model: "Binoculars", modality: "text" as Modality, latency: "0.6s", health: "healthy" as Health },
  { id: "image", name: "Image Detector", model: "UnivFD (CLIP)", modality: "image" as Modality, latency: "0.7s", health: "degraded" as Health },
];

export const analyses = [
  { id: "AEG-1042", file: "press_briefing_0918.mp4", modality: "video" as Modality, verdict: "synthetic" as Verdict, confidence: 0.91, time: "09:42", status: "Complete" },
  { id: "AEG-1041", file: "ceo_voicemail.wav", modality: "audio" as Modality, verdict: "synthetic" as Verdict, confidence: 0.84, time: "09:15", status: "Complete" },
  { id: "AEG-1040", file: "protest_square.jpg", modality: "image" as Modality, verdict: "authentic" as Verdict, confidence: 0.88, time: "08:57", status: "Complete" },
  { id: "AEG-1039", file: "interview_raw_cut.mov", modality: "video" as Modality, verdict: "inconclusive" as Verdict, confidence: 0.52, time: "08:31", status: "Flagged" },
  { id: "AEG-1038", file: "op-ed_submission.txt", modality: "text" as Modality, verdict: "synthetic" as Verdict, confidence: 0.77, time: "08:04", status: "Complete" },
  { id: "AEG-1037", file: "witness_statement.mp3", modality: "audio" as Modality, verdict: "authentic" as Verdict, confidence: 0.93, time: "07:48", status: "Complete" },
  { id: "AEG-1036", file: "dashcam_clip_22.mp4", modality: "video" as Modality, verdict: "authentic" as Verdict, confidence: 0.95, time: "07:20", status: "Complete" },
];

export const verdictsWeek = [
  { day: "Fri", authentic: 42, synthetic: 11, inconclusive: 6 },
  { day: "Sat", authentic: 31, synthetic: 8, inconclusive: 4 },
  { day: "Sun", authentic: 28, synthetic: 6, inconclusive: 3 },
  { day: "Mon", authentic: 55, synthetic: 17, inconclusive: 9 },
  { day: "Tue", authentic: 61, synthetic: 14, inconclusive: 7 },
  { day: "Wed", authentic: 58, synthetic: 21, inconclusive: 8 },
  { day: "Thu", authentic: 47, synthetic: 16, inconclusive: 5 },
];

export const timeline = [
  { t: "09:44", kind: "alert", text: "CAM-07 Loading Dock — frame injection suspected" },
  { t: "09:42", kind: "done", text: "AEG-1042 completed — Synthetic (91%)" },
  { t: "09:38", kind: "upload", text: "press_briefing_0918.mp4 uploaded by M. Haddad" },
  { t: "09:21", kind: "warn", text: "rPPG detector degraded — p95 latency 6.2s" },
  { t: "09:15", kind: "done", text: "AEG-1041 completed — Synthetic (84%)" },
  { t: "08:57", kind: "done", text: "AEG-1040 completed — Authentic (88%)" },
];

export const logs: { ts: string; level: Level; svc: string; job: string; msg: string }[] = [
  { ts: "09:42:18.204", level: "INFO", svc: "judge", job: "AEG-1042", msg: "Final verdict=SYNTHETIC p=0.91 (5 detectors, 1 dissent)" },
  { ts: "09:42:16.990", level: "WARN", svc: "debate", job: "AEG-1042", msg: "Conflict: rppg(authentic 0.44) vs video(synthetic 0.93)" },
  { ts: "09:42:15.311", level: "INFO", svc: "syncnet", job: "AEG-1042", msg: "offset=+4 frames conf=2.1 → lip-sync mismatch" },
  { ts: "09:42:13.870", level: "INFO", svc: "aasist", job: "AEG-1042", msg: "spoof_score=0.81 segments=[12.4-15.0, 31.2-33.9]" },
  { ts: "09:42:12.402", level: "WARN", svc: "rppg", job: "AEG-1042", msg: "signal_quality=0.38 below threshold 0.5 (low light)" },
  { ts: "09:42:09.118", level: "INFO", svc: "video", job: "AEG-1042", msg: "frames=1450 mean_p=0.93 max_p=0.99" },
  { ts: "09:42:04.660", level: "DEBUG", svc: "orchestrator", job: "AEG-1042", msg: "plan=[video,rppg,syncnet,aasist] skip=[text,image]" },
  { ts: "09:42:03.002", level: "INFO", svc: "ingest", job: "AEG-1042", msg: "validated mp4 h264 1920x1080 48s audio=aac" },
  { ts: "09:21:40.551", level: "ERROR", svc: "rppg", job: "AEG-1039", msg: "TimeoutError: inference exceeded 6000ms" },
  { ts: "09:15:02.773", level: "INFO", svc: "judge", job: "AEG-1041", msg: "Final verdict=SYNTHETIC p=0.84" },
  { ts: "08:57:44.019", level: "INFO", svc: "image", job: "AEG-1040", msg: "gan_p=0.07 diffusion_p=0.12" },
  { ts: "08:31:10.420", level: "WARN", svc: "judge", job: "AEG-1039", msg: "Low agreement κ=0.21 → INCONCLUSIVE" },
];

export const cameras = [
  { id: "CAM-01", name: "Lobby North", loc: "HQ · Floor 1", status: "verified", conf: 0.97, lat: 120, fps: 30 },
  { id: "CAM-02", name: "Reception", loc: "HQ · Floor 1", status: "verified", conf: 0.95, lat: 140, fps: 30 },
  { id: "CAM-03", name: "Elevator Bank", loc: "HQ · Floor 1", status: "analyzing", conf: 0.71, lat: 210, fps: 25 },
  { id: "CAM-04", name: "Server Room", loc: "HQ · B1", status: "verified", conf: 0.98, lat: 95, fps: 30 },
  { id: "CAM-05", name: "Parking East", loc: "Lot B", status: "verified", conf: 0.92, lat: 180, fps: 15 },
  { id: "CAM-06", name: "Exec Corridor", loc: "HQ · Floor 9", status: "analyzing", conf: 0.66, lat: 230, fps: 25 },
  { id: "CAM-07", name: "Loading Dock", loc: "Warehouse", status: "suspect", conf: 0.23, lat: 260, fps: 30 },
  { id: "CAM-08", name: "Gate 2", loc: "Perimeter", status: "verified", conf: 0.94, lat: 150, fps: 20 },
  { id: "CAM-09", name: "Atrium", loc: "HQ · Floor 2", status: "verified", conf: 0.96, lat: 130, fps: 30 },
] as const;

export const reportJson = {
  job_id: "AEG-1042",
  input: { file: "press_briefing_0918.mp4", sha256: "9f2c4e81b7a0d3f6e5c2a19b8d4f7e60c3a1b2d9e8f7a6c5b4d3e2f1a0b9c8d7", duration_s: 48.3 },
  plan: { detectors: ["video", "rppg", "syncnet", "aasist"], skipped: { text: "no text modality", image: "video path covers frames" } },
  results: { video: { p_synthetic: 0.93, latency_ms: 2410 }, rppg: { p_synthetic: 0.44, bpm: 61, quality: 0.38 }, syncnet: { offset: 4, conf: 2.1, p_synthetic: 0.88 }, aasist: { p_synthetic: 0.81 } },
  verdict: { label: "SYNTHETIC", confidence: 0.91, dissent: ["rppg"] },
};
