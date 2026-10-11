"""Split and run manifests: what every evaluation and prediction resolves back to."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from .base import (
    ArtifactRef,
    Contract,
    DatasetSnapshotRef,
    FeatureName,
    GitSha,
    Identifier,
    RelativePath,
    SchemaVersion,
    Sha256,
    SubjectId,
    TaskName,
    Text,
    UtcDatetime,
    VersionString,
    require_ordered,
    require_unique,
)


class Exclusion(Contract):
    subject_id: SubjectId
    record_id: Identifier | None = Field(description="Null excludes the whole subject.")
    reason: Text


class TimeWindow(Contract):
    start_utc: UtcDatetime
    end_utc: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_ordered(self.start_utc, self.end_utc, "time window", allow_equal=False)
        return self


class SplitManifest(Contract):
    """Participant-grouped partitions and rolling-origin settings for one evaluation fold.

    Immutable once `test_opened_at_utc` is set; changes produce a new manifest id.
    """

    schema_version: SchemaVersion
    manifest_id: Identifier
    created_at_utc: UtcDatetime
    dataset_snapshot: DatasetSnapshotRef
    task: TaskName
    fold: Annotated[int, Field(ge=0)] | None
    n_folds: Annotated[int, Field(ge=2)] | None
    train_subjects: Annotated[list[SubjectId], Field(min_length=1)]
    validation_subjects: list[SubjectId]
    test_subjects: list[SubjectId]
    exclusions: list[Exclusion]
    lookback_hours: Annotated[int, Field(gt=0)]
    horizon_hours: Annotated[int, Field(gt=0)]
    embargo_hours: Annotated[int, Field(ge=0)] = Field(
        description="Gap purged between the cutoff and the first target window."
    )
    cutoff_stride_hours: Annotated[int, Field(gt=0)]
    min_history_hours: Annotated[int, Field(ge=0)]
    evaluation_window: TimeWindow | None
    seed: int
    test_opened_at_utc: UtcDatetime | None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if (self.fold is None) != (self.n_folds is None):
            raise ValueError("fold and n_folds are given together or not at all")
        if self.fold is not None and self.n_folds is not None and self.fold >= self.n_folds:
            raise ValueError("fold must be less than n_folds")
        partitions = {
            "train": self.train_subjects,
            "validation": self.validation_subjects,
            "test": self.test_subjects,
        }
        for name, subjects in partitions.items():
            require_unique(subjects, f"{name}_subjects")
        names = list(partitions)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                if set(partitions[a]) & set(partitions[b]):
                    raise ValueError(f"{a} and {b} partitions share subjects")
        assigned = set().union(*partitions.values())
        excluded = {e.subject_id for e in self.exclusions if e.record_id is None}
        if assigned & excluded:
            raise ValueError("an excluded subject cannot be assigned to a partition")
        return self


class ModelRef(Contract):
    model_id: Identifier
    checkpoint_source: Text | None = Field(description="Upstream checkpoint, e.g. a Hub repo id.")
    checkpoint_revision: VersionString | None
    license: Text | None


class RunManifest(Contract):
    """Everything needed to trace a prediction back to its code, data, model and environment."""

    schema_version: SchemaVersion
    run_id: Identifier
    created_at_utc: UtcDatetime
    git_sha: GitSha
    git_dirty: bool = Field(description="True when the run used uncommitted code.")
    config_sha256: Sha256
    dataset_snapshot: DatasetSnapshotRef
    split_manifest_sha256: Sha256
    task: TaskName
    feature_order: Annotated[list[FeatureName], Field(min_length=1)]
    model: ModelRef
    environment_sha256: Sha256 = Field(description="Digest of the lockfile or container image.")
    seed: int
    artifact: ArtifactRef | None = Field(description="Null for runs that export no artifact.")
    metrics_paths: list[RelativePath]

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_unique(self.feature_order, "feature_order")
        require_unique(self.metrics_paths, "metrics_paths")
        return self
