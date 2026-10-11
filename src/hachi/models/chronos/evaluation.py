"""Export causal contexts, load verified GX10 forecasts, and score quantiles after pairing."""

import json
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from hachi.contracts.manifests import SplitManifest
from hachi.contracts.tables import Aggregate
from hachi.evaluation import (
    ComparisonResult,
    EvaluationConfig,
    EvaluationResult,
    ForecastObservation,
    evaluate_forecast,
)
from hachi.evaluation.forecast import target_quality_eligible
from hachi.evaluation.metrics import Estimate, bootstrap_participant_mean
from hachi.evaluation.splits import Partition

from .adapter import AdapterLog, ChronosConfig, ContextRequest, recording_factory
from .inference import PREDICTION_FORMAT, REQUEST_FORMAT, canonical_bytes, file_sha256

DECILES = tuple(round(0.1 * i, 1) for i in range(1, 10))
# Central intervals reported for calibration, as (lower, upper) quantile levels.
CALIBRATION_INTERVALS = ((0.25, 0.75), (0.1, 0.9), (0.05, 0.95), (0.01, 0.99))


def export_requests(
    manifest: SplitManifest,
    observations: Sequence[ForecastObservation],
    chronos: ChronosConfig,
    config: EvaluationConfig,
    *,
    partition: Partition = "validation",
) -> tuple[dict[str, ContextRequest], AdapterLog, EvaluationResult]:
    """Run the harness with no labels at all; the recorder sees only what a model would."""
    sink: dict[str, ContextRequest] = {}
    log = AdapterLog()
    result = evaluate_forecast(
        manifest,
        observations,
        (),
        recording_factory(chronos, sink, log),
        config,
        partition=partition,
    )
    return sink, log, result


def write_requests(path: Path, requests: Mapping[str, ContextRequest]) -> str:
    """Write each distinct context once, in id order, to a new private file."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        for key in sorted(requests):
            stream.write(canonical_bytes(requests[key].row()))
    return file_sha256(path)


@dataclass(frozen=True)
class Forecasts:
    levels: tuple[float, ...]
    quantiles: dict[str, list[list[float]]]
    evidence: dict[str, Any]


def load_forecasts(requests_path: Path, run_dir: Path) -> Forecasts:
    """Accept a GX10 run only if it answered exactly these requests, byte-verified."""
    evidence = json.loads((run_dir / "inference.json").read_text())
    if evidence.get("format") != PREDICTION_FORMAT or evidence.get("request_format") != (
        REQUEST_FORMAT
    ):
        raise ValueError("unrecognized Chronos inference format")
    if evidence["requests_sha256"] != file_sha256(requests_path):
        raise ValueError("GX10 run answered a different request file")
    if evidence["predictions_sha256"] != file_sha256(run_dir / "predictions.jsonl"):
        raise ValueError("predictions file does not match its recorded checksum")
    with requests_path.open() as stream:
        wanted = {json.loads(line)["request_id"] for line in stream}
    quantiles: dict[str, list[list[float]]] = {}
    with (run_dir / "predictions.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            if row["request_id"] in quantiles:
                raise ValueError("duplicate forecast for one request")
            quantiles[row["request_id"]] = row["quantiles"]
    if quantiles.keys() != wanted:
        raise ValueError("forecasts do not cover exactly the exported requests")
    return Forecasts(tuple(evidence["quantile_levels"]), quantiles, evidence)


def pinball(truth: float, forecast: float, level: float) -> float:
    error = truth - forecast
    return max(level * error, (level - 1) * error)


def _quantile_at(levels: Sequence[float], values: Sequence[float], level: float) -> float:
    for known, value in zip(levels, values, strict=True):
        if abs(known - level) < 1e-9:
            return value
    raise ValueError(f"quantile level {level} is not among the model's levels")


@dataclass(frozen=True)
class SubjectQuantiles:
    """One participant's paired decile losses and Chronos interval hits (private)."""

    subject_id: str
    paired_points: int
    baseline_loss: float | None
    candidate_loss: float | None
    calibration_points: int
    calibration: dict[str, float]


@dataclass(frozen=True)
class QuantileReport:
    definition: str
    subjects: tuple[SubjectQuantiles, ...]
    paired_points: int
    participants: int
    baseline: Estimate | None
    candidate: Estimate | None
    difference: Estimate | None
    calibration: dict[str, Estimate | None]


