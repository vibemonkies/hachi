"""Synthetic scientific-boundary regressions; no participant data in test fixtures."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from hachi.models.illness.artifacts import export, load, save
from hachi.models.illness.data import FeaturePoint, FeatureSet, Window, external_at, survey_features
from hachi.models.illness.metrics import Score, alert_groups, paired_auprc, report, scalar_metrics
from hachi.models.illness.protocol import load_protocol
from hachi.models.illness.training import calibration_partition, choose_threshold, fit

PROTOCOL = load_protocol(Path("configs/experiments/illness/phase1.toml"))
CUTOFF = datetime(2020, 1, 10, tzinfo=UTC)


def windows(subjects, *, horizon=24):
    out = []
    for i, sid in enumerate(subjects):
        for k in range(20):
            cutoff = CUTOFF + timedelta(days=k)
            positive = k % 4 == 0
            out.append(
                Window(
                    sid,
                    cutoff,
                    horizon,
                    positive,
                    f"{sid}-event-{k}" if positive else None,
                    cutoff + timedelta(hours=12) if positive else None,
                    cutoff + timedelta(hours=36) if positive else None,
                    (float(k % 4), float(i % 3), None if k % 3 else float(k)),
                )
            )
    return out


def test_surveys_end_of_day_and_future_perturbation():
    known = {date(2020, 1, 9): "symptom_free", date(2020, 1, 10): "symptomatic"}
    assert survey_features(known, CUTOFF, 7) == (1, 1, 0, 0)
    known[date(2020, 1, 10)] = "symptom_free"
    assert survey_features(known, CUTOFF, 7) == (1, 1, 0, 0)
    assert survey_features(known, CUTOFF + timedelta(days=1), 7) == (2, 2, 0, 0)


def test_external_backdated_late_and_stale_values_are_withheld():
    points = [
        FeaturePoint(
            subject_id="synthetic",
            at=CUTOFF - timedelta(days=1),
            available_at=CUTOFF,
            values=(2.0,),
        ),
        FeaturePoint(
            subject_id="synthetic",
            at=CUTOFF,
            available_at=CUTOFF + timedelta(hours=1),
            values=(999.0,),
        ),
    ]
    assert external_at(points, CUTOFF, 7) == (2.0,)
    assert external_at(points, CUTOFF + timedelta(days=10), 7) is None
    with pytest.raises(ValueError, match="duplicate feature points"):
        FeatureSet(
            feature_names=("x",),
            provenance_sha256="a" * 64,
            fit_subjects=(),
            clock="floating_local_shifted",
            points=(points[0], points[0]),
        )


@pytest.mark.parametrize("candidate", ["prevalence", "logistic", "tree"])
def test_participant_held_calibration_artifact_replay(candidate, tmp_path):
    subjects = [f"synthetic-{i}" for i in range(16)]
    rows = windows(subjects)
    fitted, status = fit(candidate, rows, subjects, PROTOCOL)
    assert status == "fitted"
    assert fitted is not None
    assert not set(fitted.fit_subjects) & set(fitted.calibration_subjects)
    artifact = export(
        fitted,
        ("a", "b", "c"),
        protocol_sha256=PROTOCOL.sha256,
        feature_sha256="b" * 64,
        training_sha256="c" * 64,
        horizon_hours=24,
    )
    ref = save(tmp_path / "model", artifact, "synthetic-test-model")
    replay = load(tmp_path / "model", ref)
    evaluation = windows(["new-synthetic-person"])
    assert np.allclose(
        [s.probability for s in fitted.predict(evaluation)],
        [s.probability for s in replay.predict(evaluation)],
        rtol=0,
        atol=1e-12,
    )
    assert [s.alert for s in fitted.predict(evaluation)] == [
        s.alert for s in replay.predict(evaluation)
    ]
    assert (tmp_path / "model/model.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="horizon"):
        replay.predict([replace(evaluation[0], horizon_hours=48)])
    model = tmp_path / "model/model.json"
    model.write_text(model.read_text() + " ")
    with pytest.raises(ValueError, match="checksum"):
        load(tmp_path / "model", ref)


def test_calibration_rows_cannot_change_scaler_or_classifier_fit():
    subjects = [f"synthetic-{i}" for i in range(16)]
    rows = windows(subjects)
    a, _ = fit("logistic", rows, subjects, PROTOCOL)
    _, calibration = calibration_partition(subjects, PROTOCOL)
    changed = [
        replace(r, features=(99999.0, -99999.0, 999.0)) if r.subject_id in calibration else r
        for r in rows
    ]
    b, _ = fit("logistic", changed, subjects, PROTOCOL)
    assert a is not None and b is not None
    np.testing.assert_array_equal(a.estimator[1].mean_, b.estimator[1].mean_)
    np.testing.assert_array_equal(a.estimator[2].coef_, b.estimator[2].coef_)


def test_single_class_fit_or_calibration_is_unavailable():
    subjects = [f"synthetic-{i}" for i in range(16)]
    rows = windows(subjects)
    _, calibration = calibration_partition(subjects, PROTOCOL)
    changed = [replace(r, positive=False) if r.subject_id in calibration else r for r in rows]
    fitted, status = fit("tree", changed, subjects, PROTOCOL)
    assert fitted is None and status == "calibration_cohort_lacks_both_outcome_classes"
    fitted, status = fit(
        "prevalence", [replace(r, positive=False) for r in rows], subjects, PROTOCOL
    )
    assert fitted is None and status == "fit_cohort_lacks_both_outcome_classes"


def test_repeated_positive_windows_count_one_incident_event_and_interval_lead():
    base = windows(["synthetic"])[0]
    rows = [
        replace(base, cutoff=CUTOFF - timedelta(days=1), horizon_hours=72),
        replace(base, horizon_hours=72),
    ]
    scores = [Score(r, 0.8, 0.5) for r in rows]
    summary = report(scores, PROTOCOL.model_copy(update={"bootstrap_replicates": 100}))
    assert summary["counts"]["positive_windows"] == 2
    assert summary["counts"]["incident_episodes"] == 1
    assert summary["counts"]["alert_episodes"] == 1
    assert summary["metrics"]["event_sensitivity"] == 1
    assert summary["metrics"]["median_lead_time_min_hours"] == 36
    assert summary["metrics"]["median_lead_time_max_hours"] == 60
    assert summary["metrics"]["auroc"] is None


def test_unknown_gap_breaks_alert_episode_and_burden_denominator_is_selected():
    base = replace(windows(["synthetic"])[1], cutoff=CUTOFF)
    rows = [
        base,
        replace(base, cutoff=CUTOFF + timedelta(days=1)),
        replace(base, cutoff=CUTOFF + timedelta(days=3)),
    ]
    scores = [Score(r, 0.8, 0.5) for r in rows]
    assert len(alert_groups(scores)) == 2
    assert scalar_metrics(scores)["false_alert_episodes_per_30_negative_cutoff_days"] == 20
    threshold = choose_threshold(scores, PROTOCOL)
    assert threshold > 1  # No attainable alert threshold meets the prespecified cap.


def test_participant_paired_difference_respects_same_windows():
    rows = windows(["synthetic-a", "synthetic-b"])
    a = [Score(r, 0.8 if r.positive else 0.1, 0.5) for r in rows]
    b = [Score(r, 0.25, 0.5) for r in rows]
    result = paired_auprc(a, b, PROTOCOL.model_copy(update={"bootstrap_replicates": 100}))
    assert result["lower"] > 0
    with pytest.raises(ValueError, match="identical"):
        paired_auprc(a, b[:-1], PROTOCOL)


def test_later_onset_never_erases_earlier_false_alert_episode():
    base = windows(["synthetic"])[0]
    negatives = [
        replace(
            base,
            cutoff=CUTOFF + timedelta(days=k),
            positive=False,
            episode_id=None,
            onset_first=None,
            onset_end=None,
        )
        for k in range(10)
    ]
    positive = replace(base, cutoff=CUTOFF + timedelta(days=10))
    scores = [Score(r, 0.5, 0.5) for r in [*negatives, positive]]
    assert len(alert_groups(scores)) == 1
    assert scalar_metrics(scores)["false_alert_episodes_per_30_negative_cutoff_days"] == 3
    assert choose_threshold(scores, PROTOCOL) > 1


def test_seven_day_history_has_seven_completed_days():
    surveys = {(CUTOFF - timedelta(days=k)).date(): "symptom_free" for k in range(1, 9)}
    assert survey_features(surveys, CUTOFF, 7) == (7, 7, 0, 0)
