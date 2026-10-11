"""Generated decisions exercise freeze integrity, never scientific model selection."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hachi.contracts.base import ArtifactRef
from hachi.contracts.manifests import RunManifest
from hachi.evaluation.finalization.development import (
    TASKS,
    DevelopmentReceipt,
    EvaluationIdentity,
    TaskSupport,
)
from hachi.evaluation.finalization.freeze import DocumentRef, FreezeRequest, freeze_decisions
from hachi.evaluation.finalization.integrity import EvidenceRefused, digest, verify_index
from hachi.evaluation.pmdata_run import PMDataProtocol
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.ensemble.selection import SelectionLog, SelectionRule

from ..conftest import BASE


@pytest.fixture
def freeze_inputs(tmp_path, manifest):
    root = tmp_path / "inputs"
    root.mkdir()
    repo = Path(__file__).resolve().parents[3]
    protocol = PMDataProtocol.model_validate_json(
        (repo / "configs/evaluation/pmdata-hourly-validation.json").read_bytes()
    )
    rule = SelectionRule.model_validate_json(
        (repo / "configs/experiments/pmdata-hourly-selection.json").read_bytes()
    )
    rule = rule.model_copy(
        update={"candidate_order": ["generated-model"], "ablations_not_candidates": []}
    )
    log = SelectionLog(document_sha256(rule), "generated-model", ())
    split = manifest.model_copy(update={"dataset_snapshot": protocol.expected_snapshot})
    run = RunManifest(
        schema_version="0.1",
        run_id="generated-selected",
        created_at_utc=BASE,
        git_sha="b" * 40,
        git_dirty=False,
        config_sha256=document_sha256(protocol.evaluation),
        dataset_snapshot=split.dataset_snapshot,
        split_manifest_sha256=document_sha256(split),
        task="physiology_forecast",
        feature_order=["heart_rate"],
        seed=split.seed,
        model={
            "model_id": "generated-model",
            "checkpoint_source": None,
            "checkpoint_revision": None,
            "license": None,
        },
        environment_sha256="c" * 64,
        artifact=ArtifactRef(artifact_id="generated-artifact", artifact_sha256="d" * 64),
        metrics_paths=["evaluation.json"],
    )
    support = [
        TaskSupport(
            task=t,
            status="development_evidence" if t == "physiology_forecast" else "blocked",
            reason="final_selection_pending"
            if t == "physiology_forecast"
            else "no_verified_development_evidence",
        )
        for t in TASKS
    ]
    receipt = DevelopmentReceipt(
        bundle_index_sha256="e" * 64,
        files_verified=1,
        artifact_bundle_index_sha256=[],
        evaluations=[
            EvaluationIdentity(
                run_sha256=document_sha256(run),
                split_sha256=document_sha256(split),
                config_sha256=run.config_sha256,
                evaluation_sha256="a" * 64,
                metric_definition_sha256="a" * 64,
                source_sha256="a" * 64,
                dataset_snapshot=run.dataset_snapshot,
                artifact=run.artifact,
                test_cohort_sha256=document_sha256(sorted(split.test_subjects)),
                development_cohort_sha256=document_sha256(
                    sorted(split.train_subjects + split.validation_subjects)
                ),
                scored_participants=2,
                scored_points=4,
            )
        ],
        comparison_sha256=[],
        task_support=support,
    )
    documents = {
        "development_receipt": receipt,
        "protocol": protocol,
        "selection_rule": rule,
        "selection_log": log,
        "experiment_config": {
            "protocol_sha256": document_sha256(protocol),
            "selection_rule_sha256": document_sha256(rule),
            "budget": "generated-test",
        },
        "preprocessing": {"decision": "generated-causal-prefix"},
        "thresholds": {"decision": "none"},
        "calibration": {"decision": "none"},
        "selected_run": run,
        "selected_split": split,
        "selected_config": protocol.evaluation,
    }
    refs = {}
    for name, doc in documents.items():
        raw = document_bytes(doc)
        path = f"{name}.json"
        (root / path).write_bytes(raw)
        refs[name] = DocumentRef(path=path, sha256=digest(raw))
    request = FreezeRequest(
        created_at_utc=BASE,
        development_receipts=[refs.pop("development_receipt")],
        task_support=support,
        **refs,
    )
    return root, request


def test_records_exact_decisions_but_never_authorizes_test(freeze_inputs, tmp_path):
    root, request = freeze_inputs
    output = tmp_path / "freeze"
    receipt = freeze_decisions(root, request, output)
    assert receipt.state == "decisions_frozen"
    assert receipt.readiness == "blocked_pending_acceptance" and not receipt.final_test_authorized
    assert receipt.calibration_sha256 == request.calibration.sha256
    assert receipt.selection_sha256 == digest((output / "selection.json").read_bytes())
    assert receipt.manifest_sha256 == digest((output / "manifest.json").read_bytes())
    assert len(verify_index(output, digest((output / "sha256.json").read_bytes()))) == 9
    with pytest.raises(FileExistsError):
        freeze_decisions(root, request, output)


@pytest.mark.parametrize("mutation", ["hash", "winner", "candidate_order", "cohort", "empty"])
def test_missing_or_inconsistent_frozen_evidence_is_refused(freeze_inputs, tmp_path, mutation):
    root, request = freeze_inputs
    name = {
        "hash": "thresholds",
        "winner": "selection_log",
        "candidate_order": "selection_log",
        "cohort": "selected_split",
        "empty": "calibration",
    }[mutation]
    ref = getattr(request, name)
    doc = json.loads((root / ref.path).read_bytes())
    if mutation == "hash":
        doc["decision"] = "changed"
    elif mutation == "winner":
        doc["selected"] = "unscored-model"
    elif mutation == "candidate_order":
        doc["steps"] = [
            {
                "candidate": "extra-model",
                "incumbent": "generated-model",
                "status": "not_available",
                "gates": {},
                "challenge": None,
            }
        ]
    elif mutation == "cohort":
        doc["test_subjects"] = ["replacement-person"]
    else:
        doc = {}
    raw = document_bytes(doc)
    (root / ref.path).write_bytes(raw)
    if mutation != "hash":
        request = request.model_copy(update={name: DocumentRef(path=ref.path, sha256=digest(raw))})
    with pytest.raises(EvidenceRefused):
        freeze_decisions(root, request, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()


def test_no_task_can_be_omitted_or_promoted_without_evidence(freeze_inputs, tmp_path):
    root, request = freeze_inputs
    with pytest.raises(ValidationError):
        FreezeRequest.model_validate(
            {**request.model_dump(), "task_support": request.task_support[:1]}
        )
    supported = [
        TaskSupport(task=t, status="development_evidence", reason="final_selection_pending")
        for t in TASKS
    ]
    changed = request.model_copy(update={"task_support": supported})
    with pytest.raises(EvidenceRefused, match="no verified development"):
        freeze_decisions(root, changed, tmp_path / "unsupported")
