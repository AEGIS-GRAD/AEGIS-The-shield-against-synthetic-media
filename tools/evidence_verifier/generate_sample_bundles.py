#!/usr/bin/env python3
"""
Generate Genuine & Tampered Sample Evidence Bundles for Independent Verification Demo
====================================================================================
Produces 11 lightweight, deterministic sample ZIP bundles in
`tools/evidence_verifier/sample_bundles/` covering:
  - 6 Genuine Bundles: video, audio, image, text, multimodal, and live_surveillance alert
  - 5 Tampered Bundles: verdict_flip, payload_swap, report_markdown, forged_signature,
    and missing_signature

Usage:
    python tools/evidence_verifier/generate_sample_bundles.py
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from security.forensics.evidence_vault import UnifiedEvidenceVault  # noqa: E402

SAMPLE_DIR = _THIS_DIR / "sample_bundles"


def _rewrite_zip(src_zip: Path, dst_zip: Path, mutator) -> None:
    with zipfile.ZipFile(src_zip, "r") as zin:
        entries = {info.filename: zin.read(info.filename) for info in zin.infolist() if not info.is_dir()}
    mutator(entries)
    with zipfile.ZipFile(dst_zip, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries.items():
            zout.writestr(name, data)


def _sample_transcript(modality: str, verdict: str, summary_note: str) -> Dict[str, Any]:
    return {
        "judge_mode": "expert_deterministic_judge",
        "prompt_version": "judge-prompt-v2.1",
        "llm_model": None,
        "llm_fallback_used": False,
        "debate_transcript_hash": hashlib.sha256(f"{modality}:{verdict}:{summary_note}".encode()).hexdigest(),
        "guards_applied": ["G1_CONFLICT_CHECK", "G2B_SECONDARY_PROXY_CAP"],
        "forensic_justification": summary_note,
        "cross_examination_findings": [
            {
                "detector_id": "primary",
                "check_category": "manifest_constraints",
                "severity": "INFO",
                "finding": f"Verified operating conditions for {modality} modality.",
            }
        ],
        "rounds": [
            {"round_number": 1, "round_name": "Claim Submissions", "summary": f"Collected {modality} evidence claims.", "details": {}},
            {"round_number": 2, "round_name": "Cross-Examination & Context Injection", "summary": summary_note, "details": {}},
            {"round_number": 3, "round_name": "Adjudication & Forensic Ruling", "summary": f"Final verdict={verdict}.", "details": {}},
        ],
        "adjudication_latency_ms": 6.4,
    }


def generate_samples(out_dir: Path = SAMPLE_DIR) -> List[Dict[str, str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Remove old generated zips so stale artifacts do not linger
    for old_zip in out_dir.glob("*.zip"):
        old_zip.unlink()

    manifest_rows: List[Dict[str, str]] = []

    with tempfile.TemporaryDirectory(prefix="aegis_sample_gen_") as tmp:
        vault = UnifiedEvidenceVault(vault_dir=Path(tmp) / "vault")

        specs = [
            {
                "filename_zip": "genuine_video_bundle.zip",
                "job_id": "demo-video-001",
                "modality": "video",
                "input_filename": "spokesperson_briefing.mp4",
                "payload": b"\x00\x00\x00\x18ftypmp42_AEGIS_DEMO_VIDEO_SAMPLE_CLIP_BYTES",
                "verdict": "SYNTHETIC",
                "score": 0.9140,
                "siem_tier": "P1_CRITICAL",
                "detectors": [
                    {"detector": "video-classifier", "status": "ok", "confidence": 0.94, "raw_score": 0.94, "latency_ms": 1380},
                    {"detector": "syncnet", "status": "ok", "confidence": 0.88, "raw_score": 0.88, "latency_ms": 920},
                    {"detector": "rppg", "status": "ok", "confidence": 0.19, "raw_score": 0.19, "latency_ms": 610},
                ],
                "model_versions": {"video-classifier": "efficientnet-b0-df40-v1", "syncnet": "syncnet-v1.3", "rppg": "chrom-v1.2"},
                "note": "Precedence Rule 3 applied: facial synthesis & lip-desync override donor rPPG pulse.",
            },
            {
                "filename_zip": "genuine_audio_bundle.zip",
                "job_id": "demo-audio-002",
                "modality": "audio",
                "input_filename": "executive_voicemail.wav",
                "payload": b"RIFF\x24\x00\x00\x00WAVEfmt _AEGIS_DEMO_AUDIO_SAMPLE_BYTES",
                "verdict": "SYNTHETIC",
                "score": 0.8820,
                "siem_tier": "P1_CRITICAL",
                "detectors": [
                    {"detector": "aasist", "status": "ok", "confidence": 0.89, "raw_score": 0.89, "latency_ms": 215},
                ],
                "model_versions": {"aasist": "aasist-sincnet-v1.3"},
                "note": "AASIST spectro-temporal graph attention detected neural voice cloning artifacts.",
            },
            {
                "filename_zip": "genuine_image_bundle.zip",
                "job_id": "demo-image-003",
                "modality": "image",
                "input_filename": "press_photo.png",
                "payload": b"\x89PNG\r\n\x1a\n_AEGIS_DEMO_AUTHENTIC_IMAGE_BYTES",
                "verdict": "AUTHENTIC",
                "score": 0.1150,
                "siem_tier": "P4_INFORMATIONAL",
                "detectors": [
                    {"detector": "detector_image", "status": "ok", "confidence": 0.12, "raw_score": 0.12, "latency_ms": 110},
                ],
                "model_versions": {"detector_image": "commfor-model-384-fp16"},
                "note": "No diffusion grid or GAN upsampling anomalies detected; consistent EXIF profile.",
            },
            {
                "filename_zip": "genuine_text_bundle.zip",
                "job_id": "demo-text-004",
                "modality": "text",
                "input_filename": "statement_draft.txt",
                "payload": (
                    b"In contemporary digital ecosystems, organizations increasingly leverage automated "
                    b"compliance frameworks to streamline verification workflows and bolster operational resilience."
                ),
                "verdict": "SYNTHETIC",
                "score": 0.8650,
                "siem_tier": "P1_CRITICAL",
                "detectors": [
                    {"detector": "detector_text", "status": "ok", "confidence": 0.87, "raw_score": 0.87, "latency_ms": 185},
                ],
                "model_versions": {"detector_text": "desklib-ai-text-detector-v1.01-lora"},
                "note": "Desklib semantic classifier corroborated by uniformly low GPT-2 sentence burstiness.",
            },
            {
                "filename_zip": "genuine_multimodal_bundle.zip",
                "job_id": "demo-multi-005",
                "modality": "multimodal",
                "input_filename": "broadcast_interview.mp4",
                "payload": b"\x00\x00\x00\x18ftypisom_AEGIS_DEMO_MULTIMODAL_AV_BYTES",
                "verdict": "SYNTHETIC",
                "score": 0.9280,
                "siem_tier": "P1_CRITICAL",
                "detectors": [
                    {"detector": "video-classifier", "status": "ok", "confidence": 0.93, "raw_score": 0.93, "latency_ms": 1410},
                    {"detector": "aasist", "status": "ok", "confidence": 0.91, "raw_score": 0.91, "latency_ms": 230},
                    {"detector": "syncnet", "status": "ok", "confidence": 0.86, "raw_score": 0.86, "latency_ms": 910},
                    {"detector": "rppg", "status": "ok", "confidence": 0.76, "raw_score": 0.76, "latency_ms": 640},
                ],
                "model_versions": {
                    "video-classifier": "efficientnet-b0-df40-v1",
                    "aasist": "aasist-sincnet-v1.3",
                    "syncnet": "syncnet-v1.3",
                    "rppg": "chrom-v1.2",
                },
                "note": "Cross-modal consensus across visual, acoustic, lip-sync, and physiological channels.",
            },
        ]

        video_zip_path = out_dir / "genuine_video_bundle.zip"
        for sp in specs:
            vault.store_verification(
                job_id=sp["job_id"],
                modality=sp["modality"],
                input_filename=sp["input_filename"],
                input_bytes=sp["payload"],
                verdict=sp["verdict"],
                calibrated_score=sp["score"],
                detector_outputs=sp["detectors"],
                model_versions=sp["model_versions"],
                calibration_version="aegis-calibrator-v2.0",
                judge_transcript=_sample_transcript(sp["modality"], sp["verdict"], sp["note"]),
                siem_alert_tier=sp["siem_tier"],
            )
            dst = out_dir / sp["filename_zip"]
            vault.export_signed_bundle(sp["job_id"], output_zip_path=dst)
            manifest_rows.append(
                {
                    "file": sp["filename_zip"],
                    "expected": "PASS",
                    "modality": sp["modality"],
                    "description": f"Genuine signed {sp['modality']} bundle ({sp['verdict']}, score={sp['score']:.2f}).",
                }
            )

        # 6th genuine bundle: Live surveillance incident alert
        inc = vault.store_incident(
            camera_id="cam-lobby-mtls-01",
            threat_type="HASH_CHAIN_BREAK",
            severity="CRITICAL",
            sequence_number=421,
            timestamp_ms=1795550000123,
            primary_frame_bytes=b"\x89PNG\r\n\x1a\n_AEGIS_DEMO_LIVE_ALERT_FRAME_421",
            reasoning_narrative="Frame hash-chain continuity broken between seq 420 and 421 over mTLS ingestion.",
            telemetry={"prnu_pce": 14.2, "expected_chain": "8a91...", "received_chain": "deadbeef..."},
        )
        live_zip = out_dir / "genuine_live_alert_bundle.zip"
        vault.export_signed_bundle(inc.incident_id, output_zip_path=live_zip)
        manifest_rows.append(
            {
                "file": "genuine_live_alert_bundle.zip",
                "expected": "PASS",
                "modality": "live_surveillance",
                "description": "Genuine signed live surveillance HASH_CHAIN_BREAK incident bundle.",
            }
        )

        # ── Build 5 Tampered Demo Bundles from genuine_video_bundle.zip ──────
        # T1: Verdict Flip inside evidence.json
        def _tamper_verdict(entries: Dict[str, bytes]) -> None:
            doc = json.loads(entries["evidence.json"].decode("utf-8"))
            doc["verdict"] = "AUTHENTIC"
            entries["evidence.json"] = json.dumps(doc, indent=2, sort_keys=True).encode("utf-8")

        _rewrite_zip(video_zip_path, out_dir / "tampered_verdict_flip.zip", _tamper_verdict)
        manifest_rows.append(
            {
                "file": "tampered_verdict_flip.zip",
                "expected": "FAIL",
                "modality": "video",
                "description": "evidence.json modified (`SYNTHETIC` -> `AUTHENTIC`) without valid hashes/signatures.",
            }
        )

        # T2: Payload byte modification inside payload/
        def _tamper_payload(entries: Dict[str, bytes]) -> None:
            pkey = next(k for k in entries if k.startswith("payload/"))
            entries[pkey] = entries[pkey][:-5] + b"SPOOF"

        _rewrite_zip(video_zip_path, out_dir / "tampered_payload_swap.zip", _tamper_payload)
        manifest_rows.append(
            {
                "file": "tampered_payload_swap.zip",
                "expected": "FAIL",
                "modality": "video",
                "description": "Raw media file inside payload/ mutated by 5 bytes.",
            }
        )

        # T3: Narrative report modification inside report.md
        def _tamper_report(entries: Dict[str, bytes]) -> None:
            md = entries["report.md"].decode("utf-8").replace("SYNTHETIC", "AUTHENTIC")
            entries["report.md"] = md.encode("utf-8")

        _rewrite_zip(video_zip_path, out_dir / "tampered_report_markdown.zip", _tamper_report)
        manifest_rows.append(
            {
                "file": "tampered_report_markdown.zip",
                "expected": "FAIL",
                "modality": "video",
                "description": "Human-readable report.md altered while JSON & payload remain untouched.",
            }
        )

        # T4: Attacker modifies verdict AND recomputes hashes.sha256, but signs with forged key
        def _tamper_forged_sig(entries: Dict[str, bytes]) -> None:
            doc = json.loads(entries["evidence.json"].decode("utf-8"))
            doc["verdict"] = "AUTHENTIC"
            new_ev = json.dumps(doc, indent=2, sort_keys=True).encode("utf-8")
            entries["evidence.json"] = new_ev
            pkey = next(k for k in entries if k.startswith("payload/"))
            new_hashes = (
                f"{hashlib.sha256(new_ev).hexdigest()}  evidence.json\n"
                f"{hashlib.sha256(entries['report.md']).hexdigest()}  report.md\n"
                f"{hashlib.sha256(entries[pkey]).hexdigest()}  {pkey}\n"
            ).encode("utf-8")
            entries["hashes.sha256"] = new_hashes
            h_sha = hashlib.sha256(new_hashes).hexdigest()
            e_sha = hashlib.sha256(new_ev).hexdigest()
            forged_sig = hmac.new(b"attacker_forged_key", f"{h_sha}:{e_sha}".encode("utf-8"), hashlib.sha256).hexdigest()
            sig_doc = json.loads(entries["bundle_signature.sig"].decode("utf-8"))
            sig_doc["hashes_sha256"] = h_sha
            sig_doc["evidence_sha256"] = e_sha
            sig_doc["signature"] = forged_sig
            entries["bundle_signature.sig"] = json.dumps(sig_doc, indent=2).encode("utf-8")

        _rewrite_zip(video_zip_path, out_dir / "tampered_forged_signature.zip", _tamper_forged_sig)
        manifest_rows.append(
            {
                "file": "tampered_forged_signature.zip",
                "expected": "FAIL",
                "modality": "video",
                "description": "evidence.json + hashes.sha256 recomputed, but bundle_signature.sig signed with attacker key.",
            }
        )

        # T5: Signature file stripped from archive
        def _tamper_missing_sig(entries: Dict[str, bytes]) -> None:
            entries.pop("bundle_signature.sig", None)

        _rewrite_zip(video_zip_path, out_dir / "tampered_missing_signature.zip", _tamper_missing_sig)
        manifest_rows.append(
            {
                "file": "tampered_missing_signature.zip",
                "expected": "FAIL",
                "modality": "video",
                "description": "Required cryptographic signature file `bundle_signature.sig` removed.",
            }
        )

    # Write human-readable manifest
    lines = [
        "# Sample Forensic Evidence Bundles (Genuine & Tampered)",
        "",
        "Verify all bundles offline with zero dependencies using:",
        "```bash",
        "python tools/evidence_verifier/aegis_verify.py tools/evidence_verifier/sample_bundles/ --verbose",
        "```",
        "",
        "| Bundle File | Expected | Modality | Scenario / Attack Demonstrated |",
        "|---|---|---|---|",
    ]
    for r in manifest_rows:
        lines.append(f"| `{r['file']}` | **{r['expected']}** | `{r['modality']}` | {r['description']} |")
    (out_dir / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_rows


if __name__ == "__main__":
    rows = generate_samples()
    print(f"Generated {len(rows)} sample bundles in {SAMPLE_DIR}")
