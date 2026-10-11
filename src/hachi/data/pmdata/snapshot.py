"""Build, publish, read and verify immutable PMData feature snapshots.

A snapshot directory holds Parquet tables, a manifest, the private audit and SHA256SUMS. Its
name ends with the first 12 hex digits of its snapshot hash, which covers the admitted
archive, every member read, the pipeline configuration and every table. The same code, config
and archive give a byte-identical directory.
"""

import hashlib
import json
import os
import platform
import stat
import subprocess
import tempfile
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pydantic

from hachi.contracts.base import SCHEMA_VERSION, DatasetSnapshotRef
from hachi.contracts.metrics import METRICS
from hachi.contracts.tables import Aggregate, Observation, StatusUnknown

from . import audit, sources, wellness
from .aggregates import Obs, subject_aggregates, subject_grids
from .archive import Archive, open_archive, sha256_file
from .clock import from_us
from .config import Admission, LoadedConfig

UTC_US = pa.timestamp("us", tz="UTC")
OBSERVATION_SCHEMA = pa.schema(
    [
        ("dataset_id", pa.string()),
        ("subject_id", pa.string()),
        ("record_id", pa.string()),
        ("source_kind", pa.string()),
        ("source_id", pa.string()),
        ("device_model", pa.string()),
        ("metric", pa.string()),
        ("value", pa.float64()),
        ("unit", pa.string()),
        ("start_utc", UTC_US),
        ("end_utc", UTC_US),
        ("available_at_utc", UTC_US),
        ("availability", pa.string()),
        ("availability_rule", pa.string()),
        ("tz_name", pa.string()),
        ("utc_offset_minutes", pa.int16()),
        ("tz_provenance", pa.string()),
    ]
)
AGGREGATE_SCHEMA = pa.schema(
    [
        ("dataset_id", pa.string()),
        ("subject_id", pa.string()),
        ("metric", pa.string()),
        ("unit", pa.string()),
        ("resolution", pa.string()),
        ("interval_start_utc", UTC_US),
        ("interval_end_utc", UTC_US),
        ("local_date", pa.date32()),
        ("tz_name", pa.string()),
        ("aggregation", pa.string()),
        ("value", pa.float64()),
        ("null_reason", pa.string()),
        ("observed_count", pa.int64()),
        ("coverage", pa.float64()),
        ("source_ids", pa.list_(pa.string())),
        ("pipeline_version", pa.string()),
        # Pipeline metadata, not an Aggregate field: see aggregates.py.
        ("available_at_utc", UTC_US),
    ]
)
WELLNESS_SCHEMA = pa.schema(
    [
        ("dataset_id", pa.string()),
        ("subject_id", pa.string()),
        ("local_date", pa.date32()),
        ("tz_name", pa.string()),
        ("item", pa.string()),
        ("value", pa.float64()),
        ("null_reason", pa.string()),
        ("higher_means", pa.string()),
        ("report_id", pa.string()),
        ("reported_at_utc", UTC_US),
        ("reports_that_day", pa.int64()),
    ]
)
OUTCOME_SCHEMA = pa.schema(
    [
        ("kind", pa.string()),
        ("dataset_id", pa.string()),
        ("subject_id", pa.string()),
        ("start_utc", UTC_US),
        ("end_utc", UTC_US),
        ("reason", pa.string()),
        ("note", pa.string()),
    ]
)
TABLES = {
    "observations.parquet": OBSERVATION_SCHEMA,
    "aggregates_hourly.parquet": AGGREGATE_SCHEMA,
    "aggregates_daily.parquet": AGGREGATE_SCHEMA,
    "wellness_daily.parquet": WELLNESS_SCHEMA,
    "outcomes.parquet": OUTCOME_SCHEMA,
}
PARQUET_OPTIONS = {"compression": "zstd", "compression_level": 9, "write_statistics": True}
VALIDATION_BATCH = 65_536


class SnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class GitState:
    sha: str
    dirty: bool


def git_state(repo: Path) -> GitState:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()

    return GitState(run("rev-parse", "HEAD"), bool(run("status", "--porcelain")))


@dataclass(frozen=True)
class BuildResult:
    path: Path
    manifest: dict[str, Any]
    report: dict[str, Any]


def _canonical(document: Any) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), default=str).encode()


