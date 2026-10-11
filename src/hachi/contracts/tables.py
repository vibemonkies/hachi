"""Row contracts for the canonical analytical tables.

Rows carry no schema_version of their own; the table's snapshot manifest records it.
"""

from datetime import date, timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, RootModel, model_validator

from .base import (
    Contract,
    IanaTimezone,
    Identifier,
    SubjectId,
    Text,
    UtcDatetime,
    VersionString,
    local_day_bounds,
    require_ordered,
    require_unique,
)
from .metrics import METRICS, Aggregation, Metric, Unit, check_metric_value

type SourceKind = Literal[
    "watch",
    "phone",
    "ring",
    "fitness_tracker",
    "third_party_app",
    "manual_entry",
    "research_device",
    "unknown",
]

type Resolution = Literal["hour", "day"]

type LabelSource = Literal["study_survey", "self_report", "clinician", "derived"]


class Observation(Contract):
    """One source measurement, as recorded, in canonical units.

    `source_id` is a pseudonymous stable id used for deduplication precedence. Raw source
    names (for example "Alex's Apple Watch") can contain personal names and stay out of
    canonical tables.
    """

    dataset_id: Identifier
    subject_id: SubjectId
    record_id: Identifier
    source_kind: SourceKind
    source_id: Identifier
    device_model: Annotated[str, Field(min_length=1, max_length=64)] | None
    metric: Metric
    value: float
    unit: Unit
    start_utc: UtcDatetime
    end_utc: UtcDatetime
    available_at_utc: UtcDatetime = Field(
        description="When the record became available to the system. Features at a cutoff may "
        "only use records whose end and availability are both at or before it."
    )
    availability: Literal["observed", "assumed"] = Field(
        description="'observed' when the source records availability (e.g. Apple creationDate); "
        "'assumed' when a documented rule supplied it."
    )
    availability_rule: Identifier | None = Field(
        description="Id of the documented availability assumption. Required iff assumed."
    )
    tz_name: IanaTimezone | None
    utc_offset_minutes: Annotated[int, Field(ge=-720, le=840)] | None
    tz_provenance: Literal["record_offset", "user_declared", "dataset_documentation", "unknown"]

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(self.start_utc, self.end_utc, "observation", allow_equal=True)
        seconds = (self.end_utc - self.start_utc).total_seconds()
        check_metric_value(self.metric, self.unit, self.value, seconds, "observation")
        if (self.availability == "assumed") != (self.availability_rule is not None):
            raise ValueError("availability_rule is required for assumed availability and only then")
        if self.available_at_utc < self.start_utc:
            raise ValueError("a record cannot become available before it starts")
        has_tz = self.tz_name is not None or self.utc_offset_minutes is not None
        if (self.tz_provenance == "unknown") == has_tz:
            raise ValueError("tz_provenance 'unknown' means no tz_name or offset, and only then")
        return self


class Aggregate(Contract):
    """One metric summarised over an hourly or local-day bin.

    An empty bin is missing (`value` null with a `null_reason`), never zero.
    """

    dataset_id: Identifier
    subject_id: SubjectId
    metric: Metric
    unit: Unit
    resolution: Resolution
    interval_start_utc: UtcDatetime
    interval_end_utc: UtcDatetime
    local_date: date | None = Field(description="Local calendar day. Required for day bins.")
    tz_name: IanaTimezone | None = Field(description="Timezone of local_date. Required for days.")
    aggregation: Aggregation
    value: float | None
    null_reason: Literal["no_observations", "insufficient_coverage", "quarantined"] | None
    observed_count: Annotated[int, Field(ge=0)]
    coverage: Annotated[float, Field(ge=0.0, le=1.0)] = Field(
        description="Fraction of the bin with usable observations."
    )
    source_ids: list[Identifier]
    pipeline_version: VersionString

    @model_validator(mode="after")
    def _check(self) -> Self:
        start, end = self.interval_start_utc, self.interval_end_utc
        require_ordered(start, end, "aggregate", allow_equal=False)
        if self.resolution == "hour":
            if end - start != timedelta(hours=1) or start.second or start.microsecond:
                raise ValueError("hour bins span exactly one hour starting on a whole minute")
            if self.local_date is not None:
                raise ValueError("hour bins do not carry local_date")
        else:
            if self.local_date is None or self.tz_name is None:
                raise ValueError("day bins require local_date and tz_name")
            if (start, end) != local_day_bounds(self.local_date, self.tz_name):
                raise ValueError("day bin must span local midnight to midnight in tz_name")
        spec = METRICS[self.metric]
        if self.aggregation not in spec.aggregations:
            raise ValueError(f"{self.metric} cannot be aggregated with {self.aggregation}")
        if (self.value is None) == (self.null_reason is None):
            raise ValueError("value is null exactly when null_reason is given")
        if self.observed_count == 0:
            if self.null_reason != "no_observations" or self.coverage != 0:
                raise ValueError("an empty bin is missing: no value, no coverage, never zero")
        elif self.null_reason == "no_observations":
            raise ValueError("null_reason 'no_observations' contradicts observed_count")
        if self.value is not None:
            if not self.source_ids:
                raise ValueError("an aggregate value must name the sources it came from")
            seconds = (end - start).total_seconds()
            check_metric_value(self.metric, self.unit, self.value, seconds, "aggregate")
        require_unique(self.source_ids, "source_ids")
        return self


