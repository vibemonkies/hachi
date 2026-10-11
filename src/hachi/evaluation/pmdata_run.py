"""Private real-PMData validation runs; the selected outer test remains sealed."""

import argparse
import hashlib
import json
import os
import platform
import resource
import subprocess
import sys
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Annotated, Self

from pydantic import Field, TypeAdapter, model_validator

from hachi.contracts.base import Contract, DatasetSnapshotRef, SubjectId, UtcDatetime
from hachi.contracts.manifests import Exclusion, ModelRef, RunManifest, SplitManifest, TimeWindow
from hachi.data.pmdata import (
    AGGREGATE_AVAILABILITY_RULE,
    dataset_snapshot_ref,
    iter_aggregates,
    load_manifest,
    verify,
)
from hachi.models.baselines import (
    BaselineConfig,
    TreeConfig,
    fit_baseline,
    fit_tree,
    load_artifact,
    save_artifact,
)
from hachi.models.baselines.artifacts import ForecastArtifact, source_hashes
from hachi.models.baselines.tree import FEATURES

from .artifacts import write_packet
from .features import HourlyFeaturePolicy, hourly_features
from .folds import NestedFoldConfig, nested_participant_folds
from .forecast import EvaluationConfig, TrainingPrefix, evaluate_forecast
from .metrics import MetricReport, combine_metric_reports
from .serialization import document_bytes, document_sha256


class PMDataProtocol(Contract):
    split_created_at_utc: UtcDatetime
    expected_snapshot: DatasetSnapshotRef
    folds: NestedFoldConfig
    active_outer_fold: Annotated[int, Field(ge=0)]
    feature_policy: HourlyFeaturePolicy
    evaluation: EvaluationConfig
    evaluation_window: TimeWindow
    lookback_hours: Annotated[int, Field(gt=0)]
    min_history_hours: Annotated[int, Field(ge=0)]
    horizon_hours: Annotated[int, Field(gt=0)]
    cutoff_stride_hours: Annotated[int, Field(gt=0)]
    embargo_hours: Annotated[int, Field(ge=0)]
    baselines: list[BaselineConfig]
    tree: TreeConfig
    exclusions: list[Exclusion]

    @model_validator(mode="after")
    def _protocol(self) -> Self:
        if self.expected_snapshot.dataset_id != "pmdata" or self.evaluation.data_mode != "real":
            raise ValueError("this command requires an admitted real PMData protocol")
        if self.active_outer_fold >= self.folds.outer_folds:
            raise ValueError("active outer fold must belong to the plan")
        if self.min_history_hours > self.lookback_hours:
            raise ValueError("minimum history must fit the lookback")
        if self.feature_policy.availability_rule != AGGREGATE_AVAILABILITY_RULE:
            raise ValueError("use the documented PMData aggregate availability rule")
        if len(self.baselines) != 3 or {c.method for c in self.baselines} != {
            "last_valid",
            "seasonal_naive",
            "train_population_mean",
        }:
            raise ValueError("configure exactly the three simple baselines")
        if any(
            (c.metric, c.aggregation) != (self.evaluation.metric, self.evaluation.aggregation)
            for c in [self.feature_policy, *self.baselines, self.tree]
        ):
            raise ValueError(
                "features, targets and every model must use the same metric/aggregation"
            )
        if self.tree.seed != self.folds.seed or self.tree.max_lead_hours < self.horizon_hours - 1:
            raise ValueError("tree seed and supported lead range must match the protocol")
        return self


