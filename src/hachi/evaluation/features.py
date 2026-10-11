"""Availability-preserving hourly inputs, distinct from recorded source measurements."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Protocol, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, Identifier, UtcDatetime
from hachi.contracts.metrics import METRICS, Aggregation, Metric, Unit
from hachi.contracts.tables import Aggregate, Observation

from .serialization import document_sha256


class FeatureBin(Protocol):
    """Structural interface implemented by the PMData loader's named tuple."""

    @property
    def aggregate(self) -> Aggregate: ...

    @property
    def available_at_utc(self) -> datetime: ...


class HourlyFeature(Contract):
    """A complete derived bin with its source lineage and causal readiness.

    The producer guarantees the stored value is unchanged by recomputation at any
    cutoff at or after readiness, including availability of coverage contributions.
    This consumer cannot establish that guarantee from an Aggregate alone.
    """

    aggregate: Aggregate
    available_at_utc: UtcDatetime
    availability_rule: Identifier

    @model_validator(mode="after")
    def _hour(self) -> Self:
        row = self.aggregate
        if row.resolution != "hour" or row.interval_start_utc.minute:
            raise ValueError("hourly features require complete UTC hour-aligned bins")
        if row.value is None:
            raise ValueError("hourly features require an observed value")
        if self.available_at_utc < row.interval_end_utc:
            raise ValueError("a complete hourly feature cannot be available before its bin ends")
        return self

    @property
    def dataset_id(self) -> str:
        return self.aggregate.dataset_id

    @property
    def subject_id(self) -> str:
        return self.aggregate.subject_id

    @property
    def record_id(self) -> str:
        # Do not bind the whole snapshot here: adding withheld future rows must
        # not change an earlier bin's identity or a training-prefix checksum.
        return "hour-" + document_sha256(self)

    @property
    def metric(self) -> Metric:
        return self.aggregate.metric

    @property
    def unit(self) -> Unit:
        return self.aggregate.unit

    @property
    def value(self) -> float:
        value = self.aggregate.value
        assert value is not None  # construction rejects missing bins
        return value

    @property
    def start_utc(self) -> datetime:
        return self.aggregate.interval_start_utc

    @property
    def end_utc(self) -> datetime:
        return self.aggregate.interval_end_utc


type ForecastObservation = Observation | HourlyFeature


class HourlyFeaturePolicy(Contract):
    metric: Metric
    aggregation: Aggregation
    min_coverage: Annotated[float, Field(ge=0, le=1)]
    min_observed_count: Annotated[int, Field(gt=0)]
    availability_rule: Identifier

    @model_validator(mode="after")
    def _metric(self) -> Self:
        spec = METRICS[self.metric]
        if self.aggregation not in spec.aggregations:
            raise ValueError("hourly feature policy requires the registered metric aggregation")
        return self


@dataclass(frozen=True)
class HourlyFeatureView:
    policy: HourlyFeaturePolicy
    features: tuple[HourlyFeature, ...]
    counts: dict[str, int]


def hourly_features(bins: Iterable[FeatureBin], policy: HourlyFeaturePolicy) -> HourlyFeatureView:
    """Select one hourly series without imputing missingness or guessing readiness.

    Counts are exclusive and sum to input_bins. Persist the policy and counts next
    to the private evaluation packet; inclusion choices are experiment parameters.
    Snapshot admission, upstream exclusions and hashes remain the caller's duty.
    """
    counts: Counter[str] = Counter(
        dict.fromkeys(
            (
                "input_bins",
                "included",
                "other_metric",
                "other_aggregation",
                "missing",
                "low_coverage",
                "low_count",
            ),
            0,
        )
    )
    features: list[HourlyFeature] = []
    keys: set[tuple[str, datetime]] = set()
    for item in bins:
        row = item.aggregate
        counts["input_bins"] += 1
        if row.metric != policy.metric:
            counts["other_metric"] += 1
            continue
        if row.aggregation != policy.aggregation:
            counts["other_aggregation"] += 1
            continue
        if row.resolution != "hour" or row.interval_start_utc.minute:
            raise ValueError("feature input must use complete UTC hour-aligned bins")
        key = row.subject_id, row.interval_start_utc
        if key in keys:
            raise ValueError("duplicate hourly feature bins; resolve source precedence upstream")
        keys.add(key)
        if row.value is None:
            counts["missing"] += 1
        elif row.coverage < policy.min_coverage:
            counts["low_coverage"] += 1
        elif row.observed_count < policy.min_observed_count:
            counts["low_count"] += 1
        else:
            features.append(
                HourlyFeature(
                    aggregate=row,
                    available_at_utc=item.available_at_utc,
                    availability_rule=policy.availability_rule,
                )
            )
            counts["included"] += 1
    return HourlyFeatureView(policy, tuple(features), dict(sorted(counts.items())))


def require_input_series(
    observations: Iterable[ForecastObservation], metric: Metric, aggregation: Aggregation
) -> None:
    """Refuse double counting raw rows with derived bins for the selected metric."""
    selected = [row for row in observations if row.metric == metric]
    derived = [row for row in selected if isinstance(row, HourlyFeature)]
    if derived and len(derived) != len(selected):
        raise ValueError("do not mix raw observations and derived hourly features for one metric")
    if any(row.aggregate.aggregation != aggregation for row in derived):
        raise ValueError("hourly feature aggregation must match the evaluation/model configuration")
