"""Build and verify outcome-label snapshots (#8).

    python -I -m hachi.data.clinical build DATASET_ID [--data-dir DIR] [--output-root DIR]
                                                     [--report-dir DIR] [--workers N]
    python -I -m hachi.data.clinical verify SNAPSHOT [--full]
    python -I -m hachi.data.clinical reconcile SNAPSHOT [--data-dir DIR]

DATASET_ID is stanford-covid19-wearables, stanford-covid19-wearables-phase2 or
cmu-common-cold-project. Source files default to $HACHI_DATA_ROOT/<dataset_id>/ and snapshots go
under $HACHI_DATA_ROOT/derived/. Output is aggregate only: no participant rows are printed.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import cmu, stanford
from .config import load_definitions, load_stanford, registry_admission
from .reconcile import reconcile
from .report import write_report
from .snapshot import build, git_state, load_manifest, verify

REPO = Path(__file__).resolve().parents[4]
DATASETS = (*stanford.READERS, cmu.DATASET_ID)


def _data_root() -> Path:
    if "HACHI_DATA_ROOT" not in os.environ:
        raise SystemExit("set HACHI_DATA_ROOT or pass explicit paths")
    return Path(os.environ["HACHI_DATA_ROOT"]).expanduser()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build a new immutable label snapshot")
    b.add_argument("dataset_id", choices=DATASETS)
    b.add_argument("--data-dir", type=Path, help="defaults to $HACHI_DATA_ROOT/<dataset_id>")
    b.add_argument("--output-root", type=Path)
    b.add_argument("--report-dir", type=Path, help="write the sanitized report (JSON, Markdown)")
    b.add_argument("--workers", type=int, default=6)
    v = sub.add_parser("verify", help="check a snapshot's checksums, identity and rows")
    v.add_argument("snapshot", type=Path)
    v.add_argument("--full", action="store_true", help="re-validate every outcome row")
    r = sub.add_parser("reconcile", help="check a Stanford snapshot against its source workbook")
    r.add_argument("snapshot", type=Path)
    r.add_argument("--data-dir", type=Path, help="defaults to $HACHI_DATA_ROOT/<dataset_id>")
    args = parser.parse_args(argv)

    if args.command == "reconcile":
        dataset_id = load_manifest(args.snapshot)["dataset_snapshot"]["dataset_id"]
        settings = load_stanford(dataset_id).value
        data_dir = args.data_dir or _data_root() / dataset_id
        outcome = reconcile(args.snapshot, data_dir / settings.labels_workbook, settings)
        print(json.dumps(outcome, indent=2))
        return 0 if outcome["ok"] else 1

    if args.command == "verify":
        outcome = verify(args.snapshot, full=args.full)
        print(json.dumps(outcome, indent=2))
        return 0 if outcome["ok"] else 1

    data_dir = args.data_dir or _data_root() / args.dataset_id
    output_root = args.output_root or _data_root() / "derived"
    definitions = load_definitions()
    admission = registry_admission(args.dataset_id)
    began = time.monotonic()
    if args.dataset_id == cmu.DATASET_ID:
        settings = cmu.load_settings()
        cmu.require_registered_analysis(settings.value)
        sources = [settings.value.data_file_archive]
        make = lambda: cmu.label_set(data_dir, settings.value, admission)  # noqa: E731
    else:
        settings = load_stanford(args.dataset_id)
        sources = [settings.value.archive, settings.value.labels_workbook]
        make = lambda: stanford.label_set(  # noqa: E731
            data_dir, settings.value, admission, workers=args.workers
        )
    result = build(
        make,
        admission=admission,
        sources_read=sources,
        definitions=definitions,
        settings=settings,
        pipeline_version=settings.value.pipeline_version,
        output_root=output_root,
        git=git_state(REPO),
    )
    if args.report_dir:
        write_report(result.report, args.report_dir)
    summary = {
        "snapshot": str(result.path),
        "dataset_snapshot": result.manifest["dataset_snapshot"],
        "table_rows": {k: v["rows"] for k, v in result.manifest["tables"].items()},
        "seconds": round(time.monotonic() - began, 1),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
