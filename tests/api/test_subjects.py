"""Coverage, self-reports, scenarios, deletion, health and the request boundary."""

from hachi.contracts.api import ApiError, Coverage, HealthStatus, SelfReportHistory
from hachi.contracts.results import ReportResult

from .conftest import hourly_export, private_files, upload, wait

ONSET = {
    "kind": "symptom_onset",
    "entry_id": "onset-1",
    "entered_at_utc": "2026-09-02T08:00:00Z",
    "onset_earliest_utc": "2026-09-01T20:00:00Z",
    "onset_latest_utc": "2026-09-02T06:00:00Z",
    "symptoms": ["cough", "fatigue"],
    "severity": 2,
}
SCENARIO = {
    "schema_version": "0.1",
    "subject_id": "synthetic-001",
    "tz_name": "America/Los_Angeles",
    "schedules": [
        {
            "schedule_id": "early",
            "bedtime_local": "2026-10-10T22:00:00",
            "wake_time_local": "2026-10-11T06:00:00",
        }
    ],
    "assumptions": {"prior_sleep_hours": 7.0, "caffeine": "none", "light_exposure": "not_modeled"},
}


def entries(*items):
    return {"schema_version": "0.1", "entries": list(items)}


def test_snapshot_coverage_respects_as_of(client):
    full = Coverage.model_validate_json(client.get("/v1/subjects/p01/coverage").content)
    assert full.history == "sufficient" and full.data_mode == "synthetic"
    assert full.dataset_snapshot is not None and full.dataset_snapshot.dataset_id == "pmdata"
    heart = next(m for m in full.metrics if m.metric == "heart_rate")
    assert heart.unit == "bpm" and heart.source_kinds == ["watch"]
    assert heart.longest_gap_hours >= 1  # the synthetic watch is off 13:00-14:00 UTC
    support = {t.task: t for t in full.task_support}
    assert support["physiology_forecast"].supported
    assert support["illness_onset"].reason_code == "NO_VALIDATED_ILLNESS_ARTIFACT"

    early = client.get("/v1/subjects/p01/coverage", params={"as_of": "2020-03-28T06:00:00Z"})
    early = Coverage.model_validate_json(early.content)
    assert early.span_end_utc <= early.span_start_utc.replace(day=28, hour=6)
    assert early.history == "insufficient"
    assert {t.task: t for t in early.task_support}["physiology_forecast"].reason_code == (
        "INSUFFICIENT_HISTORY"
    )
    sparse = Coverage.model_validate_json(client.get("/v1/subjects/p02/coverage").content)
    assert "heart_rate" not in {m.metric for m in sparse.metrics}
    assert {t.task: t for t in sparse.task_support}["physiology_forecast"].reason_code == (
        "METRIC_NOT_OBSERVED"
    )
    naive = client.get("/v1/subjects/p01/coverage", params={"as_of": "2020-03-28T06:00:00"})
    assert naive.status_code == 422
    assert client.get("/v1/subjects/nobody/coverage").status_code == 404


def test_empty_and_failed_histories(client):
    response = upload(client, b"<HealthData></HealthData>")
    wait(client)
    assert client.get(f"/v1/imports/{response.json()['import_id']}").json()["state"] == (
        "succeeded"
    )
    empty = Coverage.model_validate_json(
        client.get("/v1/subjects/synthetic-apple-001/coverage").content
    )
    assert empty.history == "empty" and empty.metrics == [] and empty.span_start_utc is None
    upload(client, b"<HealthData", subject="synthetic-failed")
    wait(client)
    failed = client.get("/v1/subjects/synthetic-failed/coverage").json()
    assert failed["history"] == "empty" and failed["dataset_snapshot"] is None


def test_self_reports_are_persisted_idempotently(client, open_client, make_settings):
    stored = client.post("/v1/subjects/synthetic-001/observations", json=entries(ONSET))
    assert stored.status_code == 201
    assert (
        client.post("/v1/subjects/synthetic-001/observations", json=entries(ONSET)).status_code
        == 200
    )
    changed = client.post(
        "/v1/subjects/synthetic-001/observations", json=entries(ONSET | {"severity": 3})
    )
    assert changed.status_code == 409
    assert changed.json()["field_issues"][0]["path"] == "body.entries.0.entry_id"
    orphan = {
        "kind": "symptom_resolution",
        "entry_id": "resolved-1",
        "entered_at_utc": "2026-09-05T08:00:00Z",
        "onset_entry_id": "never-recorded",
        "resolved_earliest_utc": "2026-09-04T00:00:00Z",
        "resolved_latest_utc": "2026-09-05T00:00:00Z",
    }
    assert (
        client.post("/v1/subjects/synthetic-001/observations", json=entries(orphan)).status_code
        == 422
    )
    resolution = orphan | {"onset_entry_id": "onset-1"}
    assert (
        client.post("/v1/subjects/synthetic-001/observations", json=entries(resolution)).status_code
        == 201
    )
    backdated = ONSET | {"entry_id": "onset-2", "entered_at_utc": "2026-09-01T00:00:00Z"}
    rejected = client.post("/v1/subjects/synthetic-001/observations", json=entries(backdated))
    assert rejected.status_code == 422  # an entry cannot precede the event it describes
    history = SelfReportHistory.model_validate_json(
        client.get("/v1/subjects/synthetic-001/observations").content
    )
    assert [e.entry_id for e in history.entries] == ["onset-1", "resolved-1"]
    assert history.subject_id == "synthetic-001"
    empty = client.get("/v1/subjects/p01/observations").json()
    assert empty["entries"] == []  # a known subject with no entries is an empty history
    assert client.get("/v1/subjects/nobody/observations").status_code == 404

    client.__exit__(None, None, None)
    reopened = open_client(make_settings())  # persisted across restarts
    assert len(reopened.app.state.service.metadata.self_reports("synthetic-001")) == 2


