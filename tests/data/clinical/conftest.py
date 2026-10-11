"""Synthetic sources in the layouts of the Stanford releases and the CMU five-study file.

Every value is generated here; nothing is copied from the real datasets.
"""

import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from hachi.data.clinical.config import Admission, AdmittedFile, load_definitions
from hachi.data.clinical.snapshot import sha256_file

EXCEL_EPOCH = date(1899, 12, 30)
DEFS = load_definitions().value


def _col(i: int) -> str:
    name = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        name = chr(65 + r) + name
    return name


def write_xlsx(path: Path, sheets: dict[str, list[list[object]]], extra: str = "") -> Path:
    """A minimal workbook: inline strings and numbers, one worksheet per entry."""
    book = "".join(
        f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(sheets, 1)
    )
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "xl/workbook.xml",
            f'{extra}<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{book}</sheets></workbook>",
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{rels}</Relationships>",
        )
        for i, rows in enumerate(sheets.values(), 1):
            body = []
            for r, row in enumerate(rows, 1):
                cells = []
                for c, value in enumerate(row):
                    ref = f"{_col(c)}{r}"
                    if value is None:
                        continue
                    if isinstance(value, int | float):
                        cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                    else:
                        cells.append(
                            f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                        )
                body.append(f'<row r="{r}">{"".join(cells)}</row>')
            z.writestr(
                f"xl/worksheets/sheet{i}.xml",
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"<sheetData>{''.join(body)}</sheetData></worksheet>",
            )
    return path


def stamps(days: list[date | None]) -> str:
    return "[" + ", ".join(f"Timestamp('{d} 00:00:00')" if d else "NaT" for d in days) + "]"


def excel(day: date) -> int:
    return (day - EXCEL_EPOCH).days


SYMPTOMS = [
    "aches_pains_matrix", "cough_matrix", "diarrhea_matrix", "fatigue_matrix", "headaches_matrix",
    "runny_nose_matrix", "shortness_breath_matrix", "sore_throat_matrix", "smell_matrix",
    "taste_matrix",
]  # fmt: skip

D0 = date(2025, 3, 1)


def day(n: int) -> date:
    return D0 + timedelta(days=n)


def phase1_workbook(path: Path) -> Path:
    """Three labeled participants plus the paper's header layout."""
    episodes = [
        ["Supplementary Table 3: synthetic"],
        ["Dates have been shifted"],
        [],
        ["ParticipantID", "Category", "Symptom_dates", "covid_diagnosis_dates", "recovery_dates"],
        # COVID-19 with a linked test, then a later unrelated illness 40 days on.
        ["AAAAAA1", "COVID-19", stamps([day(20), day(60)]), stamps([day(22)]), stamps([day(30)])],
        # Other illness without a recovery date.
        ["BBBBBB2", "Other Illness", stamps([day(15)]), stamps([None]), stamps([None])],
        # Positive test but no symptom date: infection without onset.
        ["CCCCCC3", "COVID-19", stamps([None]), stamps([day(40)]), stamps([None])],
    ]
    header = ["ParticipantID", "Date", "overall_feel", "temperature", "temp_units", *SYMPTOMS]
    surveys = [["Supplementary Table 5: synthetic"], ["severity 1-5"], ["smell"], [], header]

    def survey(subject, n, feel=None, **sym):
        row = [subject, excel(day(n)), feel, None, None]
        return row + [sym.get(s) for s in SYMPTOMS]

    # AAAAAA1: healthy surveys days 10-19, ill 20-24, unanswered row 25, symptom-free 26-35.
    for n in range(10, 20):
        surveys.append(survey("AAAAAA1", n, "Generally healthy"))
    for n in range(20, 25):
        surveys.append(survey("AAAAAA1", n, "Currently ill", cough_matrix="3"))
    surveys.append(survey("AAAAAA1", 25))
    for n in range(26, 36):
        surveys.append(survey("AAAAAA1", n, "Recovered from illness"))
    surveys.append(survey("AAAAAA1", 26, "Recovered from illness", fatigue_matrix="1"))
    return write_xlsx(
        path,
        {
            "SuppTable1_Demogr_FullCohort": [["n = 3"]],
            "SuppTable3_Fig2a_COVID-19": episodes,
            "SuppTable5_Fig2a_DailySymptoms": surveys,
        },
    )


def phase2_workbook(path: Path) -> Path:
    rows = [
        [
            "Participant ID",
            "COVID-19 Test Date",
            "COVID-19 Symptom Onset",
            "Retrospective / Prospective",
            "Device",
        ],
        ["P000001", str(day(32)), str(day(30)), "prospective", "Fitbit"],
        ["P000002", str(day(25)), "-", "retrospective", "AppleWatch"],
    ]
    return write_xlsx(path, {"SourceData_COVID19_Positives": rows})


