"""Immutable private data-only research artifacts, with production abstention."""

import hashlib
import os
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from hachi.contracts.base import ArtifactRef, Contract, Identifier, Sha256
from hachi.contracts.results import RecoveryPayload, SurvivalPoint
from hachi.evaluation.serialization import document_bytes, document_sha256

from .clinical import ENDPOINT
from .cohorts import STANFORD, Cohort, cohort_named
from .survival import SurvivalModel


class Receipt(Contract):
    artifact_id: Identifier
    format: Literal["recovery-research-2"]
    files: dict[str, Sha256]


@dataclass(frozen=True)
class RecoveryArtifact:
    model: SurvivalModel
    cohort: Cohort = STANFORD
    endpoint: str = ENDPOINT
    readiness: Literal["research_only"] = "research_only"

    def __post_init__(self) -> None:
        if self.cohort != cohort_named(self.cohort.name) or self.endpoint != ENDPOINT:
            raise ValueError("artifact cohort/endpoint mismatch")
        if len(self.model.means) != len(self.cohort.features):
            raise ValueError("artifact predictor dimension differs from source schema")

    @property
    def feature_order(self) -> tuple[str, ...]:
        return self.cohort.features

    def predict(self, episode_id: str, covariates: tuple[float, ...]) -> None:
        """Current evidence cannot authorize a clinical/serving recovery prediction."""
        return None

    def research_payload(self, episode_id: str, covariates: tuple[float, ...]) -> RecoveryPayload:
        """Explicit research path; relative days only, no unsupported quantile extrapolation."""
        if len(covariates) != len(self.feature_order) or not all(isfinite(x) for x in covariates):
            raise ValueError("research input must match the artifact's native predictor schema")
        curve = self.model.survival(covariates, self.model.supported_days)
        return RecoveryPayload(
            episode_id=episode_id,
            endpoint_definition=self.endpoint,
            survival=[
                SurvivalPoint(days_after_as_of=d, probability_still_symptomatic=s)
                for d, s in enumerate(curve)
            ],
            median_days_after_as_of=self.model.quantiles(covariates)["0.5"],
            supported_follow_up_days=self.model.supported_days,
        )


def source_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.py"))}


def write_private(path: Path, value: object) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(document_bytes(value))


def save_artifact(path: Path, artifact: RecoveryArtifact, artifact_id: str) -> ArtifactRef:
    path.mkdir(mode=0o700)
    write_private(path / "model.json", artifact)
    write_private(path / "source-sha256.json", source_hashes())
    receipt = Receipt(
        artifact_id=artifact_id,
        format="recovery-research-2",
        files={
            name: hashlib.sha256((path / name).read_bytes()).hexdigest()
            for name in ("model.json", "source-sha256.json")
        },
    )
    write_private(path / "artifact.json", receipt)
    return ArtifactRef(artifact_id=artifact_id, artifact_sha256=document_sha256(receipt))


def _read(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("oversized recovery artifact file")
    return data


def load_artifact(path: Path, expected: ArtifactRef) -> RecoveryArtifact:
    receipt = Receipt.model_validate_json(_read(path / "artifact.json"))
    if (
        receipt.artifact_id != expected.artifact_id
        or document_sha256(receipt) != expected.artifact_sha256
    ):
        raise ValueError("recovery artifact pin mismatch")
    if set(receipt.files) != {"model.json", "source-sha256.json"}:
        raise ValueError("recovery artifact file set mismatch")
    payloads = {name: _read(path / name) for name in receipt.files}
    if any(
        hashlib.sha256(payloads[name]).hexdigest() != digest
        for name, digest in receipt.files.items()
    ):
        raise ValueError("recovery artifact checksum mismatch")
    sources = TypeAdapter(dict[str, Sha256]).validate_json(payloads["source-sha256.json"])
    if sources != source_hashes():
        raise ValueError("recovery artifact implementation mismatch")
    artifact = TypeAdapter(RecoveryArtifact).validate_json(payloads["model.json"])
    return artifact
