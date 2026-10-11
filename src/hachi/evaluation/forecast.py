"""CPU-only evaluator: factories see training prefixes; predictors never see targets."""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, DataMode, Text
from hachi.contracts.causality import available_by
from hachi.contracts.manifests import SplitManifest, TimeWindow
from hachi.contracts.metrics import METRICS, Aggregation, Metric, check_metric_value
from hachi.contracts.tables import Aggregate, Observation

from .metrics import MetricReport, ScoredPoint, forecast_metrics
from .serialization import document_sha256
from .splits import Origin, OriginExclusion, OriginPlan, Partition, rolling_origins


class EvaluationConfig(Contract):
    """Internal experiment configuration, not a replacement for the API contracts."""

    data_mode: DataMode
    metric: Metric
    aggregation: Aggregation
    history_policy: Literal["population_only", "causal_prefix"]
    pretrained_cohort_overlap: Literal["not_applicable", "none", "known", "unknown"]
    overlap_note: Text
    bootstrap_samples: Annotated[int, Field(ge=2)]
    confidence: Annotated[float, Field(gt=0, lt=1)]

    @model_validator(mode="after")
    def _metric(self) -> Self:
        spec = METRICS[self.metric]
        if self.aggregation not in spec.aggregations or spec.kind != "level":
            raise ValueError("this initial hourly evaluator supports level metrics only")
        return self


class ForecastEstimate(Contract):
    median: float
    lower: float | None = None
    upper: float | None = None

    @model_validator(mode="after")
    def _interval(self) -> Self:
        if (self.lower is None) != (self.upper is None):
            raise ValueError("give both interval bounds or neither")
        if (
            self.lower is not None
            and self.upper is not None
            and not self.lower <= self.median <= self.upper
        ):
            raise ValueError("interval must contain the median")
        return self


@dataclass(frozen=True)
class TrainingPrefix:
    fit_as_of: datetime
    subjects: tuple[str, ...]
    observations: tuple[Observation, ...]


@dataclass(frozen=True)
class ForecastInput:
    subject_id: str
    cutoff: datetime
    targets: tuple[TimeWindow, ...]
    history: tuple[Observation, ...]


type Predictor = Callable[[ForecastInput], Sequence[ForecastEstimate | None]]
type PredictorFactory = Callable[[TrainingPrefix], Predictor]


@dataclass(frozen=True)
class Prediction:
    origin: Origin
    estimates: tuple[ForecastEstimate | None, ...]


@dataclass(frozen=True)
class EvaluationResult:
    split_manifest_sha256: str
    config: EvaluationConfig
    plan: OriginPlan
    predictions: tuple[Prediction, ...]
    counts: dict[str, int]
    metrics: MetricReport


def _observation_order(o: Observation) -> tuple[datetime, datetime, str]:
    return o.end_utc, o.available_at_utc, o.record_id


