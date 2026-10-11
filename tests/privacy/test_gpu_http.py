"""Actual HTTP cleanup/error/refusal checks with generated staged models and no GPU."""

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from test_correction_http import live_api as live_api
from test_gpu_boundary import PIN, SENTINEL, Remote

from hachi.api.artifacts import ServingSpec, SourceAdmission, load_served_artifact, stage_artifact
from hachi.api.gpu import Gx10Target
from hachi.api.sources import open_dataset_snapshot
from hachi.contracts.manifests import ModelRef, RunManifest
from hachi.data.apple_health.hourly import AVAILABILITY_RULE
from hachi.data.pmdata import build, load_config
from hachi.models.chronos import ChronosConfig
from hachi.models.chronos.artifacts import ChronosArtifact, save_artifact


def stage_generated_catalog(service, tmp_path, remote):
    # Reuse only ordinary generated-data/packet builders, not the API author's assertions.
    path = Path(__file__).parents[1] / "api/conftest.py"
    name = "_privacy_generated_api_fixtures"
    spec = importlib.util.spec_from_file_location(name, path)
    factory = importlib.util.module_from_spec(spec)
    sys.modules[name] = factory
    spec.loader.exec_module(factory)
    fixtures = factory._pmdata_fixtures()
    data_root = tmp_path / "generated-data"
    data_root.mkdir()
    archive = data_root / "generated.zip"
    admission = fixtures.write_archive(archive, fixtures.build_members())
    from hachi.data.pmdata.snapshot import GitState

    build(archive, data_root / "derived", load_config(), admission, GitState("0" * 40, False))
    (snapshot,) = [p for p in (data_root / "derived").iterdir() if not p.name.startswith(".")]
    packet = factory.make_packet(tmp_path / "generated-baseline", snapshot)
    config = ChronosConfig(model=PIN, metric="heart_rate", aggregation="mean", context_hours=48)
    model = ChronosArtifact(
        model_id="chronos-2-zero-shot",
        chronos=config,
        protocol_sha256="a" * 64,
        harness_lookback_hours=48,
    )
    model_dir = tmp_path / "generated-chronos"
    ref = save_artifact(model_dir, model, artifact_id="generated-privacy-chronos")
    run = RunManifest.model_validate_json((packet.packet_dir / "run.json").read_bytes())
    run = run.model_copy(
        update={
            "artifact": ref,
            "environment_sha256": PIN.runtime_lock_sha256,
            "model": ModelRef(
                model_id=model.model_id,
                checkpoint_source=PIN.model_id,
                checkpoint_revision=PIN.revision,
                license=PIN.license,
            ),
        }
    )
    (packet.packet_dir / "run.json").write_text(run.model_dump_json())
    serving = ServingSpec(
        format_version="hachi-serving-1",
        task="physiology_forecast",
        resolution="hour",
        entry_point="hachi.models.chronos.artifacts.load_artifact",
        input="hourly_features",
        feature_policy=factory.HR_POLICY,
        interval_nominal_coverage=0.8,
        requires_gpu=True,
        protocol_sha256="a" * 64,
        accepted_sources=[
            SourceAdmission(
                source="apple_health",
                feature_policy=factory.HR_POLICY.model_copy(
                    update={"availability_rule": AVAILABILITY_RULE}
                ),
                rationale="Generated privacy probe only; not real source transfer authorization.",
            )
        ],
    )
    artifact_root = tmp_path / "generated-artifacts"
    artifact_root.mkdir()
    pin = stage_artifact(artifact_root, model_dir, packet.packet_dir, serving)
    target = Gx10Target(transport=remote, owner="privacy-test", checkout="/generated")
    service.catalog.artifacts = (load_served_artifact(artifact_root, pin, target),)
    service.catalog.datasets = (
        open_dataset_snapshot(data_root, snapshot.name, allow_unadmitted=True),
    )
    service.catalog.gx10 = target
    return factory, pin


def forecast(client, service, subject="p01", cutoff="2020-03-29T12:00:00Z"):
    response = client.post(
        "/v1/reports",
        json={
            "schema_version": "0.1",
            "subject_id": subject,
            "as_of": cutoff,
            "task": "physiology_forecast",
            "resolution": "hour",
            "horizon_hours": 24,
            "metrics": ["heart_rate"],
        },
    )
    assert response.status_code == 202
    assert service.runner.wait_idle()
    result = client.get(f"/v1/reports/{response.json()['report_id']}")
    assert result.status_code == 200
    return result


@pytest.mark.parametrize("mode", ["ok", "integrity_failure"])
def test_cleanup_refusal_reaches_http_without_predictions_or_private_echo(
    live_api, tmp_path, caplog, mode
):
    client, service, _ = live_api
    remote = Remote(mode, "both")
    _, pin = stage_generated_catalog(service, tmp_path, remote)
    assert client.get("/healthz").json()["artifacts"] == [pin.model_dump(mode="json")]
    response = forecast(client, service)
    result = response.json()["result"]
    assert result["status"] == "error"
    assert result["error_code"] == "INFERENCE_FAILED"
    assert "payload" not in result and "series" not in result
    assert SENTINEL not in response.text and SENTINEL not in caplog.text
    assert "remove_request" in remote.calls and "remove_output" in remote.calls


def test_unexpected_transport_error_erases_outputs_and_logs_only_class(live_api, tmp_path, caplog):
    client, service, _ = live_api
    remote = Remote("unexpected")
    stage_generated_catalog(service, tmp_path, remote)
    response = forecast(client, service)
    assert response.json()["result"]["status"] == "error"
    assert SENTINEL not in response.text and SENTINEL not in caplog.text
    remaining = len(remote.files)
    assert remaining == 1


def test_real_classified_apple_source_refused_before_transfer(live_api, tmp_path):
    """Only generated bytes; deliberately real-classified metadata tests the admission guard."""
    from datetime import UTC, datetime, timedelta

    client, service, _ = live_api
    remote = Remote()
    factory, _ = stage_generated_catalog(service, tmp_path, remote)
    start = datetime(2026, 9, 1, tzinfo=UTC)
    records = []
    for minute in range(48 * 60):
        stamp = (start + timedelta(minutes=minute)).strftime("%Y-%m-%d %H:%M:%S +0000")
        records.append(factory.heart_rate_record(stamp, "70", creationDate=stamp))
    response = client.post(
        "/v1/imports",
        params={
            "subject_id": "synthetic-privacy-real-classification",
            "tz_name": "UTC",
            "source_format": "apple_health_export_xml",
            "data_mode": "real",
        },
        content=factory.export_xml(records),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 202
    assert service.runner.wait_idle()
    subject = service.catalog.subject(
        "synthetic-privacy-real-classification", service.metadata, service.workspace
    )
    assert subject is not None and subject.data_mode == "real" and subject.source == "apple_health"
    result = forecast(client, service, subject.subject_id, "2026-09-03T00:00:00Z").json()["result"]
    assert result["status"] in ("error", "unavailable")
    assert not remote.calls, "unauthorized source reached the remote transport"
    assert (
        client.delete(
            f"/v1/subjects/{subject.subject_id}", params={"confirm": subject.subject_id}
        ).status_code
        == 204
    )
