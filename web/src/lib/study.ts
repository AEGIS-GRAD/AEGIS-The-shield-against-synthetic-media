/**
 * RQ3 trust & usability study — scenarios, questionnaire wording, counterbalancing, export.
 *
 * Source of truth for all participant-facing wording. The printable copies in
 * docs/rq3_study/ mirror this file; src/lib/__tests__/study.test.ts fails if they drift.
 *
 * Every scenario is FICTIONAL (invented files, people and numbers). No real person or
 * real incident appears anywhere in the kit.
 */

export type Condition = "evidence" | "baseline";
export type Category = "agreement" | "conflict" | "limits";
export type Decision = "authentic" | "manipulated" | "undecided";

export interface StudyDetector {
  id: "video" | "rppg" | "syncnet" | "aasist";
  name: string;
  /** P(synthetic) in [0,1]; null = the detector did not run / abstained. */
  p: number | null;
  quality?: number;
  claim: string;
  flags: string[];
}

export interface StudyDebateTurn {
  who: string;
  text: string;
  conflict?: boolean;
}

export interface StudyChainEvent {
  time: string;
  text: string;
  status: "ok" | "warn" | "broken";
}

export interface StudyScenario {
  id: string;
  title: string;
  category: Category;
  /** Short story shown to the participant. */
  context: string;
  file: string;
  durationS: number;
  /** What a careful analyst should conclude. Used only for the export, never shown. */
  expected: Decision;
  detectors: StudyDetector[];
  debate: StudyDebateTurn[];
  judge: { verdict: "synthetic" | "authentic" | "inconclusive" | "integrity_unknown"; tier: string; justification: string };
  chain: { fileHash: string; intact: boolean; events: StudyChainEvent[] };
}

const H = (seed: string) => (seed.repeat(8)).slice(0, 64);

