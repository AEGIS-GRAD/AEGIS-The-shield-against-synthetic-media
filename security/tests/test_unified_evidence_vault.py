"""
End-to-End Test Suite for AEGIS Unified Evidence Vault & Offline Bundle Verifier.
Verifies tamper-evident storage, signed evidence bundle export, and standalone
offline verification across all 5 modalities (video, audio, image, text, multimodal)
plus live surveillance alerts.
"""

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from security.forensics.evidence_vault import UnifiedEvidenceVault
from security.forensics.verify_bundle import verify_bundle


FIVE_MODALITIES = [
    {
        "modality": "video",
        "filename": "sample_clip.mp4",
        "payload": b"\x00\x00\x00\x18ftypmp42_fake_video_bytes_for_vault_test",
        "verdict": "SYNTHETIC",
        "score": 0.91,
        "detectors": [
            {"detector": "video-classifier", "status": "ok", "confidence": 0.92, "raw_score": 0.91, "latency_ms": 1450},
        ],
        "model_versions": {"video-classifier": "xception-v2.1"},
    },
    {
        "modality": "audio",
        "filename": "voice_memo.wav",
        "payload": b"RIFF\x24\x00\x00\x00WAVEfmt _fake_audio_bytes",
        "verdict": "SYNTHETIC",
        "score": 0.87,
        "detectors": [
            {"detector": "aasist", "status": "ok", "confidence": 0.89, "raw_score": 0.87, "latency_ms": 220},
        ],
        "model_versions": {"aasist": "aasist-sincnet-v1.3"},
    },
    {
        "modality": "image",
        "filename": "portrait.png",
        "payload": b"\x89PNG\r\n\x1a\n_fake_image_bytes_mirror_dinov3",
        "verdict": "AUTHENTIC",
        "score": 0.14,
        "detectors": [
            {"detector": "detector_image", "status": "ok", "confidence": 0.86, "raw_score": 0.14, "latency_ms": 95},
        ],
        "model_versions": {"detector_image": "mirror-dinov3-v1"},
    },
    {
        "modality": "text",
        "filename": "article.txt",
        "payload": b"Generated synthetic text sample evaluated by DeskLib and Binoculars.",
        "verdict": "SYNTHETIC",
        "score": 0.83,
        "detectors": [
            {"detector": "detector_text", "status": "ok", "confidence": 0.84, "raw_score": 0.83, "latency_ms": 180},
        ],
        "model_versions": {"detector_text": "desklib-lora-v2"},
    },
    {
        "modality": "multimodal",
        "filename": "broadcast_av.mp4",
        "payload": b"\x00\x00\x00\x18ftypisom_fake_multimodal_av_stream",
        "verdict": "SYNTHETIC",
        "score": 0.94,
        "detectors": [
            {"detector": "video-classifier", "status": "ok", "confidence": 0.93, "raw_score": 0.92, "latency_ms": 1200},
            {"detector": "rppg", "status": "ok", "confidence": 0.88, "raw_score": 0.89, "latency_ms": 980},
            {"detector": "syncnet", "status": "ok", "confidence": 0.95, "raw_score": 0.96, "latency_ms": 1640},
            {"detector": "aasist", "status": "ok", "confidence": 0.90, "raw_score": 0.91, "latency_ms": 210},
        ],
        "model_versions": {
            "video-classifier": "xception-v2.1",
            "rppg": "physnet-rppg-v1.0",
            "syncnet": "syncnet-av-v1.2",
            "aasist": "aasist-sincnet-v1.3",
        },
    },
]


def _make_sample_transcript(modality: str, verdict: str) -> dict:
    return {
        "judge_mode": "expert_deterministic_judge",
        "prompt_version": "judge-v2.1",
        "llm_model": None,
        "llm_fallback_used": False,
        "debate_transcript_hash": "a" * 64,
        "guards_applied": ["G1_INTEGRITY_PRECEDENCE"],
        "forensic_justification": f"Calibrated {modality} adjudication resulted in {verdict}.",
        "cross_examination_findings": [],
        "rounds": [
            {"round_number": 1, "round_name": "Claim Submission", "summary": "All claims ingested.", "details": {}},
            {"round_number": 2, "round_name": "Cross-Examination", "summary": "No fatal contradictions.", "details": {}},
            {"round_number": 3, "round_name": "Final Adjudication", "summary": f"Verdict={verdict}.", "details": {}},
        ],
        "adjudication_latency_ms": 4.2,
    }


