"""Validate the existing #7 forecast/comparison packets and #9 artifact receipts."""

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from hachi.contracts.base import ArtifactRef, Contract, DatasetSnapshotRef, Sha256, TaskName
from hachi.contracts.manifests import RunManifest, SplitManifest
from hachi.evaluation.comparison import ComparisonSummary
from hachi.evaluation.forecast import EvaluationConfig, EvaluationResult
from hachi.evaluation.serialization import document_sha256
from hachi.evaluation.splits import rolling_origins
from hachi.models.baselines.artifacts import ARTIFACT, Receipt
from hachi.models.baselines.tree import FEATURES, TreeArtifact

from .integrity import EvidenceRefused, digest, read_file, verify_index, verify_sources

TASKS: tuple[TaskName, ...] = (
    "physiology_forecast",
    "anomaly",
    "illness_onset",
    "recovery",
    "alertness",
)
PACKET_FILES = {
    "run.json",
    "split.json",
    "config.json",
    "evaluation.json",
    "origins.json",
    "source-sha256.json",
}


class TaskSupport(Contract):
    task: TaskName
    status: Literal["development_evidence", "blocked"]
    reason: Literal["final_selection_pending", "no_verified_development_evidence"]


class EvaluationIdentity(Contract):
    run_sha256: Sha256
    split_sha256: Sha256
    config_sha256: Sha256
    evaluation_sha256: Sha256
    metric_definition_sha256: Sha256
    source_sha256: Sha256
    dataset_snapshot: DatasetSnapshotRef
    test_cohort_sha256: Sha256
    development_cohort_sha256: Sha256
    artifact: ArtifactRef | None
    scored_participants: Annotated[int, Field(ge=0)]
    scored_points: Annotated[int, Field(ge=0)]


class DevelopmentReceipt(Contract):
    format_version: Literal["hachi-development-receipt-1"] = "hachi-development-receipt-1"
    state: Literal["development_verified"] = "development_verified"
    bundle_index_sha256: Sha256
    files_verified: Annotated[int, Field(gt=0)]
    artifact_bundle_index_sha256: list[Sha256]
    evaluations: Annotated[list[EvaluationIdentity], Field(min_length=1)]
    comparison_sha256: list[Sha256]
    task_support: list[TaskSupport]
    final_test_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if len({e.run_sha256 for e in self.evaluations}) != len(self.evaluations):
            raise ValueError("development receipt contains duplicate runs")
        if {s.task for s in self.task_support} != set(TASKS) or len(self.task_support) != len(
            TASKS
        ):
            raise ValueError("every required task must have an explicit support state")
        return self


def _packet(root: Path, repo: Path) -> tuple[EvaluationIdentity, EvaluationResult, SplitManifest]:
    raw_index = read_file(root, "sha256.json")
    index = verify_index(root, digest(raw_index))
    if set(index) != PACKET_FILES:
        raise EvidenceRefused("evaluation packet differs from the established layout")
    run = RunManifest.model_validate_json(read_file(root, "run.json"))
    split = SplitManifest.model_validate_json(read_file(root, "split.json"))
    config = EvaluationConfig.model_validate_json(read_file(root, "config.json"))
    result = TypeAdapter(EvaluationResult).validate_json(read_file(root, "evaluation.json"))
    if run.git_dirty or config.data_mode != "real":
        raise EvidenceRefused("development evidence requires clean code and real data")
    if split.test_opened_at_utc is not None or result.plan.partition != "validation":
        raise EvidenceRefused("development evidence cannot contain an opened or scored test")
    if (
        run.split_manifest_sha256 != document_sha256(split)
        or result.split_manifest_sha256 != document_sha256(split)
        or run.config_sha256 != document_sha256(config)
        or config != result.config
        or run.dataset_snapshot != split.dataset_snapshot
        or run.task != split.task
        or run.seed != split.seed
        or run.metrics_paths != ["evaluation.json"]
    ):
        raise EvidenceRefused("run, config, data, split or metric identity mismatch")
    # The evaluator appends history exclusions; its original schedule is label independent.
    scheduled = rolling_origins(split, "validation")
    if result.plan.origins != scheduled.origins:
        raise EvidenceRefused("evaluation origins differ from the frozen validation schedule")
    if document_sha256(result.plan) != digest(read_file(root, "origins.json")):
        raise EvidenceRefused("origin document differs from the evaluation")
    validation = set(split.validation_subjects)
    scored = {s.subject_id for s in result.metrics.subjects}
    if (
        not scored <= validation
        or any(p.origin not in scheduled.origins for p in result.predictions)
        or len({(p.origin.subject_id, p.origin.cutoff) for p in result.predictions})
        != len(result.predictions)
        or any(len(p.estimates) != len(p.origin.targets) for p in result.predictions)
        or any(e.subject_id not in validation for e in result.plan.exclusions)
    ):
        raise EvidenceRefused("development rows escaped their validation partition")
    if (
        result.counts.get("scored_participants") != len(scored)
        or result.counts.get("scored_points")
        != sum(s.scored_points for s in result.metrics.subjects)
        or result.counts.get("evaluation_participants") != len(validation)
        or any(v < 0 for v in result.counts.values())
        or result.metrics.metric != config.metric
        or result.metrics.confidence != config.confidence
        or result.metrics.bootstrap_samples != config.bootstrap_samples
    ):
        raise EvidenceRefused("metric support counts or definitions disagree")
    source = read_file(root, "source-sha256.json")
    verify_sources(source, repo, run.git_sha, "src/hachi/evaluation")
    identity = EvaluationIdentity(
        run_sha256=digest(read_file(root, "run.json")),
        split_sha256=document_sha256(split),
        config_sha256=document_sha256(config),
        evaluation_sha256=digest(read_file(root, "evaluation.json")),
        metric_definition_sha256=document_sha256(
            {
                "metric": result.metrics.metric,
                "unit": result.metrics.unit,
                "weighting": result.metrics.weighting,
                "confidence": result.metrics.confidence,
                "bootstrap_samples": result.metrics.bootstrap_samples,
            }
        ),
        source_sha256=digest(source),
        dataset_snapshot=split.dataset_snapshot,
        test_cohort_sha256=document_sha256(sorted(split.test_subjects)),
        development_cohort_sha256=document_sha256(
            sorted(split.train_subjects + split.validation_subjects)
        ),
        artifact=run.artifact,
        scored_participants=len(scored),
        scored_points=result.counts["scored_points"],
    )
    return identity, result, split