export const SCENARIOS: StudyScenario[] = [
  {
    id: "S1",
    title: "Spokesperson briefing",
    category: "agreement",
    context: "A video of a company spokesperson is spreading online. Your editor asks whether it is safe to publish as genuine.",
    file: "spokesperson_briefing.mp4",
    durationS: 48,
    expected: "manipulated",
    detectors: [
      { id: "video", name: "Video Classifier", p: 0.94, quality: 0.9, claim: "Blending artifacts around the jawline in 81% of sampled frames.", flags: ["Jaw blending", "Texture smoothing"] },
      { id: "rppg", name: "Pulse (rPPG)", p: 0.71, quality: 0.72, claim: "A pulse signal was found, but it is irregular.", flags: ["Irregular rhythm"] },
      { id: "syncnet", name: "Lip-sync (SyncNet)", p: 0.88, quality: 0.85, claim: "Lips trail the audio by 4 frames (about 160 ms).", flags: ["Offset +4 frames"] },
      { id: "aasist", name: "Voice (AASIST)", p: 0.83, quality: 0.8, claim: "Voice-synthesis artifacts in two speech segments.", flags: ["12.4–15.0 s", "31.2–33.9 s"] },
    ],
    debate: [
      { who: "Video Classifier", text: "Synthetic. Face edges blend in most frames." },
      { who: "Lip-sync", text: "I agree. A 4-frame lag is typical of a swapped face." },
      { who: "Voice", text: "I agree. The voice also looks cloned in two segments." },
      { who: "Pulse", text: "My signal is weak but also irregular, so it does not contradict the others." },
    ],
    judge: { verdict: "synthetic", tier: "TIER_3_CRITICAL", justification: "All four independent checks point the same way: face, lip timing, voice and pulse." },
    chain: {
      fileHash: H("9f2c4e81b7a0d3f6"),
      intact: true,
      events: [
        { time: "09:38:02", text: "File received and SHA-256 recorded", status: "ok" },
        { time: "09:38:09", text: "Detectors run on the verified copy", status: "ok" },
        { time: "09:38:31", text: "Debate transcript sealed and signed", status: "ok" },
      ],
    },
  },
  {
    id: "S2",
    title: "Dashcam footage",
    category: "agreement",
    context: "An insurance team received dashcam footage of an accident. They ask whether it has been tampered with.",
    file: "dashcam_clip_22.mp4",
    durationS: 31,
    expected: "authentic",
    detectors: [
      { id: "video", name: "Video Classifier", p: 0.05, quality: 0.93, claim: "No blending or texture artifacts found in 930 sampled frames.", flags: [] },
      { id: "rppg", name: "Pulse (rPPG)", p: 0.18, quality: 0.81, claim: "No face is visible for most of the clip; the few frames with a driver show a steady pulse.", flags: ["Few face frames"] },
      { id: "syncnet", name: "Lip-sync (SyncNet)", p: 0.09, quality: 0.7, claim: "Where speech is visible, lips and audio are in step.", flags: [] },
      { id: "aasist", name: "Voice (AASIST)", p: null, quality: undefined, claim: "Not run: the file has no audio track.", flags: ["No audio"] },
    ],
    debate: [
      { who: "Video Classifier", text: "Authentic. Nothing unusual across the clip." },
      { who: "Lip-sync", text: "Agree. Little speech, but what there is is in step." },
      { who: "Pulse", text: "Agree. Limited face time, no red flags." },
    ],
    judge: { verdict: "authentic", tier: "TIER_1_LOW", justification: "Three checks found nothing unusual; the audio check did not apply because there is no sound." },
    chain: {
      fileHash: H("1a7be03c55d2e9f4"),
      intact: true,
      events: [
        { time: "07:20:11", text: "File received and SHA-256 recorded", status: "ok" },
        { time: "07:20:15", text: "Detectors run on the verified copy", status: "ok" },
        { time: "07:20:29", text: "Debate transcript sealed and signed", status: "ok" },
      ],
    },
  },
  {
    id: "S3",
    title: "Interview with an official",
    category: "conflict",
    context: "A news desk got a video interview with a regional official saying something controversial. They want to know if it is real.",
    file: "official_interview.mov",
    durationS: 62,
    expected: "manipulated",
    detectors: [
      { id: "video", name: "Video Classifier", p: 0.91, quality: 0.88, claim: "Strong face-region blending in 77% of frames.", flags: ["Face blending"] },
      { id: "rppg", name: "Pulse (rPPG)", p: 0.38, quality: 0.55, claim: "A pulse was found with moderate quality.", flags: ["Moderate quality"] },
      { id: "syncnet", name: "Lip-sync (SyncNet)", p: 0.84, quality: 0.8, claim: "Lips trail the audio by 5 frames.", flags: ["Offset +5 frames"] },
      { id: "aasist", name: "Voice (AASIST)", p: 0.12, quality: 0.86, claim: "The voice has natural texture; no voice-synthesis artifacts found.", flags: [] },
    ],
    debate: [
      { who: "Video Classifier", text: "Synthetic. The face looks pasted onto the head." },
      { who: "Voice", text: "I disagree. The voice is genuine.", conflict: true },
      { who: "Lip-sync", text: "A real voice with a swapped face would produce exactly this lag. I side with the video check." },
      { who: "Voice", text: "That is consistent. My check only covers the voice, not the face." },
    ],
    judge: { verdict: "synthetic", tier: "TIER_2_ELEVATED", justification: "The voice looks real, but the face and lip timing show manipulation. The most likely explanation is a real voice track under a swapped face." },
    chain: {
      fileHash: H("c04d77aa19b3e8f2"),
      intact: true,
      events: [
        { time: "10:02:44", text: "File received and SHA-256 recorded", status: "ok" },
        { time: "10:02:51", text: "Detectors run on the verified copy", status: "ok" },
        { time: "10:03:20", text: "Debate transcript sealed and signed", status: "ok" },
      ],
    },
  },
  {
    id: "S4",
    title: "Executive video call",
    category: "conflict",
    context: "Finance received a recorded video call in which a senior executive appears to approve an urgent payment. Security wants to know if the call is genuine.",
    file: "exec_call_recording.mp4",
    durationS: 74,
    expected: "manipulated",
    detectors: [
      { id: "video", name: "Video Classifier", p: 0.14, quality: 0.9, claim: "No blending or texture artifacts found.", flags: [] },
      { id: "rppg", name: "Pulse (rPPG)", p: 0.12, quality: 0.78, claim: "A steady pulse of about 72 BPM was found.", flags: ["Steady pulse"] },
      { id: "syncnet", name: "Lip-sync (SyncNet)", p: 0.46, quality: 0.62, claim: "Lips trail the audio by 2 frames; this is borderline.", flags: ["Offset +2 frames"] },
      { id: "aasist", name: "Voice (AASIST)", p: 0.92, quality: 0.84, claim: "Strong voice-synthesis artifacts across most of the speech.", flags: ["Vocoder artifacts", "Most of clip"] },
    ],
    debate: [
      { who: "Voice", text: "Synthetic. The voice shows clear synthesis artifacts throughout." },
      { who: "Video Classifier", text: "I disagree. The picture looks untouched.", conflict: true },
      { who: "Pulse", text: "I also see a real, steady pulse, so the person on screen is probably real." },
      { who: "Lip-sync", text: "A small lag fits a cloned voice laid over real video." },
    ],
    judge: { verdict: "synthetic", tier: "TIER_2_ELEVATED", justification: "The picture and pulse look genuine, but the voice is very likely cloned. Treat the audio as manipulated." },
    chain: {
      fileHash: H("5be19d02a47c6f31"),
      intact: true,
      events: [
        { time: "14:11:05", text: "File received and SHA-256 recorded", status: "ok" },
        { time: "14:11:12", text: "Detectors run on the verified copy", status: "ok" },
        { time: "14:11:49", text: "Debate transcript sealed and signed", status: "ok" },
      ],
    },
  },
  {
    id: "S5",
    title: "Compressed protest footage",
    category: "conflict",
    context: "A heavily re-shared clip of a street protest has been flagged by readers as fake. A journalist wants to know whether to trust it.",
    file: "protest_clip_forwarded.mp4",
    durationS: 27,
    expected: "authentic",
    detectors: [
      { id: "video", name: "Video Classifier", p: 0.72, quality: 0.41, claim: "Possible blending, but the frames are very heavily compressed.", flags: ["Low bitrate", "Blocky frames"] },
      { id: "rppg", name: "Pulse (rPPG)", p: 0.21, quality: 0.64, claim: "A normal pulse was found on two visible faces.", flags: [] },
      { id: "syncnet", name: "Lip-sync (SyncNet)", p: 0.1, quality: 0.66, claim: "Lips and audio are in step.", flags: [] },
      { id: "aasist", name: "Voice (AASIST)", p: 0.15, quality: 0.7, claim: "Voices look natural; background noise is high.", flags: ["Noisy audio"] },
    ],
    debate: [
      { who: "Video Classifier", text: "Synthetic, p=0.72. But my score is unreliable on heavily compressed video." , conflict: true },
      { who: "Pulse", text: "I see normal pulses on two faces." },
      { who: "Lip-sync", text: "Timing is normal." },
      { who: "Voice", text: "Voices look natural." },
    ],
    judge: { verdict: "authentic", tier: "TIER_1_LOW", justification: "Only the video check objects, and it is known to over-report on heavily compressed video. Three other checks found nothing unusual." },
    chain: {
      fileHash: H("e6f0a2b9d17c4835"),
      intact: true,
      events: [
        { time: "11:47:20", text: "File received and SHA-256 recorded", status: "ok" },
        { time: "11:47:24", text: "Detectors run on the verified copy", status: "ok" },
        { time: "11:47:50", text: "Debate transcript sealed and signed", status: "ok" },
      ],
    },
  },
  {
    id: "S6",
    title: "Night-time security clip",
    category: "conflict",
    context: "A security team has night-time footage of a person speaking at a loading dock. They suspect it is fabricated.",
    file: "loading_dock_night.mp4",
    durationS: 40,
    expected: "manipulated",
    detectors: [
      { id: "video", name: "Video Classifier", p: 0.88, quality: 0.74, claim: "Texture smoothing and blending in 70% of frames.", flags: ["Texture smoothing"] },
      { id: "rppg", name: "Pulse (rPPG)", p: 0.36, quality: 0.31, claim: "A weak pulse was found, but the light is too low to trust it.", flags: ["Low light", "Quality below threshold"] },
      { id: "syncnet", name: "Lip-sync (SyncNet)", p: 0.81, quality: 0.72, claim: "Lips trail the audio by 4 frames.", flags: ["Offset +4 frames"] },
      { id: "aasist", name: "Voice (AASIST)", p: 0.79, quality: 0.77, claim: "Voice-synthesis artifacts in the first half.", flags: ["0–19 s"] },
    ],
    debate: [
      { who: "Video Classifier", text: "Synthetic. Blending is visible in most frames." },
      { who: "Pulse", text: "I lean authentic, but my signal quality is only 0.31 in this light.", conflict: true },
      { who: "Lip-sync", text: "I agree with the video check. Timing is off." },
      { who: "Voice", text: "I agree. Synthesis artifacts are present." },
    ],
    judge: { verdict: "synthetic", tier: "TIER_3_CRITICAL", justification: "Three reliable checks agree. The pulse check disagrees, but its signal is too poor in low light to outweigh them." },
    chain: {
      fileHash: H("7d3a91c0f4e2b568"),
      intact: true,
      events: [
        { time: "02:14:33", text: "File received and SHA-256 recorded", status: "ok" },
        { time: "02:14:38", text: "Detectors run on the verified copy", status: "ok" },
        { time: "02:15:02", text: "Debate transcript sealed and signed", status: "ok" },
      ],
    },
  },
  {
    id: "S7",
    title: "Camera clip with a broken record",
    category: "limits",
    context: "A building's security camera produced a clip that will be used in an internal investigation. It must be treated as evidence.",
    file: "lobby_cam_clip.mp4",
    durationS: 55,
    expected: "undecided",
    detectors: [
      { id: "video", name: "Video Classifier", p: 0.09, quality: 0.91, claim: "No blending or texture artifacts found.", flags: [] },
      { id: "rppg", name: "Pulse (rPPG)", p: 0.15, quality: 0.7, claim: "A normal pulse was found.", flags: [] },
      { id: "syncnet", name: "Lip-sync (SyncNet)", p: 0.12, quality: 0.74, claim: "Lips and audio are in step.", flags: [] },
      { id: "aasist", name: "Voice (AASIST)", p: 0.08, quality: 0.83, claim: "Voice looks natural.", flags: [] },
    ],
    debate: [
      { who: "Video Classifier", text: "Nothing unusual in the content." },
      { who: "Lip-sync", text: "Agree." },
      { who: "Chain of evidence", text: "The content checks pass, but the record of this file's handling is broken (see below).", conflict: true },
    ],
    judge: { verdict: "integrity_unknown", tier: "TIER_2_ELEVATED", justification: "The content looks genuine, but the file's tamper-evident record is broken, so we cannot confirm it is the original footage." },
    chain: {
      fileHash: H("b2c8e51f09a7d364"),
      intact: false,
      events: [
        { time: "16:30:00", text: "File received; no capture-time signature from the camera", status: "warn" },
        { time: "16:30:06", text: "Frame hash mismatch at frame 412 — frames after this point do not match the recorded chain", status: "broken" },
        { time: "16:30:41", text: "Detectors run on the received copy", status: "ok" },
      ],
    },
  },
  {
    id: "S8",
    title: "Very short night clip",
    category: "limits",
    context: "A three-second clip from a phone was sent to your team. Someone claims it shows a politician at an event.",
    file: "phone_clip_short.mp4",
    durationS: 2.8,
    expected: "undecided",
    detectors: [
      { id: "video", name: "Video Classifier", p: 0.58, quality: 0.3, claim: "Only 84 frames were available in poor light; the result is unreliable.", flags: ["Short clip", "Low light"] },
      { id: "rppg", name: "Pulse (rPPG)", p: null, quality: undefined, claim: "Not run: the clip is shorter than the 5-second minimum.", flags: ["Too short"] },
      { id: "syncnet", name: "Lip-sync (SyncNet)", p: null, quality: undefined, claim: "Not run: no speech detected.", flags: ["No speech"] },
      { id: "aasist", name: "Voice (AASIST)", p: null, quality: undefined, claim: "Not run: not enough audio.", flags: ["Too little audio"] },
    ],
    debate: [
      { who: "Video Classifier", text: "Slightly synthetic, p=0.58. But I have very little to work with." },
      { who: "Chain of evidence", text: "Three of the four checks could not run on this clip." },
    ],
    judge: { verdict: "inconclusive", tier: "TIER_2_ELEVATED", justification: "There is not enough material for a reliable answer. A longer or better-quality copy is needed." },
    chain: {
      fileHash: H("3e9a04d7c1b56f82"),
      intact: true,
      events: [
        { time: "19:05:10", text: "File received and SHA-256 recorded", status: "ok" },
        { time: "19:05:12", text: "Three detectors skipped (clip too short)", status: "warn" },
        { time: "19:05:20", text: "Debate transcript sealed and signed", status: "ok" },
      ],
    },
  },
];

