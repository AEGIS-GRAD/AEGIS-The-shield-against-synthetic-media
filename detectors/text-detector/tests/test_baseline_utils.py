"""Regression tests for interim MAGE dataset label polarity and manifest schema helpers."""
from __future__ import annotations

import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from build_interim_textset import _parse_src, _row_to_record  # noqa: E402


def test_mage_label_polarity_maps_human_1_to_aegis_0_and_machine_0_to_aegis_1():
    human_rec = _row_to_record(
        {"text": "Human written story with enough authentic details.", "label": "1", "src": "cnn_human"},
        origin="test",
    )
    ai_rec = _row_to_record(
        {"text": "GPT4 generated continuation over test domain.", "label": "0", "src": "imdb_gpt4_para"},
        origin="test",
    )

    assert human_rec is not None
    assert human_rec["label"] == 0
    assert human_rec["class_name"] == "human"
    assert human_rec["generator"] == "human"
    assert human_rec["paraphrased"] is False

    assert ai_rec is not None
    assert ai_rec["label"] == 1
    assert ai_rec["class_name"] == "ai"
    assert ai_rec["generator"] == "gpt-4"
    assert ai_rec["domain"] == "imdb"
    assert ai_rec["paraphrased"] is True


def test_parse_src_extracts_mage_machine_generators():
    assert _parse_src("cmv_machine_continuation_gpt-3.5-trubo", "0") == (
        "cmv",
        "gpt-3.5-trubo",
        False,
    )
    assert _parse_src("pubmed_human_para", "0") == ("pubmed", "gpt-paraphraser", True)

