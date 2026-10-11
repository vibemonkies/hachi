"""Aggregate label audit: participants, episodes, tests, follow-up, censoring, at-risk windows.

Everything here is a count or a distribution over participants or episodes. No participant id
or date leaves this module, so the report can be committed (reports/data/clinical-*).
"""

import statistics
from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.compute as pc

from .config import Definitions
from .labels import SubjectLabels

if TYPE_CHECKING:
    from .snapshot import LabelSet

PRE_ONSET_MIN_HR_DAYS = 14


def distribution(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    q = (
        statistics.quantiles(ordered, n=4, method="inclusive")
        if len(ordered) > 1
        else [ordered[0]] * 3
    )
    return {
        "n": len(ordered),
        "min": ordered[0],
        "p25": round(q[0], 2),
        "median": round(q[1], 2),
        "p75": round(q[2], 2),
        "max": ordered[-1],
    }


def _value_counts(t: pa.Table, column: str) -> dict[str, int]:
    return {
        str(item["values"]): item["counts"]
        for item in pc.value_counts(t.column(column)).to_pylist()
    }


def build_audit(
    dataset_id: str,
    results: Sequence[SubjectLabels],
    label_set: "LabelSet",
    written: dict[str, pa.Table],
    defs: Definitions,
    endpoint_ids: dict[str, str],
) -> dict[str, Any]:
    wearable = {s for s, days in label_set.any_days.items() if days}
    # In the label tables at all, dated or not; a participant outside them is a control.
    labeled = {r.subject_id for r in results if r.episodes or r.tests} | set(label_set.subject_info)
    surveyed = {s.subject_id for s in label_set.subjects if s.surveys}
    controls = [r for r in results if r.subject_id not in labeled]
    issues: Counter = Counter()
    for r in results:
        issues.update(r.issues)

    episodes = [e for r in results for e in r.episodes]
    episode_table = written["episodes.parquet"].to_pylist()
    pre_onset = Counter()
    for row in episode_table:
        hr = row["hr_days_28d_before_onset"]
        pre_onset[f"{row['category']}:hr_days_ge_{PRE_ONSET_MIN_HR_DAYS}"] += (
            hr >= PRE_ONSET_MIN_HR_DAYS
        )
        pre_onset[f"{row['category']}:any_wearable_day"] += (
            row["wearable_days_28d_before_onset"] > 0
        )
        pre_onset[f"{row['category']}:episodes"] += 1

    tests = [t for r in results for t in r.tests]
    by_episode = {e.episode_id: e for e in episodes}
    gaps_linked = [
        (t.day - by_episode[t.episode_id].onset.first).days for t in tests if t.episode_id
    ]
    gaps_unlinked = []
    for r in results:
        for t in r.tests:
            if t.episode_id is None and r.episodes:
                gaps_unlinked.append(
                    min(((t.day - e.onset.first).days for e in r.episodes), key=abs)
                )

    recovery = written["recovery.parquet"].to_pylist()
    recovery_summary: dict[str, Any] = {}
    for endpoint, ident in endpoint_ids.items():
        rows = [x for x in recovery if x["endpoint"] == endpoint]
        if not rows:
            continue
        resolved = [x for x in rows if x["status"] == "resolved"]
        recovery_summary[ident] = {
            "episodes": len(rows),
            "by_reason": dict(sorted(Counter(x["reason"] for x in rows).items())),
            "days_to_resolution_min": distribution([x["days_to_resolution_min"] for x in resolved]),
            "days_to_resolution_max": distribution([x["days_to_resolution_max"] for x in resolved]),
            "days_followed_censored": distribution(
                [x["days_followed"] for x in rows if x["status"] != "resolved"]
            ),
        }

    windows = written["onset_windows.parquet"]
    window_summary: dict[str, Any] = {"cutoffs": windows.num_rows}
    if windows.num_rows:
        with_data = windows.filter(pc.field("wearable_records_day_before"))
        window_summary["cutoffs_with_wearable_records_day_before"] = with_data.num_rows
        for h in defs.onset.horizons_hours:
            labels = _value_counts(windows, f"onset_{h}h")
            on_data = _value_counts(with_data, f"onset_{h}h") if with_data.num_rows else {}
            positives = windows.filter(pc.field(f"onset_{h}h") == "positive")
            window_summary[f"{h}h"] = {
                "onset_labels": dict(sorted(labels.items())),
                "onset_labels_with_wearable_day_before": dict(sorted(on_data.items())),
                "at_risk_denominator": labels.get("positive", 0) + labels.get("negative", 0),
                "participants_with_a_positive_window": len(
                    set(positives.column("subject_id").to_pylist())
                ),
                "episodes_with_a_positive_window": len(
                    set(positives.column(f"onset_episode_{h}h").to_pylist())
                ),
                "test_labels": dict(sorted(_value_counts(windows, f"test_{h}h").items())),
            }

    unknown = [u for r in results for u in r.unknown]
    survey_states = Counter(state for s in label_set.subjects for state in s.surveys.values())
    control_days = [len(label_set.any_days.get(r.subject_id, ())) for r in controls]
    return {
        "dataset_id": dataset_id,
        "clock": label_set.clock,
        "participants": {
            "total": len(results),
            "with_wearable_records": len(wearable),
            "with_outcome_labels": len(labeled),
            "labeled_with_wearable_records": len(labeled & wearable),
            "labeled_without_wearable_records": len(labeled - wearable),
            "with_completed_surveys": len(surveyed),
            "without_outcome_labels": len(controls),
        },
        "control_follow_up": {
            "participants": len(controls),
            "wearable_days": sum(control_days),
            "wearable_days_per_participant": distribution(control_days),
            "completed_survey_days": sum(
                len(s.surveys) for s in label_set.subjects if s.subject_id not in labeled
            ),
        },
        "surveys": {
            "completed_days_by_state": dict(sorted(survey_states.items())),
            "participants": len(surveyed),
        },
        "episodes": {
            "total": len(episodes),
            "by_category": dict(sorted(Counter(e.category for e in episodes).items())),
            "by_confidence": dict(sorted(Counter(e.confidence for e in episodes).items())),
            "by_category_and_confidence": dict(
                sorted(Counter(f"{e.category}:{e.confidence}" for e in episodes).items())
            ),
            "with_merged_relapse_onsets": sum(e.reported_onsets > 1 for e in episodes),
            "onset_interval_days": dict(
                sorted(Counter((e.onset.last - e.onset.first).days + 1 for e in episodes).items())
            ),
            "pre_onset_wearable_coverage_28d": dict(sorted(pre_onset.items())),
        },
        "tests": {
            "total": len(tests),
            "by_pathogen_and_result": dict(
                sorted(Counter(f"{t.pathogen}:{t.result}" for t in tests).items())
            ),
            "linked_to_episode": sum(t.episode_id is not None for t in tests),
            "unlinked": sum(t.episode_id is None for t in tests),
            "unlinked_in_participants_with_an_episode": len(gaps_unlinked),
            "test_day_minus_onset_day_linked": distribution(gaps_linked),
            "test_day_minus_nearest_onset_day_unlinked": distribution(gaps_unlinked),
        },
        "recovery": recovery_summary,
        "onset_windows": window_summary,
        "status_unknown": {
            "rows": len(unknown),
            "days": sum((u.last - u.first).days + 1 for u in unknown),
        },
        "source_counts": dict(sorted(label_set.source_counts.items())),
        "label_issues": dict(sorted(issues.items())),
        **label_set.extra_audit,
    }


def report(snapshot_id: str, manifest: dict[str, Any], audit_doc: dict[str, Any]) -> dict[str, Any]:
    """The committed report: the aggregate audit plus the snapshot's identity."""
    return {
        "snapshot_id": snapshot_id,
        "dataset_snapshot": manifest["dataset_snapshot"],
        "pipeline_version": manifest["pipeline_version"],
        "definitions_version": manifest["definitions"]["definitions_version"],
        "definitions_sha256": manifest["definitions"]["sha256"],
        "settings_sha256": manifest["settings"]["sha256"],
        "sources": manifest["sources"],
        "canonical_recovery_endpoint": manifest["canonical_recovery_endpoint"],
        "tables": {k: v["rows"] for k, v in manifest["tables"].items()},
        "built_with": manifest["built_with"],
        "audit": audit_doc,
    }