// ---------------------------------------------------------------------------
// Single-score baseline
// ---------------------------------------------------------------------------

export type BaselineLabel = "authentic" | "uncertain" | "synthetic";

/** Mean P(synthetic) over the detectors that ran. Same thresholds as the orchestrator (0.35 / 0.65). */
export function singleScore(s: StudyScenario): { score: number | null; label: BaselineLabel | null } {
  const ps = s.detectors.map((d) => d.p).filter((p): p is number => typeof p === "number");
  if (ps.length === 0) return { score: null, label: null };
  const score = Number((ps.reduce((a, b) => a + b, 0) / ps.length).toFixed(2));
  const label: BaselineLabel = score >= 0.65 ? "synthetic" : score <= 0.35 ? "authentic" : "uncertain";
  return { score, label };
}

// ---------------------------------------------------------------------------
// Text shown to participants
// ---------------------------------------------------------------------------

export const FORMAT_LABEL: Record<Condition, string> = {
  evidence: "the full evidence report",
  baseline: "the single score",
};

export const DECISION_PROMPT = "Based on this result, what would you do with this media?";

export const DECISION_OPTIONS: { value: Decision; label: string }[] = [
  { value: "authentic", label: "Treat it as authentic" },
  { value: "manipulated", label: "Treat it as manipulated" },
  { value: "undecided", label: "I can't decide without further checks" },
];

