"""CPU-only receipt operations. No inference, clock override, or real-case execution."""

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path

from pydantic import ValidationError

from .lifecycle import CaseRefused, preregister, private_read, reveal, seal, verify
from .specification import Prespecification, ResultBatch
from .synthetic import demo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generated = commands.add_parser("synthetic-proof")
    generated.add_argument("--output", type=Path, required=True)
    generated.add_argument("--repo", type=Path, required=True)
    for name in ("preregister", "seal", "reveal", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--inputs", type=Path, required=True)
        command.add_argument("--receipts", type=Path, required=True)
        if name == "preregister":
            command.add_argument("--specification", required=True)
        else:
            command.add_argument("--prespec-pin", required=True)
        if name == "seal":
            command.add_argument("--results", required=True)
        if name in ("reveal", "verify"):
            command.add_argument("--sealed-pin", required=True)
        if name == "verify":
            command.add_argument("--reveal-pin", required=True)
    args = parser.parse_args()
    try:
        if args.repo.resolve() != Path(__file__).resolve().parents[4]:
            raise CaseRefused("CLI must run from the exact source checkout being pinned")
        if args.command == "synthetic-proof":
            result = demo(args.output, args.repo)
        elif args.command == "preregister":
            spec = Prespecification.model_validate_json(
                private_read(args.inputs, args.specification)
            )
            result = {"receipt_sha256": preregister(spec, args.inputs, args.repo, args.receipts)}
        elif args.command == "seal":
            batch = ResultBatch.model_validate_json(private_read(args.inputs, args.results))
            result = {
                "receipt_sha256": seal(
                    args.receipts, args.prespec_pin, batch, args.inputs, args.repo
                )
            }
        elif args.command == "reveal":
            result = {
                "receipt_sha256": reveal(
                    args.receipts, args.prespec_pin, args.sealed_pin, args.inputs, args.repo
                )
            }
        else:
            result = verify(
                args.receipts,
                args.prespec_pin,
                args.sealed_pin,
                args.reveal_pin,
                args.inputs,
                args.repo,
            )
    except (CaseRefused, OSError, ValidationError, subprocess.CalledProcessError, sqlite3.Error):
        # Validation errors include offending data; never print their details.
        print(json.dumps({"status": "refused", "clinical_case_status": "unavailable"}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
