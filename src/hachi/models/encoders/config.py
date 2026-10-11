"""The frozen #11 experiment: which inputs each candidate head sees, fixed before any scoring."""

import hashlib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, Identifier, RelativePath, Sha256

from .head import HANDCRAFTED, HeadConfig
from .windows import WindowConfig

REPO = Path(__file__).resolve().parents[4]


class ProtocolRef(Contract):
    path: RelativePath
    sha256: Sha256

    def resolve(self) -> Path:
        path = REPO / self.path
        if hashlib.sha256(path.read_bytes()).hexdigest() != self.sha256:
            raise ValueError(f"{self.path} changed; the experiment binds a different protocol")
        return path


class Candidate(Contract):
    name: Identifier
    blocks: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    pca_components: Annotated[int, Field(ge=1)] | None = None
    role: Literal["primary", "ablation"]
    pretrained_cohort_overlap: Literal["not_applicable", "none", "known", "unknown"]


class EncoderExperiment(Contract):
    protocol: ProtocolRef
    window: WindowConfig
    head: HeadConfig
    tables: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    baseline: Identifier
    candidates: Annotated[tuple[Candidate, ...], Field(min_length=2)]
    overlap_notes: dict[Literal["none", "unknown", "not_applicable"], str]

    @model_validator(mode="after")
    def _names(self) -> Self:
        names = [c.name for c in self.candidates]
        if len(set(names)) != len(names):
            raise ValueError("candidate names must be unique")
        by_name = {c.name: c for c in self.candidates}
        if self.baseline not in by_name or by_name[self.baseline].blocks != (HANDCRAFTED,):
            raise ValueError("the baseline is the same head on handcrafted inputs only")
        for candidate in self.candidates:
            unknown = set(candidate.blocks) - set(self.tables) - {HANDCRAFTED}
            if unknown:
                raise ValueError(f"{candidate.name} uses undeclared tables {sorted(unknown)}")
            if candidate.pretrained_cohort_overlap not in self.overlap_notes:
                raise ValueError(f"{candidate.name} needs an overlap note")
        return self

    def head_for(self, candidate: Candidate) -> HeadConfig:
        if candidate.pca_components is None:
            return self.head
        return self.head.model_copy(update={"pca_components": candidate.pca_components})
