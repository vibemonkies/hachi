"""Report inference: resolve data and a served artifact, apply the cutoff, never invent a result.

A task without a validated artifact, or a subject without the evidence the artifact needs,
gets an `unavailable` result naming what is missing. Failures are `error` results with a
stable code. Only a served artifact's own prediction becomes an `ok` result.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import TypeAdapter

from hachi.contracts.api import TaskSupport
from hachi.contracts.base import SCHEMA_VERSION, DataMode, TaskName
from hachi.contracts.manifests import TimeWindow
from hachi.contracts.metrics import METRICS, Metric
from hachi.contracts.requests import (
    PhysiologyForecastHourlyRequest,
    ReportRequest,
    SelfReportEntry,
    SymptomOnsetEntry,
    SymptomResolutionEntry,
)
from hachi.contracts.results import (
    ErrorResult,
    FeatureCoverage,
    ForecastPayload,
    ForecastPoint,
    ForecastSeries,
    MetricUnavailable,
    PartialProvenance,
    PhysiologyForecastResult,
    Provenance,
    ReportErrorCode,
    ReportResult,
    ResultWarning,
    UnavailableReason,
    UnavailableResult,
    WarningCode,
)
from hachi.evaluation import ForecastEstimate, ForecastInput
from hachi.evaluation.features import HourlyFeaturePolicy
from hachi.evaluation.serialization import document_sha256
from hachi.storage import Metadata, Workspace

from .artifacts import ServedArtifact
from .catalog import Catalog
from .gpu import GpuCleanupFailed, GpuOutputRejected, GpuTimeout, GpuUnavailable
from .sources import SubjectData

log = logging.getLogger("hachi.api")

HOUR = timedelta(hours=1)
ENTRY = TypeAdapter(SelfReportEntry)

REQUIREMENTS: dict[UnavailableReason, str] = {
    "NO_ARTIFACT_FOR_TASK": "A validated, frozen artifact for this task served by this API",
    "NO_VALIDATED_ILLNESS_ARTIFACT": "Labeled cohort evaluation and a calibrated illness artifact",
    "NO_VALIDATED_RECOVERY_ARTIFACT": (
        "Censoring-aware recovery evaluation and a validated recovery artifact"
    ),
    "INSUFFICIENT_HISTORY": "More observed history before as_of for the model's lookback",
    "ONGOING_EPISODE": "Illness onset is only forecast for people without an ongoing episode",
    "NO_ONGOING_EPISODE": "A recorded, unresolved symptom onset with this episode_id",
}


def floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def ceil_hour(moment: datetime) -> datetime:
    floor = floor_hour(moment)
    return floor if floor == moment else floor + HOUR


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def fallback_data_mode(subject_id: str) -> DataMode:
    """For a subject without resolved data: synthetic ids stay labelled synthetic."""
    return "synthetic" if subject_id.startswith("synthetic") else "real"


@dataclass(frozen=True)
class Context:
    catalog: Catalog
    metadata: Metadata
    workspace: Workspace
    git_sha: str


# Self-reports --------------------------------------------------------------------------


@dataclass(frozen=True)
class Version:
    """One stored version of a self-report entry and the id of its chain's original."""

    entry: SelfReportEntry
    root: str


def self_report_versions(metadata: Metadata, subject_id: str) -> list[Version]:
    """Every stored version, in recording order."""
    return [
        Version(ENTRY.validate_json(row.entry_json), row.root)
        for row in metadata.self_reports(subject_id)
    ]


def current_versions(versions: Sequence[Version], as_of: datetime | None = None) -> list[Version]:
    """The latest version of each entry known by `as_of` (all time when None).

    Corrections are entered after what they correct, so the versions known at a cutoff are a
    prefix of each chain: an earlier as_of keeps seeing what was known then. Results follow
    the recording order of each chain's original entry.
    """
    visible = [v for v in versions if as_of is None or v.entry.entered_at_utc <= as_of]
    superseded = {v.entry.supersedes for v in visible if v.entry.supersedes}
    latest = {v.root: v for v in visible if v.entry.entry_id not in superseded}
    first: dict[str, int] = {}
    for index, version in enumerate(versions):
        first.setdefault(version.root, index)
    return sorted(latest.values(), key=lambda v: first[v.root])


