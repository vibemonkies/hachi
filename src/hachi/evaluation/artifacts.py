"""Immutable, hash-identified private evaluation packets; never overwrite an existing run."""

import hashlib
import os
from pathlib import Path

from hachi.contracts.manifests import RunManifest, SplitManifest

from .comparison import ComparisonResult
from .forecast import EvaluationResult
from .serialization import document_bytes, document_sha256


def _packet_payloads(
    split: SplitManifest, run: RunManifest, result: EvaluationResult
) -> dict[str, bytes]:
    if run.split_manifest_sha256 != document_sha256(split):
        raise ValueError("RunManifest split hash does not match")
    if result.split_manifest_sha256 != document_sha256(split):
        raise ValueError("evaluation result was generated against a different split")
    if run.config_sha256 != document_sha256(result.config):
        raise ValueError("RunManifest config hash does not match")
    if run.dataset_snapshot != split.dataset_snapshot or run.task != split.task:
        raise ValueError("RunManifest must resolve the same dataset and task as the split")
    if run.seed != split.seed:
        raise ValueError("RunManifest seed must match the evaluation split seed")
    if run.metrics_paths != ["evaluation.json"]:
        raise ValueError("this packet stores its metrics in evaluation.json")
    return {
        "split.json": document_bytes(split),
        "run.json": document_bytes(run),
        "config.json": document_bytes(result.config),
        "origins.json": document_bytes(result.plan),
        "evaluation.json": document_bytes(result),
        "source-sha256.json": document_bytes(
            {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(Path(__file__).parent.glob("*.py"))
            }
        ),
    }


def _hashes(payloads: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(payload).hexdigest() for name, payload in payloads.items()}


def _write_payloads(output: Path, payloads: dict[str, bytes]) -> dict[str, str]:
    hashes = _hashes(payloads)
    payloads["sha256.json"] = document_bytes(hashes)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, payload in payloads.items():
        (output / name).parent.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
    return hashes


def write_packet(
    output: Path, split: SplitManifest, run: RunManifest, result: EvaluationResult
) -> dict[str, str]:
    """Write only into a new caller-selected private directory.

    Per-subject predictions and split identities belong in approved private storage,
    even when a caller subsequently publishes a sanitized aggregate summary.
    """
    return _write_payloads(output, _packet_payloads(split, run, result))


def write_comparison_packet(
    output: Path,
    split: SplitManifest,
    baseline_run: RunManifest,
    candidate_run: RunManifest,
    result: ComparisonResult,
) -> dict[str, str]:
    """Persist the comparison and both independently identifiable model runs."""
    if result.summary.split_manifest_sha256 != document_sha256(split):
        raise ValueError("comparison split hash does not match")
    if result.summary.baseline_result_sha256 != document_sha256(
        result.baseline
    ) or result.summary.candidate_result_sha256 != document_sha256(result.candidate):
        raise ValueError("comparison summary does not match its model results")
    if baseline_run.run_id == candidate_run.run_id:
        raise ValueError("comparison runs must have distinct run ids")
    payloads = {"comparison.json": document_bytes(result.summary)}
    for name, run, evaluation in (
        ("baseline", baseline_run, result.baseline),
        ("candidate", candidate_run, result.candidate),
    ):
        packet = _packet_payloads(split, run, evaluation)
        packet["sha256.json"] = document_bytes(_hashes(packet))
        payloads.update({f"{name}/{filename}": data for filename, data in packet.items()})
    return _write_payloads(output, payloads)
