"""Local import command. Prints aggregate audit counts, never raw rows or source names."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError

from .importer import ImportConfig, import_export
from .security import ImportProblem


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--subject-id", required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--data-mode", choices=("synthetic", "real"), required=True)
    args = parser.parse_args()
    try:
        config = ImportConfig(
            dataset_id=args.dataset_id,
            subject_id=args.subject_id,
            declared_tz_name=args.timezone,
            data_mode=args.data_mode,
        )
        audit = import_export(args.input, config, args.database)
    except ImportProblem as exc:
        print(json.dumps({"failure": exc.failure.model_dump()}))
        return 1
    except (OSError, ValueError, ValidationError):
        print(json.dumps({"error": "Check input/configuration and use a new private output path."}))
        return 1
    output = asdict(audit)
    output["counts"] = audit.counts.model_dump()
    output["issues"] = [issue.model_dump() for issue in audit.issues]
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
