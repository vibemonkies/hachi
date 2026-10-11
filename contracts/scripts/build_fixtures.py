"""Build the synthetic contract fixtures in contracts/fixtures/.

    uv run python contracts/scripts/build_fixtures.py           # write fixtures
    uv run python contracts/scripts/build_fixtures.py --check   # fail if fixtures are stale

Every fixture is synthetic and says so: subject ids start with "synthetic-", datasets and
artifacts are named "synthetic", and documents with a data_mode use "synthetic". Values are
illustrative shapes for UI and API development, not model output or real measurements.

Valid fixtures live in fixtures/<Document>/. Invalid fixtures live in
fixtures/invalid/<Document>/, and fixtures/invalid/expectations.json records the error each
one must produce.
"""

import argparse
import copy
import hashlib
import json
import math
import shutil
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from hachi.contracts import (
    SCHEMA_VERSION,
    Aggregate,
    ApiError,
    Coverage,
    HealthStatus,
    ImportStatus,
    Observation,
    Outcome,
    ReportJob,
    ReportRequest,
    ReportResult,
    RunManifest,
    ScenarioRequest,
    SelfReportRequest,
    SplitManifest,
    local_day_bounds,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

Doc = dict[str, Any]

# --- Shared synthetic identities ------------------------------------------------------------

SUBJECT = "synthetic-001"
TZ = "America/Los_Angeles"
GIT_SHA = "0" * 40
AS_OF = datetime(2026, 10, 10, 7, 0, tzinfo=UTC)  # local midnight, 2026-10-10 in TZ


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def ts(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


DATASET = {
    "dataset_id": "synthetic",
    "dataset_version": "0.1",
    "snapshot_sha256": sha("synthetic-dataset-0.1"),
}
ARTIFACT = {
    "artifact_id": "synthetic-fixture-artifact",
    "artifact_sha256": sha("synthetic-fixture-artifact"),
}
SIM_ARTIFACT = {
    "artifact_id": "synthetic-alertness-simulation",
    "artifact_sha256": sha("synthetic-alertness-simulation"),
}


def result_base(report_id: str, as_of: datetime = AS_OF, **extra: Any) -> Doc:
    return {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "subject_id": SUBJECT,
        "as_of": ts(as_of),
        "data_mode": "synthetic",
        "generated_at_utc": ts(as_of + timedelta(seconds=5)),
        "git_sha": GIT_SHA,
        "warnings": [],
        "replay": None,
        **extra,
    }


def coverage_list(**metrics: float) -> list[Doc]:
    return [{"metric": m, "coverage": c} for m, c in metrics.items()]


# --- Requests -------------------------------------------------------------------------------


def report_requests() -> dict[str, Doc]:
    base = {"schema_version": SCHEMA_VERSION, "subject_id": SUBJECT, "as_of": ts(AS_OF)}
    return {
        "physiology-forecast-hourly": {
            **base,
            "task": "physiology_forecast",
            "resolution": "hour",
            "horizon_hours": 24,
            "metrics": ["heart_rate", "steps"],
        },
        "physiology-forecast-daily": {
            **base,
            "task": "physiology_forecast",
            "resolution": "day",
            "horizon_days": 1,
            "metrics": None,
        },
        "anomaly": {**base, "task": "anomaly"},
        "illness-onset-48h": {**base, "task": "illness_onset", "horizon_hours": 48},
        "recovery": {**base, "task": "recovery", "episode_id": "synthetic-episode-01"},
    }


SCENARIO_ASSUMPTIONS = {
    "prior_sleep_hours": 7.0,
    "caffeine": "none",
    "light_exposure": "not_modeled",
}


def scenario_requests() -> dict[str, Doc]:
    return {
        "compare-two-bedtimes": {
            "schema_version": SCHEMA_VERSION,
            "subject_id": SUBJECT,
            "tz_name": TZ,
            "schedules": [
                {
                    "schedule_id": "early",
                    "bedtime_local": "2026-10-10T22:30:00",
                    "wake_time_local": "2026-10-11T06:30:00",
                },
                {
                    "schedule_id": "late",
                    "bedtime_local": "2026-10-11T01:00:00",
                    "wake_time_local": "2026-10-11T09:00:00",
                },
            ],
            "assumptions": SCENARIO_ASSUMPTIONS,
        }
    }


def self_report_requests() -> dict[str, Doc]:
    day = timedelta(days=1)
    onset = AS_OF - 3 * day
    return {
        "symptoms-tests-and-alertness": {
            "schema_version": SCHEMA_VERSION,
            "entries": [
                {
                    "kind": "symptom_onset",
                    "entry_id": "synthetic-entry-01",
                    "entered_at_utc": ts(onset + timedelta(hours=14)),
                    "onset_earliest_utc": ts(onset),
                    "onset_latest_utc": ts(onset + timedelta(hours=12)),
                    "symptoms": ["sore_throat", "fatigue", "congestion"],
                    "severity": 2,
                },
                {
                    "kind": "symptom_checkin",
                    "entry_id": "synthetic-entry-02",
                    "entered_at_utc": ts(AS_OF - day + timedelta(hours=14)),
                    "period_start_utc": ts(AS_OF - day),
                    "period_end_utc": ts(AS_OF),
                    "symptoms_present": True,
                    "symptoms": ["congestion", "cough"],
                    "severity": 1,
                },
                {
                    "kind": "test_result",
                    "entry_id": "synthetic-entry-03",
                    "entered_at_utc": ts(onset + day + timedelta(hours=10)),
                    "pathogen": "sars_cov_2",
                    "method": "antigen",
                    "result": "negative",
                    "collected_earliest_utc": ts(onset + day + timedelta(hours=8)),
                    "collected_latest_utc": ts(onset + day + timedelta(hours=9)),
                },
                {
                    "kind": "alertness_rating",
                    "entry_id": "synthetic-entry-04",
                    "entered_at_utc": ts(AS_OF - day + timedelta(hours=17, minutes=1)),
                    "rated_at_utc": ts(AS_OF - day + timedelta(hours=17)),
                    "scale": "kss_1_9",
                    "value": 6,
                },
                {
                    "kind": "pvt_result",
                    "entry_id": "synthetic-entry-05",
                    "entered_at_utc": ts(AS_OF - day + timedelta(hours=17, minutes=10)),
                    "started_at_utc": ts(AS_OF - day + timedelta(hours=17, minutes=5)),
                    "duration_seconds": 180,
                    "trials": 31,
                    "mean_reaction_time_ms": 312.5,
                    "lapses": 2,
                },
                {
                    "kind": "confounder",
                    "entry_id": "synthetic-entry-06",
                    "entered_at_utc": ts(onset - day + timedelta(hours=20)),
                    "factor": "intense_exercise",
                    "occurred_earliest_utc": ts(onset - day + timedelta(hours=15)),
                    "occurred_latest_utc": ts(onset - day + timedelta(hours=17)),
                },
                {
                    "kind": "symptom_resolution",
                    "entry_id": "synthetic-entry-07",
                    "entered_at_utc": ts(AS_OF + timedelta(hours=10)),
                    "onset_entry_id": "synthetic-entry-01",
                    "resolved_earliest_utc": ts(AS_OF),
                    "resolved_latest_utc": ts(AS_OF + timedelta(hours=8)),
                },
            ],
        }
    }


# --- Results --------------------------------------------------------------------------------


def hourly_forecast() -> Doc:
    def hr(i: int) -> float:
        return round(64 + 9 * math.sin((i - 9) / 24 * 2 * math.pi), 1)

    def steps(i: int) -> float:
        local_hour = i  # AS_OF is local midnight
        return 0.0 if local_hour < 7 or local_hour >= 23 else float(300 + 40 * (local_hour % 5))

    def points(fn: Callable[[int], float], spread: float, floor: float) -> list[Doc]:
        out = []
        for i in range(24):
            start = AS_OF + timedelta(hours=i)
            median = fn(i)
            out.append(
                {
                    "interval_start_utc": ts(start),
                    "interval_end_utc": ts(start + timedelta(hours=1)),
                    "local_date": None,
                    "median": median,
                    "lower": round(max(floor, median - spread), 1),
                    "upper": round(median + spread, 1),
                }
            )
        return out

    return result_base(
        "synthetic-report-forecast-hourly",
        status="ok",
        task="physiology_forecast",
        provenance={
            "dataset_snapshot": DATASET,
            "artifact": ARTIFACT,
            "feature_coverage": coverage_list(heart_rate=0.92, steps=0.88),
        },
        forecast={
            "resolution": "hour",
            "tz_name": TZ,
            "series": [
                {
                    "metric": "heart_rate",
                    "unit": "bpm",
                    "nominal_coverage": 0.8,
                    "interval_calibration": "uncalibrated",
                    "baseline": {
                        "value": 63.0,
                        "definition": "Train-only personal median of hourly heart rate (synthetic)",
                        "window_start_utc": ts(AS_OF - timedelta(days=28)),
                        "window_end_utc": ts(AS_OF),
                    },
                    "points": points(hr, 7.5, 1.0),
                },
                {
                    "metric": "steps",
                    "unit": "count",
                    "nominal_coverage": 0.8,
                    "interval_calibration": "uncalibrated",
                    "baseline": None,
                    "points": points(steps, 250.0, 0.0),
                },
            ],
            "unavailable_metrics": [{"metric": "hrv_sdnn", "reason_code": "METRIC_NOT_OBSERVED"}],
        },
        warnings=[
            {
                "code": "UNCALIBRATED_INTERVALS",
                "message": "Interval coverage has not been measured on held-out data.",
            }
        ],
    )


def daily_forecast() -> Doc:
    start, end = local_day_bounds(date(2026, 10, 10), TZ)

    def point(median: float, lower: float, upper: float) -> Doc:
        return {
            "interval_start_utc": ts(start),
            "interval_end_utc": ts(end),
            "local_date": "2026-10-10",
            "median": median,
            "lower": lower,
            "upper": upper,
        }

    return result_base(
        "synthetic-report-forecast-daily",
        status="ok",
        task="physiology_forecast",
        provenance={
            "dataset_snapshot": DATASET,
            "artifact": ARTIFACT,
            "feature_coverage": coverage_list(
                resting_heart_rate_vendor=0.97, sleep_asleep_unspecified=0.9
            ),
        },
        forecast={
            "resolution": "day",
            "tz_name": TZ,
            "series": [
                {
                    "metric": "resting_heart_rate_vendor",
                    "unit": "bpm",
                    "nominal_coverage": 0.8,
                    "interval_calibration": "uncalibrated",
                    "baseline": None,
                    "points": [point(58.0, 55.0, 62.0)],
                },
                {
                    "metric": "sleep_asleep_unspecified",
                    "unit": "s",
                    "nominal_coverage": 0.8,
                    "interval_calibration": "uncalibrated",
                    "baseline": None,
                    "points": [point(25200.0, 21600.0, 28800.0)],
                },
            ],
            "unavailable_metrics": [],
        },
    )


def anomaly_timeline(scores: list[float | None], threshold: float) -> list[Doc]:
    days = len(scores)
    out = []
    for i, score in enumerate(scores):
        start = AS_OF - timedelta(days=days - i)
        out.append(
            {
                "interval_start_utc": ts(start),
                "interval_end_utc": ts(start + timedelta(days=1)),
                "score": score,
                "alert": score is not None and score >= threshold,
            }
        )
    return out


ANOMALY_DEFINITION = (
    "Robust z-score of overnight resting heart rate against the trailing 28-day personal "
    "median, using only data available at each cutoff (synthetic fixture)"
)


def anomaly_alert() -> Doc:
    scores = [0.2, -0.4, 0.9, 0.1, -1.1, 0.5, 0.3, -0.2, 0.8, 1.2, 0.6, 1.9, 2.7, 3.4]
    return result_base(
        "synthetic-report-anomaly",
        status="ok",
        task="anomaly",
        provenance={
            "dataset_snapshot": DATASET,
            "artifact": ARTIFACT,
            "feature_coverage": coverage_list(heart_rate=0.95, resting_heart_rate_vendor=1.0),
        },
        anomaly={
            "score_definition": ANOMALY_DEFINITION,
            "alert_state": "alert",
            "score": 3.4,
            "alert_threshold": 3.0,
            "baseline_window_start_utc": ts(AS_OF - timedelta(days=29)),
            "baseline_window_end_utc": ts(AS_OF - timedelta(days=1)),
            "changed_features": [
                {
                    "metric": "resting_heart_rate_vendor",
                    "unit": "bpm",
                    "observed": 66.0,
                    "baseline_median": 58.0,
                    "robust_z": 3.4,
                }
            ],
            "timeline": anomaly_timeline(scores, 3.0),
            "observed_alert_burden": None,
        },
    )


def anomaly_abstained() -> Doc:
    return result_base(
        "synthetic-report-anomaly-sparse",
        status="ok",
        task="anomaly",
        provenance={
            "dataset_snapshot": DATASET,
            "artifact": ARTIFACT,
            "feature_coverage": coverage_list(heart_rate=0.18),
        },
        anomaly={
            "score_definition": ANOMALY_DEFINITION,
            "alert_state": "abstained",
            "score": None,
            "alert_threshold": 3.0,
            "baseline_window_start_utc": ts(AS_OF - timedelta(days=29)),
            "baseline_window_end_utc": ts(AS_OF - timedelta(days=1)),
            "changed_features": [],
            "timeline": anomaly_timeline([None, None, 0.4, None, None], 3.0),
            "observed_alert_burden": None,
        },
        warnings=[
            {
                "code": "SPARSE_HISTORY",
                "message": "Too few overnight readings to estimate a personal baseline.",
            }
        ],
    )


def illness_onset() -> Doc:
    return result_base(
        "synthetic-report-illness",
        status="ok",
        task="illness_onset",
        provenance={
            "dataset_snapshot": DATASET,
            "artifact": ARTIFACT,
            "feature_coverage": coverage_list(heart_rate=0.95, resting_heart_rate_vendor=1.0),
        },
        illness_onset={
            "horizon_hours": 48,
            "onset_probability": 0.12,
            "target_definition": (
                "New symptom onset within 48 hours after as_of, for people without an ongoing "
                "episode (synthetic fixture; no validated illness artifact exists)"
            ),
            "calibration": {"cohort": "synthetic", "version": "0.1", "method": "none (fixture)"},
            "distribution_status": "unknown",
        },
    )


def recovery() -> Doc:
    survival = [(0, 1.0), (1, 0.93), (2, 0.78), (3, 0.6), (5, 0.34), (7, 0.18), (10, 0.08)]
    return result_base(
        "synthetic-report-recovery",
        status="ok",
        task="recovery",
        provenance={
            "dataset_snapshot": DATASET,
            "artifact": ARTIFACT,
            "feature_coverage": coverage_list(resting_heart_rate_vendor=1.0),
        },
        recovery={
            "episode_id": "synthetic-episode-01",
            "endpoint_definition": (
                "Two consecutive symptom-free daily check-ins (synthetic fixture definition)"
            ),
            "survival": [
                {"days_after_as_of": float(d), "probability_still_symptomatic": p}
                for d, p in survival
            ],
            "median_days_after_as_of": 3.5,
            "supported_follow_up_days": 10.0,
        },
    )


def alertness_simulation() -> Doc:
    def curve(schedule_id: str, wake: datetime) -> Doc:
        points = []
        for h in range(0, 17, 2):
            value = 0.55 + 0.3 * math.sin((h - 2) / 16 * math.pi) - 0.02 * h
            points.append({"time_utc": ts(wake + timedelta(hours=h)), "value": round(value, 3)})
        return {"schedule_id": schedule_id, "points": points}

    early_wake = datetime(2026, 10, 11, 13, 30, tzinfo=UTC)  # 06:30 local
    late_wake = datetime(2026, 10, 11, 16, 0, tzinfo=UTC)  # 09:00 local
    return result_base(
        "synthetic-report-alertness",
        status="ok",
        task="alertness",
        provenance={"dataset_snapshot": None, "artifact": SIM_ARTIFACT, "feature_coverage": []},
        alertness={
            "mode": "simulation",
            "model_description": (
                "Placeholder curve shape for UI development. The real simulation's equations "
                "and citation are chosen in the scenarios issue."
            ),
            "scale": {
                "name": "Simulated relative alertness",
                "unit": "relative",
                "minimum": 0.0,
                "maximum": 1.0,
                "higher_is_more_alert": True,
            },
            "tz_name": TZ,
            "assumptions": SCENARIO_ASSUMPTIONS,
            "curves": [curve("early", early_wake), curve("late", late_wake)],
            "validation": None,
        },
    )


def unavailable_illness() -> Doc:
    return result_base(
        "synthetic-report-unavailable",
        status="unavailable",
        task="illness_onset",
        reason_code="NO_VALIDATED_ILLNESS_ARTIFACT",
        requirements=["Labeled cohort evaluation and calibrated artifact"],
        provenance=None,
    )


def unavailable_recovery() -> Doc:
    return result_base(
        "synthetic-report-recovery-unavailable",
        status="unavailable",
        task="recovery",
        reason_code="NO_ONGOING_EPISODE",
        requirements=["A recorded symptom onset without a recorded resolution"],
        provenance={"dataset_snapshot": DATASET, "artifact": None, "feature_coverage": []},
    )


def unavailable_sparse_forecast() -> Doc:
    return result_base(
        "synthetic-report-forecast-sparse",
        status="unavailable",
        task="physiology_forecast",
        reason_code="INSUFFICIENT_HISTORY",
        requirements=["At least 14 days of heart-rate history before as_of"],
        provenance={
            "dataset_snapshot": DATASET,
            "artifact": ARTIFACT,
            "feature_coverage": coverage_list(heart_rate=0.21, steps=0.09),
        },
        warnings=[{"code": "SPARSE_HISTORY", "message": "Only 5 days of history are available."}],
    )


def error_artifact() -> Doc:
    return result_base(
        "synthetic-report-error",
        status="error",
        task="physiology_forecast",
        error_code="ARTIFACT_INTEGRITY_FAILED",
        message="The model artifact failed its checksum check and was not loaded.",
    )


def report_results() -> dict[str, Doc]:
    return {
        "ok-physiology-forecast-hourly": hourly_forecast(),
        "ok-physiology-forecast-daily": daily_forecast(),
        "ok-anomaly-alert": anomaly_alert(),
        "ok-anomaly-abstained-sparse": anomaly_abstained(),
        "ok-illness-onset": illness_onset(),
        "ok-recovery": recovery(),
        "ok-alertness-simulation": alertness_simulation(),
        "unavailable-illness-onset": unavailable_illness(),
        "unavailable-recovery-no-episode": unavailable_recovery(),
        "unavailable-forecast-sparse-history": unavailable_sparse_forecast(),
        "error-artifact-integrity": error_artifact(),
    }


def report_jobs() -> dict[str, Doc]:
    request = report_requests()["physiology-forecast-hourly"]
    result = hourly_forecast()
    common = {"schema_version": SCHEMA_VERSION, "report_id": result["report_id"]}
    return {
        "queued": {
            **common,
            "state": "queued",
            "submitted_at_utc": ts(AS_OF + timedelta(seconds=1)),
            "updated_at_utc": ts(AS_OF + timedelta(seconds=1)),
            "request": request,
            "result": None,
        },
        "completed": {
            **common,
            "state": "completed",
            "submitted_at_utc": ts(AS_OF + timedelta(seconds=1)),
            "updated_at_utc": ts(AS_OF + timedelta(seconds=6)),
            "request": request,
            "result": result,
        },
    }


# --- Imports, coverage, errors, health -------------------------------------------------------


def import_statuses() -> dict[str, Doc]:
    created = AS_OF - timedelta(hours=2)
    base = {
        "schema_version": SCHEMA_VERSION,
        "import_id": "synthetic-import-01",
        "subject_id": SUBJECT,
        "data_mode": "synthetic",
        "source_format": "apple_health_export_zip",
        "declared_tz_name": TZ,
        "created_at_utc": ts(created),
    }
    return {
        "pending": {
            **base,
            "state": "pending",
            "updated_at_utc": ts(created),
            "counts": None,
            "record_issues": [],
            "failure": None,
        },
        "running": {
            **base,
            "state": "running",
            "updated_at_utc": ts(created + timedelta(seconds=40)),
            "counts": {
                "records_seen": 412000,
                "records_accepted": 380210,
                "records_duplicate": 20480,
                "records_unsupported": 11102,
                "records_rejected": 160,
                "records_quarantined": 48,
            },
            "record_issues": [],
            "failure": None,
        },
        "succeeded-with-quarantine": {
            **base,
            "state": "succeeded",
            "updated_at_utc": ts(created + timedelta(minutes=3)),
            "counts": {
                "records_seen": 1284311,
                "records_accepted": 1190402,
                "records_duplicate": 61250,
                "records_unsupported": 31987,
                "records_rejected": 512,
                "records_quarantined": 160,
            },
            "record_issues": [
                {"disposition": "rejected", "code": "INVALID_TIMESTAMP", "count": 300},
                {"disposition": "rejected", "code": "END_BEFORE_START", "count": 212},
                {"disposition": "quarantined", "code": "UNKNOWN_UNIT", "count": 160},
            ],
            "failure": None,
        },
        "failed-malformed-xml": {
            **base,
            "state": "failed",
            "updated_at_utc": ts(created + timedelta(seconds=75)),
            "counts": None,
            "record_issues": [],
            "failure": {
                "error_code": "MALFORMED_XML",
                "message": "export.xml is not well-formed XML near the end of the file.",
                "action": "Export again from the Health app and upload the new export.zip.",
            },
        },
    }


def task_support(**unsupported: str) -> list[Doc]:
    tasks = ["physiology_forecast", "anomaly", "illness_onset", "recovery", "alertness"]
    return [
        {"task": t, "supported": t not in unsupported, "reason_code": unsupported.get(t)}
        for t in tasks
    ]


def coverages() -> dict[str, Doc]:
    base = {
        "schema_version": SCHEMA_VERSION,
        "subject_id": SUBJECT,
        "data_mode": "synthetic",
        "generated_at_utc": ts(AS_OF),
    }
    span_start = datetime(2026, 6, 1, 7, 0, tzinfo=UTC)

    def metric(name: str, unit: str, coverage: float, days: int, gap: float) -> Doc:
        return {
            "metric": name,
            "unit": unit,
            "first_utc": ts(span_start),
            "last_utc": ts(AS_OF - timedelta(hours=1)),
            "days_with_data": days,
            "coverage": coverage,
            "longest_gap_hours": gap,
            "source_kinds": ["watch"] if name != "steps" else ["watch", "phone"],
        }

    sparse_start = AS_OF - timedelta(days=5)
    return {
        "typical": {
            **base,
            "dataset_snapshot": DATASET,
            "history": "sufficient",
            "span_start_utc": ts(span_start),
            "span_end_utc": ts(AS_OF),
            "metrics": [
                metric("heart_rate", "bpm", 0.91, 129, 31.5),
                metric("resting_heart_rate_vendor", "bpm", 0.96, 126, 48.0),
                metric("steps", "count", 0.88, 131, 22.0),
                metric("sleep_asleep_core", "s", 0.83, 112, 72.0),
            ],
            "task_support": task_support(
                illness_onset="NO_VALIDATED_ILLNESS_ARTIFACT", recovery="NO_ONGOING_EPISODE"
            ),
        },
        "sparse-history": {
            **base,
            "dataset_snapshot": DATASET,
            "history": "insufficient",
            "span_start_utc": ts(sparse_start),
            "span_end_utc": ts(AS_OF),
            "metrics": [
                {
                    "metric": "heart_rate",
                    "unit": "bpm",
                    "first_utc": ts(sparse_start),
                    "last_utc": ts(AS_OF - timedelta(hours=3)),
                    "days_with_data": 3,
                    "coverage": 0.21,
                    "longest_gap_hours": 41.0,
                    "source_kinds": ["watch"],
                }
            ],
            "task_support": task_support(
                physiology_forecast="INSUFFICIENT_HISTORY",
                anomaly="INSUFFICIENT_HISTORY",
                illness_onset="INSUFFICIENT_HISTORY",
                recovery="NO_ONGOING_EPISODE",
            ),
        },
        "empty": {
            **base,
            "dataset_snapshot": None,
            "history": "empty",
            "span_start_utc": None,
            "span_end_utc": None,
            "metrics": [],
            "task_support": task_support(
                physiology_forecast="INSUFFICIENT_HISTORY",
                anomaly="INSUFFICIENT_HISTORY",
                illness_onset="INSUFFICIENT_HISTORY",
                recovery="NO_ONGOING_EPISODE",
            ),
        },
    }


def api_errors() -> dict[str, Doc]:
    return {
        "validation-failed": {
            "schema_version": SCHEMA_VERSION,
            "error_code": "VALIDATION_FAILED",
            "message": "The report request is invalid.",
            "request_id": "synthetic-request-0001",
            "field_issues": [{"path": "horizon_hours", "message": "Input should be 24, 48 or 72"}],
        }
    }


def health_statuses() -> dict[str, Doc]:
    return {
        "ok": {
            "schema_version": SCHEMA_VERSION,
            "status": "ok",
            "git_sha": GIT_SHA,
            "artifacts": [ARTIFACT],
        }
    }


# --- Table rows and manifests ---------------------------------------------------------------


def observation(**overrides: Any) -> Doc:
    start = AS_OF - timedelta(hours=10)
    return {
        "dataset_id": "synthetic",
        "subject_id": SUBJECT,
        "record_id": sha("synthetic-record-hr")[:32],
        "source_kind": "watch",
        "source_id": "synthetic-source-watch",
        "device_model": "Watch7,1",
        "metric": "heart_rate",
        "value": 61.0,
        "unit": "bpm",
        "start_utc": ts(start),
        "end_utc": ts(start),
        "available_at_utc": ts(start + timedelta(minutes=4)),
        "availability": "observed",
        "availability_rule": None,
        "tz_name": None,
        "utc_offset_minutes": -420,
        "tz_provenance": "record_offset",
        **overrides,
    }


def observations() -> dict[str, Doc]:
    step_start = AS_OF - timedelta(hours=6)
    sleep_start = AS_OF - timedelta(hours=3)
    return {
        "heart-rate-sample": observation(),
        "steps-interval": observation(
            record_id=sha("synthetic-record-steps")[:32],
            source_kind="phone",
            source_id="synthetic-source-phone",
            device_model=None,
            metric="steps",
            value=412.0,
            unit="count",
            start_utc=ts(step_start),
            end_utc=ts(step_start + timedelta(minutes=10)),
            available_at_utc=ts(step_start + timedelta(minutes=11)),
        ),
        "sleep-stage-assumed-availability": observation(
            dataset_id="synthetic-pmdata-like",
            record_id=sha("synthetic-record-sleep")[:32],
            source_kind="fitness_tracker",
            source_id="synthetic-source-tracker",
            device_model=None,
            metric="sleep_asleep_deep",
            value=1500.0,
            unit="s",
            start_utc=ts(sleep_start),
            end_utc=ts(sleep_start + timedelta(minutes=25)),
            available_at_utc=ts(sleep_start + timedelta(hours=12)),
            availability="assumed",
            availability_rule="synthetic-sleep-synced-by-noon",
            tz_name=TZ,
            utc_offset_minutes=None,
            tz_provenance="dataset_documentation",
        ),
    }


def aggregate(**overrides: Any) -> Doc:
    start = AS_OF - timedelta(hours=5)
    return {
        "dataset_id": "synthetic",
        "subject_id": SUBJECT,
        "metric": "steps",
        "unit": "count",
        "resolution": "hour",
        "interval_start_utc": ts(start),
        "interval_end_utc": ts(start + timedelta(hours=1)),
        "local_date": None,
        "tz_name": None,
        "aggregation": "sum",
        "value": 1290.0,
        "null_reason": None,
        "observed_count": 6,
        "coverage": 0.92,
        "source_ids": ["synthetic-source-phone", "synthetic-source-watch"],
        "pipeline_version": "0.1.0",
        **overrides,
    }


def aggregates() -> dict[str, Doc]:
    dst_start, dst_end = local_day_bounds(date(2026, 11, 1), TZ)  # 25-hour local day
    return {
        "hourly-steps": aggregate(),
        "hourly-steps-missing": aggregate(
            value=None,
            null_reason="no_observations",
            observed_count=0,
            coverage=0.0,
            source_ids=[],
        ),
        "daily-resting-hr-dst-fall-back": aggregate(
            metric="resting_heart_rate_vendor",
            unit="bpm",
            resolution="day",
            interval_start_utc=ts(dst_start),
            interval_end_utc=ts(dst_end),
            local_date="2026-11-01",
            tz_name=TZ,
            aggregation="mean",
            value=57.0,
            observed_count=1,
            coverage=1.0,
            source_ids=["synthetic-source-watch"],
        ),
    }


def outcomes() -> dict[str, Doc]:
    onset = AS_OF - timedelta(days=12)
    base = {"dataset_id": "synthetic", "subject_id": SUBJECT, "label_source": "study_survey"}
    return {
        "symptom-episode-resolved": {
            **base,
            "kind": "symptom_episode",
            "episode_id": "synthetic-episode-00",
            "onset_earliest_utc": ts(onset),
            "onset_latest_utc": ts(onset + timedelta(hours=12)),
            "resolution_status": "resolved",
            "resolution_earliest_utc": ts(onset + timedelta(days=5)),
            "resolution_latest_utc": ts(onset + timedelta(days=6)),
            "resolution_definition": "synthetic-two-symptom-free-checkins",
            "last_follow_up_utc": ts(onset + timedelta(days=9)),
            "observed_at_utc": ts(onset + timedelta(days=1)),
            "confidence": "confirmed",
        },
        "symptom-episode-censored": {
            **base,
            "kind": "symptom_episode",
            "episode_id": "synthetic-episode-01",
            "onset_earliest_utc": ts(AS_OF - timedelta(days=3)),
            "onset_latest_utc": ts(AS_OF - timedelta(days=3) + timedelta(hours=12)),
            "resolution_status": "right_censored",
            "resolution_earliest_utc": None,
            "resolution_latest_utc": None,
            "resolution_definition": None,
            "last_follow_up_utc": ts(AS_OF),
            "observed_at_utc": ts(AS_OF - timedelta(days=2)),
            "confidence": "probable",
        },
        "test-result-positive": {
            **base,
            "kind": "test_result",
            "test_id": "synthetic-test-01",
            "episode_id": "synthetic-episode-00",
            "pathogen": "sars_cov_2",
            "method": "pcr",
            "result": "positive",
            "collected_earliest_utc": ts(onset + timedelta(days=1)),
            "collected_latest_utc": ts(onset + timedelta(days=2)),
            "observed_at_utc": ts(onset + timedelta(days=3)),
        },
        "status-unknown-no-survey": {
            "dataset_id": "synthetic",
            "subject_id": SUBJECT,
            "kind": "status_unknown",
            "start_utc": ts(onset - timedelta(days=10)),
            "end_utc": ts(onset - timedelta(days=7)),
            "reason": "no_survey",
            "note": None,
        },
    }


def split_manifests() -> dict[str, Doc]:
    subjects = [f"synthetic-{i:03d}" for i in range(1, 12)]
    return {
        "fold-0": {
            "schema_version": SCHEMA_VERSION,
            "manifest_id": "synthetic-split-fold-0",
            "created_at_utc": ts(AS_OF),
            "dataset_snapshot": DATASET,
            "task": "physiology_forecast",
            "fold": 0,
            "n_folds": 5,
            "train_subjects": subjects[:6],
            "validation_subjects": subjects[6:8],
            "test_subjects": subjects[8:10],
            "exclusions": [
                {
                    "subject_id": subjects[10],
                    "record_id": None,
                    "reason": "Fewer than 14 days of data",
                }
            ],
            "lookback_hours": 336,
            "horizon_hours": 24,
            "embargo_hours": 0,
            "cutoff_stride_hours": 24,
            "min_history_hours": 336,
            "evaluation_window": None,
            "seed": 20261010,
            "test_opened_at_utc": None,
        }
    }


def run_manifests() -> dict[str, Doc]:
    return {
        "baseline-last-value": {
            "schema_version": SCHEMA_VERSION,
            "run_id": "synthetic-run-baseline-last-value",
            "created_at_utc": ts(AS_OF),
            "git_sha": GIT_SHA,
            "git_dirty": False,
            "config_sha256": sha("synthetic-config"),
            "dataset_snapshot": DATASET,
            "split_manifest_sha256": sha("synthetic-split-fold-0"),
            "task": "physiology_forecast",
            "feature_order": ["heart_rate:mean:1h", "steps:sum:1h"],
            "model": {
                "model_id": "synthetic-last-value",
                "checkpoint_source": None,
                "checkpoint_revision": None,
                "license": None,
            },
            "environment_sha256": sha("synthetic-uv-lock"),
            "seed": 20261010,
            "artifact": ARTIFACT,
            "metrics_paths": ["metrics/per_subject.json", "metrics/summary.json"],
        }
    }


VALID: dict[type[BaseModel], Callable[[], dict[str, Doc]]] = {
    ReportRequest: report_requests,
    ScenarioRequest: scenario_requests,
    SelfReportRequest: self_report_requests,
    ReportResult: report_results,
    ReportJob: report_jobs,
    ImportStatus: import_statuses,
    Coverage: coverages,
    ApiError: api_errors,
    HealthStatus: health_statuses,
    Observation: observations,
    Aggregate: aggregates,
    Outcome: outcomes,
    SplitManifest: split_manifests,
    RunManifest: run_manifests,
}

# --- Invalid fixtures: (document, name, base fixture, mutation, expected error) ---------------


def _set(path: str, value: Any) -> Callable[[Doc], None]:
    keys = path.split(".")

    def apply(doc: Doc) -> None:
        target = doc
        for key in keys[:-1]:
            target = target[int(key)] if isinstance(target, list) else target[key]
        if isinstance(target, list):
            target[int(keys[-1])] = value
        else:
            target[keys[-1]] = value

    return apply


def _drop(path: str) -> Callable[[Doc], None]:
    keys = path.split(".")

    def apply(doc: Doc) -> None:
        target = doc
        for key in keys[:-1]:
            target = target[int(key)] if isinstance(target, list) else target[key]
        del target[keys[-1]]

    return apply


def _rename(old: str, new: str) -> Callable[[Doc], None]:
    def apply(doc: Doc) -> None:
        doc[new] = doc.pop(old)

    return apply


def _all(*mutations: Callable[[Doc], None]) -> Callable[[Doc], None]:
    def apply(doc: Doc) -> None:
        for m in mutations:
            m(doc)

    return apply


# fmt: off
INVALID: list[tuple[type[BaseModel], str, str, Callable[[Doc], None], str]] = [
    # Report results
    (ReportResult, "ok-payload-for-wrong-task", "ok-anomaly-alert",
     _rename("anomaly", "forecast"), "Extra inputs are not permitted"),
    (ReportResult, "ok-unknown-task", "ok-anomaly-alert",
     _set("task", "cold_prediction"), "Expected status ok (with a known task)"),
    (ReportResult, "forecast-lower-above-median", "ok-physiology-forecast-hourly",
     _set("forecast.series.0.points.0.lower", 99.0), "lower <= median <= upper"),
    (ReportResult, "forecast-before-as-of", "ok-physiology-forecast-hourly",
     _set("as_of", "2026-10-10T08:00:00Z"), "start at or after as_of"),
    (ReportResult, "forecast-wrong-unit", "ok-physiology-forecast-hourly",
     _set("forecast.series.0.unit", "ms"), "must use canonical unit"),
    (ReportResult, "forecast-negative-steps", "ok-physiology-forecast-hourly",
     _set("forecast.series.1.points.0.lower", -50.0), "steps cannot be negative"),
    (ReportResult, "anomaly-with-illness-probability", "ok-anomaly-alert",
     _set("anomaly.illness_probability", 0.4), "Extra inputs are not permitted"),
    (ReportResult, "anomaly-baseline-after-as-of", "ok-anomaly-alert",
     _set("anomaly.baseline_window_end_utc", "2026-10-11T07:00:00Z"),
     "baseline window must end at or before as_of"),
    (ReportResult, "anomaly-alert-below-threshold", "ok-anomaly-alert",
     _set("anomaly.score", 1.2), "alert_state must agree"),
    (ReportResult, "unavailable-as-zero-probability", "unavailable-illness-onset",
     _set("onset_probability", 0.0), "Extra inputs are not permitted"),
    (ReportResult, "unavailable-without-requirements", "unavailable-illness-onset",
     _set("requirements", []), "at least 1 item"),
    (ReportResult, "simulation-with-accuracy", "ok-alertness-simulation",
     _set("alertness.validation",
          {"report": "synthetic", "metric": "MAE", "value": 0.1, "n_observations": 3}),
     "validation is present exactly for validated_prediction"),
    (ReportResult, "ok-without-dataset-snapshot", "ok-recovery",
     _set("provenance.dataset_snapshot", None), "must name its dataset snapshot"),
    (ReportResult, "recovery-survival-increases", "ok-recovery",
     _set("recovery.survival.3.probability_still_symptomatic", 0.95), "cannot increase"),
    (ReportResult, "naive-as-of", "unavailable-illness-onset",
     _set("as_of", "2026-10-10T07:00:00"), "timezone"),
    (ReportResult, "non-utc-as-of", "unavailable-illness-onset",
     _set("as_of", "2026-10-10T09:00:00+02:00"), "must be expressed in UTC"),
    # Report requests
    (ReportRequest, "horizon-as-string", "physiology-forecast-hourly",
     _set("horizon_hours", "24"), "valid integer"),
    (ReportRequest, "illness-seven-day-horizon", "illness-onset-48h",
     _set("horizon_hours", 168), "24, 48 or 72"),
    (ReportRequest, "forecast-without-resolution", "physiology-forecast-hourly",
     _drop("resolution"), "physiology_forecast without a resolution"),
    (ReportRequest, "subject-id-path-traversal", "anomaly",
     _set("subject_id", "../../etc/passwd"), "should match pattern"),
    (ReportRequest, "unsupported-schema-version", "anomaly",
     _set("schema_version", "9.9"), "Input should be '0.1'"),
    # Scenario and self-report requests
    (ScenarioRequest, "bedtime-in-dst-gap", "compare-two-bedtimes",
     _all(_set("schedules.0.bedtime_local", "2027-03-14T02:30:00"),
          _set("schedules.0.wake_time_local", "2027-03-14T09:30:00")),
     "does not exist"),
    (ScenarioRequest, "wake-before-bedtime", "compare-two-bedtimes",
     _set("schedules.1.wake_time_local", "2026-10-10T21:00:00"), "wake must follow bedtime"),
    (ScenarioRequest, "missing-assumptions", "compare-two-bedtimes",
     _drop("assumptions"), "Field required"),
    (SelfReportRequest, "entered-before-event", "symptoms-tests-and-alertness",
     _set("entries.3.entered_at_utc", "2026-10-09T23:00:00Z"), "cannot be recorded before"),
    (SelfReportRequest, "checkin-present-without-symptoms", "symptoms-tests-and-alertness",
     _set("entries.1.symptoms", []), "exactly when symptoms are present"),
    # Imports
    (ImportStatus, "failed-without-failure", "failed-malformed-xml",
     _set("failure", None), "failure is present exactly when"),
    (ImportStatus, "counts-do-not-add-up", "succeeded-with-quarantine",
     _set("counts.records_accepted", 1), "must add up to records_seen"),
    # Coverage
    (Coverage, "unsupported-task-without-reason", "typical",
     _set("task_support.2.reason_code", None), "needs a reason_code"),
    # Table rows
    (Observation, "unknown-unit", "heart-rate-sample",
     _set("unit", "count/min"), "Input should be 'bpm'"),
    (Observation, "non-canonical-unit", "heart-rate-sample",
     _set("unit", "ms"), "must use canonical unit"),
    (Observation, "end-before-start", "steps-interval",
     _set("end_utc", "2026-10-10T00:00:00Z"), "end must be at or after start"),
    (Observation, "assumed-availability-without-rule", "sleep-stage-assumed-availability",
     _set("availability_rule", None), "availability_rule is required"),
    (Observation, "sleep-longer-than-interval", "sleep-stage-assumed-availability",
     _set("value", 7200.0), "duration exceeds its interval"),
    (Aggregate, "empty-bin-as-zero", "hourly-steps-missing",
     _all(_set("value", 0.0), _set("null_reason", None)), "never zero"),
    (Aggregate, "dst-day-as-24-hours", "daily-resting-hr-dst-fall-back",
     _set("interval_end_utc", "2026-11-02T07:00:00Z"), "local midnight to midnight"),
    (Aggregate, "mean-of-steps", "hourly-steps",
     _set("aggregation", "mean"), "cannot be aggregated with mean"),
    (Outcome, "censored-with-resolution", "symptom-episode-censored",
     _set("resolution_earliest_utc", "2026-10-09T07:00:00Z"), "censored episode has no"),
    (Outcome, "test-date-as-onset", "test-result-positive",
     _set("onset_earliest_utc", "2026-09-29T07:00:00Z"), "Extra inputs are not permitted"),
    (SplitManifest, "overlapping-partitions", "fold-0",
     _set("test_subjects.0", "synthetic-001"), "partitions share subjects"),
    (RunManifest, "metrics-path-escapes-root", "baseline-last-value",
     _set("metrics_paths.0", "metrics/../../secrets.json"), "'..' segments"),
]
# fmt: on


# --- Writing --------------------------------------------------------------------------------


def _dump(doc: Doc) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def build(root: Path) -> None:
    valid_docs: dict[tuple[type[BaseModel], str], Doc] = {}
    for model, factory in VALID.items():
        for name, doc in factory().items():
            model.model_validate_json(json.dumps(doc))  # fail fast on an invalid valid fixture
            valid_docs[(model, name)] = doc
            path = root / model.__name__ / f"{name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_dump(doc))

    expectations = {}
    for model, name, base, mutate, expected in INVALID:
        doc = copy.deepcopy(valid_docs[(model, base)])
        mutate(doc)
        try:
            model.model_validate_json(json.dumps(doc))
        except ValidationError as error:
            if expected not in str(error):
                message = f"{model.__name__}/{name}: expected {expected!r}, got:\n{error}"
                raise SystemExit(message) from error
        else:
            raise SystemExit(f"{model.__name__}/{name}: invalid fixture was accepted")
        relative = f"{model.__name__}/{name}.json"
        path = root / "invalid" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_dump(doc))
        expectations[relative] = expected
    (root / "invalid" / "expectations.json").write_text(_dump(expectations))


def _tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*.json"))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if fixtures are stale")
    args = parser.parse_args(argv)
    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp))
            if _tree(Path(tmp)) != (_tree(FIXTURES) if FIXTURES.exists() else {}):
                print("contracts/fixtures is stale; run `make build`", file=sys.stderr)
                return 1
        return 0
    if FIXTURES.exists():
        shutil.rmtree(FIXTURES)
    build(FIXTURES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
