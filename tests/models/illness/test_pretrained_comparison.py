"""Same-row paired metrics cannot hide unavailable folds or sentinel-derived support gaps."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hachi.models.illness.data import Window
from hachi.models.illness.metrics import Score
from hachi.models.illness.pretrained_comparison import compare
from hachi.models.illness.pretrained_protocol import load_pretrained_protocol
from hachi.models.illness.protocol import load_protocol

pytest.importorskip("sklearn", reason="comparison metrics require the baselines extra")
TASK = load_protocol(Path("configs/experiments/illness/phase1.toml")).model_copy(
    update={"bootstrap_replicates": 10}
)
FROZEN = load_pretrained_protocol(Path("configs/experiments/illness/pretrained.json"))


def fixture():
    rows = [
        Window(
            f"synthetic-{i}",
            datetime(2020, 1, 1, tzinfo=UTC),
            24,
            i < 2,
            "synthetic-event" if i < 2 else None,
            datetime(2020, 1, 2, tzinfo=UTC) if i < 2 else None,
            datetime(2020, 1, 3, tzinfo=UTC) if i < 2 else None,
            (0.0,) * 4,
        )
        for i in range(4)
    ]
    scored = [Score(w, 0.8 if w.positive else 0.2, 0.5) for w in rows]
    families = (*FROZEN.paired_baselines, "wbm_hr", "moment_hr", "chronos_hr")
    scores = {f: {h: list(scored) for h in FROZEN.head_candidates} for f in families}
    supported = {
        r.name: frozenset((w.subject_id, w.cutoff) for w in rows) for r in FROZEN.representations
    }
    return rows, scores, supported


def test_partial_scores_do_not_become_full_window_completion_or_negative_imputation():
    rows, scores, supported = fixture()
    for head in FROZEN.head_candidates:
        scores["chronos_hr"][head] = scores["chronos_hr"][head][1:]
    result = compare(scores, supported, rows, TASK, FROZEN)
    view = result["whole_window"]["chronos_hr"]["logistic"]
    assert view["eligible_windows"] == 4 and view["scored_windows"] == 3
    assert view["coverage_status"] == "partial_unavailable_folds"
    pair = result["paired_same_head"]["chronos_hr"]["logistic"]["survey-history"]["whole_window"]
    assert pair["paired_windows"] == 3 and pair["unpaired_windows"] == 1
    assert pair["auprc_difference"]["difference"] == 0.0
    assert result["selection"] == "descriptive_only_no_final_winner"
    assert result["outer_test"] == "sealed"


def test_common_context_requires_all_primary_runtime_flags_even_with_finite_predictions():
    rows, scores, supported = fixture()
    supported["moment_hr"] = frozenset((w.subject_id, w.cutoff) for w in rows[:2])
    result = compare(scores, supported, rows, TASK, FROZEN)
    for family in result["common_supported_context"].values():
        for view in family.values():
            assert view["eligible_windows"] == view["scored_windows"] == 2
            assert view["report"]["metrics"]["auprc"] is None
            assert view["report"]["metrics"]["auroc"] is None
            assert view["report"]["counts"]["negative_cutoff_days"] == 0
    supported["moment_hr"] = frozenset()
    result = compare(scores, supported, rows, TASK, FROZEN)
    assert result["common_supported_context"]["wbm_hr"]["tree"]["coverage_status"] == (
        "unavailable_no_eligible_windows"
    )


def test_paired_views_reject_different_outcomes_and_missing_families():
    rows, scores, supported = fixture()
    score = scores["wbm_hr"]["tree"][0]
    scores["wbm_hr"]["tree"][0] = replace(score, window=replace(score.window, positive=False))
    with pytest.raises(ValueError, match="paired labels"):
        compare(scores, supported, rows, TASK, FROZEN)
    del scores["wbm_hr"]
    with pytest.raises(ValueError, match="all frozen families"):
        compare(scores, supported, rows, TASK, FROZEN)
