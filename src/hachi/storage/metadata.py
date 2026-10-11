"""Owner-isolated SQLite metadata: imports, report jobs and self-reports.

Each developer runs their own database (docs/DEVELOPMENT.md). Documents are stored as the
contract JSON they are served as; indexed columns duplicate only what queries need. Raw
records and observations never enter this database: they stay in each import's private
snapshot or in the approved dataset snapshot.
"""

import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from hachi.contracts.api import ImportStatus, ReportJob
from hachi.contracts.base import DatasetSnapshotRef

_MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE imports (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        import_id TEXT NOT NULL UNIQUE,
        subject_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        upload_sha256 TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('pending', 'running', 'succeeded', 'failed')),
        status_json TEXT NOT NULL,
        snapshot_json TEXT,
        summary_json TEXT
    );
    CREATE INDEX imports_subject ON imports (subject_id, seq);
    CREATE INDEX imports_key ON imports (idempotency_key, seq);
    CREATE TABLE report_jobs (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id TEXT NOT NULL UNIQUE,
        subject_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'completed')),
        job_json TEXT NOT NULL
    );
    CREATE INDEX report_jobs_subject ON report_jobs (subject_id, seq);
    CREATE INDEX report_jobs_key ON report_jobs (idempotency_key, seq);
    CREATE TABLE self_reports (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id TEXT NOT NULL,
        entry_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        entry_json TEXT NOT NULL,
        UNIQUE (subject_id, entry_id)
    );
    """,
)


@dataclass(frozen=True)
class ImportRecord:
    import_id: str
    subject_id: str
    idempotency_key: str
    upload_sha256: str
    status: ImportStatus
    snapshot: DatasetSnapshotRef | None
    summary_json: str | None


@dataclass(frozen=True)
class SelfReportRow:
    entry_id: str
    kind: str
    entry_json: str


class Metadata:
    """One connection guarded by a lock; the API's request and job threads share it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        # Personal documents must not survive deletion in SQLite free pages.
        self._connection.execute("PRAGMA secure_delete=ON")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _migrate(self) -> None:
        with self._lock:
            (version,) = self._connection.execute("PRAGMA user_version").fetchone()
            if version > len(_MIGRATIONS):
                raise RuntimeError("metadata database is newer than this code")
            for number, script in enumerate(_MIGRATIONS[version:], start=version + 1):
                with self.transaction() as db:
                    for statement in filter(str.strip, script.split(";")):
                        db.execute(statement)
                    db.execute(f"PRAGMA user_version={number}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise
            self._connection.execute("COMMIT")

    def _rows(self, sql: str, parameters: Iterable = ()) -> list[tuple]:
        with self._lock:
            return self._connection.execute(sql, tuple(parameters)).fetchall()

    def check(self) -> bool:
        try:
            return self._rows("PRAGMA quick_check") == [("ok",)]
        except sqlite3.Error:
            return False

    # Imports ---------------------------------------------------------------------------

    def insert_import(self, key: str, upload_sha256: str, status: ImportStatus) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO imports (import_id, subject_id, idempotency_key, upload_sha256, "
                "state, status_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    status.import_id,
                    status.subject_id,
                    key,
                    upload_sha256,
                    status.state,
                    status.model_dump_json(),
                ),
            )

    def update_import(
        self,
        status: ImportStatus,
        *,
        snapshot: DatasetSnapshotRef | None = None,
        summary_json: str | None = None,
    ) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE imports SET state=?, status_json=?, snapshot_json=?, summary_json=? "
                "WHERE import_id=?",
                (
                    status.state,
                    status.model_dump_json(),
                    snapshot.model_dump_json() if snapshot else None,
                    summary_json,
                    status.import_id,
                ),
            )

    _IMPORT_COLUMNS = (
        "import_id, subject_id, idempotency_key, upload_sha256, status_json, snapshot_json, "
        "summary_json"
    )

    @staticmethod
    def _import(row: tuple) -> ImportRecord:
        import_id, subject_id, key, upload, status, snapshot, summary = row
        return ImportRecord(
            import_id,
            subject_id,
            key,
            upload,
            ImportStatus.model_validate_json(status),
            DatasetSnapshotRef.model_validate_json(snapshot) if snapshot else None,
            summary,
        )

    def get_import(self, import_id: str) -> ImportRecord | None:
        rows = self._rows(
            f"SELECT {self._IMPORT_COLUMNS} FROM imports WHERE import_id=?", (import_id,)
        )
        return self._import(rows[0]) if rows else None

    def imports_with_key(self, key: str) -> list[ImportRecord]:
        rows = self._rows(
            f"SELECT {self._IMPORT_COLUMNS} FROM imports WHERE idempotency_key=? ORDER BY seq DESC",
            (key,),
        )
        return [self._import(r) for r in rows]

    def imports_in_states(self, *states: str) -> list[ImportRecord]:
        marks = ",".join("?" * len(states))
        rows = self._rows(
            f"SELECT {self._IMPORT_COLUMNS} FROM imports WHERE state IN ({marks}) ORDER BY seq",
            states,
        )
        return [self._import(r) for r in rows]

    def subject_imports(self, subject_id: str) -> list[ImportRecord]:
        rows = self._rows(
            f"SELECT {self._IMPORT_COLUMNS} FROM imports WHERE subject_id=? ORDER BY seq",
            (subject_id,),
        )
        return [self._import(r) for r in rows]

    def latest_succeeded_import(self, subject_id: str) -> ImportRecord | None:
        rows = self._rows(
            f"SELECT {self._IMPORT_COLUMNS} FROM imports WHERE subject_id=? AND "
            "state='succeeded' ORDER BY seq DESC LIMIT 1",
            (subject_id,),
        )
        return self._import(rows[0]) if rows else None

    # Report jobs -----------------------------------------------------------------------

    def insert_report(self, key: str, job: ReportJob) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO report_jobs (report_id, subject_id, idempotency_key, state, job_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (job.report_id, job.request.root.subject_id, key, job.state, job.model_dump_json()),
            )

    def update_report(self, job: ReportJob) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE report_jobs SET state=?, job_json=? WHERE report_id=?",
                (job.state, job.model_dump_json(), job.report_id),
            )

    def get_report(self, report_id: str) -> ReportJob | None:
        rows = self._rows("SELECT job_json FROM report_jobs WHERE report_id=?", (report_id,))
        return ReportJob.model_validate_json(rows[0][0]) if rows else None

    def reports_with_key(self, key: str) -> list[ReportJob]:
        rows = self._rows(
            "SELECT job_json FROM report_jobs WHERE idempotency_key=? ORDER BY seq DESC", (key,)
        )
        return [ReportJob.model_validate_json(r[0]) for r in rows]

    def reports_in_states(self, *states: str) -> list[ReportJob]:
        marks = ",".join("?" * len(states))
        rows = self._rows(
            f"SELECT job_json FROM report_jobs WHERE state IN ({marks}) ORDER BY seq", states
        )
        return [ReportJob.model_validate_json(r[0]) for r in rows]

    def subject_reports(self, subject_id: str) -> list[ReportJob]:
        rows = self._rows(
            "SELECT job_json FROM report_jobs WHERE subject_id=? ORDER BY seq", (subject_id,)
        )
        return [ReportJob.model_validate_json(r[0]) for r in rows]

    # Self-reports ----------------------------------------------------------------------

    def self_reports(self, subject_id: str) -> list[SelfReportRow]:
        rows = self._rows(
            "SELECT entry_id, kind, entry_json FROM self_reports WHERE subject_id=? ORDER BY seq",
            (subject_id,),
        )
        return [SelfReportRow(*r) for r in rows]

    def insert_self_reports(self, subject_id: str, rows: Iterable[SelfReportRow]) -> None:
        with self.transaction() as db:
            db.executemany(
                "INSERT INTO self_reports (subject_id, entry_id, kind, entry_json) "
                "VALUES (?, ?, ?, ?)",
                [(subject_id, r.entry_id, r.kind, r.entry_json) for r in rows],
            )

    # Subjects --------------------------------------------------------------------------

    def subject_known(self, subject_id: str) -> bool:
        return any(
            self._rows(f"SELECT 1 FROM {table} WHERE subject_id=? LIMIT 1", (subject_id,))
            for table in ("imports", "report_jobs", "self_reports")
        )

    def delete_subject(self, subject_id: str) -> list[str]:
        """Remove every metadata row for the subject; returns the deleted import ids."""
        with self._lock:
            with self.transaction() as db:
                ids = [
                    r[0]
                    for r in db.execute(
                        "SELECT import_id FROM imports WHERE subject_id=?", (subject_id,)
                    ).fetchall()
                ]
                for table in ("imports", "report_jobs", "self_reports"):
                    db.execute(f"DELETE FROM {table} WHERE subject_id=?", (subject_id,))
            # WAL frames contain pre-deletion documents even with secure_delete enabled.
            # This API owns its connection/database; an external reader blocking the
            # checkpoint is an operator error, not successful deletion evidence.
            busy, _, _ = self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if busy:
                raise RuntimeError("personal metadata WAL checkpoint was blocked")
        return ids
