"""Boundary and monotonicity tests for minimum-length gating and confidence attenuation."""
from __future__ import annotations

import pytest

from chunking import apply_length_gating


def test_below_min_words_returns_not_applicable_neutral():
    for n in (0, 1, 15, 39):
        res = apply_length_gating(0.99, word_count=n, min_words=40, reliable_words=150)
        assert res.status == "not_applicable"
        assert res.confidence == 0.5
        assert res.attenuation_factor == 0.0
        assert res.attenuated is True


def test_marginal_length_attenuates_monotonically_toward_raw_probability():
    low = apply_length_gating(0.95, word_count=40, min_words=40, reliable_words=150)
    mid = apply_length_gating(0.95, word_count=90, min_words=40, reliable_words=150)
    high = apply_length_gating(0.95, word_count=149, min_words=40, reliable_words=150)
    assert low.status == mid.status == high.status == "ok"
    assert 0.5 < low.confidence < mid.confidence < high.confidence < 0.95


def test_equal_min_and_reliable_words_avoids_zero_division():
    res = apply_length_gating(0.84, word_count=50, min_words=50, reliable_words=50)
    assert res.status == "ok"
    assert res.attenuated is False
    assert res.confidence == pytest.approx(0.84)

