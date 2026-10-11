"""The report result envelope: `ok` with exactly one task payload, `unavailable`, or `error`.

Missing evidence is `unavailable` with a reason, never a probability of zero. Every result
names the code that produced it; `ok` results also name their data snapshot and artifact.
"""

from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal, Self

from pydantic import Discriminator, Field, RootModel, Tag, model_validator

from .base import (
    ArtifactRef,
    Contract,
    DataMode,
    DatasetSnapshotRef,
    GitSha,
    IanaTimezone,
    Identifier,
    Probability,
    SchemaVersion,
    SubjectId,
    TaskName,
    Text,
    UtcDatetime,
    VersionString,
    local_day_bounds,
    require_ordered,
    require_unique,
)
from .metrics import METRICS, Metric, Unit, check_metric_value
from .requests import ScenarioAssumptions
from .tables import Resolution

type UnavailableReason = Literal[
    "NO_VALIDATED_ILLNESS_ARTIFACT",
    "NO_VALIDATED_RECOVERY_ARTIFACT",
    "NO_ARTIFACT_FOR_TASK",
    "INSUFFICIENT_HISTORY",
    "NO_SUPPORTED_METRICS",
    "METRIC_NOT_OBSERVED",
    "LOW_COVERAGE",
    "ONGOING_EPISODE",
    "NO_ONGOING_EPISODE",
    "LABELS_UNAVAILABLE",
    "DATA_ACCESS_PENDING",
]

type ReportErrorCode = Literal[
    "ARTIFACT_INTEGRITY_FAILED",
    "ARTIFACT_INCOMPATIBLE",
    "DATA_READ_FAILED",
    "INFERENCE_FAILED",
    "INFERENCE_TIMEOUT",
    "GPU_UNAVAILABLE",
    "INTERNAL_ERROR",
]

type WarningCode = Literal[
    "LOW_COVERAGE",
    "SPARSE_HISTORY",
    "UNCALIBRATED_INTERVALS",
    "DEVICE_SHIFT",
    "OUT_OF_DISTRIBUTION",
    "STALE_DATA",
]


class ResultWarning(Contract):
    code: WarningCode
    message: Text


class ReplayInfo(Contract):
    """Present when a saved result is shown instead of a live run."""

    source_report_id: Identifier
    recorded_at_utc: UtcDatetime


class FeatureCoverage(Contract):
    metric: Metric
    coverage: Annotated[float, Field(ge=0.0, le=1.0)] = Field(
        description="Fraction of the lookback window with usable observations."
    )


class Provenance(Contract):
    dataset_snapshot: DatasetSnapshotRef | None = Field(
        description="Required for every task except an alertness simulation."
    )
    artifact: ArtifactRef
    feature_coverage: list[FeatureCoverage]


class PartialProvenance(Contract):
    """Whatever was resolved before a result became unavailable or failed."""

    dataset_snapshot: DatasetSnapshotRef | None
    artifact: ArtifactRef | None
    feature_coverage: list[FeatureCoverage]


class _ResultBase(Contract):
    schema_version: SchemaVersion
    report_id: Identifier
    subject_id: SubjectId
    as_of: UtcDatetime
    data_mode: DataMode
    generated_at_utc: UtcDatetime
    git_sha: GitSha
    warnings: list[ResultWarning]
    replay: ReplayInfo | None


class _OkBase(_ResultBase):
    status: Literal["ok"]
    provenance: Provenance

    def _require_dataset(self) -> None:
        if self.provenance.dataset_snapshot is None:
            raise ValueError("this result must name its dataset snapshot")


def _require_causal_past(end: datetime, as_of: datetime, label: str) -> None:
    if end > as_of:
        raise ValueError(f"{label} must end at or before as_of")


# --- Physiology forecast -------------------------------------------------------------------


class ForecastPoint(Contract):
    interval_start_utc: UtcDatetime
    interval_end_utc: UtcDatetime
    local_date: date | None = Field(description="Local day for day-resolution points.")
    median: float
    lower: float | None = Field(description="Null exactly for a point-only forecast.")
    upper: float | None = Field(description="Null exactly for a point-only forecast.")

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(
            self.interval_start_utc, self.interval_end_utc, "forecast point", allow_equal=False
        )
        if (self.lower is None) != (self.upper is None):
            raise ValueError("a forecast point gives both interval bounds or neither")
        if (
            self.lower is not None
            and self.upper is not None
            and not self.lower <= self.median <= self.upper
        ):
            raise ValueError("forecast interval must satisfy lower <= median <= upper")
        return self


