"""Causal weekly input windows for frozen wearable encoders, built from PMData hourly bins.

A window covers the seven local calendar days before a local midnight ``m`` (168 local hours,
the alignment WBM was pretrained on). It is computed as of ``m + as_of_delay_hours`` and only
reads bins that had ended and were final by then; a bin that existed but was not yet final is
unknown, never zero. A predictor at cutoff ``c`` uses the latest window whose as-of instant is
at or before ``c``, so recomputing from a snapshot truncated at ``c`` gives the same input.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import numpy as np
from pydantic import Field

from hachi.contracts.base import Contract, IanaTimezone
from hachi.data.pmdata import FeatureBin, iter_aggregates, load_manifest

HOUR = timedelta(hours=1)
HOURS_PER_DAY = 24

# Native hourly channels, in this order, before any model-specific layout.
CHANNELS = ("heart_rate", "steps", "walking_running_distance", "sleep_asleep", "sleep_in_bed")
ASLEEP_METRICS = (
    "sleep_asleep_core",
    "sleep_asleep_deep",
    "sleep_asleep_rem",
    "sleep_asleep_unspecified",
)
SOURCE_METRICS = {
    "heart_rate": ("heart_rate", "mean"),
    "steps": ("steps", "sum"),
    "walking_running_distance": ("walking_running_distance", "sum"),
    "sleep_in_bed": ("sleep_in_bed", "sum"),
    **{m: (m, "sum") for m in ASLEEP_METRICS},
}


class WindowConfig(Contract):
    days: Annotated[int, Field(ge=1, le=28)] = 7
    as_of_delay_hours: Annotated[int, Field(ge=0, le=48)]
    min_observed_hours: Annotated[int, Field(ge=1)] = 24
    local_timezone: IanaTimezone


@dataclass(frozen=True)
class WeekWindows:
    """Native-channel windows; values are NaN where unknown as of the window's as-of instant."""

    subject_ids: tuple[str, ...]
    window_end_utc: tuple[datetime, ...]
    as_of_utc: tuple[datetime, ...]
    values: np.ndarray  # (n, hours, len(CHANNELS)) float32
    worn: np.ndarray  # (n, hours) bool: heart rate or steps known in that hour

    def __len__(self) -> int:
        return len(self.subject_ids)

    def keys(self) -> list[tuple[str, str]]:
        return [
            (s, e.isoformat()) for s, e in zip(self.subject_ids, self.window_end_utc, strict=True)
        ]


@dataclass(frozen=True)
class _Cell:
    value: float | None
    available_at: datetime


def snapshot_timezone(snapshot: Path) -> str:
    """The local timezone the snapshot's pipeline config declares for its cohort."""
    return load_manifest(snapshot)["config"]["content"]["local_timezone"]


def load_bins(snapshot: Path, subjects: Sequence[str] | None = None) -> list[FeatureBin]:
    """Every hourly bin the windows can use (values, nulls and their availability)."""
    wanted = {(m, a) for m, a in SOURCE_METRICS.values()}
    return [
        b
        for b in iter_aggregates(
            snapshot, "hour", subjects=subjects, metrics=sorted({m for m, _ in wanted})
        )
        if (b.aggregate.metric, b.aggregate.aggregation) in wanted
    ]


def _local_hours(midnight: datetime, days: int, zone: ZoneInfo) -> list[datetime | None]:
    """UTC starts of the local hours in the ``days`` before ``midnight``; None where a DST gap
    removes the local hour. A repeated local hour resolves to its first occurrence."""
    end_day = midnight.astimezone(zone).date()
    hours: list[datetime | None] = []
    for offset in range(days, 0, -1):
        day = end_day - timedelta(days=offset)
        for hour in range(HOURS_PER_DAY):
            local = datetime(day.year, day.month, day.day, hour, tzinfo=zone)
            start = local.astimezone(UTC)
            hours.append(
                start
                if start.astimezone(zone).replace(tzinfo=None) == local.replace(tzinfo=None)
                else None
            )
    return hours


def _local_midnight(day: date, zone: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(UTC)


def build_windows(bins: Iterable[FeatureBin], config: WindowConfig) -> WeekWindows:
    """One window per subject and local midnight whose input week has enough known hours."""
    zone = ZoneInfo(config.local_timezone)
    cells: dict[str, dict[tuple[str, datetime], _Cell]] = defaultdict(dict)
    for b in bins:
        row = b.aggregate
        if row.resolution != "hour":
            raise ValueError("windows need hourly bins")
        if SOURCE_METRICS.get(row.metric) != (row.metric, row.aggregation):
            continue
        key = (row.metric, row.interval_start_utc)
        if key in cells[row.subject_id]:
            raise ValueError("duplicate hourly bin; ingestion must resolve precedence first")
        cells[row.subject_id][key] = _Cell(row.value, b.available_at_utc)

    subjects: list[str] = []
    ends: list[datetime] = []
    as_ofs: list[datetime] = []
    blocks: list[np.ndarray] = []
    worn_blocks: list[np.ndarray] = []
    hours = config.days * HOURS_PER_DAY
    for subject in sorted(cells):
        table = cells[subject]
        starts = [t for _, t in table]
        first = min(starts).astimezone(zone).date()
        last = max(starts).astimezone(zone).date()
        day = first + timedelta(days=config.days)
        while day <= last + timedelta(days=1):
            midnight = _local_midnight(day, zone)
            as_of = midnight + config.as_of_delay_hours * HOUR
            values = np.full((hours, len(CHANNELS)), np.nan, dtype=np.float32)
            worn = np.zeros(hours, dtype=bool)
            for index, start in enumerate(_local_hours(midnight, config.days, zone)):
                if start is None:
                    continue
                values[index], worn[index] = _hour(table, start, as_of)
            if int(np.isfinite(values).any(axis=1).sum()) >= config.min_observed_hours:
                subjects.append(subject)
                ends.append(midnight)
                as_ofs.append(as_of)
                blocks.append(values)
                worn_blocks.append(worn)
            day += timedelta(days=1)
    return WeekWindows(
        tuple(subjects),
        tuple(ends),
        tuple(as_ofs),
        np.stack(blocks) if blocks else np.zeros((0, hours, len(CHANNELS)), np.float32),
        np.stack(worn_blocks) if worn_blocks else np.zeros((0, hours), bool),
    )


def _hour(
    table: dict[tuple[str, datetime], _Cell], start: datetime, as_of: datetime
) -> tuple[list[float], bool]:
    def known(metric: str) -> float | None:
        cell = table.get((metric, start))
        if cell is None or cell.available_at > as_of or cell.value is None:
            return None
        return cell.value

    def pending(metrics: Sequence[str]) -> bool:
        return any(
            (cell := table.get((m, start))) is not None and cell.available_at > as_of
            for m in metrics
        )

    heart_rate = known("heart_rate")
    steps = known("steps")
    distance = known("walking_running_distance")
    worn = heart_rate is not None or steps is not None

    def state(metrics: Sequence[str]) -> float:
        # A recorded segment marks the hour; a worn hour without one is observed "not in it";
        # an unworn hour, or one whose sleep log was not final yet, is unknown.
        if pending(metrics):
            return np.nan
        if any((known(m) or 0.0) > 0 for m in metrics):
            return 1.0
        return 0.0 if worn else np.nan

    row = [
        np.nan if heart_rate is None else heart_rate,
        np.nan if steps is None else steps,
        np.nan if distance is None else distance,
        state(ASLEEP_METRICS),
        state(("sleep_in_bed",)),
    ]
    return row, worn
