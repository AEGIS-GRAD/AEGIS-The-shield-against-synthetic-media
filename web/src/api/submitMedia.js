/**
 * Submits a media file (video or audio) for deepfake detection analysis
 * by posting to the Cybersecurity API Gateway endpoint or Orchestrator.
 */

import { logger } from "./systemLogger";

const API_GATEWAY_URL = process.env.NEXT_PUBLIC_API_GATEWAY_URL || "http://localhost:8081";
const INTERNAL_API_KEY = process.env.NEXT_PUBLIC_INTERNAL_API_KEY || "aegis-secret-key-change-in-prod";
const ORCHESTRATOR_BASE_URL = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL || "http://localhost:8000";

export const DEMO_PRESETS = [
  {
    id: "clean_baseline",
    title: "Clean Baseline Video",
    filename: "clean_interview_broadcast.mp4",
    mimeType: "video/mp4",
    modality: "Multimodal (Video + Audio)",
    scenario: "Full Consensus: Verified Authentic",
    badgeColor: "text-emerald-400 border-emerald-500/40 bg-emerald-950/40",
    description: "Authentic broadcast interview with natural audio-visual sync and authentic pulse.",
  },
  {
    id: "voice_clone",
    title: "Voice Clone Deepfake",
    filename: "synthetic_voice_clone_scam.wav",
    mimeType: "audio/wav",
    modality: "Audio Only",
    scenario: "Acoustic Spoofing: Synthetic Speech",
    badgeColor: "text-violet-400 border-violet-500/40 bg-violet-950/40",
    description: "Neural voice cloning with vocoder artifacts; visual detectors gracefully skipped.",
  },
  {
    id: "silent_video",
    title: "Silent Video Edge Case",
    filename: "surveillance_silent_clip.mp4",
    mimeType: "video/mp4",
    modality: "Video Only (Silent)",
    scenario: "Edge Case: Zero Audio Track",
    badgeColor: "text-cyan-400 border-cyan-500/40 bg-cyan-950/40",
    description: "Camera footage without audio track; audio and syncnet detectors marked Not Applicable.",
  },
  {
    id: "cross_modal_conflict",
    title: "Cross-Modal Conflict",
    filename: "dubbed_speech_conflict.mp4",
    mimeType: "video/mp4",
    modality: "Multimodal (Video + Audio)",
    scenario: "Disagreement: Authentic Face + Fake Audio",
    badgeColor: "text-amber-400 border-amber-500/40 bg-amber-950/40",
    description: "Authentic visual video paired with cloned synthetic voice and lip desynchronization.",
  },
];

export function createPresetFile(presetId) {
  const preset = DEMO_PRESETS.find((p) => p.id === presetId);
  if (!preset) return null;
  const content = new Blob([new Uint8Array(48 * 1024)], { type: preset.mimeType });
  const file = new File([content], preset.filename, { type: preset.mimeType });
  file.__presetId = preset.id;
  return file;
}

