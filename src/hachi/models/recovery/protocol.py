"""Frozen source-specific recovery choices and independent whole-person partitions."""

from pathlib import Path
from typing import Annotated, Literal, Self

import pyarrow.parquet as pq
from pydantic import Field, model_validator

from hachi.contracts.base import Contract, DatasetSnapshotRef, Sha256, UtcDatetime
from hachi.data.clinical import dataset_snapshot_ref, load_manifest, verify
from hachi.evaluation.clinical_protocol import ClinicalProtocol
from hachi.evaluation.folds import NestedFoldConfig, NestedFoldPlan, nested_participant_folds
from hachi.evaluation.serialization import document_sha256

from .clinical import ENDPOINT
from .cohorts import CMU, STANFORD, cohort_named


class CMUSplitProtocol(Contract):
    compatible_snapshots: Annotated[list[DatasetSnapshotRef], Field(min_length=1)]
    clock: Literal["relative_to_challenge"]
    roster: Literal["all_subjects_before_task_eligibility"]
    folds: NestedFoldConfig
    active_outer_fold: Annotated[int, Field(ge=0)]
    nested_plan_sha256: Sha256
    split_created_at_utc: UtcDatetime


class Protocol(Contract):
    protocol_version: Literal["recovery-phase1-research-2", "recovery-cmu-research-2"]
    cohort: Literal["stanford_phase1", "cmu_common_cold"]
    split_protocol_path: Literal[
        "configs/evaluation/stanford-phase1-clinical.json",
        "configs/experiments/recovery/cmu-split.json",
    ]
    expected_split_protocol_sha256: Sha256
    expected_snapshot_sha256: Sha256
    expected_fold_plan_sha256: Sha256
    endpoint: Literal[ENDPOINT]
    landmark: Literal["first-observed-symptomatic-survey-end-of-day-per-episode"]
    censoring: Literal["last-observed-symptomatic-or-intermediate-day"]
    outcome_scope: Literal["active-outer-development-only"]
    historical_test_aggregate_exposure: bool
    feature_order: tuple[str, ...]
    primary_horizon_days: Annotated[int, Field(gt=0)]
    maximum_export_days: Annotated[int, Field(gt=0)]
    calibration_days: tuple[Annotated[int, Field(gt=0)], ...]
    support_policy: Literal["label-extent", "known-at-risk"]
    minimum_followed_training_subjects: Annotated[int, Field(ge=2)]
    minimum_resolved_training_episodes: Annotated[int, Field(ge=1)]
    ridge: Annotated[float, Field(gt=0)]
    max_iterations: Annotated[int, Field(gt=0)]
    tolerance: Annotated[float, Field(gt=0)]
    bootstrap_replicates: Annotated[int, Field(ge=100)]
    selection: Literal["none-fixed-comparison-no-refit-no-serving"]
    calibration: Literal["unmodified-probabilities-interval-identification-bounds"]
    wearables: Literal["none-symptom-only-primary"]

    @model_validator(mode="after")
    def _source(self) -> Self:
        cohort = cohort_named(self.cohort)
        if self.feature_order != cohort.features:
            raise ValueError("predictor schema must be native to the specified source")
        expected_path = (
            "configs/evaluation/stanford-phase1-clinical.json"
            if cohort == STANFORD
            else "configs/experiments/recovery/cmu-split.json"
        )
        if self.split_protocol_path != expected_path:
            raise ValueError("cohort and frozen split protocol differ")
        if (
            self.maximum_export_days < self.primary_horizon_days
            or not self.calibration_days
            or max(self.calibration_days) > self.maximum_export_days
            or len(set(self.calibration_days)) != len(self.calibration_days)
        ):
            raise ValueError("calibration/scoring days must fit the frozen source horizon")
        if cohort == CMU and (self.maximum_export_days > 3 or self.primary_horizon_days > 2):
            raise ValueError("CMU requires its separate short-follow-up protocol")
        return self


def load_split(
    snapshot: Path,
    protocol: Protocol,
    repo: Path,
) -> tuple[ClinicalProtocol | CMUSplitProtocol, NestedFoldPlan]:
    cohort = cohort_named(protocol.cohort)
    path = repo / protocol.split_protocol_path
    if cohort == STANFORD:
        common = ClinicalProtocol.model_validate_json(path.read_bytes())
    else:
        common = CMUSplitProtocol.model_validate_json(path.read_bytes())
    if (
        not verify(snapshot)["ok"]
        or dataset_snapshot_ref(snapshot) not in common.compatible_snapshots
        or load_manifest(snapshot)["clock"] != cohort.clock
        or common.clock != cohort.clock
    ):
        raise ValueError("snapshot/clock differs from the frozen protocol")
    # Project just identity: the subjects table also holds outcome-derived counts.
    # None of those columns is needed to assign a participant's independent fold.
    plan = nested_participant_folds(
        pq.read_table(snapshot / "subjects.parquet", columns=["subject_id"])[
            "subject_id"
        ].to_pylist(),
        common.folds,
    )
    if (
        document_sha256(common) != protocol.expected_split_protocol_sha256
        or dataset_snapshot_ref(snapshot).snapshot_sha256 != protocol.expected_snapshot_sha256
        or dataset_snapshot_ref(snapshot).dataset_id != cohort.dataset_id
        or common.nested_plan_sha256 != protocol.expected_fold_plan_sha256
        or document_sha256(plan) != protocol.expected_fold_plan_sha256
        or common.active_outer_fold >= common.folds.outer_folds
    ):
        raise ValueError("cohort, protocol, snapshot or deterministic fold identity mismatch")
    return common, plan
