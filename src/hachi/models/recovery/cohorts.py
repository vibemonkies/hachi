"""Separate symptom schemas and clocks; cohorts are never joined or rescaled."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Cohort:
    name: Literal["stanford_phase1", "cmu_common_cold"]
    dataset_id: str
    clock: Literal["floating_local_shifted", "relative_to_challenge"]
    scale: str
    features: tuple[str, ...]


STANFORD = Cohort(
    "stanford_phase1",
    "stanford-covid19-wearables",
    "floating_local_shifted",
    "stanford-phase1-daily-survey-10-symptoms-severity-1-to-5",
    ("symptom_count", "max_severity", "severity_sum"),
)
CMU = Cohort(
    "cmu_common_cold",
    "cmu-common-cold-project",
    "relative_to_challenge",
    "cmu-modified-jackson-8-items-baseline-adjusted",
    ("jackson_adjusted",),
)


def cohort_named(name: str) -> Cohort:
    if name == STANFORD.name:
        return STANFORD
    if name == CMU.name:
        return CMU
    raise ValueError("unsupported recovery cohort")
