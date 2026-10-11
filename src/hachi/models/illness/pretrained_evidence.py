"""Publish only re-derived aggregates from a private frozen-feature CPU packet."""

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

from pydantic import TypeAdapter

from hachi.contracts.base import GitSha
from hachi.contracts.manifests import ModelRef, RunManifest, SplitManifest
from hachi.data.clinical.snapshot import dataset_snapshot_ref
from hachi.evaluation.clinical_protocol import ClinicalProtocol, clinical_fold_plan
from hachi.evaluation.serialization import document_bytes, document_sha256

from .artifacts import load, source_hashes
from .data import SURVEY_FEATURE_NAMES, FeatureSet, at_risk_windows, feature_identity
from .encoder_features import EncoderReturnPins, load_encoder_features
from .metrics import Score, report
from .pretrained_features import build_meanpool_features, load_chronos_features, sha
from .pretrained_protocol import REPO, load_pretrained_protocol
from .protocol import load_protocol
from .run import clinical_split
from .support import support_evidence
from .training import calibration_partition


def compile_report(
    snapshot: Path,
    packet: Path,
    run: Path,
    inference: Path | None = None,
    encoder_return: Path | None = None,
    encoder_pins: Path | None = None,
) -> dict:
    comparison = load_pretrained_protocol(REPO / "configs/experiments/illness/pretrained.json")
    task = load_protocol(REPO / comparison.task_protocol.path)
    clinical = ClinicalProtocol.model_validate_json(
        (REPO / comparison.clinical_protocol.path).read_bytes()
    )
    summary = json.loads((run / "summary.json").read_bytes())
    scoring_commit = TypeAdapter(GitSha).validate_python(summary["git_sha"])
    if (
        summary["git_dirty"] is not False
        or summary["outer_test_status"] != "sealed"
        or summary["active_outer_fold"] != 0
        or summary["protocol_sha256"] != task.sha256
        or summary["shared_protocol_sha256"] != document_sha256(clinical)
        or summary["pretrained_protocol_sha256"] != document_sha256(comparison)
        or summary["dataset_snapshot"] != dataset_snapshot_ref(snapshot).model_dump(mode="json")
    ):
        raise ValueError("summary differs from clean frozen clinical run identity")
    # Byte identity binds the claimed scoring commit even after report-only commits.
    for filename, expected in source_hashes().items():
        payload = subprocess.check_output(
            ["git", "show", f"{scoring_commit}:src/hachi/models/illness/{filename}"], cwd=REPO
        )

        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError("scoring commit differs from head replay source")
    name = summary["feature_candidate"]
    if name == "meanpool_hr":
        features = build_meanpool_features(snapshot, packet, comparison)
    elif (
        name in {"wbm_hr", "moment_hr"} and encoder_return is not None and encoder_pins is not None
    ):
        pins = EncoderReturnPins.model_validate_json(encoder_pins.read_bytes())
        features = load_encoder_features(snapshot, packet, encoder_return, comparison, pins)[name]
    elif name == "chronos_hr" and inference is not None:
        features = load_chronos_features(snapshot, packet, inference, comparison)
    else:
        raise ValueError("supported original frozen feature files are required")
    for filename, expected in (
        ("protocol.json", task),
        ("clinical-protocol.json", clinical),
        ("pretrained-protocol.json", comparison),
    ):
        if document_sha256(json.loads((run / filename).read_bytes())) != document_sha256(expected):
            raise ValueError("private run protocol differs from frozen reference")
    saved = TypeAdapter(dict[int, FeatureSet]).validate_json(
        (run / "external-features.json").read_bytes()
    )
    if (
        document_sha256(saved) != document_sha256(features.by_inner)
        or json.loads((run / "feature-provenance.json").read_bytes()) != features.provenance
    ):
        raise ValueError("saved clinical vectors differ from original admitted features")
    plan = clinical_fold_plan(snapshot, clinical)
    if document_sha256(json.loads((run / "fold-plan.json").read_bytes())) != document_sha256(
        plan
    ) or summary["fold_plan_sha256"] != document_sha256(plan):
        raise ValueError("saved clinical plan differs from sealed roster")
    scores = {(h, c): [] for h in task.horizons_hours for c in task.candidate_order}
    statuses = {key: [] for key in scores}
    evidence, replayed, max_delta = [], 0, 0.0
    eligible = {h: [] for h in task.horizons_hours}
    environment = hashlib.sha256(
        subprocess.check_output(["git", "show", f"{scoring_commit}:uv.lock"], cwd=REPO)
    ).hexdigest()
    for fold in plan.folds:
        if fold.outer_fold != 0:
            continue
        rows, _ = at_risk_windows(
            snapshot,
            fold.train_subjects + fold.validation_subjects,
            task,
            features.by_inner[fold.inner_fold],
        )
        for horizon in task.horizons_hours:
            selected = [r for r in rows if r.horizon_hours == horizon]
            validation = [r for r in selected if r.subject_id in fold.validation_subjects]
            eligible[horizon].extend(validation)
            target = {(r.subject_id, r.cutoff): r for r in validation}
            support = support_evidence(
                selected,
                fold.train_subjects,
                fold.validation_subjects,
                features.supported_by_inner[fold.inner_fold],
                task,
                comparison,
            )
            status = "fitted" if support["fit_status"] == "supported" else support["fit_status"]
            for candidate in task.candidate_order:
                root = run / f"inner-{fold.inner_fold}-{horizon}h-{candidate}"
                split = SplitManifest.model_validate_json((root / "split.json").read_bytes())
                if split != clinical_split(snapshot, fold, task, clinical, horizon):
                    raise ValueError("prediction split differs from complete frozen split")
                config = json.loads((root / "config.json").read_bytes())
                if document_sha256(config) != document_sha256(
                    {"task": task, "comparison": comparison}
                ):
                    raise ValueError("prediction configuration differs from frozen reference")
                scored = []
                if status != "fitted":
                    if (root / "predictions.json").exists() or (root / "model").exists():
                        raise ValueError("unsupported fold contains model or scored predictions")
                else:
                    manifest = RunManifest.model_validate_json((root / "run.json").read_bytes())
                    artifact_id = f"illness-dev-inner{fold.inner_fold}-{horizon}h-{candidate}"
                    if (
                        manifest.config_sha256 != document_sha256(config)
                        or manifest.split_manifest_sha256 != document_sha256(split)
                        or manifest.git_sha != scoring_commit
                        or manifest.git_dirty
                        or manifest.run_id != artifact_id
                        or manifest.artifact is None
                        or manifest.artifact.artifact_id != artifact_id
                        or manifest.dataset_snapshot != dataset_snapshot_ref(snapshot)
                        or manifest.task != "illness_onset"
                        or manifest.seed != task.seed
                        or manifest.environment_sha256 != environment
                        or manifest.feature_order
                        != list(
                            SURVEY_FEATURE_NAMES + features.by_inner[fold.inner_fold].feature_names
                        )
                        or manifest.model
                        != ModelRef(
                            model_id=f"illness-development-{candidate}-v1",
                            checkpoint_source=None,
                            checkpoint_revision=None,
                            license=None,
                        )
                        or manifest.metrics_paths != ["predictions.json"]
                    ):
                        raise ValueError("prediction manifest differs from saved configuration")
                    scored = TypeAdapter(list[Score]).validate_json(
                        (root / "predictions.json").read_bytes()
                    )
                    actual = {(s.window.subject_id, s.window.cutoff): s.window for s in scored}
                    if (
                        actual != target
                        or len(actual) != len(scored)
                        or any(
                            not math.isfinite(s.probability) or not 0 <= s.probability <= 1
                            for s in scored
                        )
                    ):
                        raise ValueError(
                            "predictions differ from eligible validation features/labels"
                        )
                    saved_model = load(root / "model", manifest.artifact)
                    fit_subjects, calibration_subjects = calibration_partition(
                        fold.train_subjects, task
                    )
                    train = [r for r in selected if r.subject_id in fold.train_subjects]
                    expected_partitions = {
                        "fit_subjects": fit_subjects,
                        "calibration_subjects": calibration_subjects,
                    }
                    if (
                        saved_model.horizon_hours != horizon
                        or saved_model.candidate != candidate
                        or saved_model.feature_names != tuple(manifest.feature_order)
                        or saved_model.protocol_sha256 != task.sha256
                        or saved_model.feature_sha256
                        != feature_identity(task, features.by_inner[fold.inner_fold])
                        or saved_model.training_sha256
                        != document_sha256({**expected_partitions, "rows": train})
                        or document_sha256(
                            json.loads((root / "training-partitions.json").read_bytes())
                        )
                        != document_sha256(expected_partitions)
                        or any(s.threshold != saved_model.threshold for s in scored)
                    ):
                        raise ValueError("head artifact differs from frozen fit/calibration inputs")
                    replay = saved_model.predict([s.window for s in scored])
                    delta = max(
                        (
                            abs(a.probability - b.probability)
                            for a, b in zip(scored, replay, strict=True)
                        ),
                        default=0,
                    )
                    if delta > 1e-12 or [s.alert for s in scored] != [s.alert for s in replay]:
                        raise ValueError("frozen head artifact replay differs from saved scores")
                    max_delta = max(max_delta, delta)
                    replayed += len(scored)
                scores[(horizon, candidate)].extend(scored)
                statuses[(horizon, candidate)].append(status)
                evidence.append(
                    {
                        "inner_fold": fold.inner_fold,
                        "horizon_hours": horizon,
                        "candidate": candidate,
                        "status": status,
                        "scored_windows": len(scored),
                        "context_support": support,
                    }
                )
    metrics = {}
    for h in task.horizons_hours:
        metrics[str(h)] = {}
        for candidate in task.candidate_order:
            rederived = report(scores[(h, candidate)], task)
            rederived["fold_statuses"] = statuses[(h, candidate)]
            if rederived != summary["reports"][str(h)][candidate]:
                raise ValueError("aggregate report differs from original saved predictions")
            metrics[str(h)][candidate] = rederived
    return {
        "scoring_commit": summary["git_sha"],
        "report_producing_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "comparison_sha256": document_sha256(comparison),
        "task_sha256": task.sha256,
        "clinical_sha256": document_sha256(clinical),
        "fold_plan_sha256": document_sha256(plan),
        "feature_candidate": name,
        "eligible_validation": {
            str(h): {
                "participants": len({r.subject_id for r in rows}),
                "windows": len(rows),
                "positive_windows": sum(r.positive for r in rows),
                "negative_windows": sum(not r.positive for r in rows),
                "incident_episodes": len(
                    {(r.subject_id, r.episode_id) for r in rows if r.episode_id}
                ),
            }
            for h, rows in eligible.items()
        },
        "feature_provenance": features.provenance,
        "private_summary_sha256": sha(run / "summary.json"),
        "fold_evidence": evidence,
        "reports": metrics,
        "head_replay": {"predictions": replayed, "max_probability_delta": max_delta},
        "selection": "descriptive_only_no_final_winner",
        "outer_test": "sealed",
        "population_calibration": "unsupported_selected_survey_cohort",
        "serving": "unavailable",
        "cross_family_comparison": "pending_all_original_frozen_outputs_and_accepted_packets",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--context-packet", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--chronos-inference", type=Path)
    parser.add_argument("--encoder-return", type=Path)
    parser.add_argument(
        "--encoder-pins",
        type=Path,
        default=REPO / "configs/experiments/illness/encoder-return-001.json",
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True):
            raise ValueError("commit implementation before publishing frozen feature evidence")
        result = compile_report(
            args.snapshot,
            args.context_packet,
            args.run,
            args.chronos_inference,
            args.encoder_return,
            args.encoder_pins,
        )
        args.report.write_bytes(document_bytes(result))
        print(
            json.dumps(
                {
                    "feature_candidate": result["feature_candidate"],
                    "head_replay": result["head_replay"],
                    "outer_test": "sealed",
                }
            )
        )
        return 0
    except (ValueError, OSError, KeyError):
        print(
            "Frozen feature evidence failed validation or I/O; no private rows printed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
