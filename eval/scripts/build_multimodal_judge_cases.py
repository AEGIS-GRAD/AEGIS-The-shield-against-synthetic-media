#!/usr/bin/env python3
"""
AEGIS Task 7 — Multimodal (Text & Image) Judge Evaluation Fixture & Real Text Calibrator Builder
=================================================================================================
1. Runs the real CUDA/CPU `detectors/text-detector` runtime (Desklib v1.01 + GPT-2 perplexity +
   stylometry + minimum-length gating) on a deterministic stratified split of
   `eval/data/text/text_eval_manifest.jsonl`.
2. Saves the fit split to `eval/calibration/data/detector_text_fit_predictions.jsonl` and fits
   held-out `detector_text_{platt,temperature}_calibrator.json` artifacts via `calibrate.py`
   with `metadata.source = "heldout_real"`.
3. Exports disjoint real held-out Text Judge evaluation cases (plus multi-signal edge cases)
   to `eval/fixtures/judge/text_judge_cases.json`.
4. Exports empirically grounded Image & Image+Text Judge evaluation cases (matching
   `detectors/image/app.py` and `eval/reports/image_detector_baseline.md`) to
   `eval/fixtures/judge/image_judge_cases.json`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEXT_DETECTOR_DIR = REPO_ROOT / "detectors" / "text-detector"
TEXT_MANIFEST_PATH = REPO_ROOT / "eval" / "data" / "text" / "text_eval_manifest.jsonl"
CAL_DATA_DIR = REPO_ROOT / "eval" / "calibration" / "data"
FIT_PREDICTIONS_PATH = CAL_DATA_DIR / "detector_text_fit_predictions.jsonl"
TEXT_FIXTURES_OUT = REPO_ROOT / "eval" / "fixtures" / "judge" / "text_judge_cases.json"
IMAGE_FIXTURES_OUT = REPO_ROOT / "eval" / "fixtures" / "judge" / "image_judge_cases.json"


def _stratified_select(
    rows: List[Dict[str, Any]],
    *,
    label: int,
    bucket: str,
    count: int,
    exclude_ids: set,
    paraphrased_first: bool = False,
) -> List[Dict[str, Any]]:
    pool = [
        r for r in rows
        if r.get("label") == label
        and r.get("length_bucket") == bucket
        and r.get("id") not in exclude_ids
    ]
    if paraphrased_first:
        pool.sort(key=lambda r: (0 if r.get("paraphrased") else 1, str(r.get("id", ""))))
    else:
        pool.sort(key=lambda r: str(r.get("id", "")))
    selected = pool[:count]
    for item in selected:
        exclude_ids.add(item["id"])
    return selected


def _score_real_text_samples(samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if str(TEXT_DETECTOR_DIR) not in sys.path:
        sys.path.insert(0, str(TEXT_DETECTOR_DIR))

    import torch  # noqa: E402
    from app import create_default_runtime, _score_ingested_text  # noqa: E402
    from ingest import prepare_raw_text  # noqa: E402

    print(f"[*] Initializing real text-detector runtime (CUDA={torch.cuda.is_available()})...")
    rt = create_default_runtime()
    rt.desklib.load()
    if rt.perplexity is not None:
        rt.perplexity.load()

    scored: List[Dict[str, Any]] = []
    for idx, s in enumerate(samples, 1):
        ingested = prepare_raw_text(s["text"], max_chars=rt.config.max_chars)
        resp = _score_ingested_text(
            job_id=f"txt-{s['id']}",
            ingested=ingested,
            runtime=rt,
            started_at=time.perf_counter(),
        )
        scored.append({"sample": s, "response": resp.model_dump()})
        if idx % 10 == 0 or idx == len(samples):
            print(f"    Scored {idx}/{len(samples)} real text samples (last={resp.status}, conf={resp.confidence:.4f})")

    return scored


def build_text_suite_and_calibrator() -> List[Dict[str, Any]]:
    if not TEXT_MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"Missing real text eval manifest: {TEXT_MANIFEST_PATH}")

    rows = [
        json.loads(line)
        for line in TEXT_MANIFEST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    used_ids: set = set()

    # 1. Select Disjoint Held-out Real Evaluation Split first (18 samples including 2 short_lt40 gaps)
    eval_samples: List[Dict[str, Any]] = []
    # Human held-out (7 real: 3 medium, 2 long, 1 marginal, 1 short <40w gap)
    eval_samples.extend(_stratified_select(rows, label=0, bucket="medium_150_499", count=3, exclude_ids=used_ids))
    eval_samples.extend(_stratified_select(rows, label=0, bucket="long_500_plus", count=2, exclude_ids=used_ids))
    eval_samples.extend(_stratified_select(rows, label=0, bucket="marginal_40_149", count=1, exclude_ids=used_ids))
    eval_samples.extend(_stratified_select(rows, label=0, bucket="short_lt40", count=1, exclude_ids=used_ids))
    # AI held-out (11 real: 4 medium clean/paraphrased, 2 long, 4 marginal, 1 short <40w gap)
    eval_samples.extend(_stratified_select(rows, label=1, bucket="medium_150_499", count=4, exclude_ids=used_ids, paraphrased_first=True))
    eval_samples.extend(_stratified_select(rows, label=1, bucket="long_500_plus", count=2, exclude_ids=used_ids))
    eval_samples.extend(_stratified_select(rows, label=1, bucket="marginal_40_149", count=4, exclude_ids=used_ids))
    eval_samples.extend(_stratified_select(rows, label=1, bucket="short_lt40", count=1, exclude_ids=used_ids))

    # 2. Disjoint Calibration Fit Split (72 non-short real samples, balanced human vs AI)
    fit_samples: List[Dict[str, Any]] = []
    for lbl in (0, 1):
        fit_samples.extend(_stratified_select(rows, label=lbl, bucket="medium_150_499", count=16, exclude_ids=used_ids, paraphrased_first=(lbl == 1)))
        fit_samples.extend(_stratified_select(rows, label=lbl, bucket="marginal_40_149", count=12, exclude_ids=used_ids))
        fit_samples.extend(_stratified_select(rows, label=lbl, bucket="long_500_plus", count=8, exclude_ids=used_ids))

    all_scored = _score_real_text_samples(fit_samples + eval_samples)
    fit_scored = all_scored[: len(fit_samples)]
    eval_scored = all_scored[len(fit_samples) :]

    # Fit Platt/Temperature on un-attenuated full-document confidence (medium + long) so
    # 40-149w length attenuation doesn't bias the logistic intercept.
    CAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(FIT_PREDICTIONS_PATH, "w", encoding="utf-8") as f:
        for item in fit_scored:
            s = item["sample"]
            r = item["response"]
            if s["length_bucket"] == "short_lt40":
                continue
            rec = {
                "id": s["id"],
                "label": int(s["label"]),
                "true_label": "fake" if int(s["label"]) == 1 else "real",
                "confidence": float(r["raw_score"]),
                "raw_score": float(r["raw_score"]),
                "length_bucket": s["length_bucket"],
                "paraphrased": bool(s.get("paraphrased")),
            }
            f.write(json.dumps(rec) + "\n")

    cmd = [
        sys.executable,
        str(REPO_ROOT / "eval" / "scripts" / "calibrate.py"),
        "--predictions-file",
        str(FIT_PREDICTIONS_PATH),
        "--detector-id",
        "detector_text",
        "--method",
        "platt,temperature",
        "--source-label",
        "heldout_real",
    ]
    print("[*] Fitting real held-out text calibrator via calibrate.py...")
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)

    # Convert held-out real scored samples to judge evaluation fixtures
    cases: List[Dict[str, Any]] = []
    for idx, item in enumerate(eval_scored, 1):
        s = item["sample"]
        r = item["response"]
        is_fake = int(s["label"]) == 1
        true_label = "fake" if is_fake else "real"
        is_short_gap = r["status"] == "not_applicable"
        is_marginal = s["length_bucket"] == "marginal_40_149"

        if is_short_gap:
            allowed = ["INTEGRITY_UNKNOWN"]
            cat = "short_text_not_applicable"
        elif is_fake:
            allowed = ["SYNTHETIC", "UNCERTAIN"]
            cat = "marginal_ai_text" if is_marginal else ("paraphrased_ai_text" if s.get("paraphrased") else "clean_ai_text")
        else:
            allowed = ["AUTHENTIC", "UNCERTAIN"]
            cat = "marginal_human_text" if is_marginal else "clean_human_text"

        case_id = f"txt-case-{idx:03d}"
        r_copy = dict(r)
        r_copy["job_id"] = case_id
        cases.append(
            {
                "case_id": case_id,
                "modality": "text",
                "sample_id": s["id"],
                "filename": f"{s['id']}.txt",
                "category": cat,
                "true_label": true_label,
                "word_count": int(s["word_count"]),
                "length_bucket": s["length_bucket"],
                "paraphrased": bool(s.get("paraphrased")),
                "baseline_single_score": float(r["confidence"]),
                "expected_allowed_verdicts": allowed,
                "raw_responses": {"detector_text": r_copy},
                "operating_conditions": {
                    "duration_seconds": None,
                    "mean_luminance": None,
                    "face_detected": True,
                    "audio_present": False,
                },
                "description": (
                    f"Real MAGE text ({true_label}, {s['length_bucket']}, {s['word_count']}w, "
                    f"paraphrased={bool(s.get('paraphrased'))}): status={r['status']}, conf={r['confidence']:.4f}."
                ),
            }
        )

    # Add 2 targeted multi-signal text edge cases exercising Rule 8 and chunk disagreement
    cases.append(
        {
            "case_id": "txt-case-019",
            "modality": "text",
            "sample_id": "edge-bino-corroborated-paraphrase",
            "filename": "paraphrased_bino_corroborated.txt",
            "category": "multi_signal_rule8_ai",
            "true_label": "fake",
            "word_count": 265,
            "length_bucket": "medium_150_499",
            "paraphrased": True,
            "baseline_single_score": 0.59,
            "expected_allowed_verdicts": ["SYNTHETIC", "UNCERTAIN"],
            "raw_responses": {
                "detector_text": {
                    "job_id": "txt-case-019",
                    "status": "ok",
                    "modality": "text",
                    "confidence": 0.59,
                    "raw_score": 0.59,
                    "model_version": "desklib-v1.01-fp16",
                    "evidence": {
                        "claim": "Borderline Desklib sequence score corroborated by Binoculars-small and low GPT-2 perplexity.",
                        "flags": [
                            "moderate_ai_probability",
                            "low_perplexity",
                            "low_burstiness",
                            "binoculars_corroborated",
                        ],
                    },
                }
            },
            "operating_conditions": {"face_detected": True, "audio_present": False},
            "description": "Edge case: borderline paraphrased AI text rescued to SYNTHETIC via Rule 8 Binoculars+PPL corroboration.",
        }
    )
    cases.append(
        {
            "case_id": "txt-case-020",
            "modality": "text",
            "sample_id": "edge-chunk-disagreement-hybrid",
            "filename": "hybrid_human_ai_document.txt",
            "category": "hybrid_chunk_disagreement",
            "true_label": "fake",
            "word_count": 610,
            "length_bucket": "long_500_plus",
            "paraphrased": True,
            "baseline_single_score": 0.51,
            "expected_allowed_verdicts": ["UNCERTAIN"],
            "raw_responses": {
                "detector_text": {
                    "job_id": "txt-case-020",
                    "status": "ok",
                    "modality": "text",
                    "confidence": 0.51,
                    "raw_score": 0.51,
                    "model_version": "desklib-v1.01-fp16",
                    "evidence": {
                        "claim": "Hybrid authorship suspected: chunk scores diverged cleanly (0.14 vs 0.89).",
                        "flags": ["uncertain_authorship_band", "chunk_disagreement"],
                    },
                }
            },
            "operating_conditions": {"face_detected": True, "audio_present": False},
            "description": "Edge case: hybrid long document with chunk disagreement cleanly held in UNCERTAIN.",
        }
    )

    TEXT_FIXTURES_OUT.parent.mkdir(parents=True, exist_ok=True)
    TEXT_FIXTURES_OUT.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    print(f"[*] Saved {len(cases)} Text judge cases to {TEXT_FIXTURES_OUT}")
    return cases


def build_image_suite() -> List[Dict[str, Any]]:
    """
    Constructs 20 Image & Multimodal Image+Text Judge cases grounded empirically in
    `eval/reports/image_detector_baseline.md` (CommFor Real=0.082 avg / 96%, GAN=0.941 / 98%,
    Diffusion=0.887 / 91%) and `detectors/image/app.py` / `detectors/text-detector/app.py`.
    """
    def img_resp(job_id: str, conf: float, flags: List[str], status: str = "ok", claim: str = "") -> Dict[str, Any]:
        return {
            "job_id": job_id,
            "status": status,
            "modality": "image",
            "confidence": conf,
            "raw_score": conf,
            "latency_ms": 40,
            "model_version": "commfor-model-384-fp16",
            "evidence": {
                "claim": claim or f"CommFor image detector confidence={conf:.4f}.",
                "flags": flags,
            },
        }

    def txt_resp(job_id: str, conf: float, flags: List[str], status: str = "ok") -> Dict[str, Any]:
        return {
            "job_id": job_id,
            "status": status,
            "modality": "text",
            "confidence": conf,
            "raw_score": conf,
            "latency_ms": 55,
            "model_version": "desklib-v1.01-fp16",
            "evidence": {
                "claim": f"Desklib caption authenticity confidence={conf:.4f}.",
                "flags": flags,
            },
        }

    specs = [
        # 5 Clean photographic real (camera EXIF intact)
        ("img-case-001", "flickr_real_001.jpg", "clean_real_photo", "real", ["AUTHENTIC"],
         {"detector_image": img_resp("img-case-001", 0.045, [])}, "Clean real camera photo with valid EXIF."),
        ("img-case-002", "flickr_real_002.jpg", "clean_real_photo", "real", ["AUTHENTIC"],
         {"detector_image": img_resp("img-case-002", 0.082, [])}, "Clean real baseline mean confidence photo."),
        ("img-case-003", "portrait_real_003.png", "clean_real_photo", "real", ["AUTHENTIC"],
         {"detector_image": img_resp("img-case-003", 0.115, [])}, "Clean studio portrait with camera EXIF."),
        ("img-case-004", "street_real_004.jpg", "clean_real_photo", "real", ["AUTHENTIC"],
         {"detector_image": img_resp("img-case-004", 0.142, [])}, "Outdoor authentic photo with valid EXIF."),
        ("img-case-005", "raw_camera_005.dng.jpg", "clean_real_photo", "real", ["AUTHENTIC"],
         {"detector_image": img_resp("img-case-005", 0.064, [])}, "High-detail authentic scene."),

        # 3 Social-media stripped-EXIF real images (tests exif_missing non-dispositive handling)
        ("img-case-006", "whatsapp_reupload_006.jpg", "social_reencoded_exif_missing", "real", ["AUTHENTIC"],
         {"detector_image": img_resp("img-case-006", 0.19, ["exif_missing"])},
         "WhatsApp re-encoded real photo: exif_missing alone must not inflate synthetic risk."),
        ("img-case-007", "instagram_crop_007.jpg", "social_reencoded_exif_missing", "real", ["AUTHENTIC"],
         {"detector_image": img_resp("img-case-007", 0.27, ["exif_missing"])},
         "Social upload stripped EXIF with authentic spatial features."),
        ("img-case-008", "x_compressed_008.jpg", "social_reencoded_borderline", "real", ["UNCERTAIN", "AUTHENTIC"],
         {"detector_image": img_resp("img-case-008", 0.43, ["exif_missing"])},
         "Heavily cropped social upload without EXIF in borderline zone -> safely UNCERTAIN (never SYNTHETIC)."),

        # 4 GAN images (StyleGAN2 / ProGAN + FFT artifacts)
        ("img-case-009", "stylegan2_face_009.png", "gan_synthetic", "fake", ["SYNTHETIC"],
         {"detector_image": img_resp("img-case-009", 0.962, ["frequency_anomaly", "exif_missing", "high_confidence_synthetic"])},
         "StyleGAN2 synthesis with strong ViT and FFT checkerboard periodicity."),
        ("img-case-010", "progan_lsun_010.png", "gan_synthetic", "fake", ["SYNTHETIC"],
         {"detector_image": img_resp("img-case-010", 0.941, ["frequency_anomaly", "high_confidence_synthetic"])},
         "ProGAN empirical mean confidence synthetic sample."),
        ("img-case-011", "stargan_edit_011.jpg", "gan_synthetic", "fake", ["SYNTHETIC"],
         {"detector_image": img_resp("img-case-011", 0.884, ["frequency_anomaly", "exif_missing"])},
         "StarGAN facial attribute synthesis."),
        ("img-case-012", "biggan_scene_012.png", "gan_synthetic", "fake", ["SYNTHETIC"],
         {"detector_image": img_resp("img-case-012", 0.795, ["frequency_anomaly"])},
         "BigGAN scene synthesis with upsampling artifacts."),

        # 3 Diffusion images (Midjourney / SDXL, including 2 borderline ViT rescued via Rule 8 FFT/software_tag!)
        ("img-case-013", "sdxl_portrait_013.png", "diffusion_synthetic", "fake", ["SYNTHETIC"],
         {"detector_image": img_resp("img-case-013", 0.887, ["software_tag_present", "exif_missing"])},
         "SDXL generation with generator metadata signature."),
        ("img-case-014", "midjourney_v6_014.png", "diffusion_borderline_rule8", "fake", ["SYNTHETIC"],
         {"detector_image": img_resp("img-case-014", 0.59, ["frequency_anomaly", "borderline"])},
         "Rule 8: Borderline Midjourney ViT (0.59) corroborated by FFT anomaly -> resolved to SYNTHETIC."),
        ("img-case-015", "flux_recompressed_015.png", "diffusion_borderline_rule8", "fake", ["SYNTHETIC"],
         {"detector_image": img_resp("img-case-015", 0.57, ["frequency_anomaly", "software_tag_present", "borderline"])},
         "Rule 8: Borderline Flux diffusion (0.57) corroborated by FFT + software tag -> SYNTHETIC."),

        # 1 Low-res degraded image
        ("img-case-016", "thumbnail_tiny_016.jpg", "low_resolution_degraded", "real", ["UNCERTAIN"],
         {"detector_image": img_resp("img-case-016", 0.44, ["low_resolution", "heavy_compression", "exif_missing"])},
         "Severely downsampled thumbnail lacks reliable spatial frequencies -> UNCERTAIN."),

        # 1 Corrupt / unparseable image
        ("img-case-017", "corrupt_payload_017.bin", "unparseable_not_applicable", "real", ["INTEGRITY_UNKNOWN"],
         {"detector_image": img_resp("img-case-017", 0.50, ["not_applicable"], status="not_applicable",
                                     claim="Cannot decode image bytes; detector returned not_applicable.")},
         "Corrupt/unparseable image payload -> INTEGRITY_UNKNOWN."),

        # 3 Multimodal Image + Text paired verification cases
        ("img-case-018", "news_real_pair_018.json", "multimodal_image_text_real", "real", ["AUTHENTIC"],
         {"detector_image": img_resp("img-case-018", 0.09, []),
          "detector_text": txt_resp("img-case-018", 0.07, ["high_perplexity", "natural_burstiness"])},
         "Genuine news post: authentic photo + human-written article -> AUTHENTIC."),
        ("img-case-019", "disinfo_pair_rule8_019.json", "multimodal_image_text_fake", "fake", ["SYNTHETIC"],
         {"detector_image": img_resp("img-case-019", 0.62, ["frequency_anomaly", "exif_missing"]),
          "detector_text": txt_resp("img-case-019", 0.63, ["low_perplexity", "low_burstiness", "binoculars_corroborated"])},
         "Coordinated AI disinfo: both image (Rule 8 FFT) and text (Rule 8 Binoculars+PPL) corroborate SYNTHETIC."),
        ("img-case-020", "synth_meme_human_caption_020.json", "multimodal_image_text_fake", "fake", ["SYNTHETIC", "UNCERTAIN"],
         {"detector_image": img_resp("img-case-020", 0.93, ["frequency_anomaly", "high_confidence_synthetic"]),
          "detector_text": txt_resp("img-case-020", 0.28, ["short_text_attenuated"])},
         "Synthetic generated image paired with short authentic human caption: manifest weights full primary image (1.5x) over short text (0.65x)."),
    ]

    cases: List[Dict[str, Any]] = []
    for cid, fname, cat, lbl, allowed, raws, desc in specs:
        cases.append(
            {
                "case_id": cid,
                "modality": "multimodal_image_text" if "detector_text" in raws else "image",
                "filename": fname,
                "category": cat,
                "true_label": lbl,
                "baseline_single_score": float(raws["detector_image"]["confidence"]),
                "expected_allowed_verdicts": allowed,
                "raw_responses": raws,
                "operating_conditions": {
                    "duration_seconds": None,
                    "mean_luminance": None,
                    "face_detected": True,
                    "audio_present": False,
                },
                "description": desc,
            }
        )

    IMAGE_FIXTURES_OUT.parent.mkdir(parents=True, exist_ok=True)
    IMAGE_FIXTURES_OUT.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    print(f"[*] Saved {len(cases)} Image & Image+Text judge cases to {IMAGE_FIXTURES_OUT}")
    return cases


def main() -> int:
    build_text_suite_and_calibrator()
    build_image_suite()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
