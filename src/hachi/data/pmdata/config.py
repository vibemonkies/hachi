"""Pipeline configuration and the admitted archive it may read."""

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import (
    Contract,
    IanaTimezone,
    Identifier,
    SchemaVersion,
    Sha256,
    VersionString,
)
from hachi.contracts.metrics import METRICS, Aggregation, Metric
from hachi.contracts.tables import SourceKind

CONFIG_PATH = Path(__file__).resolve().parents[4] / "configs" / "features" / "pmdata.toml"

# Metrics PMData can supply, and the resolutions each is binned at. Vendor resting HR is a
# whole-day value: spreading it over hours would invent hourly structure the source lacks.
RESOLUTIONS: dict[Metric, tuple[Literal["hour", "day"], ...]] = {
    "heart_rate": ("hour", "day"),
    "resting_heart_rate_vendor": ("day",),
    "steps": ("hour", "day"),
    "walking_running_distance": ("hour", "day"),
    "sleep_in_bed": ("hour", "day"),
    "sleep_asleep_unspecified": ("hour", "day"),
    "sleep_asleep_core": ("hour", "day"),
    "sleep_asleep_deep": ("hour", "day"),
    "sleep_asleep_rem": ("hour", "day"),
    "sleep_awake": ("hour", "day"),
}

type Fraction = Annotated[float, Field(ge=0.0, le=1.0)]
type LagSeconds = Annotated[int, Field(ge=0, le=7 * 24 * 3600)]


class Availability(Contract):
    intraday_lag_seconds: LagSeconds
    daily_summary_lag_seconds: LagSeconds
    sleep_lag_seconds: LagSeconds


class MinCoverage(Contract):
    hour: Fraction | None = None
    day: Fraction | None = None


class PipelineConfig(Contract):
    schema_version: SchemaVersion
    pipeline_version: VersionString
    dataset_id: Identifier
    local_timezone: IanaTimezone
    device_model: Annotated[str, Field(min_length=1, max_length=64)]
    source_kind: SourceKind
    availability: Availability
    min_coverage: dict[Metric, MinCoverage]
    aggregations: dict[Metric, Annotated[list[Aggregation], Field(min_length=1)]]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if set(self.min_coverage) != set(RESOLUTIONS):
            raise ValueError(f"min_coverage must name exactly {sorted(RESOLUTIONS)}")
        for metric, rule in self.min_coverage.items():
            given = {r for r in ("hour", "day") if getattr(rule, r) is not None}
            if given != set(RESOLUTIONS[metric]):
                raise ValueError(f"{metric}: min_coverage needs exactly {RESOLUTIONS[metric]}")
        for metric, aggregations in self.aggregations.items():
            if metric not in RESOLUTIONS:
                raise ValueError(f"{metric} is not produced from PMData")
            if len(set(aggregations)) != len(aggregations):
                raise ValueError(f"{metric}: duplicate aggregations")
            if not set(aggregations) <= METRICS[metric].aggregations:
                raise ValueError(f"{metric} cannot be aggregated with {aggregations}")
        return self

    def aggregations_for(self, metric: Metric) -> tuple[Aggregation, ...]:
        """Level metrics take the configured aggregations; amounts and durations are summed."""
        if METRICS[metric].kind != "level":
            return ("sum",)
        if metric not in self.aggregations:
            raise ValueError(f"{metric}: level metrics need configured aggregations")
        return tuple(self.aggregations[metric])


@dataclass(frozen=True)
class LoadedConfig:
    config: PipelineConfig
    sha256: str
    text: str


def load_config(path: Path = CONFIG_PATH) -> LoadedConfig:
    raw = path.read_bytes()
    config = PipelineConfig.model_validate(tomllib.loads(raw.decode("utf-8")))
    return LoadedConfig(config, hashlib.sha256(raw).hexdigest(), raw.decode("utf-8"))


class Admission(Contract):
    """The admitted archive, as recorded by the dataset registry (#2)."""

    dataset_id: Identifier
    dataset_version: VersionString
    archive_name: Annotated[str, Field(pattern=r"^[^/\\]{1,255}$")]
    archive_bytes: Annotated[int, Field(gt=0)]
    archive_sha256: Sha256


def registry_admission(dataset_id: str = "pmdata") -> Admission:
    """Read the admitted PMData archive from the dataset registry."""
    from hachi.data.registry import load_registry

    source = load_registry()[dataset_id]
    if source.status not in {"downloaded", "validated"} or source.version is None:
        raise ValueError(f"{dataset_id} is not admitted with a held, versioned archive")
    if len(source.files) != 1:
        raise ValueError(f"{dataset_id}: expected exactly one registered archive")
    archive = source.files[0]
    return Admission(
        dataset_id=source.dataset_id,
        dataset_version=source.version,
        archive_name=archive.name,
        archive_bytes=archive.bytes,
        archive_sha256=archive.sha256,
    )
