"""Reconcile saved paired support and aggregates without consulting outcome labels."""

import math

from hachi.contracts.manifests import SplitManifest
from hachi.evaluation.comparison import ComparisonSummary, _paired_metrics
from hachi.evaluation.forecast import EvaluationConfig, EvaluationResult
from hachi.evaluation.metrics import combine_metric_reports

from .integrity import EvidenceRefused


def _bounded_total(paired: float, full: float, complete: bool) -> bool:
    # Both reports independently sum floating-point errors over the same labels.
    close = math.isclose(paired, full, rel_tol=1e-10, abs_tol=1e-10)
    return close if complete else paired <= full or close


def verify_paired_summary(
    summary: ComparisonSummary,
    baseline: EvaluationResult,
    candidate: EvaluationResult,
    split: SplitManifest,
) -> None:
    fields = EvaluationConfig.model_fields.keys() - {"pretrained_cohort_overlap", "overlap_note"}
    if any(getattr(baseline.config, k) != getattr(candidate.config, k) for k in fields):
        raise EvidenceRefused("paired evaluations use different scoring settings")
    b = summary.baseline_on_paired_targets
    c = summary.candidate_on_paired_targets
    b_full = {s.subject_id: s for s in baseline.metrics.subjects}
    c_full = {s.subject_id: s for s in candidate.metrics.subjects}
    if [s.subject_id for s in b.subjects] != [s.subject_id for s in c.subjects]:
        raise EvidenceRefused("paired reports do not share participant support")
    for report, full, result in ((b, b_full, baseline), (c, c_full, candidate)):
        if (
            len({s.subject_id for s in report.subjects}) != len(report.subjects)
            or (
                report.metric,
                report.unit,
                report.weighting,
                report.confidence,
                report.bootstrap_samples,
            )
            != (
                result.metrics.metric,
                result.metrics.unit,
                result.metrics.weighting,
                result.config.confidence,
                result.config.bootstrap_samples,
            )
            or any(
                s.subject_id not in full
                or not 0 < s.scored_points <= full[s.subject_id].scored_points
                or not 0
                <= s.interval_points
                <= min(s.scored_points, full[s.subject_id].interval_points)
                or any(
                    not math.isfinite(v) or v < 0 for v in (s.mae, s.rmse, s.median_pinball_loss)
                )
                or (s.interval_coverage is not None and not 0 <= s.interval_coverage <= 1)
                or (
                    s.mean_interval_width is not None
                    and (not math.isfinite(s.mean_interval_width) or s.mean_interval_width < 0)
                )
                for s in report.subjects
            )
        ):
            raise EvidenceRefused("paired report support or metric definitions disagree")
        for subject in report.subjects:
            all_points = full[subject.subject_id]
            complete = subject.scored_points == all_points.scored_points
            for name, power in (("mae", 1), ("rmse", 2), ("median_pinball_loss", 1)):
                if not _bounded_total(
                    getattr(subject, name) ** power * subject.scored_points,
                    getattr(all_points, name) ** power * all_points.scored_points,
                    complete,
                ):
                    raise EvidenceRefused("paired error totals exceed or differ from full support")
            if subject.interval_points == 0:
                if subject.interval_coverage is not None or subject.mean_interval_width is not None:
                    raise EvidenceRefused("paired interval metrics have no interval support")
            else:
                for name in ("interval_coverage", "mean_interval_width"):
                    paired_value = getattr(subject, name)
                    full_value = getattr(all_points, name)
                    if (
                        paired_value is None
                        or full_value is None
                        or not _bounded_total(
                            paired_value * subject.interval_points,
                            full_value * all_points.interval_points,
                            subject.interval_points == all_points.interval_points,
                        )
                    ):
                        raise EvidenceRefused("paired interval totals differ from full support")
        if combine_metric_reports([report], seed=split.seed) != report:
            raise EvidenceRefused("paired aggregate differs from its saved participant metrics")
    if any(
        (bs.scored_points, bs.interval_points) != (cs.scored_points, cs.interval_points)
        for bs, cs in zip(b.subjects, c.subjects, strict=True)
    ):
        raise EvidenceRefused("paired reports use different target support")
    counts = summary.counts
    expected = {
        "evaluation_participants": baseline.counts["evaluation_participants"],
        "expected_points": baseline.counts["expected_points"],
        "insufficient_history_points": baseline.counts["insufficient_history_points"],
        "missing_labels": baseline.counts["missing_labels"],
        "paired_points": sum(s.scored_points for s in b.subjects),
        "paired_interval_points": sum(s.interval_points for s in b.subjects),
        "paired_participants": len(b.subjects),
        "baseline_scored_points": baseline.counts["scored_points"],
        "candidate_scored_points": candidate.counts["scored_points"],
    }
    if (
        any(v < 0 for v in counts.values())
        or any(counts.get(k) != v for k, v in expected.items())
        or candidate.counts["missing_labels"] != expected["missing_labels"]
        or expected["baseline_scored_points"]
        != expected["paired_points"] + counts.get("baseline_only_points", -1)
        or expected["candidate_scored_points"]
        != expected["paired_points"] + counts.get("candidate_only_points", -1)
        or expected["expected_points"]
        != sum(
            counts.get(k, -1)
            for k in (
                "paired_points",
                "baseline_only_points",
                "candidate_only_points",
                "both_abstained_points",
                "missing_labels",
                "insufficient_history_points",
            )
        )
    ):
        raise EvidenceRefused("paired comparison counts disagree with its model reports")
    if summary.difference != _paired_metrics(b, c, baseline.config, split.seed):
        raise EvidenceRefused("paired difference disagrees with its saved participant metrics")
