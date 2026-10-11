"""Label results to Parquet tables: canonical outcome rows plus the tables #13 and #14 read.

Every timestamp is on the dataset's clock (see the dataset settings): a local day D becomes the
instant D 00:00 written as UTC. Within one dataset, order and durations are exact.
"""

from collections.abc import Iterable, Sequence
from datetime import date, timedelta

import pyarrow as pa

from hachi.contracts.tables import StatusUnknown, SymptomEpisode, TestResult

from .config import Definitions
from .labels import DAY, SubjectLabels, at

UTC_US = pa.timestamp("us", tz="UTC")

OUTCOME_SCHEMA = pa.schema(
    [
        ("kind", pa.string()),
        ("dataset_id", pa.string()),
        ("subject_id", pa.string()),
        ("episode_id", pa.string()),
        ("test_id", pa.string()),
        ("onset_earliest_utc", UTC_US),
        ("onset_latest_utc", UTC_US),
        ("resolution_status", pa.string()),
        ("resolution_earliest_utc", UTC_US),
        ("resolution_latest_utc", UTC_US),
        ("resolution_definition", pa.string()),
        ("last_follow_up_utc", UTC_US),
        ("pathogen", pa.string()),
        ("method", pa.string()),
        ("result", pa.string()),
        ("collected_earliest_utc", UTC_US),
        ("collected_latest_utc", UTC_US),
        ("start_utc", UTC_US),
        ("end_utc", UTC_US),
        ("reason", pa.string()),
        ("note", pa.string()),
        ("observed_at_utc", UTC_US),
        ("label_source", pa.string()),
        ("confidence", pa.string()),
    ]
)
KIND_FIELDS = {
    "symptom_episode": set(SymptomEpisode.model_fields),
    "test_result": set(TestResult.model_fields),
    "status_unknown": set(StatusUnknown.model_fields),
}
MODELS = {
    "symptom_episode": SymptomEpisode,
    "test_result": TestResult,
    "status_unknown": StatusUnknown,
}

EPISODE_SCHEMA = pa.schema(
    [
        ("dataset_id", pa.string()),
        ("subject_id", pa.string()),
        ("episode_id", pa.string()),
        ("category", pa.string()),
        ("onset_first_day", pa.date32()),
        ("onset_last_day", pa.date32()),
        ("reported_onsets", pa.int32()),
        ("confidence", pa.string()),
        ("test_ids", pa.list_(pa.string())),
        ("recruitment", pa.string()),
        ("device", pa.string()),
        ("hr_days_28d_before_onset", pa.int32()),
        ("wearable_days_28d_before_onset", pa.int32()),
        ("ongoing_last_day", pa.date32()),
        ("washout_last_day", pa.date32()),
    ]
)
SUBJECT_SCHEMA = pa.schema(
    [
        ("dataset_id", pa.string()),
        ("subject_id", pa.string()),
        ("span_first_day", pa.date32()),
        ("span_last_day", pa.date32()),
        ("follow_up_start_utc", UTC_US),
        ("follow_up_end_utc", UTC_US),
        ("in_label_tables", pa.bool_()),
        ("undated_illness", pa.bool_()),
        ("episodes", pa.int32()),
        ("positive_tests", pa.int32()),
        ("survey_days", pa.int32()),
        ("wearable_days", pa.int32()),
        ("category", pa.string()),
        ("recruitment", pa.string()),
        ("device", pa.string()),
    ]
)
STATUS_SCHEMA = pa.schema(
    [
        ("dataset_id", pa.string()),
        ("subject_id", pa.string()),
        ("interval_start_utc", UTC_US),
        ("interval_end_utc", UTC_US),
        ("evidence", pa.string()),
        ("source", pa.string()),
        ("available_at_utc", UTC_US),
        ("availability_rule", pa.string()),
        ("definitions_version", pa.string()),
    ]
)
SCORE_SCHEMA = pa.schema(
    [
        ("dataset_id", pa.string()),
        ("subject_id", pa.string()),
        ("local_date", pa.date32()),
        ("scale", pa.string()),
        ("reports", pa.int32()),
        ("symptom_count", pa.int32()),
        ("max_severity", pa.int32()),
        ("severity_sum", pa.int32()),
        ("jackson_adjusted", pa.float64()),
        ("cold_or_flu", pa.bool_()),
        ("available_at_utc", UTC_US),
        ("availability_rule", pa.string()),
    ]
)
SURVEY_AVAILABILITY_RULE = "survey-available-at-end-of-its-local-day"
LABEL_AVAILABILITY_RULE = "labels-known-at-end-of-participant-follow-up"
EVIDENCE = {
    "symptom_free": "observed_symptom_free",
    "symptomatic": "observed_symptomatic",
    "intermediate": "observed_intermediate",
}
RECOVERY_SCHEMA = pa.schema(
    [
        ("dataset_id", pa.string()),
        ("subject_id", pa.string()),
        ("episode_id", pa.string()),
        ("endpoint", pa.string()),
        ("resolution_definition", pa.string()),
        ("status", pa.string()),
        ("reason", pa.string()),
        ("onset_first_day", pa.date32()),
        ("resolution_first_day", pa.date32()),
        ("resolution_last_day", pa.date32()),
        ("follow_up_last_day", pa.date32()),
        ("days_to_resolution_min", pa.int32()),
        ("days_to_resolution_max", pa.int32()),
        ("days_followed", pa.int32()),
    ]
)
WEARABLE_SCHEMA = pa.schema(
    [
        ("subject_id", pa.string()),
        ("local_date", pa.date32()),
        ("heart_rate_records", pa.int64()),
        ("steps_records", pa.int64()),
        ("sleep_records", pa.int64()),
    ]
)
SURVEY_SCHEMA = pa.schema(
    [("subject_id", pa.string()), ("local_date", pa.date32()), ("state", pa.string())]
)


