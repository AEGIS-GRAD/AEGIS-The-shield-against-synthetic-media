# Planner v1 — Evaluation Notes

Prompt version: `planner-v2.0`

**18/19 samples passed validation** (valid JSON, schema-conformant, no ineligible detector used, within budget).

---

## Sample 1: baseline: clean video with audio, nothing unusual

- Eligible detectors: `['rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 197.55s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier",
        "syncnet"
      ],
      "mode": "parallel"
    },
    {
      "stage": 2,
      "run": [
        "rppg"
      ],
      "mode": "parallel",
      "condition": "stage 1 inconclusive"
    }
  ],
  "skipped": [],
  "coverage_warnings": [],
  "estimated_latency_s": 16.2,
  "rationale": "Input conditions (luminance 0.5, face_visibility 0.9, duration 10s) match well with all eligible detectors; no known failure modes are triggered. Stage 1 combines the primary video-classifier and syncnet for face-swap and lip-sync detection in parallel. Stage 2 adds rppg as a secondary pulse-signal check if stage 1 is inconclusive, staying within the 20s budget (total estimated 16.2s). aasist is excluded due to video modality mismatch, but syncnet provides adequate audio-based evidence."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 2: baseline: audio-only file

- Eligible detectors: `['aasist']`
- Excluded: `[{'detector_name': 'rppg', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'video-classifier', 'reason': "modality 'audio' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 36.69s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "aasist"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [
    "No video-based evidence available \u2014 input has no visual track."
  ],
  "estimated_latency_s": 0.3,
  "rationale": "Only aasist is eligible for audio-only input with 4.5s duration, which exceeds its known failure threshold of 1s. It fits well within the 10s compute budget."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 3: baseline: single image, no audio/video detectors should apply

- Eligible detectors: `['video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'image' not supported by this detector"}, {'detector_name': 'rppg', 'reason': "modality 'image' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': "modality 'image' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 155.54s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [
    "No audio-based evidence available \u2014 audio detectors are excluded for image modality."
  ],
  "estimated_latency_s": 7.0,
  "rationale": "Only eligible detector is video-classifier, which is the default for image/video input and fits within the 10.0s compute budget. Audio-based coverage is limited due to modality exclusions."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 4: EDGE CASE: silent video — AASIST and SyncNet must be excluded, not skipped silently

- Eligible detectors: `['rppg', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': 'requires_audio=true in manifest; input has no audio track'}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 365.49s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [
    "No audio-based evidence available \u2014 input has no audio track."
  ],
  "estimated_latency_s": 7.0,
  "rationale": "Standard risk profile with compute budget 20.0s, which comfortably fits both eligible detectors. video-classifier is the primary signal for video deepfake detection. rppg is included as a secondary explainability signal; input conditions (luminance 0.5, face_visibility 0.9, duration 8.0s) do not match rppg's known failure modes (low light, short clips, occluded face). Both run in parallel, estimated latency ~7.0s within budget."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 5: EDGE CASE: clip under 2s — rPPG needs min_duration_s, should be excluded

- Eligible detectors: `['syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'rppg', 'reason': 'clip is 1.2s, manifest requires min_duration_seconds=2.0'}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 223.16s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "syncnet",
      "reason": "clip shorter than 2 seconds \u2192 known_failure_mode returns not_applicable"
    }
  ],
  "coverage_warnings": [
    "aasist excluded: modality 'video' not supported by this detector",
    "rppg excluded: clip duration 1.2s below minimum 2.0s requirement",
    "syncnet skipped: clip shorter than 2 seconds \u2192 known_failure_mode returns not_applicable"
  ],
  "estimated_latency_s": 7.0,
  "rationale": "video-classifier is the only eligible detector that can produce a meaningful verdict on this short-duration video within the compute budget. aasist and rppg are excluded per their documented constraints, and syncnet is technically eligible but its known failure mode for clips under 2 seconds causes it to return not_applicable, so it is skipped to avoid wasted compute and misleading coverage."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 6: EDGE CASE: heavily occluded face — rPPG/SyncNet need min_face_visibility

- Eligible detectors: `['rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 63.65s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "rppg",
      "reason": "input has partially occluded face (face_visibility=0.25) matching known failure mode of confident-but-wrong results"
    },
    {
      "detector_name": "syncnet",
      "reason": "input low face visibility (0.25) causes lip sync analysis to return not_applicable, providing no useful evidence within budget"
    }
  ],
  "coverage_warnings": [
    "rppg excluded despite eligibility due to documented failure condition for partially occluded faces",
    "syncnet excluded as low face visibility results in not_applicable output, reducing audio-based evidence coverage despite has_audio=true"
  ],
  "estimated_latency_s": 7.0,
  "rationale": "video-classifier selected as the most reliable primary detector given the input conditions. rppg skipped to avoid misleading confident-but-wrong outputs per its documented failure mode for partially occluded faces. syncnet skipped as low face visibility prevents meaningful lip sync analysis, making it return not_applicable and wasting budget without contributing to the verdict."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 7: EDGE CASE: poorly lit clip — below min_luminance for rPPG

