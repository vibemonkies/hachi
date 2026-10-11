"""Build, verify and reconcile PMData feature snapshots.

    python -I -m hachi.data.pmdata build [--archive ZIP] [--output-root DIR] [--report JSON]
    python -I -m hachi.data.pmdata verify SNAPSHOT [--full] [--archive ZIP]
    python -I -m hachi.data.pmdata reconcile SNAPSHOT [--archive ZIP]

The archive defaults to $HACHI_DATA_ROOT/pmdata/pmdata.zip and snapshots go under
$HACHI_DATA_ROOT/derived/. Output is aggregate only: no participant rows are printed.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .config import CONFIG_PATH, load_config, registry_admission
from .reconcile import reconcile
from .snapshot import build, git_state, verify

REPO = Path(__file__).resolve().parents[4]


def _data_root() -> Path:
    if "HACHI_DATA_ROOT" not in os.environ:
        raise SystemExit("set HACHI_DATA_ROOT or pass explicit paths")
    return Path(os.environ["HACHI_DATA_ROOT"]).expanduser()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build a new immutable snapshot")
    b.add_argument("--archive", type=Path)
    b.add_argument("--output-root", type=Path)
    b.add_argument("--config", type=Path, default=CONFIG_PATH)
    b.add_argument("--report", type=Path, help="write the sanitized cohort report here")
    v = sub.add_parser("verify", help="check a snapshot's checksums, identity and rows")
    v.add_argument("snapshot", type=Path)
    v.add_argument("--full", action="store_true", help="re-validate every row")
    v.add_argument("--archive", type=Path, help="also re-hash the archive members read")
    r = sub.add_parser("reconcile", help="recompute sampled values straight from the archive")
    r.add_argument("snapshot", type=Path)
    r.add_argument("--archive", type=Path)
    args = parser.parse_args(argv)

    if args.command == "build":
        archive = args.archive or _data_root() / "pmdata" / "pmdata.zip"
        output_root = args.output_root or _data_root() / "derived"
        began = time.monotonic()
        result = build(
            archive, output_root, load_config(args.config), registry_admission(), git_state(REPO)
        )
        if args.report:
            args.report.write_text(json.dumps(result.report, indent=2, sort_keys=True) + "\n")
        summary = {
            "snapshot": str(result.path),
            "dataset_snapshot": result.manifest["dataset_snapshot"],
            "table_rows": {k: v["rows"] for k, v in result.manifest["tables"].items()},
            "seconds": round(time.monotonic() - began, 1),
        }
        print(json.dumps(summary, indent=2))
        return 0
    if args.command == "verify":
        admission = registry_admission() if args.archive else None
        outcome = verify(
            args.snapshot, full=args.full, archive_path=args.archive, admission=admission
        )
        print(json.dumps(outcome, indent=2))
        return 0 if outcome["ok"] else 1
    archive = args.archive or _data_root() / "pmdata" / "pmdata.zip"
    outcome = reconcile(args.snapshot, archive, registry_admission())
    print(json.dumps(outcome, indent=2))
    return 0 if outcome["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
