"""CLI for the PMData Chronos-2 run; see pmdata.py for the export → GX10 → score flow."""

import argparse
import json
import sys
import traceback
from pathlib import Path

from hachi.evaluation.pmdata_run import PMDataProtocol
from hachi.evaluation.serialization import document_bytes

from .pmdata import ChronosPMDataConfig, export, prepare, score


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("export", "score"):
        command = commands.add_parser(name)
        command.add_argument("--snapshot", required=True, type=Path)
        command.add_argument("--protocol", required=True, type=Path)
        command.add_argument("--config", required=True, type=Path)
        command.add_argument("--output", required=True, type=Path, help="new private directory")
        if name == "score":
            command.add_argument("--export", required=True, type=Path)
            command.add_argument("--gx10-run", required=True, type=Path)
    args = parser.parse_args()
    try:
        protocol = PMDataProtocol.model_validate_json(args.protocol.read_bytes())
        config = ChronosPMDataConfig.model_validate_json(args.config.read_bytes())
        inputs = prepare(args.snapshot, protocol, config)
        if args.command == "export":
            result = export(inputs, args.output)
        else:
            result = score(inputs, args.export, args.gx10_run, args.output)
        print(json.dumps(result, indent=2, sort_keys=True))
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
