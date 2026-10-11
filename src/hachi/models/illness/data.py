"""At-risk labels and cutoff-safe feature inputs; outcome metadata never enters features."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from pydantic import Field, FiniteFloat, model_validator

from hachi.contracts.base import Contract, Sha256, UtcDatetime
from hachi.data.clinical.labels import at
from hachi.data.clinical.snapshot import load_manifest, read_table
from hachi.evaluation.serialization import document_sha256

from .protocol import Protocol


class FeaturePoint(Contract):
    """One past-only external feature, available by cutoff on the floating clock.

    Feature-producing models must declare their training participants separately.
    Episode/test/recovery fields are forbidden predictors even if retrospective labels exist.
    """

    subject_id: str
    at: UtcDatetime
    available_at: UtcDatetime
    values: tuple[FiniteFloat | None, ...]

    @model_validator(mode="after")
    def _availability(self):
        if self.available_at < self.at:
            raise ValueError("a feature cannot be available before its event")
        return self


class FeatureSet(Contract):
    feature_names: Annotated[tuple[str, ...], Field(min_length=1)]
    provenance_sha256: Sha256
    fit_subjects: tuple[str, ...]
    clock: str
    points: tuple[FeaturePoint, ...]

    @model_validator(mode="after")
    def _shape(self):
        if self.clock != "floating_local_shifted":
            raise ValueError("clinical feature clock must be floating_local_shifted")
        if len(set(self.feature_names)) != len(self.feature_names):
            raise ValueError("duplicate feature names")
        if any(len(p.values) != len(self.feature_names) for p in self.points):
            raise ValueError("feature values do not match feature names")
        keys = [(p.subject_id, p.at) for p in self.points]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate feature points")
        return self


@dataclass(frozen=True)
class Window:
    subject_id: str
    cutoff: datetime
    horizon_hours: int
    positive: bool
    episode_id: str | None
    onset_first: datetime | None
    onset_end: datetime | None
    features: tuple[float | None, ...]


def survey_features(
    surveys: dict[date, str], cutoff: datetime, lookback_days: int
) -> tuple[float, ...]:
    """Only a daily survey whose day has ended can affect this cutoff."""
    known = [
        state
        for day, state in surveys.items()
        if cutoff - timedelta(days=lookback_days) < at(day + timedelta(days=1)) <= cutoff
    ]
    return (
        float(len(known)),
        float(sum(s == "symptom_free" for s in known)),
        float(sum(s == "symptomatic" for s in known)),
        float(sum(s == "intermediate" for s in known)),
    )


SURVEY_FEATURE_NAMES = (
    "past_7d_survey_count",
    "past_7d_symptom_free_count",
    "past_7d_symptomatic_count",
    "past_7d_intermediate_count",
)


def external_at(
    points: Sequence[FeaturePoint], cutoff: datetime, max_age_days: int
) -> tuple[float | None, ...] | None:
    eligible = [
        p
        for p in points
        if cutoff - timedelta(days=max_age_days) <= p.at <= cutoff and p.available_at <= cutoff
    ]
    return max(eligible, key=lambda p: p.at).values if eligible else None


def at_risk_windows(
    snapshot: Path,
    subjects: Sequence[str],
    protocol: Protocol,
    external: FeatureSet | None = None,
) -> tuple[list[Window], dict[str, int]]:
    """Read only designated development participants; known outcome fields stay labels."""
    manifest = load_manifest(snapshot)
    if (
        manifest["dataset_snapshot"]["snapshot_sha256"] != protocol.snapshot_sha256
        or manifest["dataset_snapshot"]["dataset_id"] != protocol.dataset_id
        or manifest["clock"] != protocol.clock
        or manifest["definitions"]["definitions_version"] != protocol.definitions_version
    ):
        raise ValueError("snapshot identity/clock/definitions differ from frozen protocol")
    surveys: dict[str, dict[date, str]] = {}
    for r in read_table(snapshot, "surveys", subjects).to_pylist():
        surveys.setdefault(r["subject_id"], {})[r["local_date"]] = r["state"]
    # These fields attach event-level labels and interval lead times only.
    episodes = {
        r["episode_id"]: (at(r["onset_first_day"]), at(r["onset_last_day"] + timedelta(days=1)))
        for r in read_table(snapshot, "episodes", subjects).to_pylist()
    }
    points: dict[str, list[FeaturePoint]] = {}
    if external:
        for p in external.points:
            if p.subject_id in subjects:
                points.setdefault(p.subject_id, []).append(p)
    result, counts = [], Counter()
    for r in read_table(snapshot, "onset_windows", subjects).to_pylist():
        cutoff, sid = r["cutoff_utc"], r["subject_id"]
        features = survey_features(surveys.get(sid, {}), cutoff, protocol.feature_lookback_days)
        if external:
            values = external_at(points.get(sid, []), cutoff, protocol.feature_lookback_days)
            features += values or (None,) * len(external.feature_names)
        for h in protocol.horizons_hours:
            label = r[f"onset_{h}h"]
            counts[f"{h}h:{label}"] += 1
            if label not in {"positive", "negative"}:
                continue
            eid = r[f"onset_episode_{h}h"]
            lo, hi = episodes[eid] if eid else (None, None)
            result.append(Window(sid, cutoff, h, label == "positive", eid, lo, hi, features))
    return result, dict(sorted(counts.items()))


def roster(snapshot: Path) -> tuple[str, ...]:
    return tuple(sorted(read_table(snapshot, "subjects").column("subject_id").to_pylist()))


def feature_identity(protocol: Protocol, external: FeatureSet | None = None) -> str:
    return document_sha256(
        {
            "survey_availability": "end-of-floating-local-day",
            "lookback_days": protocol.feature_lookback_days,
            "external": external,
        }
    )
