"""CLI for #12 on PMData: export GX10 inputs, then score every candidate and select."""

import argparse
import json
import sys
import traceback
from pathlib import Path

from hachi.evaluation.serialization import document_bytes

from .pmdata import export, load_experiment, prepare


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("export")
    command.add_argument("--snapshot", required=True, type=Path)
    command.add_argument("--output", required=True, type=Path, help="new private directory")
    args = parser.parse_args()
    try:
        inputs = prepare(args.snapshot, load_experiment())
        result = export(inputs, args.output)
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    except Exception as error:
        # Row validation errors can quote participant values; keep diagnostics private.
        if args.output.is_dir():
            (args.output / "failure.json").write_bytes(
                document_bytes({"traceback": traceback.format_exc()})
            )
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
