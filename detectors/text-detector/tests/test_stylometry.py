"""
Tests for stylometry feature extraction and threshold sanity.
"""
from stylometry import (
    compute_vocabulary_diversity,
    compute_ngram_repetition,
    compute_sentence_variation,
    extract_stylometry_features
)

def test_vocabulary_diversity_empty():
    res = compute_vocabulary_diversity([])
    assert res["ttr"] == 0.0
    assert res["unique_words"] == 0

def test_vocabulary_diversity_basic():
    tokens = ["the", "quick", "brown", "fox", "the", "fox"]
    res = compute_vocabulary_diversity(tokens)
    assert res["total_words"] == 6
    assert res["unique_words"] == 4
    assert res["ttr"] == round(4 / 6, 4)

def test_ngram_repetition():
    tokens = ["in", "conclusion", "we", "find", "in", "conclusion", "we", "agree"]
    res3 = compute_ngram_repetition(tokens, n=3)
    assert res3["total_3grams"] == 6
    # ("in", "conclusion", "we") appears twice -> unique is 5
    assert res3["unique_3grams"] == 5
    assert res3["3gram_repetition_rate"] > 0.0

def test_sentence_variation():
    text = "Short sentence. Another short sentence! A much longer, descriptive sentence that has significantly more words than the earlier ones."
    res = compute_sentence_variation(text)
    assert res["sentence_count"] == 3
    assert res["sentence_length_cov"] > 0.3

def test_extract_stylometry_features_structure():
    text = "Furthermore, in conclusion, the findings demonstrate clear and consistent results. Therefore, we recommend adopting the strategy."
    feat = extract_stylometry_features(text)
    assert "vocabulary_diversity" in feat
    assert "ngram_repetition" in feat
    assert "sentence_variation" in feat
    assert "synthetic_indication_score" in feat
    assert "stylometry_verdict" in feat
    assert 0.0 <= feat["synthetic_indication_score"] <= 1.0
