"""Disk staging and cutoff-aware deduplication; raw provenance stays private."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from hachi.contracts.tables import Observation

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def timestamp_us(value: datetime) -> int:
    delta = value - EPOCH
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        PRAGMA cache_size=-4096;
        PRAGMA temp_store=FILE;
        CREATE TABLE records (
            row_id INTEGER PRIMARY KEY, raw_json TEXT NOT NULL,
            bucket TEXT NOT NULL, issue TEXT
        );
        CREATE TABLE candidates (
            row_id INTEGER PRIMARY KEY REFERENCES records(row_id),
            record_id TEXT UNIQUE NOT NULL, family TEXT NOT NULL,
            stage_priority INTEGER NOT NULL, source_priority INTEGER NOT NULL,
            start_us INTEGER NOT NULL, end_us INTEGER NOT NULL, available_us INTEGER NOT NULL,
            observation_json TEXT NOT NULL
        );
        CREATE INDEX candidate_order ON candidates
            (stage_priority, source_priority, start_us, available_us DESC, record_id);
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)


def select_candidates(
    connection: sqlite3.Connection, as_of: datetime | None = None
) -> Iterator[tuple[int, Observation]]:
    connection.executescript("""
        DROP TABLE IF EXISTS temp.kept;
        DROP TABLE IF EXISTS temp.kept_ranges;
        CREATE TEMP TABLE kept (
            id INTEGER PRIMARY KEY, family TEXT, start_us INTEGER, end_us INTEGER
        );
        CREATE VIRTUAL TABLE temp.kept_ranges USING rtree(id, min_start, max_end);
    """)
    cutoff = timestamp_us(as_of) if as_of is not None else None
    cursor = connection.execute(
        """SELECT row_id, family, start_us, end_us, observation_json FROM candidates
           WHERE (? IS NULL OR (end_us <= ? AND available_us <= ?))
           ORDER BY stage_priority, source_priority, start_us, available_us DESC, record_id""",
        (cutoff, cutoff, cutoff),
    )
    for row_id, family, start, end, payload in cursor:
        overlap = connection.execute(
            """SELECT 1 FROM kept_ranges bounds JOIN kept ON kept.id=bounds.id
               WHERE bounds.min_start<=:end AND bounds.max_end>=:start AND family=:family AND (
                (start_us < :end AND end_us > :start)
                OR (start_us=end_us AND start_us>=:start AND start_us<:end)
                OR (:start=:end AND start_us<=:start AND end_us>:start)
                OR (start_us=end_us AND start_us=:start AND :start=:end)
            ) LIMIT 1""",
            {"family": family, "start": start, "end": end},
        ).fetchone()
        if overlap is None:
            connection.execute("INSERT INTO kept VALUES (?, ?, ?, ?)", (row_id, family, start, end))
            # RTree bounds round outward; exact integer interval checks above
            # prevent false overlap decisions while avoiding quadratic scans.
            connection.execute("INSERT INTO kept_ranges VALUES (?, ?, ?)", (row_id, start, end))
            yield row_id, Observation.model_validate_json(payload)


def iter_observations(path: Path, *, as_of: datetime | None = None) -> Iterator[Observation]:
    """Reapply precedence AFTER availability filtering so future edits cannot win early."""
    if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
        raise ValueError("as_of requires an aware instant")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA cache_size=-4096")
        connection.execute("PRAGMA temp_store=FILE")
        completed = connection.execute(
            "SELECT value FROM metadata WHERE key='completed'"
        ).fetchone()
        if completed != ("true",):
            raise ValueError("import has not completed")
        for _, observation in select_candidates(connection, as_of):
            yield observation
