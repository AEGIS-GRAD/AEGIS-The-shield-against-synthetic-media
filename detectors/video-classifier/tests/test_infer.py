import pytest
from infer import aggregate_scores, predict_frame, load_model


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


def test_predict_frame_placeholder():
    """Test that predict_frame stub returns a float in [0.0, 1.0]."""
    dummy_tensor = "dummy_tensor_placeholder"
    score = predict_frame(dummy_tensor)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_load_model_raises_not_implemented():
    """Test that load_model stub raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        load_model()