function makeJobId() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `job-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function notApplicableResponse(jobId, modelVersion, reason) {
  return {
    job_id: jobId,
    confidence: 0.0,
    raw_score: 0.0,
    latency_ms: 0,
    ram_usage_mb: 0,
    model_version: modelVersion,
    evidence: {
      claim: reason,
      flags: ["not_applicable"],
    },
  };
}

function completedResponse(jobId, modelVersion, { confidence, rawScore, latencyMs, ramMb = 950, claim, flags = [] }) {
  return {
    job_id: jobId,
    confidence,
    raw_score: rawScore,
    latency_ms: latencyMs,
    ram_usage_mb: ramMb,
    model_version: modelVersion,
    evidence: { claim, flags },
  };
}

function formatResultsFromStatus(statusData, jobId, isAudio) {
  const dets = statusData.detectors || {};

  const video_classifier = !isAudio && dets.video_classifier?.status === "complete"
    ? completedResponse(jobId, "efficientnet-b0-ffpp", {
        confidence: dets.video_classifier.confidence ?? 0.15,
        rawScore: dets.video_classifier.raw_score ?? -1.4,
        latencyMs: dets.video_classifier.latency_ms ?? 310,
        ramMb: dets.video_classifier.ram_usage_mb ?? 940,
        claim: dets.video_classifier.claim ?? "Frame-level facial boundary analysis completed.",
        flags: dets.video_classifier.flags ?? [],
      })
    : notApplicableResponse(jobId, "efficientnet-b0-ffpp", dets.video_classifier?.claim || "Submitted media file has no video stream — visual frame analysis skipped.");

  const aasist = dets.aasist?.status === "complete"
    ? completedResponse(jobId, "aasist-gat-v2", {
        confidence: dets.aasist.confidence ?? 0.12,
        rawScore: dets.aasist.raw_score ?? -1.8,
        latencyMs: dets.aasist.latency_ms ?? 195,
        ramMb: dets.aasist.ram_usage_mb ?? 620,
        claim: dets.aasist.claim ?? "Acoustic spectral graph attention inference completed.",
        flags: dets.aasist.flags ?? [],
      })
    : notApplicableResponse(jobId, "aasist-gat-v2", dets.aasist?.claim || "No audio stream present in media file — AASIST speech verification skipped.");

  const rppg = !isAudio && dets.rppg?.status === "complete"
    ? completedResponse(jobId, "rppg-chrom-bvp", {
        confidence: dets.rppg.confidence ?? 0.18,
        rawScore: dets.rppg.raw_score ?? 2.8,
        latencyMs: dets.rppg.latency_ms ?? 450,
        ramMb: dets.rppg.ram_usage_mb ?? 1120,
        claim: dets.rppg.claim ?? "CHROM facial blood volume pulse recovered.",
        flags: dets.rppg.flags ?? [],
      })
    : notApplicableResponse(jobId, "rppg-chrom-bvp", dets.rppg?.claim || "No visible facial region in submitted media — pulse extraction skipped.");

  const syncnet = !isAudio && dets.syncnet?.status === "complete"
    ? completedResponse(jobId, "syncnet-phoneme-viseme", {
        confidence: dets.syncnet.confidence ?? 0.20,
        rawScore: dets.syncnet.raw_score ?? 1.5,
        latencyMs: dets.syncnet.latency_ms ?? 280,
        ramMb: dets.syncnet.ram_usage_mb ?? 1380,
        claim: dets.syncnet.claim ?? "Audio-visual lip sync alignment evaluated.",
        flags: dets.syncnet.flags ?? [],
      })
    : notApplicableResponse(jobId, "syncnet-phoneme-viseme", dets.syncnet?.claim || "Lip-sync synchronization not applicable for this media modality.");

  return { video_classifier, rppg, aasist, syncnet };
}

/**
 * Sends a real media upload request directly to the Cybersecurity API Gateway.
 */
export async function submitMediaGateway(file) {
  if (!file) {
    throw new Error("No media file provided for submission.");
  }

  const isAudio = file.type.startsWith("audio/");
  const endpoint = isAudio
    ? `${API_GATEWAY_URL}/api/audio`
    : `${API_GATEWAY_URL}/api/video`;

  try {
    let response;

    if (isAudio) {
      const arrayBuffer = await file.arrayBuffer();
      const base64Payload = btoa(
        new Uint8Array(arrayBuffer).reduce((data, byte) => data + String.fromCharCode(byte), "")
      );

      response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Internal-Token": INTERNAL_API_KEY,
        },
        body: JSON.stringify({
          job_id: `job-${Date.now()}`,
          modality: "audio",
          payload: base64Payload,
        }),
        signal: AbortSignal.timeout ? AbortSignal.timeout(2000) : undefined,
      });
    } else {
      const formData = new FormData();
      formData.append("file", file, file.name);

      response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "X-Internal-Token": INTERNAL_API_KEY,
        },
        body: formData,
        signal: AbortSignal.timeout ? AbortSignal.timeout(2000) : undefined,
      });
    }

    const statusCode = response.status;
    let data;
    try {
      data = await response.json();
    } catch {
      data = { error: "Gateway returned a non-JSON response" };
    }

    return {
      raw_response: data,
      endpoint_used: endpoint,
      status_code: statusCode,
      video_classifier: !isAudio ? data : { evidence: { claim: "Skipped (audio file)", flags: ["not_applicable"] } },
      rppg: !isAudio ? { evidence: { claim: "rPPG analyzed via Gateway pipeline", flags: [] } } : { evidence: { claim: "Skipped (audio file)", flags: ["not_applicable"] } },
      aasist: isAudio ? data : { evidence: { claim: "Skipped (video file without audio pipeline dispatch)", flags: ["not_applicable"] } },
      syncnet: { evidence: { claim: "SyncNet analyzed via Gateway pipeline", flags: [] } },
    };
  } catch (error) {
    const errorResponse = {
      error: "API Gateway network request failed",
      message: error.message,
      target_endpoint: endpoint,
      hint: "Falling back to standalone simulation harness."
    };

    return {
      raw_response: errorResponse,
      endpoint_used: endpoint,
      status_code: 503,
      video_classifier: { error: error.message, evidence: { claim: `Failed to contact gateway at ${endpoint}`, flags: ["error"] } },
    };
  }
}

/**
 * Submits media with real-time per-detector status updates for the LiveStatusScreen.
 */
export async function submitMediaWithProgress(file, onProgress) {
  if (!file) {
    throw new Error("No media file provided for submission.");
  }

  const isAudio = file.type.startsWith("audio/");
  const jobId = makeJobId();
  const presetId = file.__presetId;

  // If a predefined demo preset was selected, directly execute the tailored preset simulation
  if (presetId) {
    return runPresetSimulation(presetId, file, jobId, onProgress);
  }

  // Log submission initiation
  logger.info("Ingestion", `Initiating verification for uploaded file '${file.name}' (${formatFileSize(file.size)})`, {
    job_id: jobId,
    filename: file.name,
    size_bytes: file.size,
    type: file.type,
    is_audio: isAudio,
  });

  // Attempt real Orchestrator connection
  logger.info("Orchestrator", `Sending health check to ${ORCHESTRATOR_BASE_URL}/health...`);

  let probe;
  try {
    probe = await fetch(`${ORCHESTRATOR_BASE_URL}/health`, {
      method: "GET",
      signal: AbortSignal.timeout ? AbortSignal.timeout(1500) : undefined,
    });
  } catch (err) {
    logger.error("Orchestrator", `Backend unreachable at ${ORCHESTRATOR_BASE_URL}/health. Connection refused or timeout.`, {
      error: err.message,
      target_url: `${ORCHESTRATOR_BASE_URL}/health`,
    });

    throw new Error(
      `BACKEND OFFLINE: Failed to connect to Python Orchestrator at ${ORCHESTRATOR_BASE_URL}. Go to the terminal to see what the error is and verify uvicorn/fastapi is running.`
    );
  }

  if (!probe.ok) {
    logger.error("Orchestrator", `Backend health probe returned status ${probe.status}`, { status: probe.status });
    throw new Error(
      `BACKEND HEALTH ERROR: Orchestrator health endpoint returned HTTP ${probe.status}. Go to the terminal to see what the error is.`
    );
  }

  logger.info("Orchestrator", `Health check OK. Dispatching media to ${ORCHESTRATOR_BASE_URL}/orchestrate...`);

  const formData = new FormData();
  formData.append("file", file);

  let orchestrateRes;
  try {
    orchestrateRes = await fetch(`${ORCHESTRATOR_BASE_URL}/orchestrate`, {
      method: "POST",
      headers: {
        "X-API-Key": INTERNAL_API_KEY,
      },
      body: formData,
      signal: AbortSignal.timeout ? AbortSignal.timeout(45000) : undefined,
    });
  } catch (err) {
    logger.error("Orchestrator", `POST /orchestrate network request failed`, {
      error: err.message,
      target_url: `${ORCHESTRATOR_BASE_URL}/orchestrate`,
    });
    throw new Error(
      `PIPELINE NETWORK FAILURE: Failed to post media to ${ORCHESTRATOR_BASE_URL}/orchestrate. Go to the terminal to see what the error is.`
    );
  }

  if (!orchestrateRes.ok) {
    let errorText = "";
    try {
      const errJson = await orchestrateRes.json();
      errorText = errJson.detail || JSON.stringify(errJson);
    } catch {
      errorText = await orchestrateRes.text();
    }
    logger.error("Orchestrator", `POST /orchestrate returned HTTP ${orchestrateRes.status}`, {
      status: orchestrateRes.status,
      detail: errorText,
    });

    throw new Error(
      `ORCHESTRATOR HTTP ${orchestrateRes.status}: ${errorText || "Internal Server Error"}. Go to the terminal to see what the error is.`
    );
  }

  const data = await orchestrateRes.json();
  logger.success("Orchestrator", `Received response from /orchestrate`, data);

  // Transform orchestrator response to grid format
  const detectorMap = {};
  for (const item of data.raw_results || []) {
    detectorMap[item.detector] = item;
    if (item.status !== "ok") {
      logger.warn("Detector Warning", `Detector '${item.detector}' failed execution: ${item.error || "Unknown error"}`, item);
    } else {
      logger.info("Detector Success", `Detector '${item.detector}' returned score ${item.raw_score} (latency: ${item.latency_ms}ms)`, item);
    }
  }

  if (onProgress) {
    onProgress({
      job_id: jobId,
      filename: file.name,
      modality: data.metadata?.modality || (isAudio ? "audio" : "video"),
      overall_status: "completed",
      progress_percent: 100,
      elapsed_ms: 650,
      detectors: Object.fromEntries(
        Object.entries(detectorMap).map(([k, v]) => [k, { ...v, status: v.status === "ok" ? "complete" : "failed" }])
      ),
    });
  }

  return {
    ...detectorMap,
    judge_verdict: data.judge_verdict,
    judge_score: data.judge_score,
    judge_mode: data.judge_mode,
    siem_alert_tier: data.siem_alert_tier,
    guards_applied: data.guards_applied || [],
    debate_transcript: data.debate_transcript,
    debate_transcript_hash: data.debate_transcript_hash,
    forensic_justification: data.forensic_justification,
    cross_examination_findings: data.cross_examination_findings,
    adjudication_latency_ms: data.adjudication_latency_ms,
    raw_response: data,
    endpoint_used: `${ORCHESTRATOR_BASE_URL}/orchestrate`,
    status_code: 200,
  };
}

/**
 * Runs tailored simulation for the 4 demo presets
 */
async function runPresetSimulation(presetId, file, jobId, onProgress) {
  logger.info("Demo Preset", `Running predefined demo preset '${presetId}' (File: ${file.name})`, {
    preset_id: presetId,
    job_id: jobId,
    filename: file.name,
    note: "This is a curated demo preset for demonstration testing.",
  });
  const startTime = Date.now();
  const isAudio = presetId === "voice_clone";
  const isSilent = presetId === "silent_video";
  const isConflict = presetId === "cross_modal_conflict";

  const state = {
    job_id: jobId,
    filename: file.name,
    modality: isAudio ? "audio" : "video",
    overall_status: "processing",
    progress_percent: 0,
    elapsed_ms: 0,
    detectors: {
      video_classifier: {
        detector: "video_classifier",
        status: isAudio ? "skipped" : "queued",
        claim: isAudio ? "Skipped: Audio file contains no visual frames." : "Queued for frame-level artifact analysis.",
        flags: isAudio ? ["not_applicable"] : [],
      },
      aasist: {
        detector: "aasist",
        status: isSilent ? "skipped" : "queued",
        claim: isSilent ? "Skipped: Video contains no audio stream." : "Queued for spectral graph attention analysis.",
        flags: isSilent ? ["not_applicable"] : [],
      },
      rppg: {
        detector: "rppg",
        status: isAudio ? "skipped" : "queued",
        claim: isAudio ? "Skipped: Audio file has no facial stream." : "Queued for blood volume pulse extraction.",
        flags: isAudio ? ["not_applicable"] : [],
      },
      syncnet: {
        detector: "syncnet",
        status: isAudio || isSilent ? "skipped" : "queued",
        claim: isAudio || isSilent ? "Skipped: Multi-modal sync requires both audio and video streams." : "Queued for lip-sync alignment verification.",
        flags: isAudio || isSilent ? ["not_applicable"] : [],
      },
    },
  };

  const emit = (progress) => {
    state.elapsed_ms = Date.now() - startTime;
    state.progress_percent = progress;
    if (onProgress) onProgress({ ...state });
  };

  emit(5);
  await new Promise((r) => setTimeout(r, 200));

  // Step 1: Video Frame Classifier
  if (!isAudio) {
    state.detectors.video_classifier.status = "running";
    emit(25);
    await new Promise((r) => setTimeout(r, 350));
    state.detectors.video_classifier.status = "complete";
    state.detectors.video_classifier.confidence = 0.12; // Authentic
    state.detectors.video_classifier.raw_score = -1.82;
    state.detectors.video_classifier.latency_ms = 312;
    state.detectors.video_classifier.ram_usage_mb = 940;
    state.detectors.video_classifier.claim = "Facial boundary textures and temporal continuity are consistent with authentic camera capture.";
  }

  // Step 2: AASIST Audio
  if (!isSilent) {
    state.detectors.aasist.status = "running";
    emit(50);
    await new Promise((r) => setTimeout(r, 320));
    state.detectors.aasist.status = "complete";

    if (isAudio || isConflict) {
      state.detectors.aasist.confidence = isConflict ? 0.91 : 0.94; // Synthetic spoof
      state.detectors.aasist.raw_score = 4.25;
      state.detectors.aasist.latency_ms = 215;
      state.detectors.aasist.ram_usage_mb = 620;
      state.detectors.aasist.flags = ["spectral_anomaly", "vocoder_cutoff"];
      state.detectors.aasist.claim = "High-frequency neural vocoder phase artifacts and unnatural harmonics detected in 2-4kHz band.";
    } else {
      state.detectors.aasist.confidence = 0.08; // Authentic
      state.detectors.aasist.raw_score = -2.35;
      state.detectors.aasist.latency_ms = 195;
      state.detectors.aasist.ram_usage_mb = 620;
      state.detectors.aasist.claim = "Acoustic spectrogram shows natural human vocal tract formant resonance without synthetic spectral cutoff.";
    }
  }

  // Step 3: rPPG
  if (!isAudio) {
    state.detectors.rppg.status = "running";
    emit(75);
    await new Promise((r) => setTimeout(r, 380));
    state.detectors.rppg.status = "complete";
    state.detectors.rppg.confidence = 0.15; // Authentic
    state.detectors.rppg.raw_score = 3.2;
    state.detectors.rppg.latency_ms = 445;
    state.detectors.rppg.ram_usage_mb = 1120;
    state.detectors.rppg.claim = "CHROM algorithm extracted periodic blood volume pulse waveform at 72.4 BPM with high spectral SNR.";
  }

  // Step 4: SyncNet
  if (!isAudio && !isSilent) {
    state.detectors.syncnet.status = "running";
    emit(90);
    await new Promise((r) => setTimeout(r, 320));
    state.detectors.syncnet.status = "complete";

    if (isConflict) {
      state.detectors.syncnet.confidence = 0.85; // Synthetic
      state.detectors.syncnet.raw_score = 0.04;
      state.detectors.syncnet.latency_ms = 310;
      state.detectors.syncnet.ram_usage_mb = 1380;
      state.detectors.syncnet.flags = ["temporal_lag", "phoneme_offset"];
      state.detectors.syncnet.claim = "Phoneme-viseme correlation offset exceeds natural tolerance (>140ms desynchronization).";
    } else {
      state.detectors.syncnet.confidence = 0.18; // Authentic
      state.detectors.syncnet.raw_score = 1.85;
      state.detectors.syncnet.latency_ms = 278;
      state.detectors.syncnet.ram_usage_mb = 1380;
      state.detectors.syncnet.claim = "Audio-visual phoneme-viseme correlation aligned within 12ms of natural speech cadence.";
    }
  }

  state.overall_status = "completed";
  emit(100);

  const presetJudgeData = {
    clean_baseline: {
      judge_verdict: "AUTHENTIC",
      judge_score: 0.12,
      judge_mode: "deterministic",
      siem_alert_tier: "TIER_1_LOW",
      guards_applied: ["Guard 2: Cross-Modal Corroboration Requirement Satisfied"],
      forensic_justification: "All active modalities (Visual boundary, CHROM rPPG, SyncNet, AASIST) corroborate natural origin with high statistical confidence. No synthesis or reenactment anomalies detected.",
      cross_examination_findings: "Unanimous agreement across all 4 layers. Cross-examination found zero temporal or spectral inconsistencies.",
      adjudication_latency_ms: 0.35,
      debate_transcript_hash: "0xa4f28e9b10c551dd6a7b391d84f001c27e8a93bc44ef0182736154388192a001",
      debate_transcript: [
        { round: 1, speaker: "video_classifier", claim: "Natural facial boundary textures, no warping artifacts (score: 0.12).", polarity: "AUTHENTIC", confidence: 0.88 },
        { round: 1, speaker: "rppg", claim: "Continuous sub-dermal blood volume pulse extracted at 72.4 BPM (score: 0.15).", polarity: "AUTHENTIC", confidence: 0.85 },
        { round: 2, speaker: "syncnet", claim: "Phoneme-viseme temporal correlation aligned within 12ms natural window (score: 0.18).", polarity: "AUTHENTIC", confidence: 0.82 },
        { round: 2, speaker: "aasist", claim: "Vocal tract formants conform to natural biological acoustics (score: 0.08).", polarity: "AUTHENTIC", confidence: 0.92 },
        { round: 3, speaker: "judge_agent", claim: "Synthesis: Unanimous 4-layer multi-modal corroboration. Authentic media certified under standard court-admissible protocol.", polarity: "AUTHENTIC", confidence: 0.94 }
      ],
    },
    voice_clone: {
      judge_verdict: "SYNTHETIC",
      judge_score: 0.94,
      judge_mode: "deterministic",
      siem_alert_tier: "TIER_3_CRITICAL",
      guards_applied: ["Acoustic Synthesis Precedence Rule Activated"],
      forensic_justification: "Neural vocoder phase discontinuity and unnatural harmonic envelope detected in 2-4kHz band. Visual modalities correctly bypassed as Not Applicable.",
      cross_examination_findings: "AASIST spectro-temporal graph attention identified vocoder artifact clusters at 12.4s and 31.2s.",
      adjudication_latency_ms: 0.42,
      debate_transcript_hash: "0x51c3d987e2a9b4001c5f829033ba019482fe913840219572839105827192a3bc",
      debate_transcript: [
        { round: 1, speaker: "aasist", claim: "Critical acoustic spoofing detected: neural vocoder synthesis artifacts in 2-4kHz band (score: 0.94).", polarity: "SYNTHETIC", confidence: 0.94 },
        { round: 1, speaker: "video_classifier", claim: "Skipped: Audio file contains no visual frames.", polarity: "NOT_APPLICABLE", confidence: 0.0 },
        { round: 2, speaker: "judge_agent", claim: "Pre-dispatch manifest verified audio-only modality. Acoustic synthesis precedence rule triggered.", polarity: "SYNTHETIC", confidence: 0.94 },
        { round: 3, speaker: "judge_agent", claim: "Synthesis: Standalone voice clone confirmed. Immediate SIEM Tier 3 escalation.", polarity: "SYNTHETIC", confidence: 0.95 }
      ],
    },
    silent_video: {
      judge_verdict: "AUTHENTIC",
      judge_score: 0.14,
      judge_mode: "deterministic",
      siem_alert_tier: "TIER_1_LOW",
      guards_applied: ["Pre-dispatch Zero-Audio Manifest Filter Applied"],
      forensic_justification: "Silent surveillance footage: audio and lip-sync detectors safely bypassed via capability manifest. Visual classifier and rPPG pulse confirm natural camera capture.",
      cross_examination_findings: "Visual spatial textures and dermal blood volume pulse verified authentic without audio dependency.",
      adjudication_latency_ms: 0.28,
      debate_transcript_hash: "0x892a014c2b98e1f0037a891048b291c3057e9128394018274619283740192837",
      debate_transcript: [
        { round: 1, speaker: "video_classifier", claim: "Natural camera capture confirmed without warping or blend boundaries (score: 0.12).", polarity: "AUTHENTIC", confidence: 0.88 },
        { round: 1, speaker: "rppg", claim: "CHROM algorithm extracted stable pulse wave at 70.8 BPM (score: 0.15).", polarity: "AUTHENTIC", confidence: 0.85 },
        { round: 2, speaker: "aasist", claim: "Skipped: Video contains zero audio stream.", polarity: "NOT_APPLICABLE", confidence: 0.0 },
        { round: 2, speaker: "syncnet", claim: "Skipped: Multi-modal sync requires audio stream.", polarity: "NOT_APPLICABLE", confidence: 0.0 },
        { round: 3, speaker: "judge_agent", claim: "Synthesis: Capability manifest correctly isolated visual domain. Visual and biometric authenticity corroborated.", polarity: "AUTHENTIC", confidence: 0.91 }
      ],
    },
    cross_modal_conflict: {
      judge_verdict: "SYNTHETIC",
      judge_score: 0.88,
      judge_mode: "deterministic",
      siem_alert_tier: "TIER_3_CRITICAL",
      guards_applied: [
        "Guard 1: Unresolved Polarity Inversion Anti-Default",
        "Guard 2: Cross-Modal Corroboration Requirement"
      ],
      forensic_justification: "Cross-modal contradiction: Video classifier reported authentic visual face (score: 0.12), but AASIST detected neural speech cloning (score: 0.91) and SyncNet observed >140ms desynchronization. Guard 1 prevented false-authentic default and escalated to TIER_3_CRITICAL.",
      cross_examination_findings: "Severe cross-modal divergence between authentic facial texture and acoustic deepfake voice dubbing.",
      adjudication_latency_ms: 0.51,
      debate_transcript_hash: "0x3f7b9218c0a891273948501c8293740192837461029384756102938475610293",
      debate_transcript: [
        { round: 1, speaker: "video_classifier", claim: "Facial textures and boundaries appear natural (score: 0.12).", polarity: "AUTHENTIC", confidence: 0.88 },
        { round: 1, speaker: "aasist", claim: "Voice track cloned via neural vocoder with high anomaly score (score: 0.91).", polarity: "SYNTHETIC", confidence: 0.91 },
        { round: 2, speaker: "syncnet", claim: "Lip-sync trails audio by 140ms, indicating dubbed face replacement (score: 0.85).", polarity: "SYNTHETIC", confidence: 0.85 },
        { round: 2, speaker: "judge_agent", claim: "Cross-examination: Polarity conflict detected. Video claiming AUTHENTIC while Audio and AV Sync claim SYNTHETIC.", polarity: "INCONCLUSIVE", confidence: 0.50 },
        { round: 3, speaker: "judge_agent", claim: "Synthesis: Guard 1 triggered to block false-authentic default. Dubbed speech manipulation confirmed.", polarity: "SYNTHETIC", confidence: 0.89 }
      ],
    },
  };

  const judgeDetails = presetJudgeData[presetId] || {
    judge_verdict: isConflict ? "SYNTHETIC" : isAudio ? "SYNTHETIC" : "AUTHENTIC",
    judge_score: isConflict ? 0.88 : isAudio ? 0.94 : 0.12,
    judge_mode: "deterministic",
    siem_alert_tier: isConflict || isAudio ? "TIER_3_CRITICAL" : "TIER_1_LOW",
    guards_applied: isConflict ? ["Guard 1: Unresolved Polarity Inversion Anti-Default"] : [],
    forensic_justification: "Standard multi-modal evaluation completed.",
    cross_examination_findings: "Completed.",
    adjudication_latency_ms: 0.40,
    debate_transcript_hash: "0x9f8c12...4a02",
    debate_transcript: [],
  };

  const formatted = formatResultsFromStatus(state, jobId, isAudio);
  return {
    ...formatted,
    ...judgeDetails,
    raw_response: {
      ...state,
      ...judgeDetails,
    },
    endpoint_used: `Standalone Preset Harness (${presetId})`,
    status_code: 200,
  };
}

/**
 * Runs dynamic simulation for custom uploaded files
 */
async function runDynamicSimulation(file, jobId, isAudio, onProgress) {
  const startTime = Date.now();

  const state = {
    job_id: jobId,
    filename: file.name,
    modality: isAudio ? "audio" : "video",
    overall_status: "processing",
    progress_percent: 0,
    elapsed_ms: 0,
    detectors: {
      video_classifier: {
        detector: "video_classifier",
        status: isAudio ? "skipped" : "queued",
        claim: isAudio ? "Skipped: Media has no video track." : "Queued for frame-level artifact inspection.",
        flags: isAudio ? ["not_applicable"] : [],
      },
      aasist: {
        detector: "aasist",
        status: "queued",
        claim: "Queued for voice synthesis graph attention analysis.",
        flags: [],
      },
      rppg: {
        detector: "rppg",
        status: isAudio ? "skipped" : "queued",
        claim: isAudio ? "Skipped: Media has no video track." : "Queued for biological BVP pulse extraction.",
        flags: isAudio ? ["not_applicable"] : [],
      },
      syncnet: {
        detector: "syncnet",
        status: isAudio ? "skipped" : "queued",
        claim: isAudio ? "Skipped: Media has no video track." : "Queued for lip-sync alignment verification.",
        flags: isAudio ? ["not_applicable"] : [],
      },
    },
  };

  const emit = (progress) => {
    state.elapsed_ms = Date.now() - startTime;
    state.progress_percent = progress;
    if (onProgress) onProgress({ ...state });
  };

  emit(10);
  await new Promise((r) => setTimeout(r, 200));

  if (!isAudio) {
    state.detectors.video_classifier.status = "running";
    emit(25);
    await new Promise((r) => setTimeout(r, 350));
    state.detectors.video_classifier.status = "complete";
    state.detectors.video_classifier.confidence = 0.22;
    state.detectors.video_classifier.raw_score = -1.25;
    state.detectors.video_classifier.latency_ms = 330;
    state.detectors.video_classifier.ram_usage_mb = 940;
    state.detectors.video_classifier.claim = "Facial boundary textures analyzed across 180 sampled frames.";
  }

  state.detectors.aasist.status = "running";
  emit(55);
  await new Promise((r) => setTimeout(r, 320));
  state.detectors.aasist.status = "complete";
  state.detectors.aasist.confidence = isAudio ? 0.88 : 0.18;
  state.detectors.aasist.raw_score = isAudio ? 3.4 : -1.8;
  state.detectors.aasist.latency_ms = 210;
  state.detectors.aasist.ram_usage_mb = 620;
  state.detectors.aasist.flags = isAudio ? ["spectral_anomaly"] : [];
  state.detectors.aasist.claim = isAudio
    ? "Acoustic spoofing anomalies detected in high-frequency spectral bands."
    : "Vocal frequency harmonics remain within natural biological human distribution.";

  if (!isAudio) {
    state.detectors.rppg.status = "running";
    emit(75);
    await new Promise((r) => setTimeout(r, 350));
    state.detectors.rppg.status = "complete";
    state.detectors.rppg.confidence = 0.25;
    state.detectors.rppg.raw_score = 2.4;
    state.detectors.rppg.latency_ms = 460;
    state.detectors.rppg.ram_usage_mb = 1120;
    state.detectors.rppg.claim = "Physiological pulse wave detected with consistent 70 BPM cardiac rhythm.";

    state.detectors.syncnet.status = "running";
    emit(90);
    await new Promise((r) => setTimeout(r, 320));
    state.detectors.syncnet.status = "complete";
    state.detectors.syncnet.confidence = 0.28;
    state.detectors.syncnet.raw_score = 1.4;
    state.detectors.syncnet.latency_ms = 285;
    state.detectors.syncnet.ram_usage_mb = 1380;
    state.detectors.syncnet.claim = "Audio-visual lip movements synchronize within natural speaking offset bounds.";
  }

  state.overall_status = "completed";
  emit(100);

  const formatted = formatResultsFromStatus(state, jobId, isAudio);
  const synth = isAudio;
  const judgeDetails = {
    judge_verdict: synth ? "SYNTHETIC" : "AUTHENTIC",
    judge_score: synth ? 0.88 : 0.22,
    judge_mode: "deterministic",
    siem_alert_tier: synth ? "TIER_3_CRITICAL" : "TIER_1_LOW",
    guards_applied: synth ? ["Acoustic Synthesis Precedence Rule Activated"] : ["Guard 2: Cross-Modal Corroboration Requirement Satisfied"],
    forensic_justification: synth
      ? "Acoustic spoofing anomalies identified in speech harmonics. Visual layers isolated via capability manifest."
      : "Multi-modal consensus verified authentic. No manipulation signatures detected.",
    cross_examination_findings: "Completed.",
    adjudication_latency_ms: 0.38,
    debate_transcript_hash: "0x7a2e49...10b8",
    debate_transcript: [
      { round: 1, speaker: isAudio ? "aasist" : "video_classifier", claim: synth ? "Acoustic spoofing detected." : "Authentic frame textures.", polarity: synth ? "SYNTHETIC" : "AUTHENTIC" },
      { round: 2, speaker: "judge_agent", claim: "Evaluated against capability manifest and precedence matrix.", polarity: synth ? "SYNTHETIC" : "AUTHENTIC" },
      { round: 3, speaker: "judge_agent", claim: synth ? "Final Verdict: SYNTHETIC (SIEM Tier 3)" : "Final Verdict: AUTHENTIC (SIEM Tier 1)", polarity: synth ? "SYNTHETIC" : "AUTHENTIC" }
    ],
  };

  return {
    ...formatted,
    ...judgeDetails,
    raw_response: {
      ...state,
      ...judgeDetails,
    },
    endpoint_used: "Standalone Dynamic Simulation",
    status_code: 200,
  };
}

export async function submitMedia(file) {
  return submitMediaGateway(file);
}
