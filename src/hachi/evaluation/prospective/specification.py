"""Private preparation records; shared request/result and data contracts remain canonical."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import (
    ArtifactRef,
    Contract,
    DataMode,
    DatasetSnapshotRef,
    GitSha,
    IanaTimezone,
    Sha256,
    UtcDatetime,
    VersionString,
)
from hachi.contracts.metrics import METRICS, Aggregation, Metric
from hachi.contracts.requests import ReportRequest
from hachi.contracts.results import ReportResult
from hachi.contracts.tables import Aggregate


class SystemPins(Contract):
    """References, never permission or an invented #20 scientific freeze."""

    model_version: VersionString
    artifact: ArtifactRef
    git_sha: GitSha
    environment_sha256: Sha256
    config_sha256: Sha256
    preprocessing_sha256: Sha256
    thresholds_sha256: Sha256
    calibration_sha256: Sha256
    selection_receipt_sha256: Sha256


class MetricTarget(Contract):
    metric: Metric
    aggregation: Aggregation

    @model_validator(mode="after")
    def _aggregation(self) -> Self:
        if self.aggregation not in METRICS[self.metric].aggregations:
            raise ValueError("target aggregation must suit its canonical metric")
        return self


class Protocol(Contract):
    format_version: Literal["hachi-prospective-protocol-1"] = "hachi-prospective-protocol-1"
    protocol_version: VersionString
    data_mode: DataMode
    analysis_plan_sha256: Sha256
    system: SystemPins
    tz_name: IanaTimezone
    targets: Annotated[list[MetricTarget], Field(min_length=1)]
    target: Literal["next_completed_local_day"] = "next_completed_local_day"
    successful_task: Literal["physiology_forecast"] = "physiology_forecast"
    max_recording_delay_seconds: Annotated[int, Field(ge=1, le=300)] = 60
    real_study_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _targets(self) -> Self:
        if len({t.metric for t in self.targets}) != len(self.targets):
            raise ValueError("protocol targets must be unique")
        return self


class Prediction(Contract):
    kind: Literal["prediction"] = "prediction"
    request: ReportRequest
    result: ReportResult
    dataset_snapshot: DatasetSnapshotRef
    input_sha256: Sha256
    protocol_sha256: Sha256
    system_sha256: Sha256
    window_start_utc: UtcDatetime
    window_end_utc: UtcDatetime


class FollowUp(Contract):
    kind: Literal["follow_up"] = "follow_up"
    prediction_sha256: Sha256
    data_mode: DataMode
    status: Literal["observed", "missing", "right_censored"]
    recorded_at_utc: UtcDatetime
    observed_through_utc: UtcDatetime
    outcome_snapshot: DatasetSnapshotRef
    outcome_document_sha256: Sha256
    aggregates: list[Aggregate]
    missing_reason: Literal["no_observations", "lost_to_follow_up", "withdrawn", "other"] | None


class Registration(Contract):
    kind: Literal["protocol"] = "protocol"
    protocol: Protocol


class ReceiptBody(Contract):
    format_version: Literal["hachi-prospective-receipt-1"] = "hachi-prospective-receipt-1"
    sequence: Annotated[int, Field(ge=0)]
    previous_sha256: Sha256 | None
    logged_at_utc: UtcDatetime
    payload: Annotated[Registration | Prediction | FollowUp, Field(discriminator="kind")]


class Receipt(Contract):
    body: ReceiptBody
    sha256: Sha256