- Eligible detectors: `['rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 60.51s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "rppg",
      "reason": "input luminance 0.08 matches known failure mode: low-light footage \u2192 unreliable pulse signal extraction, high false-negative rate; reliability notes warn it is not authoritative in poor lighting"
    },
    {
      "detector_name": "syncnet",
      "reason": "input luminance 0.08 matches known failure mode: severely underexposed video \u2192 zero lip sequences extracted, returns not_applicable rather than a score; would waste budget without useful evidence"
    }
  ],
  "coverage_warnings": [
    "rppg excluded despite eligibility due to documented failure condition for low-light inputs producing unreliable/misleading results",
    "syncnet excluded despite has_audio=true due to low luminance causing not_applicable output"
  ],
  "estimated_latency_s": 7.0,
  "rationale": "video-classifier is the most reliable primary signal for video inputs and runs within budget. Both rppg and syncnet have documented failure modes matching this input's low luminance (0.08): rppg suffers from unreliable pulse signal extraction and potentially misleading confident-but-wrong results, while syncnet returns not_applicable for severely underexposed video. Skipping them avoids low-value evidence while maintaining coverage with the primary detector under the standard risk profile and 20s compute budget."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 8: combined: silent AND short clip, high risk — tests coverage_warnings stacking

- Eligible detectors: `['video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'rppg', 'reason': 'clip is 1.5s, manifest requires min_duration_seconds=2.0'}, {'detector_name': 'syncnet', 'reason': 'requires_audio=true in manifest; input has no audio track'}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 21.82s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [
    "No audio-based evidence available \u2014 input has no audio track.",
    "rppg excluded: clip duration 1.5s below minimum 2.0s requirement.",
    "syncnet excluded: requires audio track; input has no audio."
  ],
  "estimated_latency_s": 7.0,
  "rationale": "Only video-classifier is eligible given the input constraints (no audio track, duration 1.5s). Other detectors (aasist, rppg, syncnet) are excluded per manifest rules. High risk profile favors broader coverage, but budget and eligibility constraints limit selection to the primary video classifier."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 9: combined: occluded face AND poorly lit — almost nothing video-based should be eligible

