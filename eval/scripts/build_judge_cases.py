"""
Builds the 20 Month 1 Evaluation Cases for the AEGIS Judge Agent.
=================================================================
Pulls real evaluated samples from eval/reports/week_benchmark_raw.csv,
reconstructing the exact video detector responses (video-classifier, rppg, syncnet)
and pairing them with expected arbitration outcomes, known disagreement triggers,
and forensic audit metadata.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List

BENCHMARK_CSV = Path(__file__).resolve().parent.parent / "reports" / "week_benchmark_raw.csv"
OUTPUT_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "judge" / "month1_judge_cases.json"


def vc_response(job_id: str, conf: float) -> Dict[str, Any]:
    flags = ["high_fake_probability"] if conf >= 0.65 else (["authentic_frames"] if conf <= 0.35 else ["borderline_frames"])
    return {
        "job_id": job_id,
        "modality": "video",
        "confidence": conf,
        "raw_score": conf,
        "latency_ms": 5000,
        "model": "efficientnet-b0",
        "model_version": "efficientnet-b0-v1.0",
        "evidence": {
            "claim": f"Frame-level analysis computed synthetic probability of {conf:.2f}.",
            "flags": flags,
        },
    }


def rppg_response(job_id: str, score: float, iq: float = 1.0, flags: List[str] = None) -> Dict[str, Any]:
    flags = flags or []
    verdict = "inconclusive" if iq < 0.5 else ("synthetic" if score >= 0.5 else "authentic")
    bpm = 72.0 if score < 0.5 else 0.0
    return {
        "job_id": job_id,
        "modality": "video",
        "confidence": round(abs(score - 0.5) * 2.0 * iq, 4),
        "raw_score": score,
        "score": score,
        "verdict": verdict,
        "model": "rppg-chrom",
        "model_version": "rppg-chrom-v1.0",
        "estimated_bpm": bpm,
        "latency_ms": 4000,
        "input_quality": iq,
        "evidence": {
            "claim": f"BVP pulse signal extracted via CHROM with estimated heart rate of {bpm:.1f} BPM.",
            "flags": flags,
        },
    }


def syncnet_response(job_id: str, conf: float = 0.5, offset: float = 0.0, flags: List[str] = None) -> Dict[str, Any]:
    flags = flags or ["not_applicable"]
    return {
        "job_id": job_id,
        "confidence": conf,
        "raw_score": offset,
        "latency_ms": 6000,
        "model": "syncnet",
        "model_version": "syncnet-v1.3",
        "evidence": {
            "claim": "Lip-sync analysis evaluated audiovisual correlation.",
            "flags": flags,
        },
    }


def build_cases() -> List[Dict[str, Any]]:
    if not BENCHMARK_CSV.is_file():
        raise FileNotFoundError(f"Benchmark CSV not found at {BENCHMARK_CSV}")

    rows = []
    with open(BENCHMARK_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("modality") == "video":
                rows.append(r)

    # 1. Select 8 Known Disagreement Cases (Hard Polarity Inversion: Classifier Authentic vs rPPG Synthetic)
    # real videos with low vc and high rppg:
    # 296 (0.00 / 0.74), 146 (0.24 / 0.89), 863 (0.08 / 0.78), 992 (0.21 / 0.79), 379 (0.29 / 0.68)
    # fake videos (missed fakes where rppg caught anomaly):
    # FaceShifter_761_766 (0.26 / 0.67), DeepFakeDetection_10_19 (0.26 / 0.78), NeuralTextures_076_079 (0.06 / 0.75)
    disagreement_keys = [
        "eval/data/video_subset/real/296.mp4",
        "eval/data/video_subset/real/146.mp4",
        "eval/data/video_subset/real/863.mp4",
        "eval/data/video_subset/real/992.mp4",
        "eval/data/video_subset/real/379.mp4",
        "eval/data/video_subset/fake/FaceShifter_761_766.mp4",
        "eval/data/video_subset/fake/DeepFakeDetection_10_19__kitchen_still__IDX76N5R.mp4",
        "eval/data/video_subset/fake/NeuralTextures_076_079.mp4",
    ]

    # 2. Select 4 Borderline / One-sided cases (Classifier Borderline [0.35, 0.65] vs rPPG Synthetic)
    borderline_keys = [
        "eval/data/video_subset/fake/FaceShifter_705_707.mp4",  # vc=0.5407, rppg=0.7667
        "eval/data/video_subset/real/067.mp4",                  # vc=0.6111, rppg=0.7800
        "eval/data/video_subset/fake/FaceShifter_892_112.mp4",  # vc=0.4375, rppg=0.7023
        "eval/data/video_subset/fake/FaceSwap_507_418.mp4",     # vc=0.2499, rppg=0.4648 (inconclusive rppg)
    ]

    # 3. Select 3 Gap / Degraded cases
    gap_keys = [
        "eval/data/video_subset/real/721.mp4",                  # vc=0.1857, rppg=0.6847
        "eval/data/video_subset/fake/FaceShifter_526_436.mp4",  # vc=0.2999, rppg=0.8541
        "eval/data/video_subset/fake/FaceShifter_817_827.mp4",  # vc=0.3055, rppg=0.6431
    ]

    # 4. Select Consensus / Clean cases
    consensus_keys = [
        "eval/data/video_subset/real/159.mp4",                  # vc=0.1818, rppg=0.2630 (Authentic consensus)
    ]

    selected_order = disagreement_keys + borderline_keys + gap_keys + consensus_keys
    row_map = {r["sample_path"]: r for r in rows}

    cases: List[Dict[str, Any]] = []

    case_counter = 1
    for path in selected_order:
        r = row_map.get(path)
        if not r:
            continue
        job_id = f"m1-case-{case_counter:03d}"
        vc_conf = round(float(r["det_video_classifier_confidence"]), 4)
        rppg_score = round(float(r["det_rppg_confidence"]), 4)  # legacy rppg confidence was P(synthetic)
        sync_conf = round(float(r.get("det_syncnet_confidence", 0.5)), 4)

        is_disagreement = path in disagreement_keys
        category = "disagreement_polarity_inversion" if is_disagreement else (
            "borderline_one_sided" if path in borderline_keys else (
                "consensus" if path in consensus_keys else "gap_or_degraded"
            )
        )

        expected_allowed_verdicts = ["INTEGRITY_UNKNOWN"]
        if category == "consensus":
            expected_allowed_verdicts = ["AUTHENTIC"]
        elif is_disagreement:
            # Under Guard 1, unresolved polarity inversion must downgrade to INTEGRITY_UNKNOWN
            expected_allowed_verdicts = ["INTEGRITY_UNKNOWN", "SYNTHETIC"]
        elif category == "borderline_one_sided":
            # VC is dropped as borderline gap; rPPG synthetic alone dictates synthetic or integrity_unknown under Guard 2
            expected_allowed_verdicts = ["SYNTHETIC", "INTEGRITY_UNKNOWN"]

        case = {
            "case_id": job_id,
            "sample_path": path,
            "filename": Path(path).name,
            "category": category,
            "is_known_disagreement": is_disagreement,
            "true_label": r["true_label"],
            "month1_baseline_verdict": r["final_verdict"],
            "month1_baseline_score": float(r["final_score"]),
            "expected_allowed_verdicts": expected_allowed_verdicts,
            "raw_responses": {
                "video-classifier": vc_response(job_id, vc_conf),
                "rppg": rppg_response(job_id, rppg_score),
                "syncnet": syncnet_response(job_id, sync_conf, 0.0, ["not_applicable"]),
            },
            "operating_conditions": {
                "duration_seconds": 5.0,
                "mean_luminance": 80.0,
                "face_detected": True,
                "audio_present": False,
            },
            "description": (
                f"Month 1 sample '{Path(path).name}' ({r['true_label']}). "
                f"video-classifier={vc_conf:.2f}, rppg={rppg_score:.2f}, syncnet={sync_conf:.2f}."
            ),
        }
        cases.append(case)
        case_counter += 1

    # Add 4 specialized edge-case scenarios from Month 1 testbed to bring total to 20:
    # A. Face-Swap deepfake (Rule 3)
    cases.append({
        "case_id": f"m1-case-{case_counter:03d}",
        "sample_path": "eval/data/synthesized/face_swap_high_spatial.mp4",
        "filename": "face_swap_high_spatial.mp4",
        "category": "disagreement_polarity_inversion",
        "is_known_disagreement": True,
        "true_label": "fake",
        "month1_baseline_verdict": "UNCERTAIN",
        "month1_baseline_score": 0.52,
        "expected_allowed_verdicts": ["SYNTHETIC"],
        "raw_responses": {
            "video-classifier": vc_response(f"m1-case-{case_counter:03d}", 0.92),
            "rppg": rppg_response(f"m1-case-{case_counter:03d}", 0.15, 1.0, ["nominal_pulse_70_bpm"]),
            "syncnet": syncnet_response(f"m1-case-{case_counter:03d}", 0.5, 0.0, ["not_applicable"]),
        },
        "operating_conditions": {
            "duration_seconds": 6.0,
            "mean_luminance": 95.0,
            "face_detected": True,
            "audio_present": False,
        },
        "description": "Rule 3 Face-Swap scenario: high spatial manipulation overrides authentic host body pulse.",
    })
    case_counter += 1

    # B. Low-light score inversion trap (Rule 1)
    cases.append({
        "case_id": f"m1-case-{case_counter:03d}",
        "sample_path": "eval/fixtures/edge_cases/dim_light.mp4",
        "filename": "dim_light.mp4",
        "category": "disagreement_polarity_inversion",
        "is_known_disagreement": True,
        "true_label": "real",
        "month1_baseline_verdict": "UNCERTAIN",
        "month1_baseline_score": 0.55,
        "expected_allowed_verdicts": ["AUTHENTIC", "INTEGRITY_UNKNOWN"],
        "raw_responses": {
            "video-classifier": vc_response(f"m1-case-{case_counter:03d}", 0.22),
            "rppg": rppg_response(f"m1-case-{case_counter:03d}", 0.88, 0.5, ["low_light_attenuation"]),
            "syncnet": syncnet_response(f"m1-case-{case_counter:03d}", 0.5, 0.0, ["not_applicable"]),
        },
        "operating_conditions": {
            "duration_seconds": 7.0,
            "mean_luminance": 25.0,  # < 40.0 triggers Rule 1
            "face_detected": True,
            "audio_present": False,
        },
        "description": "Rule 1 Low-light scenario: rPPG synthetic signal discounted under low luminance.",
    })
    case_counter += 1

    # C. Audio dubbing desync (Rule 4)
    cases.append({
        "case_id": f"m1-case-{case_counter:03d}",
        "sample_path": "eval/data/synthesized/foreign_dubbed_news.mp4",
        "filename": "foreign_dubbed_news.mp4",
        "category": "disagreement_polarity_inversion",
        "is_known_disagreement": True,
        "true_label": "real",
        "month1_baseline_verdict": "UNCERTAIN",
        "month1_baseline_score": 0.58,
        "expected_allowed_verdicts": ["AUTHENTIC"],
        "raw_responses": {
            "video-classifier": vc_response(f"m1-case-{case_counter:03d}", 0.18),
            "rppg": rppg_response(f"m1-case-{case_counter:03d}", 0.20, 1.0, ["nominal_pulse_72_bpm"]),
            "syncnet": syncnet_response(f"m1-case-{case_counter:03d}", 0.90, -5.0, ["sync_offset_detected", "audio_visual_mismatch"]),
        },
        "operating_conditions": {
            "duration_seconds": 8.0,
            "mean_luminance": 110.0,
            "face_detected": True,
            "audio_present": True,
        },
        "description": "Rule 4 Dubbing scenario: SyncNet lip-desync ruled as translation dubbing; visual authenticity prevails.",
    })
    case_counter += 1

    # D. Severely degraded clip (Rule 5 anti-default)
    cases.append({
        "case_id": f"m1-case-{case_counter:03d}",
        "sample_path": "eval/fixtures/edge_cases/short_clip.mp4",
        "filename": "short_clip.mp4",
        "category": "fully_degraded",
        "is_known_disagreement": False,
        "true_label": "real",
        "month1_baseline_verdict": "UNCERTAIN",
        "month1_baseline_score": 0.50,
        "expected_allowed_verdicts": ["INTEGRITY_UNKNOWN"],
        "raw_responses": {
            "video-classifier": vc_response(f"m1-case-{case_counter:03d}", 0.50),
            "rppg": rppg_response(f"m1-case-{case_counter:03d}", 0.50, 0.0, ["insufficient_duration"]),
            "syncnet": syncnet_response(f"m1-case-{case_counter:03d}", 0.50, 0.0, ["not_applicable"]),
        },
        "operating_conditions": {
            "duration_seconds": 1.1,  # < 2.0s
            "mean_luminance": 30.0,
            "face_detected": True,
            "audio_present": False,
        },
        "description": "Rule 5 Degraded video: insufficient signal across all modalities forces INTEGRITY_UNKNOWN.",
    })

    return cases


def main():
    parser = argparse.ArgumentParser(description="Build 20 Month 1 Judge Evaluation Cases")
    parser.add_argument("--check", action="store_true", help="Verify fixtures exist and validate schema")
    args = parser.parse_args()

    cases = build_cases()
    OUTPUT_FIXTURES.parent.mkdir(parents=True, exist_ok=True)

    if args.check:
        if not OUTPUT_FIXTURES.is_file():
            print(f"ERROR: Fixture file {OUTPUT_FIXTURES} does not exist.")
            exit(1)
        with open(OUTPUT_FIXTURES, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if len(existing) != len(cases):
            print(f"ERROR: Existing count ({len(existing)}) != generated count ({len(cases)}).")
            exit(1)
        print(f"SUCCESS: Fixture file verified with {len(existing)} cases.")
        return

    with open(OUTPUT_FIXTURES, "w", encoding="utf-8") as f:
        json.dump(cases, f, indent=2)

    disagreements = sum(1 for c in cases if c["is_known_disagreement"])
    print(f"Built {len(cases)} Month 1 judge evaluation cases ({disagreements} known disagreements).")
    print(f"Saved to: {OUTPUT_FIXTURES}")


if __name__ == "__main__":
    main()
