"""Accrued amounts/durations use sums, with observed zeros distinct from missingness."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from hachi.contracts.metrics import METRICS
from hachi.contracts.tables import Aggregate, Observation
from hachi.evaluation import (
    EvaluationConfig,
    HourlyFeature,
    HourlyFeaturePolicy,
    TrainingPrefix,
    compare_forecasts,
    evaluate_forecast,
)
from hachi.models.baselines import BaselineConfig, baseline_factory, fit_baseline, hourly_values
from hachi.models.baselines.tree import Leaf, TreeArtifact, TreeConfig

from .conftest import BASE, HOUR, observation, target


def total_row(subject, hour, value, metric="steps", **changes):
    return Observation.model_validate(
        {
            **observation(subject, hour).model_dump(),
            "metric": metric,
            "unit": METRICS[metric].unit,
            "value": float(value),
            **changes,
        }
    )


def total_bin(subject, hour, value, metric="steps"):
    return Aggregate.model_validate(
        {
            **target(subject, hour, None if value is None else 61.0).model_dump(),
            "value": value,
            "metric": metric,
            "unit": METRICS[metric].unit,
            "aggregation": "sum",
        }
    )


def feature(row):
    return HourlyFeature(
        aggregate=row,
        available_at_utc=row.interval_end_utc,
        availability_rule="generated-complete-bin-1",
    )


@pytest.mark.parametrize(
    "metric", ["steps", "active_energy", "walking_running_distance", "sleep_asleep_core"]
)
def test_raw_hourly_totals_preserve_recorded_zero_and_do_not_invent_missing_hours(metric):
    config = BaselineConfig(method="last_valid", metric=metric, aggregation="sum")
    rows = [
        total_row("synthetic-1", -2, 10, metric),
        total_row(
            "synthetic-1",
            -2,
            20,
            metric,
            record_id="second",
            start_utc=BASE - 2 * HOUR + timedelta(minutes=30),
            end_utc=BASE - 2 * HOUR + timedelta(minutes=45),
            available_at_utc=BASE - HOUR,
        ),
        total_row("synthetic-1", -1, 0, metric),
    ]
    values = hourly_values(rows, config, BASE)
    assert [r.value for r in values] == [30.0, 0.0]
    assert hourly_values([], config, BASE) == ()
    assert (
        hourly_values([feature(total_bin("synthetic-1", -1, 0, metric))], config, BASE)[0].value
        == 0.0
    )
    HourlyFeaturePolicy(
        metric=metric,
        aggregation="sum",
        min_coverage=0.5,
        min_observed_count=1,
        availability_rule="generated-1",
    )


def test_step_evaluation_keeps_zero_labels_scored_and_missing_labels_missing(manifest, config):
    subjects = manifest.train_subjects + manifest.validation_subjects + manifest.test_subjects
    inputs = [feature(total_bin(s, h, 0.0)) for s in subjects for h in range(-4, 4)]
    labels = [total_bin(s, h, None if h == 1 else 0.0) for s in subjects for h in range(4)]
    selected = EvaluationConfig.model_validate(
        {**config.model_dump(), "metric": "steps", "aggregation": "sum"}
    )
    result = evaluate_forecast(
        manifest,
        inputs,
        labels,
        baseline_factory(BaselineConfig(method="last_valid", metric="steps", aggregation="sum")),
        selected,
    )
    assert result.counts["missing_labels"] == 2
    assert result.counts["scored_points"] == 6
    assert result.metrics.mae.value == 0.0


def test_overlapping_raw_totals_are_refused_and_duration_bounds_apply_to_saved_models():
    config = BaselineConfig(method="last_valid", metric="sleep_asleep_core", aggregation="sum")
    row = total_row("synthetic-1", -1, 900, "sleep_asleep_core")
    overlap = Observation.model_validate({**row.model_dump(), "record_id": "overlap"})
    with pytest.raises(ValueError, match="overlapping"):
        hourly_values([row, overlap], config, BASE)
    fitted = fit_baseline(TrainingPrefix(BASE, ("synthetic-1",), (row,)), config)
    with pytest.raises(ValidationError, match="duration exceeds"):
        type(fitted).model_validate(
            {
                **fitted.model_dump(),
                "config": config.model_copy(update={"method": "train_population_mean"}),
                "training_hours": 1,
                "population_mean": 7200.0,
            }
        )
    tree_config = TreeConfig(metric="sleep_asleep_core", aggregation="sum", min_training_examples=1)
    with pytest.raises(ValidationError, match="duration exceeds"):
        TreeArtifact(
            config=tree_config,
            fit_as_of=BASE,
            training_prefix_sha256="a" * 64,
            training_examples=1,
            nodes=(Leaf(value=7200.0),),
        )


def test_target_quality_policy_is_identical_for_individual_and_paired_scoring(manifest, config):
    subjects = manifest.train_subjects + manifest.validation_subjects + manifest.test_subjects
    inputs = [feature(total_bin(s, h, 0.0)) for s in subjects for h in range(-4, 4)]
    labels = [total_bin(s, h, 0.0) for s in subjects for h in range(4)]
    labels = [
        Aggregate.model_validate(
            {
                **r.model_dump(),
                "coverage": 0.5 if r.interval_start_utc == BASE else 1.0,
                "observed_count": 1 if r.interval_start_utc == BASE + HOUR else 60,
            }
        )
        for r in labels
    ]
    selected = EvaluationConfig.model_validate(
        {
            **config.model_dump(),
            "metric": "steps",
            "aggregation": "sum",
            "min_target_coverage": 1.0,
            "min_target_observed_count": 60,
        }
    )
    factory = baseline_factory(
        BaselineConfig(method="last_valid", metric="steps", aggregation="sum")
    )
    result = evaluate_forecast(manifest, inputs, labels, factory, selected)
    assert result.counts["missing_labels"] == result.counts["excluded_target_quality_points"] == 4
    assert result.counts["scored_points"] == 4
    comparison = compare_forecasts(
        manifest,
        inputs,
        labels,
        factory,
        factory,
        baseline_config=selected,
        candidate_config=selected,
    )
    assert comparison.summary.counts["missing_labels"] == 4
    assert comparison.summary.counts["paired_points"] == 4
    with pytest.raises(ValueError, match="matching min_target_coverage"):
        compare_forecasts(
            manifest,
            inputs,
            labels,
            factory,
            factory,
            baseline_config=selected,
            candidate_config=selected.model_copy(update={"min_target_coverage": 0.5}),
        )
