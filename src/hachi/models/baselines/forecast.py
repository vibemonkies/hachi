"""Simple hourly level comparators fitted only from the evaluator's training prefix."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean, median
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, Sha256, UtcDatetime
from hachi.contracts.causality import available_by
from hachi.contracts.metrics import METRICS, Aggregation, Metric
from hachi.contracts.tables import Observation
from hachi.evaluation import (
    ForecastEstimate,
    ForecastInput,
    Predictor,
    PredictorFactory,
    TrainingPrefix,
)
from hachi.evaluation.serialization import document_sha256

HOUR = timedelta(hours=1)


class BaselineConfig(Contract):
    method: Literal["last_valid", "seasonal_naive", "train_population_mean"]
    metric: Metric
    aggregation: Aggregation
    max_age_hours: Annotated[int, Field(gt=0)] = 48
    seasonal_period_hours: Annotated[int, Field(gt=0)] = 24
    min_samples_per_hour: Annotated[int, Field(gt=0)] = 1

    @model_validator(mode="after")
    def _level_metric(self) -> Self:
        spec = METRICS[self.metric]
        if spec.kind != "level" or self.aggregation not in spec.aggregations:
            raise ValueError("hourly level baselines require a compatible level aggregation")
        return self


@dataclass(frozen=True)
class HourlyValue:
    start: datetime
    value: float
    available_at: datetime
    samples: int


def hourly_values(
    observations: Sequence[Observation], config: BaselineConfig, cutoff: datetime
) -> tuple[HourlyValue, ...]:
    """Use only completed UTC bins and records available at the requested instant.

    A source interval spanning hours is omitted rather than prorated. Sample counts
    enforce the declared inclusion policy; they do not establish time coverage.
    """
    bins: dict[datetime, list[Observation]] = defaultdict(list)
    for row in observations:
        if row.metric != config.metric or not available_by(row, cutoff):
            continue
        start = row.start_utc.replace(minute=0, second=0, microsecond=0)
        if start + HOUR <= cutoff and row.end_utc <= start + HOUR:
            bins[start].append(row)
    output: list[HourlyValue] = []
    for start, rows in sorted(bins.items()):
        if len(rows) < config.min_samples_per_hour:
            continue
        values = [r.value for r in rows]
        match config.aggregation:
            case "mean":
                value = fmean(values)
            case "median":
                value = median(values)
            case "min":
                value = min(values)
            case "max":
                value = max(values)
            case _:
                raise AssertionError("validated level aggregation")
        output.append(HourlyValue(start, value, max(r.available_at_utc for r in rows), len(rows)))
    return tuple(output)


class BaselineArtifact(Contract):
    format_version: Literal["hourly-baseline-1"] = "hourly-baseline-1"
    config: BaselineConfig
    fit_as_of: UtcDatetime
    training_prefix_sha256: Sha256
    training_participants: Annotated[int, Field(ge=0)]
    training_hours: Annotated[int, Field(ge=0)]
    population_mean: float | None

    @model_validator(mode="after")
    def _fitted_state(self) -> Self:
        fitted = self.config.method == "train_population_mean" and self.training_hours > 0
        if fitted != (self.population_mean is not None):
            raise ValueError("only a nonempty train-mean fit may contain a population mean")
        if self.population_mean is not None:
            spec = METRICS[self.config.metric]
            if spec.minimum is not None and self.population_mean < spec.minimum:
                raise ValueError("population mean is below the metric bound")
            if spec.maximum is not None and self.population_mean > spec.maximum:
                raise ValueError("population mean is above the metric bound")
        return self

    @property
    def model_id(self) -> str:
        return {
            "last_valid": "hourly-last-valid-v1",
            "seasonal_naive": "utc-seasonal-naive-v1",
            "train_population_mean": "train-population-mean-v1",
        }[self.config.method]

    def predict(self, request: ForecastInput) -> tuple[ForecastEstimate | None, ...]:
        if request.cutoff < self.fit_as_of:
            raise ValueError("prediction cutoff precedes the model's fit cutoff")
        if self.config.method == "train_population_mean":
            value = (
                ForecastEstimate(median=self.population_mean)
                if self.population_mean is not None
                else None
            )
            return (value,) * len(request.targets)
        values = hourly_values(request.history, self.config, request.cutoff)
        earliest = request.cutoff - self.config.max_age_hours * HOUR
        eligible = {v.start: v for v in values if v.start >= earliest}
        if self.config.method == "last_valid":
            last = eligible[max(eligible)].value if eligible else None
            return (ForecastEstimate(median=last) if last is not None else None,) * len(
                request.targets
            )
        period = self.config.seasonal_period_hours * HOUR
        estimates: list[ForecastEstimate | None] = []
        for target in request.targets:
            phase = target.start_utc - period
            while phase + HOUR > request.cutoff:
                phase -= period
            # Use this exact latest completed seasonal bin; missingness is abstention.
            row = eligible.get(phase)
            estimates.append(ForecastEstimate(median=row.value) if row is not None else None)
        return tuple(estimates)


def fit_baseline(training: TrainingPrefix, config: BaselineConfig) -> BaselineArtifact:
    by_subject: dict[str, list[Observation]] = defaultdict(list)
    for row in training.observations:
        by_subject[row.subject_id].append(row)
    series = [hourly_values(rows, config, training.fit_as_of) for rows in by_subject.values()]
    nonempty = [rows for rows in series if rows]
    # Equal participant weight prevents densely sampled participants dominating the fit.
    population = (
        fmean(fmean(r.value for r in rows) for rows in nonempty)
        if nonempty and config.method == "train_population_mean"
        else None
    )
    return BaselineArtifact(
        config=config,
        fit_as_of=training.fit_as_of,
        training_prefix_sha256=document_sha256(training),
        training_participants=len(nonempty),
        training_hours=sum(len(rows) for rows in nonempty),
        population_mean=population,
    )


def baseline_factory(config: BaselineConfig) -> PredictorFactory:
    def fit(training: TrainingPrefix) -> Predictor:
        return fit_baseline(training, config).predict

    return fit
