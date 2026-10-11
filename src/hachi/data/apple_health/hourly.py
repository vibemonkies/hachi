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
from hachi.evaluation.features import HourlyFeature, HourlyFeaturePolicy
from hachi.evaluation.features import hourly_features as _select_features

from .importer import ImportConfig
from .store import EPOCH, select_candidates, timestamp_us

AVAILABILITY_RULE = "apple-hour-end-sealed-native-v1"
PIPELINE_VERSION = "apple-hourly-1"
HOUR = timedelta(hours=1)
type NativeMetric = Literal["heart_rate", "steps"]

__all__ = ["AVAILABILITY_RULE", "AppleHourlyView", "HourAudit", "apple_hourly_features"]


@dataclass(frozen=True)
class HourAudit:
    """Known unique native candidates, attributed once to their start hour.

    Reasons are exclusive: late creation first, then crossing, then precedence
    loss, then thinning (only when a thinning slot is requested), or inclusion.
    All counts require creation AND event end <= audit_as_of.
    Audit receipts can grow after closure; they are never feature identity inputs.
    """

    interval_start_utc: datetime
    closure_utc: datetime
    audit_as_of_utc: datetime
    known_candidates: int
    excluded_created_after_seal: int
    excluded_cross_hour: int
    excluded_by_precedence: int
    included_records: int
    sample_minutes: int
    interval_seconds: float
    source_counts: tuple[tuple[str, int], ...]
    excluded_by_thinning: int = 0


@dataclass(frozen=True)
class AppleHourlyView:
    policy: HourlyFeaturePolicy
    features: tuple[HourlyFeature, ...]
    counts: dict[str, int]
    audits: tuple[HourAudit, ...]


@dataclass(frozen=True)
class _AppleFeatureBin:
    aggregate: Aggregate
    available_at_utc: datetime
    sample_minutes: int
    interval_seconds: float
    source_counts: tuple[tuple[str, int], ...]
    selected_records: int


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
    thin_slot_seconds: int | None = None,
) -> _AppleFeatureBin:
    """Pure transform of selected rows already eligible at this hour's end.

    With `thin_slot_seconds`, heart rate is thinned by the Apple-density variant's rule
    (#97): the earliest-starting sample, then lowest record_id, per UTC slot; coverage is
    then the share of the hour's slots holding a sample instead of sampled minutes.
    """
    end = start + HOUR
    included: list[Observation] = []
    for row in rows:
        if row.metric != metric or row.start_utc >= end or row.end_utc < start:
            continue
        if row.start_utc < start or row.end_utc > end:
            continue
        included.append(row)
    included.sort(key=lambda r: (r.start_utc, r.record_id))
    selected = len(included)
    pipeline_version = PIPELINE_VERSION
    if thin_slot_seconds is not None:
        slot_us = thin_slot_seconds * 1_000_000
        slots: set[int] = set()
        kept: list[Observation] = []
        for row in included:
            slot = timestamp_us(row.start_utc) // slot_us
            if slot not in slots:
                slots.add(slot)
                kept.append(row)
        included = kept
        pipeline_version = f"{PIPELINE_VERSION}+thin{thin_slot_seconds}s"
    minutes = len({r.start_utc.minute for r in included}) if metric == "heart_rate" else 0
    seconds = _interval_seconds(included) if metric == "steps" else 0.0
    if thin_slot_seconds is not None:
        coverage = len(included) / (3600 // thin_slot_seconds)
    else:
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
    return _AppleFeatureBin(
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
            pipeline_version=pipeline_version,
        ),
        end,
        minutes,
        seconds,
        tuple(sorted(Counter(r.source_id for r in included).items())),
        selected,
    )


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} requires an aware instant")
    return value.astimezone(UTC)


def _iter_hourly_bins(
    path: Path,
    *,
    metric: NativeMetric,
    aggregation: Aggregation,
    as_of: datetime,
    start: datetime | None = None,
    thin_slot_seconds: int | None = None,
) -> Iterator[tuple[_AppleFeatureBin, HourAudit]]:
    """Replay native precedence at every completed hour end, never at a later cutoff.

    Late creations and intervals ending after that hour are permanently excluded
    from its model input. They remain available through the native observation API.
    This makes value, coverage, source lineage and readiness stable after sealing.
    """
    if metric not in ("heart_rate", "steps"):
        raise ValueError("Apple hourly inputs support only native heart_rate and steps")
    if aggregation not in METRICS[metric].aggregations:
        raise ValueError("aggregation must match the native metric")
    audit_as_of = _utc(as_of, "as_of")
    cutoff = audit_as_of.replace(minute=0, second=0, microsecond=0)
    lower = _utc(start, "start") if start is not None else None
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA cache_size=-4096")
        # Candidate metadata and selector state stay in connection-local RAM.
        # There is no participant temp file to leave behind after a hard crash.
        connection.execute("PRAGMA temp_store=MEMORY")
        if connection.execute("SELECT value FROM metadata WHERE key='completed'").fetchone() != (
            "true",
        ):
            raise ValueError("import has not completed")
        (payload,) = connection.execute("SELECT value FROM metadata WHERE key='config'").fetchone()
        config = ImportConfig.model_validate_json(payload)
        _index_candidates(connection, metric, audit_as_of)
        # Select the grid from native candidates, not full-import winners: a late
        # winning watch record must not erase a previously eligible phone hour.
        (first,) = connection.execute(
            "SELECT min(start_us) FROM temp.hourly_index",
        ).fetchone()
        if first is None:
            return
        hour = (EPOCH + timedelta(microseconds=first)).replace(minute=0, second=0, microsecond=0)
        if lower is not None and lower > hour:
            hour = lower.replace(minute=0, second=0, microsecond=0)
            if hour < lower:
                hour += HOUR
        while hour < cutoff:
            _set_hour_window(connection, hour, hour + HOUR)
            selected = (row for _, row in select_candidates(connection, hour + HOUR))
            item = _aggregate_hour(selected, config, metric, aggregation, hour, thin_slot_seconds)
            yield item, _audit_hour(connection, item, audit_as_of)
            hour += HOUR


