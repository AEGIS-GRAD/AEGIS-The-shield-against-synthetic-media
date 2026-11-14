# Planner v1 — Evaluation Notes

Prompt version: `planner-v3.0`

**22/22 samples passed validation** (valid JSON, schema-conformant, no ineligible detector used, within budget).

---

## Sample 1: baseline: clean video with audio, nothing unusual

- Eligible detectors: `['fusion', 'rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "syncnet",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    },
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    }
  ],
  "coverage_warnings": [],
  "estimated_latency_s": 15.85,
  "rationale": "Selected ['fusion', 'rppg'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 2: baseline: audio-only file

- Eligible detectors: `['aasist']`
- Excluded: `[{'detector_name': 'detector_image', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'fusion', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'rppg', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'video-classifier', 'reason': "modality 'audio' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
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
    "No audio track present; detector_image excluded.",
    "No audio track present; detector_text excluded.",
    "No audio track present; fusion excluded.",
    "No audio track present; rppg excluded.",
    "No audio track present; syncnet excluded.",
    "No audio track present; video-classifier excluded."
  ],
  "estimated_latency_s": 0.33,
  "rationale": "Selected ['aasist'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 3: baseline: single image — detector_image should apply

- Eligible detectors: `['detector_image']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'image' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'image' not supported by this detector"}, {'detector_name': 'fusion', 'reason': "modality 'image' not supported by this detector"}, {'detector_name': 'rppg', 'reason': "modality 'image' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': "modality 'image' not supported by this detector"}, {'detector_name': 'video-classifier', 'reason': "modality 'image' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "detector_image"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [],
  "estimated_latency_s": 2.0,
  "rationale": "Selected ['detector_image'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 4: baseline: text file — detector_text applies, audio/video detectors excluded

- Eligible detectors: `['detector_text']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'text' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'text' not supported by this detector"}, {'detector_name': 'fusion', 'reason': "modality 'text' not supported by this detector"}, {'detector_name': 'rppg', 'reason': "modality 'text' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': "modality 'text' not supported by this detector"}, {'detector_name': 'video-classifier', 'reason': "modality 'text' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "detector_text"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [],
  "estimated_latency_s": 0.4,
  "rationale": "Selected ['detector_text'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 5: image edge case: high risk, tight budget — tests detector_image under budget ceiling

- Eligible detectors: `['detector_image']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'image' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'image' not supported by this detector"}, {'detector_name': 'fusion', 'reason': "modality 'image' not supported by this detector"}, {'detector_name': 'rppg', 'reason': "modality 'image' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': "modality 'image' not supported by this detector"}, {'detector_name': 'video-classifier', 'reason': "modality 'image' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "detector_image"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [],
  "estimated_latency_s": 2.0,
  "rationale": "Selected ['detector_image'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 6: text edge case: high risk, tight 2s budget — tests detector_text latency fit

- Eligible detectors: `['detector_text']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'text' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'text' not supported by this detector"}, {'detector_name': 'fusion', 'reason': "modality 'text' not supported by this detector"}, {'detector_name': 'rppg', 'reason': "modality 'text' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': "modality 'text' not supported by this detector"}, {'detector_name': 'video-classifier', 'reason': "modality 'text' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "detector_text"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [],
  "estimated_latency_s": 0.4,
  "rationale": "Selected ['detector_text'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 7: EDGE CASE: silent video — AASIST and SyncNet must be excluded, not skipped silently

- Eligible detectors: `['fusion', 'rppg', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': 'requires_audio=true in manifest; input has no audio track'}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    }
  ],
  "coverage_warnings": [
    "No audio track present; syncnet excluded."
  ],
  "estimated_latency_s": 15.85,
  "rationale": "Selected ['fusion', 'rppg'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 8: EDGE CASE: clip under 2s — rPPG needs min_duration_s, should be excluded

- Eligible detectors: `['fusion', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'rppg', 'reason': 'clip is 1.2s, manifest requires min_duration_seconds=2.0'}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "video-classifier"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "syncnet",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    }
  ],
  "coverage_warnings": [],
  "estimated_latency_s": 14.96,
  "rationale": "Selected ['fusion', 'video-classifier'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 9: EDGE CASE: heavily occluded face — rPPG/SyncNet need min_face_visibility

- Eligible detectors: `['fusion', 'rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "syncnet",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    },
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    }
  ],
  "coverage_warnings": [],
  "estimated_latency_s": 15.85,
  "rationale": "Selected ['fusion', 'rppg'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 10: EDGE CASE: poorly lit clip — below min_luminance for rPPG

- Eligible detectors: `['fusion', 'rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "syncnet",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    },
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    }
  ],
  "coverage_warnings": [],
  "estimated_latency_s": 15.85,
  "rationale": "Selected ['fusion', 'rppg'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 11: combined: silent AND short clip, high risk — tests coverage_warnings stacking

- Eligible detectors: `['fusion', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'rppg', 'reason': 'clip is 1.5s, manifest requires min_duration_seconds=2.0'}, {'detector_name': 'syncnet', 'reason': 'requires_audio=true in manifest; input has no audio track'}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 10.0s"
    }
  ],
  "coverage_warnings": [
    "No audio track present; syncnet excluded."
  ],
  "estimated_latency_s": 0.0,
  "rationale": "Selected ['fusion'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 12: combined: occluded face AND poorly lit — almost nothing video-based should be eligible

- Eligible detectors: `['fusion', 'rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "syncnet",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    },
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    }
  ],
  "coverage_warnings": [],
  "estimated_latency_s": 15.85,
  "rationale": "Selected ['fusion', 'rppg'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 13: budget pressure: all 4 eligible, but budget too tight for all — tests staging logic

