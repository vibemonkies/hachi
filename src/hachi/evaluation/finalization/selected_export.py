"""Bind the original #12 selected export and recorded reload proof, without inference."""

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from hachi.contracts.base import ArtifactRef, Contract, Identifier, RelativePath, Sha256
from hachi.contracts.manifests import RunManifest
from hachi.evaluation.forecast import EvaluationResult
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.chronos.artifacts import ChronosArtifact
from hachi.models.chronos.inference import canonical_bytes, check_request

from .development import _packet
from .exports import verify_forecast_export
from .integrity import EvidenceRefused, digest, read_file, read_producing_file, verify_index
from .owner12 import owner_experiment
from .selection import SelectionEvidence


class _Reload(Contract):
    evaluation_sha256: Sha256
    requests: Annotated[int, Field(gt=0)]
    reproduced: Literal[True]


class _Export(Contract):
    format: Literal["issue12-selected-artifact-1"]
    selected: Identifier
    pin: str
    artifact: ArtifactRef
    weights_sha256: Sha256
    runtime_lock_sha256: Sha256
    context_policy_sha256: Sha256 | None
    selection_rule_sha256: Sha256
    score_summary_sha256: Sha256
    reload_checks: dict[Identifier, _Reload]
    packet_sha256: dict[RelativePath, Sha256]
    reproduce_requests_sha256: Sha256
    reproduce_requests: Annotated[int, Field(gt=0)]
    fresh_gx10_reproduction: str
    post_selection_calibration: Literal["none: zero-shot native q0.1/q0.9, served as uncalibrated"]
    outer_test_sealed: Literal[True]


class _FullRerun(Contract):
    run: str
    requests: Annotated[int, Field(gt=0)]
    predictions_sha256: Sha256
    equals_scored_run_predictions_sha256: Literal[True]


class _SubsetRerun(Contract):
    run: str
    requests: Annotated[int, Field(gt=0)]
    predictions_sha256: Sha256
    bit_identical_requests: Annotated[int, Field(ge=0)]
    max_abs_difference_bpm: Annotated[float, Field(ge=0)]
    source_commit: str
    explanation: str


class _VerificationReload(Contract):
    how: str
    folds: dict[Identifier, _Reload]
    all_evaluations_hash_equal_to_scored_packets: Literal[True]


class _Verification(Contract):
    format: Literal["issue12-artifact-verification-1"]
    pin: str
    reload: _VerificationReload
    fresh_gx10_subset_run: _SubsetRerun
    fresh_gx10_full_rerun: _FullRerun
    gx10_artifact_location: str


class SelectedExportEvidence(Contract):
    format_version: Literal["hachi-selected-export-evidence-1"] = "hachi-selected-export-evidence-1"
    state: Literal["development_export_links_verified"] = "development_export_links_verified"
    selection_evidence_sha256: Sha256
    transport_inventory_sha256: Sha256
    producer_receipt_sha256: Sha256
    owner_verification_sha256: Sha256
    artifact: ArtifactRef
    weights_sha256: Sha256
    runtime_lock_sha256: Sha256
    context_policy_sha256: Sha256 | None
    serving_packet_evaluation_sha256: Sha256
    reload_evaluation_sha256: list[Sha256]
    reproduce_requests_sha256: Sha256
    reproduce_requests: int
    recorded_full_rerun_predictions_sha256: Sha256
    recorded_subset_rerun_predictions_sha256: Sha256
    recorded_subset_max_abs_difference_bpm: float
    inference_reproduced_here: Literal[False] = False
    scientific_selection_accepted: Literal[False] = False
    final_test_authorized: Literal[False] = False
    limitations: list[str]


