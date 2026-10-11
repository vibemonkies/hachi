"""#15's sleep scenarios over POST /v1/scenarios: a synchronous, labelled simulation."""

import hashlib
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from hachi.api.scenarios import CONFIG_PATH, REQUIREMENT, load_scenario_model
from hachi.contracts.api import ApiError, Coverage
from hachi.contracts.base import ArtifactRef
from hachi.contracts.results import ReportResult

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
FIXTURE = FIXTURES / "ScenarioRequest" / "compare-two-bedtimes.json"
REQUEST = json.loads(FIXTURE.read_text())


def assume(**changes):
    return REQUEST | {"assumptions": REQUEST["assumptions"] | changes}


def schedule(schedule_id, bedtime, wake):
    return {"schedule_id": schedule_id, "bedtime_local": bedtime, "wake_time_local": wake}


def with_schedules(*schedules, **changes):
    return REQUEST | {"schedules": list(schedules)} | changes


def test_a_scenario_is_a_synchronous_labelled_simulation(client):
    response = client.post("/v1/scenarios", json=REQUEST)
    assert response.status_code == 200
    result = ReportResult.model_validate_json(response.content).root
    assert (result.status, result.task) == ("ok", "alertness")
    assert (result.alertness.mode, result.alertness.validation) == ("simulation", None)
    assert result.data_mode == "synthetic"
    assert result.provenance.dataset_snapshot is None  # the simulation's contract exemption
    assert result.provenance.artifact == load_scenario_model().ref
    assert result.alertness.assumptions.model_dump() == REQUEST["assumptions"]
    assert "not probability, KSS, PVT" in result.alertness.model_description
    # as_of is the earliest bedtime (22:30 PDT); curves start at each wake, every 30 min.
    assert result.as_of.isoformat() == "2026-10-11T05:30:00+00:00"
    early, late = result.alertness.curves
    assert (early.schedule_id, late.schedule_id) == ("early", "late")
    assert early.points[0].time_utc.isoformat() == "2026-10-11T13:30:00+00:00"
    gaps = {b.time_utc - a.time_utc for a, b in zip(early.points, early.points[1:], strict=False)}
    assert max(gaps) == timedelta(minutes=30)
    assert all(0 <= p.value <= 1 for c in result.alertness.curves for p in c.points)
    again = ReportResult.model_validate_json(client.post("/v1/scenarios", json=REQUEST).content)
    assert again.root.report_id == result.report_id
    assert again.root.alertness.curves == result.alertness.curves  # deterministic
    # Nothing is read about or stored for the subject.
    assert not client.app.state.service.metadata.subject_known(REQUEST["subject_id"])


