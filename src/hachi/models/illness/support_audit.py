"""Reproduce pre-score availability gates from a verified private context packet."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from hachi.evaluation.clinical_protocol import ClinicalProtocol, clinical_fold_plan
from hachi.evaluation.serialization import document_bytes, document_sha256

from .context_export import verify_packet
from .data import at_risk_windows
from .hourly import ContextProtocol
from .pretrained_features import context_joins, sha
from .pretrained_protocol import REPO, load_pretrained_protocol
from .protocol import load_protocol
from .support import support_evidence


def audit(snapshot: Path, packet: Path, comparison_path: Path) -> dict:
    comparison = load_pretrained_protocol(comparison_path)
    context = ContextProtocol.model_validate_json((packet / "protocol.json").read_bytes())
    clinical = ClinicalProtocol.model_validate_json(
        (packet / "clinical-protocol.json").read_bytes()
    )
    if (
        document_sha256(context) != comparison.context_protocol.sha256
        or document_sha256(clinical) != comparison.clinical_protocol.sha256
    ):
        raise ValueError("support audit packet differs from frozen comparison inputs")
    verified = verify_packet(snapshot, packet)
    task = load_protocol(REPO / comparison.task_protocol.path)
    plan = clinical_fold_plan(snapshot, clinical)
    joins = context_joins(packet)
    evidence = []
    for fold in plan.folds:
        if fold.outer_fold != 0:
            continue
        supported = frozenset(
            (j.subject_id, j.cutoff_floating)
            for j in joins
            if j.inner_fold == fold.inner_fold and j.request_id is not None
        )
        rows, _ = at_risk_windows(snapshot, fold.train_subjects + fold.validation_subjects, task)
        for horizon in task.horizons_hours:
            evidence.append(
                {
                    "inner_fold": fold.inner_fold,
                    "horizon_hours": horizon,
                    **support_evidence(
                        [r for r in rows if r.horizon_hours == horizon],
                        fold.train_subjects,
                        fold.validation_subjects,
                        supported,
                        task,
                        comparison,
                    ),
                }
            )
    return {
        "producing_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "comparison_sha256": document_sha256(comparison),
        "context_policy_sha256": document_sha256(context),
        "fold_plan_sha256": verified["fold_plan_sha256"],
        "snapshot_sha256": task.snapshot_sha256,
        "context_join_file_sha256": sha(packet / "joins.json"),
        "support_definition": "hourly-coverage-only-upper-bound-runtime-vector-flags-pending",
        "feature_scores": "not_run",
        "outer_test": "sealed",
        "fold_evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument(
        "--comparison", type=Path, default=REPO / "configs/experiments/illness/pretrained.json"
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True):
            raise ValueError("commit implementation before publishing support evidence")
        result = audit(args.snapshot, args.packet, args.comparison)
        args.report.write_bytes(document_bytes(result))
        print(
            json.dumps(
                {
                    "folds_checked": len(result["fold_evidence"]),
                    "feature_scores": "not_run",
                    "outer_test": "sealed",
                }
            )
        )
        return 0
    except (ValueError, OSError, KeyError):
        print("Support audit failed validation or I/O; no private rows printed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