def ongoing_episodes(versions: Sequence[Version], as_of: datetime) -> set[str]:
    """Episodes (original onset entry ids) begun by as_of with no resolution known by then."""
    current = current_versions(versions, as_of)
    onsets = {
        v.root
        for v in current
        if isinstance(v.entry, SymptomOnsetEntry) and v.entry.onset_earliest_utc <= as_of
    }
    resolved = {
        v.entry.onset_entry_id
        for v in current
        if isinstance(v.entry, SymptomResolutionEntry) and v.entry.resolved_latest_utc <= as_of
    }
    return onsets - resolved


def self_report_digest(versions: Sequence[Version], as_of: datetime) -> str:
    current = sorted(current_versions(versions, as_of), key=lambda v: v.root)
    return document_sha256([(v.root, v.entry) for v in current])


# Artifact selection --------------------------------------------------------------------


def input_policy(artifact: ServedArtifact, subject: SubjectData) -> HourlyFeaturePolicy | None:
    """The feature policy that feeds this subject to this artifact, if the artifact admits it.

    Dataset snapshots use the artifact's own policy; any other source (an Apple import) only
    through an explicit `accepted_sources` admission in the artifact's serving profile.
    """
    if subject.provides_hourly_features:
        return artifact.serving.feature_policy
    admission = artifact.serving.admission(subject.source)
    return admission.feature_policy if admission else None


def hourly_forecasters(catalog: Catalog) -> list[ServedArtifact]:
    return [
        a
        for a in catalog.artifacts
        if a.serving.task == "physiology_forecast" and a.serving.resolution == "hour"
    ]


def personal(subject: SubjectData | None) -> bool:
    """A real person's own import, as opposed to admitted research data or generated data."""
    return subject is not None and subject.kind == "apple_import" and subject.data_mode == "real"


def forecast_artifacts(catalog: Catalog, subject: SubjectData | None) -> list[ServedArtifact]:
    """Served hourly forecasters whose declared input this subject's data can supply.

    GPU-backed models run on the shared GX10 login, so they serve only research snapshots
    and generated data until a transfer and retention design for personal data is approved.
    """
    return [
        a
        for a in hourly_forecasters(catalog)
        if (a.serving.input == "observations" or (subject and input_policy(a, subject)))
        and not (a.serving.requires_gpu and personal(subject))
    ]


def select_artifact(
    request: ReportRequest, catalog: Catalog, subject: SubjectData | None
) -> ServedArtifact | None:
    body = request.root
    if not isinstance(body, PhysiologyForecastHourlyRequest):
        return None
    wanted = body.metrics
    return next(
        (a for a in forecast_artifacts(catalog, subject) if wanted is None or a.metric in wanted),
        None,
    )


def report_key(
    request: ReportRequest,
    subject: SubjectData | None,
    artifact: ServedArtifact | None,
    git_sha: str,
    entries_digest: str | None,
) -> str:
    """Input hashes plus model, version and task: retries never rerun an identical job."""
    return document_sha256(
        {
            "request": request,
            "dataset_snapshot": subject.snapshot if subject else None,
            "artifact": artifact.ref if artifact else None,
            "git_sha": git_sha,
            "self_reports": entries_digest,
        }
    )


def task_support(
    catalog: Catalog,
    subject: SubjectData | None,
    observed: set[Metric],
    sufficient: bool,
) -> list[TaskSupport]:
    def entry(task: TaskName, reason: UnavailableReason | None) -> TaskSupport:
        return TaskSupport(task=task, supported=reason is None, reason_code=reason)

    candidates = forecast_artifacts(catalog, subject)
    if not candidates:
        forecast: UnavailableReason | None = "NO_ARTIFACT_FOR_TASK"
    elif not any(a.metric in observed for a in candidates):
        forecast = "METRIC_NOT_OBSERVED"
    elif not sufficient:
        forecast = "INSUFFICIENT_HISTORY"
    else:
        forecast = None
    return [
        entry("physiology_forecast", forecast),
        entry("anomaly", "NO_ARTIFACT_FOR_TASK"),
        entry("illness_onset", "NO_VALIDATED_ILLNESS_ARTIFACT"),
        entry("recovery", "NO_VALIDATED_RECOVERY_ARTIFACT"),
        entry("alertness", "NO_ARTIFACT_FOR_TASK"),  # until #15's artifact is served
    ]


