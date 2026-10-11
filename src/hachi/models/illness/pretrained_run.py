"""Local frozen-feature CPU heads; queued inference stays in its owning runtime lane."""

import argparse
import json
import sys
from pathlib import Path

from hachi.evaluation.clinical_protocol import ClinicalProtocol
from hachi.evaluation.serialization import document_sha256

from .encoder_features import EncoderReturnPins, load_encoder_features
from .pretrained_features import build_meanpool_features, load_chronos_features
from .pretrained_protocol import REPO, load_pretrained_protocol
from .protocol import load_protocol
from .run import run, write_private


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--context-packet", type=Path, required=True)
    parser.add_argument(
        "--family",
        choices=["meanpool_hr", "wbm_hr", "moment_hr", "chronos_hr"],
        default="chronos_hr",
    )
    parser.add_argument("--encoder-return", type=Path)
    parser.add_argument(
        "--encoder-pins",
        type=Path,
        default=REPO / "configs/experiments/illness/encoder-return-001.json",
    )
    parser.add_argument("--chronos-inference", type=Path)
    parser.add_argument(
        "--output", type=Path, required=True, help="fresh private CPU run directory"
    )
    parser.add_argument(
        "--comparison", type=Path, default=REPO / "configs/experiments/illness/pretrained.json"
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must be a fresh private run directory")
    if args.family == "chronos_hr" and args.chronos_inference is None:
        parser.error("Chronos features require the queued --chronos-inference packet")
    if args.family in {"wbm_hr", "moment_hr"} and args.encoder_return is None:
        parser.error("Frozen encoders require the original --encoder-return packet")
    try:
        comparison = load_pretrained_protocol(args.comparison)
        task = load_protocol(REPO / comparison.task_protocol.path)
        clinical = ClinicalProtocol.model_validate_json(
            (REPO / comparison.clinical_protocol.path).read_bytes()
        )
        if args.family in {"wbm_hr", "moment_hr"}:
            pins = EncoderReturnPins.model_validate_json(args.encoder_pins.read_bytes())
            features = load_encoder_features(
                args.snapshot, args.context_packet, args.encoder_return, comparison, pins
            )[args.family]
        elif args.family == "meanpool_hr":
            features = build_meanpool_features(args.snapshot, args.context_packet, comparison)
        else:
            features = load_chronos_features(
                args.snapshot, args.context_packet, args.chronos_inference, comparison
            )
        result = run(
            args.snapshot,
            args.output,
            task,
            clinical=clinical,
            external_by_inner=features.by_inner,
            feature_family=features.name,
            comparison=comparison,
            supported_by_inner=features.supported_by_inner,
        )
        write_private(args.output / "feature-provenance.json", features.provenance)
        write_private(args.output / "external-features.json", features.by_inner)
        print(
            json.dumps(
                {
                    "git_sha": result["git_sha"],
                    "comparison_sha256": document_sha256(comparison),
                    "outer_test": "sealed",
                    "serving": "unavailable",
                    "feature_family": features.name,
                    "fold_statuses": [e["status"] for e in result["fold_evidence"]],
                }
            )
        )
        return 0
    except (ValueError, OSError, KeyError):
        print(
            "Frozen-feature run failed validation or I/O; no private rows printed.", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
