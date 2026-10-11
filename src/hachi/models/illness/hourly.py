"""Bounded native Stanford physiology on its shifted floating clock, never cross-dataset UTC."""

import csv
import hashlib
import json
import math
import tomllib
import zipfile
from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, model_validator

from hachi.contracts.base import Contract, Sha256, UtcDatetime
from hachi.data.clinical.config import registry_admission
from hachi.data.clinical.snapshot import check_admitted
from hachi.models.baselines.stanford.source import phase1_members

HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)


class ContextProtocol(Contract):
    protocol_id: str
    clock: Literal["floating_local_shifted"]
    dataset_id: Literal["stanford-covid19-wearables"]
    snapshot_sha256: Sha256
    active_outer_fold: Literal[0]
    nested_plan_sha256: Sha256
    context_hours: Annotated[int, Field(ge=1, le=8192)]
    prediction_hours: Annotated[int, Field(ge=1, le=1024)]
    min_observed_hr_hours: Annotated[int, Field(ge=1)]
    min_recorded_hr_minutes_per_hour: Annotated[int, Field(ge=1, le=60)]
    hr_minute_statistic: Literal["median"]
    hr_hour_statistic: Literal["mean-of-recorded-minute-medians"]
    step_edge_policy: Literal["both-complete-and-equal-hour-totals"]
    primary_model_channels: tuple[Literal["heart_rate"], ...]
    availability_rule: Literal["floating-native-points-assumed-end-ready-hours-complete-v1"]

    @model_validator(mode="after")
    def _minimum(self):
        if self.min_observed_hr_hours > self.context_hours:
            raise ValueError("minimum observed hours must fit context")
        if self.primary_model_channels != ("heart_rate",):
            raise ValueError("primary exported model contexts are HR-only")
        return self


class NativePoint(Contract):
    at: UtcDatetime
    available_at: UtcDatetime
    metric: Literal["heart_rate", "steps"]
    value: FiniteFloat

    @model_validator(mode="after")
    def _native(self):
        if self.available_at < self.at:
            raise ValueError("native availability must not precede event")
        if self.metric == "heart_rate" and not 1 <= self.value <= 300:
            raise ValueError("HR outside source-compatible range")
        if self.metric == "steps" and (self.value < 0 or self.at.second or self.at.microsecond):
            raise ValueError("steps need nonnegative minute-aligned totals")
        return self


class ClinicalHour(Contract):
    start: UtcDatetime
    end: UtcDatetime
    available_at: UtcDatetime
    hr_bpm: FiniteFloat | None
    recorded_hr_minutes: Annotated[int, Field(ge=0, le=60)]
    steps_total: Annotated[FiniteFloat, Field(ge=0)] | None
    complete_step_minutes: Annotated[int, Field(ge=0, le=60)]

    @model_validator(mode="after")
    def _hour(self):
        if (
            self.start.minute
            or self.start.second
            or self.start.microsecond
            or (self.end - self.start != HOUR or self.available_at < self.end)
        ):
            raise ValueError("clinical hours must be complete aligned intervals")
        return self


@dataclass(frozen=True)
class NativeSeries:
    points: tuple[NativePoint, ...]
    counts: dict[str, int]
    source_sha256: str


def load_context_protocol(path: Path) -> ContextProtocol:
    # JSON validation parses TOML arrays into precise tuples under Contract strict mode.
    return ContextProtocol.model_validate_json(json.dumps(tomllib.loads(path.read_text())))


def verify_archive(archive: Path, protocol: ContextProtocol) -> str:
    admitted = registry_admission(protocol.dataset_id).files["COVID-19-Wearables.zip"]
    check_admitted(archive, admitted)
    return admitted.sha256


