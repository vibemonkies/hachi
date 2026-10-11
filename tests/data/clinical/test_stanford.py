"""Synthetic Stanford releases through adapter, snapshot, verify and report."""

import itertools
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from hachi.contracts.tables import StatusUnknown, SymptomEpisode, TestResult
from hachi.data.clinical import stanford
from hachi.data.clinical.config import load_definitions, load_stanford
from hachi.data.clinical.reconcile import reconcile
from hachi.data.clinical.report import render_markdown, write_report
from hachi.data.clinical.snapshot import (
    GitState,
    SnapshotError,
    build,
    read_outcomes,
    read_table,
    verify,
)
from hachi.data.clinical.wearables import WearableArchiveError
from hachi.data.clinical.windows import onset_labels

from .conftest import (
    admission,
    day,
    phase1_archive,
    phase1_workbook,
    phase2_archive,
    phase2_workbook,
)

GIT = GitState("0" * 40, False)
P1 = "stanford-covid19-wearables"
P2 = "stanford-covid19-wearables-phase2"


@dataclass
class Built:
    snapshot: Path
    report: dict
    data_dir: Path


def _build(tmp: Path, dataset_id: str, out: str = "derived") -> Built:
    settings = load_stanford(dataset_id)
    data = tmp / dataset_id
    adm = admission(
        dataset_id, data / settings.value.archive, data / settings.value.labels_workbook
    )
    result = build(
        lambda: stanford.label_set(data, settings.value, adm, workers=2),
        admission=adm,
        sources_read=[settings.value.archive, settings.value.labels_workbook],
        definitions=load_definitions(),
        settings=settings,
        pipeline_version=settings.value.pipeline_version,
        output_root=tmp / out,
        git=GIT,
    )
    return Built(result.path, result.report, data)


def _phase1_sources(tmp: Path) -> None:
    data = tmp / P1
    data.mkdir()
    settings = load_stanford(P1).value
    phase1_workbook(data / settings.labels_workbook)
    phase1_archive(
        data / settings.archive,
        {"AAAAAA1": (0, 70), "BBBBBB2": (0, 30), "DDDDDD4": (5, 40)},
    )


def _phase2_sources(tmp: Path) -> None:
    data = tmp / P2
    data.mkdir()
    settings = load_stanford(P2).value
    phase2_workbook(data / settings.labels_workbook)
    phase2_archive(data / settings.archive, {"P000001": (0, 40), "P000003": (0, 20)})


@pytest.fixture(scope="module")
def phase1(tmp_path_factory) -> Built:
    tmp = tmp_path_factory.mktemp("phase1")
    _phase1_sources(tmp)
    return _build(tmp, P1)


@pytest.fixture(scope="module")
def phase2(tmp_path_factory) -> Built:
    tmp = tmp_path_factory.mktemp("phase2")
    _phase2_sources(tmp)
    return _build(tmp, P2)


def test_phase1_snapshot_verifies_and_rows_are_contracts(phase1):
    outcome = verify(phase1.snapshot, full=True)
    assert outcome["ok"], outcome["problems"]
    rows = read_outcomes(phase1.snapshot)
    episodes = [r for r in rows if isinstance(r, SymptomEpisode)]
    tests = [r for r in rows if isinstance(r, TestResult)]
    assert {e.subject_id for e in episodes} == {"AAAAAA1", "BBBBBB2"}
    assert len(tests) == 2 and all(t.result == "positive" for t in tests)
    assert any(isinstance(r, StatusUnknown) and r.subject_id == "DDDDDD4" for r in rows)


def test_phase1_labels(phase1):
    episodes = {r["episode_id"]: r for r in read_table(phase1.snapshot, "episodes").to_pylist()}
    first, later = episodes["AAAAAA1-e1"], episodes["AAAAAA1-e2"]
    assert (first["category"], first["confidence"]) == ("covid19", "confirmed")
    assert later["category"] == "unspecified_illness"  # the COVID test belongs to e1
    assert first["hr_days_28d_before_onset"] == 20

    recovery = {
        (r["episode_id"], r["endpoint"]): r
        for r in read_table(phase1.snapshot, "recovery").to_pylist()
    }
    sustained = recovery[("AAAAAA1-e1", "sustained_symptom_free")]
    # Ill through day 24, a day-25 row with no answer, and day 26 has a symptomatic report.
    assert sustained["status"] == "resolved"
    assert (sustained["resolution_first_day"], sustained["resolution_last_day"]) == (
        day(27),
        day(27),
    )
    reported = recovery[("AAAAAA1-e1", "self_reported_recovery")]
    assert (reported["status"], reported["resolution_first_day"]) == ("resolved", day(30))
    assert recovery[("BBBBBB2-e1", "self_reported_recovery")]["reason"] == "not_reported"

    windows = {
        (w["subject_id"], w["cutoff_day"]): w
        for w in read_table(phase1.snapshot, "onset_windows").to_pylist()
    }
    assert windows[("AAAAAA1", day(20))]["onset_24h"] == "positive"
    assert windows[("AAAAAA1", day(10))]["onset_72h"] == "negative"
    assert windows[("AAAAAA1", day(22))]["onset_24h"] == "excluded_ongoing_episode"
    assert windows[("AAAAAA1", day(22))]["test_24h"] == "positive_test"
    assert windows[("DDDDDD4", day(10))]["onset_24h"] == "unknown_no_survey"
    # CCCCCC3 has one positive test and no symptom date or wearables: a one-day span, so no
    # cutoff has an earlier day to draw features from.
    assert not [key for key in windows if key[0] == "CCCCCC3"]


