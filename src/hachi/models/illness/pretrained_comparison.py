"""Paired descriptive views with explicit scored coverage and shared runtime support."""

from collections.abc import Sequence
from dataclasses import replace

from .data import Window
from .metrics import Score, paired_auprc, report
from .pretrained_protocol import PretrainedProtocol
from .protocol import Protocol
from .support import CutoffKey


def compare(
    scores: dict[str, dict[str, Sequence[Score]]],
    supported: dict[str, frozenset[CutoffKey]],
    eligible: Sequence[Window],
    task: Protocol,
    comparison: PretrainedProtocol,
) -> dict:
    """One horizon, untouched inner-validation rows; blocked folds are never filled in.

    Callers verify private run receipts and eligible snapshot labels before this pure step.
    Missing scored folds reduce pair coverage explicitly; they cannot become a complete result.
    """
    families = tuple(
        dict.fromkeys((*comparison.paired_baselines, *(r.name for r in comparison.representations)))
    )
    representations = {r.name for r in comparison.representations}
    if set(scores) != set(families) or set(supported) != representations:
        raise ValueError("paired views require all frozen families and runtime support sets")
    target = {(w.subject_id, w.cutoff): w for w in eligible}
    if len(target) != len(eligible) or len({w.horizon_hours for w in eligible}) > 1:
        raise ValueError("paired views require unique eligible cutoffs at one horizon")
    indices = {}
    for family in families:
        if tuple(scores[family]) != comparison.head_candidates:
            raise ValueError("paired views require every fixed head in frozen order")
        indices[family] = {}
        for head, rows in scores[family].items():
            keyed = {(s.window.subject_id, s.window.cutoff): s for s in rows}
            if len(keyed) != len(rows) or not set(keyed) <= set(target):
                raise ValueError("scored windows repeat or fall outside eligible validation")
            if any(
                replace(s.window, features=s.window.features[:4]) != target[key]
                for key, s in keyed.items()
            ):
                raise ValueError("paired labels, horizons or causal survey features differ")
            indices[family][head] = keyed
    common = set(target).intersection(*(supported[name] for name in sorted(representations)))

    def coverage(scored: int, wanted: int) -> str:
        if not wanted:
            return "unavailable_no_eligible_windows"
        if not scored:
            return "unavailable_no_scores"
        return "complete" if scored == wanted else "partial_unavailable_folds"

    def view(index, keys):
        selected = sorted(set(index) & keys)
        return {
            "eligible_windows": len(keys),
            "scored_windows": len(selected),
            "unscored_windows": len(keys) - len(selected),
            "coverage_status": coverage(len(selected), len(keys)),
            "report": report([index[k] for k in selected], task),
        }

    full, shared, paired = {}, {}, {}
    for family in families:
        full[family], shared[family], paired[family] = {}, {}, {}
        for head in comparison.head_candidates:
            index = indices[family][head]
            full[family][head] = view(index, set(target))
            shared[family][head] = view(index, common)
            pairs = {}
            for baseline in comparison.paired_baselines:
                if baseline == family:
                    continue
                baseline_index = indices[baseline][head]
                pairs[baseline] = {}
                for name, wanted in (("whole_window", set(target)), ("common_context", common)):
                    keys = sorted(wanted & set(index) & set(baseline_index))
                    pairs[baseline][name] = {
                        "eligible_windows": len(wanted),
                        "paired_windows": len(keys),
                        "unpaired_windows": len(wanted) - len(keys),
                        "coverage_status": coverage(len(keys), len(wanted)),
                        "auprc_difference": paired_auprc(
                            [index[k] for k in keys], [baseline_index[k] for k in keys], task
                        ),
                    }
            paired[family][head] = pairs
    return {
        "whole_window": full,
        "common_supported_context": shared,
        "paired_same_head": paired,
        "common_context_definition": "intersection-of-all-four-runtime-supported-primary-vectors",
        "selection": "descriptive_only_no_final_winner",
        "population_calibration": "unsupported_selected_survey_cohort",
        "outer_test": "sealed",
    }
