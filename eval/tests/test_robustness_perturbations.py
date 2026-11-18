"""Unit tests for the Week 10 robustness harness perturbations (no models needed)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from eval.robustness import perturbations as P  # noqa: E402
from eval.robustness.harness import auc, summarise  # noqa: E402

TEXT = ("Additionally, the committee will utilize several approaches to ensure that residents obtain sufficient "
        "assistance. However, it is not clear when the programme will commence. Officials stated that numerous "
        "individuals require help. The overall impact remains significant.")


@pytest.fixture
def img():
    rng = np.random.default_rng(0)
    return Image.fromarray(rng.integers(0, 255, (96, 128, 3), dtype=np.uint8))


def test_strengths_avoid_training_augmentations_and_existing_eval_variants():
    assert not set(P.IMAGE_PERTURBATIONS["jpeg"][1]) & {75, 50}
    assert 0.5 not in P.IMAGE_PERTURBATIONS["resize"][1]
    assert "flip" not in P.IMAGE_PERTURBATIONS and "color_jitter" not in P.IMAGE_PERTURBATIONS


@pytest.mark.parametrize("name", list(P.IMAGE_PERTURBATIONS))
def test_image_perturbations_deterministic_and_shape(img, name):
    fn, strengths = P.IMAGE_PERTURBATIONS[name]
    for s in strengths:
        a, b = fn(img, s, seed=3), fn(img, s, seed=3)
        assert np.array_equal(np.asarray(a), np.asarray(b))
        if name != "crop":
            assert a.size == img.size


def test_image_strength_is_monotonic(img):
    def dist(x):
        return float(np.abs(np.asarray(x, dtype=np.float32) - np.asarray(img, dtype=np.float32)).mean())

    for name in ("jpeg", "blur", "noise", "resize"):
        fn, strengths = P.IMAGE_PERTURBATIONS[name]
        d = [dist(fn(img, s, seed=1)) for s in strengths]
        assert d == sorted(d), (name, d)


@pytest.mark.parametrize("name", list(P.TEXT_PERTURBATIONS))
def test_text_perturbations_deterministic_and_monotonic(name):
    fn, strengths = P.TEXT_PERTURBATIONS[name]
    import difflib

    outs = [fn(TEXT, s, seed=5) for s in strengths]
    assert outs == [fn(TEXT, s, seed=5) for s in strengths]
    changed = [1.0 - difflib.SequenceMatcher(None, o, TEXT).ratio() for o in outs]
    assert changed[0] > 0 and changed == sorted(changed), changed


def test_homoglyphs_survive_nfkc_but_zero_width_does_not():
    """Documents why the matrix treats the two attacks differently: the text service's
    NFKC + format-char stripping removes zero-width characters but not Cyrillic lookalikes."""
    import unicodedata

    zw = P.txt_zero_width(TEXT, 0.25, seed=1)
    hg = P.txt_homoglyph(TEXT, 0.25, seed=1)
    clean_zw = "".join(c for c in unicodedata.normalize("NFKC", zw) if unicodedata.category(c) != "Cf")
    assert clean_zw == unicodedata.normalize("NFKC", TEXT)
    assert unicodedata.normalize("NFKC", hg) != unicodedata.normalize("NFKC", TEXT)


def test_audio_perturbations_keep_length():
    sr = 16000
    t = np.arange(sr) / sr
    wav = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    tel = P.aud_telephone(wav, sr)
    assert abs(len(tel) - len(wav)) <= 2 and np.isfinite(tel).all()
    q4 = P.aud_quantize(wav, sr, 4)
    assert len(np.unique(q4)) <= 16


def test_summary_metrics():
    rows = []
    for i, (lab, clean, pert) in enumerate([(1, 0.9, 0.2), (1, 0.8, 0.7), (1, 0.3, 0.1), (0, 0.1, 0.6), (0, 0.2, 0.2)]):
        rows += [{"sample_id": f"s{i}", "label": lab, "perturbation": "clean", "strength": 0.0, "score": clean},
                 {"sample_id": f"s{i}", "label": lab, "perturbation": "jpeg", "strength": 40, "score": pert}]
    m = {(r["perturbation"], r["strength"]): r for r in summarise(rows, "d", "v", {})["matrix"]}
    assert m[("clean", 0.0)]["detection_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert m[("jpeg", 40)]["evasion_rate"] == 0.5  # 2 detected clean, 1 of them missed after jpeg
    assert m[("jpeg", 40)]["false_positive_rate"] == 0.5
    assert auc([0.9, 0.8], [0.1, 0.2]) == 1.0
