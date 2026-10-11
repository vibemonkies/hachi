"""Freeze exact upstream decisions; never infer scientific acceptance or open test."""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from hachi.contracts.base import Contract, RelativePath, Sha256, UtcDatetime
from hachi.contracts.manifests import RunManifest, SplitManifest
from hachi.evaluation.serialization import document_bytes, document_sha256

from .development import TASKS, DevelopmentReceipt, TaskSupport
from .integrity import EvidenceRefused, digest, read_file, write_private


class DocumentRef(Contract):
    path: RelativePath
    sha256: Sha256


class FreezeRequest(Contract):
    """Private #20 assembly instructions, not a replacement for model-owner schemas."""

    format_version: Literal["hachi-freeze-request-1"] = "hachi-freeze-request-1"
    created_at_utc: UtcDatetime
    development_receipts: Annotated[list[DocumentRef], Field(min_length=1)]
    protocol: DocumentRef
    selection_rule: DocumentRef
    selection_log: DocumentRef
    experiment_config: DocumentRef
    preprocessing: DocumentRef
    thresholds: DocumentRef
    calibration: DocumentRef
    selected_run: DocumentRef
    selected_split: DocumentRef
    selected_config: DocumentRef
    task_support: list[TaskSupport]

    @model_validator(mode="after")
    def _tasks(self) -> Self:
        if len(self.task_support) != len(TASKS) or {s.task for s in self.task_support} != set(
            TASKS
        ):
            raise ValueError("freeze must explicitly retain every required task")
        return self


class FreezeReceipt(Contract):
    format_version: Literal["hachi-freeze-receipt-1"] = "hachi-freeze-receipt-1"
    state: Literal["decisions_frozen"] = "decisions_frozen"
    request_sha256: Sha256
    selection_sha256: Sha256
    calibration_sha256: Sha256
    manifest_sha256: Sha256
    readiness: Literal["blocked_pending_acceptance"] = "blocked_pending_acceptance"
    final_test_authorized: Literal[False] = False
    blockers: list[
        Literal[
            "task_acceptance",
            "selected_artifact_reproduction",
            "selection_packet_linkage",
            "independent_review",
            "parent_coordinated_test_opening",
        ]
    ]


def _read(root: Path, ref: DocumentRef) -> bytes:
    raw = read_file(root, ref.path)
    if digest(raw) != ref.sha256:
        raise EvidenceRefused("freeze input differs from its immutable document reference")
    return raw


