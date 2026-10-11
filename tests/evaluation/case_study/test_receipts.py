"""Meaningful refusal properties on generated inputs, without real case acceptance."""

import json
import os
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from hachi.contracts.base import ArtifactRef
from hachi.contracts.results import PartialProvenance
from hachi.evaluation.case_study import lifecycle as flow
from hachi.evaluation.case_study.__main__ import main
from hachi.evaluation.case_study.specification import Consent, Prespecification, ResultBatch
from hachi.evaluation.case_study.synthetic import fixture, parser_seam, unavailable_batch


@pytest.fixture
def prepared(tmp_path):
    # Isolated generated repository allows mutation probes without changing this checkout.
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src/hachi").mkdir(parents=True)
    (repo / "src/hachi/generated.py").write_text("# synthetic source\n")
    (repo / "pyproject.toml").write_text("# synthetic toolchain\n")
    (repo / "uv.lock").write_text("# synthetic lock\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "Generated fixture",
        ],
        cwd=repo,
        check=True,
    )
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    inputs = private / "inputs"
    spec = fixture(inputs, repo)
    root = private / "receipts"
    pin = flow.preregister(spec, inputs, repo, root)
    batch = unavailable_batch(spec, flow.source_snapshot(repo))
    return repo, inputs, spec, root, pin, batch


def test_complete_readback_and_separate_presentation_permission(prepared):
    repo, inputs, spec, root, pin, batch = prepared
    sealed = flow.seal(root, pin, batch, inputs, repo)
    opened = flow.reveal(root, pin, sealed, inputs, repo)
    proof = flow.verify(root, pin, sealed, opened, inputs, repo)
    assert proof["unavailable_results"] == proof["results"] == 8
    assert proof["clinical_case_status"] == "unavailable"
    assert proof["presentation_consent"] == "unavailable"
    assert proof["source_git_sha"] == flow.source_snapshot(repo).git_sha
    for path in root.rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
    with pytest.raises(FileExistsError):
        flow.preregister(spec, inputs, repo, root)
    with pytest.raises(FileExistsError):
        flow.reveal(root, pin, sealed, inputs, repo)
    with pytest.raises(flow.CaseRefused, match="after reveal"):
        flow.seal(root, pin, batch, inputs, repo)


def test_real_mode_refuses_current_false_freeze_even_with_processing_metadata(prepared):
    repo, inputs, spec, root, _, _ = prepared
    real = Prespecification.model_validate_json(
        spec.model_dump_json().replace('"data_mode":"synthetic"', '"data_mode":"real"')
    )
    assert json.loads((inputs / "freeze.json").read_bytes())["final_test_authorized"] is False
    with pytest.raises(flow.CaseRefused, match="final_test_authorized=false"):
        flow.preregister(real, inputs, repo, root.parent / "real")
    assert not (root.parent / "real").exists()


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "cutoff", "source", "artifact", "time", "mode"]
)
def test_prediction_selection_and_identity_refusals(prepared, change):
    repo, inputs, _, root, pin, batch = prepared
    values = batch.model_dump(mode="json")
    rows = values["results"]
    match change:
        case "missing":
            rows.pop()
        case "duplicate":
            rows[-1] = rows[0]
        case "cutoff":
            rows[0]["as_of"] = "2026-01-07T12:00:01Z"
        case "source":
            rows[0]["git_sha"] = "f" * 40
        case "time":
            rows[0]["generated_at_utc"] = "2026-01-01T00:00:00Z"
        case "mode":
            rows[0]["data_mode"] = "real"
        case "artifact":
            rows[0]["provenance"] = PartialProvenance(
                dataset_snapshot=None,
                artifact=ArtifactRef(artifact_id="changed", artifact_sha256="f" * 64),
                feature_coverage=[],
            ).model_dump(mode="json")
    changed = ResultBatch.model_validate_json(json.dumps(values))
    with pytest.raises(flow.CaseRefused):
        flow.seal(root, pin, changed, inputs, repo)
    assert not (root / "predictions_sealed").exists()


@pytest.mark.parametrize(
    "document",
    [
        "model.json",
        "config.json",
        "feature-source.json",
        "compatibility.json",
        "timeline.json",
        "processing.json",
        "freeze.json",
    ],
)
def test_bound_input_mutation_refused_before_seal(prepared, document):
    repo, inputs, _, root, pin, batch = prepared
    (inputs / document).write_bytes(b"{}\n")
    with pytest.raises(flow.CaseRefused, match="input document"):
        flow.seal(root, pin, batch, inputs, repo)


