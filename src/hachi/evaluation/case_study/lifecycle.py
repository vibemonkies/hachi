"""Append-only private receipts pinned outside the bundle; never runs a model."""

import hashlib
import os
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from hachi.contracts.base import Sha256
from hachi.evaluation.serialization import document_bytes

from .specification import Prespecification, Receipt, ResultBatch, SourceSnapshot

MAX_BYTES = 16 * 1024 * 1024


class CaseRefused(ValueError):
    """Safe refusal messages contain no input values, paths or health records."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _now() -> datetime:
    # Observed system clock, not a trusted timestamp service. No caller override.
    return datetime.now(UTC)


def _directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise CaseRefused("private directory must have mode 0700 and cannot be a symlink")


def private_read(root: Path, relative: str) -> bytes:
    """No links, shared permissions or special files in private evidence."""
    _directory(root)
    path = root
    for part in relative.split("/"):
        if part in ("", ".", ".."):
            raise CaseRefused("private document path is invalid")
        path = path / part
        if path.is_symlink():
            raise CaseRefused("private evidence cannot contain symlinks")
        if path != root / relative:
            _directory(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_size > MAX_BYTES
        ):
            raise CaseRefused(
                "private document requires an unlinked regular 0600 file within limit"
            )
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise CaseRefused("private document exceeds size limit")
    return raw


def exclusive_write(path: Path, raw: bytes) -> None:
    _directory(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    # Persist the directory entry before returning a receipt to an external holder.
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def source_snapshot(repo: Path) -> SourceSnapshot:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    )
    paths = sorted(
        [
            *repo.glob("src/hachi/**/*.py"),
            *repo.glob("scripts/case_study/*.py"),
            repo / "pyproject.toml",
            repo / "uv.lock",
        ]
    )
    if any(p.is_symlink() for p in paths):
        raise CaseRefused("source snapshot cannot contain symlinks")
    return SourceSnapshot(
        git_sha=result.stdout.strip(),
        files={p.relative_to(repo).as_posix(): digest(p.read_bytes()) for p in paths},
    )


def _verify_inputs(spec: Prespecification, inputs: Path, repo: Path) -> SourceSnapshot:
    for pin in spec.document_pins():
        if digest(private_read(inputs, pin.path)) != pin.sha256:
            raise CaseRefused("a preregistered input document has changed")
    source = SourceSnapshot.model_validate_json(private_read(inputs, spec.system.source.path))
    if source != source_snapshot(repo):
        raise CaseRefused("original source or producing commit has changed")
    return source


def _preparation_only(spec: Prespecification) -> None:
    if spec.data_mode != "synthetic":
        raise CaseRefused(
            "real case unavailable: requires real inputs, separate consents, Justin/Coffee handoff "
            "and accepted #20; final_test_authorized=false never authorizes scoring"
        )
    if spec.processing_consent.status != "granted":
        raise CaseRefused("synthetic processing permission fixture is required")


def _stage(root: Path, receipt: Receipt, payload_name: str, payload: bytes) -> str:
    stage = root / receipt.stage
    stage.mkdir(mode=0o700, exist_ok=False)
    exclusive_write(stage / payload_name, payload)
    raw = document_bytes(receipt)
    exclusive_write(stage / "receipt.json", raw)
    return digest(raw)


def preregister(spec: Prespecification, inputs: Path, repo: Path, output: Path) -> str:
    _preparation_only(spec)
    _verify_inputs(spec, inputs, repo)
    if output.resolve().is_relative_to(repo.resolve()) or output.resolve().is_relative_to(
        inputs.resolve()
    ):
        raise CaseRefused("private case output must be outside repository and immutable inputs")
    _directory(output.parent)
    now = _now()
    if any(
        c.recorded_at_utc is not None and c.recorded_at_utc > now
        for c in (spec.processing_consent, spec.presentation_consent)
    ):
        raise CaseRefused("consent recording cannot be later than observed receipt time")
    output.mkdir(mode=0o700, exist_ok=False)
    payload = document_bytes(spec)
    return _stage(
        output,
        Receipt(
            stage="prespecified",
            observed_at_utc=now,
            prespecification_sha256=digest(payload),
            previous_receipt_sha256=None,
            payload_sha256=digest(payload),
        ),
        "prespecification.json",
        payload,
    )


def _read_receipt(
    root: Path, stage: str, expected: str, payload_name: str
) -> tuple[Receipt, bytes]:
    TypeAdapter(Sha256).validate_python(expected)
    if {p.name for p in (root / stage).iterdir()} != {"receipt.json", payload_name}:
        raise CaseRefused("receipt stage contains missing or unindexed documents")
    raw = private_read(root / stage, "receipt.json")
    if digest(raw) != expected:
        raise CaseRefused("receipt differs from its external pin")
    receipt = Receipt.model_validate_json(raw)
    payload = private_read(root / stage, payload_name)
    if receipt.stage != stage or digest(payload) != receipt.payload_sha256:
        raise CaseRefused("receipt stage or payload has changed")
    if receipt.observed_at_utc >= _now():
        raise CaseRefused("observed system clock precedes an existing receipt")
    return receipt, payload


def _prespec(root: Path, pin: str, inputs: Path, repo: Path) -> tuple[Receipt, Prespecification]:
    _directory(root)
    if not {p.name for p in root.iterdir()} <= {"prespecified", "predictions_sealed", "revealed"}:
        raise CaseRefused("receipt root contains unrecognized stages")
    receipt, raw = _read_receipt(root, "prespecified", pin, "prespecification.json")
    spec = Prespecification.model_validate_json(raw)
    if (
        receipt.prespecification_sha256 != digest(raw)
        or receipt.previous_receipt_sha256 is not None
    ):
        raise CaseRefused("prespecification receipt linkage differs")
    _preparation_only(spec)
    _verify_inputs(spec, inputs, repo)
    return receipt, spec


def _batch(
    spec: Prespecification, batch: ResultBatch, source: SourceSnapshot, before: Receipt
) -> None:
    expected = {(t, task) for t in spec.scoring_times() for task in spec.tasks}
    actual = [(r.root.as_of, r.root.task) for r in batch.results]
    if len(actual) != len(expected) or set(actual) != expected:
        raise CaseRefused("retain exactly every prespecified cutoff/comparison and task")
    if len({r.root.subject_id for r in batch.results}) != 1 or len(
        {r.root.report_id for r in batch.results}
    ) != len(batch.results):
        raise CaseRefused("batch requires one synthetic subject and unique report identities")
    for wrapped in batch.results:
        r = wrapped.root
        if r.data_mode != "synthetic" or r.git_sha != source.git_sha:
            raise CaseRefused("result source or synthetic mode differs from preregistration")
        if r.generated_at_utc < before.observed_at_utc or r.generated_at_utc >= _now():
            raise CaseRefused("result generation must follow preregistration and precede sealing")
        if r.replay is not None:
            raise CaseRefused("replayed predictions cannot establish new sealing chronology")
        if r.status == "ok":
            # This preparation has no accepted clinical artifact or output handoff.
            if r.task in ("illness_onset", "recovery"):
                raise CaseRefused("clinical case outputs remain unavailable in preparation")
            artifact = r.provenance.artifact
        elif r.status == "unavailable" and r.provenance is not None:
            artifact = r.provenance.artifact
        else:
            artifact = None
        if artifact is not None and artifact != spec.system.artifact:
            raise CaseRefused("result original model differs from preregistered artifact")


def seal(root: Path, prespec_pin: str, batch: ResultBatch, inputs: Path, repo: Path) -> str:
    before, spec = _prespec(root, prespec_pin, inputs, repo)
    if (root / "revealed").exists():
        raise CaseRefused("cannot seal after reveal")
    source = _verify_inputs(spec, inputs, repo)
    _batch(spec, batch, source, before)
    raw = document_bytes(batch)
    now = _now()
    if now <= before.observed_at_utc or any(r.root.generated_at_utc >= now for r in batch.results):
        raise CaseRefused("observed system clock regressed during sealing")
    return _stage(
        root,
        Receipt(
            stage="predictions_sealed",
            observed_at_utc=now,
            prespecification_sha256=before.prespecification_sha256,
            previous_receipt_sha256=prespec_pin,
            payload_sha256=digest(raw),
        ),
        "results.json",
        raw,
    )


def reveal(root: Path, prespec_pin: str, sealed_pin: str, inputs: Path, repo: Path) -> str:
    before, spec = _prespec(root, prespec_pin, inputs, repo)
    sealed, raw = _read_receipt(root, "predictions_sealed", sealed_pin, "results.json")
    if (
        sealed.previous_receipt_sha256 != prespec_pin
        or sealed.prespecification_sha256 != before.prespecification_sha256
        or sealed.observed_at_utc <= before.observed_at_utc
    ):
        raise CaseRefused("sealed receipt does not follow the original prespecification")
    batch = ResultBatch.model_validate_json(raw)
    _batch(spec, batch, _verify_inputs(spec, inputs, repo), before)
    if any(r.root.generated_at_utc >= sealed.observed_at_utc for r in batch.results):
        raise CaseRefused("saved results postdate their sealing receipt")
    # Receipt of permission to open the holder's timeline; no labels become predictors.
    payload = document_bytes({"sealed_timeline_sha256": spec.onset.sealed_timeline.sha256})
    now = _now()
    if now <= sealed.observed_at_utc:
        raise CaseRefused("observed system clock regressed during reveal")
    return _stage(
        root,
        Receipt(
            stage="revealed",
            observed_at_utc=now,
            prespecification_sha256=before.prespecification_sha256,
            previous_receipt_sha256=sealed_pin,
            payload_sha256=digest(payload),
        ),
        "reveal.json",
        payload,
    )


def verify(
    root: Path, prespec_pin: str, sealed_pin: str, reveal_pin: str, inputs: Path, repo: Path
) -> dict[str, object]:
    """Read back all three externally pinned stages; emit counts and source identity only."""
    before, spec = _prespec(root, prespec_pin, inputs, repo)
    sealed, raw = _read_receipt(root, "predictions_sealed", sealed_pin, "results.json")
    opened, payload = _read_receipt(root, "revealed", reveal_pin, "reveal.json")
    source = _verify_inputs(spec, inputs, repo)
    batch = ResultBatch.model_validate_json(raw)
    _batch(spec, batch, source, before)
    if (
        not before.observed_at_utc < sealed.observed_at_utc < opened.observed_at_utc
        or sealed.previous_receipt_sha256 != prespec_pin
        or opened.previous_receipt_sha256 != sealed_pin
        or sealed.prespecification_sha256 != before.prespecification_sha256
        or opened.prespecification_sha256 != before.prespecification_sha256
        or any(r.root.generated_at_utc >= sealed.observed_at_utc for r in batch.results)
        or payload != document_bytes({"sealed_timeline_sha256": spec.onset.sealed_timeline.sha256})
    ):
        raise CaseRefused("receipt sequence or revealed timeline linkage differs")
    return {
        "data_mode": "synthetic",
        "clinical_case_status": "unavailable",
        "source_git_sha": source.git_sha,
        "source_document_sha256": spec.system.source.sha256,
        "prespecified_cutoffs": len(spec.cutoffs),
        "healthy_periods": len(spec.healthy_periods),
        "results": len(batch.results),
        "unavailable_results": sum(r.root.status == "unavailable" for r in batch.results),
        "receipt_order_verified": True,
        "presentation_consent": spec.presentation_consent.status,
        "timestamp_basis": "observed_system_utc_not_trusted_attestation",
    }