def _write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True, default=str) + "\n")


def source_id(subject: str) -> str:
    return f"{subject}-fitbit"


def _observation_table(p: sources.Participant, config, dataset_id: str) -> pa.Table:
    rows, n = p.rows, len(p.rows)
    repeat = lambda value: pa.repeat(pa.scalar(value, pa.string()), n)  # noqa: E731
    stamps = lambda values: pa.array(values, pa.int64()).cast(UTC_US)  # noqa: E731
    table = pa.table(
        {
            "dataset_id": repeat(dataset_id),
            "subject_id": repeat(p.subject),
            "record_id": pa.array(rows.record_id, pa.string()),
            "source_kind": repeat(config.source_kind),
            "source_id": repeat(source_id(p.subject)),
            "device_model": repeat(config.device_model),
            "metric": pa.array(rows.metric, pa.string()),
            "value": pa.array(rows.value, pa.float64()),
            "unit": pa.array([METRICS[m].unit for m in rows.metric], pa.string()),
            "start_utc": stamps(rows.start),
            "end_utc": stamps(rows.end),
            "available_at_utc": stamps(rows.available),
            "availability": repeat("assumed"),
            "availability_rule": pa.array(rows.rule, pa.string()),
            "tz_name": repeat(config.local_timezone),
            "utc_offset_minutes": pa.nulls(n, pa.int16()),
            "tz_provenance": repeat("dataset_documentation"),
        },
        schema=OBSERVATION_SCHEMA,
    )
    order = pc.sort_indices(
        table, [("metric", "ascending"), ("start_utc", "ascending"), ("record_id", "ascending")]
    )
    return table.take(order)


def _validate(table: pa.Table, model, drop: Sequence[str] = ()) -> None:
    for batch in table.to_batches(max_chunksize=VALIDATION_BATCH):
        for row in batch.to_pylist():
            for column in drop:
                row.pop(column)
            model.model_validate(row)


def _aggregation_inputs(p: sources.Participant) -> dict[str, list[Obs]]:
    rows, source = p.rows, source_id(p.subject)
    by_metric: dict[str, list[Obs]] = {}
    for i, metric in enumerate(rows.metric):
        by_metric.setdefault(metric, []).append(
            Obs(
                rows.start[i],
                rows.end[i],
                rows.value[i],
                rows.available[i],
                source,
                rows.record_id[i],
            )
        )
    for obs in by_metric.values():
        obs.sort(key=lambda o: (o.start, o.record_id))
    return by_metric


def _member_inventory(archive: Archive) -> dict[str, Any]:
    read = {
        name: {"sha256": d.sha256, "bytes": d.size} for name, d in sorted(archive.digests.items())
    }
    not_read: dict[str, dict[str, int]] = {}
    for m in archive.members:
        if m.role == "not_read":
            entry = not_read.setdefault(m.kind, {"files": 0, "bytes": 0})
            entry["files"] += 1
            entry["bytes"] += m.size
    return {"read": read, "not_read": not_read}


def snapshot_hash(manifest: dict[str, Any]) -> str:
    """Hash of everything the snapshot's contents depend on, excluding how it was built."""
    basis = {
        "schema_version": manifest["schema_version"],
        "dataset_id": manifest["dataset_snapshot"]["dataset_id"],
        "dataset_version": manifest["dataset_snapshot"]["dataset_version"],
        "pipeline_version": manifest["pipeline_version"],
        "config_sha256": manifest["config"]["sha256"],
        "archive_sha256": manifest["source"]["archive_sha256"],
        "members_read": {k: v["sha256"] for k, v in manifest["source"]["members"]["read"].items()},
        "tables": {k: v["sha256"] for k, v in manifest["tables"].items()},
        "audit_sha256": manifest["audit_sha256"],
    }
    return hashlib.sha256(_canonical(basis)).hexdigest()


def build(
    archive_path: Path,
    output_root: Path,
    loaded: LoadedConfig,
    admission: Admission,
    git: GitState,
) -> BuildResult:
    """Build a snapshot into a fresh directory under output_root; never overwrite one."""
    config = loaded.config
    if config.dataset_id != admission.dataset_id:
        raise SnapshotError("config and admission name different datasets")
    output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".building-", dir=output_root))
    try:
        result = _build_into(staging, archive_path, output_root, loaded, admission, git)
    except BaseException:
        _remove_tree(staging)
        raise
    return result


