"""Support must come from the declared runtime mask, with both classes in calibration."""

from datetime import UTC, datetime
from pathlib import Path

from hachi.models.illness.data import Window
from hachi.models.illness.pretrained_protocol import load_pretrained_protocol
from hachi.models.illness.protocol import load_protocol
from hachi.models.illness.support import support_evidence
from hachi.models.illness.training import calibration_partition

TASK = load_protocol(Path("configs/experiments/illness/phase1.toml"))
COMPARISON = load_pretrained_protocol(Path("configs/experiments/illness/pretrained.json"))


def rows_for(subjects, positive):
    return [
        Window(
            s,
            datetime(2020, 1, 1 if positive else 2, tzinfo=UTC),
            24,
            positive,
            "synthetic-event" if positive else None,
            None,
            None,
            (0.0,),
        )
        for s in subjects
    ]


def test_supported_participants_do_not_impute_negative_calibration_outcomes():
    subjects = [f"synthetic-{i}" for i in range(24)]
    fit, cal = calibration_partition(subjects, TASK)
    validation = ["synthetic-val"]
    rows = rows_for(subjects + validation, True) + rows_for(subjects, False)
    # All people and both labels exist, but only positive calibration windows have contexts.
    supported = frozenset(
        (r.subject_id, r.cutoff) for r in rows if r.subject_id not in cal or r.positive
    )
    evidence = support_evidence(rows, subjects, validation, supported, TASK, COMPARISON)
    assert evidence["partitions"]["calibration"]["supported"].participants == len(cal)
    assert evidence["partitions"]["calibration"]["eligible"].negative_windows == len(cal)
    assert evidence["partitions"]["calibration"]["supported"].negative_windows == 0
    assert evidence["fit_status"] == "context_supported_calibration_lacks_both_outcome_classes"
    assert evidence["supported_validation_ranking_status"] == "unavailable_single_class_or_empty"
    assert evidence["partitions"]["fit"]["supported"].participants == len(fit)


def test_minimum_supported_people_applies_separately_to_fit_and_calibration():
    subjects = [f"synthetic-{i}" for i in range(24)]
    fit, cal = calibration_partition(subjects, TASK)
    rows = rows_for(subjects, True) + rows_for(subjects, False)
    for fit_n, cal_n, reason in [(3, 4, "fit"), (4, 3, "calibration")]:
        supported = frozenset(
            (r.subject_id, r.cutoff) for r in rows if r.subject_id in fit[:fit_n] + cal[:cal_n]
        )
        evidence = support_evidence(rows, subjects, [], supported, TASK, COMPARISON)
        assert evidence["fit_status"] == f"insufficient_context_supported_{reason}_participants"
    supported = frozenset((r.subject_id, r.cutoff) for r in rows)
    assert (
        support_evidence(rows, subjects, [], supported, TASK, COMPARISON)["fit_status"]
        == "supported"
    )
