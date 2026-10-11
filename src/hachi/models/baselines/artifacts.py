"""Private data-only model packets, checked against the expected immutable reference."""

import hashlib
import os
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from hachi.contracts.base import ArtifactRef, Contract, Identifier, Sha256
from hachi.evaluation.serialization import document_bytes, document_sha256

from .forecast import BaselineArtifact
from .tree import TreeArtifact

type ForecastArtifact = Annotated[
    BaselineArtifact | TreeArtifact, Field(discriminator="format_version")
]
ARTIFACT = TypeAdapter(ForecastArtifact)


class Receipt(Contract):
    artifact_id: Identifier
    files: dict[Literal["model.json", "source-sha256.json"], Sha256]

    @model_validator(mode="after")
    def _files(self) -> Self:
        if set(self.files) != {"model.json", "source-sha256.json"}:
            raise ValueError("artifact must identify both model and source hashes")
        return self


def source_hashes() -> dict[str, str]:
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    package = Path(__file__).parents[2]
    # These shared helpers now affect feature selection and saved-model inference.
    for relative in (
        "evaluation/features.py",
        "evaluation/serialization.py",
        "contracts/causality.py",
    ):
        hashes[relative] = hashlib.sha256((package / relative).read_bytes()).hexdigest()
    return hashes


def save_artifact(output: Path, artifact: ForecastArtifact, *, artifact_id: str) -> ArtifactRef:
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


def load_artifact(path: Path, expected: ArtifactRef) -> ForecastArtifact:
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
        raise ValueError("artifact requires its identified baseline implementation")
    return ARTIFACT.validate_json(payloads["model.json"])
