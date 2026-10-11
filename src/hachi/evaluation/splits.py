"""Participant assignment and non-overlapping rolling origins for canonical manifests."""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, TypedDict

from pydantic import TypeAdapter

from hachi.contracts.base import Contract, SubjectId
from hachi.contracts.manifests import Exclusion, SplitManifest, TimeWindow

type Partition = Literal["validation", "test"]


class Partitions(TypedDict):
    train_subjects: list[str]
    validation_subjects: list[str]
    test_subjects: list[str]
    exclusions: list[Exclusion]


def partition_participants(
    subjects: Iterable[str],
    *,
    seed: int,
    validation_count: int,
    test_count: int,
    exclusions: Iterable[Exclusion] = (),
) -> Partitions:
    """Return fields for SplitManifest, with assignments independent of input order.

    Counts are explicit: small-cohort scientific split choices are not inferred here.
    Hash-ranking avoids dependence on a particular Python shuffle implementation.
    """
    ids = TypeAdapter(list[SubjectId], config=Contract.model_config).validate_python(list(subjects))
    if len(set(ids)) != len(ids):
        raise ValueError("participant roster contains duplicates")
    excluded = sorted(exclusions, key=lambda e: (e.subject_id, e.record_id or "", e.reason))
    if any(e.subject_id not in ids for e in excluded):
        raise ValueError("exclusions must refer to participants in the roster")
    whole_subjects = {e.subject_id for e in excluded if e.record_id is None}
    eligible = [s for s in ids if s not in whole_subjects]
    if validation_count < 0 or test_count < 0:
        raise ValueError("partition counts must be nonnegative")
    if validation_count + test_count >= len(eligible):
        raise ValueError("partition counts must leave at least one training participant")
    ranked = sorted(eligible, key=lambda s: (hashlib.sha256(f"{seed}:{s}".encode()).digest(), s))
    return {
        "validation_subjects": sorted(ranked[:validation_count]),
        "test_subjects": sorted(ranked[validation_count : validation_count + test_count]),
        "train_subjects": sorted(ranked[validation_count + test_count :]),
        "exclusions": excluded,
    }


@dataclass(frozen=True)
class Origin:
    subject_id: str
    cutoff: datetime
    targets: tuple[TimeWindow, ...]


@dataclass(frozen=True)
class OriginExclusion:
    subject_id: str
    cutoff: datetime
    reason: Literal["overlapping_targets", "target_outside_window", "insufficient_history"]


@dataclass(frozen=True)
class OriginPlan:
    partition: Partition
    origins: tuple[Origin, ...]
    exclusions: tuple[OriginExclusion, ...]


def rolling_origins(manifest: SplitManifest, partition: Partition) -> OriginPlan:
    """Freeze a target grid without consulting future labels or their missingness.

    The manifest's evaluation window contains cutoffs AND complete target windows.
    Embargo is the canonical gap after a cutoff, not extra lookback or a split gap.
    """
    if manifest.task != "physiology_forecast":
        raise ValueError("this scheduler currently supports physiology_forecast only")
    if partition not in ("validation", "test"):
        raise ValueError("partition must be validation or test")
    if partition == "test" and manifest.test_opened_at_utc is None:
        raise ValueError("test cohort is sealed; supply an explicitly opened SplitManifest")
    window = manifest.evaluation_window
    if window is None:
        raise ValueError("an explicit evaluation_window is required")
    if window.start_utc.minute or window.start_utc.second or window.start_utc.microsecond:
        raise ValueError("hourly evaluation must start on a UTC hour boundary")
    subjects = manifest.validation_subjects if partition == "validation" else manifest.test_subjects
    if not subjects:
        raise ValueError("the requested partition has no participants")
    origins: list[Origin] = []
    exclusions: list[OriginExclusion] = []
    hour = timedelta(hours=1)
    for subject in sorted(subjects):
        cutoff = window.start_utc
        previous_end = window.start_utc
        while cutoff < window.end_utc:
            start = cutoff + manifest.embargo_hours * hour
            end = start + manifest.horizon_hours * hour
            if end > window.end_utc:
                exclusions.append(OriginExclusion(subject, cutoff, "target_outside_window"))
            elif start < previous_end:
                exclusions.append(OriginExclusion(subject, cutoff, "overlapping_targets"))
            else:
                targets = tuple(
                    TimeWindow(start_utc=start + i * hour, end_utc=start + (i + 1) * hour)
                    for i in range(manifest.horizon_hours)
                )
                origins.append(Origin(subject, cutoff, targets))
                previous_end = end
            cutoff += manifest.cutoff_stride_hours * hour
    if not origins:
        raise ValueError("evaluation window contains no complete target horizon")
    return OriginPlan(
        partition,
        tuple(sorted(origins, key=lambda o: (o.cutoff, o.subject_id))),
        tuple(sorted(exclusions, key=lambda e: (e.cutoff, e.subject_id, e.reason))),
    )
