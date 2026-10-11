"""Generated export-adapter boundary tests, not end-to-end selection acceptance.

The SelectionEvidence input is synthetic and typed. Production CLI callers must
first verify the original selection packet; these tests never grant that proof.
No checkpoint, private data, GPU, reload or prediction API is executed here.
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from hachi.evaluation.finalization.development import validate_development
from hachi.evaluation.finalization.integrity import EvidenceRefused, digest
from hachi.evaluation.finalization.owner12 import owner_experiment
from hachi.evaluation.finalization.selected_export import validate_selected_export
from hachi.evaluation.finalization.selection import SelectionEvidence
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.chronos.artifacts import ChronosArtifact
from hachi.models.chronos.inference import canonical_bytes, check_request, request_id

from .test_development import generated_bundle as generated_bundle
from .test_exports import generated_export as generated_export


@dataclass
class GeneratedSelectedExport:
    originals: Path
    repo: Path
    selection: SelectionEvidence
    receipt: dict
    verification: dict
    rows: list[dict]
    transport_pin: str = ""
    receipt_pin: str = ""
    verification_pin: str = ""

    @property
    def export(self):
        return self.originals / "selected-export"

    def seal(self):
        (self.export / "receipt.json").write_bytes(document_bytes(self.receipt))
        (self.originals / "artifact-verification.json").write_bytes(
            document_bytes(self.verification)
        )
        self.receipt_pin = digest((self.export / "receipt.json").read_bytes())
        self.verification_pin = digest((self.originals / "artifact-verification.json").read_bytes())
        self.seal_transport()
        return self

    def seal_transport(self):
        path = self.originals / "staging-sha256.json"
        index = {
            entry.relative_to(self.originals).as_posix(): digest(entry.read_bytes())
            for entry in self.originals.rglob("*")
            if entry.is_file() and entry != path
        }
        path.write_bytes(document_bytes(index))
        self.transport_pin = digest(path.read_bytes())

    def write_requests(self, raw=None):
        raw = raw if raw is not None else b"".join(canonical_bytes(row) for row in self.rows)
        (self.export / "reproduce-requests.jsonl").write_bytes(raw)
        self.receipt["reproduce_requests_sha256"] = digest(raw)

    def validate(self):
        return validate_selected_export(
            self.originals,
            self.transport_pin,
            self.repo,
            self.selection,
            expected_receipt_sha256=self.receipt_pin,
            expected_verification_sha256=self.verification_pin,
        )


@pytest.fixture
def generated_selected_export(generated_export, tmp_path):
    root, pin, repo, packet, model_root, kind = generated_export
    assert kind == "chronos_extended"
    development = validate_development(root, pin, repo)
    model = ChronosArtifact.model_validate_json((model_root / "model.json").read_bytes())
    run = json.loads((packet / "run.json").read_bytes())
    owner = owner_experiment(repo, run["git_sha"])
    evaluation = json.loads((packet / "evaluation.json").read_bytes())
    evaluation_sha = digest((packet / "evaluation.json").read_bytes())
    # Cloned canonical synthetic evaluations exercise the three-fold receipt
    # boundary. They are not independently scored or disjoint development folds.
    folds = [evaluation_sha] * 3
    summary = {
        "format": "issue12-pmdata-score-1",
        "git_sha": run["git_sha"],
        "git_dirty": False,
        "environment_sha256": run["environment_sha256"],
        "export_git_sha": run["git_sha"],
        "protocol_sha256": document_sha256(owner.protocol),
        "selection_rule_sha256": document_sha256(owner.rule),
        "adaptation_sha256": owner.adaptation_sha256,
        "context_policy_sha256": document_sha256(model.context_policy),
        "dataset_snapshot": run["dataset_snapshot"],
        "outer_test_sealed": True,
        "validation_participants": evaluation["counts"]["scored_participants"],
        "inner_folds": len(folds),
        "requests": {"forecast": 2},
        "zero_shot_predictions_sha256": "f" * 64,
        "embeddings_sha256": "a" * 64,
        "candidates": {
            model.model_id: {
                "family": "chronos",
                **{
                    key: evaluation["metrics"][key]
                    for key in ("mae", "rmse", "interval_coverage", "mean_interval_width")
                },
                "abstention_share": 0.0,
                "counts": {
                    key: evaluation["counts"][key]
                    for key in (
                        "expected_points",
                        "scored_points",
                        "abstained_points",
                        "missing_labels",
                        "insufficient_history_points",
                        "predicted_origins",
                    )
                },
            },
        },
        "selection": {
            "selected": model.model_id,
            "rule_sha256": document_sha256(owner.rule),
            "steps": [],
        },
        "ablations": {},
        "external_11": {},
        "ensemble_support": {},
        "residual_offsets": {},
        "finetune": None,
        "costs": {},
        "packets_evaluation_sha256": {
            f"{model.model_id}/inner-{fold}": sha for fold, sha in enumerate(folds)
        },
    }
    originals = tmp_path / "generated-originals"
    (originals / "score").mkdir(parents=True)
    summary_raw = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode()
    (originals / "score/aggregate-summary.json").write_bytes(summary_raw)
    for fold in range(len(folds)):
        path = originals / "score" / f"candidates/{model.model_id}/inner-{fold}/evaluation.json"
        path.parent.mkdir(parents=True)
        path.write_bytes((packet / "evaluation.json").read_bytes())
    score_index_raw = document_bytes(
        {
            path.relative_to(originals / "score").as_posix(): digest(path.read_bytes())
            for path in (originals / "score").rglob("*")
            if path.is_file()
        }
    )
    (originals / "score-sha256.json").write_bytes(score_index_raw)
    selection = SelectionEvidence(
        score_summary_sha256=digest(summary_raw),
        score_index_sha256=digest(score_index_raw),
        producing_git_sha=run["git_sha"],
        export_git_sha=run["git_sha"],
        owner_documents_sha256=owner.documents_sha256,
        export_documents_sha256=owner.documents_sha256,
        rule_sha256=document_sha256(owner.rule),
        adaptation_sha256=owner.adaptation_sha256,
        context_policy_sha256=document_sha256(model.context_policy),
        owner_reported_selected=model.model_id,
        selected_evaluation_sha256=folds,
        development_receipt=development,
        steps=[],
        limitations=[
            "Synthetic typed input only; full selection validation is not exercised here."
        ],
    )
    export = originals / "selected-export"
    shutil.copytree(model_root, export / "model")
    shutil.copytree(packet, export / "packet")
    rows = []
    for value in (60.0, 61.0):
        context = [value] * model.chronos.context_hours
        row = {
            "request_id": request_id(context, owner.protocol.horizon_hours),
            "context": context,
            "prediction_length": owner.protocol.horizon_hours,
        }
        check_request(row)
        rows.append(row)
    rows.sort(key=lambda row: row["request_id"])
    request_raw = b"".join(canonical_bytes(row) for row in rows)
    (export / "reproduce-requests.jsonl").write_bytes(request_raw)
    reload_checks = {
        f"inner-{fold}": {"evaluation_sha256": sha, "requests": len(rows), "reproduced": True}
        for fold, sha in enumerate(folds)
    }
    artifact = run["artifact"]
    artifact_pin = f"{artifact['artifact_id']}@{artifact['artifact_sha256']}"
    receipt = {
        "format": "issue12-selected-artifact-1",
        "selected": model.model_id,
        "pin": artifact_pin,
        "artifact": artifact,
        "weights_sha256": model.weights_sha256,
        "runtime_lock_sha256": model.chronos.model.runtime_lock_sha256,
        "context_policy_sha256": document_sha256(model.context_policy),
        "selection_rule_sha256": selection.rule_sha256,
        "score_summary_sha256": selection.score_summary_sha256,
        "reload_checks": reload_checks,
        "packet_sha256": json.loads((packet / "sha256.json").read_bytes()),
        "reproduce_requests_sha256": digest(request_raw),
        "reproduce_requests": len(rows),
        "fresh_gx10_reproduction": "pending: run inference.py on reproduce-requests.jsonl",
        "post_selection_calibration": "none: zero-shot native q0.1/q0.9, served as uncalibrated",
        "outer_test_sealed": True,
    }
    verification = {
        "format": "issue12-artifact-verification-1",
        "pin": artifact_pin,
        "reload": {
            "how": "Generated owner record; not a fresh reload",
            "folds": json.loads(document_bytes(reload_checks)),
            "all_evaluations_hash_equal_to_scored_packets": True,
        },
        "fresh_gx10_subset_run": {
            "run": "generated-subset-run",
            "requests": len(rows),
            "predictions_sha256": "9" * 64,
            "bit_identical_requests": len(rows),
            "max_abs_difference_bpm": 0.0,
            "source_commit": run["git_sha"],
            "explanation": "Generated verification record only",
        },
        "fresh_gx10_full_rerun": {
            "run": "generated-full-run",
            "requests": len(rows),
            "predictions_sha256": summary["zero_shot_predictions_sha256"],
            "equals_scored_run_predictions_sha256": True,
        },
        "gx10_artifact_location": "Generated record without a real runtime location",
    }
    return GeneratedSelectedExport(originals, repo, selection, receipt, verification, rows).seal()


@pytest.mark.parametrize("generated_export", ["chronos_extended"], indirect=True)
def test_generated_export_links_preserve_recorded_vs_fresh_and_test_authority(
    generated_selected_export, monkeypatch
):
    fixture = generated_selected_export

    def forbidden(*_args, **_kwargs):
        pytest.fail("export linkage validation must never load a checkpoint or run inference")

    monkeypatch.setattr("hachi.models.chronos.artifacts.load_artifact", forbidden)
    monkeypatch.setattr("hachi.models.chronos.inference.run", forbidden)
    evidence = fixture.validate()
    assert evidence.state == "development_export_links_verified"
    assert not evidence.inference_reproduced_here
    assert not evidence.scientific_selection_accepted and not evidence.final_test_authorized
    assert evidence.producer_receipt_sha256 == fixture.receipt_pin
    assert evidence.owner_verification_sha256 == fixture.verification_pin
    assert evidence.selection_evidence_sha256 == document_sha256(fixture.selection)
    assert evidence.reload_evaluation_sha256 == fixture.selection.selected_evaluation_sha256
    assert evidence.reproduce_requests == 2
    assert any("not a fresh rerun" in text for text in evidence.limitations)
    assert any("not transported or verified" in text for text in evidence.limitations)
    raw = document_bytes(evidence)
    assert all(key not in raw for key in (b'"subject_id":', b'"context":', b'"predictions":'))


@pytest.mark.parametrize("generated_export", ["chronos_extended"], indirect=True)
@pytest.mark.parametrize(
    "mutation",
    [
        "artifact_pin",
        "reload_evaluation",
        "missing_fold",
        "packet_hash",
        "score_summary_link",
        "verification_pin",
        "full_prediction_hash",
        "full_request_count",
        "subset_count",
        "identical_count",
        "request_count",
        "request_hash",
        "calibration",
        "test_opened",
    ],
)
def test_rehashed_owner_records_cannot_rebind_the_original_export(
    generated_selected_export, mutation
):
    fixture = generated_selected_export
    if mutation == "artifact_pin":
        fixture.receipt["artifact"]["artifact_sha256"] = "0" * 64
        artifact = fixture.receipt["artifact"]
        fixture.receipt["pin"] = f"{artifact['artifact_id']}@{artifact['artifact_sha256']}"
        fixture.verification["pin"] = fixture.receipt["pin"]
    elif mutation == "reload_evaluation":
        fixture.receipt["reload_checks"]["inner-0"]["evaluation_sha256"] = "0" * 64
        fixture.verification["reload"]["folds"]["inner-0"]["evaluation_sha256"] = "0" * 64
    elif mutation == "missing_fold":
        del fixture.receipt["reload_checks"]["inner-2"]
        del fixture.verification["reload"]["folds"]["inner-2"]
    elif mutation == "packet_hash":
        fixture.receipt["packet_sha256"]["evaluation.json"] = "0" * 64
    elif mutation == "score_summary_link":
        fixture.receipt["score_summary_sha256"] = "0" * 64
    elif mutation == "verification_pin":
        fixture.verification["pin"] = "generated-other-artifact@" + "0" * 64
    elif mutation == "full_prediction_hash":
        fixture.verification["fresh_gx10_full_rerun"]["predictions_sha256"] = "0" * 64
    elif mutation == "full_request_count":
        fixture.verification["fresh_gx10_full_rerun"]["requests"] += 1
    elif mutation == "subset_count":
        fixture.verification["fresh_gx10_subset_run"]["requests"] += 1
    elif mutation == "identical_count":
        fixture.verification["fresh_gx10_subset_run"]["bit_identical_requests"] += 1
    elif mutation == "request_count":
        fixture.receipt["reproduce_requests"] += 1
    elif mutation == "request_hash":
        fixture.receipt["reproduce_requests_sha256"] = "0" * 64
    elif mutation == "calibration":
        fixture.receipt["post_selection_calibration"] = "generated learned calibration"
    else:
        fixture.receipt["outer_test_sealed"] = False
    fixture.seal()
    with pytest.raises(ValueError):
        fixture.validate()


@pytest.mark.parametrize("generated_export", ["chronos_extended"], indirect=True)
@pytest.mark.parametrize(
    "mutation", ["content_id", "duplicate", "noncanonical", "context_width", "horizon", "covariate"]
)
def test_rehashed_requests_still_require_canonical_content_and_artifact_dimensions(
    generated_selected_export, mutation
):
    fixture = generated_selected_export
    row = fixture.rows[0]
    if mutation == "content_id":
        row["request_id"] = "0" * 64
    elif mutation == "duplicate":
        fixture.rows.append(dict(row))
        fixture.receipt["reproduce_requests"] += 1
        fixture.verification["fresh_gx10_subset_run"]["requests"] += 1
    elif mutation == "context_width":
        row["context"].pop()
        row["request_id"] = request_id(row["context"], row["prediction_length"])
    elif mutation == "horizon":
        row["prediction_length"] += 1
        row["request_id"] = request_id(row["context"], row["prediction_length"])
    elif mutation == "covariate":
        row["past_covariates"] = {"steps": [1.0] * len(row["context"])}
        row["request_id"] = request_id(
            row["context"], row["prediction_length"], row["past_covariates"]
        )
    if mutation == "noncanonical":
        fixture.write_requests(
            b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in fixture.rows)
        )
    else:
        fixture.rows.sort(key=lambda row: row["request_id"])
        fixture.write_requests()
    fixture.seal()
    with pytest.raises(ValueError):
        fixture.validate()


@pytest.mark.parametrize("generated_export", ["chronos_extended"], indirect=True)
def test_rehashed_native_interval_change_cannot_hide_behind_new_receipts(generated_selected_export):
    fixture = generated_selected_export
    root = fixture.export / "model"
    path = root / "model.json"
    model = json.loads(path.read_bytes())
    model["chronos"]["interval_lower"] = 0.2
    path.write_bytes(document_bytes(model))
    artifact_path = root / "artifact.json"
    artifact = json.loads(artifact_path.read_bytes())
    artifact["files"]["model.json"] = digest(path.read_bytes())
    artifact_path.write_bytes(document_bytes(artifact))
    reference = {
        "artifact_id": artifact["artifact_id"],
        "artifact_sha256": document_sha256(artifact),
    }
    packet = fixture.export / "packet"
    run_path = packet / "run.json"
    run = json.loads(run_path.read_bytes())
    run["artifact"] = reference
    run_path.write_bytes(document_bytes(run))
    index_path = packet / "sha256.json"
    index = json.loads(index_path.read_bytes())
    index["run.json"] = digest(run_path.read_bytes())
    index_path.write_bytes(document_bytes(index))
    fixture.receipt["packet_sha256"] = index
    fixture.receipt["artifact"] = reference
    fixture.receipt["pin"] = f"{reference['artifact_id']}@{reference['artifact_sha256']}"
    fixture.verification["pin"] = fixture.receipt["pin"]
    fixture.seal()
    with pytest.raises(EvidenceRefused, match="owner experiment"):
        fixture.validate()


@pytest.mark.parametrize("generated_export", ["chronos_extended"], indirect=True)
@pytest.mark.parametrize("document", ["receipt", "verification"])
def test_transport_rehash_does_not_replace_external_owner_document_pins(
    generated_selected_export, document
):
    fixture = generated_selected_export
    receipt_pin, verification_pin = fixture.receipt_pin, fixture.verification_pin
    if document == "receipt":
        fixture.receipt["fresh_gx10_reproduction"] = "Generated changed owner note"
    else:
        fixture.verification["reload"]["how"] = "Generated changed reload note"
    fixture.seal()
    fixture.receipt_pin, fixture.verification_pin = receipt_pin, verification_pin
    with pytest.raises(EvidenceRefused, match="original pin"):
        fixture.validate()


@pytest.mark.parametrize("generated_export", ["chronos_extended"], indirect=True)
def test_rehashed_receipt_requires_its_original_canonical_serialization(generated_selected_export):
    fixture = generated_selected_export
    path = fixture.export / "receipt.json"
    path.write_text(json.dumps(fixture.receipt, indent=2, sort_keys=True) + "\n")
    fixture.receipt_pin = digest(path.read_bytes())
    fixture.seal_transport()
    with pytest.raises(EvidenceRefused, match="original score identities disagree"):
        fixture.validate()


@pytest.mark.parametrize("generated_export", ["chronos_extended"], indirect=True)
def test_score_identity_remains_bound_after_transport_is_reindexed(generated_selected_export):
    fixture = generated_selected_export
    path = fixture.originals / "score/aggregate-summary.json"
    summary = json.loads(path.read_bytes())
    summary["zero_shot_predictions_sha256"] = "0" * 64
    path.write_bytes(document_bytes(summary))
    fixture.seal_transport()
    with pytest.raises(EvidenceRefused, match="different score packet"):
        fixture.validate()


@pytest.mark.parametrize("generated_export", ["chronos_extended"], indirect=True)
def test_transport_rehash_cannot_replace_original_score_file_inventory(generated_selected_export):
    fixture = generated_selected_export
    path = (
        fixture.originals
        / "score/candidates"
        / fixture.selection.owner_reported_selected
        / "inner-0/evaluation.json"
    )
    original_index = (fixture.originals / "score-sha256.json").read_bytes()
    result = json.loads(path.read_bytes())
    result["counts"]["predicted_origins"] += 1
    path.write_bytes(document_bytes(result))
    fixture.seal_transport()
    assert (fixture.originals / "score-sha256.json").read_bytes() == original_index
    with pytest.raises(EvidenceRefused, match="content checksum"):
        fixture.validate()


@pytest.mark.parametrize("generated_export", ["chronos_extended"], indirect=True)
def test_rehashed_reload_union_cannot_exceed_its_recorded_fold_request_support(
    generated_selected_export,
):
    fixture = generated_selected_export
    width = len(fixture.rows[0]["context"])
    horizon = fixture.rows[0]["prediction_length"]
    for value in (62.0, 63.0):
        context = [value] * width
        fixture.rows.append(
            {
                "request_id": request_id(context, horizon),
                "context": context,
                "prediction_length": horizon,
            }
        )
    fixture.rows.sort(key=lambda row: row["request_id"])
    fixture.write_requests()
    fixture.receipt["reproduce_requests"] = len(fixture.rows)
    fixture.verification["fresh_gx10_subset_run"]["requests"] = len(fixture.rows)
    for checks in (fixture.receipt["reload_checks"], fixture.verification["reload"]["folds"]):
        for check in checks.values():
            check["requests"] = 1
    assert len(fixture.rows) > sum(
        check["requests"] for check in fixture.receipt["reload_checks"].values()
    )
    fixture.seal()
    with pytest.raises(EvidenceRefused, match="original score identities disagree"):
        fixture.validate()


@pytest.mark.parametrize("generated_export", ["chronos_extended"], indirect=True)
def test_export_transport_requires_original_pin_and_complete_inventory(generated_selected_export):
    fixture = generated_selected_export
    original = fixture.transport_pin
    fixture.transport_pin = "0" * 64
    with pytest.raises(EvidenceRefused, match="expected checksum"):
        fixture.validate()
    fixture.transport_pin = original
    (fixture.originals / "unindexed-note.txt").write_text("Generated extra file")
    with pytest.raises(EvidenceRefused, match="unindexed"):
        fixture.validate()
