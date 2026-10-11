import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hachi.evaluation.metrics import Estimate
from hachi.evaluation.pmdata_run import PMDataProtocol
from hachi.evaluation.serialization import document_sha256
from hachi.models.ensemble import Challenge, SelectionGates, SelectionRule, judge, select

ROOT = Path(__file__).resolve().parents[3]


def rule() -> SelectionRule:
    path = ROOT / "configs/experiments/pmdata-hourly-selection.json"
    return SelectionRule.model_validate_json(path.read_bytes())


def evidence(candidate, incumbent, *, mae=(-2.0, -3.0, -1.0), coverage=0.8, abstain=0.0):
    return Challenge(
        candidate,
        incumbent,
        100,
        Estimate(mae[0], 12, (mae[1], mae[2])),
        Estimate(mae[0] / 2, 12, (mae[1] / 2, mae[2] / 2)),
        Estimate(coverage, 12, (coverage - 0.03, coverage + 0.03)) if coverage else None,
        abstain,
        0.0,
        0.02,
        2**30,
    )


def test_committed_rule_binds_the_frozen_protocol():
    selected = rule()
    protocol = PMDataProtocol.model_validate_json(
        (ROOT / "configs/evaluation/pmdata-hourly-validation.json").read_bytes()
    )
    assert selected.protocol_sha256 == document_sha256(protocol)
    assert selected.active_outer_fold == protocol.active_outer_fold
    assert selected.candidate_order[0] == "train-population-mean-v1"
    adaptation = json.loads(
        (ROOT / "configs/experiments/pmdata-hourly-adaptation.json").read_text()
    )
    assert adaptation["selection_rule_sha256"] == document_sha256(selected)
    assert adaptation["protocol_sha256"] == selected.protocol_sha256


def test_every_gate_must_pass_and_missing_evidence_fails():
    gates = SelectionGates()
    assert all(judge(evidence("b", "a"), gates).values())
    straddling = judge(evidence("b", "a", mae=(-1.0, -2.0, 0.1)), gates)
    assert not straddling["paired_mae_upper_below"]
    assert not judge(evidence("b", "a", coverage=None), gates)["coverage_in_range"]
    assert not judge(evidence("b", "a", coverage=0.6), gates)["coverage_in_range"]
    assert not judge(evidence("b", "a", abstain=0.06), gates)["abstention_within"]
    no_ci = Challenge("b", "a", 1, Estimate(-5.0, 1, None), None, None, 0.0, 0.0, None, None)
    verdict = judge(no_ci, gates)
    assert verdict.pop("abstention_within") and not any(verdict.values())


def test_chain_compares_each_challenger_with_the_current_incumbent():
    order = ["a", "b", "c", "d"]
    selected = rule().model_copy(update={"candidate_order": order, "ablations_not_candidates": []})
    seen = []

    def challenge(candidate, incumbent):
        seen.append((candidate, incumbent))
        return evidence(
            candidate, incumbent, mae=(-1.0, -2.0, 0.5) if candidate == "c" else (-2.0, -3.0, -1.0)
        )

    log = select(selected, "f" * 64, ["a", "b", "c"], challenge)
    assert seen == [("b", "a"), ("c", "b")]
    assert [s.status for s in log.steps] == ["promoted", "kept_incumbent", "not_available"]
    assert log.selected == "b"
    with pytest.raises(ValueError, match="default"):
        select(selected, "f" * 64, ["b"], challenge)


def test_rule_refuses_repeats_and_overlapping_ablations():
    data = rule().model_dump()
    with pytest.raises(ValidationError, match="repeat"):
        SelectionRule.model_validate({**data, "candidate_order": ["a", "a"]})
    with pytest.raises(ValidationError, match="ablation"):
        SelectionRule.model_validate(
            {**data, "ablations_not_candidates": [data["candidate_order"][1]]}
        )
