"""Thin CLI; print only sanitized aggregate receipt information."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from hachi.evaluation.serialization import document_bytes, document_sha256

from .burden import validate_stanford_burden
from .development import validate_development
from .evidence import assemble_forecast_evidence
from .freeze import FreezeRequest, freeze_decisions
from .integrity import EvidenceRefused, require_separate_output, verify_index, write_private
from .selected_export import validate_selected_export
from .selection import validate_selection_links


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    dev = commands.add_parser("development", help="verify existing private development evidence")
    dev.add_argument("--kind", choices=["forecast", "stanford-burden"], default="forecast")
    evidence = commands.add_parser(
        "evidence", help="assemble aggregate forecast development evidence"
    )
    selection = commands.add_parser(
        "selection", help="verify original owner selection packet links"
    )
    selection.add_argument("--expected-summary-sha256", required=True)
    selection.add_argument("--originals-root", type=Path)
    selection.add_argument("--expected-transport-index-sha256")
    selection.add_argument("--expected-export-receipt-sha256")
    selection.add_argument("--expected-export-verification-sha256")
    for command in (dev, evidence, selection):
        command.add_argument("--bundle", type=Path, required=True)
        command.add_argument("--expected-index-sha256", required=True)
        command.add_argument("--index-file", type=Path)
        command.add_argument("--artifact-bundle", type=Path, action="append", default=[])
        command.add_argument("--artifact-index-sha256", action="append", default=[])
        command.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[4])
        command.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify", help="read back a finalization packet's exact bytes")
    check.add_argument("--bundle", type=Path, required=True)
    check.add_argument("--expected-index-sha256", required=True)
    freeze = commands.add_parser(
        "freeze", help="record exact decisions; final test remains blocked"
    )
    freeze.add_argument("--root", type=Path, required=True)
    freeze.add_argument("--request", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"development", "evidence", "selection"}:
            artifacts = list(zip(args.artifact_bundle, args.artifact_index_sha256, strict=True))
            require_separate_output(args.output, [args.bundle, *args.artifact_bundle])
            if args.command == "selection":
                if args.index_file is None or artifacts:
                    raise EvidenceRefused(
                        "owner selection requires its original external score index"
                    )
                assembled = validate_selection_links(
                    args.bundle,
                    args.expected_index_sha256,
                    args.repo,
                    index_path=args.index_file,
                    expected_summary_sha256=args.expected_summary_sha256,
                )
                payloads = {"selection-evidence.json": document_bytes(assembled)}
                export_inputs = [
                    args.originals_root,
                    args.expected_transport_index_sha256,
                    args.expected_export_receipt_sha256,
                    args.expected_export_verification_sha256,
                ]
                if any(v is not None for v in export_inputs):
                    if not all(v is not None for v in export_inputs):
                        raise EvidenceRefused("selected export requires all original handoff pins")
                    require_separate_output(args.output, [args.originals_root])
                    selected = validate_selected_export(
                        args.originals_root,
                        args.expected_transport_index_sha256,
                        args.repo,
                        assembled,
                        expected_receipt_sha256=args.expected_export_receipt_sha256,
                        expected_verification_sha256=args.expected_export_verification_sha256,
                    )
                    payloads["selected-export-evidence.json"] = document_bytes(selected)
                hashes = write_private(args.output, payloads)
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "state": assembled.state,
                            "files": hashes,
                            "receipt_sha256": document_sha256(assembled),
                            "steps": len(assembled.steps),
                            "final_test_authorized": False,
                            "scientific_selection_accepted": False,
                        }
                    )
                )
                return 0
            if args.command == "evidence":
                assembled = assemble_forecast_evidence(
                    args.bundle,
                    args.expected_index_sha256,
                    args.repo,
                    artifact_bundles=artifacts,
                    index_path=args.index_file,
                )
                hashes = write_private(args.output, {"evidence.json": document_bytes(assembled)})
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "state": assembled.state,
                            "evidence_sha256": document_sha256(assembled),
                            "files": hashes,
                            "models": len(assembled.models),
                            "comparisons": len(assembled.comparisons),
                            "final_test_authorized": False,
                        }
                    )
                )
                return 0
            if args.kind == "stanford-burden":
                if artifacts or args.index_file is not None:
                    raise EvidenceRefused("Stanford burden stores its own algorithm artifact")
                receipt = validate_stanford_burden(
                    args.bundle, args.expected_index_sha256, args.repo
                )
            else:
                receipt = validate_development(
                    args.bundle,
                    args.expected_index_sha256,
                    args.repo,
                    artifact_bundles=artifacts,
                    index_path=args.index_file,
                )
            hashes = write_private(args.output, {"development.json": document_bytes(receipt)})
            print(
                json.dumps(
                    {
                        "ok": True,
                        "state": receipt.state,
                        "receipt_sha256": document_sha256(receipt),
                        "files": hashes,
                        "evaluations": len(receipt.evaluations),
                        "comparisons": len(receipt.comparison_sha256),
                        "final_test_authorized": False,
                    }
                )
            )
        elif args.command == "freeze":
            request = FreezeRequest.model_validate_json(args.request.read_bytes())
            receipt = freeze_decisions(args.root, request, args.output)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "state": receipt.state,
                        "receipt_sha256": document_sha256(receipt),
                        "readiness": receipt.readiness,
                        "blockers": receipt.blockers,
                        "final_test_authorized": False,
                    }
                )
            )
        else:
            index = verify_index(args.bundle, args.expected_index_sha256)
            print(json.dumps({"ok": True, "files_verified": len(index)}))
        return 0
    except EvidenceRefused as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}))
    except (ValueError, ValidationError, OSError, KeyError, TypeError):
        # Pydantic errors and OS exceptions can include participant rows or private paths.
        print(
            json.dumps(
                {"ok": False, "reason": "invalid, missing or existing evidence input/output"}
            )
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
