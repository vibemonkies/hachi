"""A predeclared density variant of the frozen PMData protocol: only the density gates move."""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, RelativePath, Sha256, Text
from hachi.evaluation.pmdata_run import PMDataProtocol

from .rule import AppleMinuteThinning, ThinningRule

REPO = Path(__file__).resolve().parents[4]


class BaseProtocolRef(Contract):
    path: RelativePath
    sha256: Sha256


class DensityGate(Contract):
    min_observed_count: Annotated[int, Field(ge=1)]
    justification: Text


class MinuteDensityGate(DensityGate):
    """Amendment 1 gate, in the Apple helper's sampled-minute coverage."""

    min_coverage: Annotated[float, Field(gt=0, le=1)]


class Amendment(Contract):
    amends_path: RelativePath
    amends_sha256: Sha256
    reason: Text


class DensityVariant(Contract):
    """Wraps a full PMDataProtocol so every existing runner accepts it unchanged."""

    base_protocol: BaseProtocolRef
    thinning: ThinningRule | AppleMinuteThinning
    density_gate: DensityGate | MinuteDensityGate
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
        minute = isinstance(self.thinning, AppleMinuteThinning)
        if minute != isinstance(self.density_gate, MinuteDensityGate):
            raise ValueError("Apple-minute coverage needs a minute-coverage gate, and only it")
        if minute and self.protocol.feature_policy.min_coverage != self.density_gate.min_coverage:
            raise ValueError("feature min_coverage must equal the declared minute-coverage gate")
        return self


class AmendedDensityVariant(DensityVariant):
    amendment: Amendment


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
    raw = json.loads(path.read_bytes())
    model = AmendedDensityVariant if "amendment" in raw else DensityVariant
    variant = model.model_validate_json(path.read_bytes())
    if isinstance(variant, AmendedDensityVariant):
        amended = REPO / variant.amendment.amends_path
        if hashlib.sha256(amended.read_bytes()).hexdigest() != variant.amendment.amends_sha256:
            raise ValueError("the amended variant changed since the amendment was declared")
    base_path = REPO / variant.base_protocol.path
    if hashlib.sha256(base_path.read_bytes()).hexdigest() != variant.base_protocol.sha256:
        raise ValueError("the frozen base protocol changed since the variant was declared")
    base = PMDataProtocol.model_validate_json(base_path.read_bytes())
    changed = _differences(
        json.loads(base.model_dump_json()), json.loads(variant.protocol.model_dump_json())
    )
    allowed = ALLOWED | (
        {("feature_policy", "min_coverage")}
        if isinstance(variant.thinning, AppleMinuteThinning)
        else set()
    )
    if not changed <= allowed:
        raise ValueError(
            f"variant changes more than the density gates: {sorted(changed - allowed)}"
        )
    return variant, base
