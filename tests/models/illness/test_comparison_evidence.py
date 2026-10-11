"""An evidence publisher cannot substitute packets or mix archived source imports."""

import io
import json
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from hachi.evaluation.serialization import document_sha256
from hachi.models.illness import comparison_evidence as evidence


@pytest.mark.parametrize("mutation", ("change", "extra", "missing"))
def test_accepted_baseline_inventory_rejects_substitution(tmp_path, mutation):
    roots, receipts = {}, {}
    for name in evidence.FAMILIES:
        root = tmp_path / name
        root.mkdir()
        (root / "predictions.json").write_text("[]")
        roots[name] = root
        hashes = evidence.input_hashes(root)
        receipts[name] = {"files_sha256": hashes, "inventory_sha256": document_sha256(hashes)}
    accepted = {"report_provenance": {"input_packets": receipts}}
    evidence.accepted_baselines(roots, accepted)
    root = roots[evidence.FAMILIES[0]]
    if mutation == "change":
        (root / "predictions.json").write_text('["synthetic-sensitive-token"]')
    elif mutation == "extra":
        (root / "extra.json").write_text("[]")
    else:
        (root / "predictions.json").unlink()
    with pytest.raises(ValueError, match="immutable inventory"):
        evidence.accepted_baselines(roots, accepted)


def test_archive_is_fresh_isolated_and_worker_failure_output_is_withheld(tmp_path, monkeypatch):
    commit = "a" * 40
    root = tmp_path / "private-packet"
    root.mkdir()
    (root / "summary.json").write_text(json.dumps({"git_sha": commit}))
    (tmp_path / ".cache").mkdir()
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        data = b"synthetic archived implementation"
        member = tarfile.TarInfo("src/synthetic.py")
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    monkeypatch.setattr(evidence, "REPO", tmp_path)
    monkeypatch.setattr(
        evidence.subprocess,
        "check_output",
        lambda args, **kwargs: commit + "\n" if args[1] == "rev-parse" else payload.getvalue(),
    )
    directories = []

    def worker(args, **kwargs):
        assert args[1:3] == ["-I", "-c"]
        source = Path(args[4])
        directories.append(source.parent)
        assert (source / "synthetic.py").read_bytes() == data
        assert kwargs["capture_output"] and kwargs["check"] is False
        return SimpleNamespace(
            returncode=1,
            stdout="synthetic-sensitive-token",
            stderr="synthetic-sensitive-token",
        )

    monkeypatch.setattr(evidence.subprocess, "run", worker)
    for _ in range(2):
        with pytest.raises(ValueError, match="failed archived verification") as error:
            evidence.archived_report(tmp_path, tmp_path, root, tmp_path, tmp_path, tmp_path)
        assert "synthetic-sensitive-token" not in str(error.value)
    assert directories[0] != directories[1]
    assert not any(p.exists() for p in directories)


def test_real_archived_worker_handles_invalid_private_packet_without_traceback(
    tmp_path, monkeypatch
):
    # Exercise the actual subprocess/import boundary at the producing source. No
    # patient data is needed to prove exception details stay inside captured output.
    from hachi.models.illness.pretrained_protocol import REPO

    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    (tmp_path / "summary.json").write_text(json.dumps({"git_sha": commit}))
    invoke = subprocess.run

    def inspect_archive(args, **kwargs):
        # Chronos's public model pin is outside configs. Missing it prevented the
        # real archive path from reaching clinical validation despite mock tests.
        if args[0] != "git":
            assert (Path(args[4]).parent / "infra/gx10/model.json").is_file()
        return invoke(args, **kwargs)

    monkeypatch.setattr(evidence.subprocess, "run", inspect_archive)
    with pytest.raises(ValueError, match="failed archived verification"):
        evidence.archived_report(
            tmp_path,
            tmp_path,
            tmp_path,
            tmp_path,
            tmp_path,
            REPO / "configs/experiments/illness/encoder-return-001.json",
        )


def test_original_input_capture_detects_changes_outside_scored_packets(tmp_path):
    packet = tmp_path / "contexts"
    packet.mkdir()
    (packet / "joins.json").write_text("[]")
    accepted = tmp_path / "accepted.json"
    accepted.write_text("{}")
    paths = {"contexts": packet, "accepted": accepted}
    captured = evidence.immutable_inputs(paths)
    (packet / "joins.json").write_text('["synthetic-sensitive-token"]')
    assert evidence.immutable_inputs(paths) != captured
    (packet / "joins.json").write_text("[]")
    assert evidence.immutable_inputs(paths) == captured
    accepted.write_text('{"changed":true}')
    assert evidence.immutable_inputs(paths) != captured
    assert "synthetic-sensitive-token" not in json.dumps(captured)


def test_actual_isolated_worker_serializes_typed_support_counts(tmp_path, monkeypatch):
    commit = "a" * 40
    root = tmp_path / "packet"
    root.mkdir()
    (root / "summary.json").write_text(json.dumps({"git_sha": commit}))
    (tmp_path / ".cache").mkdir()
    files = {
        f"src/{p}/__init__.py": b""
        for p in ("hachi", "hachi/models", "hachi/models/illness", "hachi/evaluation")
    }
    files["src/hachi/models/illness/pretrained_evidence.py"] = (
        "from dataclasses import dataclass\n"
        "@dataclass\nclass Counts:\n    participants: int\n"
        "def compile_report(**kwargs):\n"
        f"    return {{'scoring_commit': '{commit}', 'counts': Counts(3)}}\n"
    ).encode()
    files["src/hachi/evaluation/serialization.py"] = (
        evidence.REPO / "src/hachi/evaluation/serialization.py"
    ).read_bytes()
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        for path, data in files.items():
            member = tarfile.TarInfo(path)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    monkeypatch.setattr(evidence, "REPO", tmp_path)
    monkeypatch.setattr(
        evidence.subprocess,
        "check_output",
        lambda args, **kwargs: commit + "\n" if args[1] == "rev-parse" else payload.getvalue(),
    )
    result = evidence.archived_report(tmp_path, tmp_path, root, tmp_path, tmp_path, tmp_path)
    assert result == {"scoring_commit": commit, "counts": {"participants": 3}}


def test_markdown_uses_canonical_json_order():
    report = {
        "producing_commit": "a" * 40,
        "comparison_sha256": "b" * 64,
        "views": {str(h): {"whole_window": {}} for h in (72, 24, 48)},
    }
    assert evidence.render(report) == evidence.render(
        json.loads(json.dumps(report, sort_keys=True))
    )
