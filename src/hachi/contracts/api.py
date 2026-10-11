"""Responses for imports, coverage, report jobs, errors and health."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import (
    ArtifactRef,
    Contract,
    DataMode,
    DatasetSnapshotRef,
    GitSha,
    IanaTimezone,
    Identifier,
    SchemaVersion,
    SubjectId,
    TaskName,
    Text,
    UtcDatetime,
    require_ordered,
    require_unique,
)
from .metrics import Metric, Unit
from .requests import ReportRequest
from .results import ReportResult, UnavailableReason
from .tables import SourceKind

# --- Imports -------------------------------------------------------------------------------

type ImportErrorCode = Literal[
    "FILE_TOO_LARGE",
    "ARCHIVE_UNSAFE",
    "MALFORMED_XML",
    "NOT_AN_APPLE_HEALTH_EXPORT",
    "UNSUPPORTED_FORMAT",
    "INTERNAL_ERROR",
]

type RecordIssueCode = Literal[
    "UNKNOWN_UNIT",
    "INVALID_TIMESTAMP",
    "END_BEFORE_START",
    "VALUE_OUT_OF_RANGE",
    "MISSING_FIELD",
]


class ImportCounts(Contract):
    """Every record seen lands in exactly one bucket."""

    records_seen: Annotated[int, Field(ge=0)]
    records_accepted: Annotated[int, Field(ge=0)]
    records_duplicate: Annotated[int, Field(ge=0)]
    records_unsupported: Annotated[int, Field(ge=0)] = Field(
        description="Valid records of a type Hachi does not use."
    )
    records_rejected: Annotated[int, Field(ge=0)]
    records_quarantined: Annotated[int, Field(ge=0)] = Field(
        description="Records held back instead of guessed, e.g. an unknown unit."
    )

    def bucket_total(self) -> int:
        return (
            self.records_accepted
            + self.records_duplicate
            + self.records_unsupported
            + self.records_rejected
            + self.records_quarantined
        )


class RecordIssueSummary(Contract):
    """Aggregate count per issue. Raw records never appear in API responses."""

    disposition: Literal["rejected", "quarantined"]
    code: RecordIssueCode
    count: Annotated[int, Field(ge=1)]


class ImportFailure(Contract):
    error_code: ImportErrorCode
    message: Text
    action: Text = Field(description="What the person can do next.")


class ImportStatus(Contract):
    """GET /v1/imports/{id} response."""

    schema_version: SchemaVersion
    import_id: Identifier
    subject_id: SubjectId
    data_mode: DataMode
    source_format: Literal[
        "apple_health_export_zip", "apple_health_export_xml", "pmdata_archive", "synthetic"
    ]
    declared_tz_name: IanaTimezone
    state: Literal["pending", "running", "succeeded", "failed"]
    created_at_utc: UtcDatetime
    updated_at_utc: UtcDatetime
    counts: ImportCounts | None
    record_issues: list[RecordIssueSummary]
    failure: ImportFailure | None

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(self.created_at_utc, self.updated_at_utc, "import", allow_equal=True)
        if (self.state == "failed") != (self.failure is not None):
            raise ValueError("failure is present exactly when the import failed")
        if self.state == "pending" and (self.counts is not None or self.record_issues):
            raise ValueError("a pending import has no counts yet")
        if self.state == "succeeded":
            if self.counts is None:
                raise ValueError("a succeeded import reports its counts")
            if self.counts.bucket_total() != self.counts.records_seen:
                raise ValueError("record buckets must add up to records_seen")
        if self.counts is not None:
            for disposition, total in (
                ("rejected", self.counts.records_rejected),
                ("quarantined", self.counts.records_quarantined),
            ):
                issues = sum(i.count for i in self.record_issues if i.disposition == disposition)
                if issues > total:
                    raise ValueError(f"{disposition} issue counts exceed records_{disposition}")
        require_unique([(i.disposition, i.code) for i in self.record_issues], "record issues")
        return self


# --- Coverage ------------------------------------------------------------------------------


class MetricCoverage(Contract):
    metric: Metric
    unit: Unit
    first_utc: UtcDatetime
    last_utc: UtcDatetime
    days_with_data: Annotated[int, Field(ge=1)]
    coverage: Annotated[float, Field(ge=0.0, le=1.0)] = Field(
        description="Fraction of the subject's span with usable observations of this metric."
    )
    longest_gap_hours: Annotated[float, Field(ge=0)]
    source_kinds: Annotated[list[SourceKind], Field(min_length=1)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(self.first_utc, self.last_utc, "metric coverage", allow_equal=True)
        require_unique(self.source_kinds, "source_kinds")
        return self


class TaskSupport(Contract):
    task: TaskName
    supported: bool
    reason_code: UnavailableReason | None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.supported == (self.reason_code is not None):
            raise ValueError("an unsupported task needs a reason_code, a supported one none")
        return self


class Coverage(Contract):
    """GET /v1/subjects/{id}/coverage response: what data exists and what it can support."""

    schema_version: SchemaVersion
    subject_id: SubjectId
    data_mode: DataMode
    generated_at_utc: UtcDatetime
    dataset_snapshot: DatasetSnapshotRef | None
    history: Literal["empty", "insufficient", "sufficient"]
    span_start_utc: UtcDatetime | None
    span_end_utc: UtcDatetime | None
    metrics: list[MetricCoverage]
    task_support: list[TaskSupport]

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_unique([m.metric for m in self.metrics], "metrics")
        require_unique([t.task for t in self.task_support], "task_support")
        if self.history == "empty":
            if self.metrics or self.span_start_utc or self.span_end_utc:
                raise ValueError("empty history has no span and no metrics")
            return self
        if self.span_start_utc is None or self.span_end_utc is None or not self.metrics:
            raise ValueError("non-empty history requires a span and metrics")
        require_ordered(self.span_start_utc, self.span_end_utc, "span", allow_equal=True)
        for m in self.metrics:
            if m.first_utc < self.span_start_utc or m.last_utc > self.span_end_utc:
                raise ValueError(f"{m.metric} coverage lies outside the subject span")
        return self


# --- Report jobs ---------------------------------------------------------------------------


class ReportJob(Contract):
    """POST /v1/reports and GET /v1/reports/{id} response. Poll until state is completed."""

    schema_version: SchemaVersion
    report_id: Identifier
    state: Literal["queued", "running", "completed"]
    submitted_at_utc: UtcDatetime
    updated_at_utc: UtcDatetime
    request: ReportRequest
    result: ReportResult | None

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(self.submitted_at_utc, self.updated_at_utc, "report job", allow_equal=True)
        if (self.state == "completed") != (self.result is not None):
            raise ValueError("result is present exactly when the job completed")
        request, result = self.request.root, self.result.root if self.result else None
        if result is not None:
            if result.report_id != self.report_id:
                raise ValueError("result report_id must match the job")
            if (result.subject_id, result.as_of, result.task) != (
                request.subject_id,
                request.as_of,
                request.task,
            ):
                raise ValueError("result must answer the request's subject, as_of and task")
        return self


# --- Errors and health ---------------------------------------------------------------------

type ApiErrorCode = Literal[
    "VALIDATION_FAILED",
    "SCHEMA_VERSION_UNSUPPORTED",
    "NOT_FOUND",
    "CONFLICT",
    "PAYLOAD_TOO_LARGE",
    "INTERNAL_ERROR",
]


class FieldIssue(Contract):
    path: Annotated[str, Field(min_length=1, max_length=200)]
    message: Text


class ApiError(Contract):
    """Body of every non-2xx API response."""

    schema_version: SchemaVersion
    error_code: ApiErrorCode
    message: Text
    request_id: Identifier
    field_issues: list[FieldIssue]


class HealthStatus(Contract):
    """GET /healthz response. Contains no participant data."""

    schema_version: SchemaVersion
    status: Literal["ok", "degraded"]
    git_sha: GitSha
    artifacts: list[ArtifactRef]
