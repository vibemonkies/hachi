"""Forecast errors with equal participant weighting and participant bootstrap intervals."""

import math
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

from hachi.contracts.metrics import Metric, Unit


@dataclass(frozen=True)
class ScoredPoint:
    subject_id: str
    truth: float
    median: float
    lower: float | None
    upper: float | None


@dataclass(frozen=True)
class SubjectMetrics:
    subject_id: str
    scored_points: int
    mae: float
    rmse: float
    median_pinball_loss: float
    interval_points: int
    interval_coverage: float | None
    mean_interval_width: float | None


@dataclass(frozen=True)
class Estimate:
    value: float
    participants: int
    confidence_interval: tuple[float, float] | None


@dataclass(frozen=True)
class MetricReport:
    metric: Metric
    unit: Unit
    weighting: str
    confidence: float
    bootstrap_samples: int
    subjects: tuple[SubjectMetrics, ...]
    mae: Estimate | None
    rmse: Estimate | None
    median_pinball_loss: Estimate | None
    interval_coverage: Estimate | None
    mean_interval_width: Estimate | None


def _percentile(values: Sequence[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    low = math.floor(position)
    high = math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def bootstrap_participant_mean(
    values: Sequence[float], *, samples: int, confidence: float, seed: int
) -> Estimate | None:
    if not values:
        return None
    if len(values) == 1:
        # A singleton resample cannot quantify between-participant uncertainty.
        return Estimate(values[0], 1, None)
    rng = random.Random(seed)
    draws = sorted(fmean(rng.choices(values, k=len(values))) for _ in range(samples))
    tail = (1 - confidence) / 2
    return Estimate(
        fmean(values), len(values), (_percentile(draws, tail), _percentile(draws, 1 - tail))
    )


def forecast_metrics(
    points: Sequence[ScoredPoint],
    *,
    metric: Metric,
    unit: Unit,
    bootstrap_samples: int,
    confidence: float,
    seed: int,
) -> MetricReport:
    if bootstrap_samples < 2 or not 0 < confidence < 1:
        raise ValueError("bootstrap_samples must be >=2 and confidence must be between 0 and 1")
    by_subject: dict[str, list[ScoredPoint]] = defaultdict(list)
    for point in points:
        by_subject[point.subject_id].append(point)
    subjects: list[SubjectMetrics] = []
    for subject, rows in sorted(by_subject.items()):
        errors = [r.median - r.truth for r in rows]
        intervals = [r for r in rows if r.lower is not None and r.upper is not None]
        coverage: list[float] = []
        widths: list[float] = []
        for r in intervals:
            if r.lower is not None and r.upper is not None:
                coverage.append(float(r.lower <= r.truth <= r.upper))
                widths.append(r.upper - r.lower)
        mae = fmean(abs(e) for e in errors)
        subjects.append(
            SubjectMetrics(
                subject,
                len(rows),
                mae,
                math.sqrt(fmean(e * e for e in errors)),
                mae / 2,
                len(intervals),
                fmean(coverage) if coverage else None,
                fmean(widths) if widths else None,
            )
        )

    return _metric_report(
        subjects,
        metric=metric,
        unit=unit,
        bootstrap_samples=bootstrap_samples,
        confidence=confidence,
        seed=seed,
    )


def _metric_report(
    subjects: Sequence[SubjectMetrics],
    *,
    metric: Metric,
    unit: Unit,
    bootstrap_samples: int,
    confidence: float,
    seed: int,
) -> MetricReport:
    def aggregate(values: Sequence[float]) -> Estimate | None:
        return bootstrap_participant_mean(
            values, samples=bootstrap_samples, confidence=confidence, seed=seed
        )

    return MetricReport(
        metric,
        unit,
        "equal participant; mean of participant metrics",
        confidence,
        bootstrap_samples,
        tuple(subjects),
        aggregate([s.mae for s in subjects]),
        aggregate([s.rmse for s in subjects]),
        aggregate([s.median_pinball_loss for s in subjects]),
        aggregate([s.interval_coverage for s in subjects if s.interval_coverage is not None]),
        aggregate([s.mean_interval_width for s in subjects if s.mean_interval_width is not None]),
    )


def combine_metric_reports(reports: Sequence[MetricReport], *, seed: int) -> MetricReport:
    """Pool disjoint validation participants, retaining equal-person weighting.

    Do not pool nested folds in which a participant is evaluated more than once.
    Choose one outer fold's disjoint inner validation cohorts, or disjoint outer
    test reports after per-outer selection. Model selection remains caller-owned.
    """
    if not reports:
        raise ValueError("at least one metric report is required")
    first = reports[0]
    if any(
        (r.metric, r.unit, r.weighting, r.bootstrap_samples, r.confidence)
        != (first.metric, first.unit, first.weighting, first.bootstrap_samples, first.confidence)
        for r in reports
    ):
        raise ValueError("combined reports must share metric, units and bootstrap protocol")
    subjects = sorted((s for r in reports for s in r.subjects), key=lambda s: s.subject_id)
    if len({s.subject_id for s in subjects}) != len(subjects):
        raise ValueError("combined reports must have disjoint participants")
    return _metric_report(
        subjects,
        metric=first.metric,
        unit=first.unit,
        bootstrap_samples=first.bootstrap_samples,
        confidence=first.confidence,
        seed=seed,
    )
