"""Requests the dashboard sends to the API."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import Discriminator, Field, NaiveDatetime, RootModel, Tag, model_validator

from .base import (
    Contract,
    IanaTimezone,
    Identifier,
    SchemaVersion,
    SubjectId,
    UtcDatetime,
    require_ordered,
    require_unique,
)
from .metrics import Metric

# --- Reports -------------------------------------------------------------------------------


class _ReportRequestBase(Contract):
    schema_version: SchemaVersion
    subject_id: SubjectId
    as_of: UtcDatetime = Field(description="Cutoff. Only data available by this instant is used.")


class _ForecastRequestBase(_ReportRequestBase):
    task: Literal["physiology_forecast"]
    metrics: Annotated[list[Metric], Field(min_length=1)] | None = Field(
        default=None, description="Metrics to forecast; null requests every supported metric."
    )

    @model_validator(mode="after")
    def _check_metrics(self) -> Self:
        if self.metrics is not None:
            require_unique(self.metrics, "metrics")
        return self


class PhysiologyForecastHourlyRequest(_ForecastRequestBase):
    resolution: Literal["hour"]
    horizon_hours: Annotated[int, Field(ge=1, le=24)] = 24


class PhysiologyForecastDailyRequest(_ForecastRequestBase):
    """Forecast the next completed local day after `as_of`."""

    resolution: Literal["day"]
    horizon_days: Literal[1] = 1


class AnomalyRequest(_ReportRequestBase):
    task: Literal["anomaly"]


class IllnessOnsetRequest(_ReportRequestBase):
    task: Literal["illness_onset"]
    horizon_hours: Literal[24, 48, 72]


class RecoveryRequest(_ReportRequestBase):
    task: Literal["recovery"]
    episode_id: Identifier


def _report_request_tag(value: Any) -> str | None:
    get = value.get if isinstance(value, dict) else lambda k: getattr(value, k, None)
    task = get("task")
    return f"{task}:{get('resolution')}" if task == "physiology_forecast" else task


class ReportRequest(
    RootModel[
        Annotated[
            Annotated[PhysiologyForecastHourlyRequest, Tag("physiology_forecast:hour")]
            | Annotated[PhysiologyForecastDailyRequest, Tag("physiology_forecast:day")]
            | Annotated[AnomalyRequest, Tag("anomaly")]
            | Annotated[IllnessOnsetRequest, Tag("illness_onset")]
            | Annotated[RecoveryRequest, Tag("recovery")],
            Discriminator(
                _report_request_tag,
                custom_error_type="unknown_report_task",
                custom_error_message="Unknown task, or physiology_forecast without a resolution",
            ),
        ]
    ]
):
    """POST /v1/reports body. Alertness goes through POST /v1/scenarios instead."""


# --- Sleep scenarios -----------------------------------------------------------------------


def _local_to_utc(local: datetime, zone: ZoneInfo, label: str) -> datetime:
    """Resolve a wall-clock time; ambiguous times use the first occurrence (fold=0)."""
    instant = local.replace(tzinfo=zone).astimezone(UTC)
    if instant.astimezone(zone).replace(tzinfo=None) != local:
        raise ValueError(f"{label} {local.isoformat()} does not exist in {zone.key} (DST gap)")
    return instant


class SleepSchedule(Contract):
    schedule_id: Identifier
    bedtime_local: NaiveDatetime = Field(description="Local wall-clock time, without an offset.")
    wake_time_local: NaiveDatetime = Field(description="Local wall-clock time, without an offset.")


class ScenarioAssumptions(Contract):
    """Explicit inputs the simulation depends on. Nothing is silently defaulted."""

    prior_sleep_hours: Annotated[float, Field(ge=0, le=24)] = Field(
        description="Sleep obtained in the 24 hours before the first scenario bedtime."
    )
    caffeine: Literal["none", "not_modeled"]
    light_exposure: Literal["not_modeled"]


class ScenarioRequest(Contract):
    """POST /v1/scenarios body: compare candidate sleep schedules for one subject."""

    schema_version: SchemaVersion
    subject_id: SubjectId
    tz_name: IanaTimezone
    schedules: Annotated[list[SleepSchedule], Field(min_length=1, max_length=4)]
    assumptions: ScenarioAssumptions

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_unique([s.schedule_id for s in self.schedules], "schedule ids")
        zone = ZoneInfo(self.tz_name)
        for s in self.schedules:
            bed = _local_to_utc(s.bedtime_local, zone, "bedtime")
            wake = _local_to_utc(s.wake_time_local, zone, "wake time")
            if not timedelta(0) < wake - bed <= timedelta(hours=16):
                raise ValueError(f"schedule {s.schedule_id}: wake must follow bedtime within 16 h")
        return self


# --- Self-reports --------------------------------------------------------------------------

type Symptom = Literal[
    "fever",
    "chills",
    "cough",
    "sore_throat",
    "runny_nose",
    "congestion",
    "headache",
    "fatigue",
    "body_aches",
    "shortness_of_breath",
    "loss_of_taste_or_smell",
    "nausea",
    "diarrhea",
    "other",
]

type Severity = Annotated[Literal[1, 2, 3], Field(description="1 mild, 2 moderate, 3 severe.")]


class _Entry(Contract):
    entry_id: Identifier
    entered_at_utc: UtcDatetime = Field(description="When the person recorded this entry.")

    def _require_entered_after(self, event_start: datetime) -> None:
        if self.entered_at_utc < event_start:
            raise ValueError("an entry cannot be recorded before the event it describes")


class SymptomOnsetEntry(_Entry):
    """Symptoms began somewhere in [onset_earliest_utc, onset_latest_utc]."""

    kind: Literal["symptom_onset"]
    onset_earliest_utc: UtcDatetime
    onset_latest_utc: UtcDatetime
    symptoms: Annotated[list[Symptom], Field(min_length=1)]
    severity: Severity

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(self.onset_earliest_utc, self.onset_latest_utc, "onset", allow_equal=True)
        require_unique(self.symptoms, "symptoms")
        self._require_entered_after(self.onset_earliest_utc)
        return self


class SymptomCheckInEntry(_Entry):
    """Status over a period. A check-in records absence too; no check-in means unknown."""

    kind: Literal["symptom_checkin"]
    period_start_utc: UtcDatetime
    period_end_utc: UtcDatetime
    symptoms_present: bool
    symptoms: list[Symptom]
    severity: Severity | None

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(self.period_start_utc, self.period_end_utc, "period", allow_equal=False)
        require_unique(self.symptoms, "symptoms")
        if self.symptoms_present != bool(self.symptoms) or self.symptoms_present != (
            self.severity is not None
        ):
            raise ValueError("symptoms and severity are given exactly when symptoms are present")
        self._require_entered_after(self.period_start_utc)
        return self


class SymptomResolutionEntry(_Entry):
    kind: Literal["symptom_resolution"]
    onset_entry_id: Identifier
    resolved_earliest_utc: UtcDatetime
    resolved_latest_utc: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(
            self.resolved_earliest_utc, self.resolved_latest_utc, "resolution", allow_equal=True
        )
        self._require_entered_after(self.resolved_earliest_utc)
        return self


class TestResultEntry(_Entry):
    __test__ = False  # not a pytest test class

    kind: Literal["test_result"]
    pathogen: Literal["sars_cov_2", "influenza", "rsv", "other", "unknown"]
    method: Literal["pcr", "antigen", "other", "unknown"]
    result: Literal["positive", "negative", "inconclusive"]
    collected_earliest_utc: UtcDatetime
    collected_latest_utc: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(
            self.collected_earliest_utc, self.collected_latest_utc, "collection", allow_equal=True
        )
        self._require_entered_after(self.collected_earliest_utc)
        return self


class AlertnessRatingEntry(_Entry):
    kind: Literal["alertness_rating"]
    rated_at_utc: UtcDatetime
    scale: Literal["kss_1_9"] = Field(
        description="Karolinska Sleepiness Scale: 1 extremely alert, 9 very sleepy."
    )
    value: Annotated[int, Field(ge=1, le=9)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        self._require_entered_after(self.rated_at_utc)
        return self


class PvtResultEntry(_Entry):
    kind: Literal["pvt_result"]
    started_at_utc: UtcDatetime
    duration_seconds: Annotated[int, Field(ge=60, le=900)]
    trials: Annotated[int, Field(ge=1)]
    mean_reaction_time_ms: Annotated[float, Field(gt=0, le=10000)]
    lapses: Annotated[int, Field(ge=0)] = Field(description="Responses slower than 500 ms.")

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.lapses > self.trials:
            raise ValueError("lapses cannot exceed trials")
        self._require_entered_after(self.started_at_utc)
        return self


class ConfounderEntry(_Entry):
    """Something that can move physiology without illness."""

    kind: Literal["confounder"]
    factor: Literal[
        "alcohol", "vaccination", "travel", "intense_exercise", "sleep_loss", "medication", "other"
    ]
    occurred_earliest_utc: UtcDatetime
    occurred_latest_utc: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(
            self.occurred_earliest_utc, self.occurred_latest_utc, "occurrence", allow_equal=True
        )
        self._require_entered_after(self.occurred_earliest_utc)
        return self


type SelfReportEntry = Annotated[
    SymptomOnsetEntry
    | SymptomCheckInEntry
    | SymptomResolutionEntry
    | TestResultEntry
    | AlertnessRatingEntry
    | PvtResultEntry
    | ConfounderEntry,
    Field(discriminator="kind"),
]


class SelfReportRequest(Contract):
    """POST /v1/subjects/{id}/observations body."""

    schema_version: SchemaVersion
    entries: Annotated[list[SelfReportEntry], Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_unique([e.entry_id for e in self.entries], "entry ids")
        return self