# Results -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Base:
    report_id: str
    request: ReportRequest
    data_mode: DataMode
    git_sha: str

    def fields(self, warnings: Sequence[ResultWarning] = ()) -> dict:
        body = self.request.root
        return {
            "schema_version": SCHEMA_VERSION,
            "report_id": self.report_id,
            "subject_id": body.subject_id,
            "as_of": body.as_of,
            "data_mode": self.data_mode,
            "generated_at_utc": now_utc(),
            "git_sha": self.git_sha,
            "warnings": list(warnings),
            "replay": None,
        }

    def unavailable(
        self,
        reason: UnavailableReason,
        requirement: str | None = None,
        provenance: PartialProvenance | None = None,
        warnings: Sequence[ResultWarning] = (),
    ) -> ReportResult:
        return ReportResult(
            UnavailableResult(
                **self.fields(warnings),
                status="unavailable",
                task=self.request.root.task,
                reason_code=reason,
                requirements=[requirement or REQUIREMENTS[reason]],
                provenance=provenance,
            )
        )

    def error(self, code: ReportErrorCode, message: str) -> ReportResult:
        return ReportResult(
            ErrorResult(
                **self.fields(),
                status="error",
                task=self.request.root.task,
                error_code=code,
                message=message,
            )
        )


def _warning(code: WarningCode, message: str) -> ResultWarning:
    return ResultWarning(code=code, message=message)


def run_report(context: Context, report_id: str, request: ReportRequest) -> ReportResult:
    body = request.root
    subject = context.catalog.subject(body.subject_id, context.metadata, context.workspace)
    data_mode = subject.data_mode if subject else fallback_data_mode(body.subject_id)
    base = _Base(report_id, request, data_mode, context.git_sha)
    # Illness and recovery turn on self-reported episodes, which exist without wearable data.
    if subject is None and body.task not in ("illness_onset", "recovery"):
        return base.unavailable(
            "INSUFFICIENT_HISTORY", "A completed import or dataset history for this subject"
        )
    partial = PartialProvenance(
        dataset_snapshot=subject.snapshot if subject else None, artifact=None, feature_coverage=[]
    )
    match body.task:
        case "physiology_forecast":
            assert subject is not None
            return _forecast(context, base, subject, request, partial)
        case "anomaly":
            return base.unavailable(
                "NO_ARTIFACT_FOR_TASK",
                "A frozen anomaly artifact with measured healthy-period alert burden",
                partial,
            )
        case "illness_onset":
            versions = self_report_versions(context.metadata, body.subject_id)
            if ongoing_episodes(versions, body.as_of):
                return base.unavailable("ONGOING_EPISODE", provenance=partial)
            return base.unavailable("NO_VALIDATED_ILLNESS_ARTIFACT", provenance=partial)
        case "recovery":
            versions = self_report_versions(context.metadata, body.subject_id)
            if body.episode_id not in ongoing_episodes(versions, body.as_of):
                return base.unavailable("NO_ONGOING_EPISODE", provenance=partial)
            return base.unavailable("NO_VALIDATED_RECOVERY_ARTIFACT", provenance=partial)
    raise AssertionError("validated report task")


def model_inputs(
    artifact: ServedArtifact, subject: SubjectData, as_of: datetime
) -> tuple[datetime, tuple]:
    """The model's cutoff and history, built exactly as the evaluator builds an origin's input.

    Hourly models use whole-hour cutoffs, so the cutoff is as_of rounded down to the hour:
    nothing after it is read. History is the window of `lookback_hours` before the cutoff.
    """
    cutoff = floor_hour(as_of)
    start = cutoff - artifact.split.lookback_hours * HOUR
    if artifact.serving.input == "hourly_features":
        policy = input_policy(artifact, subject)
        assert policy is not None, "selection admits only sources with a policy"
        rows: list = subject.hourly_features(policy, cutoff, start)
    else:
        rows = subject.observations(artifact.metric, cutoff, start)
    rows.sort(key=lambda o: (o.end_utc, o.available_at_utc, o.record_id))
    return cutoff, tuple(rows)


