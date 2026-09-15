/**
 * Submits a media file (video or audio) for deepfake detection analysis.
 * Currently an isolated mock implementation simulating network latency and
 * returning responses for all four AEGIS detectors, each matching the
 * strict shared/json-api-contracts-schema/detector_response.schema.json
 * contract.
 *
 * A detector that cannot run on the given media (e.g. SyncNet on a video
 * with no audio track) still returns a fully schema-valid response, with
 * evidence.flags containing "not_applicable" and evidence.claim explaining
 * why. This keeps the mock honest about how the real orchestrator will
 * behave, since the schema has no dedicated "status" field.
 *
 * Swap this mock implementation with a real fetch() call to the AEGIS
 * orchestrator/gateway endpoint when backend integration is ready.
 *
 * @param {File} file - User selected media file (Video or Audio)
 * @returns {Promise<{
 *   video_classifier: DetectorResponse,
 *   rppg: DetectorResponse,
 *   aasist: DetectorResponse,
 *   syncnet: DetectorResponse,
 * }>}
 */

const MOCK_NETWORK_DELAY_MS = 1500;

function makeJobId() {
  return crypto.randomUUID
    ? crypto.randomUUID()
    : `mock-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function notApplicableResponse(jobId, modelVersion, reason) {
  return {
    job_id: jobId,
    confidence: 0.5, // neutral — the real signal is evidence.flags, not this number
    raw_score: 0,
    latency_ms: 0,
    model_version: modelVersion,
    evidence: {
      claim: reason,
      flags: ["not_applicable"],
    },
  };
}

function completedResponse(jobId, modelVersion, { confidence, rawScore, latencyMs, claim, flags = [] }) {
  return {
    job_id: jobId,
    confidence,
    raw_score: rawScore,
    latency_ms: latencyMs,
    ram_usage_mb: Math.round(800 + Math.random() * 1200),
    model_version: modelVersion,
    evidence: { claim, flags },
  };
}

export async function submitMedia(file) {
  if (!file) {
    throw new Error("No media file provided for submission.");
  }

  const isAudio = file.type.startsWith("audio/");
  const jobId = makeJobId();

  // Mock-only: simulate whether the uploaded video actually has an audio
  // track. In the real system this comes from the orchestrator's media
  // probing step before dispatch, not from the frontend.
  const videoHasAudioTrack = isAudio ? true : Math.random() > 0.3;

  await new Promise((resolve) => setTimeout(resolve, MOCK_NETWORK_DELAY_MS));

  // ---- AASIST (audio spoof detection) ----
  const aasist = (isAudio || videoHasAudioTrack)
    ? completedResponse(jobId, "aasist-v2", {
        confidence: 0.58,
        rawScore: 0.31,
        latencyMs: 210,
        claim: "Spectral artifacts consistent with voice cloning detected in the 2-4kHz band.",
        flags: ["spectral_anomaly"],
      })
    : notApplicableResponse(jobId, "aasist-v2", "No audio track present in submitted file — audio spoof analysis skipped.");

  // ---- Video Classifier (visual frame analysis) — video only ----
  const video_classifier = !isAudio
    ? completedResponse(jobId, "xception-ffpp", {
        confidence: 0.42,
        rawScore: -0.18,
        latencyMs: 340,
        claim: "Frame-level analysis shows minor compression inconsistencies but no strong synthesis markers.",
        flags: [],
      })
    : notApplicableResponse(jobId, "xception-ffpp", "Submitted file has no video stream — frame analysis skipped.");

  // ---- rPPG (heartbeat consistency) — video only ----
  const rppg = !isAudio
    ? completedResponse(jobId, "rppg-resnet-v2", {
        confidence: 0.35,
        rawScore: 2.1,
        latencyMs: 480,
        claim: "rPPG signal present and physiologically plausible across visible facial region.",
        flags: [],
      })
    : notApplicableResponse(jobId, "rppg-resnet-v2", "No visible face region in submitted file — heartbeat analysis skipped.");

  // ---- SyncNet (lip-sync consistency) — needs both video and audio ----
  const syncnet = (!isAudio && videoHasAudioTrack)
    ? completedResponse(jobId, "syncnet-v1.3", {
        confidence: 0.61,
        rawScore: 0.9,
        latencyMs: 275,
        claim: "Mild lip-audio offset detected, slightly above natural variation range.",
        flags: ["sync_offset_detected"],
      })
    : notApplicableResponse(
        jobId,
        "syncnet-v1.3",
        isAudio
          ? "Submitted file has no video stream — lip-sync analysis skipped."
          : "No audio track detected in submitted file — lip-sync analysis skipped."
      );

  return { video_classifier, rppg, aasist, syncnet };
}