export const LIKERT_ANCHORS = ["Strongly disagree", "Disagree", "Somewhat disagree", "Neutral", "Somewhat agree", "Agree", "Strongly agree"];

export interface LikertItem {
  id: string;
  text: string;
}

/** Asked after every scenario. */
export const SCENARIO_ITEMS: LikertItem[] = [
  { id: "trust", text: "I trust this result." },
  { id: "understand", text: "I understand why the system gave this result." },
  { id: "confidence", text: "I am confident in the decision I just made." },
];

/** Asked once per format at the end. {X} is replaced by FORMAT_LABEL (capitalised at the start of a sentence). */
export const FORMAT_ITEMS: LikertItem[] = [
  { id: "rely", text: "I could rely on {X} when deciding what to do with a piece of media." },
  { id: "why", text: "{X} helped me understand why the system reached its result." },
  { id: "caution", text: "{X} made it clear when I should be careful." },
  { id: "easy", text: "{X} was easy to read." },
  { id: "amount", text: "{X} gave me about the right amount of information." },
  { id: "unsure", text: "When the system was unsure or its signals conflicted, {X} helped me decide what to do next." },
  { id: "work", text: "I would be comfortable using {X} in my own work." },
];

export function formatItemText(item: LikertItem, condition: Condition): string {
  const label = FORMAT_LABEL[condition];
  const t = item.text;
  if (t.startsWith("{X}")) return t.replace("{X}", label[0].toUpperCase() + label.slice(1));
  return t.replace("{X}", label);
}

