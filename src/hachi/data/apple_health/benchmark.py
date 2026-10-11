"""Reproduce bounded-memory import measurements on generated records only."""

import argparse
import hashlib
import json
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from xml.parsers import expat

from .importer import ImportConfig, import_export
from .store import iter_observations


def _rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


def _worker(count: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="hachi-synthetic-import-") as directory:
        root = Path(directory)
        source = root / "export.xml"
        origin = datetime(2026, 1, 1, tzinfo=UTC)
        with source.open("w") as stream:
            stream.write("<HealthData>")
            for i in range(count):
                instant = origin + timedelta(minutes=i)
                stamp = instant.strftime("%Y-%m-%d %H:%M:%S +0000")
                created = (instant + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S +0000")
                stream.write(
                    '<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Synthetic Watch" '
                    f'unit="count/min" value="64" startDate="{stamp}" endDate="{stamp}" '
                    f'creationDate="{created}"/>'
                )
            stream.write("</HealthData>")
        config = ImportConfig(
            dataset_id="synthetic-memory",
            subject_id="synthetic-001",
            declared_tz_name="UTC",
            data_mode="synthetic",
        )
        database = root / "private" / "import.sqlite3"
        baseline = _rss_bytes()
        start = time.perf_counter()
        audit = import_export(source, config, database)
        readback = sum(1 for _ in iter_observations(database))
        return {
            "data_mode": "synthetic",
            "records": count,
            "records_accepted": audit.counts.records_accepted,
            "readback_records": readback,
            "input_bytes": source.stat().st_size,
            "database_bytes": database.stat().st_size,
            "baseline_peak_rss_bytes": baseline,
            "peak_rss_bytes": _rss_bytes(),
            "elapsed_seconds": time.perf_counter() - start,
            "xml_sha256": audit.xml_sha256,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--records", type=int, default=5000)
    parser.add_argument("--counts", type=int, nargs="+", default=[5000, 50000])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.records < 1 or any(count < 1 for count in args.counts):
        parser.error("record counts must be positive")
    if args.worker:
        print(json.dumps(_worker(args.records)))
        return 0
    runs = []
    for count in args.counts:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "hachi.data.apple_health.benchmark",
                "--worker",
                "--records",
                str(count),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        runs.append(json.loads(result.stdout))
    package = Path(__file__).parent
    output = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "sqlite": sqlite3.sqlite_version,
        "expat": expat.EXPAT_VERSION,
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob("*.py"))
        },
        "runs": runs,
    }
    encoded = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            stream.write(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
