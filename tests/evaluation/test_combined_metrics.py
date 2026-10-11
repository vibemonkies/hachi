import pytest

from hachi.evaluation.metrics import ScoredPoint, combine_metric_reports, forecast_metrics


def report(subject, error, count):
    return forecast_metrics(
        [ScoredPoint(subject, 60.0, 60.0 + error, None, None)] * count,
        metric="heart_rate",
        unit="bpm",
        bootstrap_samples=100,
        confidence=0.95,
        seed=42,
    )


def test_combining_folds_weights_participants_not_rows_and_matches_direct_scoring():
    first, second = report("a", 1.0, 100), report("b", 9.0, 1)
    combined = combine_metric_reports([first, second], seed=42)
    direct = forecast_metrics(
        [ScoredPoint("a", 60.0, 61.0, None, None)] * 100
        + [ScoredPoint("b", 60.0, 69.0, None, None)],
        metric="heart_rate",
        unit="bpm",
        bootstrap_samples=100,
        confidence=0.95,
        seed=42,
    )
    assert combined == direct
    assert combined.mae.value == 5.0 and combined.mae.participants == 2


def test_repeated_participants_cannot_be_pooled_as_independent_people():
    with pytest.raises(ValueError, match="disjoint participants"):
        combine_metric_reports([report("a", 1.0, 1), report("a", 2.0, 1)], seed=42)
    with pytest.raises(ValueError, match="at least one"):
        combine_metric_reports([], seed=42)
    other = forecast_metrics(
        [], metric="steps", unit="count", bootstrap_samples=100, confidence=0.95, seed=42
    )
    with pytest.raises(ValueError, match="share metric"):
        combine_metric_reports([report("a", 1.0, 1), other], seed=42)