- Eligible detectors: `['rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 316.2s)
- Validation: **FAIL** — missing schema keys: {'estimated_latency_s'}

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "rppg",
      "reason": "input luminance 0.06 and face_visibility 0.2 match known failure modes: low-light unreliable pulse signal and partially occluded face \u2192 confident-but-wrong results"
    },
    {
      "detector_name": "syncnet",
      "reason": "input luminance 0.06 and face_visibility 0.2 match known failure modes: severely underexposed video and partially occluded face cause return of not_applicable rather than a meaningful verdict"
    }
  ],
  "coverage_warnings": [
    "rppg and syncnet skipped due to documented failure conditions (low luminance, low face visibility) \u2014 no reliable deepfake signals extracted from this input.",
    "aasist excluded as modality 'video' is unsupported by this detector."
  ],
  "estimated_latency_latency_s": 7.0,
  "rationale": "video-classifier is the most reliable primary signal for video inputs under these conditions. rppg and syncnet are technically eligible but their documented failure modes (low luminance, low face visibility) risk producing misleading or not_applicable results, so they are skipped to maintain verdict reliability within the compute budget."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 10: budget pressure: all 4 eligible, but budget too tight for all — tests staging logic

- Eligible detectors: `['rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 70.5s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [],
  "skipped": [],
  "coverage_warnings": [
    "No eligible detectors can run within the 6.0s compute budget; all eligible detectors (rppg ~6.6s, video-classifier ~7.0s, syncnet ~9.6s) exceed the hard latency ceiling."
  ],
  "estimated_latency_s": 0.0,
  "rationale": "All eligible detectors have stated average latencies exceeding the 6.0s compute budget. Even the fastest eligible detector (rppg at ~6.6s avg) surpasses the budget. Given the hard constraint on total estimated latency, no detectors can be selected without violating the budget. The input conditions are favorable (good luminance, face visibility, sufficient duration), but budget is the limiting factor."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 11: very tight budget + low risk — should pick the cheapest 1-2 detectors only

- Eligible detectors: `['rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 50.71s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [],
  "skipped": [],
  "coverage_warnings": [
    "No eligible detectors can be run within the 3.0s compute budget; all eligible detectors (rppg ~6.6s, syncnet ~9.6s, video-classifier ~7.0s avg latency) exceed the hard ceiling."
  ],
  "estimated_latency_s": 0,
  "rationale": "All technically eligible detectors exceed the 3.0s compute budget. Per the hard latency ceiling rule, no detector may be selected as doing so would violate the budget. Returning an empty stages list with a full explanation in coverage_warnings and rationale."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 12: generous budget + high risk — should favor maximum coverage

- Eligible detectors: `['rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3-ultra-550b-a55b:free` (latency: 47.34s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier",
        "rppg",
        "syncnet"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [
    "No pure audio-based detector (aasist) available \u2014 excluded because modality is video; syncnet provides audio-visual sync evidence instead."
  ],
  "estimated_latency_s": 9.6,
  "rationale": "High risk profile favors maximum coverage; all three eligible detectors are applicable given good conditions (face_visibility 0.9, luminance 0.5, duration 10s, audio present). The 60s budget comfortably fits running all in parallel (max avg latency 9.6s), providing visual artifact detection (video-classifier), physiological signal analysis (rppg), and lip-sync verification (syncnet) simultaneously."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 13: silent video, low risk — compare plan against the 'standard' silent-video case above

- Eligible detectors: `['rppg', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': 'requires_audio=true in manifest; input has no audio track'}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 51.53s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [
    "No audio-based detectors are eligible for this video-only input."
  ],
  "estimated_latency_s": 13.6,
  "rationale": "Both video-classifier and rppg are eligible; input conditions (luminance 0.5, face_visibility 0.9, duration 8s) fall outside each detector's known failure modes. Low risk profile with ample compute budget permits parallel execution for comprehensive coverage."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 14: silent video, high risk — should the plan differ from low/standard risk given same gap?

- Eligible detectors: `['rppg', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': 'requires_audio=true in manifest; input has no audio track'}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 209.7s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [
    "No audio-based evidence available \u2014 input has no audio track."
  ],
  "estimated_latency_s": 13.6,
  "rationale": "Both video-classifier and rppg are eligible; input conditions (luminance 0.5, face_visibility 0.9, duration 8.0s) avoid rppg's known failure modes of low light, short clips, and occlusion. High risk profile favors broader coverage, and the 20s budget permits running both eligible detectors. video-classifier serves as the primary frame-level deepfake detector, while rppg provides a secondary pulse-based explainability signal."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 15: worst case: silent, too short, occluded, dark, low-res — tests the 'no detector eligible' path

- Eligible detectors: `['video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'rppg', 'reason': 'clip is 1.0s, manifest requires min_duration_seconds=2.0'}, {'detector_name': 'syncnet', 'reason': 'requires_audio=true in manifest; input has no audio track'}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 199.04s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [
    "No audio-based detectors eligible for this video input (aasist excluded: modality 'video' not supported; syncnet excluded: requires audio track).",
    "rppg excluded due to clip duration (1.0s) falling below manifest minimum of 2.0s.",
    "Low luminance (0.05) and face visibility (0.1) at VGA resolution (120x90) may reduce video-classifier accuracy; known_failure_modes include reduced accuracy under heavy compression/low-quality conditions."
  ],
  "estimated_latency_s": 7.0,
  "rationale": "Only video-classifier is eligible and within the 20s compute budget. All other detectors are excluded by hard rules (modality, duration, audio requirements). High risk profile favors maximum coverage, but eligibility constraints limit selection to the primary frame-level classifier. Performance may be reduced under the given low-light, low-resolution conditions."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 16: low resolution only — tests min_resolution eligibility independent of other factors

- Eligible detectors: `['rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 287.37s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier"
      ],
      "mode": "parallel"
    },
    {
      "stage": 2,
      "run": [
        "syncnet",
        "rppg"
      ],
      "mode": "parallel",
      "condition": "stage 1 inconclusive"
    }
  ],
  "skipped": [],
  "coverage_warnings": [
    "aasist excluded due to modality 'video' not supported by this detector; syncnet provides audio-based deepfake detection for video inputs."
  ],
  "estimated_latency_s": 16.6,
  "rationale": "video-classifier runs as the primary signal in stage 1 (7.0s avg). Given good input conditions (luminance 0.5, face visibility 0.9, duration 10s, audio present), both syncnet and rppg are eligible and their known failure modes do not apply. They run in parallel in stage 2 (max 9.6s) to provide lip-sync and pulse signal evidence, keeping total estimated latency at 16.6s within the 20s budget."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 17: long clip near max_duration_s boundary — tests duration upper bound handling

