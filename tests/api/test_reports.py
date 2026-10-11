"""Report jobs: served-artifact forecasts agree with direct inference; gaps are unavailable."""

from datetime import UTC, datetime

from hachi.contracts.api import ReportJob
from hachi.contracts.results import ReportResult

from .conftest import upload, wait

AS_OF = "2020-03-29T12:00:00Z"


def forecast(subject="p01", as_of=AS_OF, **changes):
    body = {
        "schema_version": "0.1",
        "subject_id": subject,
        "as_of": as_of,
        "task": "physiology_forecast",
        "resolution": "hour",
        "horizon_hours": 24,
        "metrics": ["heart_rate"],
    }
    body.update(changes)
    return body


def run(client, body) -> ReportJob:
    response = client.post("/v1/reports", json=body)
    assert response.status_code in (200, 202), response.text
    wait(client)
    job = ReportJob.model_validate_json(
        client.get(f"/v1/reports/{response.json()['report_id']}").content
    )
    assert job.state == "completed"
    return job


def test_forecast_matches_direct_inference_with_provenance(client, served):
    from hachi.api.handoff import Tally, api_points, direct_inference, expected_points

    job = run(client, forecast())
    result = job.result.root
    assert result.status == "ok", result
    assert result.provenance.artifact == served[1]
    assert result.provenance.dataset_snapshot.dataset_id == "pmdata"
    assert result.data_mode == "synthetic"
    assert result.git_sha == "a" * 40
    series = result.forecast.series[0]
    assert series.metric == "heart_rate" and series.unit == "bpm"
    assert series.points[0].interval_start_utc == datetime(2020, 3, 29, 12, tzinfo=UTC)
    # #9's baselines give medians only: a point-only series, with no band and no coverage claim.
    assert series.interval_calibration == "none" and series.nominal_coverage is None
    assert all(p.lower is None and p.upper is None for p in series.points)
    assert "UNCALIBRATED_INTERVALS" not in {w.code for w in result.warnings}

    service = client.app.state.service
    artifact = service.catalog.artifacts[0]
    subject = service.catalog.subject("p01", service.metadata, service.workspace)
    direct = direct_inference(artifact, subject, result.as_of, 24)
    tally = Tally()
    tally.add(api_points(job), expected_points(result.as_of, direct))
    assert tally.agrees and tally.compared == len(series.points) > 0
    assert tally.max_difference == 0.0


def test_declared_intervals_are_shown_as_uncalibrated(client):
    import dataclasses

    from hachi.evaluation import ForecastEstimate

    service = client.app.state.service
    served = service.catalog.artifacts[0]

    class WithIntervals:
        """The frozen baseline plus a fixed band, standing in for a quantile model."""

        config, fit_as_of, model_id = served.model.config, served.model.fit_as_of, "banded"

        def predict(self, request):
            return tuple(
                None
                if e is None
                else ForecastEstimate(median=e.median, lower=e.median - 5, upper=e.median + 5)
                for e in served.model.predict(request)
            )

    serving = served.serving.model_copy(update={"interval_nominal_coverage": 0.8})
    banded = dataclasses.replace(served, model=WithIntervals(), serving=serving)
    service.catalog.artifacts = (banded,)
    series = run(client, forecast()).result.root.forecast.series[0]
    assert (series.interval_calibration, series.nominal_coverage) == ("uncalibrated", 0.8)
    assert all(p.lower == p.median - 5 and p.upper == p.median + 5 for p in series.points)
    warnings = run(client, forecast()).result.root.warnings
    assert "UNCALIBRATED_INTERVALS" in {w.code for w in warnings}

    undeclared = dataclasses.replace(banded, serving=served.serving)  # no declared coverage
    service.catalog.artifacts = (undeclared,)
    point_only = run(client, forecast(as_of="2020-03-29T14:00:00Z")).result.root.forecast
    assert point_only.series[0].interval_calibration == "none"
    assert point_only.series[0].points[0].lower is None


def test_identical_requests_are_idempotent(client):
    first = client.post("/v1/reports", json=forecast())
    assert first.status_code == 202 and first.json()["state"] == "queued"
    wait(client)
    again = client.post("/v1/reports", json=forecast())
    assert again.status_code == 200
    assert again.json()["report_id"] == first.json()["report_id"]
    assert again.json()["state"] == "completed"
    other = client.post("/v1/reports", json=forecast(as_of="2020-03-29T13:00:00Z"))
    assert other.status_code == 202 and other.json()["report_id"] != first.json()["report_id"]


def test_as_of_filtering_uses_only_data_available_by_the_cutoff(client):
    early = run(client, forecast(as_of="2020-03-29T05:00:00Z")).result.root
    late = run(client, forecast(as_of="2020-03-29T05:59:59Z")).result.root
    # Both read up to 05:00: the bin ending 06:00 is not final at 05:59:59.
    assert early.forecast.series[0].points[0].median == late.forecast.series[0].points[0].median
    assert late.forecast.series[0].points[0].interval_start_utc.hour == 6


def test_sparse_history_is_unavailable_not_guessed(client):
    result = run(client, forecast(as_of="2020-03-28T06:00:00Z")).result.root
    assert result.status == "unavailable"
    assert result.reason_code == "INSUFFICIENT_HISTORY"
    assert result.provenance.artifact is not None
    assert 0 < result.provenance.feature_coverage[0].coverage < 0.5

    no_heart_rate = run(client, forecast(subject="p02")).result.root
    assert no_heart_rate.status == "unavailable"
    assert no_heart_rate.reason_code == "INSUFFICIENT_HISTORY"