def window_schema(horizons_hours: Sequence[int]) -> pa.Schema:
    fields = [
        ("dataset_id", pa.string()),
        ("subject_id", pa.string()),
        ("cutoff_day", pa.date32()),
        ("cutoff_utc", UTC_US),
        ("wearable_records_day_before", pa.bool_()),
    ]
    for h in horizons_hours:
        fields += [
            (f"onset_{h}h", pa.string()),
            (f"onset_episode_{h}h", pa.string()),
            (f"test_{h}h", pa.string()),
        ]
    return pa.schema(fields)


def endpoint_definition(defs: Definitions, endpoint: str) -> str:
    if endpoint == "sustained_symptom_free":
        return f"{defs.definitions_version}-sustained-symptom-free-{defs.recovery.sustained_days}d"
    return f"{defs.definitions_version}-self-reported-recovery"


CANONICAL_ENDPOINT = "sustained_symptom_free"


def outcome_rows(
    dataset_id: str, labels: SubjectLabels, defs: Definitions, unlabeled_note: str | None
) -> list[dict]:
    observed = at(labels.span.last + DAY)
    rows: list[dict] = []
    for e in labels.episodes:
        result = e.endpoints[CANONICAL_ENDPOINT]
        resolved = result.status == "resolved" and result.resolution is not None
        rows.append(
            {
                "kind": "symptom_episode",
                "dataset_id": dataset_id,
                "subject_id": e.subject_id,
                "episode_id": e.episode_id,
                "onset_earliest_utc": at(e.onset.first),
                "onset_latest_utc": at(e.onset.last + DAY),
                "resolution_status": result.status,
                "resolution_earliest_utc": at(result.resolution.first) if resolved else None,
                "resolution_latest_utc": at(result.resolution.last + DAY) if resolved else None,
                "resolution_definition": endpoint_definition(defs, CANONICAL_ENDPOINT)
                if resolved
                else None,
                "last_follow_up_utc": at(result.follow_up_last + DAY),
                "observed_at_utc": observed,
                "label_source": "study_survey",
                "confidence": e.confidence,
            }
        )
    for t in labels.tests:
        rows.append(
            {
                "kind": "test_result",
                "dataset_id": dataset_id,
                "subject_id": t.subject_id,
                "test_id": t.test_id,
                "episode_id": t.episode_id,
                "pathogen": t.pathogen,
                "method": t.method,
                "result": t.result,
                "collected_earliest_utc": at(t.day),
                "collected_latest_utc": at(t.day + DAY),
                "observed_at_utc": observed,
                "label_source": "study_survey",
            }
        )
    note = unlabeled_note if not labels.episodes and not labels.tests else None
    for run in labels.unknown:
        rows.append(
            {
                "kind": "status_unknown",
                "dataset_id": dataset_id,
                "subject_id": labels.subject_id,
                "start_utc": at(run.first),
                "end_utc": at(run.last + DAY),
                "reason": "no_survey",
                "note": note,
            }
        )
    for row in rows:
        MODELS[row["kind"]].model_validate(row)
    return rows


def episode_rows(
    dataset_id: str,
    labels: SubjectLabels,
    info: dict[str, str],
    hr_days: set[date],
    any_days: set[date],
) -> list[dict]:
    rows = []
    blocks = {b.episode_id: b for b in labels.timeline.blocks}
    for e in labels.episodes:
        block = blocks[e.episode_id]
        window = {e.onset.first - timedelta(days=k) for k in range(1, 29)}
        rows.append(
            {
                "dataset_id": dataset_id,
                "subject_id": e.subject_id,
                "episode_id": e.episode_id,
                "category": e.category,
                "onset_first_day": e.onset.first,
                "onset_last_day": e.onset.last,
                "reported_onsets": e.reported_onsets,
                "confidence": e.confidence,
                "test_ids": e.test_ids,
                "recruitment": info.get("recruitment"),
                "device": info.get("device"),
                "hr_days_28d_before_onset": len(window & hr_days),
                "wearable_days_28d_before_onset": len(window & any_days),
                "ongoing_last_day": block.ongoing_last,
                "washout_last_day": block.washout_last,
            }
        )
    return rows