def test_the_api_answers_exactly_what_15s_demo_computes(client, tmp_path):
    output = tmp_path / "demo"
    subprocess.run(
        [sys.executable, "-I", "-m", "hachi.scenarios.demo", "--request", str(FIXTURE),
         "--model", str(CONFIG_PATH), "--output", str(output)],
        check=True, capture_output=True,
    )  # fmt: skip
    demo = json.loads((output / "result.json").read_text())
    served = client.post("/v1/scenarios", json=REQUEST).json()
    bundle = hashlib.sha256((output / "model-artifact.json").read_bytes()).hexdigest()
    assert served["provenance"]["artifact"]["artifact_sha256"] == bundle
    assert served["provenance"] == demo["provenance"]
    assert served["alertness"] == demo["alertness"]
    for key in ("as_of", "data_mode", "status", "task", "subject_id"):
        assert served[key] == demo[key]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(with_schedules(schedule("long", "2026-10-10T20:00:00", "2026-10-11T12:00:00")),
                     id="exactly-16h"),
        pytest.param(with_schedules(*(schedule(f"s{i}", f"2026-10-10T2{i}:00:00",
                                               f"2026-10-11T0{6 + i}:00:00") for i in range(4))),
                     id="four-schedules"),
        pytest.param(with_schedules(schedule("fold", "2026-11-01T01:30:00", "2026-11-01T08:00:00")),
                     id="ambiguous-fall-back-time"),
        pytest.param(assume(prior_sleep_hours=0), id="no-prior-sleep"),
        pytest.param(assume(prior_sleep_hours=24), id="all-day-prior-sleep"),
    ],
)  # fmt: skip
def test_boundary_schedules_are_simulated(client, body):
    response = client.post("/v1/scenarios", json=body)
    assert response.status_code == 200, response.text
    assert ReportResult.model_validate_json(response.content).root.status == "ok"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(with_schedules(schedule("w", "2026-10-10T22:00:00", "2026-10-10T21:00:00")),
                     id="wake-before-bedtime"),
        pytest.param(with_schedules(schedule("z", "2026-10-10T22:00:00", "2026-10-10T22:00:00")),
                     id="no-sleep"),
        pytest.param(with_schedules(schedule("l", "2026-10-10T20:00:00", "2026-10-11T12:01:00")),
                     id="over-16h"),
        pytest.param(with_schedules(*(schedule(f"s{i}", "2026-10-10T22:00:00",
                                               "2026-10-11T06:00:00") for i in range(5))),
                     id="five-schedules"),
        pytest.param(with_schedules(schedule("d", "2026-10-10T22:00:00", "2026-10-11T06:00:00"),
                                    schedule("d", "2026-10-10T23:00:00", "2026-10-11T07:00:00")),
                     id="duplicate-ids"),
        pytest.param(with_schedules(schedule("g", "2026-03-08T02:30:00", "2026-03-08T09:00:00")),
                     id="bedtime-in-dst-gap"),
        pytest.param(with_schedules(schedule("o", "2026-10-10T22:00:00-07:00",
                                             "2026-10-11T06:00:00-07:00")),
                     id="offset-instead-of-local-time"),
        pytest.param(with_schedules(), id="no-schedules"),
        pytest.param(REQUEST | {"tz_name": "Mars/Olympus_Mons"}, id="unknown-timezone"),
        pytest.param(assume(prior_sleep_hours=24.5), id="prior-sleep-over-a-day"),
        pytest.param(assume(caffeine="two cups"), id="unmodeled-caffeine-value"),
        pytest.param({k: v for k, v in REQUEST.items() if k != "assumptions"},
                     id="missing-assumptions"),
        pytest.param(REQUEST | {"measured_alertness": True}, id="unknown-field"),
    ],
)  # fmt: skip
def test_malformed_schedules_are_refused_without_echo(client, body):
    response = client.post("/v1/scenarios", json=body)
    assert response.status_code == 422, response.text
    error = ApiError.model_validate_json(response.content)
    assert error.error_code == "VALIDATION_FAILED"
    assert "two cups" not in response.text and "Mars" not in response.text


@pytest.mark.parametrize(
    "path", sorted((FIXTURES / "invalid" / "ScenarioRequest").glob("*.json")), ids=lambda p: p.stem
)
def test_every_invalid_contract_fixture_is_refused(client, path):
    assert client.post("/v1/scenarios", json=json.loads(path.read_text())).status_code == 422


def test_a_pinned_bundle_is_required_when_the_operator_sets_one(open_client, make_settings):
    served = load_scenario_model().ref
    pinned = open_client(make_settings(scenario_model=served))
    assert pinned.post("/v1/scenarios", json=REQUEST).json()["status"] == "ok"
    other = ArtifactRef(artifact_id="two-process-v1", artifact_sha256="0" * 64)
    mismatched = open_client(make_settings(scenario_model=other))
    result = ReportResult.model_validate_json(
        mismatched.post("/v1/scenarios", json=REQUEST).content
    ).root
    assert (result.status, result.reason_code) == ("unavailable", "NO_ARTIFACT_FOR_TASK")
    assert result.requirements == [REQUIREMENT] and result.data_mode == "synthetic"
    assert any("scenario model" in p for p in mismatched.app.state.service.catalog.problems)


def test_coverage_reports_alertness_supported_while_the_model_is_served(client):
    coverage = Coverage.model_validate_json(client.get("/v1/subjects/p01/coverage").content)
    alertness = next(t for t in coverage.task_support if t.task == "alertness")
    assert (alertness.supported, alertness.reason_code) == (True, None)
