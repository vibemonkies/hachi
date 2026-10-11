"""Canonical hourly features to Chronos-2 context requests, and quantiles back to estimates.

Chronos-2 runs only in the pinned GX10 runtime, which cannot import Hachi. The CPU harness
therefore runs twice: once recording the exact causal context each prediction would see,
and once replaying the GX10 forecasts for those contexts by content hash. A context the
harness did not produce has no forecast, so nothing outside the causal prefix can be scored.
"""

from collections import Counter
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, Sha256, Text
from hachi.contracts.causality import available_by
from hachi.contracts.metrics import METRICS, Aggregation, Metric
from hachi.evaluation import (
    ForecastEstimate,
    ForecastInput,
    HourlyFeature,
    Predictor,
    PredictorFactory,
    TrainingPrefix,
)

from .inference import MODEL_CONTEXT_LIMIT, MODEL_HORIZON_LIMIT, request_id

HOUR = timedelta(hours=1)


class ChronosModelPin(Contract):
    """The #1-verified checkpoint and runtime; see infra/gx10/model.json and README."""

    model_id: Literal["amazon/chronos-2"]
    revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    weights_sha256: Sha256
    license: Text
    runtime_lock_sha256: Sha256


class ChronosConfig(Contract):
    """Zero-shot univariate forecasting of one hourly derived series.

    No covariates of any kind: measured physiology is never known in the future, and
    the harness hands a predictor only the configured metric's history.
    """

    model: ChronosModelPin
    metric: Metric
    aggregation: Aggregation
    context_hours: Annotated[int, Field(gt=0, le=MODEL_CONTEXT_LIMIT)]
    min_context_values: Annotated[int, Field(gt=0)] = 1
    interval_lower: Annotated[float, Field(gt=0, lt=0.5)] = 0.1
    interval_upper: Annotated[float, Field(gt=0.5, lt=1)] = 0.9
    covariates: Literal["none"] = "none"
    batch_size: Annotated[int, Field(gt=0)] = 256

    @model_validator(mode="after")
    def _policy(self) -> Self:
        if self.aggregation not in METRICS[self.metric].aggregations:
            raise ValueError("Chronos adapter requires the registered metric aggregation")
        if self.min_context_values > self.context_hours:
            raise ValueError("minimum context values must fit inside the context window")
        return self

    @property
    def nominal_coverage(self) -> float:
        return round(self.interval_upper - self.interval_lower, 10)


class UnsupportedInput(ValueError):
    """A history row the adapter refuses rather than silently dropping."""


@dataclass(frozen=True)
class ContextRequest:
    request_id: str
    context: tuple[float | None, ...]
    prediction_length: int
    steps: tuple[int, ...]

    def row(self) -> dict[str, object]:
        """What the GX10 receives: the context and horizon only, no steps or identities."""
        return {
            "request_id": self.request_id,
            "context": list(self.context),
            "prediction_length": self.prediction_length,
        }


def _hour_aligned(value: datetime) -> bool:
    return not (value.minute or value.second or value.microsecond)


