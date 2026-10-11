"""Publish only re-derived aggregates from a private frozen-feature CPU packet."""

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

from pydantic import TypeAdapter

from hachi.contracts.base import ArtifactRef, GitSha
from hachi.contracts.manifests import SplitManifest
from hachi.evaluation.clinical_protocol import ClinicalProtocol, clinical_fold_plan
from hachi.evaluation.serialization import document_bytes, document_sha256

from .artifacts import load, source_hashes
from .data import FeatureSet, at_risk_windows
from .metrics import Score, report
from .pretrained_features import build_meanpool_features, load_chronos_features, sha
from .pretrained_protocol import REPO, load_pretrained_protocol
from .protocol import load_protocol
from .support import support_evidence


def compile_report(snapshot: Path, packet: Path, run: Path, inference: Path | None = None) -> dict:
    comparison = load_pretrained_protocol(REPO / "configs/experiments/illness/pretrained.json")
    task = load_protocol(REPO / comparison.task_protocol.path)
    clinical = ClinicalProtocol.model_validate_json(
        (REPO / comparison.clinical_protocol.path).read_bytes()
    )
    summary = json.loads((run / "summary.json").read_bytes())
    scoring_commit = TypeAdapter(GitSha).validate_python(summary["git_sha"])
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
    if document_sha256(json.loads((run / "fold-plan.json").read_bytes())) != document_sha256(plan):
        raise ValueError("saved clinical plan differs from sealed roster")
    scores = {(h, c): [] for h in task.horizons_hours for c in task.candidate_order}
    statuses = {key: [] for key in scores}
    evidence, replayed, max_delta = [], 0, 0.0
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
                if split.test_opened_at_utc is not None or any(
                    tuple(getattr(split, key)) != tuple(value)
                    for key, value in fold.partitions().items()
                ):
                    raise ValueError("prediction split differs from sealed participant roles")
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
                    manifest = json.loads((root / "run.json").read_bytes())
                    if (
                        manifest["config_sha256"] != document_sha256(config)
                        or manifest["split_manifest_sha256"] != document_sha256(split)
                        or manifest["git_sha"] != summary["git_sha"]
                        or manifest["git_dirty"]
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
                    ref = ArtifactRef.model_validate_json(json.dumps(manifest["artifact"]))
                    saved_model = load(root / "model", ref)
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
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True):
            raise ValueError("commit implementation before publishing frozen feature evidence")
        result = compile_report(
            args.snapshot, args.context_packet, args.run, args.chronos_inference
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
