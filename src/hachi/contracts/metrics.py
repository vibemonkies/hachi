"""Canonical metric identities and units.

Each metric has exactly one canonical unit. Ingestion converts known units and quarantines
unknown ones; canonical tables never hold a unit other than the one registered here.
Bounds are integrity limits that catch impossible values, not plausibility filters.
"""

from dataclasses import dataclass
from typing import Literal

type Metric = Literal[
    "heart_rate",
    "resting_heart_rate_vendor",
    "hrv_sdnn",
    "hrv_rmssd",
    "respiratory_rate",
    "oxygen_saturation",
    "wrist_temperature_deviation",
    "body_temperature",
    "steps",
    "active_energy",
    "walking_running_distance",
    "sleep_in_bed",
    "sleep_asleep_unspecified",
    "sleep_asleep_core",
    "sleep_asleep_deep",
    "sleep_asleep_rem",
    "sleep_awake",
]

type Unit = Literal["bpm", "ms", "breaths_per_min", "percent", "degC", "count", "kcal", "m", "s"]

type Aggregation = Literal["mean", "median", "min", "max", "sum"]

# level: a sampled state, summarised by central tendency or extremes.
# amount: a quantity accrued over the interval, summed.
# duration: seconds spent in a state within the interval, summed; never exceeds the interval.
type ValueKind = Literal["level", "amount", "duration"]


@dataclass(frozen=True)
class MetricSpec:
    unit: Unit
    kind: ValueKind
    minimum: float | None
    maximum: float | None
    description: str

    @property
    def aggregations(self) -> frozenset[Aggregation]:
        if self.kind == "level":
            return frozenset({"mean", "median", "min", "max"})
        return frozenset({"sum"})


METRICS: dict[Metric, MetricSpec] = {
    "heart_rate": MetricSpec("bpm", "level", 1, 300, "Heart rate sample"),
    "resting_heart_rate_vendor": MetricSpec(
        "bpm", "level", 1, 250, "Vendor-reported daily resting HR; not an overnight estimate"
    ),
    "hrv_sdnn": MetricSpec("ms", "level", 0, 1000, "HRV as SDNN (Apple); not RMSSD"),
    "hrv_rmssd": MetricSpec("ms", "level", 0, 1000, "HRV as RMSSD; not SDNN"),
    "respiratory_rate": MetricSpec("breaths_per_min", "level", 1, 100, "Respiratory rate"),
    "oxygen_saturation": MetricSpec("percent", "level", 0, 100, "SpO2 as a percentage"),
    "wrist_temperature_deviation": MetricSpec(
        "degC", "level", -10, 10, "Sleeping wrist temperature deviation; not core temperature"
    ),
    "body_temperature": MetricSpec("degC", "level", 25, 45, "Measured body temperature"),
    "steps": MetricSpec("count", "amount", 0, None, "Step count over the interval"),
    "active_energy": MetricSpec("kcal", "amount", 0, None, "Active energy over the interval"),
    "walking_running_distance": MetricSpec("m", "amount", 0, None, "Walking/running distance"),
    "sleep_in_bed": MetricSpec("s", "duration", 0, None, "Time in bed"),
    "sleep_asleep_unspecified": MetricSpec(
        "s", "duration", 0, None, "Asleep without stage detail (summary sleep)"
    ),
    "sleep_asleep_core": MetricSpec("s", "duration", 0, None, "Staged sleep: core/light"),
    "sleep_asleep_deep": MetricSpec("s", "duration", 0, None, "Staged sleep: deep"),
    "sleep_asleep_rem": MetricSpec("s", "duration", 0, None, "Staged sleep: REM"),
    "sleep_awake": MetricSpec("s", "duration", 0, None, "Awake within a sleep session"),
}

# Tolerance for rounding when a duration value is compared with its interval length.
DURATION_TOLERANCE_SECONDS = 1.0


def check_metric_value(
    metric: Metric, unit: Unit, value: float, interval_seconds: float, label: str
) -> None:
    """Reject a value whose unit, bounds or duration is impossible for its metric."""
    spec = METRICS[metric]
    if unit != spec.unit:
        raise ValueError(f"{label}: {metric} must use canonical unit '{spec.unit}', not '{unit}'")
    if spec.kind == "level":
        if spec.minimum is not None and value < spec.minimum:
            raise ValueError(f"{label}: {metric} value {value} is below {spec.minimum}")
        if spec.maximum is not None and value > spec.maximum:
            raise ValueError(f"{label}: {metric} value {value} is above {spec.maximum}")
    elif value < 0:
        raise ValueError(f"{label}: {metric} cannot be negative")
    if spec.kind == "duration" and value > interval_seconds + DURATION_TOLERANCE_SECONDS:
        raise ValueError(f"{label}: {metric} duration exceeds its interval")