def forecast_targets(as_of: datetime, horizon_hours: int) -> tuple[TimeWindow, ...]:
    first = ceil_hour(as_of)
    return tuple(
        TimeWindow(start_utc=first + i * HOUR, end_utc=first + (i + 1) * HOUR)
        for i in range(horizon_hours)
    )


def _forecast(
    context: Context,
    base: _Base,
    subject: SubjectData,
    request: ReportRequest,
    partial: PartialProvenance,
) -> ReportResult:
    body = request.root
    if not isinstance(body, PhysiologyForecastHourlyRequest):
        return base.unavailable(
            "NO_ARTIFACT_FOR_TASK", "A frozen daily-resolution forecast artifact", partial
        )
    artifact = select_artifact(request, context.catalog, subject)
    if artifact is None:
        evaluated = sorted(
            {a.run.dataset_snapshot.dataset_id for a in hourly_forecasters(context.catalog)}
        )
        if forecast_artifacts(context.catalog, subject):
            requirement = "A served hourly forecast artifact for the requested metrics"
        elif personal(subject) and any(
            a.serving.requires_gpu and input_policy(a, subject)
            for a in hourly_forecasters(context.catalog)
        ):
            requirement = (
                "An approved transfer and retention design before personal data goes to the "
                "shared GPU; until then GPU models serve research and generated data only"
            )
        elif subject.source == "apple_health" and evaluated:
            requirement = (
                "A forecast artifact whose serving profile admits Apple Health input; the "
                f"served models were evaluated on {', '.join(evaluated)} hourly features only"
            )
        else:
            requirement = "A frozen hourly forecast artifact that accepts this subject's data"
        return base.unavailable("NO_ARTIFACT_FOR_TASK", requirement, partial)
    data_mode: DataMode = (
        subject.data_mode if artifact.evaluation.data_mode == "real" else "synthetic"
    )
    base = _Base(base.report_id, request, data_mode, base.git_sha)
    partial = PartialProvenance(
        dataset_snapshot=subject.snapshot, artifact=artifact.ref, feature_coverage=[]
    )
    if artifact.serving.requires_gpu and context.catalog.gx10 is None:
        return base.error(
            "GPU_UNAVAILABLE",
            "This model needs the GX10 GPU queue, which this API instance does not reach.",
        )
    model = artifact.model
    fit_as_of = getattr(model, "fit_as_of", None)
    if fit_as_of is not None and floor_hour(body.as_of) < fit_as_of:
        return base.error(
            "ARTIFACT_INCOMPATIBLE",
            "The served model was fitted on data later than this as_of; pick a later as_of.",
        )
    try:
        cutoff, history = model_inputs(artifact, subject, body.as_of)
    except (OSError, ValueError) as exc:
        log.warning("report %s: data read failed (%s)", base.report_id, type(exc).__name__)
        return base.error("DATA_READ_FAILED", "The subject's history could not be read.")
    lookback = artifact.split.lookback_hours
    observed_hours = {floor_hour(o.start_utc) for o in history if o.start_utc < cutoff}
    coverage = FeatureCoverage(metric=artifact.metric, coverage=len(observed_hours) / lookback)
    partial = PartialProvenance(
        dataset_snapshot=subject.snapshot, artifact=artifact.ref, feature_coverage=[coverage]
    )
    if len(observed_hours) < artifact.split.min_history_hours:
        return base.unavailable(
            "INSUFFICIENT_HISTORY",
            f"At least {artifact.split.min_history_hours} observed hours of {artifact.metric} "
            f"in the {lookback} hours before the cutoff",
            partial,
        )
    targets = forecast_targets(body.as_of, body.horizon_hours)
    model_input = ForecastInput(
        body.subject_id,
        cutoff,
        targets,
        history if artifact.evaluation.history_policy == "causal_prefix" else (),
    )
    try:
        estimates = tuple(model.predict(model_input))
        if len(estimates) != len(targets):
            raise ValueError("one estimate or abstention per target")
    except GpuUnavailable:
        return base.error(
            "GPU_UNAVAILABLE", "The GX10 GPU could not run this forecast now; try again later."
        )
    except GpuTimeout:
        return base.error("INFERENCE_TIMEOUT", "The GPU forecast did not finish in time.")
    except GpuCleanupFailed as exc:
        log.error("report %s: %s", base.report_id, exc)
        return base.error(
            "INFERENCE_FAILED",
            "The GPU job's files could not be removed from the GX10, so its forecast was not used.",
        )
    except GpuOutputRejected as exc:
        log.warning("report %s: %s", base.report_id, exc)
        return base.error(
            "INFERENCE_FAILED", "The GPU result failed its integrity checks and was not used."
        )
    except (ValueError, ArithmeticError) as exc:
        log.warning("report %s: inference failed (%s)", base.report_id, type(exc).__name__)
        return base.error("INFERENCE_FAILED", "The model could not produce this forecast.")
    return _forecast_result(base, subject, artifact, targets, estimates, coverage, partial)


