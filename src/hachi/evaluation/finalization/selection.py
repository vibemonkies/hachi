"""Verify #12's original selection-to-packet links, without selecting or freezing a model."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from hachi.contracts.base import (
    Contract,
    DatasetSnapshotRef,
    GitSha,
    Identifier,
    RelativePath,
    Sha256,
)
from hachi.contracts.manifests import RunManifest
from hachi.evaluation.comparison import ComparisonSummary
from hachi.evaluation.metrics import Estimate, bootstrap_participant_mean, combine_metric_reports
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.ensemble.selection import Challenge, judge

from .development import DevelopmentReceipt, _packet, validate_development
from .exports import _protocol
from .integrity import EvidenceRefused, digest, read_file, read_producing_file
from .owner12 import owner_experiment


class _OriginalLink(Contract):
    path: RelativePath
    comparison: Sha256 = Field(alias="comparison.json")
    inventory: Sha256 = Field(alias="sha256.json")


class _OriginalStep(Contract):
    candidate: Identifier
    incumbent: Identifier
    status: Literal["promoted", "kept_incumbent", "not_available"]
    gates: dict[str, bool]
    evidence: Challenge | None
    packets: dict[Identifier, _OriginalLink]


class _OriginalLog(Contract):
    selected: Identifier
    rule_sha256: Sha256
    steps: list[_OriginalStep]


class _Candidate(Contract):
    family: Literal["comparator", "ridge", "chronos", "finetuned", "ensemble", "external"]
    mae: Estimate | None
    rmse: Estimate | None
    interval_coverage: Estimate | None
    mean_interval_width: Estimate | None
    abstention_share: Annotated[float, Field(ge=0, le=1)]
    counts: dict[str, Annotated[int, Field(ge=0)]]


class _Score(Contract):
    """Boundary parser for the existing owner's issue12-pmdata-score-1 document.

    Ancillary fields remain opaque: their exact bytes are pinned, but this adapter
    makes no acceptance claim about optimizer, ablation or embedding metadata.
    """

    format: Literal["issue12-pmdata-score-1"]
    git_sha: GitSha
    git_dirty: Literal[False]
    environment_sha256: Sha256
    export_git_sha: GitSha
    protocol_sha256: Sha256
    selection_rule_sha256: Sha256
    adaptation_sha256: Sha256
    context_policy_sha256: Sha256
    dataset_snapshot: DatasetSnapshotRef
    outer_test_sealed: Literal[True]
    validation_participants: Annotated[int, Field(gt=0)]
    inner_folds: Annotated[int, Field(ge=2)]
    requests: object
    zero_shot_predictions_sha256: Sha256
    embeddings_sha256: Sha256
    candidates: dict[Identifier, _Candidate]
    selection: _OriginalLog
    ablations: object
    external_11: object
    ensemble_support: object
    residual_offsets: object
    finetune: object
    costs: dict[Identifier, dict[str, object]]
    packets_evaluation_sha256: dict[RelativePath, Sha256]


class PacketLink(Contract):
    path: RelativePath
    comparison_sha256: Sha256
    index_sha256: Sha256


class LinkedStep(Contract):
    candidate: Identifier
    incumbent: Identifier
    status: Literal["promoted", "kept_incumbent", "not_available"]
    gates: dict[str, bool]
    evidence: Challenge | None
    packets: dict[str, PacketLink]


class SelectionEvidence(Contract):
    format_version: Literal["hachi-selection-evidence-1"] = "hachi-selection-evidence-1"
    state: Literal["development_selection_links_verified"] = "development_selection_links_verified"
    score_summary_sha256: Sha256
    score_index_sha256: Sha256
    producing_git_sha: GitSha
    export_git_sha: GitSha
    owner_documents_sha256: dict[RelativePath, Sha256]
    export_documents_sha256: dict[RelativePath, Sha256]
    rule_sha256: Sha256
    adaptation_sha256: Sha256
    context_policy_sha256: Sha256
    owner_reported_selected: Identifier
    selected_evaluation_sha256: list[Sha256]
    development_receipt: DevelopmentReceipt
    steps: list[LinkedStep]
    scientific_selection_accepted: Literal[False] = False
    final_test_authorized: Literal[False] = False
    limitations: list[str]


def _abstention(results: Sequence) -> float:
    abstained = sum(r.counts["abstained_points"] for r in results)
    scored = sum(r.counts["scored_points"] for r in results)
    return abstained / (abstained + scored) if abstained + scored else 1.0


def validate_selection_links(
    root: Path,
    expected_index_sha256: str,
    repo: Path,
    *,
    index_path: Path,
    expected_summary_sha256: str,
) -> SelectionEvidence:
    """Consume issue12-pmdata-score-1 exactly as written by training.score.

    The summary and sibling inventory each need an external original-byte pin.
    Untyped ancillary owner metadata stays pinned in the original summary, never
    copied to the aggregate output or promoted to independently verified evidence.
    """
    receipt = validate_development(root, expected_index_sha256, repo, index_path=index_path)
    raw = read_file(root, "aggregate-summary.json")
    if digest(raw) != expected_summary_sha256:
        raise EvidenceRefused("selection summary differs from its original external pin")
    summary = _Score.model_validate_json(raw).model_dump(mode="json", by_alias=True)
    revision = TypeAdapter(GitSha).validate_python(summary["git_sha"])
    owner = owner_experiment(repo, revision)
    exported = owner_experiment(repo, summary["export_git_sha"])
    protocol, rule = owner.protocol, owner.rule
    # Export receipts predate the reported-comparator amendment. Bind both
    # original documents; only that explicit amendment can differ at scoring.
    scoring_adaptation = {k: v for k, v in owner.adaptation.items() if k != "amendment_2"}
    export_adaptation = {k: v for k, v in exported.adaptation.items() if k != "amendment_2"}
    if (
        summary["format"] != "issue12-pmdata-score-1"
        or summary["git_dirty"] is not False
        or summary["outer_test_sealed"] is not True
        or summary["protocol_sha256"] != document_sha256(protocol)
        or summary["selection_rule_sha256"] != document_sha256(rule)
        or summary["adaptation_sha256"] != exported.adaptation_sha256
        or scoring_adaptation != export_adaptation
        or exported.protocol != protocol
        or exported.rule != rule
        or exported.chronos != owner.chronos
        or exported.context != owner.context
        or exported.variants != owner.variants
        or summary["context_policy_sha256"] != document_sha256(owner.context)
        or summary["dataset_snapshot"] != protocol.expected_snapshot.model_dump(mode="json")
        or summary["inner_folds"] != protocol.folds.inner_folds
        or summary["environment_sha256"] != digest(read_producing_file(repo, revision, "uv.lock"))
    ):
        raise EvidenceRefused("selection summary differs from its producing experiment")
    # These pure helpers may evolve; refuse to recompute old evidence using a
    # different implementation. Historical source is read, never executed.
    for relative in ("evaluation/metrics.py", "models/ensemble/selection.py"):
        installed = Path(__file__).parents[2] / relative
        if installed.read_bytes() != read_producing_file(repo, revision, f"src/hachi/{relative}"):
            raise EvidenceRefused("selection verification requires its original pure helpers")
    links = TypeAdapter(dict[RelativePath, Sha256]).validate_python(
        summary["packets_evaluation_sha256"]
    )
    expected_folds = [f"inner-{k}" for k in range(protocol.folds.inner_folds)]
    candidates = summary["candidates"]
    TypeAdapter(dict[Identifier, object]).validate_python(candidates)
    expected_keys = {f"{name}/{fold}" for name in candidates for fold in expected_folds}
    if set(links) != expected_keys:
        raise EvidenceRefused("selection evaluation links omit or add a candidate fold")
    results = {}
    manifests = {}
    splits = {}
    for key, expected in links.items():
        packet = root / "candidates" / key
        identity, result, split = _packet(packet, repo)
        run = RunManifest.model_validate_json(read_file(packet, "run.json"))
        name, fold = key.split("/")
        _protocol(root, split, result.config, document=protocol)
        family = candidates[name]["family"]
        gpu = family in {"chronos", "finetuned"} or name == "chronos-2-embedding-ridge"
        pretrained = gpu or family == "ensemble"
        pin = owner.chronos.chronos.model
        expected_checkpoint = (
            (pin.model_id, pin.revision, pin.license) if pretrained else (None,) * 3
        )
        environment = pin.runtime_lock_sha256 if gpu else summary["environment_sha256"]
        if (
            identity.evaluation_sha256 != expected
            or expected != document_sha256(result)
            or run.git_sha != revision
            or run.model.model_id != name
            or run.artifact is not None
            or run.environment_sha256 != environment
            or (run.model.checkpoint_source, run.model.checkpoint_revision, run.model.license)
            != expected_checkpoint
            or (fold in splits and splits[fold] != split)
        ):
            raise EvidenceRefused("selection candidate link differs from its canonical packet")
        splits[fold] = split
        results[key] = result
        manifests[key] = run
    validation = [set(splits[f].validation_subjects) for f in expected_folds]
    if (
        sum(map(len, validation)) != len(set().union(*validation))
        or len(set().union(*validation)) != summary["validation_participants"]
        or any(
            s.test_subjects != splits[expected_folds[0]].test_subjects
            or set(s.train_subjects + s.validation_subjects)
            != set(
                splits[expected_folds[0]].train_subjects
                + splits[expected_folds[0]].validation_subjects
            )
            for s in splits.values()
        )
    ):
        raise EvidenceRefused("selection folds do not share one disjoint development cohort")
    for name, reported in candidates.items():
        rows = [results[f"{name}/{f}"] for f in expected_folds]
        pooled = combine_metric_reports([r.metrics for r in rows], seed=protocol.folds.seed)
        count_fields = {
            "expected_points",
            "scored_points",
            "abstained_points",
            "missing_labels",
            "insufficient_history_points",
            "predicted_origins",
        }
        if (
            set(reported["counts"]) != count_fields
            or any(
                reported[k] != json.loads(document_bytes(getattr(pooled, k)))
                for k in ("mae", "rmse", "interval_coverage", "mean_interval_width")
            )
            or reported["abstention_share"] != _abstention(rows)
            or any(
                value != sum(r.counts[k] for r in rows) for k, value in reported["counts"].items()
            )
        ):
            raise EvidenceRefused("selection pooled report differs from saved fold metrics")
    log = summary["selection"]
    if (
        log["rule_sha256"] != document_sha256(rule)
        or len(log["steps"]) != len(rule.candidate_order) - 1
    ):
        raise EvidenceRefused("selection log differs from its original rule")
    incumbent = rule.candidate_order[0]
    steps = []
    for name, row in zip(rule.candidate_order[1:], log["steps"], strict=True):
        if row["candidate"] != name or row["incumbent"] != incumbent:
            raise EvidenceRefused("selection step breaks the original candidate order or chain")
        if row["status"] == "not_available":
            if name in candidates or row["evidence"] is not None or row["gates"] or row["packets"]:
                raise EvidenceRefused("unavailable selection step has candidate evidence")
            steps.append(LinkedStep(**{**row, "packets": {}}))
            continue
        evidence = TypeAdapter(Challenge).validate_json(document_bytes(row["evidence"]))
        if (evidence.candidate, evidence.incumbent) != (name, incumbent):
            raise EvidenceRefused("selection challenge names a different pair")
        if set(row["packets"]) != set(expected_folds):
            raise EvidenceRefused("selection step lacks its exact paired fold links")
        paired = []
        packets = {}
        for fold in expected_folds:
            link = row["packets"][fold]
            path = f"chain/{incumbent}__vs__{name}/{fold}"
            if link["path"] != path or set(link) != {"path", "comparison.json", "sha256.json"}:
                raise EvidenceRefused("selection paired link differs from its original layout")
            for filename in ("comparison.json", "sha256.json"):
                if digest(read_file(root, f"{path}/{filename}")) != link[filename]:
                    raise EvidenceRefused("selection paired link checksum mismatch")
            comparison = TypeAdapter(ComparisonSummary).validate_json(
                read_file(root, f"{path}/comparison.json")
            )
            if (
                comparison.baseline_result_sha256 != links[f"{incumbent}/{fold}"]
                or comparison.candidate_result_sha256 != links[f"{name}/{fold}"]
                or comparison.split_manifest_sha256 != document_sha256(splits[fold])
            ):
                raise EvidenceRefused(
                    "selection paired results differ from the candidate evaluations"
                )
            # The producer regenerates timestamps and a challenger run_id; every
            # scientific/provenance field must still match the standalone run.
            for role, model_name in (("baseline", incumbent), ("candidate", name)):
                paired_run = RunManifest.model_validate_json(
                    read_file(root, f"{path}/{role}/run.json")
                )
                if paired_run.model_dump(exclude={"run_id", "created_at_utc"}) != manifests[
                    f"{model_name}/{fold}"
                ].model_dump(exclude={"run_id", "created_at_utc"}):
                    raise EvidenceRefused(
                        "selection paired run provenance differs from its candidate"
                    )
            paired.append(comparison)
            packets[fold] = PacketLink(
                path=path,
                comparison_sha256=link["comparison.json"],
                index_sha256=link["sha256.json"],
            )
        candidate_rows = [results[f"{name}/{f}"] for f in expected_folds]
        incumbent_rows = [results[f"{incumbent}/{f}"] for f in expected_folds]
        expected_mae = bootstrap_participant_mean(
            [d.mae for p in paired for d in p.difference.subjects],
            samples=protocol.evaluation.bootstrap_samples,
            confidence=protocol.evaluation.confidence,
            seed=protocol.folds.seed,
        )
        cost = summary["costs"][name]
        if (
            evidence.paired_points != sum(p.counts["paired_points"] for p in paired)
            or evidence.paired_mae != expected_mae
            or evidence.coverage
            != combine_metric_reports(
                [r.metrics for r in candidate_rows], seed=protocol.folds.seed
            ).interval_coverage
            or evidence.abstention_share != _abstention(candidate_rows)
            or evidence.incumbent_abstention_share != _abstention(incumbent_rows)
            or evidence.latency_p95_seconds != cost.get("latency_p95_seconds")
            or evidence.peak_memory_bytes != cost.get("peak_memory_bytes")
        ):
            raise EvidenceRefused("selection challenge differs from its linked saved evidence")
        gates = judge(evidence, rule.gates)
        status = "promoted" if all(gates.values()) else "kept_incumbent"
        if row["gates"] != gates or row["status"] != status:
            raise EvidenceRefused("selection gates differ from the owner's recorded challenge")
        steps.append(
            LinkedStep(
                candidate=name,
                incumbent=incumbent,
                status=status,
                gates=gates,
                evidence=evidence,
                packets=packets,
            )
        )
        if status == "promoted":
            incumbent = name
    if log["selected"] != incumbent:
        raise EvidenceRefused("owner-reported selection differs from its logged chain")
    return SelectionEvidence(
        score_summary_sha256=expected_summary_sha256,
        score_index_sha256=expected_index_sha256,
        producing_git_sha=revision,
        export_git_sha=summary["export_git_sha"],
        owner_documents_sha256=owner.documents_sha256,
        export_documents_sha256=exported.documents_sha256,
        rule_sha256=document_sha256(rule),
        adaptation_sha256=exported.adaptation_sha256,
        context_policy_sha256=document_sha256(owner.context),
        owner_reported_selected=incumbent,
        selected_evaluation_sha256=[links[f"{incumbent}/{f}"] for f in expected_folds],
        development_receipt=receipt,
        steps=steps,
        limitations=[
            "Owner record verified mechanically; scientific acceptance remains parent-owned.",
            "Paired decile loss is owner-reported, not recomputed from raw outcomes here.",
            "Runtime and memory bind the original cost record; measurements are not repeated here.",
            "Budgets and amendments are pinned documents; their adequacy is not established here.",
            "Selection optimism remains; decisions are not frozen and test authority is false.",
            "Reload, cache, inference reproduction and other task acceptance are separate gates.",
        ],
    )
