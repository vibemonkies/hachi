"""A predeclared density variant of the frozen PMData protocol: only the density gates move."""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, RelativePath, Sha256, Text
from hachi.evaluation.pmdata_run import PMDataProtocol

from .thinning import ThinningRule

REPO = Path(__file__).resolve().parents[4]


class BaseProtocolRef(Contract):
    path: RelativePath
    sha256: Sha256


class DensityGate(Contract):
    min_observed_count: Annotated[int, Field(ge=1)]
    justification: Text


class DensityVariant(Contract):
    """Wraps a full PMDataProtocol so every existing runner accepts it unchanged."""

    base_protocol: BaseProtocolRef
    thinning: ThinningRule
    density_gate: DensityGate
    density_audit: dict[str, Any]
    protocol: PMDataProtocol

    @model_validator(mode="after")
    def _gate(self) -> Self:
        gate = self.density_gate.min_observed_count
        counts = [
            self.protocol.feature_policy.min_observed_count,
            self.protocol.tree.min_samples_per_hour,
            *(b.min_samples_per_hour for b in self.protocol.baselines),
        ]
        if any(c != gate for c in counts):
            raise ValueError("every model-input density gate must equal the declared gate")
        if gate > self.thinning.slots_per_hour:
            raise ValueError("the gate cannot exceed the thinned samples an hour can hold")
        return self


# Only these may differ from the frozen protocol; targets keep their full-density rules.
ALLOWED = {
    ("feature_policy", "min_observed_count"),
    ("tree", "min_samples_per_hour"),
    *(("baselines", i, "min_samples_per_hour") for i in range(3)),
}


def _differences(a: Any, b: Any, path: tuple = ()) -> set[tuple]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: set[tuple] = set()
        for key in a.keys() | b.keys():
            out |= _differences(a.get(key), b.get(key), (*path, key))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = set()
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            out |= _differences(x, y, (*path, i))
        return out
    return set() if a == b else {path}


def load_variant(path: Path) -> tuple[DensityVariant, PMDataProtocol]:
    """The variant and its frozen base, refusing any change beyond the density gates."""
    variant = DensityVariant.model_validate_json(path.read_bytes())
    base_path = REPO / variant.base_protocol.path
    if hashlib.sha256(base_path.read_bytes()).hexdigest() != variant.base_protocol.sha256:
        raise ValueError("the frozen base protocol changed since the variant was declared")
    base = PMDataProtocol.model_validate_json(base_path.read_bytes())
    changed = _differences(
        json.loads(base.model_dump_json()), json.loads(variant.protocol.model_dump_json())
    )
    if not changed <= ALLOWED:
        raise ValueError(
            f"variant changes more than the density gates: {sorted(changed - ALLOWED)}"
        )
    return variant, base
