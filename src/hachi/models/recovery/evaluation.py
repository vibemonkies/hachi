"""Interval-aware scoring and participant-cluster uncertainty; no imputed dates."""

import random
from collections import defaultdict

from .survival import Observation, SurvivalModel, log_probability, truncate


def supported_horizon(
    rows: list[Observation], maximum: int, minimum_subjects: int, *, known_at_risk: bool = False
) -> int:
    """Training-only contiguous follow-up support, independent of held-out performance."""
    return max(
        (
            d
            for d in range(1, maximum + 1)
            if len(
                {
                    r.subject
                    for r in rows
                    if (r.upper >= d if not known_at_risk or r.lower is None else r.lower > d)
                }
            )
            >= minimum_subjects
        ),
        default=0,
    )


def observable_at(row: Observation, day: int) -> int | None:
    if row.lower is not None:
        if row.upper <= day:
            return 1
        if row.lower > day:
            return 0
    elif row.upper >= day:
        return 0
    return None


def calibration(
    rows: list[Observation], model: SurvivalModel, day: int, *, bootstrap: int = 0, seed: int = 42
) -> dict:
    if not rows:
        return {"day": day, "episodes": 0}
    predictions = [1 - model.survival(r.covariates, day)[day] for r in rows]
    outcomes = [observable_at(r, day) for r in rows]
    known = sum(y is not None for y in outcomes)
    positive = sum(y == 1 for y in outcomes)
    low, high = [], []
    for p, y in zip(predictions, outcomes, strict=True):
        losses = [(p - y) ** 2] if y is not None else [p * p, (1 - p) ** 2]
        low.append(min(losses))
        high.append(max(losses))
    result = {
        "day": day,
        "episodes": len(rows),
        "identified_outcomes": known,
        "ambiguous_or_censored": len(rows) - known,
        "mean_predicted_resolution": sum(predictions) / len(rows),
        "observed_resolution_fraction_bounds": [
            positive / len(rows),
            (positive + len(rows) - known) / len(rows),
        ],
        "brier_identification_bounds": [sum(low) / len(rows), sum(high) / len(rows)],
    }
    grouped: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        grouped[row.subject].append(i)
    subjects = sorted(grouped)
    rng = random.Random(seed)
    predicted, observed_low, observed_high = [], [], []
    for _ in range(bootstrap):
        draw = [i for s in rng.choices(subjects, k=len(subjects)) for i in grouped[s]]
        predicted.append(sum(predictions[i] for i in draw) / len(draw))
        observed_low.append(sum(outcomes[i] == 1 for i in draw) / len(draw))
        observed_high.append(sum(outcomes[i] != 0 for i in draw) / len(draw))
    result["mean_predicted_resolution_ci95"] = _interval(predicted)
    result["observed_lower_bound_ci95"] = _interval(observed_low)
    result["observed_upper_bound_ci95"] = _interval(observed_high)
    return result


def _interval(values: list[float]) -> list[float] | None:
    if not values:
        return None
    ordered = sorted(values)
    return [ordered[int((len(ordered) - 1) * p)] for p in (0.025, 0.975)]


def compare(
    rows: list[Observation],
    baseline: SurvivalModel,
    conditional: SurvivalModel,
    horizon: int,
    *,
    bootstrap: int,
    seed: int,
) -> tuple[dict, list[dict]]:
    """Primary proper censored log score at fixed common training-supported horizon.

    Wide intervals crossing the horizon supply only known pre-interval survival.
    Intervals starting day1 and ending past horizon have probability1 and carry
    no scoring information; report and omit these from the comparison.
    Bootstrap resamples whole held-out people, retaining all their episodes.
    This uncertainty conditions on fitted models and the active outer split.
    """
    paired = []
    for row in rows:
        if row.lower == 1 and row.upper > horizon:
            continue
        limited = truncate(row, horizon)
        paired.append(
            {
                "subject": row.subject,
                "episode": row.episode,
                "baseline_nll": -log_probability(baseline, limited),
                "conditional_nll": -log_probability(conditional, limited),
            }
        )
    result = summarize_scores(paired, bootstrap=bootstrap, seed=seed)
    result["excluded_no_information_at_horizon"] = len(rows) - len(paired)
    result["horizon_days"] = horizon
    return result, paired


def summarize_scores(paired: list[dict], *, bootstrap: int, seed: int) -> dict:
    """Pool disjoint inner validation people, preserving episode clusters."""
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for row in paired:
        by_subject[row["subject"]].append(row)
    rng = random.Random(seed)
    subjects = sorted(by_subject)
    samples = []
    for _ in range(bootstrap if subjects else 0):
        draw = [row for s in rng.choices(subjects, k=len(subjects)) for row in by_subject[s]]
        samples.append(sum(r["conditional_nll"] - r["baseline_nll"] for r in draw) / len(draw))
    result = {
        "episodes": len(paired),
        "subjects": len(subjects),
        "bootstrap_replicates": bootstrap,
        "uncertainty": "participant cluster percentile; fitted models/split fixed",
        "baseline_mean_nll": sum(r["baseline_nll"] for r in paired) / len(paired)
        if paired
        else None,
        "conditional_mean_nll": sum(r["conditional_nll"] for r in paired) / len(paired)
        if paired
        else None,
        "conditional_minus_baseline_nll_ci95": _interval(samples),
    }
    result["conditional_minus_baseline_mean_nll"] = (
        sum(r["conditional_nll"] - r["baseline_nll"] for r in paired) / len(paired)
        if paired
        else None
    )
    return result
