"""Hour-end sealed native Apple inputs; source transfer needs separate validation."""

import sqlite3
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import fmean, median
from typing import Literal

from hachi.contracts.metrics import METRICS, Aggregation
from hachi.contracts.tables import Aggregate, Observation
from hachi.evaluation.features import HourlyFeaturePolicy, HourlyFeatureView, hourly_features

from .importer import ImportConfig
from .store import EPOCH, select_candidates, timestamp_us

AVAILABILITY_RULE = "apple-hour-end-sealed-native-v1"
PIPELINE_VERSION = "apple-hourly-1"
HOUR = timedelta(hours=1)
type NativeMetric = Literal["heart_rate", "steps"]


@dataclass(frozen=True)
class HourAudit:
    """Counts after importer selection; density is not continuous observation."""

    included_records: int
    excluded_cross_hour: int
    sample_minutes: int
    interval_seconds: float
    source_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class AppleFeatureBin:
    aggregate: Aggregate
    available_at_utc: datetime
    audit: HourAudit


def _interval_seconds(rows: Iterable[Observation]) -> float:
    spans = sorted((r.start_utc, r.end_utc) for r in rows)
    seconds = 0.0
    covered_until: datetime | None = None
    for start, end in spans:
        begin = start if covered_until is None else max(start, covered_until)
        seconds += max(0.0, (end - begin).total_seconds())
        covered_until = end if covered_until is None else max(covered_until, end)
    return seconds


def _aggregate_hour(
    rows: Iterable[Observation],
    config: ImportConfig,
    metric: NativeMetric,
    aggregation: Aggregation,
    start: datetime,
) -> AppleFeatureBin:
    """Pure transform of selected rows already eligible at this hour's end."""
    end = start + HOUR
    included: list[Observation] = []
    crossing = 0
    for row in rows:
        if row.metric != metric or row.start_utc >= end or row.end_utc < start:
            continue
        if row.start_utc < start or row.end_utc > end:
            if row.end_utc > start:
                crossing += 1
            continue
        included.append(row)
    included.sort(key=lambda r: (r.start_utc, r.record_id))
    minutes = len({r.start_utc.minute for r in included}) if metric == "heart_rate" else 0
    seconds = _interval_seconds(included) if metric == "steps" else 0.0
    coverage = minutes / 60 if metric == "heart_rate" else seconds / 3600
    values = [r.value for r in included]
    value: float | None = None
    if values:
        match aggregation:
            case "mean":
                value = fmean(values)
            case "median":
                value = median(values)
            case "min":
                value = min(values)
            case "max":
                value = max(values)
            case "sum":
                value = sum(values)
            case _:
                raise AssertionError("validated native aggregation")
    return AppleFeatureBin(
        Aggregate(
            dataset_id=config.dataset_id,
            subject_id=config.subject_id,
            metric=metric,
            unit=METRICS[metric].unit,
            resolution="hour",
            interval_start_utc=start,
            interval_end_utc=end,
            local_date=None,
            tz_name=None,
            aggregation=aggregation,
            value=value,
            null_reason="no_observations" if not values else None,
            observed_count=len(included),
            coverage=coverage,
            source_ids=sorted({r.source_id for r in included}),
            pipeline_version=PIPELINE_VERSION,
        ),
        end,
        HourAudit(
            len(included),
            crossing,
            minutes,
            seconds,
            tuple(sorted(Counter(r.source_id for r in included).items())),
        ),
    )


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} requires an aware instant")
    return value.astimezone(UTC)


def iter_hourly_bins(
    path: Path,
    *,
    metric: NativeMetric,
    aggregation: Aggregation,
    as_of: datetime,
    start: datetime | None = None,
) -> Iterator[AppleFeatureBin]:
    """Replay native precedence at every completed hour end, never at a later cutoff.

    Late creations and intervals ending after that hour are permanently excluded
    from its model input. They remain available through the native observation API.
    This makes value, coverage, source lineage and readiness stable after sealing.
    """
    if metric not in ("heart_rate", "steps"):
        raise ValueError("Apple hourly inputs support only native heart_rate and steps")
    if aggregation not in METRICS[metric].aggregations:
        raise ValueError("aggregation must match the native metric")
    cutoff = _utc(as_of, "as_of").replace(minute=0, second=0, microsecond=0)
    lower = _utc(start, "start") if start is not None else None
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA cache_size=-4096")
        connection.execute("PRAGMA temp_store=FILE")
        if connection.execute("SELECT value FROM metadata WHERE key='completed'").fetchone() != (
            "true",
        ):
            raise ValueError("import has not completed")
        (payload,) = connection.execute("SELECT value FROM metadata WHERE key='config'").fetchone()
        config = ImportConfig.model_validate_json(payload)
        # Select the grid from native candidates, not full-import winners: a late
        # winning watch record must not erase a previously eligible phone hour.
        (first,) = connection.execute(
            "SELECT min(start_us) FROM candidates WHERE family=? AND end_us<=? AND available_us<=?",
            (metric, timestamp_us(cutoff), timestamp_us(cutoff)),
        ).fetchone()
        if first is None:
            return
        hour = (EPOCH + timedelta(microseconds=first)).replace(minute=0, second=0, microsecond=0)
        if lower is not None and lower > hour:
            hour = lower.replace(minute=0, second=0, microsecond=0)
            if hour < lower:
                hour += HOUR
        while hour < cutoff:
            selected = (row for _, row in select_candidates(connection, hour + HOUR))
            yield _aggregate_hour(selected, config, metric, aggregation, hour)
            hour += HOUR


def apple_hourly_features(
    path: Path,
    policy: HourlyFeaturePolicy,
    as_of: datetime,
    start: datetime | None = None,
) -> HourlyFeatureView:
    """Apply the existing model gates with an explicitly Apple-specific policy.

    Never silently rewrite a frozen PMData policy or claim its availability rule.
    Source compatibility must be declared by the serving/model owner separately.
    """
    if policy.availability_rule != AVAILABILITY_RULE:
        raise ValueError("Apple hourly inputs require their source-specific availability rule")
    if policy.metric not in ("heart_rate", "steps"):
        raise ValueError("Apple hourly inputs support only native heart_rate and steps")
    return hourly_features(
        iter_hourly_bins(
            path,
            metric=policy.metric,
            aggregation=policy.aggregation,
            as_of=as_of,
            start=start,
        ),
        policy,
    )
