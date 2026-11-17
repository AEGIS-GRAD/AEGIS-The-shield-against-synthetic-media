"""
test_reliability_feedback_loop.py — Production validation & tests for Task 5
=============================================================================
Covers:
  1. Condition tagging (low_light, short_clip, dubbed_audio, nominal, image/text exclusion)
  2. Overrule detection + post-hoc ground-truth confirmation
  3. Rolling-window statistics, cold-start min_samples guard, recovery, condition isolation
  4. Schema-validated atomic manifest write-back & manifest text rendering
  5. Planner deprioritization, cache invalidation on manifest revision change,
     live-LLM post-check guard, and sole-detector safety invariant
  6. FastAPI end-to-end flow: /orchestrate -> POST /feedback/{job_id} -> GET /reliability/summary
     including prod-mode X-API-Key enforcement and error paths (404 / 422).
"""

from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ORCH_APP = _REPO_ROOT / "orchestrator" / "app"
_MANIFESTS_SRC = _REPO_ROOT / "capability_manifests"

for _p in (str(_REPO_ROOT), str(_ORCH_APP)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import db as orch_db  # noqa: E402
import main as orch_main  # noqa: E402
from eligibility import compute_deprioritization_map  # noqa: E402
from manifest_loader import load_manifest, render_manifest_text, validate_manifest  # noqa: E402
from models import DetectorEvidence, DetectorResult, InputMetadata  # noqa: E402
from planner import clear_plan_cache, plan_detectors  # noqa: E402
from prompt_builder import build_planning_prompt  # noqa: E402
from reliability_feedback import (  # noqa: E402
    ReliabilityConfig,
    ReliabilityFeedbackEngine,
    compute_rolling_reliability,
    extract_condition_tags,
    extract_condition_tags_from_input,
    write_reliability_to_manifests,
)


@pytest.fixture()
def isolated_manifests(tmp_path: Path) -> Path:
    mdir = tmp_path / "manifests"
    mdir.mkdir(parents=True, exist_ok=True)
    for p in _MANIFESTS_SRC.glob("*.json"):
        shutil.copy2(p, mdir / p.name)
    return mdir


@pytest.fixture()
def isolated_db(tmp_path: Path):
    db_path = tmp_path / "test_feedback.db"
    eng = create_engine(f"sqlite:///{db_path}", echo=False)
    orch_db.init_db(target_engine=eng)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    try:
        yield factory
    finally:
        eng.dispose()


# ---------------------------------------------------------------------------
# 1. Condition Tagging
# ---------------------------------------------------------------------------

def test_extract_condition_tags_from_input_variants():
    low_dark = InputMetadata(
        filename="dark.mp4", modality="video", has_audio=True, duration_seconds=8.0, mean_luminance=24.0
    )
    assert extract_condition_tags_from_input(low_dark) == ["low_light"]

    short_vid = InputMetadata(
        filename="short.mp4", modality="video", has_audio=False, duration_seconds=3.1, mean_luminance=110.0
    )
    assert extract_condition_tags_from_input(short_vid) == ["short_clip"]

    dubbed = InputMetadata(
        filename="dub.mp4",
        modality="video",
        has_audio=True,
        duration_seconds=9.0,
        mean_luminance=120.0,
        metadata_tags={"audio_language": "es", "video_language": "en"},
    )
    assert extract_condition_tags_from_input(dubbed) == ["dubbed_audio"]

    # Images and text have duration_seconds=0.0 and must NOT be tagged short_clip
    img = InputMetadata(filename="photo.jpg", modality="image", has_audio=False, duration_seconds=0.0)
    assert extract_condition_tags_from_input(img) == ["nominal"]

    # Multi-condition video
    multi = InputMetadata(
        filename="multi.mp4", modality="video", has_audio=True, duration_seconds=2.5, mean_luminance=19.0
    )
    assert extract_condition_tags_from_input(multi) == ["low_light", "short_clip"]


def test_extract_condition_tags_enriches_from_detector_flags():
    meta = InputMetadata(filename="clip.mp4", modality="video", has_audio=True, duration_seconds=8.0)
    res = [
        DetectorResult(
            detector="syncnet",
            status="ok",
            confidence=0.82,
            raw_score=0.82,
            evidence=DetectorEvidence(claim="Lip offset", flags=["foreign_dubbing_risk"]),
        )
    ]
    assert extract_condition_tags(meta, raw_results=res) == ["dubbed_audio"]


# ---------------------------------------------------------------------------
# 2. Rolling Reliability, Cold-Start Guard, Recovery & Condition Isolation
# ---------------------------------------------------------------------------

def test_rolling_reliability_cold_start_deprioritization_and_recovery():
    cfg = ReliabilityConfig(window_size=10, min_samples=5, deprioritize_threshold=0.55)

    # Below min_samples (4 wrong) -> insufficient_data, NOT deprioritized
    early_rows = [
        {
            "detector_name": "rppg",
            "condition_tags": ["low_light"],
            "detector_was_wrong": True,
            "overruled_by_judge": True,
            "confirmed_overrule": True,
            "confirmed_at": f"2026-11-17T00:0{i}:00Z",
        }
        for i in range(4)
    ]
    summary_early = compute_rolling_reliability(early_rows, config=cfg)
    assert summary_early["rppg"]["by_condition"]["low_light"]["status"] == "insufficient_data"

    # Add 6 more wrong in low_light -> window=10, all wrong -> deprioritize
    # Also add 6 correct in nominal -> nominal stays reliable (condition isolation)
    more_rows = early_rows + [
        {
            "detector_name": "rppg",
            "condition_tags": ["low_light"],
            "detector_was_wrong": True,
            "overruled_by_judge": True,
            "confirmed_overrule": True,
            "confirmed_at": f"2026-11-17T00:1{i}:00Z",
        }
        for i in range(6)
    ] + [
        {
            "detector_name": "rppg",
            "condition_tags": ["nominal"],
            "detector_was_wrong": False,
            "overruled_by_judge": False,
            "confirmed_overrule": False,
            "confirmed_at": f"2026-11-17T00:2{i}:00Z",
        }
        for i in range(6)
    ]
    summary_mid = compute_rolling_reliability(more_rows, config=cfg)
    low_entry = summary_mid["rppg"]["by_condition"]["low_light"]
    nom_entry = summary_mid["rppg"]["by_condition"]["nominal"]
    assert low_entry["status"] == "deprioritize"
    assert low_entry["confirmed_overrule_count"] == 10
    assert low_entry["rolling_reliability"] < 0.30
    assert nom_entry["status"] == "reliable"

    # Recovery: 10 consecutive accurate low_light samples push old failures out of window=10
    recovered_rows = more_rows + [
        {
            "detector_name": "rppg",
            "condition_tags": ["low_light"],
            "detector_was_wrong": False,
            "overruled_by_judge": False,
            "confirmed_overrule": False,
            "confirmed_at": f"2026-11-17T01:0{i}:00Z",
        }
        for i in range(10)
    ]
    summary_rec = compute_rolling_reliability(recovered_rows, config=cfg)
    assert summary_rec["rppg"]["by_condition"]["low_light"]["status"] == "reliable"


def test_inconclusive_claims_excluded_from_accuracy_denominator(isolated_db, isolated_manifests):
    engine = ReliabilityFeedbackEngine(manifests_dir=isolated_manifests, session_factory=isolated_db)
    orch_db.log_claim_outcomes(
        [
            {
                "job_id": "job-inc",
                "detector_name": "syncnet",
                "modality": "video",
                "condition_tags": ["low_light"],
                "original_polarity": "NOT_APPLICABLE",
                "original_confidence": 0.5,
                "accepted_confidence": 0.5,
                "weight_assigned": 0.0,
                "judge_verdict": "AUTHENTIC",
                "overruled_by_judge": False,
            }
        ],
        session_factory=isolated_db,
    )
    res = engine.confirm_and_update("job-inc", "AUTHENTIC", apply_to_manifests=False)
    assert res["updated_claims"][0]["detector_was_wrong"] is None
    assert res["reliability_summary"] == {}


# ---------------------------------------------------------------------------
# 3. Manifest Write-Back, Schema Validation & Text Rendering
# ---------------------------------------------------------------------------

def test_manifest_writeback_validates_and_increments_revision(isolated_manifests: Path):
    payload = {
        "rppg": {
            "updated_at": "2026-11-17T12:00:00Z",
            "window_size": 50,
            "overall": {"sample_count": 10, "rolling_reliability": 0.35, "status": "deprioritize"},
            "by_condition": {
                "low_light": {
                    "sample_count": 10,
                    "correct_count": 1,
                    "wrong_count": 9,
                    "overruled_count": 9,
                    "confirmed_overrule_count": 9,
                    "raw_accuracy": 0.1,
                    "rolling_reliability": 0.2857,
                    "confirmed_overrule_rate": 0.9,
                    "status": "deprioritize",
                    "last_updated": "2026-11-17T12:00:00Z",
                }
            },
        }
    }
    updated = write_reliability_to_manifests(payload, manifests_dir=isolated_manifests)
    assert updated == ["rppg"]

    m1 = load_manifest("rppg", isolated_manifests)
    assert m1["observed_reliability"]["revision"] == 1
    assert m1["observed_reliability"]["by_condition"]["low_light"]["status"] == "deprioritize"
    validate_manifest(m1)

    rendered = render_manifest_text(m1)
    assert "observed_rel" in rendered
    assert "low_light=0.29 [deprioritize" in rendered

    # Second write increments revision
    write_reliability_to_manifests(payload, manifests_dir=isolated_manifests)
    m2 = load_manifest("rppg", isolated_manifests)
    assert m2["observed_reliability"]["revision"] == 2


def test_readonly_manifests_fall_back_to_overlay_and_merge(isolated_manifests: Path, tmp_path: Path, monkeypatch):
    overlay_dir = tmp_path / "overlay"
    monkeypatch.setenv("AEGIS_RELIABILITY_OVERLAY_DIR", str(overlay_dir))

    import reliability_feedback as rf_mod

    orig_atomic = rf_mod._atomic_write_json

    def _fail_primary_only(target_path: Path, data: dict) -> None:
        if target_path.parent == isolated_manifests:
            raise PermissionError("Read-only file system: /capability_manifests")
        orig_atomic(target_path, data)

    monkeypatch.setattr(rf_mod, "_atomic_write_json", _fail_primary_only)

    payload = {
        "rppg": {
            "updated_at": "2026-11-17T12:00:00Z",
            "window_size": 50,
            "overall": {"sample_count": 8, "rolling_reliability": 0.33, "status": "deprioritize"},
            "by_condition": {
                "low_light": {
                    "sample_count": 8,
                    "correct_count": 1,
                    "wrong_count": 7,
                    "overruled_count": 7,
                    "confirmed_overrule_count": 7,
                    "raw_accuracy": 0.125,
                    "rolling_reliability": 0.3333,
                    "confirmed_overrule_rate": 0.875,
                    "status": "deprioritize",
                    "last_updated": "2026-11-17T12:00:00Z",
                }
            },
        }
    }

    updated = write_reliability_to_manifests(payload, manifests_dir=isolated_manifests)
    assert updated == ["rppg"]
    assert (overlay_dir / "rppg.json").is_file()

    # Primary base file stayed untouched, yet load_manifest merges overlay seamlessly
    raw_base = json.loads((isolated_manifests / "rppg.json").read_text(encoding="utf-8"))
    assert "observed_reliability" not in raw_base

    loaded = load_manifest("rppg", isolated_manifests)
    assert loaded["observed_reliability"]["revision"] == 1
    assert loaded["observed_reliability"]["by_condition"]["low_light"]["status"] == "deprioritize"


# ---------------------------------------------------------------------------
# 4. Planner Deprioritization, Cache Busting, Sole-Detector Guard & Prompt
# ---------------------------------------------------------------------------

def test_planner_deprioritizes_failing_detector_and_invalidates_cache(isolated_manifests: Path):
    clear_plan_cache()
    dark_meta = InputMetadata(
        filename="night_cam.mp4",
        modality="video",
        has_audio=True,
        duration_seconds=8.0,
        mean_luminance=20.0,
        face_detected=True,
    )
    nominal_meta = InputMetadata(
        filename="day_cam.mp4",
        modality="video",
        has_audio=True,
        duration_seconds=8.0,
        mean_luminance=120.0,
        face_detected=True,
    )

    # Before feedback: rppg is scheduled in both low_light and nominal
    res_before = plan_detectors(dark_meta, mode="llm", budget_s=25.0, mock_llm=True, manifests_dir=isolated_manifests)
    assert "rppg" in res_before.detectors_to_call
    assert "video-classifier" in res_before.detectors_to_call

    # Write feedback marking rppg unreliable in low_light ONLY
    write_reliability_to_manifests(
        {
            "rppg": {
                "updated_at": "2026-11-17T12:00:00Z",
                "window_size": 50,
                "overall": {"sample_count": 12, "rolling_reliability": 0.30, "status": "deprioritize"},
                "by_condition": {
                    "low_light": {
                        "sample_count": 12,
                        "correct_count": 2,
                        "wrong_count": 10,
                        "overruled_count": 10,
                        "confirmed_overrule_count": 10,
                        "raw_accuracy": 0.1667,
                        "rolling_reliability": 0.3125,
                        "confirmed_overrule_rate": 0.8333,
                        "status": "deprioritize",
                        "last_updated": "2026-11-17T12:00:00Z",
                    },
                    "nominal": {
                        "sample_count": 12,
                        "correct_count": 10,
                        "wrong_count": 2,
                        "overruled_count": 0,
                        "confirmed_overrule_count": 0,
                        "raw_accuracy": 0.8333,
                        "rolling_reliability": 0.8125,
                        "confirmed_overrule_rate": 0.0,
                        "status": "reliable",
                        "last_updated": "2026-11-17T12:00:00Z",
                    },
                },
            }
        },
        manifests_dir=isolated_manifests,
    )

    # WITHOUT calling clear_plan_cache(), cache key must bust because manifest revision changed!
    res_after_dark = plan_detectors(dark_meta, mode="llm", budget_s=25.0, mock_llm=True, manifests_dir=isolated_manifests)
    assert "rppg" not in res_after_dark.detectors_to_call
    assert "video-classifier" in res_after_dark.detectors_to_call
    assert any(s.get("detector_name") == "rppg" for s in res_after_dark.plan["skipped"])
    assert any("rppg" in w and "low_light" in w for w in res_after_dark.plan["coverage_warnings"])

    # In nominal lighting, rppg must STILL be selected
    res_after_nominal = plan_detectors(nominal_meta, mode="llm", budget_s=25.0, mock_llm=True, manifests_dir=isolated_manifests)
    assert "rppg" in res_after_nominal.detectors_to_call

    # Prompt builder also reflects historical reliability cleanly and stays compact (< 6000 chars)
    m_vc = load_manifest("video-classifier", isolated_manifests)
    m_rppg = load_manifest("rppg", isolated_manifests)
    prompt = build_planning_prompt(
        [m_vc, m_rppg],
        [],
        {"modality": "video", "has_audio": True, "duration_seconds": 8.0, "mean_luminance": 20.0},
        "standard",
        25.0,
    )
    assert "DEPRIORITIZE under low_light" in prompt
    assert len(prompt) < 7000


def test_live_llm_post_guard_and_sole_detector_safety(isolated_manifests: Path):
    clear_plan_cache()
    write_reliability_to_manifests(
        {
            "syncnet": {
                "updated_at": "2026-11-17T12:00:00Z",
                "window_size": 50,
                "overall": {"sample_count": 10, "rolling_reliability": 0.30, "status": "deprioritize"},
                "by_condition": {
                    "dubbed_audio": {
                        "sample_count": 10,
                        "correct_count": 1,
                        "wrong_count": 9,
                        "overruled_count": 8,
                        "confirmed_overrule_count": 8,
                        "raw_accuracy": 0.1,
                        "rolling_reliability": 0.2857,
                        "confirmed_overrule_rate": 0.8,
                        "status": "deprioritize",
                        "last_updated": "2026-11-17T12:00:00Z",
                    }
                },
            },
            "aasist": {
                "updated_at": "2026-11-17T12:00:00Z",
                "window_size": 50,
                "overall": {"sample_count": 10, "rolling_reliability": 0.30, "status": "deprioritize"},
                "by_condition": {
                    "short_clip": {
                        "sample_count": 10,
                        "correct_count": 1,
                        "wrong_count": 9,
                        "overruled_count": 0,
                        "confirmed_overrule_count": 0,
                        "raw_accuracy": 0.1,
                        "rolling_reliability": 0.2857,
                        "confirmed_overrule_rate": 0.0,
                        "status": "deprioritize",
                        "last_updated": "2026-11-17T12:00:00Z",
                    }
                },
            },
        },
        manifests_dir=isolated_manifests,
    )

    # 1. Even if a live LLM outputs syncnet for dubbed_audio, post-guard prunes syncnet
    dubbed_meta = InputMetadata(
        filename="dubbed.mp4",
        modality="video",
        has_audio=True,
        duration_seconds=8.0,
        metadata_tags={"dubbed_audio": "true"},
    )
    hallucinating_llm_plan = {
        "plan_version": "3",
        "stages": [{"stage": 1, "run": ["video-classifier", "syncnet"], "mode": "parallel"}],
        "skipped": [],
        "coverage_warnings": [],
        "estimated_latency_s": 22.8,
        "rationale": "LLM picked both.",
    }
    with patch("planner.call_llm", return_value=(hallucinating_llm_plan, "mock-llm", 0.2)):
        res = plan_detectors(dubbed_meta, mode="llm", budget_s=25.0, manifests_dir=isolated_manifests)
        assert res.detectors_to_call == ["video-classifier"]
        assert any(s.get("detector_name") == "syncnet" for s in res.plan["skipped"])

    # 2. Sole-detector safety invariant: aasist is the ONLY audio detector on short audio
    short_audio = InputMetadata(filename="short.wav", modality="audio", has_audio=True, duration_seconds=2.5)
    dep_map = compute_deprioritization_map([load_manifest("aasist", isolated_manifests)], ["short_clip"])
    assert dep_map["aasist"]["should_deprioritize"] is False
    res_audio = plan_detectors(short_audio, mode="llm", budget_s=10.0, mock_llm=True, manifests_dir=isolated_manifests)
    assert res_audio.detectors_to_call == ["aasist"]


# ---------------------------------------------------------------------------
# 5. FastAPI End-to-End Flow: /orchestrate -> /feedback/{job_id} -> /reliability/summary
# ---------------------------------------------------------------------------

def test_fastapi_orchestrate_and_feedback_e2e(tmp_path: Path, isolated_manifests: Path, monkeypatch):
    clear_plan_cache()
    test_db_path = tmp_path / "e2e_flight.db"
    test_engine = create_engine(f"sqlite:///{test_db_path}", echo=False)
    orch_db.init_db(target_engine=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    monkeypatch.setattr(orch_db, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(orch_main, "_reliability_engine_instance", None)
    monkeypatch.setenv("AEGIS_MANIFESTS_DIR", str(isolated_manifests))

    dark_meta = InputMetadata(
        filename="dark_real.mp4",
        modality="video",
        has_audio=False,
        duration_seconds=8.0,
        mean_luminance=20.0,
        face_detected=True,
    )

    def mock_dispatch(detectors, job_id, modality, file_path):
        return [
            DetectorResult(
                detector="video-classifier",
                status="ok",
                job_id=job_id,
                confidence=0.14,
                raw_score=0.14,
                latency_ms=110,
                model_version="efficientnet-b0-ffpp-v2",
                evidence=DetectorEvidence(claim="Authentic frames.", flags=["authentic_frames"]),
            ),
            DetectorResult(
                detector="rppg",
                status="ok",
                job_id=job_id,
                confidence=0.35,
                raw_score=0.84,
                latency_ms=200,
                model_version="rppg-chrom-v1.1",
                evidence=DetectorEvidence(
                    claim="No pulse detected in dark ROI.",
                    flags=["low_light_attenuation"],
                ),
            ),
        ]

    client = TestClient(orch_main.app)
    try:
        with patch("main.get_input_metadata", return_value=dark_meta), \
             patch("main.call_all_detectors", side_effect=mock_dispatch):
            resp = client.post(
                "/orchestrate?planner_mode=rule_based",
                files={"file": ("dark_real.mp4", io.BytesIO(b"\x00\x00\x00\x18ftypmp42"), "video/mp4")},
                headers={"X-API-Key": "dev_default_key"},
            )
        assert resp.status_code == 200, resp.text
        orch_data = resp.json()
        job_id = orch_data["job_id"]
        assert job_id
        assert orch_data["judge_verdict"] == "AUTHENTIC"

        # Submit ground truth confirmation via POST /feedback/{job_id}
        fb_resp = client.post(
            f"/feedback/{job_id}",
            json={"ground_truth_label": "AUTHENTIC", "confirmed_by": "qa_analyst"},
            headers={"X-API-Key": "dev_default_key"},
        )
        assert fb_resp.status_code == 200, fb_resp.text
        fb_data = fb_resp.json()
        assert fb_data["ground_truth_label"] == "AUTHENTIC"
        rppg_claim = next(c for c in fb_data["updated_claims"] if c["detector_name"] == "rppg")
        assert rppg_claim["overruled_by_judge"] is True
        assert rppg_claim["detector_was_wrong"] is True
        assert rppg_claim["confirmed_overrule"] is True

        # Check manifest got updated on disk in isolated_manifests
        m_rppg = load_manifest("rppg", isolated_manifests)
        assert "observed_reliability" in m_rppg
        assert m_rppg["observed_reliability"]["by_condition"]["low_light"]["confirmed_overrule_count"] == 1

        # GET /reliability/summary returns structured summary
        sum_resp = client.get("/reliability/summary", headers={"X-API-Key": "dev_default_key"})
        assert sum_resp.status_code == 200
        assert "rppg" in sum_resp.json()["reliability_summary"]

        # Error checks: unknown job_id -> 404, bad label -> 422
        assert client.post(
            "/feedback/nonexistent-job",
            json={"ground_truth_label": "AUTHENTIC"},
            headers={"X-API-Key": "dev_default_key"},
        ).status_code == 404
        assert client.post(
            f"/feedback/{job_id}",
            json={"ground_truth_label": "MAYBE"},
            headers={"X-API-Key": "dev_default_key"},
        ).status_code == 422

        # Prod security enforcement on new endpoints
        monkeypatch.setenv("AEGIS_SECURITY_PROFILE", "prod")
        monkeypatch.setenv("INTERNAL_API_KEY", "super-secret-prod-key")
        assert client.post(
            f"/feedback/{job_id}",
            json={"ground_truth_label": "AUTHENTIC"},
        ).status_code == 403
        assert client.get("/reliability/summary").status_code == 403
    finally:
        orch_main._reliability_engine_instance = None
        test_engine.dispose()