def test_as_of_before_the_model_was_fitted_is_refused(client):
    result = run(client, forecast(as_of="2020-03-27T23:00:00Z")).result.root
    assert result.status == "error" and result.error_code == "ARTIFACT_INCOMPATIBLE"


def test_metrics_without_an_artifact(client):
    result = run(client, forecast(metrics=["heart_rate", "steps"])).result.root
    assert result.status == "ok"
    assert [m.metric for m in result.forecast.unavailable_metrics] == ["steps"]
    only_steps = run(client, forecast(metrics=["steps"])).result.root
    assert only_steps.status == "unavailable" and only_steps.reason_code == "NO_ARTIFACT_FOR_TASK"
    daily = {k: v for k, v in forecast().items() if k != "horizon_hours"} | {"resolution": "day"}
    assert run(client, daily).result.root.reason_code == "NO_ARTIFACT_FOR_TASK"


def test_tasks_without_validated_models_are_unavailable(client):
    base = {"schema_version": "0.1", "subject_id": "p01", "as_of": AS_OF}
    anomaly = run(client, base | {"task": "anomaly"}).result.root
    assert (anomaly.status, anomaly.reason_code) == ("unavailable", "NO_ARTIFACT_FOR_TASK")
    illness = run(client, base | {"task": "illness_onset", "horizon_hours": 48}).result.root
    assert illness.reason_code == "NO_VALIDATED_ILLNESS_ARTIFACT"
    recovery = run(client, base | {"task": "recovery", "episode_id": "ep-1"}).result.root
    assert recovery.reason_code == "NO_ONGOING_EPISODE"
    for result in (anomaly, illness, recovery):
        ReportResult.model_validate_json(ReportResult(result).model_dump_json())
        assert result.requirements and result.provenance.dataset_snapshot is not None


def test_self_reported_episodes_shape_illness_and_recovery(client):
    entry = {
        "kind": "symptom_onset",
        "entry_id": "onset-1",
        "entered_at_utc": "2020-03-29T08:00:00Z",
        "onset_earliest_utc": "2020-03-28T20:00:00Z",
        "onset_latest_utc": "2020-03-29T06:00:00Z",
        "symptoms": ["cough"],
        "severity": 1,
    }
    stored = client.post(
        "/v1/subjects/p01/observations", json={"schema_version": "0.1", "entries": [entry]}
    )
    assert stored.status_code == 201
    base = {"schema_version": "0.1", "subject_id": "p01", "as_of": AS_OF}
    illness = run(client, base | {"task": "illness_onset", "horizon_hours": 24}).result.root
    assert illness.reason_code == "ONGOING_EPISODE"
    recovery = run(client, base | {"task": "recovery", "episode_id": "onset-1"}).result.root
    assert recovery.reason_code == "NO_VALIDATED_RECOVERY_ARTIFACT"
    before = base | {"as_of": "2020-03-29T07:00:00Z"}  # entered after this as_of
    late = run(client, before | {"task": "recovery", "episode_id": "onset-1"}).result.root
    assert late.reason_code == "NO_ONGOING_EPISODE"


def test_apple_import_cannot_feed_an_hourly_feature_model(client):
    from .conftest import hourly_export

    assert upload(client, hourly_export(72)).status_code == 202
    wait(client)
    result = run(
        client, forecast(subject="synthetic-apple-001", as_of="2026-09-03T12:00:00Z")
    ).result.root
    assert result.status == "unavailable" and result.reason_code == "NO_ARTIFACT_FOR_TASK"
    assert result.data_mode == "synthetic"


def test_request_validation(client):
    future = forecast(as_of="2999-01-01T00:00:00Z")
    assert client.post("/v1/reports", json=future).json()["error_code"] == "VALIDATION_FAILED"
    unknown = client.post("/v1/reports", json=forecast(subject="nobody"))
    assert unknown.status_code == 404 and unknown.json()["error_code"] == "NOT_FOUND"
    version = client.post("/v1/reports", json=forecast(schema_version="0.2"))
    assert version.status_code == 400
    assert version.json()["error_code"] == "SCHEMA_VERSION_UNSUPPORTED"
    for bad in (
        forecast(as_of="2020-03-29T12:00:00"),  # naive
        forecast(as_of="2020-03-29T12:00:00+02:00"),  # not UTC
        forecast(horizon_hours="24"),  # strings are never coerced
        forecast(extra="field"),
        forecast(task="diagnosis"),
        forecast(subject="../../etc"),
    ):
        response = client.post("/v1/reports", json=bad)
        assert response.status_code == 422, bad
        problem = response.json()
        assert problem["error_code"] == "VALIDATION_FAILED" and problem["field_issues"]
        assert "../../etc" not in response.text
    not_json = client.post(
        "/v1/reports", content=b"{", headers={"Content-Type": "application/json"}
    )
    assert not_json.status_code == 422
    plain = client.post("/v1/reports", content=b"{}", headers={"Content-Type": "text/plain"})
    assert plain.status_code == 415 and plain.json()["error_code"] == "VALIDATION_FAILED"
    assert client.get("/v1/reports/rep-unknown").status_code == 404
    assert client.get("/v1/reports/..%2F..%2Fetc").status_code in (404, 422)