- Eligible detectors: `['rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 119.12s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier"
      ],
      "mode": "parallel"
    },
    {
      "stage": 2,
      "run": [
        "syncnet"
      ],
      "mode": "parallel",
      "condition": "stage 1 inconclusive"
    }
  ],
  "skipped": [
    {
      "detector_name": "rppg",
      "reason": "eligible but compute budget of 20s only accommodates video-classifier and syncnet; including rppg would exceed the hard latency ceiling"
    }
  ],
  "coverage_warnings": [
    "rppg excluded despite eligible conditions (good luminance, high face visibility, sufficient duration) to respect 20s compute budget; syncnet provides audio-based deepfake evidence instead."
  ],
  "estimated_latency_s": 16.6,
  "rationale": "Standard risk profile with a 20s budget allows running the primary video-classifier first, followed by the audio-sync detector (syncnet) only if stage 1 is inconclusive. This two-stage approach maximizes coverage within budget: stage 1 provides a quick verdict, and stage 2 escalates if needed. rppg is skipped because its pulse-signal analysis would add ~6.6s, pushing total estimated latency beyond the budget when combined with the other two detectors. Conditions (luminance 0.5, face visibility 0.9, duration 45s) are favorable for both video-classifier and syncnet."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 18: very short audio clip, high risk — only audio detector exists; tests minimal-but-valid plan

- Eligible detectors: `[]`
- Excluded: `[{'detector_name': 'aasist', 'reason': 'clip is 0.8s, manifest requires min_duration_seconds=1.0'}, {'detector_name': 'rppg', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'video-classifier', 'reason': "modality 'audio' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 193.03s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [],
  "skipped": [],
  "coverage_warnings": [
    "No eligible detectors: aasist excluded due to minimum clip duration of 1.0s (input is 0.8s); rppg, syncnet, and video-classifier do not support audio modality."
  ],
  "estimated_latency_s": 0.0,
  "rationale": "No detectors are eligible for this input. aasist fails the minimum duration requirement, and all other excluded detectors are incompatible with the audio modality."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 19: borderline face visibility — exactly at a plausible threshold, tests boundary behaviour

- Eligible detectors: `['rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `nvidia/nemotron-3.5-lightning:free` (latency: 162.85s)
- Validation: **PASS**

```json
{
  "plan_version": "2",
  "stages": [
    {
      "stage": 1,
      "run": [
        "video-classifier"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "rppg",
      "reason": "input face_visibility 0.65 indicates partial occlusion \u2014 rppg's known_failure_modes document partial occluded face as producing misleading confident-but-wrong results, not just reduced accuracy"
    },
    {
      "detector_name": "syncnet",
      "reason": "input face_visibility 0.65 indicates partial occlusion \u2014 syncnet's known_failure_modes cause lip sync analysis to be skipped gracefully, returning not_applicable rather than a usable score"
    },
    {
      "detector_name": "aasist",
      "reason": "modality 'video' not supported by this detector (excluded by orchestrator rules)"
    }
  ],
  "coverage_warnings": [
    "rppg excluded despite eligibility: partial face occlusion risks confident but incorrect verdict per documented failure mode.",
    "syncnet excluded despite eligibility: partial face occlusion causes not_applicable return, providing no lip-sync evidence.",
    "aasist excluded: video modality unsupported."
  ],
  "estimated_latency_s": 7.0,
  "rationale": "video-classifier selected as the primary reliable detector for video deepfake detection. rppg and syncnet are technically eligible but skipped because input conditions (partial face occlusion) match their documented failure modes, which could produce misleading results or not_applicable outputs. aasist excluded by system rules."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

