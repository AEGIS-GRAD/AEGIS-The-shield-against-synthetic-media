import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { analyses as mockAnalyses, reportJson as mockReport } from "@/lib/mock";

const JOBS_DIR = path.join(process.cwd(), ".jobs");
const JOBS_FILE = path.join(JOBS_DIR, "jobs.json");

function ensureJobsFile() {
  if (!fs.existsSync(JOBS_DIR)) {
    fs.mkdirSync(JOBS_DIR, { recursive: true });
  }
  if (!fs.existsSync(JOBS_FILE)) {
    fs.writeFileSync(JOBS_FILE, JSON.stringify([], null, 2), "utf-8");
  }
}

function readJobs() {
  try {
    ensureJobsFile();
    const data = fs.readFileSync(JOBS_FILE, "utf-8");
    return JSON.parse(data);
  } catch (err) {
    console.error("Error reading jobs:", err);
    return [];
  }
}

function writeJobs(jobs: any[]) {
  try {
    ensureJobsFile();
    fs.writeFileSync(JOBS_FILE, JSON.stringify(jobs, null, 2), "utf-8");
  } catch (err) {
    console.error("Error writing jobs:", err);
  }
}

const presetReports: Record<string, any> = {
  clean_baseline: {
    id: "clean_baseline",
    file: "clean_interview_broadcast.mp4",
    verdict: "authentic",
    confidence: 0.94,
    siem_alert_tier: "TIER_1_LOW",
    judge_verdict: "AUTHENTIC",
    judge_score: 0.12,
    guards_applied: ["Guard 2: Cross-Modal Corroboration Requirement Satisfied"],
    forensic_justification: "All active modalities (Visual boundary, CHROM rPPG, SyncNet, AASIST) corroborate natural origin with high statistical confidence. No synthesis or reenactment anomalies detected.",
    cross_examination_findings: "Unanimous agreement across all 4 layers. Cross-examination found zero temporal or spectral inconsistencies.",
    debate_transcript_hash: "0xa4f28e9b10c551dd6a7b391d84f001c27e8a93bc44ef0182736154388192a001",
    debate_transcript: [
      { round: 1, speaker: "video_classifier", claim: "Natural facial boundary textures, no warping artifacts (score: 0.12).", polarity: "AUTHENTIC", confidence: 0.88 },
      { round: 1, speaker: "rppg", claim: "Continuous sub-dermal blood volume pulse extracted at 72.4 BPM (score: 0.15).", polarity: "AUTHENTIC", confidence: 0.85 },
      { round: 2, speaker: "syncnet", claim: "Phoneme-viseme temporal correlation aligned within 12ms natural window (score: 0.18).", polarity: "AUTHENTIC", confidence: 0.82 },
      { round: 2, speaker: "aasist", claim: "Vocal tract formants conform to natural biological acoustics (score: 0.08).", polarity: "AUTHENTIC", confidence: 0.92 },
      { round: 3, speaker: "judge_agent", claim: "Synthesis: Unanimous 4-layer multi-modal corroboration. Authentic media certified under standard court-admissible protocol.", polarity: "AUTHENTIC", confidence: 0.94 }
    ],
    is_demo: true,
    results: {
      video: { p_synthetic: 0.12, confidence: 0.88, frames_scored: 24, model: "EfficientNet-B0" },
      rppg: { p_synthetic: 0.15, confidence: 0.85, hr_bpm: 72, quality: 0.88 },
      syncnet: { p_synthetic: 0.18, confidence: 0.82, offset: 0 },
      aasist: { p_synthetic: 0.08, confidence: 0.92 },
    },
    frame_scores: Array(32).fill(0.12),
  },
  voice_clone: {
    id: "voice_clone",
    file: "synthetic_voice_clone_scam.wav",
    verdict: "synthetic",
    confidence: 0.95,
    siem_alert_tier: "TIER_3_CRITICAL",
    judge_verdict: "SYNTHETIC",
    judge_score: 0.94,
    guards_applied: ["Acoustic Synthesis Precedence Rule Activated"],
    forensic_justification: "Neural vocoder phase discontinuity and unnatural harmonic envelope detected in 2-4kHz band. Visual modalities correctly bypassed as Not Applicable.",
    cross_examination_findings: "AASIST spectro-temporal graph attention identified vocoder artifact clusters at 12.4s and 31.2s.",
    debate_transcript_hash: "0x51c3d987e2a9b4001c5f829033ba019482fe913840219572839105827192a3bc",
    debate_transcript: [
      { round: 1, speaker: "aasist", claim: "Critical acoustic spoofing detected: neural vocoder synthesis artifacts in 2-4kHz band (score: 0.94).", polarity: "SYNTHETIC", confidence: 0.94 },
      { round: 1, speaker: "video_classifier", claim: "Skipped: Audio file contains no visual frames.", polarity: "NOT_APPLICABLE", confidence: 0.0 },
      { round: 2, speaker: "judge_agent", claim: "Pre-dispatch manifest verified audio-only modality. Acoustic synthesis precedence rule triggered.", polarity: "SYNTHETIC", confidence: 0.94 },
      { round: 3, speaker: "judge_agent", claim: "Synthesis: Standalone voice clone confirmed. Immediate SIEM Tier 3 escalation.", polarity: "SYNTHETIC", confidence: 0.95 }
    ],
    is_demo: true,
    results: {
      aasist: { p_synthetic: 0.94, confidence: 0.94 },
    },
    frame_scores: [],
  },
  silent_video: {
    id: "silent_video",
    file: "surveillance_silent_clip.mp4",
    verdict: "authentic",
    confidence: 0.91,
    siem_alert_tier: "TIER_1_LOW",
    judge_verdict: "AUTHENTIC",
    judge_score: 0.14,
    guards_applied: ["Pre-dispatch Zero-Audio Manifest Filter Applied"],
    forensic_justification: "Silent surveillance footage: audio and lip-sync detectors safely bypassed via capability manifest. Visual classifier and rPPG pulse confirm natural camera capture.",
    cross_examination_findings: "Visual spatial textures and dermal blood volume pulse verified authentic without audio dependency.",
    debate_transcript_hash: "0x892a014c2b98e1f0037a891048b291c3057e9128394018274619283740192837",
    debate_transcript: [
      { round: 1, speaker: "video_classifier", claim: "Natural camera capture confirmed without warping or blend boundaries (score: 0.12).", polarity: "AUTHENTIC", confidence: 0.88 },
      { round: 1, speaker: "rppg", claim: "CHROM algorithm extracted stable pulse wave at 70.8 BPM (score: 0.15).", polarity: "AUTHENTIC", confidence: 0.85 },
      { round: 2, speaker: "aasist", claim: "Skipped: Video contains zero audio stream.", polarity: "NOT_APPLICABLE", confidence: 0.0 },
      { round: 2, speaker: "syncnet", claim: "Skipped: Multi-modal sync requires audio stream.", polarity: "NOT_APPLICABLE", confidence: 0.0 },
      { round: 3, speaker: "judge_agent", claim: "Synthesis: Capability manifest correctly isolated visual domain. Visual and biometric authenticity corroborated.", polarity: "AUTHENTIC", confidence: 0.91 }
    ],
    is_demo: true,
    results: {
      video: { p_synthetic: 0.12, confidence: 0.88, frames_scored: 30, model: "MobileNetV3" },
      rppg: { p_synthetic: 0.15, confidence: 0.85, hr_bpm: 70, quality: 0.82 },
    },
    frame_scores: Array(32).fill(0.14),
  },
  cross_modal_conflict: {
    id: "cross_modal_conflict",
    file: "dubbed_speech_conflict.mp4",
    verdict: "synthetic",
    confidence: 0.89,
    siem_alert_tier: "TIER_3_CRITICAL",
    judge_verdict: "SYNTHETIC",
    judge_score: 0.88,
    guards_applied: [
      "Guard 1: Unresolved Polarity Inversion Anti-Default",
      "Guard 2: Cross-Modal Corroboration Requirement",
    ],
    forensic_justification: "Cross-modal contradiction: Video classifier reported authentic visual face (score: 0.12), but AASIST detected neural speech cloning (score: 0.91) and SyncNet observed >140ms desynchronization. Guard 1 prevented false-authentic default and escalated to TIER_3_CRITICAL.",
    cross_examination_findings: "Severe cross-modal divergence between authentic facial texture and acoustic deepfake voice dubbing.",
    debate_transcript_hash: "0x3f7b9218c0a891273948501c8293740192837461029384756102938475610293",
    debate_transcript: [
      { round: 1, speaker: "video_classifier", claim: "Natural camera textures and authentic facial boundaries detected (score: 0.12).", polarity: "AUTHENTIC", confidence: 0.88 },
      { round: 1, speaker: "aasist", claim: "Neural vocoder phase discontinuity and speech synthesis artifacts flagged (score: 0.91).", polarity: "SYNTHETIC", confidence: 0.91 },
      { round: 2, speaker: "syncnet", claim: "Lip motion lag detected >140ms desynchronized from acoustic waveform (score: 0.85).", polarity: "SYNTHETIC", confidence: 0.85 },
      { round: 2, speaker: "rppg", claim: "Weak periodic pulse detected (~68 BPM) but facial audio out of sync.", polarity: "AUTHENTIC", confidence: 0.80 },
      { round: 3, speaker: "judge_agent", claim: "Synthesis: Cross-modal polarity inversion detected between genuine face and synthesized speech. Guard 1 executed, preventing false authentic default.", polarity: "SYNTHETIC", confidence: 0.89 }
    ],
    is_demo: true,
    results: {
      video: { p_synthetic: 0.12, confidence: 0.88, frames_scored: 24 },
      rppg: { p_synthetic: 0.18, confidence: 0.80, hr_bpm: 68 },
      syncnet: { p_synthetic: 0.85, confidence: 0.85, offset: 4 },
      aasist: { p_synthetic: 0.91, confidence: 0.91 },
    },
    frame_scores: Array(32).fill(0.48),
  },
};

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const id = searchParams.get("id");
  const realJobs = readJobs();

  if (id) {
    // Check preset reports first
    if (presetReports[id]) {
      return NextResponse.json(presetReports[id]);
    }

    // Check real jobs
    const found = realJobs.find((j: any) => j.id === id || j.job_id === id);
    if (found) {
      return NextResponse.json(found);
    }
    // Fallback to mock demo report if AEG-1042 or matching demo ID
    if (id === "AEG-1042" || mockAnalyses.some((a) => a.id === id)) {
      return NextResponse.json({
        ...mockReport,
        job_id: id,
        is_demo: true,
      });
    }
    return NextResponse.json({ error: "Job not found" }, { status: 404 });
  }

  // Return real jobs merged with mock demo analyses labeled with is_demo: true
  const labeledDemos = mockAnalyses.map((a) => ({
    ...a,
    is_demo: true,
  }));

  const all = [...realJobs, ...labeledDemos];
  return NextResponse.json(all);
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const realJobs = readJobs();

    const newJob = {
      id: body.id || `AEG-${Date.now().toString().slice(-4)}`,
      file: body.file || "uploaded_media.mp4",
      modality: body.modality || "video",
      verdict: body.verdict || "synthetic",
      confidence: body.confidence || 0.85,
      siem_alert_tier: body.siem_alert_tier || (body.verdict === "synthetic" ? "TIER_3_CRITICAL" : "TIER_1_LOW"),
      judge_verdict: body.judge_verdict || (body.verdict ? body.verdict.toUpperCase() : "SYNTHETIC"),
      judge_score: body.judge_score ?? body.confidence ?? 0.85,
      guards_applied: body.guards_applied || [],
      forensic_justification: body.forensic_justification || "",
      cross_examination_findings: body.cross_examination_findings || "",
      debate_transcript: body.debate_transcript || [],
      debate_transcript_hash: body.debate_transcript_hash || null,
      time: new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }),
      status: "Complete",
      is_demo: false,
      timestamp: new Date().toISOString(),
      raw_result: body,
      results: body.results || null,
      frame_scores: body.frame_scores || null,
    };

    realJobs.unshift(newJob);
    writeJobs(realJobs);

    return NextResponse.json(newJob, { status: 201 });
  } catch (err: any) {
    return NextResponse.json({ error: err.message || "Invalid payload" }, { status: 400 });
  }
}
