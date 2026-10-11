"""Frozen experiment boundary; no inferred defaults for scientific choices."""

import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, Sha256
from hachi.evaluation.folds import NestedFoldConfig
from hachi.evaluation.serialization import document_sha256
from hachi.models.baselines.robust import RobustConfig
from hachi.models.baselines.stanford.rest import StanfordRestPolicy

type Candidate = Literal["prevalence", "logistic", "tree"]


class Protocol(Contract):
    protocol_id: str
    dataset_id: Literal["stanford-covid19-wearables"]
    snapshot_sha256: Sha256
    definitions_version: Literal["outcomes-1"]
    clock: Literal["floating_local_shifted"]
    target: Literal["any-reported-illness-incident-symptom-onset"]
    horizons_hours: list[Literal[24, 48, 72]]
    cutoff_stride_hours: Literal[24]
    active_outer_fold: Literal[0]
    outer_folds: Literal[4]
    inner_folds: Literal[3]
    min_train_subjects: Annotated[int, Field(ge=4)]
    seed: int
    calibration_fraction: Annotated[float, Field(gt=0, lt=1)]
    feature_lookback_days: Annotated[int, Field(gt=0)]
    feature_families: list[Literal["survey-history-control", "nightly-rest", "anomaly-derived"]]
    external_max_age_hours: Literal[24]
    rest: StanfordRestPolicy
    robust: RobustConfig
    candidate_order: list[Candidate]
    logistic_c: Annotated[float, Field(gt=0)]
    tree_max_depth: Annotated[int, Field(gt=0)]
    tree_min_samples_leaf: Annotated[int, Field(gt=0)]
    calibration_c: Annotated[float, Field(gt=0)]
    max_false_alert_episodes_per_30_negative_cutoff_days: Annotated[float, Field(ge=0)]
    bootstrap_replicates: Annotated[int, Field(ge=100)]
    confidence_level: Annotated[float, Field(gt=0, lt=1)]
    reliability_bins: Annotated[int, Field(ge=2)]
    selection_metric: Literal["auprc"]
    selection_min_paired_improvement: Annotated[float, Field(ge=0)]
    selection_requires_positive_ci_lower_bound: Literal[True]

    @model_validator(mode="after")
    def _choices(self):
        if self.horizons_hours != [24, 48, 72]:
            raise ValueError("primary horizons must be 24/48/72")
        if self.feature_families != ["survey-history-control", "nightly-rest", "anomaly-derived"]:
            raise ValueError("feature-family comparison order must be frozen")
        if self.rest.step_timestamp != "both" or self.rest.min_rest_minutes != 30:
            raise ValueError("primary rest policy must support both edges and 30 quiet minutes")
        if self.candidate_order != ["prevalence", "logistic", "tree"]:
            raise ValueError("primary candidate complexity order must be frozen")
        return self

    @property
    def folds(self) -> NestedFoldConfig:
        return NestedFoldConfig(
            outer_folds=self.outer_folds,
            inner_folds=self.inner_folds,
            min_train_subjects=self.min_train_subjects,
            seed=self.seed,
        )

    @property
    def sha256(self) -> str:
        return document_sha256(self)


def load_protocol(path: Path) -> Protocol:
    return Protocol.model_validate(tomllib.loads(path.read_text()))