def _index_candidates(
    connection: sqlite3.Connection, metric: NativeMetric, as_of: datetime
) -> None:
    """Index known native numeric metadata once, without copying health payloads."""
    connection.execute(
        "CREATE TEMP TABLE hourly_index (row_id INTEGER PRIMARY KEY, "
        "start_us INTEGER, end_us INTEGER, available_us INTEGER)"
    )
    cutoff = timestamp_us(as_of)
    connection.execute(
        "INSERT INTO temp.hourly_index SELECT row_id, start_us, end_us, available_us "
        "FROM main.candidates WHERE family=? AND end_us<=? AND available_us<=?",
        (metric, cutoff, cutoff),
    )
    connection.executescript("""
        CREATE INDEX temp.hourly_start ON hourly_index(start_us);
        CREATE VIRTUAL TABLE temp.hourly_ranges USING rtree(row_id, min_start, max_end);
        INSERT INTO temp.hourly_ranges SELECT row_id, start_us, end_us FROM hourly_index;
        CREATE TEMP TABLE hourly_window (begin_us INTEGER, seal_us INTEGER);
        INSERT INTO temp.hourly_window VALUES (0, 0);
        CREATE TEMP VIEW candidates AS
            SELECT native.* FROM hourly_index idx
            JOIN main.candidates native ON native.row_id=idx.row_id
            JOIN hourly_window win
            WHERE idx.start_us>=win.begin_us AND idx.start_us<win.seal_us
                AND idx.end_us<=win.seal_us AND idx.available_us<=win.seal_us;
    """)


def _set_hour_window(connection: sqlite3.Connection, start: datetime, seal: datetime) -> None:
    """Keep every overlap dependency, including chains before the model lookback.

    At closure, eligible intervals end <= seal. Therefore only the left edge
    needs expanding. Greedy source selection is independent across disconnected
    overlap components; pruning those components cannot change a retained winner.
    RTree bounds only narrow candidates; exact integer predicates decide edges.
    """
    begin, end = timestamp_us(start), timestamp_us(seal)
    while True:
        (earlier,) = connection.execute(
            "SELECT min(idx.start_us) FROM temp.hourly_ranges bounds "
            "JOIN temp.hourly_index idx ON idx.row_id=bounds.row_id "
            "WHERE bounds.min_start<=:begin AND bounds.max_end>=:begin "
            "AND idx.start_us<:begin AND idx.end_us>:begin "
            "AND idx.end_us<=:seal AND idx.available_us<=:seal",
            {"begin": begin, "seal": end},
        ).fetchone()
        if earlier is None:
            break
        begin = earlier
    connection.execute("UPDATE temp.hourly_window SET begin_us=?, seal_us=?", (begin, end))


def _audit_hour(
    connection: sqlite3.Connection,
    item: _AppleFeatureBin,
    as_of: datetime,
) -> HourAudit:
    row = item.aggregate
    begin, seal, cutoff = map(timestamp_us, (row.interval_start_utc, row.interval_end_utc, as_of))
    known = late = crossing = 0
    candidates = connection.execute(
        "SELECT end_us, available_us FROM temp.hourly_index "
        "WHERE start_us>=? AND start_us<? AND end_us<=? AND available_us<=?",
        (begin, seal, cutoff, cutoff),
    )
    for end, available in candidates:
        known += 1
        if available > seal:
            late += 1
        elif end > seal:
            crossing += 1
    return HourAudit(
        row.interval_start_utc,
        row.interval_end_utc,
        as_of,
        known,
        late,
        crossing,
        known - late - crossing - item.selected_records,
        row.observed_count,
        item.sample_minutes,
        item.interval_seconds,
        item.source_counts,
        item.selected_records - row.observed_count,
    )


def apple_hourly_features(
    path: Path,
    policy: HourlyFeaturePolicy,
    as_of: datetime,
    start: datetime | None = None,
    *,
    thin_slot_seconds: int | None = None,
) -> AppleHourlyView:
    """Apply the existing model gates with an explicitly Apple-specific policy.

    Never silently rewrite a frozen PMData policy or claim its availability rule.
    Source compatibility must be declared by the serving/model owner separately.
    `thin_slot_seconds` applies the thinning a serving profile declares, after sealing
    and source precedence, so a thinned artifact sees Apple bins built its own way.
    """
    if policy.availability_rule != AVAILABILITY_RULE:
        raise ValueError("Apple hourly inputs require their source-specific availability rule")
    if policy.metric not in ("heart_rate", "steps"):
        raise ValueError("Apple hourly inputs support only native heart_rate and steps")
    if thin_slot_seconds is not None and (
        policy.metric != "heart_rate"
        or not 0 < thin_slot_seconds <= 3600
        or 3600 % thin_slot_seconds
    ):
        raise ValueError("thinning applies to heart rate, with slots that tile the hour")
    bins: list[_AppleFeatureBin] = []
    audits: list[HourAudit] = []
    for item, audit in _iter_hourly_bins(
        path,
        metric=policy.metric,
        aggregation=policy.aggregation,
        as_of=as_of,
        start=start,
        thin_slot_seconds=thin_slot_seconds,
    ):
        bins.append(item)
        audits.append(audit)
    view = _select_features(bins, policy)
    return AppleHourlyView(view.policy, view.features, view.counts, tuple(audits))
