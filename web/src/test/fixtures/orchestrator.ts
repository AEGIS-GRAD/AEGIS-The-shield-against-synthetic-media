export interface DebateTranscriptEntry {
  round: number;
  speaker: string;
  polarity: "SYNTHETIC" | "AUTHENTIC" | "INCONCLUSIVE" | "NOT_APPLICABLE" | "ADJUDICATED" | string;
  confidence: number;
  claim: string;
}

export interface DetectorResultPayload {
  detector?: string;
  job_id: string;
  status: "ok" | "not_applicable" | "error";
  modality: "video" | "audio" | "text" | "image";
  confidence: number;
  raw_score: number;
  latency_ms: number;
  ram_usage_mb: number;
  vram_usage_mb: number;
  model_version: string;
  evidence: {
    claim: string;
    flags: string[];
  };
  signals?: Record<string, any>;
}

export interface RealJobRecord {
  id: string;
  file: string;
  verdict: "synthetic" | "authentic" | "inconclusive";
  confidence: number;
  time: string;
  status: "Complete" | "Running" | "Failed";
  is_demo: boolean;
  thumbnail_url?: string;
  frame_scores?: number[];
  siem_alert_tier: string;
  judge_verdict: string;
  judge_score: number;
  guards_applied: string[];
  forensic_justification: string;
  cross_examination_findings: string | string[];
  debate_transcript_hash: string;
  debate_transcript: DebateTranscriptEntry[];
  results: {
    video?: {
      p_synthetic: number;
      confidence: number;
      frames_scored: number;
      model: string;
      max_p?: number;
    };
    rppg?: {
      p_synthetic: number;
      quality: number;
      hr_bpm: number;
      signal?: number[];
    };
    syncnet?: {
      p_synthetic: number;
      offset_frames?: number;
    };
    aasist?: {
      p_synthetic: number;
    };
  };
}

export const REAL_SYNTHETIC_JOB: RealJobRecord = {
  id: "AEG-LIVE-9001",
  file: "interview_clip_real.mp4",
  verdict: "synthetic",
  confidence: 0.91,
  time: "14:22",
  status: "Complete",
  is_demo: false,
  thumbnail_url: "/subject.jpg",
  frame_scores: [0.12, 0.45, 0.89, 0.94, 0.77, 0.35],
  siem_alert_tier: "TIER_3_CRITICAL",
  judge_verdict: "SYNTHETIC",
  judge_score: 0.91,
  guards_applied: [
    "Guard 1: Unresolved Polarity Inversion Anti-Default",
    "Guard 2: Cross-Modal Corroboration Requirement Satisfied",
  ],
  forensic_justification:
    "Spatial artifact score and audio-visual desync corroborate synthetic manipulation despite noisy rPPG low-light attenuation.",
  cross_examination_findings: [
    "Video classifier detected 83% jawline blending artifacts (p=0.93).",
    "SyncNet confirmed +4 frame lip-sync drift consistent with face reenactment.",
    "rPPG attenuated due to marginal illumination (quality 0.38).",
  ],
  debate_transcript_hash: "0xabc123def4567890fedcba0987654321abc123def4567890fedcba0987654321",
  debate_transcript: [
    {
      round: 1,
      speaker: "video_classifier",
      polarity: "SYNTHETIC",
      confidence: 0.93,
      claim: "Spatial blending artifacts observed across forehead and jawline keyframes.",
    },
    {
      round: 1,
      speaker: "rppg",
      polarity: "AUTHENTIC",
      confidence: 0.38,
      claim: "Periodic pulse harmonic near 64 BPM detected under low illumination.",
    },
    {
      round: 2,
      speaker: "syncnet",
      polarity: "SYNTHETIC",
      confidence: 0.84,
      claim: "Lip motion lags acoustic envelope by +4 frames across voiced phonemes.",
    },
    {
      round: 3,
      speaker: "judge_agent",
      polarity: "SYNTHETIC",
      confidence: 0.91,
      claim: "Rule 3 precedence overrides attenuated rPPG signal; verdict SYNTHETIC.",
    },
  ],
  results: {
    video: {
      p_synthetic: 0.93,
      confidence: 0.92,
      frames_scored: 32,
      model: "EfficientNet-B0",
      max_p: 0.99,
    },
    rppg: {
      p_synthetic: 0.32,
      quality: 0.38,
      hr_bpm: 64,
    },
    syncnet: {
      p_synthetic: 0.88,
      offset_frames: 4,
    },
    aasist: {
      p_synthetic: 0.82,
    },
  },
};