def _build_into(staging, archive_path, output_root, loaded, admission, git) -> BuildResult:
    config = loaded.config
    zone = config.local_timezone
    counts: Counter = Counter()
    alignment = audit.ClockAlignment()
    timing: Counter = Counter()
    hourly, daily, wellness_rows, outcomes = [], [], [], []
    per_subject: dict[str, dict[str, Any]] = {}
    with open_archive(archive_path, admission) as archive:
        subjects = archive.subjects()
        writer = pq.ParquetWriter(
            staging / "observations.parquet", OBSERVATION_SCHEMA, **PARQUET_OPTIONS
        )
        try:
            for subject in subjects:
                p = sources.participant(archive, subject, config, counts)
                table = _observation_table(p, config, config.dataset_id)
                _validate(table, Observation)
                for metric in sorted(set(p.rows.metric)):
                    writer.write_table(table.filter(pc.field("metric") == metric))
                by_metric = _aggregation_inputs(p)
                grids = subject_grids(by_metric, zone)
                aggregates = subject_aggregates(subject, by_metric, config, grids)
                for resolution, sink in (("hour", hourly), ("day", daily)):
                    part = pa.Table.from_pylist(aggregates[resolution], schema=AGGREGATE_SCHEMA)
                    _validate(part, Aggregate, drop=("available_at_utc",))
                    sink.append(part)
                reports = wellness.read_reports(archive, subject, zone, counts)
                days = [b.local_date for b in grids["day"]] or [r.local_date for r in reports]
                rows = (
                    wellness.daily_rows(
                        config.dataset_id, subject, reports, min(days), max(days), zone, counts
                    )
                    if days
                    else []
                )
                wellness_rows.extend(rows)
                span = [b for g in grids.values() for b in g]
                if span:
                    start = from_us(min(b.start for b in span))
                    end = from_us(max(b.end for b in span))
                    outcomes.append(wellness.unknown_status(config.dataset_id, subject, start, end))
                alignment.add(p)
                audit.wellness_timing(reports, p, timing)
                per_subject[subject] = _subject_summary(p, aggregates, rows)
        finally:
            writer.close()
        inventory = _member_inventory(archive)
        members = archive.members
    tables = {
        "aggregates_hourly.parquet": pa.concat_tables(hourly)
        if hourly
        else AGGREGATE_SCHEMA.empty_table(),
        "aggregates_daily.parquet": pa.concat_tables(daily)
        if daily
        else AGGREGATE_SCHEMA.empty_table(),
        "wellness_daily.parquet": pa.Table.from_pylist(
            [r.model_dump() for r in wellness_rows], schema=WELLNESS_SCHEMA
        ),
        "outcomes.parquet": pa.Table.from_pylist(
            [o.model_dump() for o in outcomes], schema=OUTCOME_SCHEMA
        ),
    }
    for name, table in tables.items():
        pq.write_table(table, staging / name, **PARQUET_OPTIONS)

    report = _report(
        config, admission, counts, members, tables, alignment, timing, wellness_rows, per_subject
    )
    private = {**report, "per_subject": per_subject}
    _write_json(staging / "audit.json", private)

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": config.pipeline_version,
        "dataset_snapshot": {
            "dataset_id": admission.dataset_id,
            "dataset_version": admission.dataset_version,
        },
        "config": {
            "path": "configs/features/pmdata.toml",
            "sha256": loaded.sha256,
            "content": config.model_dump(mode="json"),
        },
        "source": {
            "archive": admission.archive_name,
            "archive_bytes": admission.archive_bytes,
            "archive_sha256": admission.archive_sha256,
            "members": inventory,
        },
        "tables": {
            name: {
                "sha256": sha256_file(staging / name),
                "rows": pq.read_metadata(staging / name).num_rows,
                "columns": TABLES[name].names,
            }
            for name in TABLES
        },
        "audit_sha256": sha256_file(staging / "audit.json"),
        "subjects": sorted(per_subject),
        "time_mappings": {
            "fitbit_intraday": "Naive 'YYYY-MM-DD HH:MM:SS' read as UTC (audit: clock_alignment).",
            "fitbit_sleep": f"Naive local wall time in {zone}; logs spanning a DST change are "
            "quarantined.",
            "fitbit_daily": f"Local calendar day in {zone}, midnight to midnight.",
            "pmsys_wellness": "ISO 8601 with Z, read as UTC (audit: wellness_timing).",
        },
        "availability_rules": sources.rules(config),
        "built_with": {
            "git_sha": git.sha,
            "git_dirty": git.dirty,
            "python": platform.python_version(),
            "pyarrow": pa.__version__,
            "pydantic": pydantic.VERSION,
        },
    }
    digest = snapshot_hash(manifest)
    manifest["dataset_snapshot"]["snapshot_sha256"] = digest
    DatasetSnapshotRef.model_validate(manifest["dataset_snapshot"])
    snapshot_id = f"{config.pipeline_version}-{admission.dataset_version}-{digest[:12]}"
    manifest["snapshot_id"] = snapshot_id
    _write_json(staging / "manifest.json", manifest)
    report = {
        "snapshot_id": snapshot_id,
        "dataset_snapshot": manifest["dataset_snapshot"],
        **report,
    }

    final = output_root / snapshot_id
    if final.exists():
        raise SnapshotError(f"{final} already exists; snapshots are never overwritten")
    sums = "".join(
        f"{sha256_file(staging / name)}  {name}\n" for name in sorted(os.listdir(staging))
    )
    (staging / "SHA256SUMS").write_text(sums)
    os.rename(staging, final)
    _make_read_only(final)
    return BuildResult(final, manifest, report)


