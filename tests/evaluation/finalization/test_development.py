"""Generated packets only. Test mode labels exercise refusal rules, not real-data proof."""

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from hachi.contracts.manifests import ModelRef, RunManifest, SplitManifest
from hachi.evaluation import EvaluationConfig, ForecastEstimate, evaluate_forecast, write_packet
from hachi.evaluation.finalization import validate_development
from hachi.evaluation.finalization.__main__ import main
from hachi.evaluation.finalization.integrity import (
    EvidenceRefused,
    digest,
    verify_index,
    write_private,
)
from hachi.evaluation.serialization import document_bytes, document_sha256

from ..conftest import BASE


def reindex(root: Path) -> str:
    for packet in root.glob("fold/evaluations/*"):
        payload = {
            p.name: digest(p.read_bytes()) for p in packet.iterdir() if p.name != "sha256.json"
        }
        (packet / "sha256.json").write_bytes(document_bytes(payload))
    index = {
        p.relative_to(root).as_posix(): digest(p.read_bytes())
        for p in root.rglob("*")
        if p.is_file() and p != root / "sha256.json"
    }
    (root / "sha256.json").write_bytes(document_bytes(index))
    return digest((root / "sha256.json").read_bytes())


@pytest.fixture
def generated_bundle(tmp_path, manifest: SplitManifest, config: EvaluationConfig, cohort):
    # Use a real temporary Git history to test historical source verification.
    repo = tmp_path / "repo"
    # The source root comes from the installed module, independent of pytest's cwd.
    import hachi.evaluation.artifacts as artifacts

    source = Path(artifacts.__file__).parent
    destination = repo / "src/hachi/evaluation"
    destination.mkdir(parents=True)
    for path in source.glob("*.py"):
        shutil.copyfile(path, destination / path.name)
    for cmd in (
        ["git", "init", "-q"],
        ["git", "add", "src"],
        [
            "git",
            "-c",
            "user.name=Generated Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "Generated source fixture",
        ],
    ):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    settings = EvaluationConfig.model_validate({**config.model_dump(), "data_mode": "real"})
    result = evaluate_forecast(
        manifest,
        *cohort,
        lambda _: lambda r: [ForecastEstimate(median=60.0)] * len(r.targets),
        settings,
    )
    run = RunManifest(
        schema_version="0.1",
        run_id="generated-run",
        created_at_utc=BASE,
        git_sha=sha,
        git_dirty=False,
        config_sha256=document_sha256(settings),
        dataset_snapshot=manifest.dataset_snapshot,
        split_manifest_sha256=document_sha256(manifest),
        task=manifest.task,
        feature_order=["heart_rate"],
        model=ModelRef(
            model_id="generated-model",
            checkpoint_source=None,
            checkpoint_revision=None,
            license=None,
        ),
        environment_sha256="b" * 64,
        seed=manifest.seed,
        artifact=None,
        metrics_paths=["evaluation.json"],
    )
    root = tmp_path / "bundle"
    packet = root / "fold/evaluations/generated-model"
    write_packet(packet, manifest, run, result)
    return root, reindex(root), repo, packet, result


def test_verifies_historical_sources_and_never_grants_test_authority(generated_bundle):
    root, pin, repo, _, _ = generated_bundle
    receipt = validate_development(root, pin, repo)
    assert receipt.state == "development_verified"
    assert not receipt.final_test_authorized
    assert len(receipt.evaluations) == 1
    assert {s.task for s in receipt.task_support if s.status == "blocked"} == {
        "anomaly",
        "illness_onset",
        "recovery",
        "alertness",
    }
    # Current source drift doesn't change a historical run's identity.
    (repo / "src/hachi/evaluation/forecast.py").write_text("changed current checkout")
    assert validate_development(root, pin, repo) == receipt


@pytest.mark.parametrize("mutation", ["dirty", "opened", "config", "partition", "support"])
def test_rejects_semantic_mismatch_even_after_rehash(generated_bundle, mutation):
    root, _, repo, packet, result = generated_bundle
    if mutation == "dirty":
        doc = json.loads((packet / "run.json").read_text())
        doc["git_dirty"] = True
        (packet / "run.json").write_bytes(document_bytes(doc))
    elif mutation == "opened":
        doc = json.loads((packet / "split.json").read_text())
        doc["test_opened_at_utc"] = "2026-10-11T00:00:00Z"
        (packet / "split.json").write_bytes(document_bytes(doc))
    elif mutation == "config":
        doc = json.loads((packet / "config.json").read_text())
        doc["bootstrap_samples"] = 999
        (packet / "config.json").write_bytes(document_bytes(doc))
    elif mutation == "partition":
        plan = replace(result.plan, partition="test")
        (packet / "evaluation.json").write_bytes(document_bytes(replace(result, plan=plan)))
    else:
        metrics = replace(
            result.metrics,
            subjects=(replace(result.metrics.subjects[0], subject_id="escaped-person"),),
        )
        (packet / "evaluation.json").write_bytes(document_bytes(replace(result, metrics=metrics)))
    with pytest.raises(EvidenceRefused):
        validate_development(root, reindex(root), repo)


def test_source_receipt_cannot_be_rebound_to_false_sources(generated_bundle):
    root, _, repo, packet, _ = generated_bundle
    doc = json.loads((packet / "source-sha256.json").read_text())
    doc["forecast.py"] = "a" * 64
    (packet / "source-sha256.json").write_bytes(document_bytes(doc))
    with pytest.raises(EvidenceRefused, match="producing commit"):
        validate_development(root, reindex(root), repo)


def test_index_pin_completeness_and_symlink_refusals(generated_bundle, tmp_path):
    root, pin, _, packet, _ = generated_bundle
    with pytest.raises(EvidenceRefused, match="expected checksum"):
        verify_index(root, "a" * 64)
    (root / "unindexed.txt").write_text("extra")
    with pytest.raises(EvidenceRefused, match="unindexed"):
        verify_index(root, pin)
    (root / "unindexed.txt").unlink()
    raw = (packet / "run.json").read_bytes()
    outside = tmp_path / "outside.json"
    outside.write_bytes(raw)
    (packet / "run.json").unlink()
    (packet / "run.json").symlink_to(outside)
    with pytest.raises(EvidenceRefused, match="symlinks"):
        verify_index(root, pin)


def test_cli_private_readback_no_overwrite_and_sanitized_errors(generated_bundle, tmp_path, capsys):
    root, pin, repo, _, _ = generated_bundle
    output = tmp_path / "output"
    args = [
        "development",
        "--bundle",
        str(root),
        "--expected-index-sha256",
        pin,
        "--repo",
        str(repo),
        "--output",
        str(output),
    ]
    assert main(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["final_test_authorized"] is False
    assert output.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in output.iterdir())
    assert (
        main(
            [
                "verify",
                "--bundle",
                str(output),
                "--expected-index-sha256",
                digest((output / "sha256.json").read_bytes()),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(args) == 1
    error = capsys.readouterr().out
    assert str(root) not in error and "synthetic-" not in error
    with pytest.raises(FileExistsError):
        write_private(output, {"other.json": b"{}"})
