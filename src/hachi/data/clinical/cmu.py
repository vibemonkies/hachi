"""CMU Common Cold Project: viral-challenge symptom scores to onset and recovery labels.

Healthy adults were inoculated on quarantine Day 0 and rated eight Modified Jackson symptoms
(0-4) each day for 5 days (6 for influenza); infection was confirmed by viral shedding or
seroconversion. There are no wearables and no follow-up after quarantine, so recovery is
right-censored at the last quarantine day and onset is a symptom-only, exploratory target.

Gate: the build refuses to read the data until the dataset settings record the submitted CMU
Data Analysis Form (`require_registered_analysis`). The reader streams one tab-delimited member
of the admitted zip, keeps only the columns it needs, and returns aggregate counts; participant
rows are never printed.
"""

import csv
import io
import tomllib
import zipfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from hachi.contracts.base import Contract, Identifier, SchemaVersion, VersionString

from .config import OUTCOMES_DIR, Admission, Loaded, _sha
from .labels import DayRange, IllnessReport, SubjectInput, SurveyState, TestDay

DATASET_ID = "cmu-common-cold-project"
# Modified Jackson total of 8 items rated 0-4, minus the Day 0 baseline, floored at 0.
SCALE = "cmu-modified-jackson-8-items-baseline-adjusted"
MAX_MEMBER_BYTES = 256 << 20
CONTRACT_PATHOGENS = Literal["sars_cov_2", "influenza", "rsv", "other", "unknown"]


class AnalysisRegistration(Contract):
    submitted_on: date | None = None
    reference: Annotated[str, Field(min_length=1, max_length=500)] | None = None


class Virus(Contract):
    category: Identifier
    pathogen: CONTRACT_PATHOGENS


class SymptomSettings(Contract):
    score_column: str
    cold_column: str
    shed_column: str
    infected_column: str
    symptomatic_min_score: Annotated[float, Field(ge=0)]
    symptom_free_max_score: Annotated[float, Field(ge=0)]
    first_day: Annotated[int, Field(ge=1, le=14)]
    last_day: Annotated[int, Field(ge=1, le=14)]
    shed_last_day: Annotated[int, Field(ge=1, le=14)]
    onset_days_before_first_symptomatic: Annotated[int, Field(ge=0, le=3)]


class CmuSettings(Contract):
    schema_version: SchemaVersion
    pipeline_version: VersionString
    dataset_id: Literal["cmu-common-cold-project"]
    data_file_archive: Annotated[str, Field(pattern=r"^[^/\\]{1,255}$")]
    data_file_member: Annotated[str, Field(pattern=r"^[^/\\]{1,255}$")]
    clock: Literal["relative_to_challenge"]
    relative_day_epoch: date
    analysis_registration: AnalysisRegistration
    studies: dict[str, Identifier]
    viruses: dict[str, Virus]
    symptoms: SymptomSettings


class CmuError(ValueError):
    pass


def load_settings(path: Path = OUTCOMES_DIR / f"{DATASET_ID}.toml") -> Loaded[CmuSettings]:
    raw = path.read_bytes()
    return Loaded(CmuSettings.model_validate(tomllib.loads(raw.decode("utf-8"))), _sha(raw), path)


def require_registered_analysis(settings: CmuSettings) -> None:
    reg = settings.analysis_registration
    if reg.submitted_on is None or reg.reference is None:
        raise SystemExit(
            "CMU requires the planned analysis to be registered (Data Analysis Form) before any "
            "analysis. Record submitted_on and reference under [analysis_registration] in "
            "configs/outcomes/cmu-common-cold-project.toml once the form is submitted."
        )


def _number(row: dict[str, str], column: str) -> float | None:
    """A cell as a number, blank as None. Errors name the column, never the value."""
    text = row[column]
    if text is None or not text.strip():
        return None
    try:
        return float(text)
    except ValueError:
        raise CmuError(f"non-numeric value in column {column}") from None


def _binary(row: dict[str, str], column: str, counts: Counter) -> float | None:
    """A 0/1 code; anything else is counted and treated as missing."""
    value = _number(row, column)
    if value is not None and value not in (0, 1):
        counts[f"non_binary_{column.split('.', 1)[-1]}"] += 1
        return None
    return value


def _rows(archive: Path, member: str, columns: set[str]) -> tuple[list[dict], list[str]]:
    with zipfile.ZipFile(archive) as z:
        info = z.getinfo(member)
        if info.file_size > MAX_MEMBER_BYTES or info.flag_bits & 0x1:
            raise CmuError(f"{member} is encrypted or too large")
        with z.open(info) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
            reader = csv.reader(text, delimiter="\t")
            header = next(reader)
            missing = sorted(columns - set(header))
            if missing:
                raise CmuError(f"{member} lacks expected columns: {missing}")
            keep = [(i, name) for i, name in enumerate(header) if name in columns]
            rows = []
            for n, record in enumerate(reader, 2):
                if len(record) != len(header):
                    raise CmuError(
                        f"{member}: line {n} has {len(record)} fields, not {len(header)}"
                    )
                rows.append({name: record[i] for i, name in keep})
    return rows, header


