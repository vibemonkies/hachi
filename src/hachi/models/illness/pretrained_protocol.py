"""Clinical frozen-representation ablation choices, fixed before any feature scores."""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, RelativePath, Sha256
from hachi.evaluation.clinical_protocol import ClinicalProtocol
from hachi.evaluation.serialization import document_sha256

from .hourly import load_context_protocol
from .protocol import load_protocol

REPO = Path(__file__).resolve().parents[4]


class DocumentPin(Contract):
    path: RelativePath
    sha256: Sha256


class FrozenRepresentation(Contract):
    kind: Literal["frozen"]
    name: Literal["wbm_hr", "moment_hr", "chronos_hr"]
    model_spec: DocumentPin
    model_revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    vector_width: Annotated[int, Field(gt=0)]
    auxiliary_features: tuple[Literal["loc_bpm", "scale_bpm"], ...]
    pretrained_cohort_overlap: Literal["unknown"]


class MeanPoolRepresentation(Contract):
    kind: Literal["summary"]
    name: Literal["meanpool_hr"]
    input_spec: DocumentPin
    vector_width: Literal[76]
    auxiliary_features: tuple[()]
    pretrained_cohort_overlap: Literal["not_applicable"]


type Representation = Annotated[
    FrozenRepresentation | MeanPoolRepresentation, Field(discriminator="kind")
]


class PretrainedProtocol(Contract):
    protocol_id: Literal["phase1-frozen-hr-representation-development-v1"]
    task_protocol: DocumentPin
    context_protocol: DocumentPin
    clinical_protocol: DocumentPin
    representations: tuple[Representation, ...]
    channels: tuple[Literal["heart_rate"], ...]
    target: Literal["any-reported-illness-incident-symptom-onset"]
    active_outer_fold: Literal[0]
    feature_policy: Literal["past-surveys-plus-frozen-vector-and-declared-auxiliary"]
    dimensionality_reduction: Literal["none"]
    preprocessing: Literal["fit-only-median-missing-indicators-standard-scaling"]
    min_context_supported_fit_participants: Annotated[int, Field(ge=4)]
    min_context_supported_calibration_participants: Annotated[int, Field(ge=4)]
    require_both_classes_in_context_supported_fit_and_calibration: Literal[True]
    all_missing_feature_status: Literal["unavailable-not-a-pretrained-success"]
    missing_feature_policy: Literal["null-until-fit-only-imputation-with-indicators"]
    full_window_comparison: Literal[True]
    common_context_comparison: Literal[
        "same-risk-labels-and-intersection-of-all-finite-primary-vectors"
    ]
    paired_baselines: tuple[
        Literal["survey-history", "nightly-rest", "anomaly-derived", "meanpool_hr"], ...
    ]
    head_candidates: tuple[Literal["prevalence", "logistic", "tree"], ...]
    hyperparameters_calibration_burden_uncertainty: Literal["unchanged-pinned-task-protocol"]
    selection: Literal["descriptive-development-only-no-final-cross-family-winner"]
    outer_test: Literal["sealed-not-opened"]
    population_calibration: Literal["unsupported-selected-illness-survey-cohort"]
    prior_cpu_development_scores_seen: Literal[True]
    feature_scores_seen_at_freeze: Literal[False]

    @model_validator(mode="after")
    def _primary(self) -> Self:
        if self.channels != ("heart_rate",):
            raise ValueError("primary clinical comparison is HR-only")
        if tuple(r.name for r in self.representations) != (
            "meanpool_hr",
            "wbm_hr",
            "moment_hr",
            "chronos_hr",
        ):
            raise ValueError("primary representation order must remain fixed")
        expected = {
            "wbm_hr": (256, ()),
            "moment_hr": (1024, ()),
            "chronos_hr": (768, ("loc_bpm", "scale_bpm")),
        }
        if any(
            (r.vector_width, r.auxiliary_features) != expected[r.name]
            for r in self.representations
            if r.kind == "frozen"
        ):
            raise ValueError("representation widths/auxiliary fields differ from supported outputs")
        if self.head_candidates != ("prevalence", "logistic", "tree") or self.paired_baselines != (
            "survey-history",
            "nightly-rest",
            "anomaly-derived",
            "meanpool_hr",
        ):
            raise ValueError("head and paired baseline order must remain fixed")
        return self


def load_pretrained_protocol(path: Path) -> PretrainedProtocol:
    protocol = PretrainedProtocol.model_validate_json(path.read_bytes())
    task = load_protocol(REPO / protocol.task_protocol.path)
    context = load_context_protocol(REPO / protocol.context_protocol.path)
    clinical = ClinicalProtocol.model_validate_json(
        (REPO / protocol.clinical_protocol.path).read_bytes()
    )
    if (
        task.sha256 != protocol.task_protocol.sha256
        or document_sha256(context) != protocol.context_protocol.sha256
        or document_sha256(clinical) != protocol.clinical_protocol.sha256
    ):
        raise ValueError("primary clinical protocol document differs from frozen reference")
    if (
        context.snapshot_sha256 != task.snapshot_sha256
        or clinical.active_outer_fold != protocol.active_outer_fold
        or context.active_outer_fold != protocol.active_outer_fold
        or task.active_outer_fold != protocol.active_outer_fold
        or clinical.folds != task.folds
        or context.nested_plan_sha256 != clinical.nested_plan_sha256
        or context.prediction_hours != 24
        or context.context_hours != 168
        or context.min_observed_hr_hours != 24
    ):
        raise ValueError("clinical representation inputs differ from accepted primary policy")
    for representation in protocol.representations:
        pin = (
            representation.model_spec
            if representation.kind == "frozen"
            else representation.input_spec
        )
        payload = (REPO / pin.path).read_bytes()
        if hashlib.sha256(payload).hexdigest() != pin.sha256:
            raise ValueError("encoder specification differs from frozen file pin")
        spec = json.loads(payload)
        if representation.kind == "frozen":
            revision = (
                spec["revision"]
                if representation.name == "chronos_hr"
                else spec["checkpoint"]["revision"]
            )
            if revision != representation.model_revision:
                raise ValueError("encoder revision differs from supported pinned checkpoint")
    return protocol
