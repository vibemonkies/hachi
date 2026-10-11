"""Generated fixtures and real journal operations with an explicitly simulated future clock."""

import hashlib
import platform
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hachi.contracts.base import ArtifactRef, DatasetSnapshotRef, local_day_bounds
from hachi.contracts.requests import PhysiologyForecastDailyRequest, ReportRequest
from hachi.contracts.results import (
    ForecastPayload,
    ForecastPoint,
    ForecastSeries,
    PhysiologyForecastResult,
    Provenance,
    ReportResult,
)
from hachi.contracts.tables import Aggregate
from hachi.evaluation.serialization import document_bytes, document_sha256

from .journal import Journal
from .policy import ProspectiveRefused
from .specification import FollowUp, MetricTarget, Prediction, Protocol, SystemPins

PLAN = b"Generated preparation only: next-local-day resting HR; no real study or acceptance.\n"
INPUT = b"generated synthetic feature prefix\n"
OUTCOME = b"generated synthetic follow-up document\n"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fixture(at: datetime) -> tuple[Protocol, Prediction]:
    """No real records, participant identities, artifacts, or freeze documents are read."""
    artifact = ArtifactRef(artifact_id="synthetic-artifact", artifact_sha256=digest(b"synthetic"))
    snapshot = DatasetSnapshotRef(
        dataset_id="synthetic", dataset_version="generated-1", snapshot_sha256=digest(INPUT)
    )
    pins = SystemPins(
        model_version="synthetic-1",
        artifact=artifact,
        git_sha="0" * 40,
        environment_sha256=digest(b"synthetic-environment"),
        config_sha256=digest(b"synthetic-config"),
        preprocessing_sha256=digest(b"synthetic-prefix"),
        thresholds_sha256=digest(b"synthetic-no-alerts"),
        calibration_sha256=digest(b"synthetic-uncalibrated"),
        selection_receipt_sha256=digest(b"synthetic-not-a-real-freeze"),
    )
    protocol = Protocol(
        protocol_version="synthetic-1",
        data_mode="synthetic",
        analysis_plan_sha256=digest(PLAN),
        system=pins,
        tz_name="UTC",
        targets=[MetricTarget(metric="resting_heart_rate_vendor", aggregation="mean")],
    )
    day = at.date() + timedelta(days=1)
    start, end = local_day_bounds(day, "UTC")
    request = ReportRequest(
        PhysiologyForecastDailyRequest(
            schema_version="0.1",
            subject_id="synthetic-generated",
            as_of=at,
            task="physiology_forecast",
            resolution="day",
            metrics=["resting_heart_rate_vendor"],
        )
    )
    result = ReportResult(
        PhysiologyForecastResult(
            schema_version="0.1",
            report_id="synthetic-daily",
            subject_id=request.root.subject_id,
            as_of=at,
            data_mode="synthetic",
            generated_at_utc=at,
            git_sha=pins.git_sha,
            warnings=[],
            replay=None,
            status="ok",
            task="physiology_forecast",
            provenance=Provenance(
                dataset_snapshot=snapshot, artifact=artifact, feature_coverage=[]
            ),
            forecast=ForecastPayload(
                resolution="day",
                tz_name="UTC",
                unavailable_metrics=[],
                series=[
                    ForecastSeries(
                        metric="resting_heart_rate_vendor",
                        unit="bpm",
                        nominal_coverage=None,
                        interval_calibration="none",
                        baseline=None,
                        points=[
                            ForecastPoint(
                                interval_start_utc=start,
                                interval_end_utc=end,
                                local_date=day,
                                median=60.0,
                                lower=None,
                                upper=None,
                            )
                        ],
                    ),
                ],
            ),
        )
    )
    return protocol, Prediction(
        request=request,
        result=result,
        dataset_snapshot=snapshot,
        input_sha256=digest(INPUT),
        protocol_sha256=document_sha256(protocol),
        system_sha256=document_sha256(pins),
        window_start_utc=start,
        window_end_utc=end,
    )