def test_phase1_report_is_aggregate(phase1):
    audit = phase1.report["audit"]
    assert audit["participants"]["with_outcome_labels"] == 3
    assert audit["participants"]["without_outcome_labels"] == 1
    assert audit["source_counts"]["survey_rows_without_any_answer"] == 1
    assert audit["source_counts"]["survey_days_with_conflicting_reports"] == 1
    text = json.dumps(phase1.report) + render_markdown(phase1.report)
    for subject in ("AAAAAA1", "BBBBBB2", "CCCCCC3", "DDDDDD4"):
        assert subject not in text
    assert str(day(20)) not in text


def test_rebuild_is_byte_identical(phase1, tmp_path):
    shutil.copytree(phase1.data_dir, tmp_path / P1)
    again = _build(tmp_path, P1)
    assert again.snapshot.name == phase1.snapshot.name
    for name in ("outcomes.parquet", "onset_windows.parquet", "audit.json", "manifest.json"):
        assert (again.snapshot / name).read_bytes() == (phase1.snapshot / name).read_bytes()


def test_snapshot_is_read_only_and_never_overwritten(phase1, tmp_path):
    assert not (phase1.snapshot / "outcomes.parquet").stat().st_mode & 0o222
    output = phase1.snapshot.parent
    data = phase1.data_dir
    settings = load_stanford(P1)
    adm = admission(P1, data / settings.value.archive, data / settings.value.labels_workbook)
    with pytest.raises(SnapshotError, match="never overwritten"):
        build(
            lambda: stanford.label_set(data, settings.value, adm, workers=1),
            admission=adm,
            sources_read=[settings.value.archive, settings.value.labels_workbook],
            definitions=load_definitions(),
            settings=settings,
            pipeline_version=settings.value.pipeline_version,
            output_root=output,
            git=GIT,
        )
    assert not [p for p in output.iterdir() if p.name.startswith(".building-")]


def test_tampering_is_detected(phase1, tmp_path):
    copy = tmp_path / phase1.snapshot.name
    shutil.copytree(phase1.snapshot, copy)
    target = copy / "episodes.parquet"
    target.chmod(0o600)
    table = pq.read_table(target)
    pq.write_table(table.slice(0, 1), target)
    outcome = verify(copy)
    assert not outcome["ok"]
    assert any("episodes.parquet" in p for p in outcome["problems"])


def test_unadmitted_source_is_refused(tmp_path):
    _phase1_sources(tmp_path)
    settings = load_stanford(P1)
    data = tmp_path / P1
    adm = admission(P1, data / settings.value.archive, data / settings.value.labels_workbook)
    with zipfile.ZipFile(data / settings.value.archive, "a") as z:
        z.writestr("COVID-19-Wearables/EEEEEE5_hr.csv", '"user","datetime","heartrate"\n')
    with pytest.raises(SnapshotError, match="differs from the admitted file"):
        stanford.label_set(data, settings.value, adm)


def test_unexpected_archive_member_is_refused(tmp_path):
    _phase1_sources(tmp_path)
    settings = load_stanford(P1)
    data = tmp_path / P1
    with zipfile.ZipFile(data / settings.value.archive, "a") as z:
        z.writestr("COVID-19-Wearables/notes.txt", "hello")
    adm = admission(P1, data / settings.value.archive, data / settings.value.labels_workbook)
    with pytest.raises(WearableArchiveError, match="unexpected member"):
        stanford.label_set(data, settings.value, adm)


