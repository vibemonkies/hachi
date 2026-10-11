"""Bounded causal context for model variants that need more than the harness lookback.

`evaluate_forecast` hands a predictor only the configured metric within the protocol
lookback. A variant that needs a longer window or another channel (a past-only
covariate) reads it here instead, keyed by the request's own subject and cutoff: the
subject's completed hourly bins in [cutoff - hours, cutoff) that are available by the
cutoff, per channel. A later or late-available bin is never returned, and a channel
without bins stays empty (missing), never zero.

This changes neither `EvaluationConfig`, origin inclusion nor the 48 h fit inputs.
Callers record the policy hash per variant as an explicit ablation.
"""

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract
from hachi.contracts.causality import available_by
from hachi.contracts.metrics import Metric

from .features import FeatureBin, HourlyFeature, HourlyFeaturePolicy, hourly_features

HOUR = timedelta(hours=1)


class ContextPolicy(Contract):
    """Window length plus one inclusion/readiness policy per channel."""

    hours: Annotated[int, Field(gt=0, le=8760)]
    channels: Annotated[list[HourlyFeaturePolicy], Field(min_length=1)]

    @model_validator(mode="after")
    def _channels(self) -> Self:
        metrics = [c.metric for c in self.channels]
        if len(set(metrics)) != len(metrics):
            raise ValueError("a context policy holds one channel per metric")
        return self


@dataclass(frozen=True)
class ContextIndex:
    policy: ContextPolicy
    counts: dict[Metric, dict[str, int]]
    _rows: dict[tuple[str, Metric], tuple[HourlyFeature, ...]]
    _starts: dict[tuple[str, Metric], tuple[datetime, ...]]

    def window(self, subject_id: str, cutoff: datetime) -> dict[Metric, tuple[HourlyFeature, ...]]:
        """Every channel's completed bins in [cutoff - hours, cutoff), available by cutoff."""
        if (
            cutoff.utcoffset() != timedelta(0)
            or cutoff.minute
            or cutoff.second
            or (cutoff.microsecond)
        ):
            raise ValueError("context cutoffs must be hour-aligned UTC instants")
        start = cutoff - self.policy.hours * HOUR
        output: dict[Metric, tuple[HourlyFeature, ...]] = {}
        for channel in self.policy.channels:
            key = (subject_id, channel.metric)
            rows = self._rows.get(key, ())
            starts = self._starts.get(key, ())
            first, last = bisect_left(starts, start), bisect_left(starts, cutoff)
            output[channel.metric] = tuple(r for r in rows[first:last] if available_by(r, cutoff))
        return output


def context_index(bins: Iterable[FeatureBin], policy: ContextPolicy) -> ContextIndex:
    """Select each channel with its own policy, exactly as `hourly_features` does."""
    materialized = tuple(bins)
    rows: dict[tuple[str, Metric], list[HourlyFeature]] = defaultdict(list)
    counts: dict[Metric, dict[str, int]] = {}
    for channel in policy.channels:
        view = hourly_features(materialized, channel)
        counts[channel.metric] = view.counts
        for feature in view.features:
            rows[(feature.subject_id, channel.metric)].append(feature)
    ordered = {key: tuple(sorted(value, key=lambda r: r.start_utc)) for key, value in rows.items()}
    return ContextIndex(
        policy,
        counts,
        ordered,
        {key: tuple(r.start_utc for r in value) for key, value in ordered.items()},
    )


def hourly_grid(
    rows: Sequence[HourlyFeature], cutoff: datetime, hours: int
) -> tuple[float | None, ...]:
    """Values on the regular hourly grid ending at the cutoff; absent hours are None."""
    start = cutoff - hours * HOUR
    values = {row.start_utc: row.value for row in rows if start <= row.start_utc < cutoff}
    if len(values) != sum(start <= row.start_utc < cutoff for row in rows):
        raise ValueError("duplicate hourly bins in one channel")
    return tuple(values.get(start + i * HOUR) for i in range(hours))