def validate_selected_export(
    originals: Path,
    transport_index_sha256: str,
    repo: Path,
    selection: SelectionEvidence,
    *,
    expected_receipt_sha256: str,
    expected_verification_sha256: str,
) -> SelectedExportEvidence:
    """The staging inventory verifies transport, never substitutes for producer receipts."""
    index = verify_index(originals, transport_index_sha256, index_name="staging-sha256.json")
    if (
        index.get("score-sha256.json") != selection.score_index_sha256
        or index.get("score/aggregate-summary.json") != selection.score_summary_sha256
    ):
        raise EvidenceRefused("selected export transport contains a different score packet")
    verify_index(
        originals / "score",
        selection.score_index_sha256,
        index_path=originals / "score-sha256.json",
    )
    export_root = originals / "selected-export"
    raw = read_file(export_root, "receipt.json")
    verification_raw = read_file(originals, "artifact-verification.json")
    if (
        digest(raw) != expected_receipt_sha256
        or digest(verification_raw) != expected_verification_sha256
    ):
        raise EvidenceRefused("selected export owner document differs from its original pin")
    exported = _Export.model_validate_json(raw)
    verified = _Verification.model_validate_json(verification_raw)
    model = ChronosArtifact.model_validate_json(read_file(export_root, "model/model.json"))
    for name in ("model.json", "artifact.json", "source-sha256.json"):
        model_raw = read_file(export_root / "model", name)
        if model_raw != document_bytes(json.loads(model_raw)):
            raise EvidenceRefused("selected model receipt differs from its canonical serialization")
    identity, result, split = _packet(export_root / "packet", repo)
    run = RunManifest.model_validate_json(read_file(export_root, "packet/run.json"))
    owner = owner_experiment(repo, run.git_sha)
    verify_forecast_export(
        export_root / "model",
        originals / "score",
        repo,
        run,
        split,
        result,
        protocol_document=owner.protocol,
    )
    pin = f"{exported.artifact.artifact_id}@{exported.artifact.artifact_sha256}"
    expected_folds = {
        f"inner-{k}": sha for k, sha in enumerate(selection.selected_evaluation_sha256)
    }
    packet_index = json.loads(read_file(export_root, "packet/sha256.json"))
    requests_raw = read_file(export_root, "reproduce-requests.jsonl")
    original_inference = read_producing_file(
        repo, run.git_sha, "src/hachi/models/chronos/inference.py"
    )
    if (
        original_inference
        != (Path(__file__).parents[2] / "models/chronos/inference.py").read_bytes()
    ):
        raise EvidenceRefused("selected requests require their original parser implementation")
    requests = []
    for line in requests_raw.splitlines(keepends=True):
        row = json.loads(line)
        if line != canonical_bytes(row):
            raise EvidenceRefused("selected request differs from its canonical serialization")
        request = check_request(row)
        if (
            len(request.context) != model.chronos.context_hours
            or request.prediction_length != split.horizon_hours
            or set(request.past_covariates) != set(model.past_covariates)
        ):
            raise EvidenceRefused("selected request dimensions differ from its artifact")
        requests.append(request.request_id)
    score_summary = json.loads(read_file(originals / "score", "aggregate-summary.json"))
    fold_results = {
        key: TypeAdapter(EvaluationResult).validate_json(
            read_file(
                originals / "score",
                f"candidates/{selection.owner_reported_selected}/{key}/evaluation.json",
            )
        )
        for key in expected_folds
    }
    if (
        raw != document_bytes(exported.model_dump(mode="json"))
        or exported.selected != selection.owner_reported_selected
        or model.model_id != exported.selected
        or exported.pin != pin
        or verified.pin != pin
        or run.artifact != exported.artifact
        or exported.weights_sha256 != model.weights_sha256
        or exported.runtime_lock_sha256 != model.chronos.model.runtime_lock_sha256
        or exported.context_policy_sha256 != selection.context_policy_sha256
        or exported.context_policy_sha256 != document_sha256(model.context_policy)
        or exported.selection_rule_sha256 != selection.rule_sha256
        or exported.score_summary_sha256 != selection.score_summary_sha256
        or set(exported.reload_checks) != set(expected_folds)
        or any(
            exported.reload_checks[k].evaluation_sha256 != sha for k, sha in expected_folds.items()
        )
        or any(check.requests > len(requests) for check in exported.reload_checks.values())
        or len(requests) > sum(check.requests for check in exported.reload_checks.values())
        or any(
            check.requests > fold_results[key].counts["predicted_origins"]
            or document_sha256(fold_results[key]) != expected_folds[key]
            for key, check in exported.reload_checks.items()
        )
        or verified.reload.folds != exported.reload_checks
        or exported.packet_sha256 != packet_index
        or identity.evaluation_sha256 != expected_folds["inner-0"]
        or requests != sorted(set(requests))
        or len(requests) != exported.reproduce_requests
        or digest(requests_raw) != exported.reproduce_requests_sha256
        or verified.fresh_gx10_full_rerun.predictions_sha256
        != score_summary["zero_shot_predictions_sha256"]
        or verified.fresh_gx10_full_rerun.requests != score_summary["requests"]["forecast"]
        or verified.fresh_gx10_subset_run.requests != len(requests)
        or verified.fresh_gx10_subset_run.bit_identical_requests > len(requests)
    ):
        raise EvidenceRefused(
            "selected export, reload record and original score identities disagree"
        )
    return SelectedExportEvidence(
        selection_evidence_sha256=document_sha256(selection),
        transport_inventory_sha256=transport_index_sha256,
        producer_receipt_sha256=expected_receipt_sha256,
        owner_verification_sha256=expected_verification_sha256,
        artifact=exported.artifact,
        weights_sha256=exported.weights_sha256,
        runtime_lock_sha256=exported.runtime_lock_sha256,
        context_policy_sha256=exported.context_policy_sha256,
        serving_packet_evaluation_sha256=identity.evaluation_sha256,
        reload_evaluation_sha256=list(expected_folds.values()),
        reproduce_requests_sha256=exported.reproduce_requests_sha256,
        reproduce_requests=len(requests),
        recorded_full_rerun_predictions_sha256=verified.fresh_gx10_full_rerun.predictions_sha256,
        recorded_subset_rerun_predictions_sha256=verified.fresh_gx10_subset_run.predictions_sha256,
        recorded_subset_max_abs_difference_bpm=verified.fresh_gx10_subset_run.max_abs_difference_bpm,
        limitations=[
            "Reload assertions and reproduction hashes are verified records, not a fresh rerun.",
            "Prediction/cache files and checkpoint bytes are not transported or verified here.",
            "Request identity is checked; availability is not re-derived from raw subject data.",
            "Native intervals are uncalibrated; no clinical or final test acceptance is granted.",
            "Transport inventory is root-created packaging evidence, not a new producer receipt.",
        ],
    )
