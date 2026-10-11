import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from hachi.contracts.manifests import ModelRef, RunManifest, SplitManifest
from hachi.contracts.tables import Aggregate, Observation
from hachi.evaluation import (
    EvaluationConfig,
    ForecastEstimate,
    ForecastInput,
    Predictor,
    PredictorFactory,
    TrainingPrefix,
    compare_forecasts,
    document_sha256,
    write_comparison_packet,
)

from .conftest import BASE, HOUR, target


def constant(value: float | None) -> PredictorFactory:
    def factory(_: TrainingPrefix) -> Predictor:
        estimate = ForecastEstimate(median=value) if value is not None else None
        return lambda request: (estimate,) * len(request.targets)

    return factory


def test_paired_bootstrap_preserves_correlation_between_models(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    subjects = sorted(manifest.validation_subjects)

    def factory(offset: float) -> PredictorFactory:
        def fit(_: TrainingPrefix) -> Predictor:
            def predict(request: ForecastInput) -> tuple[ForecastEstimate, ...]:
                median = (71.0 if request.subject_id == subjects[0] else 161.0) + offset
                return (ForecastEstimate(median=median),) * len(request.targets)

            return predict

        return fit

    report = compare_forecasts(
        manifest,
        *cohort,
        factory(0.0),
        factory(-1.0),
        baseline_config=config,
        candidate_config=config,
    )
    assert report.summary.baseline_on_paired_targets.mae.value == 55.0
    assert report.summary.candidate_on_paired_targets.mae.value == 54.0
    difference = report.summary.difference.mae
    assert difference is not None and difference.value == -1.0
    assert difference.participants == 2
    assert difference.confidence_interval == (-1.0, -1.0)
    assert [p.mae for p in report.summary.difference.subjects] == [-1.0, -1.0]
    assert report.summary.difference.rmse.value == -1.0


def test_selective_candidate_cannot_hide_coverage_or_change_baseline_support(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    observations, targets = cohort
    targets = [
        target(
            t.subject_id,
            int((t.interval_start_utc - BASE) / HOUR),
            200.0 if t.interval_start_utc == BASE else 61.0,
        )
        for t in targets
    ]

    def selective(_: TrainingPrefix) -> Predictor:
        return lambda request: tuple(
            None if w.start_utc == BASE else ForecastEstimate(median=61.0) for w in request.targets
        )

    result = compare_forecasts(
        manifest,
        observations,
        targets,
        constant(60.0),
        selective,
        baseline_config=config,
        candidate_config=config,
    )
    assert result.baseline.metrics.mae.value == 35.75
    assert result.summary.baseline_on_paired_targets.mae.value == 1.0
    assert result.summary.candidate_on_paired_targets.mae.value == 0.0
    assert result.summary.counts["expected_points"] == 8
    assert result.summary.counts["paired_points"] == 6
    assert result.summary.counts["baseline_only_points"] == 2
    assert result.summary.counts["baseline_scored_points"] == 8
    assert result.summary.counts["candidate_scored_points"] == 6
    swapped = compare_forecasts(
        manifest,
        observations,
        targets,
        selective,
        constant(60.0),
        baseline_config=config,
        candidate_config=config,
    )
    assert swapped.summary.counts["candidate_only_points"] == 2
    assert swapped.summary.difference.mae.value == -result.summary.difference.mae.value


def test_identical_models_have_zero_paired_difference_and_stable_order(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    result = compare_forecasts(
        manifest,
        *cohort,
        constant(60.0),
        constant(60.0),
        baseline_config=config,
        candidate_config=config,
    )
    assert result.summary.difference.mae.value == 0.0
    assert result.summary.difference.mae.confidence_interval == (0.0, 0.0)
    reversed_result = compare_forecasts(
        manifest,
        list(reversed(cohort[0])),
        list(reversed(cohort[1])),
        constant(60.0),
        constant(60.0),
        baseline_config=config,
        candidate_config=config,
    )
    assert reversed_result == result


def test_no_common_predictions_has_no_invented_difference(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    result = compare_forecasts(
        manifest,
        *cohort,
        constant(60.0),
        constant(None),
        baseline_config=config,
        candidate_config=config,
    )
    assert result.summary.difference.mae is None
    assert result.summary.counts["paired_participants"] == 0
    assert result.summary.counts["baseline_only_points"] == 8


def test_denominators_include_missingness_abstentions_and_history_exclusions(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    observations, targets = cohort
    excluded = manifest.validation_subjects[0]
    observations = [o for o in observations if o.subject_id != excluded]
    targets = [
        target(
            t.subject_id,
            int((t.interval_start_utc - BASE) / HOUR),
            None if t.interval_start_utc == BASE else 61.0,
        )
        for t in targets
    ]

    def selective_factory(candidate: bool) -> PredictorFactory:
        def factory(_: TrainingPrefix) -> Predictor:
            return lambda request: tuple(
                None
                if w.start_utc == BASE + 3 * HOUR or (candidate and w.start_utc == BASE + HOUR)
                else ForecastEstimate(median=60.0)
                for w in request.targets
            )

        return factory

    result = compare_forecasts(
        manifest,
        observations,
        targets,
        selective_factory(False),
        selective_factory(True),
        baseline_config=config,
        candidate_config=config,
    )
    counts = result.summary.counts
    assert counts["insufficient_history_points"] == 4
    assert counts["missing_labels"] == 1
    assert counts["baseline_only_points"] == 1
    assert counts["both_abstained_points"] == 1
    assert counts["paired_points"] == 1
    assert counts["expected_points"] == sum(
        counts[k]
        for k in (
            "insufficient_history_points",
            "missing_labels",
            "paired_points",
            "baseline_only_points",
            "candidate_only_points",
            "both_abstained_points",
        )
    )
    assert result.summary.difference.mae.confidence_interval is None


def test_interval_comparisons_use_joint_interval_support(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    def baseline(_: TrainingPrefix) -> Predictor:
        return lambda request: (
            (ForecastEstimate(median=60.0, lower=59.0, upper=63.0),) * len(request.targets)
        )

    def candidate(_: TrainingPrefix) -> Predictor:
        return lambda request: tuple(
            ForecastEstimate(median=61.0, lower=60.0, upper=62.0)
            if w.start_utc == BASE
            else ForecastEstimate(median=61.0)
            for w in request.targets
        )

    result = compare_forecasts(
        manifest,
        *cohort,
        baseline,
        candidate,
        baseline_config=config,
        candidate_config=config,
    )
    assert result.summary.counts["paired_interval_points"] == 2
    assert result.baseline.metrics.subjects[0].interval_points == 4
    assert result.summary.baseline_on_paired_targets.subjects[0].interval_points == 1
    assert result.summary.difference.interval_coverage.value == 0.0
    assert result.summary.difference.mean_interval_width.value == -2.0
    no_intervals = compare_forecasts(
        manifest,
        *cohort,
        baseline,
        constant(61.0),
        baseline_config=config,
        candidate_config=config,
    )
    assert no_intervals.summary.difference.interval_coverage is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("history_policy", "population_only"),
        ("aggregation", "median"),
        ("data_mode", "real"),
        ("metric", "respiratory_rate"),
        ("confidence", 0.9),
        ("bootstrap_samples", 50),
    ],
)
def test_incompatible_protocols_are_rejected_before_fitting(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
    field: str,
    value: str | float | int,
) -> None:
    other = EvaluationConfig.model_validate({**config.model_dump(), field: value})

    def forbidden(_: TrainingPrefix) -> Predictor:
        raise AssertionError("model must not fit on an incompatible comparison")

    with pytest.raises(ValueError, match=field):
        compare_forecasts(
            manifest,
            *cohort,
            forbidden,
            forbidden,
            baseline_config=config,
            candidate_config=other,
        )


def test_model_specific_overlap_disclosures_are_retained(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
) -> None:
    candidate_config = EvaluationConfig.model_validate(
        {
            **config.model_dump(),
            "pretrained_cohort_overlap": "unknown",
            "overlap_note": "Synthetic example of a model-specific unknown-overlap limitation.",
        }
    )
    result = compare_forecasts(
        manifest,
        *cohort,
        constant(60.0),
        constant(61.0),
        baseline_config=config,
        candidate_config=candidate_config,
    )
    assert result.candidate.config.pretrained_cohort_overlap == "unknown"
    assert result.baseline.config.pretrained_cohort_overlap == "not_applicable"


def test_comparison_packet_binds_two_runs_and_rejects_mismatched_provenance(
    manifest: SplitManifest,
    config: EvaluationConfig,
    cohort: tuple[list[Observation], list[Aggregate]],
    tmp_path: Path,
) -> None:
    result = compare_forecasts(
        manifest,
        *cohort,
        constant(60.0),
        constant(61.0),
        baseline_config=config,
        candidate_config=config,
    )

    def run(run_id: str) -> RunManifest:
        return RunManifest(
            schema_version="0.1",
            run_id=run_id,
            created_at_utc=BASE,
            git_sha="b" * 40,
            git_dirty=True,
            config_sha256=document_sha256(config),
            dataset_snapshot=manifest.dataset_snapshot,
            split_manifest_sha256=document_sha256(manifest),
            task=manifest.task,
            feature_order=["heart_rate"],
            model=ModelRef(
                model_id=run_id, checkpoint_source=None, checkpoint_revision=None, license=None
            ),
            environment_sha256="c" * 64,
            seed=manifest.seed,
            artifact=None,
            metrics_paths=["evaluation.json"],
        )

    b_run, c_run = run("synthetic-baseline"), run("synthetic-candidate")
    output = tmp_path / "comparison"
    hashes = write_comparison_packet(output, manifest, b_run, c_run, result)
    for name, digest in hashes.items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    for model in ("baseline", "candidate"):
        for name, digest in json.loads((output / model / "sha256.json").read_text()).items():
            assert hashlib.sha256((output / model / name).read_bytes()).hexdigest() == digest
    summary = json.loads((output / "comparison.json").read_text())
    assert summary["data_mode"] == "synthetic" and summary["partition"] == "validation"
    assert summary["baseline_result_sha256"] == hashes["baseline/evaluation.json"]
    assert summary["candidate_result_sha256"] == hashes["candidate/evaluation.json"]
    assert (output / "baseline").stat().st_mode & 0o777 == 0o700
    assert (output / "comparison.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_comparison_packet(output, manifest, b_run, c_run, result)
    mismatch = replace(result, summary=replace(result.summary, candidate_result_sha256="d" * 64))
    with pytest.raises(ValueError, match="summary"):
        write_comparison_packet(tmp_path / "mismatch", manifest, b_run, c_run, mismatch)
    assert not (tmp_path / "mismatch").exists()
    bad_run = RunManifest.model_validate({**c_run.model_dump(), "config_sha256": "d" * 64})
    with pytest.raises(ValueError, match="config hash"):
        write_comparison_packet(tmp_path / "bad-run", manifest, b_run, bad_run, result)
    assert not (tmp_path / "bad-run").exists()