def evaluate_forecast(
    manifest: SplitManifest,
    observations: Sequence[Observation],
    targets: Sequence[Aggregate],
    factory: PredictorFactory,
    config: EvaluationConfig,
    *,
    partition: Partition = "validation",
) -> EvaluationResult:
    """Fit once at the first cutoff, then score a label-independent hourly schedule.

    Caller-supplied factories must not capture uncensored data in their closures. We
    can enforce what we pass to a model, not audit arbitrary Python model internals.
    Raw observations supply availability; aggregates are used only as future labels.
    """
    plan = rolling_origins(manifest, partition)
    assigned = set(manifest.train_subjects + manifest.validation_subjects + manifest.test_subjects)
    excluded_subjects = {e.subject_id for e in manifest.exclusions if e.record_id is None}
    allowed = assigned | excluded_subjects
    dataset_id = manifest.dataset_snapshot.dataset_id
    if any(o.dataset_id != dataset_id or o.subject_id not in allowed for o in observations):
        raise ValueError("observations must belong to the manifest dataset and roster")
    if any(t.dataset_id != dataset_id or t.subject_id not in allowed for t in targets):
        raise ValueError("targets must belong to the manifest dataset and roster")
    keys = [(o.subject_id, o.record_id) for o in observations]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate observation record ids; ingestion must deduplicate first")
    excluded_records = {(e.subject_id, e.record_id) for e in manifest.exclusions}
    usable = [
        o
        for o in observations
        if o.metric == config.metric
        and (o.subject_id, o.record_id) not in excluded_records
        and o.subject_id not in excluded_subjects
    ]
    label_rows = [
        t
        for t in targets
        if t.metric == config.metric
        and t.resolution == "hour"
        and t.aggregation == config.aggregation
    ]
    labels = {(t.subject_id, t.interval_start_utc, t.interval_end_utc): t for t in label_rows}
    if len(labels) != len(label_rows):
        raise ValueError("duplicate target bins; ingestion must resolve source precedence first")
    fit_at = min(o.cutoff for o in plan.origins)
    train_ids = set(manifest.train_subjects)
    training = tuple(
        sorted(
            (o for o in usable if o.subject_id in train_ids and available_by(o, fit_at)),
            key=lambda o: (o.subject_id, *_observation_order(o)),
        )
    )
    predictor = factory(TrainingPrefix(fit_at, tuple(sorted(train_ids)), training))
    predictions: list[Prediction] = []
    scored: list[ScoredPoint] = []
    exclusions = list(plan.exclusions)
    counts: Counter[str] = Counter(
        {
            "roster_participants": len(allowed),
            "assigned_participants": len(assigned),
            "excluded_participants": len(excluded_subjects),
            "excluded_observation_records": sum(
                (o.subject_id, o.record_id) in excluded_records for o in observations
            ),
            "evaluation_participants": len(
                manifest.validation_subjects
                if partition == "validation"
                else manifest.test_subjects
            ),
            "training_observations": len(training),
            "planned_origins": len(plan.origins),
            "expected_points": sum(len(o.targets) for o in plan.origins),
            "scored_points": 0,
            "missing_labels": 0,
            "abstained_points": 0,
            "insufficient_history_points": 0,
        }
    )
    for origin in plan.origins:
        start = origin.cutoff - timedelta(hours=manifest.lookback_hours)
        history = tuple(
            sorted(
                (
                    o
                    for o in usable
                    if o.subject_id == origin.subject_id
                    and o.start_utc >= start
                    and available_by(o, origin.cutoff)
                ),
                key=_observation_order,
            )
        )
        observed_hours = {
            o.start_utc.replace(minute=0, second=0, microsecond=0)
            for o in history
            if o.start_utc < origin.cutoff
        }
        if len(observed_hours) < manifest.min_history_hours:
            exclusions.append(
                OriginExclusion(origin.subject_id, origin.cutoff, "insufficient_history")
            )
            counts["insufficient_history_points"] += len(origin.targets)
            continue
        model_input = ForecastInput(
            origin.subject_id,
            origin.cutoff,
            origin.targets,
            history if config.history_policy == "causal_prefix" else (),
        )
        estimates = tuple(predictor(model_input))
        if len(estimates) != len(origin.targets):
            raise ValueError("predictor must return one estimate or abstention per target bin")
        for estimate in estimates:
            if estimate is not None:
                for value in (estimate.median, estimate.lower, estimate.upper):
                    if value is not None:
                        check_metric_value(
                            config.metric,
                            METRICS[config.metric].unit,
                            value,
                            3600,
                            "forecast estimate",
                        )
        predictions.append(Prediction(origin, estimates))
        # Predictions are generated before any target value or missingness is inspected.
        for target, estimate in zip(origin.targets, estimates, strict=True):
            label = labels.get((origin.subject_id, target.start_utc, target.end_utc))
            if label is None or label.value is None:
                counts["missing_labels"] += 1
            elif estimate is None:
                counts["abstained_points"] += 1
            else:
                scored.append(
                    ScoredPoint(
                        origin.subject_id,
                        label.value,
                        estimate.median,
                        estimate.lower,
                        estimate.upper,
                    )
                )
                counts["scored_points"] += 1
    counts["scored_participants"] = len({p.subject_id for p in scored})
    counts["predicted_origins"] = len(predictions)
    for reason in ("overlapping_targets", "target_outside_window", "insufficient_history"):
        counts[f"excluded_origins_{reason}"] = sum(e.reason == reason for e in exclusions)
    metrics = forecast_metrics(
        scored,
        metric=config.metric,
        unit=METRICS[config.metric].unit,
        bootstrap_samples=config.bootstrap_samples,
        confidence=config.confidence,
        seed=manifest.seed,
    )
    return EvaluationResult(
        document_sha256(manifest),
        config,
        OriginPlan(partition, plan.origins, tuple(exclusions)),
        tuple(predictions),
        dict(sorted(counts.items())),
        metrics,
    )
