"""Tiny explicit synthetic cohorts; never read a real dataset or production state."""

from datetime import UTC, datetime, timedelta

import pytest

from hachi.contracts.base import SCHEMA_VERSION, DatasetSnapshotRef
from hachi.contracts.manifests import SplitManifest, TimeWindow
from hachi.contracts.tables import Aggregate, Observation
from hachi.evaluation import EvaluationConfig, partition_participants

BASE = datetime(2026, 10, 10, 8, tzinfo=UTC)
HOUR = timedelta(hours=1)


def observation(subject: str, hour: int, value: float = 60.0, *, delay: int = 0) -> Observation:
    start = BASE + hour * HOUR
    end = start + timedelta(minutes=15)
    return Observation(
        dataset_id="synthetic-cohort",
        subject_id=subject,
        record_id=f"{subject}-h{hour}",
        source_kind="research_device",
        source_id="synthetic-device",
        device_model=None,
        metric="heart_rate",
        value=value,
        unit="bpm",
        start_utc=start,
        end_utc=end,
        available_at_utc=end + delay * HOUR,
        availability="observed",
        availability_rule=None,
        tz_name="UTC",
        utc_offset_minutes=0,
        tz_provenance="dataset_documentation",
    )


def target(subject: str, hour: int, value: float | None = 61.0) -> Aggregate:
    return Aggregate(
        dataset_id="synthetic-cohort",
        subject_id=subject,
        metric="heart_rate",
        unit="bpm",
        resolution="hour",
        interval_start_utc=BASE + hour * HOUR,
        interval_end_utc=BASE + (hour + 1) * HOUR,
        local_date=None,
        tz_name="UTC",
        aggregation="mean",
        value=value,
        null_reason="no_observations" if value is None else None,
        observed_count=0 if value is None else 1,
        coverage=0.0 if value is None else 1.0,
        source_ids=[] if value is None else ["synthetic-device"],
        pipeline_version="synthetic-1",
    )


@pytest.fixture
def manifest() -> SplitManifest:
    return SplitManifest(
        schema_version=SCHEMA_VERSION,
        manifest_id="synthetic-split",
        created_at_utc=BASE,
        dataset_snapshot=DatasetSnapshotRef(
            dataset_id="synthetic-cohort", dataset_version="synthetic-1", snapshot_sha256="a" * 64
        ),
        task="physiology_forecast",
        fold=None,
        n_folds=None,
        **partition_participants(
            [f"synthetic-{i}" for i in range(6)], seed=42, validation_count=2, test_count=2
        ),
        lookback_hours=4,
        horizon_hours=2,
        embargo_hours=0,
        cutoff_stride_hours=1,
        min_history_hours=2,
        evaluation_window=TimeWindow(start_utc=BASE, end_utc=BASE + 4 * HOUR),
        seed=42,
        test_opened_at_utc=None,
    )


@pytest.fixture
def config() -> EvaluationConfig:
    return EvaluationConfig(
        data_mode="synthetic",
        metric="heart_rate",
        aggregation="mean",
        history_policy="causal_prefix",
        pretrained_cohort_overlap="not_applicable",
        overlap_note="Synthetic tests without a pretrained model.",
        bootstrap_samples=100,
        confidence=0.95,
    )


@pytest.fixture
def cohort(manifest: SplitManifest) -> tuple[list[Observation], list[Aggregate]]:
    subjects = manifest.train_subjects + manifest.validation_subjects + manifest.test_subjects
    return (
        [observation(s, h) for s in subjects for h in range(-4, 4)],
        [target(s, h) for s in subjects for h in range(4)],
    )