export const FORCED_CHOICE = {
  question: "If you could have only one of these for real work, which would you choose?",
  options: [
    { value: "evidence" as Condition, label: "The full evidence report" },
    { value: "baseline" as Condition, label: "The single score" },
  ],
  whyPrompt: "In a sentence or two, why?",
  confusingPrompt: "Was anything in this study confusing or hard to understand? (optional)",
};

export const BACKGROUND_ITEMS = [
  {
    id: "experience",
    question: "How much experience do you have checking whether images, audio or video are genuine?",
    options: ["None", "A little (curious or occasional)", "Some (regular part of my studies or work)", "A lot (it is my job or main focus)"],
  },
  {
    id: "tools",
    question: "Have you used an automated deepfake or AI-content detector before?",
    options: ["Never", "Once or twice", "Several times", "Regularly"],
  },
];

export const CONSENT_STATEMENTS = [
  "I have read the information sheet and I understand what the study involves.",
  "I understand that taking part is voluntary and that I can stop at any time without giving a reason.",
  "I agree that my anonymous answers and timings may be used in the research.",
];

export const INSTRUCTION_STEPS = [
  "You will see eight short cases. In each one, an automated system has checked a piece of media (a video or a recording) to see whether it may be AI-generated or manipulated.",
  "Read the result. Then say what you would do with the media, and answer three short statements about how you found the result.",
  "Some results are clear. Others are uncertain or contradictory. “I can't decide without further checks” is a valid answer when you think more checking is needed.",
  "All files, people and numbers in this study are invented. You are not being tested; we are testing how the results are presented.",
  "Work at your own pace and go with your honest first impression. At the end there is a short questionnaire comparing the two ways results were shown to you.",
];

export const SCORE_EXPLAINER = "A score is the system's estimate of how likely the media is to be AI-generated or manipulated: 0 means very unlikely, 1 means very likely.";

// ---------------------------------------------------------------------------
// Counterbalancing
// ---------------------------------------------------------------------------