def outcome(prediction: Prediction, pin: str) -> FollowUp:
    aggregate = Aggregate(
        dataset_id="synthetic",
        subject_id=prediction.request.root.subject_id,
        metric="resting_heart_rate_vendor",
        unit="bpm",
        resolution="day",
        interval_start_utc=prediction.window_start_utc,
        interval_end_utc=prediction.window_end_utc,
        local_date=prediction.window_start_utc.date(),
        tz_name="UTC",
        aggregation="mean",
        value=61.0,
        null_reason=None,
        observed_count=24,
        coverage=1.0,
        source_ids=["synthetic-source"],
        pipeline_version="synthetic-1",
    )
    follow_up = FollowUp(
        prediction_sha256=pin,
        data_mode="synthetic",
        status="observed",
        recorded_at_utc=prediction.window_end_utc + timedelta(seconds=1),
        observed_through_utc=prediction.window_end_utc,
        outcome_snapshot=DatasetSnapshotRef(
            dataset_id="synthetic",
            dataset_version="generated-follow-up-1",
            snapshot_sha256=digest(OUTCOME),
        ),
        outcome_document_sha256=digest(OUTCOME),
        aggregates=[aggregate],
        missing_reason=None,
    )
    return follow_up.model_copy(
        update={"outcome_document_sha256": digest(document_bytes([aggregate]))}
    )


def generated_proof() -> dict[str, object]:
    """Exercise disk appends, verification and refusals; emit counts, never row values."""
    at = datetime(2040, 1, 10, 12, tzinfo=UTC)
    protocol, prediction = fixture(at)
    refusals = []
    with TemporaryDirectory(prefix="hachi25-generated-") as directory:
        directory_path = Path(directory).resolve()
        root = directory_path / "journal"
        with patch(
            "hachi.evaluation.prospective.journal._now", return_value=at - timedelta(seconds=1)
        ):
            registration = Journal.create(root, protocol, analysis_plan=PLAN)
        journal = Journal(root)
        with patch(
            "hachi.evaluation.prospective.journal._now", return_value=at + timedelta(seconds=1)
        ):
            saved = journal.predict(
                prediction, expected_head=registration.sha256, input_document=INPUT
            )
        follow_up = outcome(prediction, saved.sha256)
        checks = {
            "outcome_before_window_end": lambda: journal.follow_up(
                follow_up,
                expected_head=saved.sha256,
                outcome_document=document_bytes(follow_up.aggregates),
            ),
            "stale_head": lambda: journal.predict(
                prediction, expected_head=registration.sha256, input_document=INPUT
            ),
            "input_tamper": lambda: journal.predict(
                prediction, expected_head=saved.sha256, input_document=b"tampered"
            ),
            "prediction_backfill": lambda: journal.predict(
                prediction, expected_head=saved.sha256, input_document=INPUT
            ),
        }
        for name, operation in checks.items():
            clock = (
                at + timedelta(seconds=301)
                if name == "prediction_backfill"
                else at + timedelta(seconds=2)
            )
            with patch("hachi.evaluation.prospective.journal._now", return_value=clock):
                try:
                    operation()
                except ProspectiveRefused:
                    refusals.append(name)
                else:
                    raise AssertionError("generated refusal did not occur")
        with patch(
            "hachi.evaluation.prospective.journal._now", return_value=follow_up.recorded_at_utc
        ):
            final = journal.follow_up(
                follow_up,
                expected_head=saved.sha256,
                outcome_document=document_bytes(follow_up.aggregates),
            )
        chain = journal.verify(final.sha256)
        for name, operation in {
            "real_protocol": lambda: Journal.create(
                directory_path / "real",
                protocol.model_copy(update={"data_mode": "real"}),
                analysis_plan=PLAN,
            ),
            "duplicate_follow_up": lambda: journal.follow_up(
                follow_up,
                expected_head=final.sha256,
                outcome_document=document_bytes(follow_up.aggregates),
            ),
        }.items():
            with patch(
                "hachi.evaluation.prospective.journal._now",
                return_value=follow_up.recorded_at_utc + timedelta(seconds=1),
            ):
                try:
                    operation()
                except ProspectiveRefused:
                    refusals.append(name)
                else:
                    raise AssertionError("generated refusal did not occur")
        last = root / "00000002.json"
        last.write_bytes(document_bytes(final).replace(b'"observed"', b'"missing"'))
        try:
            journal.verify(final.sha256)
        except ProspectiveRefused:
            refusals.append("receipt_tamper")
        else:
            raise AssertionError("generated tamper refusal did not occur")
    return {
        "data_mode": "synthetic",
        "clock": "simulated_future_for_generated_proof",
        "verified_receipts": len(chain),
        "prediction_before_window": True,
        "follow_up_after_window": True,
        "refusals": refusals,
        "trusted_attestation": False,
        "real_study_authorized": False,
        "python": platform.python_version(),
        "implementation_sha256": digest(
            b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))
        ),
    }