def read_native_context(
    archive: Path, subject: str, cutoffs: Sequence[datetime], protocol: ContextProtocol
) -> NativeSeries:
    """Admission is verified once by the export caller; streaming reads check native zip CRC."""
    ordered = sorted(set(cutoffs))
    if not ordered:
        return NativeSeries((), {}, hashlib.sha256(b"").hexdigest())
    if any(c.utcoffset() != timedelta(0) or c.minute or c.second or c.microsecond for c in ordered):
        raise ValueError("context cutoffs must be aligned floating-clock coordinates")
    points = []
    counts: Counter[str] = Counter()
    selected = [
        m
        for m in phase1_members(archive)
        if m.subject_id == subject
        and m.source == "standard"
        and m.stream in {"heart_rate", "steps"}
    ]
    if len({m.stream for m in selected}) != len(selected):
        raise ValueError("duplicate standard native channel")
    source = hashlib.sha256()
    with zipfile.ZipFile(archive) as z:
        for member in selected:
            value_column = "heartrate" if member.stream == "heart_rate" else "steps"
            with z.open(member.name) as raw:
                # The digest covers all bytes read, while requested physiology stays bounded.
                content = hashlib.sha256()

                def lines(stream=raw, digest=content):
                    for line in stream:
                        digest.update(line)
                        yield line.decode("utf-8-sig")

                reader = csv.DictReader(lines())
                if reader.fieldnames != ["user", "datetime", value_column]:
                    raise ValueError("native header differs from admitted phase1 schema")
                for row in reader:
                    counts[f"{member.stream}:source_rows"] += 1
                    if row.get("user") != subject:
                        counts[f"{member.stream}:quarantined_subject"] += 1
                        continue
                    try:
                        stamp = datetime.fromisoformat(row["datetime"])
                        value = float(row[value_column])
                        if stamp.tzinfo is not None or not math.isfinite(value):
                            raise ValueError("unsupported native value/time")
                        at = stamp.replace(tzinfo=UTC)
                        ready = at if member.stream == "heart_rate" else at + MINUTE
                        # Keep only points any requested past context could consume.
                        i = bisect_left(ordered, ready)
                        if i == len(ordered) or at < ordered[i] - protocol.context_hours * HOUR:
                            counts[f"{member.stream}:outside_requested_windows"] += 1
                            continue
                        point = NativePoint(
                            at=at, available_at=ready, metric=member.stream, value=value
                        )
                    except (ValueError, TypeError, KeyError):
                        counts[f"{member.stream}:quarantined_value_time"] += 1
                        continue
                    points.append(point)
                    counts[f"{member.stream}:bounded_points"] += 1
                source.update(content.digest())
    return NativeSeries(tuple(points), dict(sorted(counts.items())), source.hexdigest())


def causal_hours(
    points: Sequence[NativePoint], cutoff: datetime, protocol: ContextProtocol
) -> tuple[ClinicalHour, ...]:
    """Recompute from records available by this cutoff; late/backdated points cannot leak."""
    if cutoff.utcoffset() != timedelta(0) or cutoff.minute or cutoff.second or cutoff.microsecond:
        raise ValueError("context cutoff must be an aligned floating-clock coordinate")
    start = cutoff - protocol.context_hours * HOUR
    values: dict[tuple[str, datetime], set[float]] = defaultdict(set)
    readiness: dict[tuple[str, datetime], datetime] = {}
    for p in points:
        if start <= p.at <= cutoff and p.available_at <= cutoff:
            key = (p.metric, p.at)
            values[key].add(p.value)
            readiness[key] = min(readiness.get(key, p.available_at), p.available_at)
    # Disagreeing native duplicates become unknown, with no value chosen from their order.
    hr_minutes: dict[datetime, list[float]] = defaultdict(list)
    hr_ready: dict[datetime, list[datetime]] = defaultdict(list)
    steps = {}
    for (metric, at), observed in values.items():
        if len(observed) != 1:
            continue
        value = next(iter(observed))
        if metric == "heart_rate" and at < cutoff:
            minute = at.replace(second=0, microsecond=0)
            hr_minutes[minute].append(value)
            hr_ready[minute].append(readiness[(metric, at)])
        elif metric == "steps":
            steps[at] = value
    output = []
    hour = start
    while hour < cutoff:
        minute_values, start_steps, end_steps = [], [], []
        used_ready = [hour + HOUR]
        minute = hour
        for _ in range(60):
            if minute in hr_minutes:
                minute_values.append(median(hr_minutes[minute]))
                used_ready.extend(hr_ready[minute])
            if minute in steps and minute + MINUTE in steps:
                start_steps.append(steps[minute])
                end_steps.append(steps[minute + MINUTE])
                used_ready.extend(
                    [readiness[("steps", minute)], readiness[("steps", minute + MINUTE)]]
                )
            minute += MINUTE
        hr = (
            mean(minute_values)
            if len(minute_values) >= (protocol.min_recorded_hr_minutes_per_hour)
            else None
        )
        step_total = (
            sum(start_steps)
            if len(start_steps) == 60 and sum(start_steps) == sum(end_steps)
            else None
        )
        output.append(
            ClinicalHour(
                start=hour,
                end=hour + HOUR,
                available_at=max(used_ready),
                hr_bpm=hr,
                recorded_hr_minutes=len(minute_values),
                steps_total=step_total,
                complete_step_minutes=len(start_steps),
            )
        )
        hour += HOUR
    return tuple(output)
