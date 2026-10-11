"""Derived inputs preserve readiness, lineage and missingness without raw-row identity."""

from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import pytest
from pydantic import ValidationError

from hachi.contracts.causality import available_by, observations_available_by
from hachi.contracts.manifests import Exclusion, SplitManifest
from hachi.contracts.tables import Aggregate, Observation
from hachi.evaluation import (
    EvaluationConfig,
    ForecastInput,
    HourlyFeature,
    HourlyFeaturePolicy,
    TrainingPrefix,
    evaluate_forecast,
    hourly_features,
)
from hachi.models.baselines import BaselineConfig, baseline_factory
from hachi.models.baselines.forecast import hourly_values

from .conftest import BASE, HOUR, target


class Bin(NamedTuple):
    aggregate: Aggregate
    available_at_utc: datetime


def policy() -> HourlyFeaturePolicy:
    return HourlyFeaturePolicy(
        metric="heart_rate",
        aggregation="mean",
        min_coverage=0.5,
        min_observed_count=2,
        availability_rule="synthetic-source-end-1",
    )


def aggregate(subject: str = "synthetic-1", hour: int = -1, **changes: object) -> Aggregate:
    return Aggregate.model_validate(
        {**target(subject, hour, 60.0).model_dump(), "observed_count": 12, **changes}
    )


def feature(row: Aggregate, ready: datetime | None = None) -> HourlyFeature:
    return HourlyFeature(
        aggregate=row,
        available_at_utc=ready if ready is not None else row.interval_end_utc,
        availability_rule=policy().availability_rule,
    )


def baseline_config() -> BaselineConfig:
    return BaselineConfig(method="last_valid", metric="heart_rate", aggregation="mean")


def test_ready_boundary_and_concrete_filter_type() -> None:
    row = feature(aggregate())
    assert available_by(row, BASE)
    late = feature(row.aggregate, BASE + timedelta(microseconds=1))
    assert not available_by(late, BASE)
    assert observations_available_by([row, late], BASE) == [row]
    with pytest.raises(ValueError, match="UTC-aware"):
        available_by(row, BASE.replace(tzinfo=None))


@pytest.mark.parametrize(
    "ready",
    [BASE.replace(tzinfo=None), BASE.astimezone(timezone(timedelta(hours=2)))],
)
def test_input_utc_is_validated(ready: datetime) -> None:
    with pytest.raises(ValidationError):
        feature(aggregate(), ready)


def test_complete_bin_and_readiness_required() -> None:
    with pytest.raises(ValidationError, match="before its bin ends"):
        feature(aggregate(), BASE - timedelta(microseconds=1))
    row = aggregate(
        interval_start_utc=BASE - HOUR + timedelta(minutes=1),
        interval_end_utc=BASE + timedelta(minutes=1),
    )
    with pytest.raises(ValidationError, match="hour-aligned"):
        feature(row)
    with pytest.raises(ValidationError, match="observed value"):
        feature(target("synthetic-1", -1, None))


def test_view_exclusive_counts_and_lineage() -> None:
    rows = [
        aggregate(hour=-6),
        target("synthetic-1", -5, None),
        aggregate(hour=-4, coverage=0.4),
        aggregate(hour=-3, observed_count=1),
        aggregate(hour=-2, aggregation="median"),
        aggregate(hour=-1, metric="resting_heart_rate_vendor"),
    ]
    view = hourly_features((Bin(r, r.interval_end_utc) for r in rows), policy())
    assert view.counts == {
        "input_bins": 6,
        "included": 1,
        "missing": 1,
        "low_coverage": 1,
        "low_count": 1,
        "other_aggregation": 1,
        "other_metric": 1,
    }
    assert sum(v for k, v in view.counts.items() if k != "input_bins") == 6
    assert view.features[0].aggregate == rows[0]
    single = hourly_features([Bin(rows[0], rows[0].interval_end_utc)], policy())
    assert single.features[0].record_id == view.features[0].record_id
    with pytest.raises(ValueError, match="duplicate hourly"):
        hourly_features([Bin(rows[0], BASE), Bin(rows[0], BASE)], policy())


def test_models_preserve_derived_value_and_native_sample_count() -> None:
    row = feature(aggregate())
    config = BaselineConfig.model_validate(
        {**baseline_config().model_dump(), "min_samples_per_hour": 10}
    )
    values = hourly_values([row], config, BASE)
    assert len(values) == 1
    assert values[0].value == 60.0 and values[0].samples == 12
    assert hourly_values([row], config, BASE - timedelta(microseconds=1)) == ()
    with pytest.raises(ValueError, match="aggregation must match"):
        hourly_values([feature(aggregate(aggregation="median"))], config, BASE)
    with pytest.raises(ValueError, match="duplicate derived"):
        hourly_values([row, row], config, BASE)


def derived_cohort(observations: list[Observation]) -> list[HourlyFeature]:
    rows = []
    for row in observations:
        hour = int((row.start_utc - BASE) / HOUR)
        bin_row = aggregate(row.subject_id, hour, value=row.value)
        rows.append(feature(bin_row, max(bin_row.interval_end_utc, row.available_at_utc)))
    return rows


def test_derived_future_sentinel_and_frozen_training(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    observations, labels = cohort
    features = derived_cohort(observations)
    late = feature(aggregate(manifest.validation_subjects[0], -1, value=100.0), BASE + 10 * HOUR)
    features = [
        r for r in features if (r.subject_id, r.start_utc) != (late.subject_id, late.start_utc)
    ] + [late]
    captured: list[TrainingPrefix] = []
    requests: list[ForecastInput] = []
    factory = baseline_factory(baseline_config())

    def record_fit(training: TrainingPrefix):
        captured.append(training)
        predict = factory(training)

        def record_predict(request: ForecastInput):
            requests.append(request)
            return predict(request)

        return record_predict

    result = evaluate_forecast(manifest, features, labels, record_fit, config)
    changed = [
        feature(aggregate(r.subject_id, -1, value=200.0), r.available_at_utc) if r == late else r
        for r in features
    ]
    replay = evaluate_forecast(manifest, changed, labels, factory, config)
    assert result.predictions == replay.predictions
    assert result.counts["scored_points"] > 0
    assert all(
        isinstance(r, HourlyFeature) and available_by(r, BASE) for r in captured[0].observations
    )
    assert all(r.subject_id in manifest.train_subjects for r in captured[0].observations)
    assert all(late not in request.history for request in requests)


def test_separate_paths_and_explicit_exclusions(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    observations, labels = cohort
    features = derived_cohort(observations)
    factory = baseline_factory(baseline_config())
    raw = evaluate_forecast(manifest, observations, labels, factory, config)
    derived = evaluate_forecast(manifest, features, labels, factory, config)
    assert raw.predictions == derived.predictions
    with pytest.raises(ValueError, match="do not mix"):
        evaluate_forecast(manifest, [observations[0], *features], labels, factory, config)
    excluded = Exclusion(
        subject_id=observations[0].subject_id,
        record_id=observations[0].record_id,
        reason="raw quarantine",
    )
    with pytest.raises(ValueError, match="apply raw record exclusions"):
        evaluate_forecast(
            manifest.model_copy(update={"exclusions": [excluded]}),
            features,
            labels,
            factory,
            config,
        )
    excluded_feature = Exclusion(
        subject_id=features[0].subject_id,
        record_id=features[0].record_id,
        reason="derived quarantine",
    )
    result = evaluate_forecast(
        manifest.model_copy(update={"exclusions": [excluded_feature]}),
        features,
        labels,
        factory,
        config,
    )
    assert result.counts["excluded_observation_records"] == 1
