"""Shared building blocks for every Hachi contract.

All contract models are strict, immutable and reject unknown fields: a payload either matches
the documented shape exactly or it is refused at the boundary.
"""

from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, available_timezones

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

SCHEMA_VERSION = "0.1"
type SchemaVersion = Literal["0.1"]


class Contract(BaseModel):
    """Base for all contract models."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


def _require_utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be expressed in UTC (Z or +00:00)")
    return value.astimezone(UTC)


@cache
def _iana_timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def _require_iana_timezone(value: str) -> str:
    if value not in _iana_timezones():
        raise ValueError("timezone must be an IANA name such as 'America/Los_Angeles'")
    return value


def _require_relative_path(value: str) -> str:
    # Split by hand: PurePosixPath silently drops "." segments and repeated slashes.
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("path must be relative and must not contain '.' or '..' segments")
    return value


type UtcDatetime = Annotated[
    AwareDatetime,
    AfterValidator(_require_utc),
    Field(description="UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected."),
]
type IanaTimezone = Annotated[
    str,
    AfterValidator(_require_iana_timezone),
    Field(description="IANA timezone name. Local time decides day and sleep boundaries."),
]
type Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    Field(description="Opaque id of letters, digits, '_' and '-'; never usable as a path."),
]
type SubjectId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"),
    Field(description="Pseudonymous subject id. Identity mapping stays outside Git."),
]
type VersionString = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
]
type Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
type GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
type FeatureName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
type RelativePath = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_][A-Za-z0-9._/-]{0,255}$"),
    AfterValidator(_require_relative_path),
    Field(description="Path relative to an approved storage root; no '..' segments."),
]
type Text = Annotated[str, StringConstraints(min_length=1, max_length=2000)]
type Probability = Annotated[float, Field(ge=0.0, le=1.0)]

type DataMode = Annotated[
    Literal["real", "synthetic"],
    Field(description="Whether a document derives from real observations or a synthetic fixture."),
]

type TaskName = Literal["physiology_forecast", "anomaly", "illness_onset", "recovery", "alertness"]


class DatasetSnapshotRef(Contract):
    """Identifies the exact dataset snapshot a document was computed from."""

    dataset_id: Identifier
    dataset_version: VersionString
    snapshot_sha256: Sha256


class ArtifactRef(Contract):
    """Identifies an immutable model artifact directory by id and checksum."""

    artifact_id: Identifier
    artifact_sha256: Sha256


def local_day_bounds(local_date: date, tz_name: str) -> tuple[datetime, datetime]:
    """Return the UTC instants bounding one local calendar day.

    Days are 23 or 25 hours long across DST changes. When local midnight does not exist,
    the day starts at the transition instant.
    """
    zone = ZoneInfo(tz_name)
    start = datetime.combine(local_date, time(0), zone).astimezone(UTC)
    end = datetime.combine(local_date + timedelta(days=1), time(0), zone).astimezone(UTC)
    return start, end


def require_ordered(start: datetime, end: datetime, label: str, *, allow_equal: bool) -> None:
    if end < start or (end == start and not allow_equal):
        raise ValueError(f"{label}: end must be {'at or ' if allow_equal else ''}after start")


def require_unique(values: list, label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must not contain duplicates")
