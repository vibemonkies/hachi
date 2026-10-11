"""Check a Stanford label snapshot against its source workbook, by a separate route.

Re-reads the workbook's cells and recomputes, without the label engine, what the snapshot must
contain: every reported onset date is an episode onset or a merged relapse onset, every reported
diagnosis or test date is exactly one positive test, every answered survey day has the state its
raw answers imply, accepted self-reported recoveries are reported dates, and each episode's own
onset cutoff is positive at 24 h unless excluded. Output is counts only.
"""

import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import StanfordSettings
from .snapshot import load_manifest, read_table
from .xlsx import read_sheet

ISO = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _dates(text: str | None) -> list[date]:
    return [date.fromisoformat(d) for d in ISO.findall(text or "")]


def _rows_after(rows: list[list[str | None]], first: str) -> tuple[list[str | None], list[list]]:
    i = next(i for i, r in enumerate(rows) if r and r[0] == first)
    return rows[i], [r for r in rows[i + 1 :] if r and r[0]]


def _source(workbook: Path, settings: StanfordSettings) -> dict[str, Any]:
    onsets: dict[str, list[date]] = {}
    tests: dict[str, list[date]] = {}
    recoveries: dict[str, list[date]] = {}
    states: dict[tuple[str, date], str] = {}
    if settings.survey is not None:  # phase 1
        header, rows = _rows_after(
            read_sheet(workbook, "SuppTable3_Fig2a_COVID-19"), "ParticipantID"
        )
        col = {name: i for i, name in enumerate(header) if name}
        for r in rows:
            cells = {name: (r[i] if i < len(r) else None) for name, i in col.items()}
            onsets[r[0]] = _dates(cells["Symptom_dates"])
            tests[r[0]] = _dates(cells["covid_diagnosis_dates"])
            recoveries[r[0]] = _dates(cells["recovery_dates"])
        header, rows = _rows_after(
            read_sheet(workbook, "SuppTable5_Fig2a_DailySymptoms"), "ParticipantID"
        )
        col = {name: i for i, name in enumerate(header) if name}
        sick = set(settings.survey.symptomatic_feelings)
        for r in rows:
            values = {name: (r[i] if i < len(r) else None) for name, i in col.items()}
            day = date(1899, 12, 30) + timedelta(days=int(float(values["Date"])))
            symptoms = [values[c] for c in settings.survey.symptom_columns]
            answered = [values["overall_feel"], values["temperature"], *symptoms]
            if all(v in (None, "") for v in answered):
                continue
            state = (
                "symptomatic"
                if any(v not in (None, "") for v in symptoms) or values["overall_feel"] in sick
                else "symptom_free"
            )
            key = (r[0], day)
            if states.get(key) != "symptomatic":
                states[key] = state
    else:  # phase 2
        _, rows = _rows_after(
            read_sheet(workbook, "SourceData_COVID19_Positives"), "Participant ID"
        )
        for r in rows:
            onsets[r[0]] = _dates(r[2])
            tests[r[0]] = _dates(r[1])
            recoveries[r[0]] = []
    return {"onsets": onsets, "tests": tests, "recoveries": recoveries, "states": states}


def reconcile(snapshot: Path, workbook: Path, settings: StanfordSettings) -> dict[str, Any]:
    manifest = load_manifest(snapshot)
    if manifest["dataset_snapshot"]["dataset_id"] != settings.dataset_id:
        raise ValueError("snapshot and settings name different datasets")
    src = _source(workbook, settings)
    checks: Counter = Counter()
    problems: Counter = Counter()

    def check(name: str, ok: bool) -> None:
        checks[name] += 1
        if not ok:
            problems[name] += 1

    episodes = read_table(snapshot, "episodes").to_pylist()
    by_subject: dict[str, list[dict]] = {}
    for e in episodes:
        by_subject.setdefault(e["subject_id"], []).append(e)
    for subject, days in src["onsets"].items():
        mine = by_subject.get(subject, [])
        check("reported_onsets_accounted", sum(e["reported_onsets"] for e in mine) == len(days))
        for e in mine:
            check("episode_onset_is_a_reported_date", e["onset_first_day"] in days)
    outcomes = read_table(snapshot, "outcomes").to_pylist()
    positives: dict[str, list[date]] = {}
    for o in outcomes:
        if o["kind"] == "test_result" and o["result"] == "positive":
            positives.setdefault(o["subject_id"], []).append(o["collected_earliest_utc"].date())
    for subject, days in src["tests"].items():
        check("tests_match_reported_dates", sorted(positives.get(subject, [])) == sorted(days))
    check("no_tests_outside_source", set(positives) <= set(src["tests"]))

    surveys = {
        (r["subject_id"], r["local_date"]): r["state"]
        for r in read_table(snapshot, "surveys").to_pylist()
    }
    for key, state in src["states"].items():
        check("survey_state_matches_raw_answers", surveys.get(key) == state)
    check("no_survey_days_outside_source", set(surveys) <= set(src["states"]))

    for r in read_table(snapshot, "recovery").to_pylist():
        if r["endpoint"] == "self_reported_recovery" and r["status"] == "resolved":
            check(
                "accepted_recovery_is_a_reported_date",
                r["resolution_first_day"] in src["recoveries"].get(r["subject_id"], []),
            )
    windows = {
        (w["subject_id"], w["cutoff_day"]): w["onset_24h"]
        for w in read_table(snapshot, "onset_windows").to_pylist()
    }
    for e in episodes:
        label = windows.get((e["subject_id"], e["onset_first_day"]))
        if label is not None:
            check(
                "own_onset_cutoff_positive_or_excluded",
                label == "positive" or label.startswith("excluded_"),
            )
    return {
        "snapshot_id": manifest["snapshot_id"],
        "ok": not problems,
        "checks": dict(sorted(checks.items())),
        "mismatches": dict(sorted(problems.items())),
    }