QUANTILE_DEFINITION = (
    "mean pinball loss over deciles 0.1..0.9 on paired targets; point forecasts as "
    "degenerate distributions; equal participant weighting; candidate minus baseline. "
    "Calibration: share of Chronos-scored targets inside each central interval."
)


def summarize_quantiles(
    subjects: Sequence[SubjectQuantiles], config: EvaluationConfig, seed: int
) -> QuantileReport:
    """Bootstrap per-participant values; pooling folds requires disjoint participants."""
    ids = [s.subject_id for s in subjects]
    if len(set(ids)) != len(ids):
        raise ValueError("quantile summaries need disjoint participants")
    ordered = sorted(subjects, key=lambda s: s.subject_id)

    def boot(values: Sequence[float]) -> Estimate | None:
        return bootstrap_participant_mean(
            values, samples=config.bootstrap_samples, confidence=config.confidence, seed=seed
        )

    paired = [s for s in ordered if s.baseline_loss is not None and s.candidate_loss is not None]
    nominal = sorted({name for s in ordered for name in s.calibration})
    return QuantileReport(
        QUANTILE_DEFINITION,
        tuple(ordered),
        sum(s.paired_points for s in paired),
        len(paired),
        boot([s.baseline_loss for s in paired if s.baseline_loss is not None]),
        boot([s.candidate_loss for s in paired if s.candidate_loss is not None]),
        boot(
            [
                s.candidate_loss - s.baseline_loss
                for s in paired
                if s.candidate_loss is not None and s.baseline_loss is not None
            ]
        ),
        {
            name: boot([s.calibration[name] for s in ordered if name in s.calibration])
            for name in nominal
        },
    )


def paired_quantile_report(
    result: ComparisonResult,
    targets: Sequence[Aggregate],
    log: AdapterLog,
    levels: Sequence[float],
    config: EvaluationConfig,
    seed: int,
) -> QuantileReport:
    """Mean decile pinball loss on the comparison's paired targets, scored after prediction.

    The baseline's point forecast is a degenerate distribution, so its mean decile loss
    equals half its absolute error. Calibration uses every Chronos-scored target.
    """
    labels = {
        (t.subject_id, t.interval_start_utc): t.value
        for t in targets
        if t.metric == config.metric
        and t.resolution == "hour"
        and t.aggregation == config.aggregation
        and t.value is not None
        and target_quality_eligible(t, config)
    }
    baseline = {(p.origin.subject_id, p.origin.cutoff): p for p in result.baseline.predictions}
    losses: dict[str, list[tuple[float, float]]] = defaultdict(list)
    hits: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for prediction in result.candidate.predictions:
        key: tuple[str, datetime] = (prediction.origin.subject_id, prediction.origin.cutoff)
        rows = log.quantiles.get(key)
        if rows is None:
            continue  # the adapter abstained for this whole origin
        other = baseline[key]
        for window, estimate, b_est, values in zip(
            prediction.origin.targets, prediction.estimates, other.estimates, rows, strict=True
        ):
            truth = labels.get((key[0], window.start_utc))
            if truth is None or estimate is None:
                continue
            for lower, upper in CALIBRATION_INTERVALS:
                inside = (
                    _quantile_at(levels, values, lower)
                    <= truth
                    <= _quantile_at(levels, values, upper)
                )
                hits[key[0]][f"{upper - lower:.2f}"].append(float(inside))
            if b_est is None:
                continue
            candidate_loss = fmean(
                pinball(truth, _quantile_at(levels, values, q), q) for q in DECILES
            )
            baseline_loss = fmean(pinball(truth, b_est.median, q) for q in DECILES)
            losses[key[0]].append((baseline_loss, candidate_loss))
    subjects = [
        SubjectQuantiles(
            subject,
            len(losses[subject]),
            fmean(b for b, _ in losses[subject]) if losses[subject] else None,
            fmean(c for _, c in losses[subject]) if losses[subject] else None,
            len(next(iter(hits[subject].values()), [])),
            {name: fmean(values) for name, values in sorted(hits[subject].items())},
        )
        for subject in sorted(set(losses) | set(hits))
    ]
    return summarize_quantiles(subjects, config, seed)
