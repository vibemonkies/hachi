import hashlib
import json
from dataclasses import replace
from pathlib import Path
from statistics import fmean

import pytest
from pydantic import ValidationError

from hachi.contracts.causality import available_by
from hachi.contracts.manifests import Exclusion, ModelRef, RunManifest, SplitManifest, TimeWindow
from hachi.contracts.tables import Aggregate, Observation
from hachi.evaluation import (
    EvaluationConfig,
    ForecastEstimate,
    ForecastInput,
    Predictor,
    TrainingPrefix,
    document_sha256,
    evaluate_forecast,
    partition_participants,
    rolling_origins,
    write_packet,
)
from hachi.evaluation.metrics import ScoredPoint, forecast_metrics

from .conftest import BASE, HOUR, observation, target


def last_value(_: TrainingPrefix) -> Predictor:
    def predict(request: ForecastInput) -> tuple[ForecastEstimate | None, ...]:
        estimate = ForecastEstimate(median=request.history[-1].value) if request.history else None
        return (estimate,) * len(request.targets)

    return predict


def test_participant_assignment_is_order_invariant_and_disjoint() -> None:
    subjects = [f"synthetic-{i}" for i in range(20)]
    a = partition_participants(subjects, seed=42, validation_count=5, test_count=5)
    assert a == partition_participants(
        reversed(subjects), seed=42, validation_count=5, test_count=5
    )
    train, val, test = (
        set(a[k]) for k in ("train_subjects", "validation_subjects", "test_subjects")
    )
    assert not train & val and not train & test and not val & test
    assert train | val | test == set(subjects)


def test_split_exclusions_and_invalid_rosters() -> None:
    exclusion = Exclusion(subject_id="withdrawn", record_id=None, reason="withdrawal")
    parts = partition_participants(
        ["a", "b", "c", "withdrawn"],
        seed=1,
        validation_count=1,
        test_count=1,
        exclusions=[exclusion],
    )
    assert all(
        "withdrawn" not in parts[k]
        for k in ("train_subjects", "validation_subjects", "test_subjects")
    )
    assert parts["exclusions"] == [exclusion]
    with pytest.raises(ValueError, match="duplicates"):
        partition_participants(["a", "a"], seed=1, validation_count=0, test_count=0)
    with pytest.raises(ValueError, match="training"):
        partition_participants(["a", "b"], seed=1, validation_count=1, test_count=1)
    with pytest.raises(ValueError, match="roster"):
        partition_participants(
            ["a"], seed=1, validation_count=0, test_count=0, exclusions=[exclusion]
        )


def test_origins_purge_overlaps_and_respect_embargo(manifest: SplitManifest) -> None:
    plan = rolling_origins(manifest, "validation")
    assert [o.cutoff for o in plan.origins] == sorted(o.cutoff for o in plan.origins)
    for subject in manifest.validation_subjects:
        selected = [o for o in plan.origins if o.subject_id == subject]
        assert [o.cutoff for o in selected] == [BASE, BASE + 2 * HOUR]
        assert selected[0].targets[-1].end_utc <= selected[1].targets[0].start_utc
    assert len([e for e in plan.exclusions if e.reason == "overlapping_targets"]) == 2
    embargoed = SplitManifest.model_validate({**manifest.model_dump(), "embargo_hours": 1})
    assert rolling_origins(embargoed, "validation").origins[0].targets[0].start_utc == BASE + HOUR


def test_test_cohort_requires_explicit_opening(manifest: SplitManifest) -> None:
    with pytest.raises(ValueError, match="sealed"):
        rolling_origins(manifest, "test")
    opened = SplitManifest.model_validate({**manifest.model_dump(), "test_opened_at_utc": BASE})
    assert {o.subject_id for o in rolling_origins(opened, "test").origins} == set(
        manifest.test_subjects
    )


def test_no_complete_target_horizon_is_rejected(manifest: SplitManifest) -> None:
    shortened = SplitManifest.model_validate(
        {
            **manifest.model_dump(),
            "evaluation_window": TimeWindow(start_utc=BASE, end_utc=BASE + HOUR),
        }
    )
    with pytest.raises(ValueError, match="no complete"):
        rolling_origins(shortened, "validation")


