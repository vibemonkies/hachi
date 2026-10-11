"""Ensembles and residual intervals from harness predictions, replayed through the harness.

Every member prediction comes from `evaluate_forecast`, so it was made causally. Meta
learners (stacking weights per decile, residual interval offsets) are fitted only on
meta-fold out-of-fold points; the resulting ensemble is replayed through the harness
by (subject, cutoff) so it is scored, paired and packeted like any other model.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import fmean

from hachi.contracts.metrics import METRICS, Metric
from hachi.contracts.tables import Aggregate
from hachi.evaluation import (
    EvaluationConfig,
    EvaluationResult,
    ForecastEstimate,
    ForecastInput,
    Predictor,
    PredictorFactory,
    TrainingPrefix,
)
from hachi.evaluation.forecast import target_quality_eligible

DECILES = tuple(round(0.1 * i, 1) for i in range(1, 10))

type PointKey = tuple[str, datetime, datetime]  # subject, cutoff, target start
type OriginKey = tuple[str, datetime]


@dataclass(frozen=True)
class Point:
    """One target's forecast: the median, an interval, and deciles when the model has them."""

    median: float
    lower: float | None
    upper: float | None
    deciles: tuple[float, ...] | None

    def at(self, level: float) -> float:
        if self.deciles is None:
            return self.median  # a point forecast is a degenerate distribution
        return self.deciles[DECILES.index(round(level, 1))]


type Table = dict[PointKey, Point | None]


def table(
    result: EvaluationResult,
    deciles: Mapping[OriginKey, Sequence[Sequence[float]]] | None = None,
) -> Table:
    """Flatten a harness result; abstentions stay None, unpredicted origins stay absent."""
    output: Table = {}
    for prediction in result.predictions:
        origin = (prediction.origin.subject_id, prediction.origin.cutoff)
        rows = None if deciles is None else deciles.get(origin)
        for index, (window, estimate) in enumerate(
            zip(prediction.origin.targets, prediction.estimates, strict=True)
        ):
            key = (origin[0], origin[1], window.start_utc)
            if estimate is None:
                output[key] = None
                continue
            output[key] = Point(
                estimate.median,
                estimate.lower,
                estimate.upper,
                None if rows is None else tuple(rows[index]),
            )
    return output


def labels(
    targets: Sequence[Aggregate], config: EvaluationConfig
) -> dict[tuple[str, datetime], float]:
    return {
        (t.subject_id, t.interval_start_utc): t.value
        for t in targets
        if t.metric == config.metric
        and t.resolution == "hour"
        and t.aggregation == config.aggregation
        and t.value is not None
        and target_quality_eligible(t, config)
    }


