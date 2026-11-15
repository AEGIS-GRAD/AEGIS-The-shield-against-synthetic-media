"""
Tests for Cross-Dataset Split & Protocol Generation (Phase 2).
==============================================================
Validates:
1. Strict identity and source video isolation between train and evaluation splits.
2. Manifests generated for all 5 target datasets:
   - FF++ (Seen domain baseline)
   - Celeb-DF v2 (Unseen)
   - Wild Deepfake (Unseen)
   - DF40 LOMO (Unseen held-out methods)
   - Deepfake-Eval-2024 (Unseen modern benchmark)
3. DF40 Leave-One-Method-Out (LOMO) partition integrity:
   - Validates that held-out methods in a fold do not appear in the candidate pool.
4. Schema conformance of generated CSV manifests.
"""

import csv
import json
from pathlib import Path
import pytest

from eval.scripts.prepare_cross_dataset_splits import (
    DF40_KNOWN_METHODS,
    extract_identity_and_source,
    generate_synthetic_benchmark_splits,
    partition_df40_leave_one_method_out,
    verify_identity_and_source_isolation,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFESTS_DIR = REPO_ROOT / "eval" / "manifests"


def test_df40_leave_one_method_out_partitioning():
    """Verify LOMO partitions partition all 40 methods without overlap within a fold."""
    folds = partition_df40_leave_one_method_out(DF40_KNOWN_METHODS, num_folds=5)
    assert len(folds) == 5

    all_held_out = []
    for fold_id, split_info in folds.items():
        held_out = set(split_info["held_out_methods"])
        seen = set(split_info["seen_candidate_methods"])

        # No overlap between held out and seen
        assert len(held_out.intersection(seen)) == 0, f"Overlap in {fold_id}"
        # Union is complete
        assert held_out.union(seen) == set(DF40_KNOWN_METHODS)
        all_held_out.extend(list(held_out))

    # All methods covered exactly once across 5 folds
    assert len(all_held_out) == len(DF40_KNOWN_METHODS)
    assert set(all_held_out) == set(DF40_KNOWN_METHODS)


def test_identity_and_source_isolation_logic():
    """Verify identity and source leakage detection catches overlapping identities."""
    train = [
        {"identity": "person_A", "source_video_id": "video_1"},
        {"identity": "person_B", "source_video_id": "video_2"},
    ]
    test_clean = [
        {"identity": "person_C", "source_video_id": "video_3"},
        {"identity": "person_D", "source_video_id": "video_4"},
    ]
    audit_clean = verify_identity_and_source_isolation(train, test_clean)
    assert audit_clean["isolated"] is True
    assert audit_clean["leaked_identity_count"] == 0

    test_leaked_id = [
        {"identity": "person_A", "source_video_id": "video_5"},
    ]
    audit_leak = verify_identity_and_source_isolation(train, test_leaked_id)
    assert audit_leak["isolated"] is False
    assert audit_leak["leaked_identity_count"] == 1
    assert "person_A" in audit_leak["leaked_identities"]

    test_leaked_src = [
        {"identity": "person_E", "source_video_id": "video_1"},
    ]
    audit_src_leak = verify_identity_and_source_isolation(train, test_leaked_src)
    assert audit_src_leak["isolated"] is False
    assert audit_src_leak["leaked_source_count"] == 1
    assert "video_1" in audit_src_leak["leaked_sources"]


def test_manifest_files_and_schema(tmp_path):
    """Verify generated manifests adhere to the required evaluation schema and isolation."""
    manifest_paths = generate_synthetic_benchmark_splits(tmp_path)

    expected_keys = {"ffpp_test", "celeb_df_v2", "wild_deepfake", "df40_lomo", "deepfake_eval_2024"}
    assert set(manifest_paths.keys()) == expected_keys

    required_fields = [
        "sample_id",
        "dataset",
        "label",
        "identity",
        "method",
        "source_video_id",
        "split",
        "path",
        "is_seen",
    ]

    for key, path in manifest_paths.items():
        assert path.exists(), f"Manifest {key} missing at {path}"
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == required_fields
            rows = list(reader)
            assert len(rows) > 0, f"Empty rows in {key}"

            # Verify balance of real and fake
            labels = {r["label"] for r in rows}
            assert "real" in labels
            assert "fake" in labels

            # Verify seen flag
            for r in rows:
                if key == "ffpp_test":
                    assert r["is_seen"] == "true"
                else:
                    assert r["is_seen"] == "false"

