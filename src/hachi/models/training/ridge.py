"""Ridge task heads over handcrafted or frozen Chronos-2 features; data-only artifacts.

One ridge regression per lead predicts the next hour's value minus an offset: the
context mean (personal), the training population mean (population), or the context
location Chronos-2 reports with its embedding. The penalty is chosen on a temporal
holdout of the training participants' own windows, then the head is refit on every
training window. Fitting needs NumPy; inference replays the stored weights.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from statistics import fmean, pstdev
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, Sha256, UtcDatetime
from hachi.contracts.metrics import METRICS, Metric
from hachi.evaluation import (
    ForecastEstimate,
    ForecastInput,
    HourlyFeature,
    Predictor,
    PredictorFactory,
    TrainingPrefix,
)
from hachi.evaluation.context import hourly_grid
from hachi.evaluation.serialization import document_sha256

from ..chronos.inference import request_id
from .windows import Window, training_windows

HOUR = timedelta(hours=1)
HANDCRAFTED = (
    "last_value",
    "mean_6h",
    "mean_24h",
    "mean_48h",
    "std_48h",
    "observed_fraction",
    "hours_since_last_value",
)
CALENDAR = ("cutoff_hour_sin", "cutoff_hour_cos")

# request_id of a 48 h context -> (pooled embedding, location, scale) from the GX10.
type Embeddings = Mapping[str, tuple[Sequence[float], float, float]]


class RidgeConfig(Contract):
    kind: Literal["handcrafted-personal", "handcrafted-population", "embedding"]
    metric: Metric
    context_hours: Annotated[int, Field(gt=0)] = 48
    horizon: Annotated[int, Field(gt=0)] = 24
    stride_hours: Annotated[int, Field(gt=0)] = 6
    min_context_values: Annotated[int, Field(gt=0)] = 24
    holdout_hours: Annotated[int, Field(gt=0)] = 168
    alphas: Annotated[list[Annotated[float, Field(gt=0)]], Field(min_length=1)]

    @model_validator(mode="after")
    def _limits(self) -> Self:
        if self.min_context_values > self.context_hours:
            raise ValueError("minimum context must fit the context window")
        if self.holdout_hours % self.horizon:
            raise ValueError("holdout must be whole horizons")
        return self

    @property
    def model_id(self) -> str:
        return {
            "handcrafted-personal": "handcrafted-ridge-personal",
            "handcrafted-population": "handcrafted-ridge-population",
            "embedding": "chronos-2-embedding-ridge",
        }[self.kind]


def _calendar(cutoff: datetime) -> list[float]:
    angle = 2 * math.pi * cutoff.hour / 24
    return [math.sin(angle), math.cos(angle)]


def _handcrafted(context: Sequence[float | None]) -> list[float]:
    observed = [(i, v) for i, v in enumerate(context) if v is not None]
    values = [v for _, v in observed]

    def tail_mean(hours: int) -> float:
        recent = [v for i, v in observed if i >= len(context) - hours]
        return fmean(recent) if recent else fmean(values)

    return [
        values[-1],
        tail_mean(6),
        tail_mean(24),
        fmean(values),
        pstdev(values),
        len(values) / len(context),
        float(len(context) - observed[-1][0]),
    ]


def features(
    config: RidgeConfig,
    context: Sequence[float | None],
    cutoff: datetime,
    embeddings: Embeddings | None,
    population_mean: float | None,
) -> tuple[list[float], float] | None:
    """Feature row and target offset, or None when the context cannot be featurized."""
    if sum(v is not None for v in context) < config.min_context_values:
        return None
    calendar = _calendar(cutoff)
    match config.kind:
        case "handcrafted-personal":
            row = _handcrafted(context)
            return [*row, *calendar], row[3]
        case "handcrafted-population":
            if population_mean is None:
                return None
            return calendar, population_mean
        case "embedding":
            if embeddings is None:
                raise ValueError("embedding heads need the GX10 embeddings")
            found = embeddings.get(request_id(list(context), config.horizon))
            if found is None:
                raise ValueError("no GX10 embedding for this causal context; export again")
            vector, loc, scale = found
            return [*vector, loc, scale, *calendar], loc
    raise AssertionError("validated kind")


class LeadWeights(Contract):
    weights: list[float]
    intercept: float
    training_rows: Annotated[int, Field(ge=0)]


class RidgeArtifact(Contract):
    format_version: Literal["ridge-head-1"] = "ridge-head-1"
    config: RidgeConfig
    fit_as_of: UtcDatetime
    training_prefix_sha256: Sha256
    embeddings_sha256: Sha256 | None
    alpha: float
    holdout_mae: dict[str, float | None]
    population_mean: float | None
    feature_means: list[float]
    feature_scales: list[float]
    leads: list[LeadWeights]

    @property
    def model_id(self) -> str:
        return self.config.model_id

    def predict_with(
        self, request: ForecastInput, embeddings: Embeddings | None = None
    ) -> tuple[ForecastEstimate | None, ...]:
        if request.cutoff < self.fit_as_of:
            raise ValueError("prediction cutoff precedes the head's fit cutoff")
        rows = [r for r in request.history if isinstance(r, HourlyFeature)]
        if len(rows) != len(request.history) or any(r.metric != self.config.metric for r in rows):
            raise ValueError("ridge heads take the configured metric's derived hourly bins")
        context = hourly_grid(rows, request.cutoff, self.config.context_hours)
        made = features(self.config, context, request.cutoff, embeddings, self.population_mean)
        if made is None:
            return (None,) * len(request.targets)
        row, offset = made
        scaled = [
            (x - m) / s
            for x, m, s in zip(row, self.feature_means, self.feature_scales, strict=True)
        ]
        spec = METRICS[self.config.metric]
        output: list[ForecastEstimate | None] = []
        for window in request.targets:
            lead = int((window.start_utc - request.cutoff) / HOUR)
            if not 0 <= lead < len(self.leads) or self.leads[lead].training_rows == 0:
                output.append(None)
                continue
            head = self.leads[lead]
            value = (
                offset
                + head.intercept
                + sum(w * x for w, x in zip(head.weights, scaled, strict=True))
            )
            low = spec.minimum if spec.minimum is not None else -math.inf
            high = spec.maximum if spec.maximum is not None else math.inf
            output.append(ForecastEstimate(median=min(max(value, low), high)))
        return tuple(output)


def _solve(rows, targets, alpha: float):
    import numpy as np

    x = np.asarray(rows, dtype=float)
    y = np.asarray(targets, dtype=float)
    x_mean, y_mean = x.mean(axis=0), y.mean()
    xc = x - x_mean
    weights = np.linalg.solve(xc.T @ xc + alpha * np.eye(x.shape[1]), xc.T @ (y - y_mean))
    return weights, y_mean - float(x_mean @ weights)


def _fit(
    config: RidgeConfig,
    windows: Sequence[Window],
    embeddings: Embeddings | None,
    population_mean: float | None,
    alpha: float,
) -> tuple[list[float], list[float], list[LeadWeights]]:
    import numpy as np

    made = [
        (w, features(config, w.context, w.cutoff, embeddings, population_mean)) for w in windows
    ]
    usable = [(w, m) for w, m in made if m is not None]
    if not usable:
        raise ValueError("no featurizable training windows")
    matrix = np.asarray([m[0] for _, m in usable], dtype=float)
    means = matrix.mean(axis=0)
    scales = matrix.std(axis=0)
    scales[scales == 0] = 1.0
    scaled = (matrix - means) / scales
    leads: list[LeadWeights] = []
    for lead in range(config.horizon):
        index = [i for i, (w, _) in enumerate(usable) if w.targets[lead] is not None]
        if not index:
            leads.append(
                LeadWeights(weights=[0.0] * matrix.shape[1], intercept=0.0, training_rows=0)
            )
            continue
        y = [usable[i][0].targets[lead] - usable[i][1][1] for i in index]
        weights, intercept = _solve(scaled[index], y, alpha)
        leads.append(
            LeadWeights(
                weights=[float(v) for v in weights],
                intercept=float(intercept),
                training_rows=len(index),
            )
        )
    return [float(v) for v in means], [float(v) for v in scales], leads


def fit_ridge(
    training: TrainingPrefix,
    config: RidgeConfig,
    embeddings: Embeddings | None = None,
    embeddings_sha256: str | None = None,
) -> RidgeArtifact:
    """Choose the penalty on the last `holdout_hours` of training windows, then refit all."""
    windows = training_windows(
        training,
        config.metric,
        context_hours=config.context_hours,
        horizon=config.horizon,
        stride_hours=config.stride_hours,
        min_context_values=config.min_context_values,
    )
    split = training.fit_as_of - config.holdout_hours * HOUR
    early = [w for w in windows if w.cutoff + config.horizon * HOUR <= split]
    late = [w for w in windows if w.cutoff >= split]

    def population(rows: Sequence[Window]) -> float | None:
        # Equal participant weight, from each participant's training-window targets.
        by_subject: dict[str, list[float]] = {}
        for w in rows:
            by_subject.setdefault(w.subject_id, []).extend(v for v in w.targets if v is not None)
        means = [fmean(v) for v in by_subject.values() if v]
        return fmean(means) if means else None

    scores: dict[str, float | None] = {}
    for alpha in config.alphas:
        if not early or not late:
            scores[repr(alpha)] = None
            continue
        means, scales, leads = _fit(config, early, embeddings, population(early), alpha)
        probe = RidgeArtifact(
            config=config,
            fit_as_of=split,
            training_prefix_sha256="0" * 64,
            embeddings_sha256=embeddings_sha256,
            alpha=alpha,
            holdout_mae={},
            population_mean=population(early),
            feature_means=means,
            feature_scales=scales,
            leads=leads,
        )
        errors = []
        for w in late:
            made = features(config, w.context, w.cutoff, embeddings, probe.population_mean)
            if made is None:
                continue
            row, offset = made
            scaled = [(x - m) / s for x, m, s in zip(row, means, scales, strict=True)]
            for lead, truth in enumerate(w.targets):
                if truth is not None and leads[lead].training_rows:
                    head = leads[lead]
                    value = (
                        offset
                        + head.intercept
                        + sum(a * b for a, b in zip(head.weights, scaled, strict=True))
                    )
                    errors.append(abs(value - truth))
        scores[repr(alpha)] = fmean(errors) if errors else None
    ranked = [(s, a) for a, s in zip(config.alphas, scores.values(), strict=True) if s is not None]
    alpha = min(ranked)[1] if ranked else config.alphas[len(config.alphas) // 2]
    population_mean = population(windows)
    means, scales, leads = _fit(config, windows, embeddings, population_mean, alpha)
    return RidgeArtifact(
        config=config,
        fit_as_of=training.fit_as_of,
        training_prefix_sha256=document_sha256(training),
        embeddings_sha256=embeddings_sha256,
        alpha=alpha,
        holdout_mae=scores,
        population_mean=population_mean,
        feature_means=means,
        feature_scales=scales,
        leads=leads,
    )


def ridge_factory(
    config: RidgeConfig,
    embeddings: Embeddings | None = None,
    embeddings_sha256: str | None = None,
    fitted: list[RidgeArtifact] | None = None,
) -> PredictorFactory:
    def fit(training: TrainingPrefix) -> Predictor:
        artifact = fit_ridge(training, config, embeddings, embeddings_sha256)
        if fitted is not None:
            fitted.append(artifact)

        def predict(request: ForecastInput) -> tuple[ForecastEstimate | None, ...]:
            return artifact.predict_with(request, embeddings)

        return predict

    return fit
