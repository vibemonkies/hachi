"""Clean-source private source-specific recovery comparisons; development aggregates only."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from hachi.contracts.base import SCHEMA_VERSION
from hachi.contracts.manifests import ModelRef, RunManifest, SplitManifest
from hachi.data.clinical import dataset_snapshot_ref
from hachi.evaluation.serialization import document_sha256

from .artifacts import RecoveryArtifact, load_artifact, save_artifact, source_hashes, write_private
from .audits import PUBLIC_AUDIT_POLICY, public_counts
from .clinical import ENDPOINT, landmarks
from .cohorts import STANFORD, cohort_named
from .evaluation import calibration, compare, summarize_scores, supported_horizon
from .protocol import Protocol, load_split
from .survival import fit_survival


def run(snapshot: Path, config: Path, output: Path, repo: Path) -> dict:
    started = perf_counter()
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True).strip():
        raise ValueError("real recovery runs require an exact clean committed source")
    if output.resolve().is_relative_to(repo.resolve()):
        raise ValueError("participant artifacts must be outside the checkout")
    protocol = Protocol.model_validate_json(config.read_bytes())
    cohort = cohort_named(protocol.cohort)
    common, plan = load_split(snapshot, protocol, repo)
    folds_config = common.folds
    active_outer = common.active_outer_fold
    created = common.split_created_at_utc
    ref = dataset_snapshot_ref(snapshot)
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
        "format": "recovery-validation-3",
        "cohort": cohort.name,
        "git_sha": git_sha,
        "git_dirty": False,
        "snapshot_sha256": ref.snapshot_sha256,
        "config_sha256": config_hash,
        "split_protocol_sha256": document_sha256(common),
        "fold_plan_sha256": document_sha256(plan),
        "source_sha256": source_hashes(),
        "environment_sha256": lock_hash,
        "python": platform.python_version(),
        "clock": cohort.clock,
        "symptom_scale": cohort.scale,
        "endpoint": ENDPOINT,
        "outer_test_outcomes_read_this_run": False,
        "outer_test_scored": False,
        "historical_test_aggregate_exposure": protocol.historical_test_aggregate_exposure,
        "public_audit_policy": PUBLIC_AUDIT_POLICY,
        "residual_test_aggregate_inferability": True,
        "outcome_scope": protocol.outcome_scope,
        "censoring": protocol.censoring,
        "selection": protocol.selection,
        "calibration_policy": protocol.calibration,
        "wearable_predictors": False,
        "feature_order": list(cohort.features),
        "readiness": "research_only",
        "production_prediction": "unavailable",
        "folds": [],
    }
    pooled_scores: list[dict] = []
    development_audit: Counter[str] = Counter()
    private_audit = {"folds": []}
    export_audit: Counter[str] = Counter()
    validation_people: set[str] = set()
    for fold in active:
        if validation_people.intersection(fold.validation_subjects):
            raise ValueError("inner validation participants are duplicated")
        validation_people.update(fold.validation_subjects)
        train_landmarks, train_audit = landmarks(snapshot, fold.train_subjects, cohort)
        validation_landmarks, validation_audit = landmarks(
            snapshot, fold.validation_subjects, cohort
        )
        development_audit.update(validation_audit)
        private_audit["folds"].append(
            {
                "inner_fold": fold.inner_fold,
                "train": train_audit,
                "validation": validation_audit,
            }
        )
        train = [r.observation for r in train_landmarks]
        validation = [r.observation for r in validation_landmarks]
        support = supported_horizon(
            train,
            protocol.maximum_export_days,
            protocol.minimum_followed_training_subjects,
            known_at_risk=protocol.support_policy == "known-at-risk",
        )
        fold_report = {
            "inner_fold": fold.inner_fold,
            "train_audit": public_counts(train_audit),
            "validation_audit": public_counts(validation_audit),
            "supported_follow_up_days": support,
            "train_subjects_with_landmarks": len({r.subject for r in train}),
            "validation_subjects_with_landmarks": len({r.subject for r in validation}),
            "support_policy": protocol.support_policy,
            "resolved_training_episodes": sum(r.lower is not None for r in train),
            "support_by_day": [
                {
                    "day": d,
                    "known_at_risk_training_subjects": len(
                        {
                            r.subject
                            for r in train
                            if (r.upper >= d if r.lower is None else r.lower > d)
                        }
                    ),
                    "resolved_training_episodes_by_day": sum(
                        r.lower is not None and r.upper <= d for r in train
                    ),
                }
                for d in range(1, protocol.maximum_export_days + 1)
            ],
        }
        receipt["folds"].append(fold_report)
        if fold_report["resolved_training_episodes"] < protocol.minimum_resolved_training_episodes:
            fold_report["status"] = "unavailable_insufficient_training_events"
            continue
        if support < protocol.primary_horizon_days:
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
        pooled_scores.extend(paired)
        fold_report["calibration"] = {
            name: [
                calibration(
                    validation,
                    m,
                    d,
                    bootstrap=protocol.bootstrap_replicates,
                    seed=folds_config.seed,
                )
                for d in protocol.calibration_days
                if d <= support
            ]
            for name, m in (("baseline", baseline), ("conditional", conditional))
        }
        fold_report["status"] = "research_comparison_only"
        fold_dir = output / f"inner-{fold.inner_fold}"
        fold_dir.mkdir(mode=0o700)
        artifact = RecoveryArtifact(conditional, cohort)
        artifact_ref = save_artifact(
            fold_dir / "model", artifact, f"{cohort.name}-recovery-2-inner-{fold.inner_fold}"
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
            feature_order=list(cohort.features),
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
            export_audit["research_curves"] += 1
            for q, value in loaded.model.quantiles(row.covariates).items():
                export_audit[f"null_quantile_{q}"] += value is None
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
                "feature_order": list(cohort.features),
                "symptom_scale": cohort.scale,
                "landmark": protocol.landmark,
                "clock": receipt["clock"],
                "endpoint": ENDPOINT,
            },
        }.items():
            write_private(fold_dir / name, value)
        fold_report["artifact"] = artifact_ref.model_dump(mode="json")
        fold_report["run_sha256"] = document_sha256(run_manifest)
        fold_report["split_sha256"] = document_sha256(split)
    receipt["pooled_comparison"] = summarize_scores(
        pooled_scores, bootstrap=protocol.bootstrap_replicates, seed=folds_config.seed
    )
    receipt["pooled_comparison"]["horizon_days"] = protocol.primary_horizon_days
    private_audit["development"] = dict(sorted(development_audit.items()))
    write_private(output / "private-audit.json", private_audit)
    receipt["development_audit"] = public_counts(dict(development_audit))
    receipt["private_export_audit"] = dict(sorted(export_audit.items()))
    receipt["elapsed_seconds"] = round(perf_counter() - started, 3)
    receipt["limitations"] = [
        "Small evaluation-sized cohort; inadequate training/clinical follow-up remains a gate.",
        "Current run reads development outcomes only; no test scoring, selection or refit.",
        "One first-observed-symptomatic landmark per episode; later daily cutoffs unvalidated.",
        "Interval bounds reflect incomplete surveys; independent censoring is an assumption.",
        "One symptom-free survey cannot confirm sustained recovery; censoring uses the endpoint.",
        "Bootstrap conditions on fitted models and active outer split; few people limit precision.",
        "No wearables used; paired-day counts are coverage only, not paired-feature evidence.",
        "No cross-cohort date, wearable or serology joins; no friend data analyzed.",
        "Eligibility requires retrospectively ascertained episodes and future follow-up.",
        "Horizon-straddling interval coarsening assumes non-informative observation.",
        "Few clusters/events limit bootstrap precision; fold intervals are descriptive.",
        "Distributions are hypothetical static landmark-covariate projections, not exact dates.",
        "Source-wide #8 audits leave test-label totals roughly inferable from task support.",
        "Minimization removes category breakdowns; it cannot restore historical blinding.",
    ]
    if cohort == STANFORD:
        receipt["limitations"].append(
            "Prior whole-roster audit exposed test aggregates; historical blinding is compromised."
        )
        receipt["limitations"].append(
            "Stanford retains original label-extent support and one-event gate; thin folds."
        )
    else:
        receipt["limitations"].append(
            "Earlier public CMU category counts enabled test-total derivation; exposure recorded."
        )
        receipt["limitations"].append(
            "CMU challenge follow-up is short; Jackson scores do not transfer to app severity."
        )
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
    except Exception:
        # Do not let private input values or participant-bearing tracebacks reach terminal logs.
        parser.exit(
            1, "Recovery run failed; inspect protocol/snapshot/source prerequisites privately.\n"
        )
    print(
        json.dumps(
            {
                k: receipt[k]
                for k in (
                    "git_sha",
                    "git_dirty",
                    "snapshot_sha256",
                    "config_sha256",
                    "fold_plan_sha256",
                    "readiness",
                    "outer_test_outcomes_read_this_run",
                    "historical_test_aggregate_exposure",
                    "pooled_comparison",
                    "elapsed_seconds",
                )
            },
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
