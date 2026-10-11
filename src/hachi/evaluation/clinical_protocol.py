"""Shared clinical roster split, fixed before task eligibility or scoring."""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, DatasetSnapshotRef, Sha256, UtcDatetime
from hachi.data.clinical import dataset_snapshot_ref, load_manifest, read_table, verify

from .folds import NestedFoldConfig, NestedFoldPlan, nested_participant_folds
from .serialization import document_sha256


class ClinicalProtocol(Contract):
    compatible_snapshots: Annotated[list[DatasetSnapshotRef], Field(min_length=1)]
    clock: Literal["floating_local_shifted"]
    roster: Literal["all_subjects_before_task_eligibility"]
    folds: NestedFoldConfig
    active_outer_fold: Annotated[int, Field(ge=0)]
    nested_plan_sha256: Sha256
    split_created_at_utc: UtcDatetime

    @model_validator(mode="after")
    def _fold(self) -> Self:
        if self.active_outer_fold >= self.folds.outer_folds:
            raise ValueError("active outer fold is outside the clinical plan")
        return self


def clinical_fold_plan(snapshot: Path, protocol: ClinicalProtocol) -> NestedFoldPlan:
    if not verify(snapshot)["ok"]:
        raise ValueError("clinical snapshot verification failed")
    if dataset_snapshot_ref(snapshot) not in protocol.compatible_snapshots:
        raise ValueError("clinical snapshot is not frozen in this protocol")
    if load_manifest(snapshot)["clock"] != protocol.clock:
        raise ValueError("clinical source clock does not match protocol")
    plan = nested_participant_folds(
        read_table(snapshot, "subjects")["subject_id"].to_pylist(), protocol.folds
    )
    if document_sha256(plan) != protocol.nested_plan_sha256:
        raise ValueError("clinical roster or participant split differs from frozen plan")
    return plan
