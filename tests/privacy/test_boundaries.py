"""Security properties on the real API/storage path, using generated data only."""

import logging

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from hachi.api.app import create_app
from hachi.api.catalog import Catalog
from hachi.api.settings import Settings
from hachi.storage import Workspace

SENTINEL = "SYNTHETIC-PRIVATE-SENTINEL-19"
ONSET = {
    "kind": "symptom_onset",
    "entry_id": SENTINEL,
    "entered_at_utc": "2026-09-02T08:00:00Z",
    "onset_earliest_utc": "2026-09-01T20:00:00Z",
    "onset_latest_utc": "2026-09-02T06:00:00Z",
    "symptoms": ["cough"],
    "severity": 2,
}


@pytest.fixture
def private_api(tmp_path):
    workspace = Workspace.for_owner("privacy-test", tmp_path / "workspaces")
    settings = Settings(
        owner="privacy-test",
        workspace=workspace,
        database=workspace.default_database,
        git_sha="a" * 40,
    )
    with TestClient(
        create_app(settings, catalog=lambda _: Catalog()),
        base_url="http://127.0.0.1",
        raise_server_exceptions=False,
    ) as client:
        yield client, settings


def test_deleted_personal_documents_do_not_remain_in_sqlite_or_wal(private_api):
    client, settings = private_api
    body = {"schema_version": "0.1", "entries": [ONSET]}
    assert client.post("/v1/subjects/synthetic-delete/observations", json=body).status_code == 201
    assert (
        client.delete(
            "/v1/subjects/synthetic-delete", params={"confirm": "synthetic-delete"}
        ).status_code
        == 204
    )
    assert not client.app.state.service.metadata.subject_known("synthetic-delete")
    files = list(settings.database.parent.glob("metadata.sqlite3*"))
    assert files and all(SENTINEL.encode() not in f.read_bytes() for f in files)


def test_validation_errors_do_not_echo_schedule_ids_or_unknown_fields(private_api):
    client, _ = private_api
    scenario = {
        "schema_version": "0.1",
        "subject_id": "synthetic-error",
        "tz_name": "UTC",
        "schedules": [
            {
                "schedule_id": SENTINEL,
                "bedtime_local": "2026-10-10T22:00:00",
                "wake_time_local": "2026-10-10T21:00:00",
            }
        ],
        "assumptions": {
            "prior_sleep_hours": 7.0,
            "caffeine": "none",
            "light_exposure": "not_modeled",
        },
    }
    response = client.post("/v1/scenarios", json=scenario)
    assert response.status_code == 422 and SENTINEL not in response.text
    response = client.post(
        "/v1/subjects/synthetic-error/observations",
        json={"schema_version": "0.1", "entries": [ONSET], SENTINEL: "x"},
    )
    assert response.status_code == 422 and SENTINEL not in response.text


def test_unexpected_error_log_omits_subject_path_and_exception_data(private_api, caplog):
    client, _ = private_api

    def fail(*args):
        raise RuntimeError(SENTINEL)

    client.app.state.service.coverage = fail
    with caplog.at_level(logging.ERROR, logger="hachi.api"):
        response = client.get(f"/v1/subjects/{SENTINEL}/coverage")
    assert response.status_code == 500 and SENTINEL not in response.text
    assert SENTINEL not in caplog.text


def test_cross_subject_resolution_cannot_reference_another_subject(private_api):
    client, _ = private_api
    body = {"schema_version": "0.1", "entries": [ONSET]}
    assert client.post("/v1/subjects/synthetic-a/observations", json=body).status_code == 201
    resolution = {
        "kind": "symptom_resolution",
        "entry_id": "synthetic-resolution",
        "entered_at_utc": "2026-09-05T08:00:00Z",
        "onset_entry_id": SENTINEL,
        "resolved_earliest_utc": "2026-09-04T00:00:00Z",
        "resolved_latest_utc": "2026-09-05T00:00:00Z",
    }
    response = client.post(
        "/v1/subjects/synthetic-b/observations",
        json={"schema_version": "0.1", "entries": [resolution]},
    )
    assert response.status_code == 422
    assert not client.app.state.service.metadata.self_reports("synthetic-b")
    assert len(client.app.state.service.metadata.self_reports("synthetic-a")) == 1


def test_streaming_upload_limit_leaves_no_raw_staging(private_api):
    from dataclasses import replace

    from hachi.data.apple_health import ImportLimits

    client, settings = private_api
    service = client.app.state.service
    service.settings = replace(settings, import_limits=ImportLimits(upload_bytes=64))
    response = client.post(
        "/v1/imports",
        params={
            "subject_id": "synthetic-limit",
            "tz_name": "UTC",
            "source_format": "apple_health_export_xml",
            "data_mode": "synthetic",
        },
        content=iter([b"x" * 40, b"x" * 40]),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 413
    assert not list(settings.workspace.uploads.iterdir())
    assert not list(settings.workspace.imports.iterdir())
    assert not service.metadata.subject_known("synthetic-limit")


def test_failed_file_deletion_keeps_metadata_for_retry(private_api, monkeypatch):
    import hachi.api.service as module

    client, settings = private_api
    uploaded = client.post(
        "/v1/imports",
        params={
            "subject_id": "synthetic-retry",
            "tz_name": "UTC",
            "source_format": "apple_health_export_xml",
            "data_mode": "synthetic",
        },
        content=b"<HealthData></HealthData>",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 202
    service = client.app.state.service
    assert service.runner.wait_idle()
    iid = uploaded.json()["import_id"]
    original = module.remove_tree

    def refused(path):
        raise OSError("generated deletion fault")

    monkeypatch.setattr(module, "remove_tree", refused)
    response = client.delete("/v1/subjects/synthetic-retry", params={"confirm": "synthetic-retry"})
    assert response.status_code == 500
    assert settings.workspace.import_directory(iid).exists()
    assert service.metadata.subject_known("synthetic-retry")
    monkeypatch.setattr(module, "remove_tree", original)
    assert (
        client.delete(
            "/v1/subjects/synthetic-retry", params={"confirm": "synthetic-retry"}
        ).status_code
        == 204
    )
    assert not settings.workspace.import_directory(iid).exists()
    assert not service.metadata.subject_known("synthetic-retry")
