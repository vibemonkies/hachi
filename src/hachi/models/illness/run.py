"""Development runner with immutable private packets and a sealed outer test."""

import hashlib
import os
import platform
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from hachi.contracts.manifests import ModelRef, RunManifest, SplitManifest
from hachi.data.clinical.snapshot import dataset_snapshot_ref, verify
from hachi.evaluation.clinical_protocol import ClinicalProtocol, clinical_fold_plan
from hachi.evaluation.serialization import document_bytes, document_sha256

from .artifacts import export, load, save
from .data import (
    SURVEY_FEATURE_NAMES,
    FeatureSet,
    at_risk_windows,
    feature_identity,
    roster,
)
from .metrics import Score, paired_auprc, report, scalar_metrics
from .pretrained_protocol import PretrainedProtocol, representation_feature_names
from .protocol import Protocol
from .support import CutoffKey, support_evidence
from .training import calibration_partition, fit


def write_private(path: Path, document: object) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(document_bytes(document))


def run(
    snapshot: Path,
    output: Path,
    protocol: Protocol,
    *,
    clinical: ClinicalProtocol,
    external_by_inner: dict[int, FeatureSet] | None = None,
    feature_family: str = "survey-history-control",
    comparison: PretrainedProtocol | None = None,
    supported_by_inner: dict[int, frozenset[CutoffKey]] | None = None,
) -> dict:
    """Only outer0 inner-validation data score. No switch exists to open outer test."""
    import sklearn

    started = perf_counter()
    if not verify(snapshot)["ok"]:
        raise ValueError("snapshot integrity verification failed")
    plan = clinical_fold_plan(snapshot, clinical)
    if clinical.folds != protocol.folds or clinical.active_outer_fold != protocol.active_outer_fold:
        raise ValueError("task folds differ from shared clinical protocol")
    active = [f for f in plan.folds if f.outer_fold == protocol.active_outer_fold]
    if comparison is not None:
        if (
            comparison.task_protocol.sha256 != protocol.sha256
            or comparison.clinical_protocol.sha256 != document_sha256(clinical)
            or feature_family not in {r.name for r in comparison.representations}
            or external_by_inner is None
            or supported_by_inner is None
            or set(supported_by_inner) != {f.inner_fold for f in active}
        ):
            raise ValueError("frozen comparison requires matching protocols/features/support")
    elif supported_by_inner is not None:
        raise ValueError("support gates require the frozen comparison protocol")
    if external_by_inner is not None:
        if set(external_by_inner) != {f.inner_fold for f in active}:
            raise ValueError("external features require every active inner fold")
        schemas = {f.feature_names for f in external_by_inner.values()}
        if len(schemas) != 1:
            raise ValueError("external feature order must match across all inner folds")
        if comparison is not None:
            representation = next(r for r in comparison.representations if r.name == feature_family)
            if schemas != {representation_feature_names(representation)}:
                raise ValueError("external feature schema differs from frozen representation")
    repo = Path(__file__).resolve().parents[4]
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True))
    if dirty:
        raise ValueError("commit owned implementation before a real experiment")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_private(output / "protocol.json", protocol)
    write_private(output / "fold-plan.json", plan)
    write_private(output / "clinical-protocol.json", clinical)
    if comparison is not None:
        write_private(output / "pretrained-protocol.json", comparison)
    scores: dict[tuple[int, str], list[Score]] = defaultdict(list)
    statuses: dict[tuple[int, str], list[str]] = defaultdict(list)
    evidence = []
    exclusions = []
    eligible_validation = defaultdict(list)
    for fold in plan.folds:
        if fold.outer_fold != protocol.active_outer_fold:
            continue
        external = external_by_inner.get(fold.inner_fold) if external_by_inner else None
        fit_subjects, _ = calibration_partition(fold.train_subjects, protocol)
        if external and not set(external.fit_subjects) <= set(fit_subjects):
            raise ValueError(
                "external feature fitting included calibration or held-out participants"
            )
        names = SURVEY_FEATURE_NAMES + (external.feature_names if external else ())
        rows, counts = at_risk_windows(
            snapshot, fold.train_subjects + fold.validation_subjects, protocol, external
        )
        exclusions.append({"inner_fold": fold.inner_fold, "label_dispositions": counts})
        if comparison is not None:
            supported = supported_by_inner[fold.inner_fold]
            row_keys = {(r.subject_id, r.cutoff) for r in rows}
            if not supported <= row_keys or any(
                ((r.subject_id, r.cutoff) in supported)
                != all(v is not None for v in r.features[len(SURVEY_FEATURE_NAMES) :])
                or (
                    (r.subject_id, r.cutoff) not in supported
                    and any(v is not None for v in r.features[len(SURVEY_FEATURE_NAMES) :])
                )
                for r in rows
            ):
                raise ValueError("runtime support flags differ from exact-cutoff vector presence")
        for h in protocol.horizons_hours:
            train = [
                r for r in rows if r.horizon_hours == h and r.subject_id in fold.train_subjects
            ]
            validation = [
                r for r in rows if r.horizon_hours == h and r.subject_id in fold.validation_subjects
            ]
            eligible_validation[h].extend(validation)
            support = (
                support_evidence(
                    train + validation,
                    fold.train_subjects,
                    fold.validation_subjects,
                    supported_by_inner[fold.inner_fold],
                    protocol,
                    comparison,
                )
                if comparison is not None
                else None
            )
            split = SplitManifest(
                schema_version="0.1",
                manifest_id=f"illness-outer0-inner{fold.inner_fold}-{h}h",
                created_at_utc=clinical.split_created_at_utc,
                dataset_snapshot=dataset_snapshot_ref(snapshot),
                task="illness_onset",
                fold=0,
                n_folds=protocol.outer_folds,
                **fold.partitions(),
                lookback_hours=protocol.feature_lookback_days * 24,
                horizon_hours=h,
                embargo_hours=0,
                cutoff_stride_hours=24,
                min_history_hours=0,
                evaluation_window=None,
                seed=protocol.seed,
                test_opened_at_utc=None,
            )
            for candidate in protocol.candidate_order:
                root = output / f"inner-{fold.inner_fold}-{h}h-{candidate}"
                root.mkdir(mode=0o700)
                if support is not None and support["fit_status"] != "supported":
                    fitted, status = None, support["fit_status"]
                else:
                    fitted, status = fit(candidate, train, fold.train_subjects, protocol)
                statuses[(h, candidate)].append(status)
                entry = {
                    "inner_fold": fold.inner_fold,
                    "horizon_hours": h,
                    "candidate": candidate,
                    "status": status,
                    "train_windows": len(train),
                    "eligible_validation_windows": len(validation),
                    "eligible_validation_participants": len({r.subject_id for r in validation}),
                }
                write_private(root / "split.json", split)
                config = (
                    {"task": protocol, "comparison": comparison}
                    if comparison is not None
                    else protocol
                )
                write_private(root / "config.json", config)
                if support is not None:
                    entry["context_support"] = support
                if fitted is None:
                    entry["scored_validation_windows"] = 0
                    evidence.append(entry)
                    continue
                predicted = fitted.predict(validation)
                artifact = export(
                    fitted,
                    names,
                    horizon_hours=h,
                    protocol_sha256=protocol.sha256,
                    feature_sha256=feature_identity(protocol, external),
                    training_sha256=document_sha256(
                        {
                            "fit_subjects": fitted.fit_subjects,
                            "calibration_subjects": fitted.calibration_subjects,
                            "rows": train,
                        }
                    ),
                )
                artifact_id = f"illness-dev-inner{fold.inner_fold}-{h}h-{candidate}"
                ref = save(root / "model", artifact, artifact_id)
                reloaded = load(root / "model", ref).predict(validation)
                difference = max(
                    (
                        abs(a.probability - b.probability)
                        for a, b in zip(predicted, reloaded, strict=True)
                    ),
                    default=0,
                )
                if difference > 1e-12 or [s.alert for s in predicted] != [
                    s.alert for s in reloaded
                ]:
                    raise ValueError("saved artifact replay differs from fitted classifier")
                write_private(root / "predictions.json", predicted)
                write_private(
                    root / "training-partitions.json",
                    {
                        "fit_subjects": fitted.fit_subjects,
                        "calibration_subjects": fitted.calibration_subjects,
                    },
                )
                manifest = RunManifest(
                    schema_version="0.1",
                    run_id=artifact_id,
                    created_at_utc=datetime.now(UTC),
                    git_sha=git_sha,
                    git_dirty=False,
                    config_sha256=document_sha256(config),
                    dataset_snapshot=dataset_snapshot_ref(snapshot),
                    split_manifest_sha256=document_sha256(split),
                    task="illness_onset",
                    feature_order=list(names),
                    model=ModelRef(
                        model_id=f"illness-development-{candidate}-v1",
                        checkpoint_source=None,
                        checkpoint_revision=None,
                        license=None,
                    ),
                    environment_sha256=hashlib.sha256((repo / "uv.lock").read_bytes()).hexdigest(),
                    seed=protocol.seed,
                    artifact=ref,
                    metrics_paths=["predictions.json"],
                )
                write_private(root / "run.json", manifest)
                write_private(
                    root / "serving.json",
                    {
                        "status": "unavailable",
                        "reason": "DEVELOPMENT_ONLY_SELECTED_SURVEY_COHORT",
                        "feature_order": names,
                        "availability_rule": "survey-available-at-end-of-its-local-day",
                        "lookback_days": protocol.feature_lookback_days,
                        "clock": protocol.clock,
                        "horizon_hours": h,
                        "retrospective_outcome_predictors": False,
                    },
                )
                scores[(h, candidate)].extend(predicted)
                entry |= {
                    "scored_validation_windows": len(predicted),
                    "fit_participants": len(fitted.fit_subjects),
                    "calibration_participants": len(fitted.calibration_subjects),
                    "labeled_fit_participants": len(
                        {r.subject_id for r in train if r.subject_id in fitted.fit_subjects}
                    ),
                    "labeled_calibration_participants": len(
                        {r.subject_id for r in train if r.subject_id in fitted.calibration_subjects}
                    ),
                    "threshold": fitted.threshold,
                    "artifact": ref.model_dump(mode="json"),
                    "replay_max_probability_difference": difference,
                }
                evidence.append(entry)
    summaries, selection = {}, {}
    for h in protocol.horizons_hours:
        summaries[str(h)] = {}
        incumbent = (
            "prevalence" if all(s == "fitted" for s in statuses[(h, "prevalence")]) else None
        )
        comparisons = {}
        for candidate in protocol.candidate_order:
            rows = scores[(h, candidate)]
            summaries[str(h)][candidate] = report(rows, protocol)
            summaries[str(h)][candidate]["fold_statuses"] = statuses[(h, candidate)]
            if candidate == "prevalence":
                continue
            paired = paired_auprc(rows, scores[(h, incumbent)], protocol) if incumbent else None
            comparisons[candidate] = paired
            burden = scalar_metrics(rows)["false_alert_episodes_per_30_negative_cutoff_days"]
            if (
                paired
                and paired["lower"] is not None
                and paired["lower"] > (protocol.selection_min_paired_improvement)
                and burden is not None
                and burden <= (protocol.max_false_alert_episodes_per_30_negative_cutoff_days)
                and all(s == "fitted" for s in statuses[(h, candidate)])
            ):
                incumbent = candidate
        # Promotion is development selection; a baseline failing burden is unavailable too.
        if incumbent is not None:
            burden = scalar_metrics(scores[(h, incumbent)])[
                "false_alert_episodes_per_30_negative_cutoff_days"
            ]
            if burden is None or burden > (
                protocol.max_false_alert_episodes_per_30_negative_cutoff_days
            ):
                incumbent = None
        selection[str(h)] = {
            "development_candidate": incumbent,
            "status": "development_only" if incumbent else "unavailable",
            "paired_auprc_vs_incumbent": comparisons,
            "product_status": "unavailable",
        }
        if comparison is not None:
            selection[str(h)] = {
                "development_candidate": None,
                "status": "descriptive_only_no_selection",
                "product_status": "unavailable",
            }
    summary = {
        "protocol_id": protocol.protocol_id,
        "protocol_sha256": protocol.sha256,
        "shared_protocol_sha256": document_sha256(clinical),
        "git_sha": git_sha,
        "git_dirty": False,
        "data_mode": "real",
        "dataset_snapshot": dataset_snapshot_ref(snapshot).model_dump(mode="json"),
        "fold_plan_sha256": document_sha256(plan),
        "roster_participants": len(roster(snapshot)),
        "outer_test_status": "sealed",
        "active_outer_fold": 0,
        "feature_candidate": feature_family,
        "environment": {"python": platform.python_version(), "sklearn": sklearn.__version__},
        "eligible_validation": {
            str(h): {
                "participants": len({r.subject_id for r in rows}),
                "windows": len(rows),
                "positive_windows": sum(r.positive for r in rows),
                "negative_windows": sum(not r.positive for r in rows),
                "incident_episodes": len(
                    {(r.subject_id, r.episode_id) for r in rows if r.episode_id}
                ),
                "prevalence": sum(r.positive for r in rows) / len(rows) if rows else None,
            }
            for h, rows in eligible_validation.items()
        },
        "fold_evidence": evidence,
        "label_dispositions": exclusions,
        "reports": summaries,
        "selection": selection,
        "gates": {
            "anomaly_derived_candidate": "pending_dependency",
            "pretrained_feature_candidate": "pending_clinical_contexts_and_dependency",
            "population_calibration": "unsupported_selected_survey_cohort",
            "outer_test_evaluation": "sealed_not_run",
            "api_serving": "unavailable",
        },
        "seconds": perf_counter() - started,
    }
    if comparison is not None:
        summary["pretrained_protocol_sha256"] = document_sha256(comparison)
        summary["gates"]["pretrained_feature_candidate"] = "descriptive_development_only"
    write_private(output / "summary.json", summary)
    return summary