def _state(score: float | None, cold: float | None, s: SymptomSettings) -> SurveyState | None:
    if score is None:
        return None
    if score >= s.symptomatic_min_score:
        return "symptomatic"
    if score <= s.symptom_free_max_score and cold != 1:
        return "symptom_free"
    return "intermediate"


def label_set(data_dir: Path, settings: CmuSettings, admission: Admission):
    """Read the five-study file into SubjectInputs. Only call after the registration gate."""
    from .snapshot import LabelSet, check_admitted

    require_registered_analysis(settings)
    archive = data_dir / settings.data_file_archive
    if archive.name not in admission.files:
        raise CmuError(f"{archive.name} is not an admitted file")
    check_admitted(archive, admission.files[archive.name])
    s = settings.symptoms
    days = range(s.first_day, s.last_day + 1)
    shed_days = range(1, s.shed_last_day + 1)
    score = {d: s.score_column.format(day=d) for d in days}
    cold = {d: s.cold_column.format(day=d) for d in days}
    shed = {d: s.shed_column.format(day=d) for d in shed_days}
    needed = {"subj_id", "study.id", s.infected_column, *settings.viruses}
    needed |= set(score.values()) | set(cold.values()) | set(shed.values())
    rows, _ = _rows(archive, settings.data_file_member, needed)

    epoch = settings.relative_day_epoch
    counts: Counter = Counter()
    inputs: list[SubjectInput] = []
    scores: list[dict] = []
    info: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    for row in rows:
        study_code = row["study.id"].strip()
        if study_code not in settings.studies:
            raise CmuError("unknown study code")
        study = settings.studies[study_code]
        raw_id = row["subj_id"].strip()
        if not raw_id.replace(".", "").isalnum():
            raise CmuError("unexpected subject id format")
        subject = f"{study}-{raw_id.split('.')[0]}"
        if subject in seen:
            raise CmuError("duplicate participant")
        seen.add(subject)
        counts[f"participants_{study}"] += 1
        viruses = [v for v in settings.viruses if _number(row, v) == 1]
        if len(viruses) != 1:
            counts["excluded_virus_not_exactly_one"] += 1
            continue
        virus = settings.viruses[viruses[0]]
        states: dict[date, SurveyState] = {}
        day_scores: list[dict] = []
        for d in days:
            value, said_cold = _number(row, score[d]), _binary(row, cold[d], counts)
            state = _state(value, said_cold, s)
            if state is not None:
                states[epoch + timedelta(days=d)] = state
                day_scores.append(
                    {
                        "subject_id": subject,
                        "local_date": epoch + timedelta(days=d),
                        "scale": SCALE,
                        "reports": 1,
                        "jackson_adjusted": value,
                        "cold_or_flu": None if said_cold is None else said_cold == 1,
                    }
                )
        if not states:
            counts[f"excluded_no_daily_symptom_scores_{study}"] += 1
            continue
        scores += day_scores
        observed = sorted(states)
        gaps = (observed[-1] - observed[0]).days + 1 - len(observed)
        if gaps:
            counts["participants_with_missing_quarantine_days"] += 1
        infected = _binary(row, s.infected_column, counts)
        shedding = {d: _binary(row, shed[d], counts) for d in shed_days}
        tests = [
            TestDay(
                epoch + timedelta(days=d),
                virus.pathogen,
                "other",
                "positive" if value == 1 else "negative",
            )
            for d, value in shedding.items()
            if value is not None
        ]
        first_symptomatic = next((d for d in observed if states[d] == "symptomatic"), None)
        onsets = []
        if first_symptomatic is not None:
            back = timedelta(days=s.onset_days_before_first_symptomatic)
            onsets = [DayRange(max(epoch, first_symptomatic - back), first_symptomatic)]
        counts["with_symptomatic_onset" if onsets else "without_symptomatic_onset"] += 1
        counts[f"infected_{'unknown' if infected is None else int(infected)}"] += 1
        inputs.append(
            SubjectInput(
                subject_id=subject,
                span=DayRange(epoch, observed[-1]),
                illnesses=[
                    IllnessReport(
                        virus.category,
                        onsets,
                        (),
                        tests,
                        infection_confirmed=None if infected is None else infected == 1,
                    )
                ]
                if onsets or tests
                else [],
                surveys=states,
                has_self_reported_recovery=False,
            )
        )
        info[subject] = {
            "category": virus.category,
            "recruitment": study,
            "device": "none",
            "infected": "unknown" if infected is None else str(int(infected)),
        }
    return LabelSet(
        dataset_id=settings.dataset_id,
        subjects=inputs,
        subject_info=info,
        source_counts=counts,
        hr_days={},
        any_days={},
        wearable_rows=[],
        unlabeled_note=None,
        clock=settings.clock,
        extra_audit={},
        symptom_scores=scores,
    )