def freeze_decisions(root: Path, request: FreezeRequest, output: Path) -> FreezeReceipt:
    """Record a consistent freeze using #12's own rule and log validator.

    Replaying the log's gates is an integrity check of a recorded decision, not a
    new selection experiment. Packet linkage, fresh selected inference, scientific
    support and independent acceptance remain explicit final-test prerequisites.
    """
    try:
        from hachi.models.ensemble.selection import SelectionLog, SelectionRule, judge
    except ModuleNotFoundError as exc:
        raise EvidenceRefused("upstream #12 selection contracts have not landed") from exc

    receipts = [
        DevelopmentReceipt.model_validate_json(_read(root, r)) for r in request.development_receipts
    ]
    rule = SelectionRule.model_validate_json(_read(root, request.selection_rule))
    log = TypeAdapter(SelectionLog).validate_json(_read(root, request.selection_log))
    protocol_raw = _read(root, request.protocol)
    from hachi.evaluation.pmdata_run import PMDataProtocol

    protocol = PMDataProtocol.model_validate_json(protocol_raw)
    if rule.protocol_sha256 != document_sha256(protocol):
        raise EvidenceRefused("selection rule and frozen protocol differ")
    if (
        log.rule_sha256 != document_sha256(rule)
        or rule.active_outer_fold != protocol.active_outer_fold
    ):
        raise EvidenceRefused("selection log, rule or active outer fold disagree")
    # Keep experiment settings verbatim; validate the two authoritative digest bindings.
    config = TypeAdapter(dict[str, object]).validate_json(_read(root, request.experiment_config))
    if config.get("protocol_sha256") != document_sha256(protocol) or config.get(
        "selection_rule_sha256"
    ) != document_sha256(rule):
        raise EvidenceRefused("experiment budgets do not bind the frozen rule and protocol")
    if [s.candidate for s in log.steps] != rule.candidate_order[1:]:
        raise EvidenceRefused("selection log omits or reorders declared candidates")
    incumbent = rule.candidate_order[0]
    for step in log.steps:
        if step.incumbent != incumbent:
            raise EvidenceRefused("selection incumbent chain is inconsistent")
        if step.status == "not_available":
            if step.challenge is not None or step.gates:
                raise EvidenceRefused("unavailable selection step carries scored evidence")
            continue
        evidence = step.challenge
        if evidence is None or (evidence.candidate, evidence.incumbent) != (
            step.candidate,
            incumbent,
        ):
            raise EvidenceRefused("selection step does not bind its challenge")
        gates = judge(evidence, rule.gates)
        if step.gates != gates or (step.status == "promoted") != all(gates.values()):
            raise EvidenceRefused("selection decision disagrees with its frozen budgets and gates")
        if step.status == "promoted":
            incumbent = step.candidate
    if log.selected != incumbent:
        raise EvidenceRefused("recorded winner differs from the validated selection chain")
    run = RunManifest.model_validate_json(_read(root, request.selected_run))
    split = SplitManifest.model_validate_json(_read(root, request.selected_split))
    from hachi.evaluation.forecast import EvaluationConfig

    config = EvaluationConfig.model_validate_json(_read(root, request.selected_config))
    if (
        run.git_dirty
        or run.artifact is None
        or run.model.model_id != log.selected
        or split.test_opened_at_utc is not None
        or run.split_manifest_sha256 != document_sha256(split)
        or run.dataset_snapshot != protocol.expected_snapshot
        or split.dataset_snapshot != run.dataset_snapshot
        or run.task != split.task
        or run.task != "physiology_forecast"
        or run.seed != split.seed
        or run.seed != protocol.folds.seed
        or run.config_sha256 != document_sha256(config)
        or config.data_mode != "real"
        or (config.metric, config.aggregation)
        != (protocol.evaluation.metric, protocol.evaluation.aggregation)
    ):
        raise EvidenceRefused("selected artifact, run or sealed split is inconsistent")
    same_data = [
        e for r in receipts for e in r.evaluations if e.dataset_snapshot == run.dataset_snapshot
    ]
    if not same_data or any(
        e.test_cohort_sha256 != document_sha256(sorted(split.test_subjects))
        or e.development_cohort_sha256
        != document_sha256(sorted(split.train_subjects + split.validation_subjects))
        for e in same_data
    ):
        raise EvidenceRefused("selected refit changes the sealed test or development cohort")
    evidence_tasks = {
        s.task for r in receipts for s in r.task_support if s.status == "development_evidence"
    }
    if any(
        s.status == "development_evidence" and s.task not in evidence_tasks
        for s in request.task_support
    ):
        raise EvidenceRefused("freeze task support has no verified development receipt")
    decisions = {
        name: _read(root, getattr(request, name))
        for name in ("preprocessing", "thresholds", "calibration")
    }
    # Decisions may explicitly specify 'none'; absence or mutation must still fail.
    for raw in decisions.values():
        if not TypeAdapter(dict[str, object]).validate_json(raw):
            raise EvidenceRefused("frozen decision documents cannot be empty")
    manifest = {
        "run": run,
        "split": split,
        "config": config,
        "development_receipts": [document_sha256(r) for r in receipts],
        "task_support": request.task_support,
    }
    selection = {
        "rule": rule,
        "log": log,
        "experiment_config_sha256": request.experiment_config.sha256,
    }
    receipt = FreezeReceipt(
        request_sha256=document_sha256(request),
        selection_sha256=document_sha256(selection),
        calibration_sha256=digest(decisions["calibration"]),
        manifest_sha256=document_sha256(manifest),
        blockers=[
            "task_acceptance",
            "selected_artifact_reproduction",
            "selection_packet_linkage",
            "independent_review",
            "parent_coordinated_test_opening",
        ],
    )
    write_private(
        output,
        {
            "request.json": document_bytes(request),
            "manifest.json": document_bytes(manifest),
            "selection.json": document_bytes(selection),
            "freeze.json": document_bytes(receipt),
            "protocol.json": protocol_raw,
            "experiment-config.json": _read(root, request.experiment_config),
            **{f"{k}.json": v for k, v in decisions.items()},
        },
    )
    return receipt
