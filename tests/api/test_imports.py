"""Uploads stream to private storage, run as jobs, and survive malformed input and restarts."""

from hachi.contracts.api import ImportStatus

from .conftest import (
    export_xml,
    heart_rate_record,
    hourly_export,
    private_files,
    upload,
    wait,
    zipped,
)


def status(client, import_id: str) -> ImportStatus:
    response = client.get(f"/v1/imports/{import_id}")
    assert response.status_code == 200, response.text
    return ImportStatus.model_validate_json(response.content)


def test_upload_runs_to_success_with_counts_and_coverage(client, make_settings):
    response = upload(client, hourly_export(48))
    assert response.status_code == 202
    created = ImportStatus.model_validate_json(response.content)
    assert created.state == "pending" and created.counts is None
    wait(client)
    done = status(client, created.import_id)
    assert done.state == "succeeded" and done.failure is None
    assert done.counts.records_seen == done.counts.records_accepted == 48
    workspace = make_settings().workspace
    # The raw upload is gone; only the private snapshot keeps records.
    assert private_files(workspace.import_directory(created.import_id)) == ["snapshot.sqlite3"]
    assert private_files(workspace.uploads) == []
    coverage = client.get("/v1/subjects/synthetic-apple-001/coverage").json()
    assert coverage["history"] == "sufficient" and coverage["data_mode"] == "synthetic"
    assert [m["metric"] for m in coverage["metrics"]] == ["heart_rate"]
    assert coverage["dataset_snapshot"]["dataset_id"] == "synthetic-apple-health-export"
    zipped_upload = upload(
        client,
        zipped({"apple_health_export/export.xml": hourly_export(30)}),
        subject="synthetic-apple-002",
        source_format="apple_health_export_zip",
    )
    assert zipped_upload.status_code == 202
    wait(client)
    assert status(client, zipped_upload.json()["import_id"]).state == "succeeded"


def test_identical_uploads_are_idempotent(client):
    body = hourly_export(30)
    first = upload(client, body)
    wait(client)
    again = upload(client, body)
    assert again.status_code == 200 and again.json()["import_id"] == first.json()["import_id"]
    other_zone = upload(client, body, tz_name="Europe/Oslo")
    assert other_zone.status_code == 202
    assert other_zone.json()["import_id"] != first.json()["import_id"]


def test_record_problems_are_counted_not_echoed(client):
    rows = [
        heart_rate_record("2026-09-01 00:00:00 +0000"),
        heart_rate_record("2026-09-01 01:00:00 +0000", unit="unknown"),
        heart_rate_record("2026-09-01 02:00:00 +0000", value="NaN"),
        heart_rate_record("not-a-date"),
    ]
    response = upload(client, export_xml(rows))
    wait(client)
    done = status(client, response.json()["import_id"])
    assert done.state == "succeeded"
    assert done.counts.records_seen == 4 and done.counts.bucket_total() == 4
    assert {(i.disposition, i.code) for i in done.record_issues} == {
        ("quarantined", "UNKNOWN_UNIT"),
        ("rejected", "VALUE_OUT_OF_RANGE"),
        ("rejected", "INVALID_TIMESTAMP"),
    }
    assert "Synthetic Apple Watch" not in client.get(f"/v1/imports/{done.import_id}").text


def test_malformed_exports_fail_with_actionable_reasons(client, make_settings):
    cases = {
        "MALFORMED_XML": (b"<HealthData><Record", "apple_health_export_xml"),
        "NOT_AN_APPLE_HEALTH_EXPORT": (b"<Other/>", "apple_health_export_xml"),
        "ARCHIVE_UNSAFE": (zipped({"../export.xml": hourly_export(2)}), "apple_health_export_zip"),
    }
    entity = b'<!DOCTYPE HealthData [<!ENTITY x "y">]><HealthData>&x;</HealthData>'
    cases["MALFORMED_XML "] = (entity, "apple_health_export_xml")
    for index, (code, (body, source_format)) in enumerate(cases.items()):
        response = upload(
            client, body, subject=f"synthetic-bad-{index}", source_format=source_format
        )
        assert response.status_code == 202
        wait(client)
        failed = status(client, response.json()["import_id"])
        assert failed.state == "failed" and failed.counts is None
        assert failed.failure.error_code == code.strip() and failed.failure.action
    workspace = make_settings().workspace
    for name in private_files(workspace.imports):
        assert private_files(workspace.imports / name) == []  # no partial snapshot or upload


def test_upload_requests_are_validated_before_storage(client, open_client, make_settings):
    body = hourly_export(2)
    for params in (
        {"subject_id": "../../etc"},
        {"subject_id": "a/b"},
        {"tz_name": "PST"},
        {"source_format": "pmdata_archive"},
        {"data_mode": "fake"},
        {"path": "/etc/passwd"},
    ):
        response = upload(client, body, **params)
        assert response.status_code == 422, params
        assert response.json()["error_code"] == "VALIDATION_FAILED"
    plain = client.post(
        "/v1/imports",
        params={
            "subject_id": "synthetic-apple-001",
            "tz_name": "UTC",
            "source_format": "apple_health_export_xml",
            "data_mode": "synthetic",
        },
        content=body,
        headers={"Content-Type": "text/plain"},
    )
    assert plain.status_code == 415
    assert upload(client, b"").json()["error_code"] == "VALIDATION_FAILED"
    taken = upload(client, body, subject="p01")
    assert taken.status_code == 409 and taken.json()["error_code"] == "CONFLICT"

    from hachi.data.apple_health import ImportLimits

    small = open_client(make_settings(import_limits=ImportLimits(upload_bytes=64)))
    too_big = upload(small, hourly_export(10))
    assert too_big.status_code == 413 and too_big.json()["error_code"] == "PAYLOAD_TOO_LARGE"
    assert private_files(make_settings().workspace.uploads) == []


def test_interrupted_imports_fail_cleanly_and_can_be_retried(open_client, make_settings):
    settings = make_settings()
    first = open_client(settings)
    body = hourly_export(30)
    service = first.app.state.service
    service.runner.stop()  # nothing runs: the upload stays queued, as during a crash
    response = upload(first, body)
    pending_id = response.json()["import_id"]
    running = upload(first, hourly_export(31), subject="synthetic-apple-crash")
    running_id = running.json()["import_id"]
    record = service.metadata.get_import(running_id)
    service.metadata.update_import(record.status.model_copy(update={"state": "running"}))
    directory = settings.workspace.import_directory(running_id)
    (directory / "snapshot.sqlite3").write_bytes(b"partial")
    first.__exit__(None, None, None)

    second = open_client(settings)  # restart: recover, then run what is queued
    wait(second)
    interrupted = status(second, running_id)
    assert interrupted.state == "failed"
    assert interrupted.failure.error_code == "INTERNAL_ERROR"
    assert "interrupted" in interrupted.failure.message
    assert not directory.exists()
    assert status(second, pending_id).state == "succeeded"
    retry = upload(second, hourly_export(31), subject="synthetic-apple-crash")
    assert retry.status_code == 202 and retry.json()["import_id"] != running_id
    wait(second)
    assert status(second, retry.json()["import_id"]).state == "succeeded"