export const REAL_AUTHENTIC_JOB: RealJobRecord = {
  id: "AEG-LIVE-9002",
  file: "studio_camera_feed.mp4",
  verdict: "authentic",
  confidence: 0.14,
  time: "14:35",
  status: "Complete",
  is_demo: false,
  siem_alert_tier: "TIER_1_LOW",
  judge_verdict: "AUTHENTIC",
  judge_score: 0.14,
  guards_applied: ["Guard 2: Cross-Modal Corroboration Requirement Satisfied"],
  forensic_justification:
    "All four active detectors align on natural human sensor physics and authentic acoustic-visual temporal coherence.",
  cross_examination_findings: "Zero cross-modal contradictions raised across R1-R3.",
  debate_transcript_hash: "0x111122223333444455556666777788889999aaaabbbbccccddddeeeeffff0000",
  debate_transcript: [
    {
      round: 1,
      speaker: "video_classifier",
      polarity: "AUTHENTIC",
      confidence: 0.91,
      claim: "Natural pore distribution and stable inter-frame residuals.",
    },
    {
      round: 3,
      speaker: "judge_agent",
      polarity: "AUTHENTIC",
      confidence: 0.86,
      claim: "Multi-modal consensus authentic.",
    },
  ],
  results: {
    video: { p_synthetic: 0.11, confidence: 0.91, frames_scored: 24, model: "EfficientNet-B0", max_p: 0.21 },
    rppg: { p_synthetic: 0.15, quality: 0.88, hr_bpm: 72 },
    syncnet: { p_synthetic: 0.14, offset_frames: 0 },
    aasist: { p_synthetic: 0.12 },
  },
};

export const ORCHESTRATION_SUCCESS_RESPONSE = {
  job_id: "orch-job-101",
  status: "completed",
  verdict: "synthetic",
  confidence: 0.89,
  metadata: {
    modality: "video",
  },
  raw_results: [
    {
      detector: "video_classifier",
      job_id: "orch-job-101",
      status: "ok",
      modality: "video",
      confidence: 0.93,
      raw_score: 0.93,
      latency_ms: 1420,
      ram_usage_mb: 610,
      vram_usage_mb: 1200,
      model_version: "efficientnet-b0-ffpp-c23",
      evidence: {
        claim: "Spatial deepfake artifacts detected in facial crops.",
        flags: ["jaw_blending", "high_confidence"],
      },
    } satisfies DetectorResultPayload,
    {
      detector: "rppg",
      job_id: "orch-job-101",
      status: "ok",
      modality: "video",
      confidence: 0.28,
      raw_score: 0.28,
      latency_ms: 810,
      ram_usage_mb: 420,
      vram_usage_mb: 0,
      model_version: "rppg-chrom-v1",
      evidence: {
        claim: "Weak periodic pulse near 72 BPM under compression.",
        flags: ["low_light"],
      },
    } satisfies DetectorResultPayload,
    {
      detector: "aasist",
      job_id: "orch-job-101",
      status: "not_applicable",
      modality: "audio",
      confidence: 0.5,
      raw_score: 0.0,
      latency_ms: 8,
      ram_usage_mb: 256,
      vram_usage_mb: 0,
      model_version: "aasist-l-v1",
      evidence: {
        claim: "No audio stream present in media container.",
        flags: ["no_audio_track", "not_applicable"],
      },
    } satisfies DetectorResultPayload,
    {
      detector: "syncnet",
      job_id: "orch-job-101",
      status: "ok",
      modality: "video",
      confidence: 0.84,
      raw_score: 0.84,
      latency_ms: 690,
      ram_usage_mb: 390,
      vram_usage_mb: 500,
      model_version: "syncnet-v2",
      evidence: {
        claim: "Audio-visual alignment desync of +4 frames.",
        flags: ["av_offset"],
      },
    } satisfies DetectorResultPayload,
  ],
  judge_verdict: "SYNTHETIC",
  judge_score: 0.91,
  judge_mode: "deterministic_debate",
  siem_alert_tier: "TIER_3_CRITICAL",
  forensic_justification: REAL_SYNTHETIC_JOB.forensic_justification,
  cross_examination_findings: REAL_SYNTHETIC_JOB.cross_examination_findings,
  debate_transcript: REAL_SYNTHETIC_JOB.debate_transcript,
  guards_applied: REAL_SYNTHETIC_JOB.guards_applied,
  debate_transcript_hash: REAL_SYNTHETIC_JOB.debate_transcript_hash,
};
