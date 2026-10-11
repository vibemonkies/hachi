"""Pre-score context support counts and frozen fit/calibration eligibility."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from .data import Window
from .pretrained_protocol import PretrainedProtocol
from .protocol import Protocol
from .training import calibration_partition

type CutoffKey = tuple[str, datetime]


@dataclass(frozen=True)
class SupportCount:
    participants: int
    windows: int
    positive_windows: int
    negative_windows: int


def counts(rows: Sequence[Window]) -> SupportCount:
    return SupportCount(
        len({r.subject_id for r in rows}),
        len(rows),
        sum(r.positive for r in rows),
        sum(not r.positive for r in rows),
    )


def support_evidence(
    rows: Sequence[Window],
    train_subjects: Sequence[str],
    validation_subjects: Sequence[str],
    supported: frozenset[CutoffKey],
    task: Protocol,
    comparison: PretrainedProtocol,
) -> dict:
    """Labels determine counts only; no vector values or scores enter the support gate."""
    fit_subjects, calibration_subjects = calibration_partition(train_subjects, task)
    groups = {}
    for name, subjects in (
        ("fit", fit_subjects),
        ("calibration", calibration_subjects),
        ("validation", validation_subjects),
    ):
        selected = [r for r in rows if r.subject_id in subjects]
        groups[name] = {
            "eligible": counts(selected),
            "supported": counts([r for r in selected if (r.subject_id, r.cutoff) in supported]),
        }
    fit_count, cal_count = groups["fit"]["supported"], groups["calibration"]["supported"]
    reasons = []
    if fit_count.participants < comparison.min_context_supported_fit_participants:
        reasons.append("insufficient_context_supported_fit_participants")
    if cal_count.participants < comparison.min_context_supported_calibration_participants:
        reasons.append("insufficient_context_supported_calibration_participants")
    for name, count in (("fit", fit_count), ("calibration", cal_count)):
        if not count.positive_windows or not count.negative_windows:
            reasons.append(f"context_supported_{name}_lacks_both_outcome_classes")
    validation = groups["validation"]["supported"]
    return {
        "partitions": groups,
        "fit_status": reasons[0] if reasons else "supported",
        "unavailable_reasons": reasons,
        "supported_validation_ranking_status": (
            "estimable"
            if validation.positive_windows and validation.negative_windows
            else "unavailable_single_class_or_empty"
        ),
    }