class PersonalBaseline(Contract):
    value: float
    definition: Text
    window_start_utc: UtcDatetime
    window_end_utc: UtcDatetime


class ForecastSeries(Contract):
    """A forecast with intervals, or a point-only forecast (`interval_calibration: "none"`).

    A point-only series has no interval and makes no coverage claim: every point's `lower` and
    `upper` and the series' `nominal_coverage` are null. Draw it as points, never as a band.
    """

    metric: Metric
    unit: Unit
    nominal_coverage: Annotated[float, Field(gt=0.0, lt=1.0)] | None = Field(
        description="Intended probability that the outcome falls in [lower, upper]. "
        "Null exactly for a point-only forecast."
    )
    interval_calibration: Literal["validated", "uncalibrated", "none"] = Field(
        description="'validated' only when held-out coverage was measured for this artifact; "
        "'none' for a point-only forecast, which has no interval."
    )
    baseline: PersonalBaseline | None
    points: Annotated[list[ForecastPoint], Field(min_length=1)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        point_only = self.interval_calibration == "none"
        if point_only != (self.nominal_coverage is None):
            raise ValueError("nominal_coverage is null exactly for a point-only forecast")
        if any((p.lower is None) != point_only for p in self.points):
            raise ValueError("points carry lower and upper exactly when the forecast has intervals")
        for p in self.points:
            seconds = (p.interval_end_utc - p.interval_start_utc).total_seconds()
            for value in (p.lower, p.median, p.upper):
                if value is not None:
                    check_metric_value(self.metric, self.unit, value, seconds, "forecast")
        for a, b in zip(self.points, self.points[1:], strict=False):
            if b.interval_start_utc != a.interval_end_utc:
                raise ValueError("forecast points must be ordered and contiguous")
        return self


class MetricUnavailable(Contract):
    metric: Metric
    reason_code: UnavailableReason


class ForecastPayload(Contract):
    resolution: Resolution
    tz_name: IanaTimezone | None = Field(description="Required for day resolution.")
    series: Annotated[list[ForecastSeries], Field(min_length=1)]
    unavailable_metrics: list[MetricUnavailable]

    @model_validator(mode="after")
    def _check(self) -> Self:
        forecast = [s.metric for s in self.series]
        require_unique(forecast + [m.metric for m in self.unavailable_metrics], "metrics")
        if self.resolution == "day" and self.tz_name is None:
            raise ValueError("day forecasts require tz_name")
        for series in self.series:
            for p in series.points:
                if self.resolution == "hour":
                    if p.interval_end_utc - p.interval_start_utc != timedelta(hours=1):
                        raise ValueError("hourly forecast points span exactly one hour")
                    if p.local_date is not None:
                        raise ValueError("hourly forecast points do not carry local_date")
                elif p.local_date is None or (
                    p.interval_start_utc,
                    p.interval_end_utc,
                ) != local_day_bounds(p.local_date, self.tz_name):  # type: ignore[arg-type]
                    raise ValueError("daily forecast points span one local day in tz_name")
        return self


class PhysiologyForecastResult(_OkBase):
    task: Literal["physiology_forecast"]
    forecast: ForecastPayload

    @model_validator(mode="after")
    def _check(self) -> Self:
        self._require_dataset()
        for series in self.forecast.series:
            if series.points[0].interval_start_utc < self.as_of:
                raise ValueError("forecast points must start at or after as_of")
            if self.forecast.resolution == "hour" and len(series.points) > 24:
                raise ValueError("hourly forecasts cover at most 24 bins")
            if self.forecast.resolution == "day" and len(series.points) != 1:
                raise ValueError("daily forecasts cover exactly the next local day")
            if series.baseline is not None:
                _require_causal_past(series.baseline.window_end_utc, self.as_of, "baseline window")
        return self


# --- Anomaly -------------------------------------------------------------------------------


class AnomalyTimelinePoint(Contract):
    interval_start_utc: UtcDatetime
    interval_end_utc: UtcDatetime
    score: float | None = Field(description="Null when the detector abstained.")
    alert: bool

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(
            self.interval_start_utc, self.interval_end_utc, "timeline point", allow_equal=False
        )
        if self.score is None and self.alert:
            raise ValueError("an abstained point cannot alert")
        return self


class ChangedFeature(Contract):
    metric: Metric
    unit: Unit
    observed: float
    baseline_median: float
    robust_z: float


class AlertBurden(Contract):
    false_alert_episodes_per_30_healthy_days: Annotated[float, Field(ge=0)]
    evaluation_report: Text


class AnomalyPayload(Contract):
    """Deviation from the person's own baseline. This is not an illness probability."""

    score_definition: Text = Field(description="What the score measures; higher is more unusual.")
    alert_state: Literal["no_alert", "alert", "abstained"]
    score: float | None
    alert_threshold: float
    baseline_window_start_utc: UtcDatetime
    baseline_window_end_utc: UtcDatetime
    changed_features: list[ChangedFeature]
    timeline: list[AnomalyTimelinePoint]
    observed_alert_burden: AlertBurden | None = Field(description="Null until measured.")

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(
            self.baseline_window_start_utc,
            self.baseline_window_end_utc,
            "baseline window",
            allow_equal=False,
        )
        if (self.alert_state == "abstained") != (self.score is None):
            raise ValueError("score is null exactly when the detector abstained")
        if self.score is not None and (self.score >= self.alert_threshold) != (
            self.alert_state == "alert"
        ):
            raise ValueError("alert_state must agree with score and alert_threshold")
        for a, b in zip(self.timeline, self.timeline[1:], strict=False):
            if b.interval_start_utc < a.interval_end_utc:
                raise ValueError("timeline points must be ordered and non-overlapping")
        for f in self.changed_features:
            if f.unit != METRICS[f.metric].unit:
                raise ValueError(f"{f.metric} must use unit '{METRICS[f.metric].unit}'")
        return self


class AnomalyResult(_OkBase):
    task: Literal["anomaly"]
    anomaly: AnomalyPayload

    @model_validator(mode="after")
    def _check(self) -> Self:
        self._require_dataset()
        _require_causal_past(self.anomaly.baseline_window_end_utc, self.as_of, "baseline window")
        if self.anomaly.timeline:
            _require_causal_past(
                self.anomaly.timeline[-1].interval_end_utc, self.as_of, "anomaly timeline"
            )
        return self


# --- Illness onset -------------------------------------------------------------------------


class CalibrationRef(Contract):
    cohort: Text
    version: VersionString
    method: Text


class IllnessOnsetPayload(Contract):
    horizon_hours: Literal[24, 48, 72]
    onset_probability: Probability = Field(
        description="Probability of a new symptom onset within the horizon after as_of."
    )
    target_definition: Text
    calibration: CalibrationRef
    distribution_status: Literal["in_distribution", "out_of_distribution", "unknown"]


class IllnessOnsetResult(_OkBase):
    task: Literal["illness_onset"]
    illness_onset: IllnessOnsetPayload

    @model_validator(mode="after")
    def _check(self) -> Self:
        self._require_dataset()
        return self


# --- Recovery ------------------------------------------------------------------------------


class SurvivalPoint(Contract):
    days_after_as_of: Annotated[float, Field(ge=0)]
    probability_still_symptomatic: Probability


class RecoveryPayload(Contract):
    episode_id: Identifier
    endpoint_definition: Text
    survival: Annotated[list[SurvivalPoint], Field(min_length=2)]
    median_days_after_as_of: Annotated[float, Field(ge=0)] | None = Field(
        description="Null when the median is not reached within supported follow-up."
    )
    supported_follow_up_days: Annotated[float, Field(gt=0)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.survival[0].days_after_as_of != 0:
            raise ValueError("the survival curve starts at day 0")
        for a, b in zip(self.survival, self.survival[1:], strict=False):
            if b.days_after_as_of <= a.days_after_as_of:
                raise ValueError("survival days must strictly increase")
            if b.probability_still_symptomatic > a.probability_still_symptomatic:
                raise ValueError("survival probability cannot increase")
        if self.survival[-1].days_after_as_of > self.supported_follow_up_days:
            raise ValueError("the survival curve cannot extend past supported follow-up")
        if (
            self.median_days_after_as_of is not None
            and self.median_days_after_as_of > self.supported_follow_up_days
        ):
            raise ValueError("the median cannot lie past supported follow-up")
        return self


class RecoveryResult(_OkBase):
    task: Literal["recovery"]
    recovery: RecoveryPayload

    @model_validator(mode="after")
    def _check(self) -> Self:
        self._require_dataset()
        return self


# --- Alertness -----------------------------------------------------------------------------


class AlertnessScale(Contract):
    name: Text
    unit: Text
    minimum: float
    maximum: float
    higher_is_more_alert: bool

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.maximum <= self.minimum:
            raise ValueError("scale maximum must exceed minimum")
        return self


class AlertnessPoint(Contract):
    time_utc: UtcDatetime
    value: float


class AlertnessCurve(Contract):
    schedule_id: Identifier
    points: Annotated[list[AlertnessPoint], Field(min_length=2)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        for a, b in zip(self.points, self.points[1:], strict=False):
            if b.time_utc <= a.time_utc:
                raise ValueError("curve times must strictly increase")
        return self


class AlertnessValidation(Contract):
    report: Text = Field(description="Aggregate evaluation report backing the prediction.")
    metric: Text
    value: float
    n_observations: Annotated[int, Field(ge=1)]


class AlertnessPayload(Contract):
    """A simulation shows assumptions, never an accuracy claim."""

    mode: Literal["simulation", "validated_prediction"]
    model_description: Text = Field(description="Equations or implementation, with citation.")
    scale: AlertnessScale
    tz_name: IanaTimezone
    assumptions: ScenarioAssumptions
    curves: Annotated[list[AlertnessCurve], Field(min_length=1)]
    validation: AlertnessValidation | None = Field(
        description="Required for validated_prediction; must be null for a simulation."
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        if (self.mode == "validated_prediction") != (self.validation is not None):
            raise ValueError("validation is present exactly for validated_prediction")
        require_unique([c.schedule_id for c in self.curves], "curve schedule ids")
        for curve in self.curves:
            for p in curve.points:
                if not self.scale.minimum <= p.value <= self.scale.maximum:
                    raise ValueError("alertness values must lie within the scale")
        return self


class AlertnessResult(_OkBase):
    task: Literal["alertness"]
    alertness: AlertnessPayload

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.alertness.mode != "simulation":
            self._require_dataset()
        return self


# --- Unavailable and error -----------------------------------------------------------------


class UnavailableResult(_ResultBase):
    status: Literal["unavailable"]
    task: TaskName
    reason_code: UnavailableReason
    requirements: Annotated[list[Text], Field(min_length=1)] = Field(
        description="What would have to exist for this result to become available."
    )
    provenance: PartialProvenance | None


class ErrorResult(_ResultBase):
    status: Literal["error"]
    task: TaskName
    error_code: ReportErrorCode
    message: Text = Field(description="Safe to show; contains no participant data.")


def _result_tag(value: Any) -> str | None:
    get = value.get if isinstance(value, dict) else lambda k: getattr(value, k, None)
    status = get("status")
    return f"ok:{get('task')}" if status == "ok" else status


class ReportResult(
    RootModel[
        Annotated[
            Annotated[PhysiologyForecastResult, Tag("ok:physiology_forecast")]
            | Annotated[AnomalyResult, Tag("ok:anomaly")]
            | Annotated[IllnessOnsetResult, Tag("ok:illness_onset")]
            | Annotated[RecoveryResult, Tag("ok:recovery")]
            | Annotated[AlertnessResult, Tag("ok:alertness")]
            | Annotated[UnavailableResult, Tag("unavailable")]
            | Annotated[ErrorResult, Tag("error")],
            Discriminator(
                _result_tag,
                custom_error_type="unknown_result_variant",
                custom_error_message="Expected status ok (with a known task), unavailable or error",
            ),
        ]
    ]
):
    """A report outcome. Narrow on `status`, then on `task`."""