def subject_row(
    dataset_id: str,
    labels: SubjectLabels,
    info: dict[str, str] | None,
    any_days: set[date],
) -> dict:
    info = info or {}
    span = labels.span
    return {
        "dataset_id": dataset_id,
        "subject_id": labels.subject_id,
        "span_first_day": span.first,
        "span_last_day": span.last,
        "follow_up_start_utc": at(span.first),
        "follow_up_end_utc": at(span.last + DAY),
        "in_label_tables": bool(info) or bool(labels.episodes or labels.tests),
        "undated_illness": labels.timeline.undated_illness,
        "episodes": len(labels.episodes),
        "positive_tests": sum(t.result == "positive" for t in labels.tests),
        "survey_days": len(labels.timeline.surveys),
        "wearable_days": len(any_days),
        "category": info.get("category"),
        "recruitment": info.get("recruitment"),
        "device": info.get("device"),
    }


def status_rows(dataset_id: str, labels: SubjectLabels, defs: Definitions) -> list[dict]:
    """Run-length intervals of symptom evidence over the span; no survey is unknown."""
    rows: list[dict] = []
    surveys = labels.timeline.surveys
    run_start, run_kind = labels.span.first, None
    d = labels.span.first
    while d <= labels.span.last + DAY:
        kind = EVIDENCE.get(surveys.get(d), "unknown") if d <= labels.span.last else None
        if run_kind is not None and kind != run_kind:
            observed = run_kind != "unknown"
            rows.append(
                {
                    "dataset_id": dataset_id,
                    "subject_id": labels.subject_id,
                    "interval_start_utc": at(run_start),
                    "interval_end_utc": at(d),
                    "evidence": run_kind,
                    "source": "daily_survey" if observed else None,
                    "available_at_utc": at(d) if observed else None,
                    "availability_rule": SURVEY_AVAILABILITY_RULE if observed else None,
                    "definitions_version": defs.definitions_version,
                }
            )
        if kind != run_kind:
            run_start, run_kind = d, kind
        d += DAY
    return rows


def recovery_rows(dataset_id: str, labels: SubjectLabels, defs: Definitions) -> list[dict]:
    rows = []
    for e in labels.episodes:
        for endpoint, r in sorted(e.endpoints.items()):
            rows.append(
                {
                    "dataset_id": dataset_id,
                    "subject_id": e.subject_id,
                    "episode_id": e.episode_id,
                    "endpoint": endpoint,
                    "resolution_definition": endpoint_definition(defs, endpoint),
                    "status": r.status,
                    "reason": r.reason,
                    "onset_first_day": e.onset.first,
                    "resolution_first_day": r.resolution.first if r.resolution else None,
                    "resolution_last_day": r.resolution.last if r.resolution else None,
                    "follow_up_last_day": r.follow_up_last,
                    # Day indices from the onset interval's first day (day 0).
                    "days_to_resolution_min": (r.resolution.first - e.onset.first).days
                    if r.resolution
                    else None,
                    "days_to_resolution_max": (r.resolution.last - e.onset.first).days
                    if r.resolution
                    else None,
                    "days_followed": (r.follow_up_last - e.onset.first).days,
                }
            )
    return rows


def window_rows(
    dataset_id: str, labels: SubjectLabels, horizons: Sequence[int], any_days: set[date]
) -> list[dict]:
    rows = []
    for w in labels.windows:
        row = {
            "dataset_id": dataset_id,
            "subject_id": labels.subject_id,
            "cutoff_day": w.cutoff,
            "cutoff_utc": at(w.cutoff),
            "wearable_records_day_before": (w.cutoff - DAY) in any_days,
        }
        for i, h in enumerate(horizons):
            row[f"onset_{h}h"] = w.onset[i]
            row[f"onset_episode_{h}h"] = w.onset_episode[i]
            row[f"test_{h}h"] = w.test[i]
        rows.append(row)
    return rows


def table(rows: Iterable[dict], schema: pa.Schema) -> pa.Table:
    return pa.Table.from_pylist(list(rows), schema=schema)


def outcome_from_row(row: dict) -> SymptomEpisode | TestResult | StatusUnknown:
    kind = row["kind"]
    return MODELS[kind].model_validate({k: v for k, v in row.items() if k in KIND_FIELDS[kind]})


def score_rows(dataset_id: str, rows: list[dict]) -> list[dict]:
    """Per answered survey day severity, available at the end of that day."""
    return [
        {
            "dataset_id": dataset_id,
            **row,
            "available_at_utc": at(row["local_date"] + DAY),
            "availability_rule": SURVEY_AVAILABILITY_RULE,
        }
        for row in sorted(rows, key=lambda r: (r["subject_id"], r["local_date"]))
    ]
