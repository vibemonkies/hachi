"""Stream the admitted phase-1 native HR/steps; labels and row values stay private."""

import csv
import io
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path

from pydantic import ValidationError

from hachi.data.clinical.wearables import Member, list_members

from .rest import HeartRatePoint, StepPoint


@dataclass(frozen=True)
class NativeNights:
    heart_rate: dict[date, tuple[HeartRatePoint, ...]]
    steps: dict[date, tuple[StepPoint, ...]]
    counts: dict[str, int]
    members: tuple[str, ...]


def standard_pair(members: list[Member], subject: str) -> tuple[Member, Member] | None:
    """Freeze standard files only; never combine unspecified devices or long-term overlap."""
    selected = {
        member.stream: member
        for member in members
        if member.subject_id == subject
        and member.source == "standard"
        and member.stream in {"heart_rate", "steps"}
    }
    if set(selected) != {"heart_rate", "steps"}:
        return None
    return selected["heart_rate"], selected["steps"]


def read_native_nights(
    archive: Path, members: list[Member], subject: str, first: date, last: date
) -> NativeNights:
    """Admission SHA checking belongs to the caller; zip CRC is checked through EOF here.

    Keep midnight-07:00 HR and midnight-07:00 inclusive step timestamps. The extra
    07:00 step supports minute-edge sensitivity. Missing or malformed rows are
    quarantined/countable, never zeros. Aware timestamps are refused as incompatible
    with this source's shifted, naive floating clock.
    """
    pair = standard_pair(members, subject)
    if pair is None:
        return NativeNights({}, {}, {"excluded_no_standard_pair": 1}, ())
    heart_rate: dict[date, list[HeartRatePoint]] = defaultdict(list)
    steps: dict[date, list[StepPoint]] = defaultdict(list)
    counts: Counter[str] = Counter()
    with zipfile.ZipFile(archive) as z:
        for member in pair:
            with z.open(member.name) as stream:
                reader = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""))
                value_column = "heartrate" if member.stream == "heart_rate" else "steps"
                if reader.fieldnames != ["user", "datetime", value_column]:
                    raise ValueError(
                        "phase1 native header does not match its admitted source schema"
                    )
                for row in reader:
                    counts[f"{member.stream}_input_rows"] += 1
                    if row.get("user") != subject:
                        counts[f"{member.stream}_quarantined_subject_mismatch"] += 1
                        continue
                    try:
                        at = datetime.fromisoformat(row["datetime"])
                        if at.tzinfo is not None:
                            raise ValueError("floating clock requires naive source timestamps")
                    except (ValueError, TypeError):
                        counts[f"{member.stream}_quarantined_timestamp"] += 1
                        continue
                    day = at.date()
                    if not first <= day <= last:
                        counts[f"{member.stream}_outside_date_range"] += 1
                        continue
                    if (
                        at.time() >= time(7)
                        if member.stream == "heart_rate"
                        else at.time() > time(7)
                    ):
                        counts[f"{member.stream}_outside_night"] += 1
                        continue
                    try:
                        value = float(row[value_column])
                        if member.stream == "heart_rate":
                            point = HeartRatePoint(at=at.replace(tzinfo=UTC), bpm=value)
                            heart_rate[day].append(point)
                        else:
                            point = StepPoint(at=at.replace(tzinfo=UTC), steps=value)
                            steps[day].append(point)
                    except (ValueError, TypeError, ValidationError):
                        counts[f"{member.stream}_quarantined_value_or_alignment"] += 1
                        continue
                    counts[f"{member.stream}_included_points"] += 1
    return NativeNights(
        {d: tuple(rows) for d, rows in heart_rate.items()},
        {d: tuple(rows) for d, rows in steps.items()},
        dict(sorted(counts.items())),
        tuple(m.name for m in pair),
    )


def phase1_members(archive: Path) -> list[Member]:
    return list_members(archive, "phase1")[0]
