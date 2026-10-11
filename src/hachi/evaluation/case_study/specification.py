"""Local metadata only. Shared prediction and artifact shapes remain authoritative."""

from datetime import timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import (
    ArtifactRef,
    Contract,
    DataMode,
    DatasetSnapshotRef,
    GitSha,
    Identifier,
    RelativePath,
    Sha256,
    UtcDatetime,
)
from hachi.contracts.requests import ReportRequest, SymptomCheckInEntry
from hachi.contracts.results import ReportResult


class DocumentPin(Contract):
    path: RelativePath
    sha256: Sha256


class Consent(Contract):
    status: Literal["granted", "denied", "unavailable"]
    evidence: DocumentPin | None
    recorded_at_utc: UtcDatetime | None

    @model_validator(mode="after")
    def _evidence(self) -> Self:
        if (self.evidence is not None and self.recorded_at_utc is not None) != (
            self.status == "granted"
        ) or (self.status != "granted" and (self.evidence or self.recorded_at_utc)):
            raise ValueError("granted consent requires separately recorded evidence and time")
        return self


class OnsetInterval(Contract):
    lower_utc: UtcDatetime
    upper_utc: UtcDatetime
    sealed_timeline: DocumentPin

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.upper_utc < self.lower_utc:
            raise ValueError("onset uncertainty interval is reversed")
        return self


class Cutoff(Contract):
    hours_before_lower_onset: Literal[72, 48, 24]
    as_of_utc: UtcDatetime


class HealthyPeriod(Contract):
    period_id: Identifier
    start_utc: UtcDatetime
    end_utc: UtcDatetime
    # The comparison prediction is evaluated at end_utc, fixed before sealing.


class SystemPins(Contract):
    artifact: ArtifactRef
    source: DocumentPin
    model: DocumentPin
    config: DocumentPin
    feature_source: DocumentPin
    source_compatibility: DocumentPin
    freeze_receipt: DocumentPin


class InputPins(Contract):
    export_xml: DocumentPin
    import_snapshot: DocumentPin
    import_config: DocumentPin
    dataset_snapshot: DatasetSnapshotRef

    @model_validator(mode="after")
    def _snapshot(self) -> Self:
        if self.dataset_snapshot.snapshot_sha256 != self.import_snapshot.sha256:
            raise ValueError("input snapshot identity must bind the imported SQLite bytes")
        return self


class OutcomeRule(Contract):
    forecast_window: Literal["start_inclusive_end_exclusive"]
    onset_uncertainty: Literal["closed_interval"]
    interpretation: Literal["descriptive_containment_not_clinical_labels"]
    minimum_healthy_gap_hours: Annotated[int, Field(ge=168)]


class CommittedTimeline(Contract):
    data_mode: DataMode
    onset_lower_utc: UtcDatetime
    onset_upper_utc: UtcDatetime
    healthy_assertions: Annotated[list[SymptomCheckInEntry], Field(min_length=1)]

    @model_validator(mode="after")
    def _healthy(self) -> Self:
        if any(e.symptoms_present for e in self.healthy_assertions):
            raise ValueError("healthy comparison assertions must explicitly record symptom absence")
        return self


class SourceSnapshot(Contract):
    git_sha: GitSha
    files: dict[RelativePath, Sha256]


class Prespecification(Contract):
    format_version: Literal["hachi-case-prespec-2"] = "hachi-case-prespec-2"
    data_mode: DataMode
    processing_consent: Consent
    presentation_consent: Consent
    data_holder: Literal["justin06lee"]
    onset: OnsetInterval
    cutoffs: Annotated[list[Cutoff], Field(min_length=3, max_length=3)]
    healthy_periods: Annotated[list[HealthyPeriod], Field(min_length=1)]
    requests: Annotated[list[ReportRequest], Field(min_length=1)]
    outcome_rule: OutcomeRule
    inputs: InputPins
    system: SystemPins

    @model_validator(mode="after")
    def _schedule(self) -> Self:
        if [c.hours_before_lower_onset for c in self.cutoffs] != [72, 48, 24]:
            raise ValueError("cutoffs must retain all 72/48/24 hours in declared order")
        if any(
            c.as_of_utc != self.onset.lower_utc - timedelta(hours=c.hours_before_lower_onset)
            for c in self.cutoffs
        ):
            raise ValueError("exact UTC cutoffs must derive from the sealed lower onset bound")
        keys = [(r.root.as_of, r.root.task) for r in self.requests]
        tasks = {r.root.task for r in self.requests}
        expected = {(t, task) for t in self.scoring_times() for task in tasks}
        if len(keys) != len(expected) or set(keys) != expected:
            raise ValueError("pin exactly one canonical request per task at every scoring time")
        if not tasks <= {"physiology_forecast", "illness_onset"}:
            raise ValueError(
                "preparation requests support physiology forecast and unavailable onset"
            )
        if len({r.root.subject_id for r in self.requests}) != 1:
            raise ValueError("requests must refer to one private subject")
        if len({p.period_id for p in self.healthy_periods}) != len(self.healthy_periods):
            raise ValueError("healthy periods must have unique identifiers")
        previous_end = None
        for p in self.healthy_periods:
            if not p.start_utc < p.end_utc < self.cutoffs[0].as_of_utc:
                raise ValueError("healthy periods must finish before the earliest case cutoff")
            if self.onset.lower_utc - p.end_utc < timedelta(
                hours=self.outcome_rule.minimum_healthy_gap_hours
            ):
                raise ValueError("healthy period does not meet the prespecified minimum gap")
            if previous_end is not None and p.start_utc < previous_end:
                raise ValueError("healthy periods must be ordered and non-overlapping")
            previous_end = p.end_utc
        return self

    def document_pins(self) -> list[DocumentPin]:
        system = self.system
        pins = [
            system.source,
            system.model,
            system.config,
            system.feature_source,
            system.source_compatibility,
            system.freeze_receipt,
            self.onset.sealed_timeline,
            self.inputs.export_xml,
            self.inputs.import_snapshot,
            self.inputs.import_config,
        ]
        pins.extend(
            c.evidence
            for c in (self.processing_consent, self.presentation_consent)
            if c.evidence is not None
        )
        return pins

    def scoring_times(self) -> list[UtcDatetime]:
        return [c.as_of_utc for c in self.cutoffs] + [p.end_utc for p in self.healthy_periods]


class BoundResult(Contract):
    """Receipt metadata binds an existing canonical result to its full canonical request."""

    request_sha256: Sha256
    result: ReportResult


class ResultBatch(Contract):
    results: Annotated[list[BoundResult], Field(min_length=1)]


class Receipt(Contract):
    format_version: Literal["hachi-case-receipt-2"] = "hachi-case-receipt-2"
    stage: Literal["prespecified", "predictions_sealed", "revealed"]
    data_mode: Literal["synthetic"] = "synthetic"
    observed_at_utc: UtcDatetime
    prespecification_sha256: Sha256
    previous_receipt_sha256: Sha256 | None
    payload_sha256: Sha256
    clinical_case_status: Literal["unavailable"] = "unavailable"
