"""Generated bins only: the bounded context never returns later or late-available data."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from hachi.contracts.base import SCHEMA_VERSION, DatasetSnapshotRef
from hachi.contracts.manifests import SplitManifest, TimeWindow
from hachi.contracts.tables import Aggregate
from hachi.data.pmdata import FeatureBin
from hachi.evaluation import EvaluationConfig, evaluate_forecast, partition_participants
from hachi.evaluation.context import ContextPolicy, context_index, hourly_grid
from hachi.evaluation.features import HourlyFeaturePolicy, hourly_features

CUTOFF = datetime(2026, 1, 3, tzinfo=UTC)
HOUR = timedelta(hours=1)
HR = HourlyFeaturePolicy(
    metric="heart_rate",
    aggregation="mean",
    min_coverage=0.5,
    min_observed_count=30,
    availability_rule="generated-final-at-bin-end",
)
STEPS = HourlyFeaturePolicy(
    metric="steps",
    aggregation="sum",
    min_coverage=0.5,
    min_observed_count=30,
    availability_rule="generated-final-at-bin-end",
)


def item(subject, hour, value, *, metric="heart_rate", delay=0, coverage=1.0):
    start = CUTOFF + hour * HOUR
    row = Aggregate(
        dataset_id="generated-context",
        subject_id=subject,
        metric=metric,
        unit="bpm" if metric == "heart_rate" else "count",
        resolution="hour",
        interval_start_utc=start,
        interval_end_utc=start + HOUR,
        local_date=None,
        tz_name="UTC",
        aggregation="mean" if metric == "heart_rate" else "sum",
        value=value,
        null_reason=None,
        observed_count=60,
        coverage=coverage,
        source_ids=["generated-device"],
        pipeline_version="generated-1",
    )
    return FeatureBin(row, row.interval_end_utc + delay * HOUR)


def test_window_excludes_future_late_old_and_other_subjects():
    bins = [
        item("a", -9, 50.0),  # older than the window
        item("a", -6, 60.0),
        item("a", -2, 61.0, delay=3),  # completed, but available only after the cutoff
        item("a", -1, 62.0),
        item("a", 0, 299.0),  # future value sentinel
        item("a", 5, 299.0),
        item("b", -1, 70.0),  # another subject
        item("a", -3, 63.0, coverage=0.2),  # fails the channel's own inclusion policy
    ]
    index = context_index(bins, ContextPolicy(hours=8, channels=[HR]))
    rows = index.window("a", CUTOFF)["heart_rate"]
    assert [r.value for r in rows] == [60.0, 62.0]
    assert hourly_grid(rows, CUTOFF, 8) == (None, None, 60.0, None, None, None, None, 62.0)
    assert index.counts["heart_rate"]["low_coverage"] == 1
    # The late bin becomes visible once its availability has passed.
    later = index.window("a", CUTOFF + 2 * HOUR)["heart_rate"]
    assert [r.value for r in later] == [60.0, 61.0, 62.0, 299.0]


def test_future_values_cannot_change_the_window():
    base = [item("a", h, 60.0 + h) for h in range(-6, 0)]
    calm = context_index([*base, item("a", 1, 70.0)], ContextPolicy(hours=6, channels=[HR]))
    wild = context_index([*base, item("a", 1, 299.0)], ContextPolicy(hours=6, channels=[HR]))
    assert calm.window("a", CUTOFF) == wild.window("a", CUTOFF)


def test_channels_stay_separate_and_missing_channels_stay_empty():
    bins = [item("a", -1, 60.0), item("a", -1, 120.0, metric="steps")]
    index = context_index(bins, ContextPolicy(hours=4, channels=[HR, STEPS]))
    window = index.window("a", CUTOFF)
    assert [r.value for r in window["steps"]] == [120.0]
    assert index.window("b", CUTOFF) == {"heart_rate": (), "steps": ()}
    assert hourly_grid((), CUTOFF, 2) == (None, None)


def test_policy_and_cutoff_validation():
    with pytest.raises(ValidationError, match="one channel per metric"):
        ContextPolicy(hours=4, channels=[HR, HR])
    with pytest.raises(ValidationError):
        ContextPolicy(hours=0, channels=[HR])
    index = context_index([], ContextPolicy(hours=4, channels=[HR]))
    with pytest.raises(ValueError, match="hour-aligned"):
        index.window("a", CUTOFF + timedelta(minutes=30))


def test_last_lookback_hours_equal_the_harness_history():
    subjects = [f"generated-{i}" for i in range(6)]
    bins = [
        item(s, h, 60.0 + i + (h % 5), delay=(1 if h % 7 == 0 else 0))
        for i, s in enumerate(subjects)
        for h in range(-60, 24)
        if (h + i) % 4
    ]
    manifest = SplitManifest(
        schema_version=SCHEMA_VERSION,
        manifest_id="generated-context",
        created_at_utc=CUTOFF,
        dataset_snapshot=DatasetSnapshotRef(
            dataset_id="generated-context", dataset_version="g1", snapshot_sha256="a" * 64
        ),
        task="physiology_forecast",
        fold=None,
        n_folds=None,
        **partition_participants(subjects, seed=3, validation_count=2, test_count=2),
        lookback_hours=12,
        horizon_hours=4,
        embargo_hours=0,
        cutoff_stride_hours=4,
        min_history_hours=1,
        evaluation_window=TimeWindow(start_utc=CUTOFF, end_utc=CUTOFF + 16 * HOUR),
        seed=3,
        test_opened_at_utc=None,
    )
    config = EvaluationConfig(
        data_mode="synthetic",
        metric="heart_rate",
        aggregation="mean",
        history_policy="causal_prefix",
        pretrained_cohort_overlap="not_applicable",
        overlap_note="Generated context check.",
        bootstrap_samples=10,
        confidence=0.9,
    )
    features = hourly_features(bins, HR).features
    index = context_index(bins, ContextPolicy(hours=36, channels=[HR]))
    checked = []

    def factory(_):
        def predict(request):
            window = index.window(request.subject_id, request.cutoff)["heart_rate"]
            recent = {r.record_id for r in window if r.start_utc >= request.cutoff - 12 * HOUR}
            assert recent == {r.record_id for r in request.history}
            assert all(r.start_utc >= request.cutoff - 36 * HOUR for r in window)
            checked.append(request.cutoff)
            return (None,) * len(request.targets)

        return predict

    evaluate_forecast(manifest, features, (), factory, config)
    assert len(checked) == 8
