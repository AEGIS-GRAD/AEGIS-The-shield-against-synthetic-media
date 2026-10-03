"""
Planning test set — v1 (18 samples)
=====================================
Per orchestrator_design.md section 7, criterion #1: the test set must cover
each modality, mixed/ambiguous inputs, and the four named edge cases:
silent video, clip < 2s, occluded face, poorly lit clip.

Each sample is (input_summary, risk_profile, budget_s, note).
`note` records WHY the sample exists, so a reviewer doesn't have to guess
what each one is meant to catch.
"""

SAMPLES = [
    # --- Straightforward cases: one per modality, standard conditions ---
    (
        {"modality": "video", "has_audio": True, "duration_seconds": 10.0,
         "face_visibility": 0.9, "luminance": 0.5, "resolution": [1280, 720]},
        "standard", 20.0,
        "baseline: clean video with audio, nothing unusual",
    ),
    (
        {"modality": "audio", "has_audio": True, "duration_seconds": 4.5},
        "standard", 10.0,
        "baseline: audio-only file",
    ),
    (
        {"modality": "image", "has_audio": False},
        "standard", 10.0,
        "baseline: single image, no audio/video detectors should apply",
    ),

    # --- The 4 named edge cases from orchestrator_design.md ---
    (
        {"modality": "video", "has_audio": False, "duration_seconds": 8.0,
         "face_visibility": 0.9, "luminance": 0.5, "resolution": [1280, 720]},
        "standard", 20.0,
        "EDGE CASE: silent video — AASIST and SyncNet must be excluded, not skipped silently",
    ),
    (
        {"modality": "video", "has_audio": True, "duration_seconds": 1.2,
         "face_visibility": 0.9, "luminance": 0.5, "resolution": [1280, 720]},
        "standard", 20.0,
        "EDGE CASE: clip under 2s — rPPG needs min_duration_s, should be excluded",
    ),
    (
        {"modality": "video", "has_audio": True, "duration_seconds": 10.0,
         "face_visibility": 0.25, "luminance": 0.5, "resolution": [1280, 720]},
        "standard", 20.0,
        "EDGE CASE: heavily occluded face — rPPG/SyncNet need min_face_visibility",
    ),
    (
        {"modality": "video", "has_audio": True, "duration_seconds": 10.0,
         "face_visibility": 0.9, "luminance": 0.08, "resolution": [1280, 720]},
        "standard", 20.0,
        "EDGE CASE: poorly lit clip — below min_luminance for rPPG",
    ),

    # --- Combined edge cases (two problems at once) ---
    (
        {"modality": "video", "has_audio": False, "duration_seconds": 1.5,
         "face_visibility": 0.9, "luminance": 0.5, "resolution": [1280, 720]},
        "high", 10.0,
        "combined: silent AND short clip, high risk — tests coverage_warnings stacking",
    ),
    (
        {"modality": "video", "has_audio": True, "duration_seconds": 10.0,
         "face_visibility": 0.2, "luminance": 0.06, "resolution": [1280, 720]},
        "standard", 20.0,
        "combined: occluded face AND poorly lit — almost nothing video-based should be eligible",
    ),

    # --- Budget pressure variations ---
    (
        {"modality": "video", "has_audio": True, "duration_seconds": 10.0,
         "face_visibility": 0.9, "luminance": 0.5, "resolution": [1280, 720]},
        "standard", 6.0,
        "budget pressure: all 4 eligible, but budget too tight for all — tests staging logic",
    ),
    (
        {"modality": "video", "has_audio": True, "duration_seconds": 10.0,
         "face_visibility": 0.9, "luminance": 0.5, "resolution": [1280, 720]},
        "low", 3.0,
        "very tight budget + low risk — should pick the cheapest 1-2 detectors only",
    ),
    (
        {"modality": "video", "has_audio": True, "duration_seconds": 10.0,
         "face_visibility": 0.9, "luminance": 0.5, "resolution": [1280, 720]},
        "high", 60.0,
        "generous budget + high risk — should favor maximum coverage",
    ),

    # --- Risk profile variations, same input ---
    (
        {"modality": "video", "has_audio": False, "duration_seconds": 8.0,
         "face_visibility": 0.9, "luminance": 0.5, "resolution": [1280, 720]},
        "low", 20.0,
        "silent video, low risk — compare plan against the 'standard' silent-video case above",
    ),
    (
        {"modality": "video", "has_audio": False, "duration_seconds": 8.0,
         "face_visibility": 0.9, "luminance": 0.5, "resolution": [1280, 720]},
        "high", 20.0,
        "silent video, high risk — should the plan differ from low/standard risk given same gap?",
    ),

    # --- Nothing eligible at all ---
    (
        {"modality": "video", "has_audio": False, "duration_seconds": 1.0,
         "face_visibility": 0.1, "luminance": 0.05, "resolution": [120, 90]},
        "high", 20.0,
        "worst case: silent, too short, occluded, dark, low-res — tests the 'no detector eligible' path",
    ),

    # --- Low resolution only ---
    (
        {"modality": "video", "has_audio": True, "duration_seconds": 10.0,
         "face_visibility": 0.9, "luminance": 0.5, "resolution": [160, 120]},
        "standard", 20.0,
        "low resolution only — tests min_resolution eligibility independent of other factors",
    ),

    # --- Ambiguous / mixed-signal modality ---
    (
        {"modality": "video", "has_audio": True, "duration_seconds": 45.0,
         "face_visibility": 0.9, "luminance": 0.5, "resolution": [1920, 1080]},
        "standard", 20.0,
        "long clip near max_duration_s boundary — tests duration upper bound handling",
    ),

    # --- Unusual but plausible real input ---
    (
        {"modality": "audio", "has_audio": True, "duration_seconds": 0.8},
        "high", 10.0,
        "very short audio clip, high risk — only audio detector exists; tests minimal-but-valid plan",
    ),
    (
        {"modality": "video", "has_audio": True, "duration_seconds": 10.0,
         "face_visibility": 0.65, "luminance": 0.5, "resolution": [1280, 720]},
        "standard", 20.0,
        "borderline face visibility — exactly at a plausible threshold, tests boundary behaviour",
    ),
]

if __name__ == "__main__":
    print(f"Total samples: {len(SAMPLES)}")
    edge_case_count = sum(1 for s in SAMPLES if "EDGE CASE" in s[3])
    print(f"Named edge cases covered: {edge_case_count}")