def test_phase2_positives_and_archive_quirks(phase2, tmp_path):
    assert verify(phase2.snapshot, full=True)["ok"]
    audit = phase2.report["audit"]
    archive = audit["wearable_archive"]
    assert archive["members_by_state"] == {"empty": 2, "export_error": 2, "read": 4}
    assert archive["members_ignored"] == {"macos_metadata_or_directory": 3}
    assert archive["unparseable_timestamps"] == 2  # the repeated header rows
    assert archive["clock_check_steps_share_by_hour"] == {"09": 100.0}
    assert audit["participants"]["labeled_without_wearable_records"] == 1  # P000002
    assert audit["source_counts"]["asymptomatic_or_no_onset"] == 1
    episodes = read_table(phase2.snapshot, "episodes").to_pylist()
    assert [(e["subject_id"], e["confidence"], e["device"]) for e in episodes] == [
        ("P000001", "confirmed", "Fitbit")
    ]
    # No surveys are released: every non-excluded window is unknown, never negative.
    windows = read_table(phase2.snapshot, "onset_windows").to_pylist()
    assert "negative" not in {w["onset_24h"] for w in windows}
    recovery = read_table(phase2.snapshot, "recovery").to_pylist()
    assert {(r["endpoint"], r["reason"]) for r in recovery} == {
        ("sustained_symptom_free", "no_follow_up")
    }
    json_path, md_path = write_report(phase2.report, tmp_path / "reports")
    assert json_path.name == f"{phase2.snapshot.name.rsplit('-', 1)[0]}.json"
    assert "P000001" not in md_path.read_text() + json_path.read_text()


def test_any_cutoff_grid_matches_the_midnight_table(phase1):
    stored = read_table(phase1.snapshot, "onset_windows")
    midnight = onset_labels(phase1.snapshot, step_hours=24)
    columns = ["subject_id", "cutoff_utc", "onset_24h", "onset_48h", "onset_72h", "test_72h"]
    assert midnight.select(columns).to_pylist() == stored.select(columns).to_pylist()
    hourly = onset_labels(phase1.snapshot, step_hours=1, subjects=["AAAAAA1"])
    days = sum(s == "AAAAAA1" for s in stored.column("subject_id").to_pylist())
    assert hourly.num_rows == 24 * days
    labels = set(hourly.column("onset_24h").to_pylist())
    assert {"positive", "uncertain_partial_onset", "negative"} <= labels


def test_follow_up_tables(phase1):
    subjects = {r["subject_id"]: r for r in read_table(phase1.snapshot, "subjects").to_pylist()}
    assert subjects["DDDDDD4"]["in_label_tables"] is False
    assert subjects["AAAAAA1"]["episodes"] == 2 and subjects["AAAAAA1"]["survey_days"] > 0
    status = read_table(phase1.snapshot, "status_intervals", subjects=["AAAAAA1"]).to_pylist()
    kinds = {r["evidence"] for r in status}
    assert kinds == {"observed_symptom_free", "observed_symptomatic", "unknown"}
    for row in status:
        observed = row["evidence"] != "unknown"
        assert (row["availability_rule"] is not None) == observed
        assert row["interval_start_utc"] < row["interval_end_utc"]
    # Intervals tile the span exactly.
    ordered = sorted(status, key=lambda r: r["interval_start_utc"])
    for a, b in itertools.pairwise(ordered):
        assert a["interval_end_utc"] == b["interval_start_utc"]
    manifest = json.loads((phase1.snapshot / "manifest.json").read_text())
    assert set(manifest["availability_rules"]) == {
        "survey-available-at-end-of-its-local-day",
        "labels-known-at-end-of-participant-follow-up",
    }


@pytest.mark.parametrize("which", ["phase1", "phase2"])
def test_reconcile_against_source_workbook(which, request):
    built = request.getfixturevalue(which)
    dataset_id = P1 if which == "phase1" else P2
    settings = load_stanford(dataset_id).value
    outcome = reconcile(built.snapshot, built.data_dir / settings.labels_workbook, settings)
    assert outcome["ok"], outcome["mismatches"]
    assert outcome["checks"]["tests_match_reported_dates"] >= 2


def test_symptom_scores(phase1, phase2):
    rows = {
        (r["subject_id"], r["local_date"]): r
        for r in read_table(phase1.snapshot, "symptom_scores").to_pylist()
    }
    ill = rows[("AAAAAA1", day(20))]
    assert (ill["symptom_count"], ill["max_severity"], ill["severity_sum"]) == (1, 3, 3)
    assert ill["available_at_utc"].date() == day(21)
    assert ill["availability_rule"] == "survey-available-at-end-of-its-local-day"
    double = rows[("AAAAAA1", day(26))]  # two reports that day; the worst of each measure
    assert (double["reports"], double["symptom_count"], double["max_severity"]) == (2, 1, 1)
    assert rows[("AAAAAA1", day(10))]["symptom_count"] == 0
    assert ("AAAAAA1", day(25)) not in rows  # the row with no answer is not a survey
    surveys = read_table(phase1.snapshot, "surveys").num_rows
    assert len(rows) == surveys
    assert read_table(phase2.snapshot, "symptom_scores").num_rows == 0
