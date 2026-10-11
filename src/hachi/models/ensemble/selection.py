"""The predeclared #12 selection rule: an incumbent chain in fixed complexity order.

The rule is committed before any #12 score is computed. The first candidate is the
default; each later candidate replaces the incumbent only when every gate passes
against that incumbent. If no challenger passes, the simplest model is served.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, Identifier, Sha256, Text
from hachi.evaluation.metrics import Estimate


class SelectionGates(Contract):
    paired_mae_upper_below: float = 0.0
    paired_decile_loss_upper_below: float = 0.0
    coverage_min: Annotated[float, Field(gt=0, lt=1)] = 0.75
    coverage_max: Annotated[float, Field(gt=0, lt=1)] = 0.85
    max_extra_abstention: Annotated[float, Field(ge=0, le=1)] = 0.05
    max_latency_p95_seconds: Annotated[float, Field(gt=0)] = 1.0
    max_peak_memory_bytes: Annotated[int, Field(gt=0)] = 4 * 2**30

    @model_validator(mode="after")
    def _range(self) -> Self:
        if self.coverage_min >= self.coverage_max:
            raise ValueError("coverage gate must be a nonempty range")
        return self


class SelectionRule(Contract):
    protocol_sha256: Sha256
    partition: Literal["validation"]
    active_outer_fold: Annotated[int, Field(ge=0)]
    primary_metric: Literal["mae"]
    interval_lower: Annotated[float, Field(gt=0, lt=0.5)]
    interval_upper: Annotated[float, Field(gt=0.5, lt=1)]
    gates: SelectionGates
    candidate_order: Annotated[list[Identifier], Field(min_length=1)]
    ablations_not_candidates: list[Identifier]
    disclosure: Text

    @model_validator(mode="after")
    def _order(self) -> Self:
        if len(set(self.candidate_order)) != len(self.candidate_order):
            raise ValueError("candidate order must not repeat a candidate")
        if set(self.candidate_order) & set(self.ablations_not_candidates):
            raise ValueError("an ablation cannot also be a selection candidate")
        return self


@dataclass(frozen=True)
class Challenge:
    """Pooled inner-validation evidence for one challenger against the incumbent."""

    candidate: str
    incumbent: str
    paired_points: int
    paired_mae: Estimate | None
    paired_decile_loss: Estimate | None
    coverage: Estimate | None
    abstention_share: float
    incumbent_abstention_share: float
    latency_p95_seconds: float | None
    peak_memory_bytes: int | None


def _upper(estimate: Estimate | None) -> float | None:
    if estimate is None or estimate.confidence_interval is None:
        return None
    return estimate.confidence_interval[1]


def judge(challenge: Challenge, gates: SelectionGates) -> dict[str, bool]:
    """Every gate must be True; missing evidence fails its gate rather than passing it."""
    mae_upper = _upper(challenge.paired_mae)
    loss_upper = _upper(challenge.paired_decile_loss)
    coverage = challenge.coverage.value if challenge.coverage is not None else None
    return {
        "paired_mae_upper_below": mae_upper is not None
        and mae_upper < gates.paired_mae_upper_below,
        "paired_decile_loss_upper_below": loss_upper is not None
        and loss_upper < gates.paired_decile_loss_upper_below,
        "coverage_in_range": coverage is not None
        and gates.coverage_min <= coverage <= gates.coverage_max,
        "abstention_within": challenge.abstention_share
        <= challenge.incumbent_abstention_share + gates.max_extra_abstention,
        "latency_within": challenge.latency_p95_seconds is not None
        and challenge.latency_p95_seconds <= gates.max_latency_p95_seconds,
        "memory_within": challenge.peak_memory_bytes is not None
        and challenge.peak_memory_bytes <= gates.max_peak_memory_bytes,
    }


@dataclass(frozen=True)
class SelectionStep:
    candidate: str
    incumbent: str
    status: Literal["promoted", "kept_incumbent", "not_available"]
    gates: dict[str, bool] = field(default_factory=dict)
    challenge: Challenge | None = None


@dataclass(frozen=True)
class SelectionLog:
    rule_sha256: str
    selected: str
    steps: tuple[SelectionStep, ...]


def select(
    rule: SelectionRule,
    rule_sha256: str,
    available: Sequence[str],
    challenge: Callable[[str, str], Challenge],
) -> SelectionLog:
    """Walk the predeclared order once; unavailable candidates are logged, not skipped silently."""
    order = rule.candidate_order
    if order[0] not in available:
        raise ValueError("the default (first) candidate must be available")
    incumbent = order[0]
    steps: list[SelectionStep] = []
    for candidate in order[1:]:
        if candidate not in available:
            steps.append(SelectionStep(candidate, incumbent, "not_available"))
            continue
        evidence = challenge(candidate, incumbent)
        if (evidence.candidate, evidence.incumbent) != (candidate, incumbent):
            raise ValueError("challenge evidence does not match the requested pair")
        gates = judge(evidence, rule.gates)
        promoted = all(gates.values())
        steps.append(
            SelectionStep(
                candidate,
                incumbent,
                "promoted" if promoted else "kept_incumbent",
                gates,
                evidence,
            )
        )
        if promoted:
            incumbent = candidate
    return SelectionLog(rule_sha256, incumbent, tuple(steps))