def test_scenarios_are_unavailable_until_the_simulator_is_served(client):
    response = client.post("/v1/scenarios", json=SCENARIO)
    assert response.status_code == 200
    result = ReportResult.model_validate_json(response.content).root
    assert (result.status, result.task, result.reason_code) == (
        "unavailable",
        "alertness",
        "NO_ARTIFACT_FOR_TASK",
    )
    assert result.data_mode == "synthetic" and result.provenance is None
    # #15's rule: as_of is the earliest bedtime, resolved in the request's timezone (PDT).
    assert result.as_of.isoformat() == "2026-10-11T05:00:00+00:00"
    wake = SCENARIO["schedules"][0] | {"wake_time_local": "2026-10-10T21:00:00"}
    assert client.post("/v1/scenarios", json=SCENARIO | {"schedules": [wake]}).status_code == 422
    gap = SCENARIO["schedules"][0] | {"bedtime_local": "2026-03-08T02:30:00"}
    assert client.post("/v1/scenarios", json=SCENARIO | {"schedules": [gap]}).status_code == 422


def test_deletion_requires_confirmation_and_removes_private_data(client, make_settings):
    response = upload(client, hourly_export(30))
    import_id = response.json()["import_id"]
    wait(client)
    client.post("/v1/subjects/synthetic-apple-001/observations", json=entries(ONSET))
    report = {
        "schema_version": "0.1",
        "subject_id": "synthetic-apple-001",
        "as_of": "2026-09-02T12:00:00Z",
        "task": "anomaly",
    }
    client.post("/v1/reports", json=report)
    wait(client)
    unconfirmed = client.delete("/v1/subjects/synthetic-apple-001")
    assert unconfirmed.status_code == 422
    wrong = client.delete("/v1/subjects/synthetic-apple-001", params={"confirm": "p01"})
    assert wrong.status_code == 422
    done = client.delete(
        "/v1/subjects/synthetic-apple-001", params={"confirm": "synthetic-apple-001"}
    )
    assert done.status_code == 204
    directory = make_settings().workspace.import_directory(import_id)
    assert not directory.exists() and private_files(make_settings().workspace.imports) == []
    assert client.get(f"/v1/imports/{import_id}").status_code == 404
    assert client.get("/v1/subjects/synthetic-apple-001/coverage").status_code == 404
    assert client.delete("/v1/subjects/nobody", params={"confirm": "nobody"}).status_code == 404


def test_failed_file_removal_keeps_records_so_deletion_can_be_retried(
    client, make_settings, monkeypatch
):
    import hachi.api.service as service_module

    response = upload(client, hourly_export(30))
    import_id = response.json()["import_id"]
    wait(client)
    directory = make_settings().workspace.import_directory(import_id)
    assert directory.exists()

    real_remove = service_module.remove_tree

    def failing_remove(path):
        raise PermissionError("simulated: file still open elsewhere")

    monkeypatch.setattr(service_module, "remove_tree", failing_remove)
    confirm = {"confirm": "synthetic-apple-001"}
    failed = client.delete("/v1/subjects/synthetic-apple-001", params=confirm)
    assert failed.status_code == 500 and failed.json()["error_code"] == "INTERNAL_ERROR"
    assert "Retry" in failed.json()["message"]
    # Nothing was orphaned: the records still name the import and its files remain.
    assert client.get(f"/v1/imports/{import_id}").json()["state"] == "succeeded"
    assert directory.exists()

    monkeypatch.setattr(service_module, "remove_tree", real_remove)
    retried = client.delete("/v1/subjects/synthetic-apple-001", params=confirm)
    assert retried.status_code == 204
    assert not directory.exists()
    assert client.get(f"/v1/imports/{import_id}").status_code == 404


def test_writes_wait_out_a_deletion_in_progress(client):
    service = client.app.state.service
    client.post("/v1/subjects/synthetic-001/observations", json=entries(ONSET))
    service._deleting.add("synthetic-001")
    try:
        blocked = client.post(
            "/v1/subjects/synthetic-001/observations",
            json=entries(ONSET | {"entry_id": "onset-2"}),
        )
        assert blocked.status_code == 409 and blocked.json()["error_code"] == "CONFLICT"
        twice = client.delete("/v1/subjects/synthetic-001", params={"confirm": "synthetic-001"})
        assert twice.status_code == 409
        assert upload(client, hourly_export(30), subject="synthetic-001").status_code == 409
        assert private_files(service.workspace.imports) == []  # refused before any file
    finally:
        service._deleting.discard("synthetic-001")
    done = client.delete("/v1/subjects/synthetic-001", params={"confirm": "synthetic-001"})
    assert done.status_code == 204


def test_health_and_request_boundary(client, open_client):
    health = HealthStatus.model_validate_json(client.get("/healthz").content)
    assert health.status == "ok" and len(health.artifacts) == 1 and health.git_sha == "a" * 40
    traced = client.get("/healthz", headers={"X-Request-Id": "trace-123"})
    assert traced.headers["x-request-id"] == "trace-123"
    missing = client.get("/v1/imports/imp-missing")
    problem = ApiError.model_validate_json(missing.content)
    assert problem.request_id == missing.headers["x-request-id"]
    assert client.get("/v1/nothing").json()["error_code"] == "NOT_FOUND"
    assert client.put("/healthz").status_code == 405
    rebinding = client.get("/healthz", headers={"Host": "attacker.example"})
    assert rebinding.status_code == 400 and rebinding.json()["error_code"] == "VALIDATION_FAILED"
    preflight = client.options(
        "/v1/reports",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"
    foreign = client.options(
        "/v1/reports",
        headers={"Origin": "https://attacker.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in foreign.headers
