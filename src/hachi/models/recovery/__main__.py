"""Clean-source private Stanford recovery comparison; prints sanitized aggregates only."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Annotated, Literal

from hachi.evaluation.clinical_protocol import ClinicalProtocol, clinical_fold_plan
from pydantic import Field

from hachi.contracts.base import SCHEMA_VERSION, Contract, Sha256
from hachi.contracts.manifests import ModelRef, RunManifest, SplitManifest
from hachi.data.clinical import dataset_snapshot_ref
from hachi.evaluation.serialization import document_sha256

from .artifacts import RecoveryArtifact, load_artifact, save_artifact, source_hashes, write_private
from .clinical import ENDPOINT, FEATURES, landmarks
from .evaluation import calibration, compare, supported_horizon
from .survival import fit_survival


class Protocol(Contract):
    protocol_version: Literal["recovery-phase1-research-1"]
    shared_protocol_path: Literal["configs/evaluation/stanford-phase1-clinical.json"]
    expected_shared_protocol_sha256: Sha256
    expected_snapshot_sha256: Sha256
    expected_fold_plan_sha256: Sha256
    endpoint: Literal[ENDPOINT]
    landmark: Literal["first-observed-symptomatic-survey-end-of-day-per-episode"]
    feature_order: tuple[Literal["symptom_count", "max_severity", "severity_sum"], ...]
    primary_horizon_days: Annotated[int, Field(gt=0)]
    maximum_export_days: Annotated[int, Field(gt=0)]
    minimum_followed_training_subjects: Annotated[int, Field(ge=2)]
    ridge: Annotated[float, Field(gt=0)]
    max_iterations: Annotated[int, Field(gt=0)]
    tolerance: Annotated[float, Field(gt=0)]
    bootstrap_replicates: Annotated[int, Field(ge=100)]
    selection: Literal["none-fixed-comparison-no-refit-no-serving"]
    calibration: Literal["unmodified-probabilities-interval-identification-bounds"]
    wearables: Literal["none-symptom-only-primary"]


def run(snapshot: Path, config: Path, output: Path, repo: Path) -> dict:
    started = perf_counter()
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True).strip():
        raise ValueError("real recovery runs require an exact clean committed source")
    if output.resolve().is_relative_to(repo.resolve()):
        raise ValueError("participant artifacts must be outside the checkout")
    protocol = Protocol.model_validate_json(config.read_bytes())
    if (
        protocol.feature_order != FEATURES
        or protocol.maximum_export_days < protocol.primary_horizon_days
    ):
        raise ValueError("feature order/horizon differs from the frozen protocol")
    common_path = repo / protocol.shared_protocol_path
    common = ClinicalProtocol.model_validate_json(common_path.read_bytes())
    if document_sha256(common) != protocol.expected_shared_protocol_sha256:
        raise ValueError("common clinical protocol differs from the frozen reference")
    folds_config = common.folds
    active_outer = common.active_outer_fold
    created = common.split_created_at_utc
    ref = dataset_snapshot_ref(snapshot)
    if ref.snapshot_sha256 != protocol.expected_snapshot_sha256:
        raise ValueError("clinical snapshot is not the frozen symptom-score input")
    plan = clinical_fold_plan(snapshot, common)
    if document_sha256(plan) != protocol.expected_fold_plan_sha256:
        raise ValueError("clinical fold plan differs from the agreed canonical hash")
    active = [f for f in plan.folds if f.outer_fold == active_outer]
    if not active:
        raise ValueError("active outer fold absent")
    os.umask(0o077)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_private(output / "fold-plan.json", plan)
    config_document = {
        "recovery": protocol.model_dump(mode="json"),
        "shared": common.model_dump(mode="json"),
    }
    config_hash = document_sha256(config_document)
    lock_hash = hashlib.sha256((repo / "uv.lock").read_bytes()).hexdigest()
    receipt = {
        "format": "recovery-validation-1",
        "git_sha": git_sha,
        "git_dirty": False,
        "snapshot_sha256": ref.snapshot_sha256,
        "config_sha256": config_hash,
        "shared_protocol_sha256": document_sha256(common),
        "fold_plan_sha256": document_sha256(plan),
        "source_sha256": source_hashes(),
        "environment_sha256": lock_hash,
        "python": platform.python_version(),
        "clock": "floating_local_shifted-not-actual-UTC",
        "endpoint": ENDPOINT,
        "outer_test_opened": False,
        "selection": protocol.selection,
        "calibration_policy": protocol.calibration,
        "wearable_predictors": False,
        "feature_order": list(FEATURES),
        "readiness": "research_only",
        "production_prediction": "unavailable",
        "folds": [],
    }
    for fold in active:
        train_landmarks, train_audit = landmarks(snapshot, fold.train_subjects)
        validation_landmarks, validation_audit = landmarks(snapshot, fold.validation_subjects)
        train = [r.observation for r in train_landmarks]
        validation = [r.observation for r in validation_landmarks]
        support = supported_horizon(
            train, protocol.maximum_export_days, protocol.minimum_followed_training_subjects
        )
        fold_report = {
            "inner_fold": fold.inner_fold,
            "train_audit": train_audit,
            "validation_audit": validation_audit,
            "supported_follow_up_days": support,
            "train_subjects_with_landmarks": len({r.subject for r in train}),
            "validation_subjects_with_landmarks": len({r.subject for r in validation}),
        }
        receipt["folds"].append(fold_report)
        if support < protocol.primary_horizon_days or not any(r.lower is not None for r in train):
            fold_report["status"] = "unavailable_insufficient_training_follow_up"
            continue
        fit_days = max(r.upper for r in train)
        models = [
            fit_survival(
                train,
                conditional=c,
                supported_days=fit_days,
                ridge=protocol.ridge,
                max_iterations=protocol.max_iterations,
                tolerance=protocol.tolerance,
            )
            for c in (False, True)
        ]
        fold_report["optimizer"] = [
            {"converged": m.converged, "iterations": m.iterations} for m in models
        ]
        if not all(m.converged for m in models):
            fold_report["status"] = "unavailable_optimizer_did_not_converge"
            continue
        baseline, conditional = [replace(m, supported_days=support) for m in models]
        metrics, paired = compare(
            validation,
            baseline,
            conditional,
            protocol.primary_horizon_days,
            bootstrap=protocol.bootstrap_replicates,
            seed=folds_config.seed,
        )
        fold_report["comparison"] = metrics
        fold_report["calibration"] = {
            name: [
                calibration(
                    validation,
                    m,
                    d,
                    bootstrap=protocol.bootstrap_replicates,
                    seed=folds_config.seed,
                )
                for d in (3, 7, 14)
                if d <= support
            ]
            for name, m in (("baseline", baseline), ("conditional", conditional))
        }
        fold_report["status"] = "research_comparison_only"
        fold_dir = output / f"inner-{fold.inner_fold}"
        fold_dir.mkdir(mode=0o700)
        artifact = RecoveryArtifact(conditional)
        artifact_ref = save_artifact(
            fold_dir / "model", artifact, f"recovery-research-inner-{fold.inner_fold}"
        )
        loaded = load_artifact(fold_dir / "model", artifact_ref)
        split = SplitManifest(
            schema_version=SCHEMA_VERSION,
            manifest_id=f"recovery-outer-{active_outer}-inner-{fold.inner_fold}",
            created_at_utc=created,
            dataset_snapshot=ref,
            task="recovery",
            fold=fold.inner_fold,
            n_folds=folds_config.inner_folds,
            **fold.partitions(),
            lookback_hours=24,
            horizon_hours=protocol.primary_horizon_days * 24,
            embargo_hours=0,
            cutoff_stride_hours=24,
            min_history_hours=0,
            evaluation_window=None,
            seed=folds_config.seed,
            test_opened_at_utc=None,
        )
        run_manifest = RunManifest(
            schema_version=SCHEMA_VERSION,
            run_id=f"recovery-validation-inner-{fold.inner_fold}",
            created_at_utc=datetime.now(UTC),
            git_sha=git_sha,
            git_dirty=False,
            config_sha256=config_hash,
            dataset_snapshot=ref,
            split_manifest_sha256=document_sha256(split),
            task="recovery",
            feature_order=list(FEATURES),
            model=ModelRef(
                model_id="recovery-ridge-daily-hazard",
                checkpoint_source=None,
                checkpoint_revision=None,
                license=None,
            ),
            environment_sha256=lock_hash,
            seed=folds_config.seed,
            artifact=artifact_ref,
            metrics_paths=["metrics.json"],
        )
        predictions = []
        for landmark in validation_landmarks:
            row = landmark.observation
            expected = artifact.research_payload(row.episode, row.covariates)
            actual = loaded.research_payload(row.episode, row.covariates)
            if expected != actual or loaded.predict(row.episode, row.covariates) is not None:
                raise ValueError("artifact parity/production abstention failed")
            predictions.append(
                {
                    "subject": row.subject,
                    "cutoff": landmark.cutoff,
                    "observation": row,
                    "research_payload": actual,
                    "quantiles": loaded.model.quantiles(row.covariates),
                }
            )
        for name, value in {
            "run.json": run_manifest,
            "split.json": split,
            "config.json": config_document,
            "metrics.json": fold_report,
            "predictions.json": predictions,
            "paired-scores.json": paired,
            "serving.json": {
                "readiness": "research_only",
                "predict": "abstain",
                "feature_order": list(FEATURES),
                "landmark": protocol.landmark,
                "clock": receipt["clock"],
                "endpoint": ENDPOINT,
            },
        }.items():
            write_private(fold_dir / name, value)
        fold_report["artifact"] = artifact_ref.model_dump(mode="json")
        fold_report["run_sha256"] = document_sha256(run_manifest)
        fold_report["split_sha256"] = document_sha256(split)
    receipt["elapsed_seconds"] = round(perf_counter() - started, 3)
    receipt["limitations"] = [
        "Small evaluation-sized cohort; inadequate training/clinical follow-up remains a gate.",
        "Outer test sealed; inner validation only, no final model selection or refit.",
        "One first-observed-symptomatic landmark per episode; later daily cutoffs unvalidated.",
        "Interval bounds reflect incomplete surveys; independent censoring is an assumption.",
        "One symptom-free survey cannot confirm sustained recovery; censoring uses the endpoint.",
        "Bootstrap conditions on fitted models and active outer split; few people limit precision.",
        "No wearables used; paired-day counts are coverage only, not paired-feature evidence.",
        "Unlabeled controls are not negatives; no phase2/CMU/friend data analyzed.",
        "Distributions are hypothetical static landmark-covariate projections, not exact dates.",
    ]
    write_private(output / "aggregate.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[4]
    try:
        receipt = run(args.snapshot, args.config, args.output, repo)
    except (ValueError, OSError, KeyError):
        # Do not let private input values or participant-bearing tracebacks reach terminal logs.
        parser.exit(
            1, "Recovery run failed; inspect protocol/snapshot/source prerequisites privately.\n"
        )
    print(json.dumps(receipt, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