def test_future_and_backdated_records_cannot_change_earlier_predictions(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    observations, targets = cohort
    backdated = [
        Observation.model_validate(
            {**observation(s, -1, 250.0, delay=2).model_dump(), "record_id": f"backdated-{s}"}
        )
        for s in manifest.validation_subjects
    ]
    original = evaluate_forecast(manifest, observations + backdated, targets, last_value, config)
    altered = [
        o
        if available_by(o, BASE)
        else Observation.model_validate({**o.model_dump(), "value": 200.0})
        for o in observations
    ]
    changed = evaluate_forecast(manifest, altered + backdated, targets, last_value, config)
    assert [p for p in original.predictions if p.origin.cutoff == BASE] == [
        p for p in changed.predictions if p.origin.cutoff == BASE
    ]
    assert original.predictions[0].estimates[0] == ForecastEstimate(median=60.0)


def test_withheld_targets_and_missingness_never_change_predictions(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    observations, targets = cohort
    original = evaluate_forecast(manifest, observations, targets, last_value, config)
    changed = evaluate_forecast(
        manifest,
        observations,
        [target(t.subject_id, 0, 200.0) for t in targets if t.interval_start_utc == BASE],
        last_value,
        config,
    )
    assert changed.predictions == original.predictions
    assert changed.counts["missing_labels"] == 6
    assert original.metrics.mae is not None and original.metrics.mae.value == 1.0


def test_factory_gets_only_train_participants_and_available_prefixes(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    observations, targets = cohort
    observations = [
        *observations,
        *(
            Observation.model_validate(
                {**observation(s, -1, 250.0, delay=2).model_dump(), "record_id": f"delayed-{s}"}
            )
            for s in manifest.train_subjects
        ),
    ]
    captured: list[TrainingPrefix] = []

    def train_mean(training: TrainingPrefix) -> Predictor:
        captured.append(training)
        mean = fmean(o.value for o in training.observations)
        return lambda request: (ForecastEstimate(median=mean),) * len(request.targets)

    result = evaluate_forecast(manifest, observations, targets, train_mean, config)
    assert len(captured) == 1
    assert captured[0].fit_as_of == BASE
    assert set(captured[0].subjects) == set(manifest.train_subjects)
    assert {o.subject_id for o in captured[0].observations} == set(manifest.train_subjects)
    assert all(available_by(o, BASE) for o in captured[0].observations)
    changed = [
        o
        if o.subject_id in manifest.train_subjects and available_by(o, BASE)
        else Observation.model_validate({**o.model_dump(), "value": 250.0})
        for o in observations
    ]
    assert (
        evaluate_forecast(manifest, changed, targets, train_mean, config).predictions
        == result.predictions
    )


def test_incomplete_interval_and_record_exclusions_cannot_enter_features(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    observations, targets = cohort
    subject = manifest.validation_subjects[0]
    record = observation(subject, -1, 250.0)
    spanning = Observation.model_validate(
        {
            **record.model_dump(),
            "record_id": "incomplete",
            "end_utc": BASE + HOUR,
            "available_at_utc": BASE,
        }
    )
    excluded = Observation.model_validate({**record.model_dump(), "record_id": "quarantined"})
    split = SplitManifest.model_validate(
        {
            **manifest.model_dump(),
            "exclusions": [
                Exclusion(subject_id=subject, record_id="quarantined", reason="bad sensor")
            ],
        }
    )
    seen: list[ForecastInput] = []

    def factory(training: TrainingPrefix) -> Predictor:
        predictor = last_value(training)

        def predict(request: ForecastInput) -> tuple[ForecastEstimate | None, ...]:
            seen.append(request)
            return tuple(predictor(request))

        return predict

    result = evaluate_forecast(split, [*observations, spanning, excluded], targets, factory, config)
    prefix = next(r.history for r in seen if r.subject_id == subject and r.cutoff == BASE)
    assert not {"quarantined", "incomplete"} & {o.record_id for o in prefix}
    assert result.counts["excluded_observation_records"] == 1


def test_dataset_and_roster_mismatches_are_rejected_before_fitting(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    observations, targets = cohort
    wrong = Observation.model_validate({**observations[0].model_dump(), "dataset_id": "other"})
    with pytest.raises(ValueError, match="manifest dataset"):
        evaluate_forecast(manifest, [wrong, *observations[1:]], targets, last_value, config)
    unknown = Aggregate.model_validate({**targets[0].model_dump(), "subject_id": "unknown-subject"})
    with pytest.raises(ValueError, match="roster"):
        evaluate_forecast(manifest, observations, [unknown, *targets[1:]], last_value, config)


def test_population_only_predictors_never_receive_personal_prefix(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    population = EvaluationConfig.model_validate(
        {**config.model_dump(), "history_policy": "population_only"}
    )
    requests: list[ForecastInput] = []

    def factory(_: TrainingPrefix) -> Predictor:
        def predict(request: ForecastInput) -> tuple[None, ...]:
            requests.append(request)
            return (None,) * len(request.targets)

        return predict

    result = evaluate_forecast(manifest, *cohort, factory, population)
    assert requests and all(not r.history for r in requests)
    assert result.counts["abstained_points"] == result.counts["expected_points"]
    assert result.metrics.mae is None


def test_missing_labels_and_insufficient_history_reconcile_denominators(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    observations, targets = cohort
    subject = manifest.validation_subjects[0]
    observations = [o for o in observations if o.subject_id != subject]
    labels = [
        target(t.subject_id, int((t.interval_start_utc - BASE) / HOUR), None) for t in targets
    ]
    result = evaluate_forecast(manifest, observations, labels, last_value, config)
    assert result.counts["insufficient_history_points"] == 4
    assert result.counts["missing_labels"] == 4
    assert result.metrics.mae is None
    assert result.counts["expected_points"] == sum(
        result.counts[k]
        for k in (
            "scored_points",
            "missing_labels",
            "abstained_points",
            "insufficient_history_points",
        )
    )


def test_multiple_samples_in_one_hour_do_not_fake_history(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    observations, targets = cohort
    observations = [o for o in observations if o.subject_id in manifest.train_subjects]
    for s in manifest.validation_subjects:
        for i in range(10):
            o = observation(s, -1)
            observations.append(
                Observation.model_validate({**o.model_dump(), "record_id": f"many-{i}"})
            )
    assert (
        evaluate_forecast(manifest, observations, targets, last_value, config).counts[
            "predicted_origins"
        ]
        == 0
    )


def test_duplicate_bins_and_wrong_model_output_are_rejected(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    observations, targets = cohort
    with pytest.raises(ValueError, match="duplicate target"):
        evaluate_forecast(manifest, observations, [*targets, targets[0]], last_value, config)
    with pytest.raises(ValueError, match="duplicate observation"):
        evaluate_forecast(manifest, [*observations, observations[0]], targets, last_value, config)
    with pytest.raises(ValueError, match="one estimate"):
        evaluate_forecast(manifest, *cohort, lambda _: lambda request: (), config)
    with pytest.raises(ValueError, match="above"):
        evaluate_forecast(
            manifest,
            *cohort,
            lambda _: lambda request: (ForecastEstimate(median=301.0),) * len(request.targets),
            config,
        )


@pytest.mark.parametrize(
    "estimate",
    [
        {"median": float("nan")},
        {"median": float("inf")},
        {"median": 60.0, "lower": 50.0},
        {"median": 60.0, "lower": 61.0, "upper": 70.0},
    ],
)
def test_invalid_estimates_fail_at_boundary(estimate: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        ForecastEstimate.model_validate(estimate)


def test_metrics_weight_participants_not_rows_and_bootstrap_is_reproducible() -> None:
    points = [ScoredPoint("a", 60.0, 60.0, 59.0, 61.0)] * 100 + [
        ScoredPoint("b", 70.0, 60.0, 59.0, 61.0)
    ]
    params = dict(metric="heart_rate", unit="bpm", bootstrap_samples=1000, confidence=0.95, seed=42)
    result = forecast_metrics(points, **params)
    assert result == forecast_metrics(list(reversed(points)), **params)
    assert result.mae is not None and result.mae.value == 5.0
    assert result.rmse is not None and result.rmse.value == 5.0
    assert result.mae.confidence_interval == (0.0, 10.0)
    assert result.interval_coverage is not None and result.interval_coverage.value == 0.5
    singleton = forecast_metrics(points[:1], **params)
    assert singleton.mae is not None and singleton.mae.confidence_interval is None


def test_private_packet_hashes_and_provenance_cannot_be_relabelled(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
    tmp_path: Path,
) -> None:
    result = evaluate_forecast(manifest, *cohort, last_value, config)
    run = RunManifest(
        schema_version="0.1",
        run_id="synthetic-run",
        created_at_utc=BASE,
        git_sha="b" * 40,
        git_dirty=True,
        config_sha256=document_sha256(config),
        dataset_snapshot=manifest.dataset_snapshot,
        split_manifest_sha256=document_sha256(manifest),
        task=manifest.task,
        feature_order=["heart_rate"],
        model=ModelRef(
            model_id="synthetic-last-value",
            checkpoint_source=None,
            checkpoint_revision=None,
            license=None,
        ),
        environment_sha256="c" * 64,
        seed=manifest.seed,
        artifact=None,
        metrics_paths=["evaluation.json"],
    )
    output = tmp_path / "packet"
    hashes = write_packet(output, manifest, run, result)
    assert hashes == json.loads((output / "sha256.json").read_text())
    for name, digest in hashes.items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
        assert (output / name).stat().st_mode & 0o777 == 0o600
    assert output.stat().st_mode & 0o777 == 0o700
    assert SplitManifest.model_validate_json((output / "split.json").read_text()) == manifest
    with pytest.raises(FileExistsError):
        write_packet(output, manifest, run, result)
    with pytest.raises(ValueError, match="different split"):
        write_packet(
            tmp_path / "mismatch", manifest, run, replace(result, split_manifest_sha256="d" * 64)
        )
    assert not (tmp_path / "mismatch").exists()