def _quantile(values: Sequence[float], level: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * level
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def residual_offsets(
    meta: Table, truth: Mapping[tuple[str, datetime], float], lower: float, upper: float
) -> tuple[float, float]:
    """Quantiles of truth minus median over meta out-of-fold points (never scored points)."""
    residuals = [
        truth[(k[0], k[2])] - p.median
        for k, p in meta.items()
        if p is not None and (k[0], k[2]) in truth
    ]
    if len(residuals) < 20:
        raise ValueError("too few meta out-of-fold residuals to set an interval")
    return min(_quantile(residuals, lower), 0.0), max(_quantile(residuals, upper), 0.0)


def _bounded(metric: Metric, value: float) -> float:
    spec = METRICS[metric]
    low = spec.minimum if spec.minimum is not None else -math.inf
    high = spec.maximum if spec.maximum is not None else math.inf
    return min(max(value, low), high)


def with_interval(point: Table, offsets: tuple[float, float], metric: Metric) -> Table:
    return {
        k: None
        if p is None
        else Point(
            p.median,
            _bounded(metric, p.median + offsets[0]),
            _bounded(metric, p.median + offsets[1]),
            p.deciles,
        )
        for k, p in point.items()
    }


@dataclass(frozen=True)
class StackWeights:
    members: tuple[str, ...]
    weights: dict[float, tuple[float, ...]]  # decile -> member weights (nonnegative, sum 1)
    fitted_points: int


def fit_stack(
    meta: Mapping[str, Table], truth: Mapping[tuple[str, datetime], float], members: Sequence[str]
) -> StackWeights:
    """Per decile, minimize pinball loss over complete meta points (linear programme)."""
    import numpy as np
    from scipy.optimize import linprog
    from scipy.sparse import csr_matrix, hstack, identity

    keys = sorted(
        k
        for k in meta[members[0]]
        if (k[0], k[2]) in truth and all(meta[m].get(k) is not None for m in members)
    )
    if len(keys) < 20:
        raise ValueError("too few complete meta out-of-fold points to fit stacking weights")
    y = np.asarray([truth[(k[0], k[2])] for k in keys])
    n, m = len(keys), len(members)
    weights: dict[float, tuple[float, ...]] = {}
    for level in DECILES:
        p = np.asarray([[meta[name][k].at(level) for name in members] for k in keys])
        # Variables [w (m), u (n), v (n)]: p w + u - v = y; sum w = 1; all >= 0.
        equality = hstack(
            [csr_matrix(p), identity(n, format="csr"), -identity(n, format="csr")], format="csr"
        )
        simplex = csr_matrix(np.concatenate([np.ones(m), np.zeros(2 * n)])[None, :])
        cost = np.concatenate([np.zeros(m), np.full(n, level), np.full(n, 1 - level)])
        solved = linprog(
            cost,
            A_eq=hstack([equality.T, simplex.T]).T,
            b_eq=np.concatenate([y, [1.0]]),
            bounds=(0, None),
            method="highs",
        )
        if not solved.success:
            raise RuntimeError(f"stacking LP failed at level {level}: {solved.message}")
        w = np.clip(solved.x[:m], 0, None)
        weights[level] = tuple(float(v) for v in w / w.sum())
    return StackWeights(tuple(members), weights, n)


def combine(
    members: Mapping[str, Table],
    keys: Sequence[PointKey],
    weights: StackWeights | None,
    metric: Metric,
) -> Table:
    """Stacked (weights) or equal-weight (None) deciles; renormalized over present members."""
    names = tuple(members) if weights is None else weights.members
    output: Table = {}
    for key in keys:
        present = [(i, members[n][key]) for i, n in enumerate(names) if members[n].get(key)]
        if not present:
            output[key] = None
            continue
        deciles = []
        for level in DECILES:
            if weights is None:
                share = [1.0] * len(present)
            else:
                share = [weights.weights[level][i] for i, _ in present]
            total = sum(share)
            if total <= 0:
                share, total = [1.0] * len(present), float(len(present))
            deciles.append(
                _bounded(
                    metric,
                    sum(s * p.at(level) for s, (_, p) in zip(share, present, strict=True)) / total,
                )
            )
        deciles.sort()  # rearrangement never increases quantile loss
        output[key] = Point(deciles[4], deciles[0], deciles[8], tuple(deciles))
    return output


def replay_factory(points: Table, name: str) -> PredictorFactory:
    """Replay a fixed table through the harness by (subject, cutoff, target)."""

    def fit(_: TrainingPrefix) -> Predictor:
        def predict(request: ForecastInput) -> tuple[ForecastEstimate | None, ...]:
            output: list[ForecastEstimate | None] = []
            for window in request.targets:
                key = (request.subject_id, request.cutoff, window.start_utc)
                if key not in points:
                    raise ValueError(f"{name} has no prediction for this origin and target")
                point = points[key]
                output.append(
                    None
                    if point is None
                    else ForecastEstimate(median=point.median, lower=point.lower, upper=point.upper)
                )
            return tuple(output)

        return predict

    return fit


def keys_of(result: EvaluationResult) -> list[PointKey]:
    return [
        (p.origin.subject_id, p.origin.cutoff, w.start_utc)
        for p in result.predictions
        for w in p.origin.targets
    ]


def mean_pinball(point: Point, truth: float) -> float:
    def loss(level: float) -> float:
        error = truth - point.at(level)
        return max(level * error, (level - 1) * error)

    return fmean(loss(q) for q in DECILES)


__all__ = [
    "DECILES",
    "Point",
    "StackWeights",
    "combine",
    "fit_stack",
    "keys_of",
    "labels",
    "mean_pinball",
    "replay_factory",
    "residual_offsets",
    "table",
    "with_interval",
]
