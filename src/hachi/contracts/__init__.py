"""Canonical, versioned contracts shared by ingestion, models, the API and the web app.

The Pydantic models here are the single source of truth. `contracts/schema/hachi.schema.json`
and the TypeScript types in `contracts/typescript/` are generated from them.
"""

from .api import ApiError, Coverage, HealthStatus, ImportStatus, ReportJob
from .base import SCHEMA_VERSION, ArtifactRef, DatasetSnapshotRef, local_day_bounds
from .causality import available_by, label_known_by, observations_available_by
from .manifests import RunManifest, SplitManifest
from .metrics import METRICS, MetricSpec
from .requests import ReportRequest, ScenarioRequest, SelfReportRequest
from .results import ReportResult
from .tables import Aggregate, Observation, Outcome, StatusUnknown, SymptomEpisode, TestResult

__all__ = [
    "METRICS",
    "SCHEMA_VERSION",
    "Aggregate",
    "ApiError",
    "ArtifactRef",
    "Coverage",
    "DatasetSnapshotRef",
    "HealthStatus",
    "ImportStatus",
    "MetricSpec",
    "Observation",
    "Outcome",
    "ReportJob",
    "ReportRequest",
    "ReportResult",
    "RunManifest",
    "ScenarioRequest",
    "SelfReportRequest",
    "SplitManifest",
    "StatusUnknown",
    "SymptomEpisode",
    "TestResult",
    "available_by",
    "label_known_by",
    "local_day_bounds",
    "observations_available_by",
]
