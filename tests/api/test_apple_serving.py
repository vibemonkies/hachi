"""Apple Health imports reach hourly-feature models only through an explicit admission."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from hachi.api.artifacts import ServingSpec, SourceAdmission, stage_artifact
from hachi.contracts.api import Coverage, ReportJob
from hachi.contracts.manifests import TimeWindow
from hachi.data.apple_health.hourly import AVAILABILITY_RULE, apple_hourly_features
from hachi.evaluation import ForecastInput

from .conftest import HR_POLICY, export_xml, heart_rate_record, make_packet, upload, wait

APPLE_POLICY = HR_POLICY.model_copy(update={"availability_rule": AVAILABILITY_RULE})
RATIONALE = "Synthetic transfer test: PMData-evaluated baseline applied to Apple Watch HR."
START = datetime(2026, 9, 1, tzinfo=UTC)
AS_OF = "2026-09-03T12:00:00Z"


def apple_hr_export(hours: int, every_minutes: int = 1) -> bytes:
    """Heart rate every `every_minutes`, created 30 s after each sample (sealed in its hour)."""
    records = []
    for minute in range(0, hours * 60, every_minutes):
        moment = START + timedelta(minutes=minute)
        value = 60 + (minute // 60) % 7 + (minute % 10) / 10
        stamp = moment.strftime("%Y-%m-%d %H:%M:%S +0000")
        created = (moment + timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S +0000")
        records.append(heart_rate_record(stamp, f"{value:.1f}", creationDate=created))
    return export_xml(records)


def admitting_serving(**changes) -> ServingSpec:
    return ServingSpec(
        format_version="hachi-serving-1",
        task="physiology_forecast",
        resolution="hour",
        entry_point="hachi.models.baselines.load_artifact",
        input="hourly_features",
        feature_policy=HR_POLICY,
        accepted_sources=[
            SourceAdmission(source="apple_health", feature_policy=APPLE_POLICY, rationale=RATIONALE)
        ],
    ).model_copy(update=changes)


@pytest.fixture
def apple_client(tmp_path, data_root, snapshot_id, open_client, make_settings):
    packet = make_packet(
        tmp_path / "apple-packet",
        data_root / "derived" / snapshot_id,
        serving=admitting_serving(),
        artifact_id="synthetic-last-valid-hr-apple",
    )
    root = tmp_path / "apple-artifacts"
    root.mkdir()
    pin = stage_artifact(root, packet.model_dir, packet.packet_dir, packet.serving)
    client = open_client(make_settings(artifact_root=root, served_artifacts=(pin,)))
    return client, pin


def forecast(client, subject: str) -> ReportJob:
    body = {
        "schema_version": "0.1",
        "subject_id": subject,
        "as_of": AS_OF,
        "task": "physiology_forecast",
        "resolution": "hour",
        "horizon_hours": 24,
        "metrics": ["heart_rate"],
    }
    response = client.post("/v1/reports", json=body)
    assert response.status_code in (200, 202), response.text
    wait(client)
    return ReportJob.model_validate_json(
        client.get(f"/v1/reports/{response.json()['report_id']}").content
    )


def test_an_admitted_apple_import_is_forecast_end_to_end(apple_client):
    client, pin = apple_client
    imported = upload(client, apple_hr_export(72), subject="synthetic-apple-dense")
    assert imported.status_code == 202
    wait(client)
    assert client.get(f"/v1/imports/{imported.json()['import_id']}").json()["state"] == "succeeded"

    coverage = Coverage.model_validate_json(
        client.get("/v1/subjects/synthetic-apple-dense/coverage").content
    )
    assert coverage.history == "sufficient"
    support = {t.task: t for t in coverage.task_support}
    assert support["physiology_forecast"].supported

    job = forecast(client, "synthetic-apple-dense")
    result = job.result.root
    assert result.status == "ok", result
    assert result.provenance.artifact == pin
    assert result.provenance.dataset_snapshot.dataset_id == "synthetic-apple-health-export"
    shift = next(w for w in result.warnings if w.code == "DEVICE_SHIFT")
    assert "unvalidated transfer" in shift.message and RATIONALE in shift.message
    series = result.forecast.series[0]
    assert series.interval_calibration == "none"  # the baseline is point-only
    # last-valid repeats the sealed 11:00-12:00 Apple bin: 60 + (59 // 1 hour index) % 7 + 0.45
    assert series.points[0].median == pytest.approx(60 + (59 % 7) + 0.45)

    # The same input built directly from #78's sealed bins gives the same forecast.
    service = client.app.state.service
    served = service.catalog.artifacts[0]
    subject = service.catalog.subject("synthetic-apple-dense", service.metadata, service.workspace)
    cutoff = result.as_of
    history = apple_hourly_features(
        subject.path, APPLE_POLICY, cutoff, cutoff - timedelta(hours=48)
    ).features
    targets = tuple(
        TimeWindow(start_utc=cutoff + timedelta(hours=i), end_utc=cutoff + timedelta(hours=i + 1))
        for i in range(24)
    )
    direct = served.model.predict(ForecastInput("synthetic-apple-dense", cutoff, targets, history))
    assert [p.median for p in series.points] == [e.median for e in direct]


def test_a_model_that_does_not_admit_apple_says_so(client):
    upload(client, apple_hr_export(72), subject="synthetic-apple-dense")
    wait(client)
    result = forecast(client, "synthetic-apple-dense").result.root
    assert (result.status, result.reason_code) == ("unavailable", "NO_ARTIFACT_FOR_TASK")
    assert "admits Apple Health input" in result.requirements[0]
    assert "pmdata" in result.requirements[0]
    coverage = client.get("/v1/subjects/synthetic-apple-dense/coverage").json()
    forecast_support = next(
        t for t in coverage["task_support"] if t["task"] == "physiology_forecast"
    )
    assert forecast_support["reason_code"] == "NO_ARTIFACT_FOR_TASK"


def test_typical_watch_sampling_abstains_at_the_models_density_gates(apple_client):
    client, _ = apple_client
    upload(client, apple_hr_export(72, every_minutes=5), subject="synthetic-apple-sparse")
    wait(client)
    result = forecast(client, "synthetic-apple-sparse").result.root
    # 12 samples/hour fall below the artifact's 0.5 minute-density and 30-sample gates.
    assert (result.status, result.reason_code) == ("unavailable", "INSUFFICIENT_HISTORY")


def test_admissions_keep_the_model_target_and_their_own_readiness():
    with pytest.raises(ValidationError, match="sealed availability rule"):
        SourceAdmission(source="apple_health", feature_policy=HR_POLICY, rationale=RATIONALE)
    steps = APPLE_POLICY.model_copy(update={"metric": "steps", "aggregation": "sum"})
    with pytest.raises(ValidationError, match="own metric and aggregation"):
        ServingSpec(
            format_version="hachi-serving-1",
            task="physiology_forecast",
            resolution="hour",
            entry_point="hachi.models.baselines.load_artifact",
            input="hourly_features",
            feature_policy=HR_POLICY,
            accepted_sources=[
                SourceAdmission(source="apple_health", feature_policy=steps, rationale=RATIONALE)
            ],
        )


def test_staging_records_an_explicit_apple_admission(tmp_path, data_root, snapshot_id):
    from hachi.api.__main__ import serving_from_protocol

    packet = make_packet(tmp_path / "p", data_root / "derived" / snapshot_id)
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"feature_policy": HR_POLICY.model_dump()}))
    plain = serving_from_protocol(protocol, packet.model_dir)
    assert plain.accepted_sources == []
    admitted = serving_from_protocol(protocol, packet.model_dir, RATIONALE)
    (admission,) = admitted.accepted_sources
    assert admission.feature_policy == APPLE_POLICY and admission.rationale == RATIONALE
