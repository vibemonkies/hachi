"""Reproducible generated-only replay timing; never reads a personal export."""

import argparse
import hashlib
import json
import os
import platform
import resource
import sqlite3
import subprocess
import time
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hachi.data.apple_health import ImportConfig, hourly, import_export, iter_observations
from hachi.evaluation.features import HourlyFeaturePolicy

START = datetime(2025, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


def prepare(root: Path, hours: int, samples_per_hour: int) -> Path:
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    source = root / "generated.xml"
    descriptor = os.open(source, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write("<HealthData>")
        for i in range(hours * samples_per_hour):
            event = START + timedelta(seconds=i * 3600 / samples_per_hour)
            stream.write(
                '<Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" '
                'value="64" sourceName="Synthetic Apple Watch" '
                f'startDate="{event.isoformat()}" endDate="{event.isoformat()}" '
                f'creationDate="{(event + timedelta(seconds=1)).isoformat()}"/>'
            )
        stream.write("</HealthData>")
    database = root / "snapshot.sqlite3"
    audit = import_export(
        source,
        ImportConfig(
            dataset_id="synthetic-hourly-benchmark",
            subject_id="synthetic-only",
            declared_tz_name="UTC",
            data_mode="synthetic",
        ),
        database,
    )
    assert audit.counts.records_accepted == hours * samples_per_hour
    return database


def measure(root: Path, hours: int, samples_per_hour: int, context_hours: int) -> dict:
    database = root / "snapshot.sqlite3"
    # Refuse real/private exports before iterating any native health candidates.
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        (config_json,) = connection.execute(
            "SELECT value FROM metadata WHERE key='config'"
        ).fetchone()
        config = ImportConfig.model_validate_json(config_json)
        if config.data_mode != "synthetic" or config.dataset_id != "synthetic-hourly-benchmark":
            raise ValueError("benchmark requires its own generated synthetic fixture")
    helper_sha = hashlib.sha256(Path(hourly.__file__).read_bytes()).hexdigest()
    print(json.dumps({"phase": "measurement_started", "helper_sha256": helper_sha}), flush=True)
    cutoff = START + hours * HOUR
    policy = HourlyFeaturePolicy(
        metric="heart_rate",
        aggregation="mean",
        min_coverage=0.5,
        min_observed_count=30,
        availability_rule=hourly.AVAILABILITY_RULE,
    )
    durations = []
    checksums = []
    audit_checksums = []
    for label in ("process_cold", "warm"):
        t = time.perf_counter()
        view = hourly.apple_hourly_features(database, policy, cutoff, cutoff - context_hours * HOUR)
        durations.append({"phase": label, "seconds": time.perf_counter() - t})
        payload = [f.model_dump(mode="json") for f in view.features]
        checksums.append(hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
        audits = [asdict(a) for a in view.audits]
        audit_checksums.append(
            hashlib.sha256(
                json.dumps(audits, sort_keys=True, default=lambda stamp: stamp.isoformat()).encode()
            ).hexdigest()
        )
        assert len(view.audits) == context_hours
        assert sum(a.included_records for a in view.audits) == context_hours * samples_per_hour
    t = time.perf_counter()
    native_count = sum(1 for _ in iter_observations(database, as_of=cutoff))
    native_seconds = time.perf_counter() - t
    assert native_count == hours * samples_per_hour
    return {
        "data_mode": "synthetic",
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "helper_sha256": helper_sha,
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "runtime_platform": platform.platform(),
        "snapshot_bytes": database.stat().st_size,
        "clock_start_utc": START.isoformat(),
        "as_of_utc": cutoff.isoformat(),
        "native_hours": hours,
        "native_samples": native_count,
        "samples_per_hour": samples_per_hour,
        "context_hours": context_hours,
        "context_native_samples": context_hours * samples_per_hour,
        "policy": policy.model_dump(),
        "calls": durations,
        "native_once_seconds": native_seconds,
        "feature_count": len(view.features),
        "feature_sha256": checksums[0],
        "cold_warm_feature_identity_equal": checksums[0] == checksums[1],
        "audit_sha256": audit_checksums[0],
        "cold_warm_audits_equal": audit_checksums[0] == audit_checksums[1],
        "audit_counts": {
            key: sum(asdict(a)[key] for a in view.audits)
            for key in (
                "known_candidates",
                "included_records",
                "excluded_created_after_seal",
                "excluded_cross_hour",
                "excluded_by_precedence",
            )
        },
        "cold_definition": "first replay in fresh process; OS filesystem cache not evicted",
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if platform.system() == "Darwin" else 1024),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "measure"))
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--hours", type=int, default=8760)
    parser.add_argument("--samples-per-hour", type=int, default=12)
    parser.add_argument("--context-hours", type=int, default=48)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 0 < args.context_hours <= args.hours or not 0 < args.samples_per_hour <= 3600:
        parser.error("positive context <= history and 1..3600 samples per hour required")
    if args.action == "prepare":
        prepare(args.run_root, args.hours, args.samples_per_hour)
        print(json.dumps({"generated_records": args.hours * args.samples_per_hour}))
    else:
        result = measure(args.run_root, args.hours, args.samples_per_hour, args.context_hours)
        if args.output:
            with args.output.open("x") as stream:
                json.dump(result, stream, indent=2)
                stream.write("\n")
            os.chmod(args.output, 0o600)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
