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


def test_real_archived_worker_handles_invalid_private_packet_without_traceback(tmp_path):
    # Exercise the actual subprocess/import boundary at the producing source. No
    # patient data is needed to prove exception details stay inside captured output.
    from hachi.models.illness.pretrained_protocol import REPO

    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    (tmp_path / "summary.json").write_text(json.dumps({"git_sha": commit}))
    with pytest.raises(ValueError, match="failed archived verification"):
        evidence.archived_report(
            tmp_path,
            tmp_path,
            tmp_path,
            tmp_path,
            tmp_path,
            REPO / "configs/experiments/illness/encoder-return-001.json",
        )


def test_markdown_uses_canonical_json_order():
    report = {
        "producing_commit": "a" * 40,
        "comparison_sha256": "b" * 64,
        "views": {str(h): {"whole_window": {}} for h in (72, 24, 48)},
    }
    assert evidence.render(report) == evidence.render(
        json.loads(json.dumps(report, sort_keys=True))
    )
