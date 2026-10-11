"""Run only sealed-outer-test phase1 CPU development comparisons; stdout is aggregate."""

import argparse
import json
import sys
from pathlib import Path

from hachi.evaluation.clinical_protocol import ClinicalProtocol, clinical_fold_plan
from hachi.evaluation.serialization import document_sha256

from .protocol import load_protocol
from .run import run, write_private
from .stanford import build_features

REPO = Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="fresh private run directory")
    parser.add_argument(
        "--protocol", type=Path, default=REPO / "configs/experiments/illness/phase1.toml"
    )
    parser.add_argument(
        "--clinical-protocol",
        type=Path,
        default=REPO / "configs/evaluation/stanford-phase1-clinical.json",
    )
    parser.add_argument(
        "--feature-family",
        choices=["survey-history-control", "nightly-rest", "anomaly-derived"],
        default="survey-history-control",
    )
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args(argv)
    if args.feature_family != "survey-history-control" and args.archive is None:
        parser.error("nightly/anomaly features require the admitted --archive")
    if args.output.exists():
        parser.error("--output must be a fresh private run directory")
    try:
        protocol = load_protocol(args.protocol)
        clinical = ClinicalProtocol.model_validate_json(args.clinical_protocol.read_bytes())
        plan = clinical_fold_plan(args.snapshot, clinical)
        external = None
        counts = None
        if args.feature_family != "survey-history-control":
            development = sorted(
                {
                    s
                    for f in plan.folds
                    if f.outer_fold == clinical.active_outer_fold
                    for s in f.validation_subjects
                }
            )
            features, counts = build_features(args.snapshot, args.archive, development, protocol)
            external = {
                f.inner_fold: features[args.feature_family]
                for f in plan.folds
                if f.outer_fold == clinical.active_outer_fold
            }
        summary = run(
            args.snapshot,
            args.output,
            protocol,
            clinical=clinical,
            external_by_inner=external,
            feature_family=args.feature_family,
        )
        if counts is not None:
            write_private(args.output / "feature-audit.json", counts)
            write_private(
                args.output / "external-features.json",
                {
                    "family": args.feature_family,
                    "features": features[args.feature_family],
                },
            )
        print(
            json.dumps(
                {
                    "git_sha": summary["git_sha"],
                    "protocol_sha256": protocol.sha256,
                    "shared_protocol_sha256": document_sha256(clinical),
                    "fold_plan_sha256": summary["fold_plan_sha256"],
                    "outer_test_status": summary["outer_test_status"],
                    "feature_family": args.feature_family,
                    "eligible_validation": summary["eligible_validation"],
                    "selection": summary["selection"],
                    "seconds": round(summary["seconds"], 2),
                },
                indent=2,
            )
        )
        return 0
    except (ValueError, OSError, KeyError):
        # Source validation errors can contain private ids/values; keep stdout sanitized.
        print(
            "Illness experiment failed validation or I/O; no private rows printed.", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