export function participantNumber(pid: string): number {
  const digits = pid.match(/\d+/)?.[0];
  if (digits) return parseInt(digits, 10);
  let h = 0;
  for (const ch of pid) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
}

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface Session {
  pid: string;
  order: string[];
  conditions: Record<string, Condition>;
  /** Which format's questionnaire block is shown first. */
  formatBlockOrder: [Condition, Condition];
}

/**
 * Within-subject design. Each participant sees every scenario once: 4 in each format,
 * with 1 agreement + 2 conflict + 1 limits scenario in each format. Format assignment flips
 * with participant parity; scenario order is a seeded shuffle; questionnaire block order cycles
 * every 2 participants so it is not tied to the scenario assignment.
 */
export function buildSession(pid: string): Session {
  const n = participantNumber(pid);
  const conditions: Record<string, Condition> = {};
  const seen: Record<string, number> = {};
  for (const s of SCENARIOS) {
    const j = seen[s.category] ?? 0;
    seen[s.category] = j + 1;
    conditions[s.id] = (j + n) % 2 === 0 ? "evidence" : "baseline";
  }
  const rnd = mulberry32(Math.imul(n + 1, 2654435761));
  const order = SCENARIOS.map((s) => s.id);
  for (let i = order.length - 1; i > 0; i--) {
    const k = Math.floor(rnd() * (i + 1));
    [order[i], order[k]] = [order[k], order[i]];
  }
  const formatBlockOrder: [Condition, Condition] = Math.floor(n / 2) % 2 === 0 ? ["evidence", "baseline"] : ["baseline", "evidence"];
  return { pid, order, conditions, formatBlockOrder };
}

// ---------------------------------------------------------------------------
// Responses + export
// ---------------------------------------------------------------------------

export interface ScenarioResponse {
  scenarioId: string;
  position: number;
  category: Category;
  conditionAssigned: Condition;
  conditionAtSubmit: Condition;
  facilitatorToggles: number;
  decision: Decision;
  expected: Decision;
  correct: boolean;
  trust: number;
  understand: number;
  confidence: number;
  timeMs: number;
  unclearNote: string;
}

export interface PostResponse {
  experience: string;
  tools: string;
  evidence: Record<string, number>;
  baseline: Record<string, number>;
  preference: Condition | "";
  preferenceWhy: string;
  confusing: string;
  unclearNotes: Record<string, string>;
}

export interface StudyExport {
  pid: string;
  startedAt: string;
  finishedAt: string;
  pilot: boolean;
  session: Session;
  scenarios: ScenarioResponse[];
  post: PostResponse;
}

function esc(v: unknown): string {
  const s = String(v ?? "");
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function scenarioCsv(e: StudyExport): string {
  const head = ["participant", "pilot", "position", "scenario", "category", "condition_assigned", "condition_at_submit", "facilitator_toggles", "decision", "expected", "correct", "trust", "understand", "confidence", "time_ms", "unclear_note"];
  const rows = e.scenarios.map((r) =>
    [e.pid, e.pilot, r.position, r.scenarioId, r.category, r.conditionAssigned, r.conditionAtSubmit, r.facilitatorToggles, r.decision, r.expected, r.correct, r.trust, r.understand, r.confidence, r.timeMs, r.unclearNote].map(esc).join(",")
  );
  return [head.join(","), ...rows].join("\n");
}

export function postCsv(e: StudyExport): string {
  const head = ["participant", "pilot", "block", "item", "value"];
  const rows: string[][] = [];
  const add = (block: string, item: string, value: unknown) => rows.push([e.pid, String(e.pilot), block, item, String(value ?? "")]);
  add("background", "experience", e.post.experience);
  add("background", "tools", e.post.tools);
  for (const it of FORMAT_ITEMS) add("evidence", it.id, e.post.evidence[it.id]);
  for (const it of FORMAT_ITEMS) add("baseline", it.id, e.post.baseline[it.id]);
  add("forced_choice", "preference", e.post.preference);
  add("forced_choice", "why", e.post.preferenceWhy);
  add("open", "confusing", e.post.confusing);
  for (const [k, v] of Object.entries(e.post.unclearNotes)) if (v) add("unclear_note", k, v);
  return [head.join(","), ...rows.map((r) => r.map(esc).join(","))].join("\n");
}

export function isDecisionCorrect(decision: Decision, expected: Decision): boolean {
  return decision === expected;
}