class SymptomEpisode(Contract):
    """A labeled symptom episode. Onset and resolution are intervals expressing uncertainty."""

    kind: Literal["symptom_episode"]
    dataset_id: Identifier
    subject_id: SubjectId
    episode_id: Identifier
    onset_earliest_utc: UtcDatetime
    onset_latest_utc: UtcDatetime
    resolution_status: Literal["resolved", "right_censored"]
    resolution_earliest_utc: UtcDatetime | None
    resolution_latest_utc: UtcDatetime | None
    resolution_definition: Identifier | None = Field(
        description="Id of the prespecified resolution endpoint. Required when resolved."
    )
    last_follow_up_utc: UtcDatetime = Field(
        description="End of observation for this episode; the censoring time if unresolved."
    )
    observed_at_utc: UtcDatetime = Field(description="When the label was recorded.")
    label_source: LabelSource
    confidence: Literal["confirmed", "probable", "uncertain"]

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(self.onset_earliest_utc, self.onset_latest_utc, "onset", allow_equal=True)
        if self.last_follow_up_utc < self.onset_latest_utc:
            raise ValueError("follow-up must extend past onset")
        resolved_fields = (
            self.resolution_earliest_utc,
            self.resolution_latest_utc,
            self.resolution_definition,
        )
        if self.resolution_status == "right_censored":
            if any(v is not None for v in resolved_fields):
                raise ValueError("a censored episode has no resolution interval or definition")
            return self
        if self.resolution_earliest_utc is None or self.resolution_latest_utc is None:
            raise ValueError("a resolved episode requires its resolution interval")
        if self.resolution_definition is None:
            raise ValueError("a resolved episode requires its resolution_definition")
        require_ordered(
            self.resolution_earliest_utc, self.resolution_latest_utc, "resolution", allow_equal=True
        )
        if self.resolution_earliest_utc < self.onset_earliest_utc:
            raise ValueError("resolution cannot precede onset")
        if self.resolution_latest_utc > self.last_follow_up_utc:
            raise ValueError("resolution cannot be later than follow-up")
        return self


class TestResult(Contract):
    """A diagnostic test. A test date is not a symptom onset and is never used as one."""

    __test__ = False  # not a pytest test class

    kind: Literal["test_result"]
    dataset_id: Identifier
    subject_id: SubjectId
    test_id: Identifier
    episode_id: Identifier | None
    pathogen: Literal["sars_cov_2", "influenza", "rsv", "other", "unknown"]
    method: Literal["pcr", "antigen", "other", "unknown"]
    result: Literal["positive", "negative", "inconclusive"]
    collected_earliest_utc: UtcDatetime
    collected_latest_utc: UtcDatetime
    observed_at_utc: UtcDatetime
    label_source: LabelSource

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(
            self.collected_earliest_utc, self.collected_latest_utc, "collection", allow_equal=True
        )
        return self


class StatusUnknown(Contract):
    """An interval without outcome information. Unknown is not healthy."""

    kind: Literal["status_unknown"]
    dataset_id: Identifier
    subject_id: SubjectId
    start_utc: UtcDatetime
    end_utc: UtcDatetime
    reason: Literal["no_survey", "lost_to_follow_up", "withdrawn", "other"]
    note: Text | None

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(self.start_utc, self.end_utc, "status_unknown", allow_equal=False)
        return self


class Outcome(
    RootModel[Annotated[SymptomEpisode | TestResult | StatusUnknown, Field(discriminator="kind")]]
):
    """An outcome-table row: a symptom episode, a test result, or a period of unknown status."""