def _artifact(root: Path, repo: Path, run: RunManifest, config: EvaluationConfig) -> None:
    receipt = Receipt.model_validate_json(read_file(root, "artifact.json"))
    if run.artifact != ArtifactRef(
        artifact_id=receipt.artifact_id, artifact_sha256=document_sha256(receipt)
    ):
        raise EvidenceRefused("artifact receipt differs from its run reference")
    for name, sha in receipt.files.items():
        if digest(read_file(root, name)) != sha:
            raise EvidenceRefused("artifact file differs from its receipt")
    model = ARTIFACT.validate_json(read_file(root, "model.json"))
    if model.model_id != run.model.model_id or (model.config.metric, model.config.aggregation) != (
        config.metric,
        config.aggregation,
    ):
        raise EvidenceRefused("artifact model and evaluation target disagree")
    expected_features = list(FEATURES) if isinstance(model, TreeArtifact) else [config.metric]
    if run.feature_order != expected_features:
        raise EvidenceRefused("artifact features differ from their run manifest")
    verify_sources(
        read_file(root, "source-sha256.json"), repo, run.git_sha, "src/hachi/models/baselines"
    )


def validate_development(
    root: Path,
    expected_index_sha256: str,
    repo: Path,
    *,
    artifact_bundles: Sequence[tuple[Path, str]] = (),
) -> DevelopmentReceipt:
    """Validate a complete existing run without running inference or consulting test labels.

    The external index pin is mandatory. Hash integrity proves identity, not that a
    scientific protocol is adequate or that its historical availability is observed.
    """
    index = verify_index(root, expected_index_sha256)
    indexes = [(root, index)] + [(p, verify_index(p, sha)) for p, sha in artifact_bundles]
    packets = sorted({str(Path(name).parent) for name in index if name.endswith("/run.json")})
    evaluations: dict[str, EvaluationIdentity] = {}
    for relative in packets:
        identity, _, _ = _packet(root / relative, repo)
        run = RunManifest.model_validate_json(read_file(root, f"{relative}/run.json"))
        if run.artifact is not None:
            matches = [
                (p / Path(name).parent)
                for p, idx in indexes
                for name in idx
                if name.endswith("/artifact.json")
                and Receipt.model_validate_json(read_file(p, name)).artifact_id
                == run.artifact.artifact_id
            ]
            if len(matches) != 1:
                raise EvidenceRefused("run must resolve exactly one indexed model artifact")
            _artifact(
                matches[0],
                repo,
                run,
                EvaluationConfig.model_validate_json(read_file(root, f"{relative}/config.json")),
            )
        previous = evaluations.get(identity.run_sha256)
        if previous is not None and previous != identity:
            raise EvidenceRefused("one immutable run refers to inconsistent evaluations")
        evaluations[identity.run_sha256] = identity
    comparisons = []
    for name in sorted(index):
        if not name.endswith("/comparison.json"):
            continue
        parent = root / Path(name).parent
        summary = TypeAdapter(ComparisonSummary).validate_json(read_file(root, name))
        baseline, b_result, b_split = _packet(parent / "baseline", repo)
        candidate, c_result, c_split = _packet(parent / "candidate", repo)
        if (
            summary.partition != "validation"
            or summary.data_mode != "real"
            or summary.split_manifest_sha256 != baseline.split_sha256
            or b_split != c_split
            or b_result.plan != c_result.plan
            or summary.baseline_result_sha256 != baseline.evaluation_sha256
            or summary.candidate_result_sha256 != candidate.evaluation_sha256
        ):
            raise EvidenceRefused(
                "paired comparison does not bind the same model results and split"
            )
        comparisons.append(index[name])
    return DevelopmentReceipt(
        bundle_index_sha256=expected_index_sha256,
        files_verified=len(index),
        artifact_bundle_index_sha256=[sha for _, sha in artifact_bundles],
        evaluations=list(evaluations.values()),
        comparison_sha256=comparisons,
        task_support=[
            TaskSupport(
                task=task,
                status="development_evidence" if task == "physiology_forecast" else "blocked",
                reason="final_selection_pending"
                if task == "physiology_forecast"
                else "no_verified_development_evidence",
            )
            for task in TASKS
        ],
    )