def _subject_summary(p: sources.Participant, aggregates, wellness_rows) -> dict[str, Any]:
    days = aggregates["day"]
    valued = Counter(
        r["metric"] for r in days if r["value"] is not None and r["aggregation"] in ("mean", "sum")
    )
    return {
        "observations": dict(sorted(Counter(p.rows.metric).items())),
        "local_days": len({r["local_date"] for r in days}),
        "days_with_value": dict(sorted(valued.items())),
        "wellness_days_with_report": len(
            {r.local_date for r in wellness_rows if r.reports_that_day}
        ),
        "sleep_logs": len(p.sleep_logs),
    }


def _report(
    config, admission, counts, members, tables, alignment, timing, wellness_rows, per_subject
):
    def dist(key: str, sub: str | None = None) -> dict[str, float] | None:
        values = []
        for summary in per_subject.values():
            value = summary[key] if sub is None else summary[key].get(sub, 0)
            values.append(value)
        return audit._distribution(values)

    label_counts = Counter()
    for row in wellness_rows:
        label_counts[(row.item, row.null_reason or "observed")] += 1
    return {
        "dataset": {
            "dataset_id": admission.dataset_id,
            "dataset_version": admission.dataset_version,
            "archive": admission.archive_name,
            "archive_bytes": admission.archive_bytes,
            "archive_sha256": admission.archive_sha256,
        },
        "pipeline_version": config.pipeline_version,
        "participants": len(per_subject),
        "per_participant_distributions": {
            "local_days_in_span": dist("local_days"),
            "days_with_heart_rate": dist("days_with_value", "heart_rate"),
            "days_with_steps": dist("days_with_value", "steps"),
            "days_with_resting_heart_rate": dist("days_with_value", "resting_heart_rate_vendor"),
            "days_with_sleep_in_bed": dist("days_with_value", "sleep_in_bed"),
            "wellness_days_with_report": dist("wellness_days_with_report"),
            "sleep_logs_kept": dist("sleep_logs"),
        },
        "table_rows": {name: table.num_rows for name, table in tables.items()},
        "observations_by_metric": dict(
            sorted(
                sum((Counter(s["observations"]) for s in per_subject.values()), Counter()).items()
            )
        ),
        "sources": audit.source_table(counts, members),
        "missingness": audit.missingness(
            {
                "hour": tables["aggregates_hourly.parquet"],
                "day": tables["aggregates_daily.parquet"],
            }
        ),
        "wellness_labels": [
            {"item": item, "status": status, "days": n}
            for (item, status), n in sorted(label_counts.items())
        ],
        "wellness_scales": audit.direction_evidence(wellness_rows),
        "clock_alignment": alignment.result(),
        "wellness_timing": dict(sorted(timing.items())),
    }