def _write_private(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(document_bytes(value))


def _aggregate_metrics(report: MetricReport) -> dict[str, object]:
    return {
        name: asdict(value) if value is not None else None
        for name in (
            "mae",
            "rmse",
            "median_pinball_loss",
            "interval_coverage",
            "mean_interval_width",
        )
        if (value := getattr(report, name)) is not None
    }


def run(snapshot: Path, output: Path, protocol: PMDataProtocol) -> dict[str, object]:
    """Run only inner validation cohorts of one outer fold, exporting each frozen model."""
    output_created = False
    started = perf_counter()
    try:
        verified = verify(snapshot)
        if not verified["ok"] or dataset_snapshot_ref(snapshot) != protocol.expected_snapshot:
            raise ValueError("snapshot verification or admitted identity mismatch")
        roster = TypeAdapter(list[SubjectId], config=Contract.model_config).validate_python(
            load_manifest(snapshot)["subjects"]
        )
        plan = nested_participant_folds(roster, protocol.folds, exclusions=protocol.exclusions)
        selected = [f for f in plan.folds if f.outer_fold == protocol.active_outer_fold]
        bins = tuple(iter_aggregates(snapshot, "hour", metrics=[protocol.evaluation.metric]))
        view = hourly_features(bins, protocol.feature_policy)
        labels = tuple(b.aggregate for b in bins)
        repo = Path(__file__).resolve().parents[3]
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True))
        environment = hashlib.sha256((repo / "uv.lock").read_bytes()).hexdigest()
        now = datetime.now(UTC)
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        output_created = True
        _write_private(output / "protocol.json", protocol)
        _write_private(output / "fold-plan.json", plan)
        _write_private(output / "input-audit.json", {"policy": view.policy, "counts": view.counts})
        reports: dict[str, list[MetricReport]] = defaultdict(list)
        counts: dict[str, Counter[str]] = defaultdict(Counter)
        artifacts: dict[str, list[dict[str, object]]] = defaultdict(list)
        elapsed: dict[str, float] = defaultdict(float)
        for fold in selected:
            fold_root = output / f"outer-{fold.outer_fold}-inner-{fold.inner_fold}"
            fold_root.mkdir(mode=0o700)
            (fold_root / "models").mkdir(mode=0o700)
            (fold_root / "evaluations").mkdir(mode=0o700)
            split = SplitManifest(
                schema_version="0.1",
                manifest_id=f"pmdata-outer{fold.outer_fold}-inner{fold.inner_fold}",
                created_at_utc=protocol.split_created_at_utc,
                dataset_snapshot=protocol.expected_snapshot,
                task="physiology_forecast",
                fold=fold.outer_fold,
                n_folds=protocol.folds.outer_folds,
                **fold.partitions(),
                lookback_hours=protocol.lookback_hours,
                horizon_hours=protocol.horizon_hours,
                embargo_hours=protocol.embargo_hours,
                cutoff_stride_hours=protocol.cutoff_stride_hours,
                min_history_hours=protocol.min_history_hours,
                evaluation_window=protocol.evaluation_window,
                seed=protocol.folds.seed,
                test_opened_at_utc=None,
            )
            for model_config in [*protocol.baselines, protocol.tree]:
                fitted: list[ForecastArtifact] = []

                def factory(
                    training: TrainingPrefix,
                    model_config: BaselineConfig | TreeConfig = model_config,
                    fitted: list[ForecastArtifact] = fitted,
                ):
                    if (
                        len({r.subject_id for r in training.observations})
                        < protocol.folds.min_train_subjects
                    ):
                        raise ValueError("insufficient causally available training participants")
                    model = (
                        fit_tree(training, model_config)
                        if isinstance(model_config, TreeConfig)
                        else fit_baseline(training, model_config)
                    )
                    fitted.append(model)
                    return model.predict

                began = perf_counter()
                result = evaluate_forecast(
                    split, view.features, labels, factory, protocol.evaluation
                )
                model = fitted[0]
                identity = document_sha256({"model": model, "sources": source_hashes()})[:16]
                artifact_id = f"{model.model_id}-{identity}"
                artifact_path = fold_root / "models" / artifact_id
                reference = save_artifact(artifact_path, model, artifact_id=artifact_id)
                loaded = load_artifact(artifact_path, reference)
                replay = evaluate_forecast(
                    split,
                    view.features,
                    labels,
                    lambda _, loaded=loaded: loaded.predict,
                    protocol.evaluation,
                )
                if replay.predictions != result.predictions or replay.counts != result.counts:
                    raise RuntimeError(
                        "saved artifact replay changed predictions or inclusion counts"
                    )
                elapsed[model.model_id] += perf_counter() - began
                run_manifest = RunManifest(
                    schema_version="0.1",
                    run_id=f"outer{fold.outer_fold}-inner{fold.inner_fold}-{model.model_id}",
                    created_at_utc=now,
                    git_sha=git_sha,
                    git_dirty=dirty,
                    config_sha256=document_sha256(protocol.evaluation),
                    dataset_snapshot=protocol.expected_snapshot,
                    split_manifest_sha256=document_sha256(split),
                    task="physiology_forecast",
                    feature_order=list(FEATURES)
                    if isinstance(model_config, TreeConfig)
                    else [protocol.evaluation.metric],
                    model=ModelRef(
                        model_id=model.model_id,
                        checkpoint_source=None,
                        checkpoint_revision=None,
                        license=None,
                    ),
                    environment_sha256=environment,
                    seed=protocol.folds.seed,
                    artifact=reference,
                    metrics_paths=["evaluation.json"],
                )
                write_packet(
                    fold_root / "evaluations" / model.model_id, split, run_manifest, result
                )
                reports[model.model_id].append(result.metrics)
                counts[model.model_id].update(result.counts)
                artifacts[model.model_id].append(reference.model_dump())
        summary: dict[str, object] = {
            "data_mode": "real",
            "git_sha": git_sha,
            "git_dirty": dirty,
            "dataset_snapshot": protocol.expected_snapshot.model_dump(),
            "protocol_sha256": document_sha256(protocol),
            "nested_plan_sha256": document_sha256(plan),
            "environment_sha256": environment,
            "python": platform.python_version(),
            "resources": {
                "elapsed_seconds": perf_counter() - started,
                "peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                * (1 if sys.platform == "darwin" else 1024),
                "scope": "whole process, including snapshot verification and artifact replay",
            },
            "source_sha256": source_hashes(),
            "active_outer_fold": protocol.active_outer_fold,
            "outer_test_sealed": True,
            "outer_test_participants": len(selected[0].test_subjects),
            "validation_participants": len({s for f in selected for s in f.validation_subjects}),
            "inner_folds": len(selected),
            "feature_counts": view.counts,
            "counts_note": (
                "Counts sum disjoint validation folds; roster and training counts repeat per fold."
            ),
            "healthy_alert_burden": "unestimable: PMData has only unknown illness status",
            "models": {
                name: {
                    "metrics": _aggregate_metrics(
                        combine_metric_reports(rows, seed=protocol.folds.seed)
                    ),
                    "counts": dict(counts[name]),
                    "artifacts": artifacts[name],
                    "artifact_replay_verified": True,
                    "elapsed_seconds": elapsed[name],
                }
                for name, rows in sorted(reports.items())
            },
        }
        _write_private(output / "aggregate-summary.json", summary)
        hashes = {
            str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.rglob("*"))
            if p.is_file()
        }
        _write_private(output / "sha256.json", hashes)
        return summary
    except Exception:
        if output_created:
            _write_private(output / "failure.json", {"traceback": traceback.format_exc()})
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    args = parser.parse_args()
    try:
        protocol = PMDataProtocol.model_validate_json(args.protocol.read_bytes())
        print(json.dumps(run(args.snapshot, args.output, protocol), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        # External row validation errors may contain participant data; keep diagnostics private.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
