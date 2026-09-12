import pytest
import torch
from infer import aggregate_scores, load_model, predict_frame


def test_aggregate_scores_mean_pooling():
    """Test mean pooling calculation with normal score lists."""
    scores = [0.2, 0.4, 0.6]
    result = aggregate_scores(scores)
    assert pytest.approx(result, 0.0001) == 0.4


def test_aggregate_scores_single_frame():
    """Test aggregation with a single frame score."""
    scores = [0.85]
    result = aggregate_scores(scores)
    assert result == 0.85


def test_aggregate_scores_empty():
    """Test aggregation behavior with an empty list of scores."""
    result = aggregate_scores([])
    assert result == 0.5


def test_aggregate_scores_clamping():
    """Test that aggregated score remains in [0.0, 1.0]."""
    assert aggregate_scores([1.0, 1.0, 1.0]) == 1.0
    assert aggregate_scores([0.0, 0.0]) == 0.0


@pytest.mark.slow
def test_real_model_predict_frame():
    """Smoke test: loads real pretrained model and verifies predict_frame returns a float in [0.0, 1.0]."""
    model = load_model()
    dummy_tensor = torch.randn(1, 3, 224, 224)
    score = predict_frame(model, dummy_tensor)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0
