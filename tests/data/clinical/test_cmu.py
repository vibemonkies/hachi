"""The CMU adapter on a synthetic five-study file. No CMU data is read by any test."""

from datetime import timedelta

import pytest

from hachi.data.clinical import cmu
from hachi.data.clinical.config import load_definitions
from hachi.data.clinical.reconcile import reconcile_cmu
from hachi.data.clinical.snapshot import GitState, build, read_table, verify

from .conftest import admission, cmu_archive, cmu_row


def _unregistered():
    settings = cmu.load_settings().value
    return settings.model_copy(update={"analysis_registration": cmu.AnalysisRegistration()})


def _registered():
    loaded = cmu.load_settings()
    registration = cmu.AnalysisRegistration(
        submitted_on=loaded.value.relative_day_epoch, reference="synthetic test"
    )
    return loaded, loaded.value.model_copy(update={"analysis_registration": registration})


ROWS = [
    # PCS2, RV39, infected: symptomatic days 2-4, symptom-free 5-6 -> resolves.
    cmu_row(101, 2, "1", "rv39", [0, 3, 5, 2, 0, 1], colds=[0, 1, 1, 1, 0, 0], shed=[0, 1, 1]),
    # PCS1, not infected, symptomatic day 1, then intermediate (cold=1) day 2: never resolves.
    cmu_row(102, 1, "0", "rv39", [2, 1, 2, 3, 2], colds=[1, 1, 1, 1, 1]),
    # PMBC influenza: no symptoms, shedding positive -> infection without onset.
    cmu_row(103, 4, "1", "flu", [0, 0, 1, 0, 0, 0], colds=[0] * 6, shed=[1, 1]),
    # BCS: no daily Jackson scores in the five-study file -> excluded.
    cmu_row(104, 0, "1", "rv9", [None] * 6),
]


def test_gate_refuses_without_registration_and_records_it():
    with pytest.raises(SystemExit, match="Data Analysis Form"):
        cmu.require_registered_analysis(_unregistered())
    recorded = cmu.load_settings().value.analysis_registration
    assert recorded.submitted_on is not None and recorded.reference
    cmu.require_registered_analysis(cmu.load_settings().value)


def test_label_set_refuses_before_registration(tmp_path):
    archive = cmu_archive(tmp_path / cmu.load_settings().value.data_file_archive, ROWS)
    with pytest.raises(SystemExit):
        cmu.label_set(tmp_path, _unregistered(), admission(cmu.DATASET_ID, archive))


def test_cmu_labels_on_synthetic_rows(tmp_path):
    loaded, settings = _registered()
    archive = cmu_archive(tmp_path / settings.data_file_archive, ROWS)
    adm = admission(cmu.DATASET_ID, archive)
    result = build(
        lambda: cmu.label_set(tmp_path, settings, adm),
        admission=adm,
        sources_read=[settings.data_file_archive],
        definitions=load_definitions(),
        settings=loaded,
        pipeline_version=settings.pipeline_version,
        output_root=tmp_path / "derived",
        git=GitState("0" * 40, False),
    )
    assert verify(result.path, full=True)["ok"]
    epoch = settings.relative_day_epoch
    episodes = {e["subject_id"]: e for e in read_table(result.path, "episodes").to_pylist()}
    assert set(episodes) == {"pcs2-101", "pcs1-102"}
    first = episodes["pcs2-101"]
    # First symptomatic rating on day 2: onset after day 1's assessment, by day 2.
    assert (first["onset_first_day"], first["onset_last_day"]) == (
        epoch + timedelta(days=1),
        epoch + timedelta(days=2),
    )
    assert (first["category"], first["confidence"]) == ("rhinovirus_challenge", "confirmed")
    assert episodes["pcs1-102"]["confidence"] == "uncertain"

    recovery = {
        r["subject_id"]: r
        for r in read_table(result.path, "recovery").to_pylist()
        if r["endpoint"] == "sustained_symptom_free"
    }
    assert recovery["pcs2-101"]["status"] == "resolved"
    assert recovery["pcs2-101"]["resolution_first_day"] == epoch + timedelta(days=5)
    assert (recovery["pcs1-102"]["status"], recovery["pcs1-102"]["reason"]) == (
        "right_censored",
        "no_qualifying_run",
    )
    assert recovery["pcs1-102"]["follow_up_last_day"] == epoch + timedelta(days=5)

    counts = result.report["audit"]["source_counts"]
    assert counts["excluded_no_daily_symptom_scores_bcs"] == 1
    assert counts["infected_1"] == 2 and counts["infected_0"] == 1
    tests = result.report["audit"]["tests"]["by_pathogen_and_result"]
    assert tests == {"influenza:positive": 2, "other:negative": 1, "other:positive": 2}
    scores = {
        (r["subject_id"], r["local_date"]): r
        for r in read_table(result.path, "symptom_scores").to_pylist()
    }
    third = scores[("pcs2-101", epoch + timedelta(days=3))]
    assert (third["jackson_adjusted"], third["cold_or_flu"]) == (5.0, True)
    assert third["scale"] == "cmu-modified-jackson-8-items-baseline-adjusted"
    windows = read_table(result.path, "onset_windows", subjects=["pmbc-103"]).to_pylist()
    assert {w["onset_24h"] for w in windows} == {"excluded_infection_without_onset"}

    outcome = reconcile_cmu(result.path, archive, settings)
    assert outcome["ok"], outcome["mismatches"]
    assert outcome["checks"]["shedding_cultures_match"] == 3
    assert outcome["checks"]["onset_is_first_symptomatic_day"] == 2


def test_errors_and_odd_codes_never_echo_cell_values(tmp_path):
    _, settings = _registered()
    odd = cmu_row(201, 3, "7", "rv39", [3, 1, 0, 0, 0], colds=[2, 0, 0, 0, 0], shed=[5])
    archive = cmu_archive(tmp_path / settings.data_file_archive, [odd])
    counts = cmu.label_set(tmp_path, settings, admission(cmu.DATASET_ID, archive)).source_counts
    assert counts["non_binary_infected"] == 1
    assert counts["non_binary_cold"] == 1 and counts["non_binary_shed"] == 1

    bad = cmu_row(202, 3, "1", "rv39", ["SECRET-VALUE", 1, 0, 0, 0])
    archive = cmu_archive(tmp_path / settings.data_file_archive, [bad])
    with pytest.raises(cmu.CmuError) as raised:
        cmu.label_set(tmp_path, settings, admission(cmu.DATASET_ID, archive))
    assert "q1.jacksn_scr_adj" in str(raised.value)
    assert "SECRET" not in str(raised.value)
