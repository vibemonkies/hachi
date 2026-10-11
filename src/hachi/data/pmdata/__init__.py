"""PMData ingestion: admitted archive to canonical, reproducible feature snapshots (#5)."""

from .config import Admission, PipelineConfig, load_config, registry_admission
from .snapshot import (
    AGGREGATE_AVAILABILITY_RULE,
    FeatureBin,
    build,
    dataset_snapshot_ref,
    iter_aggregates,
    iter_observations,
    load_manifest,
    read_outcomes,
    read_wellness,
    verify,
)
from .wellness import SCALES, WellnessDay

__all__ = [
    "AGGREGATE_AVAILABILITY_RULE",
    "SCALES",
    "Admission",
    "FeatureBin",
    "PipelineConfig",
    "WellnessDay",
    "build",
    "dataset_snapshot_ref",
    "iter_aggregates",
    "iter_observations",
    "load_config",
    "load_manifest",
    "read_outcomes",
    "read_wellness",
    "registry_admission",
    "verify",
]
