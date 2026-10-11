"""Selected at-risk window metrics, incident episodes and participant-level uncertainty."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import timedelta

from .data import Window
from .protocol import Protocol


@dataclass(frozen=True)
class Score:
    window: Window
    probability: float
    threshold: float

    @property
    def alert(self) -> bool:
        return self.probability >= self.threshold


def alert_groups(scores: Sequence[Score]) -> list[list[Score]]:
    """Only consecutive observed daily alerts merge; unknown gaps break episodes."""
    by_subject: dict[str, list[Score]] = defaultdict(list)
    for s in scores:
        if s.alert:
            by_subject[s.window.subject_id].append(s)
    groups = []
    for rows in by_subject.values():
        rows.sort(key=lambda s: s.window.cutoff)
        current: list[Score] = []
        for row in rows:
            if current and row.window.cutoff - current[-1].window.cutoff > timedelta(hours=24):
                groups.append(current)
                current = []
            current.append(row)
        if current:
            groups.append(current)
    return groups


def scalar_metrics(scores: Sequence[Score]) -> dict[str, float | None]:
    import numpy as np
    from sklearn.metrics import average_precision_score, roc_auc_score

    if not scores:
        return dict.fromkeys(
            (
                "prevalence",
                "auprc",
                "auroc",
                "brier",
                "ppv",
                "window_sensitivity",
                "event_sensitivity",
                "false_alert_episodes_per_30_negative_cutoff_days",
                "median_lead_time_min_hours",
                "median_lead_time_max_hours",
            )
        )
    y = np.array([s.window.positive for s in scores], dtype=int)
    p = np.array([s.probability for s in scores])
    alerts = np.array([s.alert for s in scores])
    positives, negatives = int(y.sum()), int((1 - y).sum())
    tp, ap = int((alerts & (y == 1)).sum()), int(alerts.sum())
    # Keys include participant so resampled replicas remain separate event units.
    events: dict[tuple[str, str], list[Score]] = defaultdict(list)
    for s in scores:
        if s.window.episode_id:
            events[(s.window.subject_id, s.window.episode_id)].append(s)
    detected = [rows for rows in events.values() if any(s.alert for s in rows)]
    lead_min, lead_max = [], []
    for rows in detected:
        first = min((s for s in rows if s.alert), key=lambda s: s.window.cutoff)
        w = first.window
        assert w.onset_first is not None and w.onset_end is not None
        lead_min.append((w.onset_first - w.cutoff).total_seconds() / 3600)
        lead_max.append((w.onset_end - w.cutoff).total_seconds() / 3600)
    false_groups = len(alert_groups([s for s in scores if not s.window.positive]))
    return {
        "prevalence": float(y.mean()),
        "auprc": float(average_precision_score(y, p)) if positives and negatives else None,
        "auroc": float(roc_auc_score(y, p)) if positives and negatives else None,
        "brier": float(np.mean((p - y) ** 2)),
        "ppv": tp / ap if ap else None,
        "window_sensitivity": tp / positives if positives else None,
        "event_sensitivity": len(detected) / len(events) if events else None,
        "false_alert_episodes_per_30_negative_cutoff_days": 30 * false_groups / negatives
        if negatives
        else None,
        "median_lead_time_min_hours": float(np.median(lead_min)) if lead_min else None,
        "median_lead_time_max_hours": float(np.median(lead_max)) if lead_max else None,
    }


def reliability(scores: Sequence[Score], bins: int) -> list[dict[str, int | float | None]]:
    import numpy as np

    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        rows = [
            s for s in scores if lo <= s.probability < hi or (i == bins - 1 and s.probability == 1)
        ]
        out.append(
            {
                "lower": lo,
                "upper": hi,
                "windows": len(rows),
                "mean_probability": float(np.mean([s.probability for s in rows])) if rows else None,
                "observed_fraction": float(np.mean([s.window.positive for s in rows]))
                if rows
                else None,
            }
        )
    return out


def resample(scores: Sequence[Score], subjects: Sequence[str]) -> list[Score]:
    by_subject: dict[str, list[Score]] = defaultdict(list)
    for score in scores:
        by_subject[score.window.subject_id].append(score)
    return [
        replace(s, window=replace(s.window, subject_id=f"replica-{i}"))
        for i, subject in enumerate(subjects)
        for s in by_subject[subject]
    ]


def interval(values: Sequence[float], protocol: Protocol) -> dict[str, float | int | None]:
    import numpy as np

    alpha = (1 - protocol.confidence_level) / 2
    return {
        "lower": float(np.quantile(values, alpha)) if values else None,
        "upper": float(np.quantile(values, 1 - alpha)) if values else None,
        "estimable_replicates": len(values),
    }


def report(scores: Sequence[Score], protocol: Protocol) -> dict:
    import numpy as np

    point = scalar_metrics(scores)
    subjects = sorted({s.window.subject_id for s in scores})
    rng = np.random.default_rng(protocol.seed)
    samples: dict[str, list[float]] = {k: [] for k in point}
    if subjects:
        for _ in range(protocol.bootstrap_replicates):
            metrics = scalar_metrics(resample(scores, rng.choice(subjects, len(subjects))))
            for key, value in metrics.items():
                if value is not None:
                    samples[key].append(value)
    groups = alert_groups(scores)
    return {
        "counts": {
            "participants": len(subjects),
            "windows": len(scores),
            "positive_windows": sum(s.window.positive for s in scores),
            "negative_cutoff_days": sum(not s.window.positive for s in scores),
            "incident_episodes": len(
                {(s.window.subject_id, s.window.episode_id) for s in scores if s.window.episode_id}
            ),
            "alerted_windows": sum(s.alert for s in scores),
            "alert_episodes": len(groups),
            "false_alert_episodes": len(alert_groups([s for s in scores if not s.window.positive])),
        },
        "metrics": point,
        "participant_bootstrap": {k: interval(v, protocol) for k, v in samples.items()},
        "reliability": reliability(scores, protocol.reliability_bins),
        "uncertainty_unit": "whole-participant; overlapping incident windows remain together",
        "burden_denominator": "evaluable survey-confirmed negative cutoff-days",
        "scope": "selected retrospective at-risk windows; not population prevalence/calibration",
    }


def paired_auprc(
    candidate: Sequence[Score], baseline: Sequence[Score], protocol: Protocol
) -> dict[str, float | int | None]:
    import numpy as np

    def keys(rows: Sequence[Score]):
        return [(s.window.subject_id, s.window.cutoff) for s in rows]

    if keys(candidate) != keys(baseline):
        raise ValueError("paired comparison requires identical ordered windows")
    subjects = sorted({s.window.subject_id for s in candidate})
    rng = np.random.default_rng(protocol.seed)
    differences = []
    for _ in range(protocol.bootstrap_replicates):
        chosen = rng.choice(subjects, len(subjects)) if subjects else []
        a = scalar_metrics(resample(candidate, chosen))["auprc"]
        b = scalar_metrics(resample(baseline, chosen))["auprc"]
        if a is not None and b is not None:
            differences.append(a - b)
    a, b = scalar_metrics(candidate)["auprc"], scalar_metrics(baseline)["auprc"]
    return {
        "difference": a - b if a is not None and b is not None else None,
        **interval(differences, protocol),
    }