def _make_read_only(path: Path) -> None:
    for child in path.iterdir():
        child.chmod(stat.S_IRUSR | stat.S_IRGRP)
    path.chmod(stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    path.chmod(stat.S_IRWXU)
    for child in path.iterdir():
        child.chmod(stat.S_IRUSR | stat.S_IWUSR)
        child.unlink()
    path.rmdir()


# Reading ---------------------------------------------------------------------------------


def load_manifest(snapshot: Path) -> dict[str, Any]:
    return json.loads((snapshot / "manifest.json").read_text())


def dataset_snapshot_ref(snapshot: Path) -> DatasetSnapshotRef:
    return DatasetSnapshotRef.model_validate(load_manifest(snapshot)["dataset_snapshot"])


def _filter(
    *,
    subjects: Sequence[str] | None,
    metrics: Sequence[str] | None,
    extra: list[ds.Expression],
) -> ds.Expression | None:
    parts = list(extra)
    if subjects is not None:
        parts.append(ds.field("subject_id").isin(list(subjects)))
    if metrics is not None:
        parts.append(ds.field("metric").isin(list(metrics)))
    if not parts:
        return None
    expression = parts[0]
    for part in parts[1:]:
        expression = expression & part
    return expression


def _utc(value: datetime) -> pa.Scalar:
    if value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
        raise ValueError("cutoffs and windows must be UTC-aware datetimes")
    return pa.scalar(value, UTC_US)


def iter_observations(
    snapshot: Path,
    *,
    as_of: datetime | None = None,
    subjects: Sequence[str] | None = None,
    metrics: Sequence[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Iterator[Observation]:
    """Canonical observations, optionally only those available by `as_of` (end and availability).

    `start`/`end` keep observations overlapping [start, end). Heart rate holds ~21 million rows;
    filter by subject and metric rather than loading everything.
    """
    extra = []
    if as_of is not None:
        cutoff = _utc(as_of)
        extra += [ds.field("end_utc") <= cutoff, ds.field("available_at_utc") <= cutoff]
    if start is not None:
        extra.append(ds.field("end_utc") >= _utc(start))
    if end is not None:
        extra.append(ds.field("start_utc") < _utc(end))
    dataset = ds.dataset(snapshot / "observations.parquet", format="parquet")
    expression = _filter(subjects=subjects, metrics=metrics, extra=extra)
    for batch in dataset.to_batches(filter=expression, batch_size=VALIDATION_BATCH):
        for row in batch.to_pylist():
            yield Observation.model_validate(row)


# How a bin's available_at_utc is derived: the latest availability of any observation or
# coverage span it depends on, never before the bin ends (see aggregates.py).
AGGREGATE_AVAILABILITY_RULE = "pmdata-aggregate-final-at-latest-input"


class FeatureBin(NamedTuple):
    """A canonical Aggregate and the moment it became final (AGGREGATE_AVAILABILITY_RULE)."""

    aggregate: Aggregate
    available_at_utc: datetime


def iter_aggregates(
    snapshot: Path,
    resolution: Literal["hour", "day"],
    *,
    as_of: datetime | None = None,
    subjects: Sequence[str] | None = None,
    metrics: Sequence[str] | None = None,
) -> Iterator[FeatureBin]:
    """Bins with their availability; with `as_of`, only bins ended and final by that cutoff."""
    name = {"hour": "aggregates_hourly.parquet", "day": "aggregates_daily.parquet"}[resolution]
    extra = []
    if as_of is not None:
        cutoff = _utc(as_of)
        extra += [ds.field("interval_end_utc") <= cutoff, ds.field("available_at_utc") <= cutoff]
    dataset = ds.dataset(snapshot / name, format="parquet")
    expression = _filter(subjects=subjects, metrics=metrics, extra=extra)
    for batch in dataset.to_batches(filter=expression, batch_size=VALIDATION_BATCH):
        for row in batch.to_pylist():
            available = row.pop("available_at_utc")
            yield FeatureBin(Aggregate.model_validate(row), available)


def read_wellness(
    snapshot: Path, subjects: Sequence[str] | None = None
) -> list[wellness.WellnessDay]:
    table = pq.read_table(snapshot / "wellness_daily.parquet")
    if subjects is not None:
        table = table.filter(pc.field("subject_id").isin(list(subjects)))
    return [wellness.WellnessDay.model_validate(r) for r in table.to_pylist()]


def read_outcomes(snapshot: Path) -> list[StatusUnknown]:
    return [
        StatusUnknown.model_validate(r)
        for r in pq.read_table(snapshot / "outcomes.parquet").to_pylist()
    ]


# Verifying -------------------------------------------------------------------------------


def verify(
    snapshot: Path,
    *,
    full: bool = False,
    archive_path: Path | None = None,
    admission: Admission | None = None,
) -> dict[str, Any]:
    """Check checksums, manifest identity and counts; `full` re-validates every row."""
    problems: list[str] = []
    sums_path = snapshot / "SHA256SUMS"
    listed = {}
    for line in sums_path.read_text().splitlines():
        digest, name = line.split("  ", 1)
        listed[name] = digest
    present = set(os.listdir(snapshot)) - {"SHA256SUMS"}
    if set(listed) != present:
        problems.append(f"files differ from SHA256SUMS: {sorted(set(listed) ^ present)}")
    for name, digest in sorted(listed.items()):
        if (snapshot / name).is_file() and sha256_file(snapshot / name) != digest:
            problems.append(f"{name}: checksum mismatch")
    manifest = load_manifest(snapshot)
    for name, entry in manifest["tables"].items():
        if sha256_file(snapshot / name) != entry["sha256"]:
            problems.append(f"{name}: differs from the manifest")
            continue
        if pq.read_metadata(snapshot / name).num_rows != entry["rows"]:
            problems.append(f"{name}: row count differs from the manifest")
    if sha256_file(snapshot / "audit.json") != manifest["audit_sha256"]:
        problems.append("audit.json differs from the manifest")
    digest = snapshot_hash(manifest)
    if digest != manifest["dataset_snapshot"]["snapshot_sha256"]:
        problems.append("snapshot hash does not match its manifest")
    if not snapshot.name.endswith(digest[:12]) or snapshot.name != manifest["snapshot_id"]:
        problems.append("directory name does not match the snapshot id")
    checked: dict[str, Any] = {"files": len(listed)}
    if archive_path is not None:
        if admission is None:
            raise ValueError("verifying against the archive needs its admission")
        with open_archive(archive_path, admission) as archive:
            for name, entry in manifest["source"]["members"]["read"].items():
                member = next(m for m in archive.members if m.name == name)
                with archive.open(member):
                    pass
                if archive.digests[name].sha256 != entry["sha256"]:
                    problems.append(f"{name}: archive member differs from the manifest")
        checked["archive_members"] = len(manifest["source"]["members"]["read"])
    if full and not problems:
        checked["validated_rows"] = _validate_all(snapshot, problems)
    return {
        "snapshot_id": manifest["snapshot_id"],
        "ok": not problems,
        "problems": problems,
        "checked": checked,
    }


def _validate_all(snapshot: Path, problems: list[str]) -> dict[str, int]:
    counts = {}
    # Rows are grouped by subject, so only the current subject's ids need holding.
    finished: set[str] = set()
    subject, ids = None, set()
    n = 0
    for observation in iter_observations(snapshot):
        if observation.subject_id != subject:
            if observation.subject_id in finished:
                problems.append("observations are not grouped by subject")
            if subject is not None:
                finished.add(subject)
            subject, ids = observation.subject_id, set()
        if observation.record_id in ids:
            problems.append(f"duplicate record_id {observation.record_id}")
        ids.add(observation.record_id)
        n += 1
    counts["observations.parquet"] = n
    for resolution, name in (
        ("hour", "aggregates_hourly.parquet"),
        ("day", "aggregates_daily.parquet"),
    ):
        keys = set()
        n = 0
        for aggregate, available in iter_aggregates(snapshot, resolution):
            if available < aggregate.interval_end_utc:
                problems.append(f"{name}: available before its bin ends")
            key = (
                aggregate.subject_id,
                aggregate.metric,
                aggregate.aggregation,
                aggregate.interval_start_utc,
            )
            if key in keys:
                problems.append(f"{name}: duplicate bin {key}")
            keys.add(key)
            n += 1
        counts[name] = n
    counts["wellness_daily.parquet"] = len(read_wellness(snapshot))
    counts["outcomes.parquet"] = len(read_outcomes(snapshot))
    return counts