def test_five_modalities_and_live_alert_offline_verification(tmp_path: Path):
    vault = UnifiedEvidenceVault(vault_dir=tmp_path / "vault")
    verify_script = _REPO_ROOT / "security" / "forensics" / "verify_bundle.py"

    # 1. Store & verify all 5 file/multimodal modalities
    for idx, spec in enumerate(FIVE_MODALITIES, start=1):
        job_id = f"job-{spec['modality']}-{idx:04d}"
        rec = vault.store_verification(
            job_id=job_id,
            modality=spec["modality"],
            input_filename=spec["filename"],
            input_bytes=spec["payload"],
            verdict=spec["verdict"],
            calibrated_score=spec["score"],
            detector_outputs=spec["detectors"],
            model_versions=spec["model_versions"],
            calibration_version="aegis-calibrator-v2.0",
            judge_transcript=_make_sample_transcript(spec["modality"], spec["verdict"]),
            siem_alert_tier="P1_CRITICAL" if spec["verdict"] == "SYNTHETIC" else "P4_INFORMATIONAL",
        )

        # Export signed bundle by job_id
        bundle_zip = vault.export_signed_bundle(
            job_id,
            output_zip_path=tmp_path / "exports" / f"{spec['modality']}_bundle.zip",
        )
        assert bundle_zip.exists()

        # Verify offline via Python API
        ok, msg = verify_bundle(bundle_zip)
        assert ok, f"Offline verify failed for {spec['modality']}: {msg}"

        # Verify offline via standalone CLI script
        proc = subprocess.run(
            [sys.executable, str(verify_script), str(bundle_zip)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"CLI verify failed for {spec['modality']}: {proc.stdout}\n{proc.stderr}"
        assert "[PASS]" in proc.stdout

    # 2. Store & export a live surveillance alert in the same vault
    inc = vault.store_incident(
        camera_id="camera-001",
        threat_type="HASH_CHAIN_BREAK",
        sequence_number=42,
        timestamp_ms=1700000000000,
        primary_frame_bytes=b"\x89PNG\r\n\x1a\n_live_frame_bytes",
        telemetry={"expected_hash": "abc", "calculated_hash": "def"},
        reasoning_narrative="Cryptographic frame chain broken at seq #42.",
        severity="CRITICAL",
    )
    live_bundle = vault.export_signed_bundle(
        inc.incident_id,
        output_zip_path=tmp_path / "exports" / "live_alert_bundle.zip",
    )
    ok_live, msg_live = verify_bundle(live_bundle)
    assert ok_live, f"Offline verify failed for live alert: {msg_live}"

    # 3. Entire mixed vault ledger integrity audit must pass
    audit = vault.verify_vault_integrity()
    assert audit.is_valid, f"Vault audit failed: {audit.errors}"
    assert audit.total_records == 6
    assert audit.verified_records == 6


def test_tampered_bundle_rejected_offline(tmp_path: Path):
    vault = UnifiedEvidenceVault(vault_dir=tmp_path / "vault")
    rec = vault.store_verification(
        job_id="job-tamper-test",
        modality="image",
        input_filename="test.png",
        input_bytes=b"original-image-bytes",
        verdict="SYNTHETIC",
        calibrated_score=0.95,
        detector_outputs=[{"detector": "detector_image", "status": "ok", "raw_score": 0.95}],
        model_versions={"detector_image": "mirror-dinov3-v1"},
        calibration_version="aegis-calibrator-v2.0",
        judge_transcript=_make_sample_transcript("image", "SYNTHETIC"),
    )
    bundle_zip = vault.export_signed_bundle(rec.verification_id, output_zip_path=tmp_path / "clean.zip")

    # Extract and tamper with evidence.json (flip verdict)
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(bundle_zip, "r") as zf:
        zf.extractall(extracted)

    ev_path = extracted / "evidence.json"
    ev_data = json.loads(ev_path.read_text(encoding="utf-8"))
    ev_data["verdict"] = "AUTHENTIC"
    ev_path.write_text(json.dumps(ev_data, indent=2), encoding="utf-8")

    ok, msg = verify_bundle(extracted)
    assert not ok
    assert "[FAIL]" in msg