- Eligible detectors: `['fusion', 'rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "rppg",
      "reason": "skipped to remain within budget ceiling of 6.0s"
    },
    {
      "detector_name": "syncnet",
      "reason": "skipped to remain within budget ceiling of 6.0s"
    },
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 6.0s"
    }
  ],
  "coverage_warnings": [],
  "estimated_latency_s": 0.0,
  "rationale": "Selected ['fusion'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 14: very tight budget + low risk — should pick the cheapest 1-2 detectors only

- Eligible detectors: `['fusion', 'rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "rppg",
      "reason": "skipped to remain within budget ceiling of 3.0s"
    },
    {
      "detector_name": "syncnet",
      "reason": "skipped to remain within budget ceiling of 3.0s"
    },
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 3.0s"
    }
  ],
  "coverage_warnings": [],
  "estimated_latency_s": 0.0,
  "rationale": "Selected ['fusion'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 15: generous budget + high risk — should favor maximum coverage

- Eligible detectors: `['fusion', 'rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "rppg",
        "syncnet",
        "video-classifier"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [],
  "estimated_latency_s": 53.65,
  "rationale": "Selected ['fusion', 'rppg', 'syncnet', 'video-classifier'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 16: silent video, low risk — compare plan against the 'standard' silent-video case above

- Eligible detectors: `['fusion', 'rppg', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': 'requires_audio=true in manifest; input has no audio track'}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    }
  ],
  "coverage_warnings": [
    "No audio track present; syncnet excluded."
  ],
  "estimated_latency_s": 15.85,
  "rationale": "Selected ['fusion', 'rppg'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 17: silent video, high risk — should the plan differ from low/standard risk given same gap?

- Eligible detectors: `['fusion', 'rppg', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': 'requires_audio=true in manifest; input has no audio track'}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    }
  ],
  "coverage_warnings": [
    "No audio track present; syncnet excluded."
  ],
  "estimated_latency_s": 15.85,
  "rationale": "Selected ['fusion', 'rppg'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 18: worst case: silent, too short, occluded, dark, low-res — tests the 'no detector eligible' path

- Eligible detectors: `['fusion', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'rppg', 'reason': 'clip is 1.0s, manifest requires min_duration_seconds=2.0'}, {'detector_name': 'syncnet', 'reason': 'requires_audio=true in manifest; input has no audio track'}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "video-classifier"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [],
  "coverage_warnings": [
    "No audio track present; syncnet excluded."
  ],
  "estimated_latency_s": 14.96,
  "rationale": "Selected ['fusion', 'video-classifier'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 19: low resolution only — tests min_resolution eligibility independent of other factors

- Eligible detectors: `['fusion', 'rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "syncnet",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    },
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    }
  ],
  "coverage_warnings": [],
  "estimated_latency_s": 15.85,
  "rationale": "Selected ['fusion', 'rppg'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 20: long clip near max_duration_s boundary — tests duration upper bound handling

- Eligible detectors: `['fusion', 'rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "syncnet",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    },
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    }
  ],
  "coverage_warnings": [],
  "estimated_latency_s": 15.85,
  "rationale": "Selected ['fusion', 'rppg'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 21: very short audio clip, high risk — only audio detector exists; tests minimal-but-valid plan

- Eligible detectors: `[]`
- Excluded: `[{'detector_name': 'aasist', 'reason': 'clip is 0.8s, manifest requires min_duration_seconds=1.0'}, {'detector_name': 'detector_image', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'fusion', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'rppg', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'syncnet', 'reason': "modality 'audio' not supported by this detector"}, {'detector_name': 'video-classifier', 'reason': "modality 'audio' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [],
  "skipped": [],
  "coverage_warnings": [
    "No audio track present; detector_image excluded.",
    "No audio track present; detector_text excluded.",
    "No audio track present; fusion excluded.",
    "No audio track present; rppg excluded.",
    "No audio track present; syncnet excluded.",
    "No audio track present; video-classifier excluded."
  ],
  "estimated_latency_s": 0.0,
  "rationale": "Selected [] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

## Sample 22: borderline face visibility — exactly at a plausible threshold, tests boundary behaviour

- Eligible detectors: `['fusion', 'rppg', 'syncnet', 'video-classifier']`
- Excluded: `[{'detector_name': 'aasist', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_image', 'reason': "modality 'video' not supported by this detector"}, {'detector_name': 'detector_text', 'reason': "modality 'video' not supported by this detector"}]`
- Model used: `deterministic-reference-planner (offline-eval)` (latency: 0.02s)
- Validation: **PASS**

```json
{
  "plan_version": "3",
  "stages": [
    {
      "stage": 1,
      "run": [
        "fusion",
        "rppg"
      ],
      "mode": "parallel"
    }
  ],
  "skipped": [
    {
      "detector_name": "syncnet",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    },
    {
      "detector_name": "video-classifier",
      "reason": "skipped to remain within budget ceiling of 20.0s"
    }
  ],
  "coverage_warnings": [],
  "estimated_latency_s": 15.85,
  "rationale": "Selected ['fusion', 'rppg'] from eligible set based on budget and system load."
}
```

**Reviewer notes:** _(fill in after reading — was this a good decision?)_

---

