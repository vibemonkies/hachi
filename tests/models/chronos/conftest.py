"""Generated hourly series only; no real dataset, checkpoint or GPU is touched."""

from datetime import UTC, datetime, timedelta

import pytest

from hachi.contracts.base import SCHEMA_VERSION, DatasetSnapshotRef
from hachi.contracts.manifests import SplitManifest, TimeWindow
from hachi.contracts.tables import Aggregate
from hachi.evaluation import EvaluationConfig, HourlyFeature, partition_participants
from hachi.models.chronos import ChronosConfig, ChronosModelPin

BASE = datetime(2026, 10, 10, tzinfo=UTC)
HOUR = timedelta(hours=1)
# amazon/chronos-2 config.json quantiles.
LEVELS = (0.01, 0.05, *(round(0.05 * i, 2) for i in range(2, 19)), 0.95, 0.99)


def aggregate(subject: str, hour: int, value: float | None, metric: str = "heart_rate"):
    start = BASE + hour * HOUR
    return Aggregate(
        dataset_id="synthetic-chronos",
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
        null_reason="no_observations" if value is None else None,
        observed_count=0 if value is None else 60,
        coverage=0.0 if value is None else 1.0,
        source_ids=[] if value is None else ["synthetic-device"],
        pipeline_version="synthetic-1",
    )


def feature(subject: str, hour: int, value: float, *, delay_hours: int = 0, **kwargs):
    row = aggregate(subject, hour, value, **kwargs)
    return HourlyFeature(
        aggregate=row,
        available_at_utc=row.interval_end_utc + delay_hours * HOUR,
        availability_rule="synthetic-final-at-bin-end",
    )


def level(subject: str, hour: int) -> float:
    return 60.0 + int(subject.rsplit("-", 1)[1]) + (hour % 24) / 4


@pytest.fixture
def chronos() -> ChronosConfig:
    return ChronosConfig(
        model=ChronosModelPin(
            model_id="amazon/chronos-2",
            revision="29ec3766d36d6f73f0696f85560a422f50e8498c",
            weights_sha256="d" * 64,
            license="Apache-2.0",
            runtime_lock_sha256="8" * 64,
        ),
        metric="heart_rate",
        aggregation="mean",
        context_hours=6,
        min_context_values=2,
    )


@pytest.fixture
def evaluation() -> EvaluationConfig:
    return EvaluationConfig(
        data_mode="synthetic",
        metric="heart_rate",
        aggregation="mean",
        history_policy="causal_prefix",
        pretrained_cohort_overlap="unknown",
        overlap_note="Synthetic tests; no pretrained-cohort evidence implied.",
        bootstrap_samples=50,
        confidence=0.9,
    )


@pytest.fixture
def manifest() -> SplitManifest:
    subjects = [f"synthetic-{i}" for i in range(6)]
    return SplitManifest(
        schema_version=SCHEMA_VERSION,
        manifest_id="synthetic-chronos-split",
        created_at_utc=BASE,
        dataset_snapshot=DatasetSnapshotRef(
            dataset_id="synthetic-chronos", dataset_version="synthetic-1", snapshot_sha256="a" * 64
        ),
        task="physiology_forecast",
        fold=None,
        n_folds=None,
        **partition_participants(subjects, seed=7, validation_count=2, test_count=2),
        lookback_hours=6,
        horizon_hours=3,
        embargo_hours=1,
        cutoff_stride_hours=4,
        min_history_hours=3,
        evaluation_window=TimeWindow(start_utc=BASE, end_utc=BASE + 12 * HOUR),
        seed=7,
        test_opened_at_utc=None,
    )


@pytest.fixture
def cohort(manifest: SplitManifest):
    subjects = manifest.train_subjects + manifest.validation_subjects + manifest.test_subjects
    features = [feature(s, h, level(s, h)) for s in subjects for h in range(-8, 12) if h % 5 != 2]
    targets = [aggregate(s, h, level(s, h)) for s in subjects for h in range(12)]
    return features, targets
