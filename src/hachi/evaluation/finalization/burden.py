"""Consume #9's actual Stanford anomaly artifact/metrics without relabeling its task."""

from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter

from hachi.contracts.base import ArtifactRef, Contract, SubjectId
from hachi.contracts.manifests import RunManifest, SplitManifest
from hachi.evaluation.folds import NestedFoldPlan
from hachi.evaluation.metrics import Estimate
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.baselines.stanford.burden import (
    BurdenProtocol,
    StanfordAnomalyArtifact,
    aggregate,
)

from .development import TASKS, DevelopmentReceipt, EvaluationIdentity, TaskSupport
from .integrity import EvidenceRefused, digest, read_file, verify_index, verify_sources


class PolicyMetrics(Contract):
    counts: dict[str, Annotated[int, Field(ge=0)]]
    participants_with_scored_control_days: Annotated[int, Field(ge=0)]
    episodes_per30_scored_control_days: Estimate | None
    alerted_fraction_of_scored_control_days: Estimate | None
    pooled_episodes_per30_all_observed_control_days: float | None


def validate_stanford_burden(root: Path, expected_index: str, repo: Path) -> DevelopmentReceipt:
    """Bind the existing producer's receipts and retain its restricted clinical scope."""
    index = verify_index(root, expected_index)
    protocol = BurdenProtocol.model_validate_json(read_file(root, "protocol.json"))
    plan = TypeAdapter(NestedFoldPlan).validate_json(read_file(root, "fold-plan.json"))
    artifact_raw = read_file(root, "artifact/model.json")
    artifact = StanfordAnomalyArtifact.model_validate_json(artifact_raw)
    summary = TypeAdapter(dict[str, object]).validate_json(
        read_file(root, "aggregate-summary.json")
    )
    if (
        summary.get("data_mode") != "real"
        or summary.get("git_dirty") is not False
        or summary.get("outer_test_sealed") is not True
        or summary.get("protocol_sha256") != document_sha256(protocol)
        or summary.get("nested_plan_sha256") != document_sha256(plan)
        or plan.config != protocol.folds
        or artifact.protocol_sha256 != document_sha256(protocol)
        or artifact.rest != protocol.rest
        or artifact.robust != protocol.robust
        or artifact.rest.clock != "floating_local_shifted"
    ):
        raise EvidenceRefused("Stanford protocol, clock, source or sealed plan differs")
    pin = ArtifactRef.model_validate(summary.get("artifact"))
    if (
        pin.artifact_sha256 != digest(artifact_raw)
        or summary.get("source_sha256") != artifact.source_sha256
    ):
        raise EvidenceRefused("Stanford summary artifact identity differs")
    selected = [f for f in plan.folds if f.outer_fold == protocol.active_outer_fold]
    development = {s for f in selected for s in f.validation_subjects}
    participant_paths = [name for name in index if name.startswith("participants/")]
    rows: dict[str, list[dict[str, object]]] = {
        edge: [] for edge in [protocol.rest.step_timestamp, *protocol.sensitivities]
    }
    for name in participant_paths:
        parts = name.split("/")
        if len(parts) != 3 or TypeAdapter(SubjectId).validate_python(parts[1]) not in development:
            raise EvidenceRefused("Stanford private records escaped the development cohort")
        edge = Path(parts[2]).stem
        if edge not in rows:
            raise EvidenceRefused("Stanford records carry an unfrozen timestamp policy")
        record = TypeAdapter(dict[str, object]).validate_json(read_file(root, name))
        counts = TypeAdapter(dict[str, Annotated[int, Field(ge=0)]]).validate_python(
            record.get("counts")
        )
        rows[edge].append({"subject_id": parts[1], "counts": counts})
    runs = {name for name in index if name.endswith("/run.json")}
    if runs != {f"inner-{f.inner_fold}/run.json" for f in selected}:
        raise EvidenceRefused("Stanford fold runs differ from the complete active fold plan")
    identities = []
    definition = {
        "controls": protocol.controls,
        "cutoff": protocol.cutoff,
        "episode_definition": protocol.episode_definition,
        "bootstrap_samples": protocol.bootstrap_samples,
        "confidence": protocol.confidence,
        "clock": protocol.rest.clock,
        "step_timestamp": protocol.rest.step_timestamp,
    }
    for fold in selected:
        relative = f"inner-{fold.inner_fold}"
        run_raw = read_file(root, f"{relative}/run.json")
        run = RunManifest.model_validate_json(run_raw)
        split = SplitManifest.model_validate_json(read_file(root, f"{relative}/split.json"))
        metrics_raw = read_file(root, f"{relative}/metrics.json")
        metrics = TypeAdapter(dict[str, PolicyMetrics]).validate_json(metrics_raw)
        if (
            run.git_dirty
            or run.git_sha != summary.get("git_sha")
            or run.task != "anomaly"
            or split.task != run.task
            or run.dataset_snapshot != protocol.expected_snapshot
            or split.dataset_snapshot != run.dataset_snapshot
            or run.config_sha256 != document_sha256(protocol)
            or run.split_manifest_sha256 != document_sha256(split)
            or run.artifact != pin
            or run.model.model_id != artifact.model_id
            or run.seed != protocol.folds.seed
            or split.seed != run.seed
            or split.test_opened_at_utc is not None
            or split.train_subjects != list(fold.train_subjects)
            or split.validation_subjects != list(fold.validation_subjects)
            or split.test_subjects != list(fold.test_subjects)
            or run.metrics_paths != ["metrics.json"]
            or set(metrics) != {protocol.rest.step_timestamp, *protocol.sensitivities}
        ):
            raise EvidenceRefused("Stanford run, split, artifact or task identity mismatch")
        sources = {
            (
                "models/baselines/robust.py"
                if name == "robust.py"
                else f"models/baselines/stanford/{name}"
            ): sha
            for name, sha in artifact.source_sha256.items()
        }
        verify_sources(
            document_bytes(sources),
            repo,
            run.git_sha,
            "src/hachi/models/baselines/stanford",
        )
        primary = metrics[protocol.rest.step_timestamp]
        if primary.participants_with_scored_control_days > len(split.validation_subjects):
            raise EvidenceRefused("Stanford scored support exceeds its validation cohort")
        # Pure count aggregation uses the exact producer, never illness relabeling.
        if digest(Path(aggregate.__code__.co_filename).read_bytes()) != artifact.source_sha256.get(
            "burden.py"
        ):
            raise EvidenceRefused(
                "Stanford count reconciliation requires its producing implementation"
            )
        for edge, report in metrics.items():
            expected = aggregate(
                [row for row in rows[edge] if row["subject_id"] in split.validation_subjects],
                protocol,
            )
            if document_sha256(expected) != document_sha256(report):
                raise EvidenceRefused(
                    "Stanford metric support disagrees with private control counts"
                )
        identities.append(
            EvaluationIdentity(
                run_sha256=digest(run_raw),
                split_sha256=document_sha256(split),
                config_sha256=document_sha256(protocol),
                evaluation_sha256=digest(metrics_raw),
                metric_definition_sha256=document_sha256(definition),
                source_sha256=document_sha256(artifact.source_sha256),
                dataset_snapshot=split.dataset_snapshot,
                test_cohort_sha256=document_sha256(sorted(split.test_subjects)),
                development_cohort_sha256=document_sha256(
                    sorted(split.train_subjects + split.validation_subjects)
                ),
                artifact=pin,
                scored_participants=primary.participants_with_scored_control_days,
                scored_points=primary.counts.get("scored_control_days", 0),
            )
        )
    return DevelopmentReceipt(
        bundle_index_sha256=expected_index,
        files_verified=len(index),
        artifact_bundle_index_sha256=[],
        evaluations=identities,
        comparison_sha256=[],
        task_support=[
            TaskSupport(
                task=t,
                status="development_evidence" if t == "anomaly" else "blocked",
                reason="final_selection_pending"
                if t == "anomaly"
                else "no_verified_development_evidence",
            )
            for t in TASKS
        ],
    )