def build_request(request: ForecastInput, config: ChronosConfig) -> ContextRequest | None:
    """One regular hourly grid ending at the cutoff; absent hours stay missing (null).

    Returns None (abstain) when fewer than `min_context_values` hours are observed.
    """
    cutoff = request.cutoff
    if not _hour_aligned(cutoff):
        raise UnsupportedInput("Chronos contexts need an hour-aligned UTC cutoff")
    start = cutoff - config.context_hours * HOUR
    grid: dict[datetime, float] = {}
    for row in request.history:
        if not isinstance(row, HourlyFeature):
            raise UnsupportedInput(
                "the Chronos adapter consumes derived hourly features; raw observations "
                "need an explicit aggregation policy upstream"
            )
        if row.metric != config.metric or row.aggregate.aggregation != config.aggregation:
            raise UnsupportedInput(
                "unsupported channel: the adapter forecasts one univariate series and "
                "takes no covariates"
            )
        if not available_by(row, cutoff):
            raise ValueError("history row was not available at the cutoff")
        if row.start_utc < start:
            continue
        if row.start_utc in grid:
            raise ValueError("duplicate hourly bins in history")
        grid[row.start_utc] = row.value
    context = tuple(grid.get(start + i * HOUR) for i in range(config.context_hours))
    steps: list[int] = []
    for window in request.targets:
        offset = window.start_utc - cutoff
        if (
            window.end_utc - window.start_utc != HOUR
            or not _hour_aligned(window.start_utc)
            or offset < timedelta(0)
        ):
            raise UnsupportedInput("targets must be whole UTC hours at or after the cutoff")
        steps.append(offset // HOUR)
    length = max(steps) + 1
    if length > MODEL_HORIZON_LIMIT:
        raise UnsupportedInput("target horizon exceeds the model's output limit")
    if sum(v is not None for v in context) < config.min_context_values:
        return None
    return ContextRequest(request_id(context, length), context, length, tuple(steps))


@dataclass
class AdapterLog:
    """Counts and per-origin quantiles kept beside the harness's own result."""

    counts: Counter[str] = field(default_factory=Counter)
    # (subject, cutoff) -> one row of raw quantiles per target bin, in target order.
    quantiles: dict[tuple[str, datetime], tuple[tuple[float, ...], ...]] = field(
        default_factory=dict
    )


def _level_index(levels: Sequence[float], level: float) -> int:
    for index, value in enumerate(levels):
        if abs(value - level) < 1e-9:
            return index
    raise ValueError(f"quantile level {level} is not among the model's levels")


def estimates(
    quantiles: Sequence[Sequence[float]],
    levels: Sequence[float],
    steps: Sequence[int],
    config: ChronosConfig,
    log: AdapterLog | None = None,
) -> tuple[tuple[ForecastEstimate, ...], tuple[tuple[float, ...], ...]]:
    """Median and central interval per target step, within the metric's physical bounds.

    Crossing quantiles are rearranged (sorted), which never increases quantile loss.
    Clipping to registered bounds only removes physically impossible values.
    """
    low, mid, high = (
        _level_index(levels, q) for q in (config.interval_lower, 0.5, config.interval_upper)
    )
    spec = METRICS[config.metric]
    lo_bound = spec.minimum if spec.minimum is not None else float("-inf")
    hi_bound = spec.maximum if spec.maximum is not None else float("inf")
    counts: Counter[str] = Counter()
    output: list[ForecastEstimate] = []
    kept: list[tuple[float, ...]] = []
    for step in steps:
        raw = list(quantiles[step])
        ordered = sorted(raw)
        counts["rearranged_steps"] += ordered != raw
        bounded = [min(max(v, lo_bound), hi_bound) for v in ordered]
        counts["clipped_quantiles"] += sum(a != b for a, b in zip(ordered, bounded, strict=True))
        kept.append(tuple(bounded))
        output.append(
            ForecastEstimate(median=bounded[mid], lower=bounded[low], upper=bounded[high])
        )
    if log is not None:
        log.counts.update(counts)
    return tuple(output), tuple(kept)


def recording_factory(
    config: ChronosConfig, sink: MutableMapping[str, ContextRequest], log: AdapterLog
) -> PredictorFactory:
    """Export pass: record each causal context and abstain; no forecast exists yet."""

    def fit(_: TrainingPrefix) -> Predictor:
        def predict(request: ForecastInput) -> tuple[None, ...]:
            built = build_request(request, config)
            if built is None:
                log.counts["abstained_origins_short_context"] += 1
            else:
                log.counts["requested_origins"] += 1
                sink.setdefault(built.request_id, built)
            return (None,) * len(request.targets)

        return predict

    return fit


def replay_factory(
    config: ChronosConfig,
    forecasts: Mapping[str, Sequence[Sequence[float]]],
    levels: Sequence[float],
    log: AdapterLog,
) -> PredictorFactory:
    """Scoring pass: zero-shot, so the training prefix is unused; look up by content hash."""

    def fit(_: TrainingPrefix) -> Predictor:
        def predict(request: ForecastInput) -> tuple[ForecastEstimate | None, ...]:
            built = build_request(request, config)
            if built is None:
                log.counts["abstained_origins_short_context"] += 1
                return (None,) * len(request.targets)
            quantiles = forecasts.get(built.request_id)
            if quantiles is None:
                raise ValueError("no GX10 forecast for this causal context; export again")
            if len(quantiles) != built.prediction_length:
                raise ValueError("forecast horizon does not match the request")
            log.counts["predicted_origins"] += 1
            output, kept = estimates(quantiles, levels, built.steps, config, log)
            log.quantiles[(request.subject_id, request.cutoff)] = kept
            return output

        return predict

    return fit
