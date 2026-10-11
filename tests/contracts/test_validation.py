"""Boundary rules that the shared fixtures do not exercise directly."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from hachi.contracts import METRICS, Observation, ReportJob, local_day_bounds
from hachi.contracts.base import Contract, IanaTimezone, Identifier, RelativePath, UtcDatetime
from hachi.contracts.metrics import Metric, Unit

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


def test_metric_registry_matches_metric_and_unit_types() -> None:
    assert set(METRICS) == set(get_args(Metric.__value__))
    assert {spec.unit for spec in METRICS.values()} == set(get_args(Unit.__value__))


def test_distinct_measurements_stay_distinct_metrics() -> None:
    assert {"hrv_sdnn", "hrv_rmssd"} <= set(METRICS)
    assert "wrist_temperature_deviation" in METRICS and "body_temperature" in METRICS
    assert "resting_heart_rate_vendor" in METRICS


@pytest.mark.parametrize(
    ("day", "tz", "hours"),
    [
        (date(2026, 10, 10), "America/Los_Angeles", 24),
        (date(2026, 3, 8), "America/Los_Angeles", 23),
        (date(2026, 11, 1), "America/Los_Angeles", 25),
        (date(2026, 10, 4), "Australia/Lord_Howe", 23.5),
        (date(2026, 9, 6), "America/Santiago", 23),  # local midnight does not exist
    ],
)
def test_local_day_bounds_follow_dst(day: date, tz: str, hours: float) -> None:
    start, end = local_day_bounds(day, tz)
    assert start.tzinfo == UTC and end.tzinfo == UTC
    assert end - start == timedelta(hours=hours)


def test_utc_timestamps_normalise_and_reject_other_offsets() -> None:
    adapter = TypeAdapter(UtcDatetime, config=Contract.model_config)
    parsed = adapter.validate_json('"2026-10-10T07:00:00+00:00"')
    assert adapter.dump_json(parsed) == b'"2026-10-10T07:00:00Z"'
    for bad in ('"2026-10-10T07:00:00"', '"2026-10-10T00:00:00-07:00"', "1760079600"):
        with pytest.raises(ValidationError):
            adapter.validate_json(bad)


@pytest.mark.parametrize("value", ["../x", "a/b", ".hidden", "a.b", "", "x" * 129, "a b"])
def test_identifiers_cannot_be_paths(value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Identifier).validate_python(value)


@pytest.mark.parametrize("value", ["/etc/passwd", "a/../b", "a/./b", "a//b", "~/x", ".env"])
def test_relative_paths_stay_under_their_root(value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(RelativePath).validate_python(value)


@pytest.mark.parametrize("value", ["PST", "UTC+2", "Mars/Olympus_Mons", "america/los_angeles"])
def test_timezones_must_be_iana_names(value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(IanaTimezone).validate_python(value)


def test_report_job_result_must_answer_its_request() -> None:
    job = json.loads((FIXTURES / "ReportJob" / "completed.json").read_text())
    job["result"]["subject_id"] = "synthetic-002"
    with pytest.raises(ValidationError, match="must answer the request"):
        ReportJob.model_validate_json(json.dumps(job))


def test_contract_models_are_immutable() -> None:
    job = ReportJob.model_validate_json((FIXTURES / "ReportJob" / "queued.json").read_text())
    with pytest.raises(ValidationError):
        job.state = "completed"  # type: ignore[misc]


def test_python_callers_get_the_same_rules() -> None:
    raw = json.loads((FIXTURES / "Observation" / "heart-rate-sample.json").read_text())
    raw.update(
        start_utc=datetime(2026, 10, 9, 21, tzinfo=UTC),
        end_utc=datetime(2026, 10, 9, 21, tzinfo=UTC),
        available_at_utc=datetime(2026, 10, 9, 20, tzinfo=UTC),
    )
    with pytest.raises(ValidationError, match="available before it starts"):
        Observation.model_validate(raw)
