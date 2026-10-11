"""Causal training examples built only from what a factory receives: one TrainingPrefix.

Each window's context holds only bins available by that window's own cutoff, and its
targets end by the prefix's fit cutoff, so a model trained on these windows has seen
nothing a predictor at the fit cutoff could not have seen.
"""

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from hachi.contracts.causality import available_by
from hachi.evaluation import HourlyFeature, TrainingPrefix
from hachi.evaluation.context import hourly_grid

from ..chronos.inference import canonical_bytes

HOUR = timedelta(hours=1)
SERIES_FORMAT = "chronos-training-series-1"


def _features(prefix: TrainingPrefix, metric: str) -> dict[str, list[HourlyFeature]]:
    rows: dict[str, list[HourlyFeature]] = defaultdict(list)
    for row in prefix.observations:
        if not isinstance(row, HourlyFeature):
            raise ValueError("training windows need derived hourly features")
        if row.metric == metric:
            if not available_by(row, prefix.fit_as_of):
                raise ValueError("training prefix holds a row unavailable at its fit cutoff")
            rows[row.subject_id].append(row)
    return {k: sorted(v, key=lambda r: r.start_utc) for k, v in rows.items()}


@dataclass(frozen=True)
class Window:
    subject_id: str
    cutoff: datetime
    context: tuple[float | None, ...]
    targets: tuple[float | None, ...]


def training_windows(
    prefix: TrainingPrefix,
    metric: str,
    *,
    context_hours: int,
    horizon: int,
    stride_hours: int,
    min_context_values: int,
) -> list[Window]:
    """Windows on a UTC-midnight-anchored grid whose targets end by the fit cutoff."""
    windows: list[Window] = []
    for subject, rows in sorted(_features(prefix, metric).items()):
        first = rows[0].start_utc + context_hours * HOUR
        cutoff = first.replace(hour=0) + (-(-first.hour // stride_hours) * stride_hours) * HOUR
        while cutoff + horizon * HOUR <= prefix.fit_as_of:
            # Context: only what was available by this window's own cutoff.
            context = hourly_grid(
                [r for r in rows if available_by(r, cutoff)], cutoff, context_hours
            )
            targets = tuple(
                hourly_grid(rows, cutoff + horizon * HOUR, horizon)
            )  # bins in [cutoff, cutoff + horizon)
            if sum(v is not None for v in context) >= min_context_values and any(
                v is not None for v in targets
            ):
                windows.append(Window(subject, cutoff, context, targets))
            cutoff += stride_hours * HOUR
    return windows


def _series_row(target: Sequence[float | None]) -> dict[str, Any]:
    values = list(target)
    digest = hashlib.sha256(canonical_bytes({"target": values})).hexdigest()
    return {"format": SERIES_FORMAT, "series_id": digest, "target": values}


def finetune_series(
    prefix: TrainingPrefix,
    metric: str,
    *,
    holdout_hours: int,
    horizon: int,
    min_target_values: int,
    min_past_values: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Training series end before the temporal holdout; holdout series end inside it.

    A holdout series' final `horizon` hours lie in [fit - holdout, fit); it exists only
    for best-checkpoint selection. Series ids are content hashes, never subject ids.
    """
    holdout_start = prefix.fit_as_of - holdout_hours * HOUR
    train: list[dict[str, Any]] = []
    holdout: list[dict[str, Any]] = []
    for rows in _features(prefix, metric).values():
        start = rows[0].start_utc
        span = int((holdout_start - start) / HOUR)
        if span > 0:
            values = hourly_grid(rows, holdout_start, span)
            if sum(v is not None for v in values) >= min_past_values + min_target_values:
                train.append(_series_row(values))
        for day in range(holdout_hours // horizon):
            end = holdout_start + (day + 1) * horizon * HOUR
            length = int((end - start) / HOUR)
            if length <= horizon:
                continue
            values = hourly_grid(rows, end, length)
            past, future = values[:-horizon], values[-horizon:]
            if (
                sum(v is not None for v in future) >= min_target_values
                and sum(v is not None for v in past) >= min_past_values
            ):
                holdout.append(_series_row(values))
    return train, holdout