def test_source_and_commit_mutation_refused(prepared):
    repo, inputs, _, root, pin, batch = prepared
    source = repo / "src/hachi/generated.py"
    source.write_text("# changed\n")
    with pytest.raises(flow.CaseRefused, match="original source"):
        flow.seal(root, pin, batch, inputs, repo)
    source.write_text("# synthetic source\n")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "Changed commit",
        ],
        cwd=repo,
        check=True,
    )
    with pytest.raises(flow.CaseRefused, match="producing commit"):
        flow.seal(root, pin, batch, inputs, repo)


def test_external_pins_detect_receipt_and_result_rewrite(prepared):
    repo, inputs, _, root, pin, batch = prepared
    sealed = flow.seal(root, pin, batch, inputs, repo)
    with pytest.raises(flow.CaseRefused, match="external pin"):
        flow.reveal(root, pin, "f" * 64, inputs, repo)
    result = root / "predictions_sealed/results.json"
    result.write_bytes(result.read_bytes() + b" ")
    with pytest.raises(flow.CaseRefused, match="payload"):
        flow.reveal(root, pin, sealed, inputs, repo)
    assert not (root / "revealed").exists()


def test_clock_regression_and_saved_receipt_time_mutation_refused(prepared, monkeypatch):
    repo, inputs, _, root, pin, batch = prepared
    raw = (root / "prespecified/receipt.json").read_bytes()
    before = flow.Receipt.model_validate_json(raw)
    monkeypatch.setattr(flow, "_now", lambda: before.observed_at_utc - timedelta(seconds=1))
    with pytest.raises(flow.CaseRefused, match="system clock"):
        flow.seal(root, pin, batch, inputs, repo)
    monkeypatch.undo()
    receipt = root / "prespecified/receipt.json"
    receipt.write_bytes(raw.replace(b'"observed_at_utc":', b'"changed_clock":'))
    with pytest.raises(flow.CaseRefused, match="external pin"):
        flow.seal(root, pin, batch, inputs, repo)


@pytest.mark.parametrize("kind", ["permissions", "symlink", "hardlink"])
def test_private_input_storage_refusals(prepared, kind):
    repo, inputs, _, root, pin, batch = prepared
    path = inputs / "model.json"
    if kind == "permissions":
        path.chmod(0o644)
    elif kind == "hardlink":
        os.link(path, inputs / "linked.json")
    else:
        path.rename(inputs / "original.json")
        path.symlink_to("original.json")
    with pytest.raises(flow.CaseRefused):
        flow.seal(root, pin, batch, inputs, repo)


def test_specification_refuses_posthoc_cutoffs_and_missing_consent_evidence(prepared):
    _, _, spec, _, _, _ = prepared
    values = spec.model_dump(mode="json")
    values["cutoffs"][0]["as_of_utc"] = "2026-01-07T12:00:01Z"
    with pytest.raises(ValidationError, match="sealed lower"):
        Prespecification.model_validate_json(json.dumps(values))
    with pytest.raises(ValidationError, match="separately recorded"):
        Consent(status="granted", evidence=None, recorded_at_utc=None)


def test_generated_raw_parser_and_pre_transform_seam(tmp_path):
    proof = parser_seam(tmp_path / "generated")
    assert proof["records_seen"] == 6
    assert proof["visible_at_cutoff"] == 2
    assert proof["hourly_prefix_unchanged_after_tail"] is True


def test_actual_cli_generated_lifecycle_and_sanitized_refusal(prepared, monkeypatch, capsys):
    _, inputs, _, root, _, _ = prepared
    repo = Path(__file__).resolve().parents[3]
    output = root.parent / "cli-proof"
    monkeypatch.setattr(
        "sys.argv", ["receipt", "synthetic-proof", "--repo", str(repo), "--output", str(output)]
    )
    assert main() == 0
    proof = json.loads(capsys.readouterr().out)
    assert proof == json.loads((output / "synthetic-proof.json").read_bytes())
    assert len(proof["refusals_verified"]) == 6
    assert main() == 2  # exclusive output; no overwrite even through the caller
    assert (
        capsys.readouterr().out == '{"status": "refused", "clinical_case_status": "unavailable"}\n'
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "receipt",
            "preregister",
            "--repo",
            str(repo),
            "--inputs",
            str(inputs),
            "--receipts",
            str(root.parent / "bad"),
            "--specification",
            "missing.json",
        ],
    )
    assert main() == 2
    assert str(inputs) not in capsys.readouterr().out