def _forecast_result(
    base: _Base,
    subject: SubjectData,
    artifact: ServedArtifact,
    targets: Sequence[TimeWindow],
    estimates: Sequence[ForecastEstimate | None],
    coverage: FeatureCoverage,
    partial: PartialProvenance,
) -> ReportResult:
    body = base.request.root
    first = next((i for i, e in enumerate(estimates) if e is not None), None)
    if first is None:
        return base.unavailable(
            "INSUFFICIENT_HISTORY",
            "Recent enough observations for the model; it abstained for every target hour",
            partial,
        )
    # An interval is shown only when the model gives one for every hour AND its artifact
    # declares the interval's nominal coverage; otherwise the forecast is point-only.
    declared = artifact.serving.interval_nominal_coverage
    intervals = declared is not None and all(e is None or e.lower is not None for e in estimates)
    points: list[ForecastPoint] = []
    for target, estimate in zip(targets[first:], estimates[first:], strict=True):
        if estimate is None:
            break  # points must be contiguous; later hours are reported as abstained
        points.append(
            ForecastPoint(
                interval_start_utc=target.start_utc,
                interval_end_utc=target.end_utc,
                local_date=None,
                median=estimate.median,
                lower=estimate.lower if intervals else None,
                upper=estimate.upper if intervals else None,
            )
        )
    warnings = []
    if intervals:
        warnings.append(
            _warning(
                "UNCALIBRATED_INTERVALS", "Interval coverage was not measured on held-out data."
            )
        )
    if len(points) < len(targets):
        warnings.append(
            _warning(
                "SPARSE_HISTORY",
                f"The model abstained for {len(targets) - len(points)} of {len(targets)} "
                "target hours; only the contiguous forecast is shown.",
            )
        )
    elif coverage.coverage < 0.5:
        warnings.append(
            _warning("SPARSE_HISTORY", "Less than half of the lookback window had usable data.")
        )
    if subject.snapshot.dataset_id != artifact.run.dataset_snapshot.dataset_id:
        warnings.append(
            _warning(
                "DEVICE_SHIFT",
                f"The model was evaluated on {artifact.run.dataset_snapshot.dataset_id}, "
                "not on this subject's data source."
                + (
                    f" {subject.source} input is admitted as an unvalidated transfer: "
                    f"{admission.rationale}"
                    if (admission := artifact.serving.admission(subject.source))
                    else ""
                ),
            )
        )
    wanted = body.metrics or [artifact.metric]
    series = ForecastSeries(
        metric=artifact.metric,
        unit=METRICS[artifact.metric].unit,
        nominal_coverage=declared if intervals else None,
        interval_calibration="uncalibrated" if intervals else "none",
        baseline=None,
        points=points,
    )
    return ReportResult(
        PhysiologyForecastResult(
            **base.fields(warnings),
            status="ok",
            task="physiology_forecast",
            provenance=Provenance(
                dataset_snapshot=subject.snapshot,
                artifact=artifact.ref,
                feature_coverage=[coverage],
            ),
            forecast=ForecastPayload(
                resolution="hour",
                tz_name=subject.tz_name,
                series=[series],
                unavailable_metrics=[
                    MetricUnavailable(metric=m, reason_code="NO_ARTIFACT_FOR_TASK")
                    for m in wanted
                    if m != artifact.metric
                ],
            ),
        )
    )
