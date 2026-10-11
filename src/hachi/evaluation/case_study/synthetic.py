"""Generate local fixture inputs; no real export, probabilities, inference or tuning."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import quoteattr

from hachi.contracts.base import ArtifactRef, DatasetSnapshotRef
from hachi.contracts.requests import (
    IllnessOnsetRequest,
    PhysiologyForecastHourlyRequest,
    ReportRequest,
    SymptomCheckInEntry,
)
from hachi.contracts.results import PartialProvenance, ReportResult, UnavailableResult
from hachi.data.apple_health import ImportConfig, import_export, iter_observations
from hachi.data.apple_health.hourly import AVAILABILITY_RULE, apple_hourly_features
from hachi.evaluation.features import HourlyFeaturePolicy
from hachi.evaluation.serialization import document_bytes, document_sha256

from .lifecycle import (
    CaseRefused,
    digest,
    exclusive_write,
    preregister,
    reveal,
    seal,
    source_snapshot,
    verify,
)
from .specification import (
    BoundResult,
    CommittedTimeline,
    Consent,
    Cutoff,
    DocumentPin,
    HealthyPeriod,
    InputPins,
    OnsetInterval,
    OutcomeRule,
    Prespecification,
    ResultBatch,
    SourceSnapshot,
    SystemPins,
)


def fixture(inputs: Path, repo: Path) -> Prespecification:
    """Fictional dates and consent evidence are never claims about a real person."""
    source = source_snapshot(repo)
    onset = datetime(2026, 1, 10, 12, tzinfo=UTC)
    healthy = HealthyPeriod(
        period_id="synthetic-healthy",
        start_utc=onset - timedelta(days=8),
        end_utc=onset - timedelta(days=7),
    )
    timeline = CommittedTimeline(
        data_mode="synthetic",
        onset_lower_utc=onset,
        onset_upper_utc=onset + timedelta(hours=6),
        healthy_assertions=[
            SymptomCheckInEntry(
                kind="symptom_checkin",
                entry_id="synthetic-absence",
                entered_at_utc=healthy.end_utc,
                period_start_utc=healthy.start_utc,
                period_end_utc=healthy.end_utc,
                symptoms_present=False,
                symptoms=[],
                severity=None,
            )
        ],
    )
    inputs.mkdir(mode=0o700, exist_ok=False)
    _, database, config = _generated_import(inputs)
    values = {
        "source.json": document_bytes(source),
        "model.json": document_bytes({"synthetic_fixture": True, "inference": "unavailable"}),
        "config.json": document_bytes({"synthetic_fixture": True, "tuning": False}),
        "feature-source.json": document_bytes({"availability_rule": AVAILABILITY_RULE}),
        "compatibility.json": document_bytes({"synthetic_only": True, "real_transfer": False}),
        "freeze.json": document_bytes({"final_test_authorized": False}),
        "timeline.json": document_bytes(timeline),
        "import-config.json": document_bytes(config),
        "processing.json": document_bytes({"synthetic_fixture": True, "processing": "granted"}),
    }
    for name, raw in values.items():
        exclusive_write(inputs / name, raw)

    def pin(name: str) -> DocumentPin:
        return DocumentPin(path=name, sha256=digest(values[name]))

    times = [onset - timedelta(hours=h) for h in (72, 48, 24)] + [healthy.end_utc]
    requests = [
        request
        for t in times
        for request in (
            ReportRequest(
                PhysiologyForecastHourlyRequest(
                    schema_version="0.1",
                    subject_id=config.subject_id,
                    as_of=t,
                    task="physiology_forecast",
                    resolution="hour",
                    horizon_hours=24,
                    metrics=["heart_rate"],
                )
            ),
            ReportRequest(
                IllnessOnsetRequest(
                    schema_version="0.1",
                    subject_id=config.subject_id,
                    as_of=t,
                    task="illness_onset",
                    horizon_hours=72,
                )
            ),
        )
    ]
    return Prespecification(
        data_mode="synthetic",
        processing_consent=Consent(
            status="granted",
            evidence=pin("processing.json"),
            recorded_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        presentation_consent=Consent(status="unavailable", evidence=None, recorded_at_utc=None),
        data_holder="justin06lee",
        onset=OnsetInterval(
            lower_utc=onset,
            upper_utc=onset + timedelta(hours=6),
            sealed_timeline=pin("timeline.json"),
        ),
        cutoffs=[
            Cutoff(hours_before_lower_onset=h, as_of_utc=onset - timedelta(hours=h))
            for h in (72, 48, 24)
        ],
        healthy_periods=[healthy],
        requests=requests,
        outcome_rule=OutcomeRule(
            forecast_window="start_inclusive_end_exclusive",
            onset_uncertainty="closed_interval",
            interpretation="descriptive_containment_not_clinical_labels",
            minimum_healthy_gap_hours=168,
        ),
        inputs=InputPins(
            export_xml=DocumentPin(
                path="export.xml", sha256=digest((inputs / "export.xml").read_bytes())
            ),
            import_snapshot=DocumentPin(
                path="import.sqlite3", sha256=digest(database.read_bytes())
            ),
            import_config=pin("import-config.json"),
            dataset_snapshot=DatasetSnapshotRef(
                dataset_id=config.dataset_id,
                dataset_version="apple-generated-fixture-1",
                snapshot_sha256=digest(database.read_bytes()),
            ),
        ),
        system=SystemPins(
            artifact=ArtifactRef(
                artifact_id="synthetic-unavailable", artifact_sha256=pin("model.json").sha256
            ),
            source=pin("source.json"),
            model=pin("model.json"),
            config=pin("config.json"),
            feature_source=pin("feature-source.json"),
            source_compatibility=pin("compatibility.json"),
            freeze_receipt=pin("freeze.json"),
        ),
    )


def unavailable_batch(spec: Prespecification, source: SourceSnapshot) -> ResultBatch:
    results = []
    for request in spec.requests:
        r = request.root
        task = r.task
        cutoff = r.as_of
        results.append(
            BoundResult(
                request_sha256=document_sha256(request),
                result=ReportResult(
                    UnavailableResult(
                        schema_version="0.1",
                        report_id=f"synthetic-{len(results)}",
                        subject_id="synthetic-only",
                        as_of=cutoff,
                        data_mode="synthetic",
                        generated_at_utc=datetime.now(UTC),
                        git_sha=source.git_sha,
                        warnings=[],
                        replay=None,
                        status="unavailable",
                        task=task,
                        reason_code="NO_VALIDATED_ILLNESS_ARTIFACT"
                        if task == "illness_onset"
                        else "NO_ARTIFACT_FOR_TASK",
                        requirements=[
                            "Accepted frozen system and permitted real inputs are absent."
                        ],
                        provenance=PartialProvenance(
                            dataset_snapshot=spec.inputs.dataset_snapshot,
                            artifact=spec.system.artifact,
                            feature_coverage=[],
                        ),
                    )
                ),
            )
        )
    return ResultBatch(results=results)


def _generated_import(root: Path):
    """The only built-in input producer generates these six fictional records."""
    cutoff = datetime(2026, 1, 7, 12, tzinfo=UTC)
    hour = cutoff - timedelta(hours=1)

    def record(**changes: str) -> str:
        fields = {
            "type": "HKQuantityTypeIdentifierHeartRate",
            "unit": "count/min",
            "value": "65",
            "sourceName": "Synthetic Apple Watch",
            "startDate": hour.isoformat(),
            "endDate": hour.isoformat(),
            "creationDate": hour.isoformat(),
            **changes,
        }
        return "<Record " + " ".join(f"{k}={quoteattr(v)}" for k, v in fields.items()) + "/>"

    early = record()
    rows = [
        early,
        early,
        record(
            startDate=(hour + timedelta(minutes=1)).isoformat(),
            endDate=(hour + timedelta(minutes=1)).isoformat(),
            value="99",
            creationDate=(cutoff + timedelta(seconds=1)).isoformat(),
        ),
        record(
            startDate=(cutoff + timedelta(seconds=1)).isoformat(),
            endDate=(cutoff + timedelta(seconds=1)).isoformat(),
            creationDate=(cutoff + timedelta(seconds=1)).isoformat(),
            value="97",
        ),
        record(
            type="HKQuantityTypeIdentifierStepCount",
            unit="count",
            value="120",
            endDate=cutoff.isoformat(),
        ),
        record(
            type="HKCategoryTypeIdentifierSleepAnalysis",
            unit="",
            value="HKCategoryValueSleepAnalysisAsleepCore",
            startDate=(cutoff - timedelta(hours=8)).isoformat(),
            endDate=(cutoff + timedelta(seconds=1)).isoformat(),
        ),
    ]
    xml = ("<HealthData>" + "".join(rows) + "</HealthData>").encode()
    exclusive_write(root / "export.xml", xml)
    database = root / "import.sqlite3"
    config = ImportConfig(
        dataset_id="synthetic-apple",
        subject_id="synthetic-only",
        declared_tz_name="UTC",
        data_mode="synthetic",
    )
    audit = import_export(
        root / "export.xml",
        config,
        database,
    )
    return audit, database, config


def parser_seam(root: Path) -> dict[str, object]:
    """Independent known generated values/counts compared to the actual Apple boundary."""
    root.mkdir(mode=0o700, exist_ok=False)
    audit, database, _ = _generated_import(root)
    cutoff = datetime(2026, 1, 7, 12, tzinfo=UTC)
    hour = cutoff - timedelta(hours=1)
    visible = list(iter_observations(database, as_of=cutoff))
    expected = {("heart_rate", "bpm", 65.0), ("steps", "count", 120.0)}
    if (
        audit.counts.records_seen != 6
        or audit.counts.records_accepted != 5
        or audit.counts.records_duplicate != 1
        or {(o.metric, o.unit, o.value) for o in visible} != expected
        or len(visible) != 2
        or any(o.available_at_utc > cutoff or o.end_utc > cutoff for o in visible)
        or len({o.source_id for o in visible}) != 1
    ):
        raise CaseRefused("generated raw parser/cutoff reconciliation failed")
    policy = HourlyFeaturePolicy(
        metric="heart_rate",
        aggregation="mean",
        min_coverage=0.0,
        min_observed_count=1,
        availability_rule=AVAILABILITY_RULE,
    )
    before = apple_hourly_features(database, policy, cutoff, hour)
    after = apple_hourly_features(database, policy, cutoff + timedelta(hours=2), hour)
    if (
        len(before.features) != 1
        or before.features[0].value != 65.0
        or before.features[0].aggregate.coverage != 1 / 60
        or before.features[0] != after.features[0]
    ):
        raise CaseRefused("generated late creation changed a sealed pre-transform input")
    return {
        "data_mode": "synthetic",
        "records_seen": 6,
        "records_accepted": 5,
        "duplicates": 1,
        "visible_at_cutoff": 2,
        "source_count": 1,
        "unit_reconciliation": True,
        "future_creation_event_and_sleep_excluded": True,
        "hourly_prefix_unchanged_after_tail": True,
    }


def demo(output: Path, repo: Path) -> dict[str, object]:
    if output.resolve().is_relative_to(repo.resolve()):
        raise CaseRefused("generated private run must be outside the repository")
    output.mkdir(mode=0o700, exist_ok=False)
    inputs = output / "inputs"
    spec = fixture(inputs, repo)
    root = output / "receipts"
    pin = preregister(spec, inputs, repo, root)
    refused = []

    def refusal(name: str, action) -> None:
        try:
            action()
        except (CaseRefused, FileExistsError, FileNotFoundError):
            refused.append(name)
        else:
            raise CaseRefused("generated expected-refusal check did not refuse")

    refusal("reveal_before_seal", lambda: reveal(root, pin, "0" * 64, inputs, repo))
    refusal(
        "real_mode_with_freeze_false",
        lambda: preregister(
            spec.model_copy(update={"data_mode": "real"}), inputs, repo, output / "real-refused"
        ),
    )
    batch = unavailable_batch(spec, source_snapshot(repo))
    refusal(
        "posthoc_cutoff_omission",
        lambda: seal(root, pin, ResultBatch(results=batch.results[:-1]), inputs, repo),
    )
    sealed = seal(root, pin, batch, inputs, repo)
    refusal("resealing", lambda: seal(root, pin, batch, inputs, repo))
    opened = reveal(root, pin, sealed, inputs, repo)
    refusal("repeat_reveal", lambda: reveal(root, pin, sealed, inputs, repo))
    refusal("seal_after_reveal", lambda: seal(root, pin, batch, inputs, repo))
    receipt = verify(root, pin, sealed, opened, inputs, repo)
    result = {
        "receipt_lifecycle": receipt,
        "generated_parser_seam": parser_seam(output / "parser"),
        "refusals_verified": refused,
        "external_pins": {"prespecification": pin, "sealed_predictions": sealed, "reveal": opened},
        "real_case_acceptance": "unavailable",
    }
    exclusive_write(output / "synthetic-proof.json", document_bytes(result))
    return result
