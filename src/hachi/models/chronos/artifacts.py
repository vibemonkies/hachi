"""Immutable Chronos-2 serving artifacts in the same receipt format as the baselines.

A zero-shot artifact holds no weights: it pins the public checkpoint (revision and
weight hash), the GX10 runtime lock, the adapter settings and, for variants, the
bounded context policy. A fine-tuned artifact also names the fine-tuned weight hash;
the weights themselves stay in approved GX10 storage, never in Git.
"""

import hashlib
import os
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from hachi.contracts.base import ArtifactRef, Contract, Identifier, Sha256
from hachi.contracts.metrics import Metric
from hachi.evaluation.context import ContextPolicy
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.baselines.artifacts import Receipt

from .adapter import ChronosConfig


class ChronosArtifact(Contract):
    format_version: Literal["chronos-2-artifact-1"] = "chronos-2-artifact-1"
    model_id: Identifier
    chronos: ChronosConfig
    protocol_sha256: Sha256
    harness_lookback_hours: Annotated[int, Field(gt=0)]
    context_policy: ContextPolicy | None = None
    past_covariates: list[Metric] = Field(default_factory=list)
    finetuned_weights_sha256: Sha256 | None = None
    finetune_receipt_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        extended = self.chronos.context_hours != self.harness_lookback_hours or self.past_covariates
        if extended and self.context_policy is None:
            raise ValueError("longer contexts and covariates need their context policy")
        if (self.finetuned_weights_sha256 is None) != (self.finetune_receipt_sha256 is None):
            raise ValueError("a fine-tuned artifact names both its weights and its receipt")
        return self

    @property
    def weights_sha256(self) -> str:
        return self.finetuned_weights_sha256 or self.chronos.model.weights_sha256


def source_hashes() -> dict[str, str]:
    """The code that turns harness inputs into GX10 requests and requests into estimates."""
    package = Path(__file__).parents[2]
    hashes = {
        f"models/chronos/{p.name}": hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(__file__).parent.glob("*.py"))
        if p.name in {"adapter.py", "inference.py", "finetune.py", "artifacts.py"}
    }
    for relative in (
        "evaluation/features.py",
        "evaluation/context.py",
        "evaluation/serialization.py",
        "contracts/causality.py",
    ):
        hashes[relative] = hashlib.sha256((package / relative).read_bytes()).hexdigest()
    return hashes


def save_artifact(output: Path, artifact: ChronosArtifact, *, artifact_id: str) -> ArtifactRef:
    payloads = {
        "model.json": document_bytes(artifact),
        "source-sha256.json": document_bytes(source_hashes()),
    }
    receipt = Receipt(
        artifact_id=artifact_id,
        files={name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
    )
    reference = ArtifactRef(artifact_id=artifact_id, artifact_sha256=document_sha256(receipt))
    payloads["artifact.json"] = document_bytes(receipt)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, data in payloads.items():
        descriptor = os.open(output / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    return reference


def _read_small(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("artifact file exceeds its format limit")
    return data


def load_artifact(path: Path, expected: ArtifactRef) -> ChronosArtifact:
    """Refuse an altered receipt, file or implementation; return the pinned settings."""
    receipt = Receipt.model_validate_json(_read_small(path / "artifact.json", 4096))
    if (
        receipt.artifact_id != expected.artifact_id
        or document_sha256(receipt) != expected.artifact_sha256
    ):
        raise ValueError("artifact receipt does not match the expected immutable reference")
    payloads = {}
    for name, digest in receipt.files.items():
        data = _read_small(path / name, 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("artifact content checksum mismatch")
        payloads[name] = data
    sources = TypeAdapter(dict[str, Sha256]).validate_json(payloads["source-sha256.json"])
    if sources != source_hashes():
        raise ValueError("artifact requires its identified Chronos implementation")
    return ChronosArtifact.model_validate_json(payloads["model.json"])


def artifact_id_for(artifact: ChronosArtifact) -> str:
    identity = document_sha256({"model": artifact, "sources": source_hashes()})
    return f"{artifact.model_id}-{identity[:16]}"
