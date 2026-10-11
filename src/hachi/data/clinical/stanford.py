"""Stanford COVID-19 wearables labels: the papers' supplementary tables to `SubjectInput`.

Phase 1 (Mishra et al. 2020) publishes, in Supplementary Data 1:
  - Supplementary Table 3: per participant, a category (COVID-19 or another illness) and lists of
    symptom-onset, COVID-19 diagnosis and recovery dates;
  - Supplementary Table 5: daily symptom surveys (overall feeling, ten symptoms rated 1-5).
Phase 2 (Alavi et al. 2022) publishes, as source data, each COVID-19-positive participant's test
date and symptom-onset date ("-" when asymptomatic), recruitment (retrospective/prospective) and
device. Neither paper releases negative tests, and phase 2 releases no surveys.

All dates are shifted local calendar days, on the same floating clock as the wearable CSVs.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import wearables
from .config import Admission, StanfordSettings
from .labels import DayRange, IllnessReport, SubjectInput, SurveyState, TestDay
from .xlsx import read_sheet

EXCEL_EPOCH = date(1899, 12, 30)
TIMESTAMP = re.compile(r"Timestamp\('(\d{4}-\d{2}-\d{2})[ T]00:00:00'\)|(NaT)")
PATHOGENS = {"covid19": "sars_cov_2", "influenza_b": "influenza"}

PHASE1_EPISODES = "SuppTable3_Fig2a_COVID-19"
PHASE1_SURVEYS = "SuppTable5_Fig2a_DailySymptoms"
PHASE2_POSITIVES = "SourceData_COVID19_Positives"


class LabelSourceError(ValueError):
    pass


@dataclass
class SourceLabels:
    """Labels for one dataset, keyed by subject, before episodes are formed."""

    illnesses: dict[str, list[IllnessReport]] = field(default_factory=dict)
    surveys: dict[str, dict[date, SurveyState]] = field(default_factory=dict)
    subject_info: dict[str, dict[str, str]] = field(default_factory=dict)
    has_self_reported_recovery: bool = False
    counts: Counter = field(default_factory=Counter)

    def label_days(self, subject: str) -> list[date]:
        days = list(self.surveys.get(subject, {}))
        for illness in self.illnesses.get(subject, []):
            days += [r.first for r in illness.onsets] + [r.last for r in illness.onsets]
            days += list(illness.recoveries) + [t.day for t in illness.tests]
        return days


def _header_index(rows: list[list[str | None]], first_cell: str) -> int:
    for i, row in enumerate(rows):
        if row and row[0] == first_cell:
            return i
    raise LabelSourceError(f"no header row starting with {first_cell!r}")


def _columns(header: list[str | None], wanted: list[str]) -> dict[str, int]:
    index = {name: i for i, name in enumerate(header) if name}
    missing = [w for w in wanted if w not in index]
    if missing:
        raise LabelSourceError(f"missing columns {missing}")
    return {w: index[w] for w in wanted}


def _cell(row: list[str | None], i: int) -> str | None:
    value = row[i] if i < len(row) else None
    return value.strip() or None if isinstance(value, str) else value


def _date_list(text: str | None, counts: Counter, what: str) -> list[date]:
    if text is None:
        return []
    out = []
    body = text.strip()
    if not (body.startswith("[") and body.endswith("]")):
        raise LabelSourceError(f"unexpected {what} list format")
    found = TIMESTAMP.findall(body)
    rebuilt = ", ".join("NaT" if nat else f"Timestamp('{d} 00:00:00')" for d, nat in found)
    if rebuilt != body[1:-1].strip():
        raise LabelSourceError(f"unexpected {what} list format")
    for day, nat in found:
        if nat:
            counts[f"{what}_missing_nat"] += 1
        else:
            out.append(date.fromisoformat(day))
    return out


def _excel_day(text: str | None) -> date:
    if text is None:
        raise LabelSourceError("survey row without a date")
    value = float(text)
    if value != int(value):
        raise LabelSourceError("survey dates must be whole days")
    return EXCEL_EPOCH + timedelta(days=int(value))


def read_phase1(workbook: Path, settings: StanfordSettings) -> SourceLabels:
    if settings.survey is None:
        raise LabelSourceError("phase 1 needs survey settings")
    labels = SourceLabels(has_self_reported_recovery=True)
    counts = labels.counts

    rows = read_sheet(workbook, PHASE1_EPISODES)
    h = _header_index(rows, "ParticipantID")
    cols = _columns(
        rows[h],
        ["ParticipantID", "Category", "Symptom_dates", "covid_diagnosis_dates", "recovery_dates"],
    )
    for row in rows[h + 1 :]:
        subject = _cell(row, cols["ParticipantID"])
        if subject is None:
            continue
        category_text = _cell(row, cols["Category"])
        if category_text not in settings.illness_categories:
            raise LabelSourceError(f"unmapped illness category {category_text!r}")
        category = settings.illness_categories[category_text]
        onsets = _date_list(_cell(row, cols["Symptom_dates"]), counts, "onset")
        diagnoses = _date_list(_cell(row, cols["covid_diagnosis_dates"]), counts, "diagnosis")
        recoveries = _date_list(_cell(row, cols["recovery_dates"]), counts, "recovery")
        if subject in labels.illnesses:
            raise LabelSourceError("a participant appears twice in the episode table")
        counts[f"participants_{category}"] += 1
        counts["reported_onset_dates"] += len(onsets)
        counts["reported_diagnosis_dates"] += len(diagnoses)
        counts["reported_recovery_dates"] += len(recoveries)
        labels.illnesses[subject] = [
            IllnessReport(
                category=category,
                onsets=[DayRange(d, d) for d in onsets],
                recoveries=recoveries,
                tests=[
                    TestDay(d, PATHOGENS.get(category, "unknown"), "unknown", "positive")
                    for d in diagnoses
                ],
            )
        ]
        labels.subject_info[subject] = {"category": category}

    rows = read_sheet(workbook, PHASE1_SURVEYS)
    h = _header_index(rows, "ParticipantID")
    symptom_columns = settings.survey.symptom_columns
    cols = _columns(rows[h], ["ParticipantID", "Date", "overall_feel", "temperature"])
    sym = _columns(rows[h], symptom_columns)
    rank = {"symptom_free": 0, "intermediate": 1, "symptomatic": 2}
    per_day: dict[tuple[str, date], list[SurveyState]] = {}
    for row in rows[h + 1 :]:
        subject = _cell(row, cols["ParticipantID"])
        if subject is None:
            continue
        day = _excel_day(_cell(row, cols["Date"]))
        feel = _cell(row, cols["overall_feel"])
        ratings = [_cell(row, i) for i in sym.values()]
        for rating in ratings:
            if rating is not None and rating not in {"1", "2", "3", "4", "5"}:
                raise LabelSourceError("symptom severity outside 1-5")
        counts["survey_rows"] += 1
        if (
            feel is None
            and all(r is None for r in ratings)
            and _cell(row, cols["temperature"]) is None
        ):
            counts["survey_rows_without_any_answer"] += 1
            continue
        symptomatic = any(r is not None for r in ratings) or (
            feel in settings.survey.symptomatic_feelings
        )
        state: SurveyState = "symptomatic" if symptomatic else "symptom_free"
        per_day.setdefault((subject, day), []).append(state)
    for (subject, day), states in sorted(per_day.items()):
        if len(states) > 1:
            counts["survey_days_with_several_reports"] += 1
            if len(set(states)) > 1:
                counts["survey_days_with_conflicting_reports"] += 1
        labels.surveys.setdefault(subject, {})[day] = max(states, key=rank.__getitem__)
    counts["survey_days_completed"] = len(per_day)
    unlabeled = set(labels.surveys) - set(labels.illnesses)
    if unlabeled:
        counts["survey_participants_without_episode_row"] = len(unlabeled)
    return labels


def read_phase2(workbook: Path, settings: StanfordSettings) -> SourceLabels:
    labels = SourceLabels(has_self_reported_recovery=False)
    counts = labels.counts
    rows = read_sheet(workbook, PHASE2_POSITIVES)
    h = _header_index(rows, "Participant ID")
    cols = _columns(
        rows[h],
        [
            "Participant ID",
            "COVID-19 Test Date",
            "COVID-19 Symptom Onset",
            "Retrospective / Prospective",
            "Device",
        ],
    )
    category = settings.illness_categories["COVID-19"]
    for row in rows[h + 1 :]:
        subject = _cell(row, cols["Participant ID"])
        if subject is None:
            continue
        if subject in labels.illnesses:
            raise LabelSourceError("a participant appears twice in the positives table")
        test_text = _cell(row, cols["COVID-19 Test Date"])
        onset_text = _cell(row, cols["COVID-19 Symptom Onset"])
        if test_text in (None, "-"):
            raise LabelSourceError("every released positive has a test date")
        test = date.fromisoformat(test_text)
        onsets = [] if onset_text in (None, "-") else [date.fromisoformat(onset_text)]
        recruitment = _cell(row, cols["Retrospective / Prospective"]) or "unknown"
        device = _cell(row, cols["Device"]) or "unknown"
        counts["participants_covid19"] += 1
        counts["asymptomatic_or_no_onset" if not onsets else "with_symptom_onset"] += 1
        counts[f"recruitment_{recruitment}"] += 1
        counts[f"device_{device}"] += 1
        labels.illnesses[subject] = [
            IllnessReport(
                category=category,
                onsets=[DayRange(d, d) for d in onsets],
                tests=[TestDay(test, "sars_cov_2", "unknown", "positive")],
            )
        ]
        labels.subject_info[subject] = {
            "category": category,
            "recruitment": recruitment,
            "device": device,
        }
    return labels


READERS = {
    "stanford-covid19-wearables": (read_phase1, "phase1"),
    "stanford-covid19-wearables-phase2": (read_phase2, "phase2"),
}


UNLABELED_NOTE = "No outcome data were released for this participant."


def _hour_shares(steps_by_hour: Counter) -> dict[str, float]:
    """Percent of all steps in each local hour: local wall time troughs at night."""
    total = sum(steps_by_hour.values())
    if not total:
        return {}
    return {h: round(100 * steps_by_hour[h] / total, 2) for h in sorted(steps_by_hour)}


def label_set(data_dir: Path, settings: StanfordSettings, admission: Admission, workers: int = 6):
    """Read, check and join one Stanford dataset's labels and wearable day coverage."""
    from .snapshot import LabelSet, check_admitted

    archive = data_dir / settings.archive
    workbook = data_dir / settings.labels_workbook
    for path in (archive, workbook):
        if path.name not in admission.files:
            raise LabelSourceError(f"{path.name} is not an admitted file of {admission.dataset_id}")
        check_admitted(path, admission.files[path.name])
    reader, layout = READERS[settings.dataset_id]
    labels = reader(workbook, settings)
    coverage = wearables.scan(archive, layout, workers=workers)

    per_subject: dict[str, dict[date, dict[str, int]]] = {}
    for (subject, day, stream), n in coverage.days.items():
        per_subject.setdefault(subject, {}).setdefault(day, Counter())[stream] += n
    subjects = sorted(set(per_subject) | set(labels.illnesses) | set(labels.surveys))
    inputs, wearable_rows = [], []
    hr_days: dict[str, set[date]] = {}
    any_days: dict[str, set[date]] = {}
    for subject in subjects:
        days = per_subject.get(subject, {})
        hr_days[subject] = {d for d, c in days.items() if c.get("heart_rate")}
        any_days[subject] = set(days)
        for d in sorted(days):
            c = days[d]
            wearable_rows.append(
                {
                    "subject_id": subject,
                    "local_date": d,
                    "heart_rate_records": c.get("heart_rate", 0),
                    "steps_records": c.get("steps", 0),
                    "sleep_records": c.get("sleep", 0),
                }
            )
        all_days = list(days) + labels.label_days(subject)
        inputs.append(
            SubjectInput(
                subject_id=subject,
                span=DayRange(min(all_days), max(all_days)),
                illnesses=labels.illnesses.get(subject, []),
                surveys=labels.surveys.get(subject, {}),
                has_self_reported_recovery=labels.has_self_reported_recovery,
            )
        )
    members = list(coverage.members.values())
    records: Counter = Counter()
    for m in members:
        records[m["stream"]] += m["rows"]
    extra = {
        "wearable_archive": {
            "members_read": len(members),
            "members_ignored": dict(coverage.ignored),
            "members_by_stream_and_source": dict(
                sorted(Counter(f"{m['stream']}:{m['source']}" for m in members).items())
            ),
            "members_by_state": dict(sorted(Counter(m["state"] for m in members).items())),
            "records_by_stream": dict(sorted(records.items())),
            "unparseable_timestamps": sum(m["bad_timestamps"] for m in members),
            "clock_check_steps_share_by_hour": _hour_shares(coverage.steps_by_hour),
            "participants": len(per_subject),
            "labeled_participants_absent_from_archive": len(
                (set(labels.illnesses) | set(labels.surveys)) - set(per_subject)
            ),
        }
    }
    return LabelSet(
        dataset_id=settings.dataset_id,
        subjects=inputs,
        subject_info=labels.subject_info,
        source_counts=labels.counts,
        hr_days=hr_days,
        any_days=any_days,
        wearable_rows=wearable_rows,
        unlabeled_note=UNLABELED_NOTE,
        clock=settings.clock,
        extra_audit=extra,
    )
