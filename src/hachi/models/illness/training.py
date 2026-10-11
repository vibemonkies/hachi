"""Fit/scaling on fit participants, sigmoid calibration/thresholds on separate participants."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from .data import Window
from .metrics import Score, scalar_metrics
from .protocol import Candidate, Protocol


def calibration_partition(
    subjects: Sequence[str], protocol: Protocol
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    ranked = sorted(
        subjects,
        key=lambda s: (
            hashlib.sha256(f"illness-calibration:{protocol.seed}:{s}".encode()).digest(),
            s,
        ),
    )
    count = max(1, int(len(ranked) * protocol.calibration_fraction))
    return tuple(sorted(ranked[count:])), tuple(sorted(ranked[:count]))


@dataclass
class Fitted:
    candidate: Candidate
    estimator: Pipeline | None
    prevalence: float
    calibrator: LogisticRegression
    threshold: float
    feature_count: int
    fit_subjects: tuple[str, ...]
    calibration_subjects: tuple[str, ...]

    def raw(self, rows: Sequence[Window]) -> np.ndarray:
        if self.estimator is None:
            return np.full(len(rows), self.prevalence)
        return self.estimator.predict_proba(_matrix(rows))[:, 1]

    def predict(self, rows: Sequence[Window]) -> list[Score]:
        if not rows:
            return []
        probability = self.calibrator.predict_proba(_logits(self.raw(rows)))[:, 1]
        return [
            Score(row, float(p), self.threshold) for row, p in zip(rows, probability, strict=True)
        ]


def _matrix(rows: Sequence[Window]) -> np.ndarray:
    return np.array([[np.nan if x is None else x for x in r.features] for r in rows], dtype=float)


def _logits(probability: np.ndarray) -> np.ndarray:
    p = np.clip(probability, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def choose_threshold(scores: Sequence[Score], protocol: Protocol) -> float:
    """Lowest threshold meeting the frozen calibration negative-time burden cap."""
    thresholds = sorted({s.probability for s in scores} | {1.000001})
    previous = 0.0
    for threshold in thresholds:
        rows = [Score(s.window, s.probability, threshold) for s in scores]
        burden = scalar_metrics(rows)["false_alert_episodes_per_30_negative_cutoff_days"]
        if burden is not None and burden <= (
            protocol.max_false_alert_episodes_per_30_negative_cutoff_days
        ):
            # Midpoints retain the chosen calibration alert set without binding
            # a decision to floating-point equality at a discrete predicted score.
            return (previous + threshold) / 2 if threshold <= 1 else threshold
        previous = threshold
    raise ValueError("threshold calibration requires observed negative cutoff-days")


def fit(
    candidate: Candidate, rows: Sequence[Window], train_subjects: Sequence[str], protocol: Protocol
) -> tuple[Fitted | None, str]:
    fit_subjects, calibration_subjects = calibration_partition(train_subjects, protocol)
    fit_rows = [r for r in rows if r.subject_id in fit_subjects]
    calibration_rows = [r for r in rows if r.subject_id in calibration_subjects]
    if {r.positive for r in fit_rows} != {False, True}:
        return None, "fit_cohort_lacks_both_outcome_classes"
    if {r.positive for r in calibration_rows} != {False, True}:
        return None, "calibration_cohort_lacks_both_outcome_classes"
    prevalence = sum(r.positive for r in fit_rows) / len(fit_rows)
    estimator = None
    if candidate != "prevalence":
        model = (
            LogisticRegression(C=protocol.logistic_c, max_iter=1000, random_state=protocol.seed)
            if candidate == "logistic"
            else DecisionTreeClassifier(
                max_depth=protocol.tree_max_depth,
                min_samples_leaf=protocol.tree_min_samples_leaf,
                random_state=protocol.seed,
            )
        )
        estimator = make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
            StandardScaler(),
            model,
        )
        estimator.fit(_matrix(fit_rows), [r.positive for r in fit_rows])
    calibrator = LogisticRegression(C=protocol.calibration_c, random_state=protocol.seed)
    fitted = Fitted(
        candidate,
        estimator,
        prevalence,
        calibrator,
        1.000001,
        len(fit_rows[0].features),
        fit_subjects,
        calibration_subjects,
    )
    calibrator.fit(_logits(fitted.raw(calibration_rows)), [r.positive for r in calibration_rows])
    fitted.threshold = choose_threshold(fitted.predict(calibration_rows), protocol)
    return fitted, "fitted"
