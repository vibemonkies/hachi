"""Stream Apple exports to a fresh private SQLite snapshot and reconcile counts."""

import hashlib
import json
import os
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from xml.parsers import expat

from pydantic import Field

from hachi.contracts.api import ImportCounts, RecordIssueSummary
from hachi.contracts.base import Contract, DataMode, IanaTimezone, Identifier, SubjectId
from hachi.contracts.metrics import METRICS

from .normalization import RecordIssue, normalize_record
from .security import ImportLimits, ImportProblem, export_stream, too_large
from .store import initialize, select_candidates, timestamp_us

DEFAULT_LIMITS = ImportLimits()


class ImportConfig(Contract):
    dataset_id: Identifier
    subject_id: SubjectId
    declared_tz_name: IanaTimezone
    data_mode: DataMode
    source_priority: tuple[str, ...] = Field(default=(), max_length=256)


@dataclass(frozen=True)
class ImportAudit:
    data_mode: DataMode
    counts: ImportCounts
    issues: tuple[RecordIssueSummary, ...]
    metric_counts: dict[str, int]
    metric_spans_utc: dict[str, tuple[str, str]]
    missing_metrics: tuple[str, ...]
    source_kind_counts: dict[str, int]
    xml_sha256: str
    xml_bytes: int
    declared_tz_name: str


def _malformed() -> ImportProblem:
    return ImportProblem(
        "MALFORMED_XML",
        "The XML is malformed or exceeds safe parsing limits.",
        "Export again from Apple Health; remove external resources and entity declarations.",
    )


class _Records:
    def __init__(self, connection: sqlite3.Connection, config: ImportConfig) -> None:
        self.connection = connection
        self.config = config
        self.seen = 0

    def add(self, attrs: dict[str, str]) -> None:
        self.seen += 1
        bucket, issue = "candidate", None
        try:
            observation = normalize_record(
                attrs, dataset_id=self.config.dataset_id, subject_id=self.config.subject_id
            )
        except RecordIssue as exc:
            observation = None
            bucket, issue = exc.disposition, exc.code
        if observation is None and issue is None:
            bucket = "unsupported"
        if (
            observation is not None
            and self.connection.execute(
                "SELECT 1 FROM candidates WHERE record_id=?", (observation.record_id,)
            ).fetchone()
        ):
            bucket = "duplicate"
        self.connection.execute(
            "INSERT INTO records VALUES (?, ?, ?, ?)",
            (self.seen, json.dumps(attrs, sort_keys=True), bucket, issue),
        )
        if bucket == "candidate":
            metric = observation.metric
            asleep = metric.startswith("sleep_asleep_")
            stage_priority = 1 if metric == "sleep_asleep_unspecified" else 0
            priority_names = self.config.source_priority
            name = attrs["sourceName"]
            kind_order = ("watch", "phone", "third_party_app", "unknown")
            priority = (
                priority_names.index(name)
                if name in priority_names
                else len(priority_names) + kind_order.index(observation.source_kind)
            )
            self.connection.execute(
                "INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.seen,
                    observation.record_id,
                    "sleep_asleep" if asleep else metric,
                    stage_priority,
                    priority,
                    timestamp_us(observation.start_utc),
                    timestamp_us(observation.end_utc),
                    timestamp_us(observation.available_at_utc),
                    observation.model_dump_json(),
                ),
            )