def _minutes(start: datetime, count: int, step: int = 60) -> list[datetime]:
    return [start + timedelta(seconds=step * i) for i in range(count)]


def phase1_archive(path: Path, subjects: dict[str, tuple[int, int]]) -> Path:
    """Hourly HR and steps rows for each subject over a range of synthetic days."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("COVID-19-Wearables/", "")
        for subject, (first, last) in subjects.items():
            hr = ['"user","datetime","heartrate"']
            st = ['"user","datetime","steps"']
            for n in range(first, last + 1):
                for t in _minutes(datetime.combine(day(n), datetime.min.time()), 24, 3600):
                    hr.append(f'"{subject}","{t:%Y-%m-%d %H:%M:%S}",{60 + t.hour}')
                    st.append(f'"{subject}","{t:%Y-%m-%d %H:%M:%S}",{t.hour * 10}')
            z.writestr(f"COVID-19-Wearables/{subject}_hr.csv", "\n".join(hr) + "\n")
            z.writestr(f"COVID-19-Wearables/{subject}_steps.csv", "\n".join(st) + "\n")
    return path


def phase2_archive(path: Path, subjects: dict[str, tuple[int, int]]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("COVID-19-Phase2-Wearables/", "")
        z.writestr("__MACOSX/._COVID-19-Phase2-Wearables", "x")
        z.writestr("COVID-19-Phase2-Wearables/.DS_Store", "x")
        for subject, (first, last) in subjects.items():
            base = f"COVID-19-Phase2-Wearables/{subject}"
            hr, st = ["", "datetime,heartrate"], ["", "device,start_datetime,end_datetime,steps"]
            for n in range(first, last + 1):
                t = datetime.combine(day(n), datetime.min.time()) + timedelta(hours=9)
                hr.append(f"{t:%Y-%m-%d %H:%M:%S},70")
                st.append(f"HK Connect,{t:%Y-%m-%d %H:%M:%S},{t:%Y-%m-%d %H:%M:59},40")
            z.writestr(f"{base}/Orig_Fitbit_HR.csv", "\n".join(hr) + "\n")
            # A header repeated mid-file, and an hour without zero padding, as in real members.
            st.insert(3, "device,start_datetime,end_datetime,steps")
            st.append(f"HK Connect,{day(first)} 9:30:00,{day(first)} 9:30:59,40")
            z.writestr(f"{base}/Orig_NonFitbit_ST.csv", "\n".join(st) + "\n")
            z.writestr(
                f"{base}/Orig_Fitbit_ST.csv", "BigQuery error in query operation: Error processing"
            )
            z.writestr(f"{base}/Orig_NonFitbit_HR.csv", "\n\n")
    return path


def admission(dataset_id: str, *paths: Path) -> Admission:
    return Admission(
        dataset_id=dataset_id,
        dataset_version="synthetic-1",
        files={
            p.name: AdmittedFile(name=p.name, bytes=p.stat().st_size, sha256=sha256_file(p))
            for p in paths
        },
    )


CMU_DAYS = range(1, 7)


def cmu_header() -> list[str]:
    cols = ["subj_id", "study.id", "post.infected"]
    cols += ["rv2", "rv9", "rv14", "rv23", "rv39", "hanks", "cov229e", "rsv", "flu"]
    cols += [f"q{d}.jacksn_scr_adj" for d in CMU_DAYS] + [f"q{d}.cold" for d in CMU_DAYS]
    cols += [f"q{d}.shed" for d in range(1, 8)] + ["q1.mucwt"]
    return cols


def cmu_row(subj, study, infected, virus, scores, colds=None, shed=None) -> dict[str, str]:
    row = {c: "" for c in cmu_header()}
    row.update({"subj_id": str(subj), "study.id": str(study), "post.infected": infected})
    for v in ["rv2", "rv9", "rv14", "rv23", "rv39", "hanks", "cov229e", "rsv", "flu"]:
        row[v] = "1" if v == virus else "0"
    for d, s in zip(CMU_DAYS, scores, strict=False):
        row[f"q{d}.jacksn_scr_adj"] = "" if s is None else str(s)
    for d, c in zip(CMU_DAYS, colds or [], strict=False):
        row[f"q{d}.cold"] = str(c)
    for d, s in zip(range(1, 8), shed or [], strict=False):
        row[f"q{d}.shed"] = str(s)
    return row


def cmu_archive(path: Path, rows: list[dict[str, str]], member="FIVE_STUDY_DATA.dat") -> Path:
    header = cmu_header()
    lines = ["﻿" + "\t".join(header)] + ["\t".join(r[c] for c in header) for r in rows]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, "\r\n".join(lines) + "\r\n")
    return path
