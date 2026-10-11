"""Paired model comparisons on common target support, with visible coverage differences."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from hachi.contracts.base import DataMode
from hachi.contracts.manifests import SplitManifest
from hachi.contracts.tables import Aggregate, Observation

from .forecast import (
    EvaluationConfig,
    EvaluationResult,
    PredictorFactory,
    evaluate_forecast,
)
from .metrics import (
    Estimate,
    MetricReport,
    ScoredPoint,
    bootstrap_participant_mean,
    forecast_metrics,
)
from .serialization import document_sha256
from .splits import Partition


@dataclass(frozen=True)
class ParticipantDifference:
    subject_id: str
    paired_points: int
    mae: float
    rmse: float
    median_pinball_loss: float
    paired_interval_points: int
    interval_coverage: float | None
    mean_interval_width: float | None


@dataclass(frozen=True)
class PairedMetrics:
    definition: str
    subjects: tuple[ParticipantDifference, ...]
    mae: Estimate | None
    rmse: Estimate | None
    median_pinball_loss: Estimate | None
    interval_coverage: Estimate | None
    mean_interval_width: Estimate | None


@dataclass(frozen=True)
class ComparisonSummary:
    data_mode: DataMode
    partition: Partition
    split_manifest_sha256: str
    baseline_result_sha256: str
    candidate_result_sha256: str
    counts: dict[str, int]
    baseline_on_paired_targets: MetricReport
    candidate_on_paired_targets: MetricReport
    difference: PairedMetrics


@dataclass(frozen=True)
class ComparisonResult:
    baseline: EvaluationResult
    candidate: EvaluationResult
    summary: ComparisonSummary


def _paired_metrics(
    baseline: MetricReport, candidate: MetricReport, config: EvaluationConfig, seed: int
) -> PairedMetrics:
    differences: list[ParticipantDifference] = []
    for b, c in zip(baseline.subjects, candidate.subjects, strict=True):
        # Both reports were computed from the same point and interval masks.
        differences.append(
            ParticipantDifference(
                b.subject_id,
                b.scored_points,
                c.mae - b.mae,
                c.rmse - b.rmse,
                c.median_pinball_loss - b.median_pinball_loss,
                b.interval_points,
                c.interval_coverage - b.interval_coverage
                if c.interval_coverage is not None and b.interval_coverage is not None
                else None,
                c.mean_interval_width - b.mean_interval_width
                if c.mean_interval_width is not None and b.mean_interval_width is not None
                else None,
            )
        )

    def interval(values: Sequence[float]) -> Estimate | None:
        return bootstrap_participant_mean(
            values, samples=config.bootstrap_samples, confidence=config.confidence, seed=seed
        )

    return PairedMetrics(
        "candidate minus baseline; bootstrap paired participant differences",
        tuple(differences),
        interval([d.mae for d in differences]),
        interval([d.rmse for d in differences]),
        interval([d.median_pinball_loss for d in differences]),
        interval([d.interval_coverage for d in differences if d.interval_coverage is not None]),
        interval([d.mean_interval_width for d in differences if d.mean_interval_width is not None]),
    )


def compare_forecasts(
    manifest: SplitManifest,
    observations: Sequence[Observation],
    targets: Sequence[Aggregate],
    baseline_factory: PredictorFactory,
    candidate_factory: PredictorFactory,
    *,
    baseline_config: EvaluationConfig,
    candidate_config: EvaluationConfig,
    partition: Partition = "validation",
) -> ComparisonResult:
    """Evaluate two frozen models, then pair by subject, cutoff and exact target bin.

    Error differences are conditional on joint labeled prediction coverage. Exclusive
    predictions and abstentions remain in the denominator and in both full reports;
    a favorable paired error alone does not justify promoting a selective model.
    """
    shared_fields = (
        "data_mode",
        "metric",
        "aggregation",
        "history_policy",
        "bootstrap_samples",
        "confidence",
    )
    for field in shared_fields:
        if getattr(baseline_config, field) != getattr(candidate_config, field):
            raise ValueError(f"paired comparisons require matching {field}")
    split_hash = document_sha256(manifest)
    observations = tuple(observations)
    targets = tuple(targets)
    baseline = evaluate_forecast(
        manifest, observations, targets, baseline_factory, baseline_config, partition=partition
    )
    candidate = evaluate_forecast(
        manifest, observations, targets, candidate_factory, candidate_config, partition=partition
    )
    if (
        baseline.split_manifest_sha256 != split_hash
        or candidate.split_manifest_sha256 != split_hash
    ):
        raise ValueError("split manifest changed during model evaluation")
    if baseline.plan != candidate.plan:
        raise ValueError("models did not use the same origin plan and history inclusion")
    baseline_predictions = {(p.origin.subject_id, p.origin.cutoff): p for p in baseline.predictions}
    candidate_predictions = {
        (p.origin.subject_id, p.origin.cutoff): p for p in candidate.predictions
    }
    if baseline_predictions.keys() != candidate_predictions.keys():
        raise ValueError("models did not predict the same eligible origins")
    labels = {
        (t.subject_id, t.interval_start_utc, t.interval_end_utc): t.value
        for t in targets
        if t.metric == baseline_config.metric
        and t.resolution == "hour"
        and t.aggregation == baseline_config.aggregation
    }
    paired_baseline: list[ScoredPoint] = []
    paired_candidate: list[ScoredPoint] = []
    counts: Counter[str] = Counter(
        {
            "evaluation_participants": baseline.counts["evaluation_participants"],
            "expected_points": baseline.counts["expected_points"],
            "insufficient_history_points": baseline.counts["insufficient_history_points"],
            "missing_labels": 0,
            "paired_points": 0,
            "baseline_only_points": 0,
            "candidate_only_points": 0,
            "both_abstained_points": 0,
            "paired_interval_points": 0,
        }
    )
    for key in sorted(baseline_predictions):
        b = baseline_predictions[key]
        c = candidate_predictions[key]
        for window, b_est, c_est in zip(b.origin.targets, b.estimates, c.estimates, strict=True):
            value = labels.get((key[0], window.start_utc, window.end_utc))
            if value is None:
                counts["missing_labels"] += 1
            elif b_est is None and c_est is None:
                counts["both_abstained_points"] += 1
            elif c_est is None:
                counts["baseline_only_points"] += 1
            elif b_est is None:
                counts["candidate_only_points"] += 1
            else:
                counts["paired_points"] += 1
                has_intervals = b_est.lower is not None and c_est.lower is not None
                counts["paired_interval_points"] += int(has_intervals)
                paired_baseline.append(
                    ScoredPoint(
                        key[0],
                        value,
                        b_est.median,
                        b_est.lower if has_intervals else None,
                        b_est.upper if has_intervals else None,
                    )
                )
                paired_candidate.append(
                    ScoredPoint(
                        key[0],
                        value,
                        c_est.median,
                        c_est.lower if has_intervals else None,
                        c_est.upper if has_intervals else None,
                    )
                )

    def metrics(points: Sequence[ScoredPoint]) -> MetricReport:
        return forecast_metrics(
            points,
            metric=baseline_config.metric,
            unit=baseline.metrics.unit,
            bootstrap_samples=baseline_config.bootstrap_samples,
            confidence=baseline_config.confidence,
            seed=manifest.seed,
        )

    b_metrics = metrics(paired_baseline)
    c_metrics = metrics(paired_candidate)
    counts["paired_participants"] = len(b_metrics.subjects)
    counts["baseline_scored_points"] = baseline.counts["scored_points"]
    counts["candidate_scored_points"] = candidate.counts["scored_points"]
    return ComparisonResult(
        baseline,
        candidate,
        ComparisonSummary(
            data_mode=baseline_config.data_mode,
            partition=partition,
            split_manifest_sha256=split_hash,
            baseline_result_sha256=document_sha256(baseline),
            candidate_result_sha256=document_sha256(candidate),
            counts=dict(sorted(counts.items())),
            baseline_on_paired_targets=b_metrics,
            candidate_on_paired_targets=c_metrics,
            difference=_paired_metrics(b_metrics, c_metrics, baseline_config, manifest.seed),
        ),
    )
