"""Comprehensive Edge-Case Test Suite for AEGIS Detectors (rPPG & SyncNet).

Validates:
1. silent_video.mp4: Video without audio track.
2. short_clip.mp4: Video under 2 seconds.
3. occluded_face.mp4: Face region heavily occluded.
4. poorly_lit.mp4: Severely underexposed / dark video.
5. clean_baseline.mp4: Reference clean sample.
"""
import os
import sys

import importlib.util

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Load rPPG modules
rppg_prep_path = os.path.join(REPO_ROOT, "detectors", "rppg", "preprocess.py")
rppg_prep_spec = importlib.util.spec_from_file_location("rppg_preprocess", rppg_prep_path)
rppg_prep_mod = importlib.util.module_from_spec(rppg_prep_spec)
rppg_prep_spec.loader.exec_module(rppg_prep_mod)
RppgPreprocessor = rppg_prep_mod.RppgPreprocessor

rppg_extract_path = os.path.join(REPO_ROOT, "detectors", "rppg", "rppg_extract.py")
rppg_ext_spec = importlib.util.spec_from_file_location("rppg_extract", rppg_extract_path)
rppg_ext_mod = importlib.util.module_from_spec(rppg_ext_spec)
rppg_ext_spec.loader.exec_module(rppg_ext_mod)
extract_pulse_signal = rppg_ext_mod.extract_pulse_signal
estimate_heart_rate = rppg_ext_mod.estimate_heart_rate
signal_quality_score = rppg_ext_mod.signal_quality_score

# Load SyncNet modules
sys.path.insert(0, os.path.join(REPO_ROOT, "detectors", "syncnet"))
import preprocess as syncnet_prep_mod
from infer import SyncNetInference

FIXTURES_DIR = os.path.join(REPO_ROOT, "eval", "fixtures", "edge_cases")


def run_rppg_edge_case_tests():
    print("=" * 70)
    print("=== TEST SUITE 1: rPPG Detector Guardrails Validation ===")
    print("=" * 70)

    prep = RppgPreprocessor()
    fixtures = [
        ("clean_baseline.mp4", "Clean baseline reference clip"),
        ("silent_video.mp4", "Video with no audio track"),
        ("short_clip.mp4", "Video < 2s duration (24 frames)"),
        ("occluded_face.mp4", "Partially occluded face"),
        ("poorly_lit.mp4", "Severely underexposed video (< 8 px intensity)"),
    ]

    results = []

    for filename, desc in fixtures:
        filepath = os.path.join(FIXTURES_DIR, filename)
        if not os.path.exists(filepath):
            print(f"[FAIL] Missing fixture: {filepath}")
            continue

        rgb, fps, meta = prep.preprocess_video(filepath)

        if meta.get("guardrail_triggered", False):
            res = {
                "sample": filename,
                "description": desc,
                "guardrail": True,
                "flags": meta["flags"],
                "claim": meta["claim"],
                "score": 0.5,
                "verdict": "inconclusive",
                "estimated_bpm": 0.0,
            }
        else:
            pulse = extract_pulse_signal(rgb, fps)
            bpm = estimate_heart_rate(pulse, fps)
            quality = signal_quality_score(pulse)
            score = float(1.0 - quality)
            verdict = "synthetic" if score > 0.5 else "authentic"
            res = {
                "sample": filename,
                "description": desc,
                "guardrail": False,
                "flags": [],
                "claim": f"CHROM BVP signal extracted. BPM: {bpm:.1f}",
                "score": round(score, 3),
                "verdict": verdict,
                "estimated_bpm": round(bpm, 1),
            }

        results.append(res)
        status_tag = "[GUARDRAIL TRIGGERED]" if res["guardrail"] else "[NORMAL INFERENCE]"
        print(f"\nSample: {filename} ({desc})")
        print(f"  Status:    {status_tag}")
        print(f"  Verdict:   {res['verdict']} (score: {res['score']})")
        print(f"  Flags:     {res['flags']}")
        print(f"  Evidence:  {res['claim']}")

    return results


def run_syncnet_edge_case_tests():
    print("\n" + "=" * 70)
    print("=== TEST SUITE 2: SyncNet Detector Guardrails Validation ===")
    print("=" * 70)

    sync_prep = syncnet_prep_mod.SyncNetPreprocessor()
    infer = SyncNetInference()

    fixtures = [
        ("clean_baseline.mp4", "Clean baseline reference clip"),
        ("silent_video.mp4", "Video with no audio track"),
        ("short_clip.mp4", "Video < 2s duration (24 frames)"),
        ("occluded_face.mp4", "Partially occluded face"),
        ("poorly_lit.mp4", "Severely underexposed video"),
    ]

    results = []

    for filename, desc in fixtures:
        filepath = os.path.join(FIXTURES_DIR, filename)
        if not os.path.exists(filepath):
            print(f"[FAIL] Missing fixture: {filepath}")
            continue

        vid_seqs, aud_seqs, has_audio = sync_prep.preprocess(filepath)
        conf, raw, evidence = infer.score_video(vid_seqs, aud_seqs, has_audio)

        res = {
            "sample": filename,
            "description": desc,
            "has_audio": has_audio,
            "vid_sequences": len(vid_seqs),
            "confidence": round(conf, 3),
            "flags": evidence.flags,
            "claim": evidence.claim,
        }
        results.append(res)

        print(f"\nSample: {filename} ({desc})")
        print(f"  Has Audio:     {has_audio}")
        print(f"  Lip Sequences: {len(vid_seqs)}")
        print(f"  Confidence:    {conf} (0.5 = neutral / N/A)")
        print(f"  Flags:         {evidence.flags}")
        print(f"  Evidence:      {evidence.claim}")

    return results


if __name__ == "__main__":
    rppg_res = run_rppg_edge_case_tests()
    sync_res = run_syncnet_edge_case_tests()
    print("\nAll edge-case validations completed.")