def _parse(stream, records: _Records, limits: ImportLimits) -> tuple[str, int]:
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.specified_attributes = True
    depth = 0
    names: set[str] = set()
    current: dict[str, str] | None = None
    record_bytes = 0
    declarations = 0

    def forbid(*_args):
        raise _malformed()

    def doctype(name, system, public, _internal):
        if name != "HealthData" or system is not None or public is not None:
            raise _malformed()

    def declaration(*_args):
        nonlocal declarations
        declarations += 1
        if declarations > limits.xml_names * 4:
            raise _malformed()

    def start(name: str, attrs: dict[str, str]):
        nonlocal depth, current, record_bytes
        depth += 1
        names.add(name)
        names.update(attrs)
        if depth > limits.depth or len(names) > limits.xml_names or len(attrs) > 64:
            raise _malformed()
        if depth == 1 and name != "HealthData":
            raise ImportProblem(
                "NOT_AN_APPLE_HEALTH_EXPORT",
                "The XML root is not HealthData.",
                "Choose the Apple Health export.xml file.",
            )
        if name == "Record":
            if depth != 2 or current is not None:
                raise _malformed()
            if records.seen >= limits.records:
                raise too_large()
            current = dict(attrs)
            record_bytes = len(json.dumps(attrs).encode())
            if record_bytes > limits.record_bytes:
                raise _malformed()
        elif current is not None:
            record_bytes += len(json.dumps(attrs).encode())
            if record_bytes > limits.record_bytes:
                raise _malformed()
            if name == "MetadataEntry" and "key" in attrs and "value" in attrs:
                current["metadata:" + attrs["key"]] = attrs["value"]

    def end(name: str):
        nonlocal depth, current
        if name == "Record":
            if current is None:
                raise _malformed()
            records.add(current)
            current = None
        depth -= 1

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = doctype
    parser.EntityDeclHandler = forbid
    parser.ExternalEntityRefHandler = forbid
    parser.UnparsedEntityDeclHandler = forbid
    parser.ElementDeclHandler = declaration
    parser.AttlistDeclHandler = declaration
    digest = hashlib.sha256()
    total = 0
    try:
        while chunk := stream.read(min(16 * 1024, limits.token_bytes)):
            total += len(chunk)
            if total > limits.xml_bytes:
                raise too_large()
            digest.update(chunk)
            parser.Parse(chunk, False)
            # Expat retains an incomplete token. Reparse deferral stays enabled;
            # this check bounds its buffer even for a huge unfinished attribute.
            if total - parser.CurrentByteIndex > limits.token_bytes:
                raise _malformed()
            parser.intern.clear()
        parser.Parse(b"", True)
    except expat.ExpatError as exc:
        raise _malformed() from exc
    return digest.hexdigest(), total


def import_export(
    path: Path, config: ImportConfig, database: Path, *, limits: ImportLimits = DEFAULT_LIMITS
) -> ImportAudit:
    """The caller owns the private output directory; existing snapshots are never overwritten."""
    database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if database.parent.stat().st_mode & 0o077:
        raise ValueError("output directory must be private (mode 0700)")
    descriptor = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    connection = sqlite3.connect(database)
    try:
        initialize(connection)
        records = _Records(connection, config)
        with export_stream(path, limits) as stream:
            digest, size = _parse(stream, records, limits)
        metric_counts: Counter[str] = Counter()
        metric_spans: dict[str, tuple[str, str]] = {}
        source_counts: Counter[str] = Counter()
        connection.execute("UPDATE records SET bucket='duplicate' WHERE bucket='candidate'")
        for row_id, observation in select_candidates(connection):
            connection.execute("UPDATE records SET bucket='accepted' WHERE row_id=?", (row_id,))
            metric_counts[observation.metric] += 1
            start, end = observation.start_utc.isoformat(), observation.end_utc.isoformat()
            previous = metric_spans.get(observation.metric, (start, end))
            metric_spans[observation.metric] = min(start, previous[0]), max(end, previous[1])
            source_counts[observation.source_kind] += 1
        buckets = dict(connection.execute("SELECT bucket, COUNT(*) FROM records GROUP BY bucket"))
        counts = ImportCounts(
            records_seen=records.seen,
            records_accepted=buckets.get("accepted", 0),
            records_duplicate=buckets.get("duplicate", 0),
            records_unsupported=buckets.get("unsupported", 0),
            records_rejected=buckets.get("rejected", 0),
            records_quarantined=buckets.get("quarantined", 0),
        )
        if counts.bucket_total() != counts.records_seen:
            raise RuntimeError("import count reconciliation failed")
        issues = tuple(
            RecordIssueSummary(disposition=bucket, code=code, count=count)
            for bucket, code, count in connection.execute(
                "SELECT bucket, issue, COUNT(*) FROM records WHERE issue IS NOT NULL "
                "GROUP BY bucket, issue ORDER BY bucket, issue"
            )
        )
        audit = ImportAudit(
            config.data_mode,
            counts,
            issues,
            dict(metric_counts),
            metric_spans,
            tuple(sorted(set(METRICS) - metric_counts.keys())),
            dict(source_counts),
            digest,
            size,
            config.declared_tz_name,
        )
        connection.execute("INSERT INTO metadata VALUES ('config', ?)", (config.model_dump_json(),))
        connection.execute("INSERT INTO metadata VALUES ('xml_sha256', ?)", (digest,))
        connection.execute("INSERT INTO metadata VALUES ('completed', 'true')")
        connection.commit()
        return audit
    except BaseException:
        connection.close()
        # Only this invocation's O_EXCL-created snapshot is removed on failure.
        database.unlink(missing_ok=True)
        raise
    finally:
        connection.close()
