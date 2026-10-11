"""What each endpoint does, independent of HTTP: imports, coverage, reports, self-reports,
scenarios, deletion and health. Jobs are persisted before they are queued.
"""

import hashlib
import logging
import os
import secrets
import tempfile
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field

from hachi.contracts.api import (
    Coverage,
    FieldIssue,
    HealthStatus,
    ImportFailure,
    ImportStatus,
    ReportJob,
    SelfReportHistory,
)
from hachi.contracts.base import (
    SCHEMA_VERSION,
    Contract,
    DataMode,
    DatasetSnapshotRef,
    IanaTimezone,
    SubjectId,
    UtcDatetime,
)
from hachi.contracts.requests import (
    ReportRequest,
    ScenarioRequest,
    SelfReportRequest,
    SymptomOnsetEntry,
    SymptomResolutionEntry,
)
from hachi.contracts.results import ErrorResult, ReportResult
from hachi.data.apple_health import ImportConfig, ImportProblem, import_export
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.storage import ImportRecord, Metadata, SelfReportRow, private_directory, remove_tree

from . import reports
from .catalog import Catalog
from .coverage import build_coverage
from .errors import ApiProblem
from .jobs import JobRunner
from .reports import Context, now_utc, run_report
from .scenarios import scenario_result
from .settings import Settings

log = logging.getLogger("hachi.api")

IMPORTER_VERSION = "apple-health-import-1"
UPLOAD_SUFFIX = {"apple_health_export_zip": ".zip", "apple_health_export_xml": ".xml"}
# Errors a retry can cure; an identical request after one of these runs again.
TRANSIENT_REPORT_ERRORS = {
    "INTERNAL_ERROR",
    "INFERENCE_TIMEOUT",
    "GPU_UNAVAILABLE",
    "DATA_READ_FAILED",
}
FUTURE_SKEW = timedelta(minutes=5)


class UploadParams(Contract):
    """Query parameters of POST /v1/imports. The body is the export file itself."""

    subject_id: SubjectId
    tz_name: IanaTimezone
    source_format: Literal["apple_health_export_zip", "apple_health_export_xml"] = Field(
        description="PMData is served from operator-approved snapshots, not uploaded."
    )
    data_mode: DataMode


class CoverageParams(Contract):
    as_of: UtcDatetime | None = None


def _dataset_id(data_mode: DataMode) -> str:
    return "apple-health-export" if data_mode == "real" else "synthetic-apple-health-export"


class Service:
    def __init__(self, settings: Settings, metadata: Metadata, catalog: Catalog) -> None:
        self.settings = settings
        self.metadata = metadata
        self.catalog = catalog
        self.workspace = settings.workspace
        self.context = Context(catalog, metadata, settings.workspace, settings.git_sha)
        self.runner = JobRunner({"import": self.run_import, "report": self.run_report})
        # Deletion is serialised against new records for the same subject.
        self._subjects = threading.Lock()
        self._deleting: set[str] = set()

    def start(self) -> None:
        private_directory(self.workspace.state)
        private_directory(self.workspace.imports)
        private_directory(self.workspace.uploads)
        self.recover()
        self.runner.start()

    def stop(self) -> None:
        self.runner.stop()

    # Subjects ---------------------------------------------------------------------------

    def known(self, subject_id: str) -> bool:
        return self.catalog.dataset_for(subject_id) is not None or self.metadata.subject_known(
            subject_id
        )

    @contextmanager
    def _writing(self, subject_id: str) -> Iterator[None]:
        """Hold off deletion while a new record for this subject is written."""
        with self._subjects:
            if subject_id in self._deleting:
                raise ApiProblem(
                    "CONFLICT", "This subject is being deleted; try again after it finishes."
                )
            yield

    def _require_known(self, subject_id: str) -> None:
        if not self.known(subject_id):
            raise ApiProblem("NOT_FOUND", "No data or records exist for this subject.")

    # Imports ----------------------------------------------------------------------------

    async def receive_import(
        self, params: UploadParams, declared_length: int | None, chunks: AsyncIterator[bytes]
    ) -> tuple[ImportStatus, bool]:
        """Stream the upload to a private file, then reuse an identical import or queue one."""
        if self.catalog.dataset_for(params.subject_id) is not None:
            raise ApiProblem(
                "CONFLICT", "This subject id belongs to a served dataset; choose another."
            )
        limit = self.settings.import_limits.upload_bytes
        if declared_length is not None and declared_length > limit:
            raise ApiProblem("PAYLOAD_TOO_LARGE", "The export exceeds the upload limit.")
        descriptor, name = tempfile.mkstemp(prefix=".upload-", dir=self.workspace.uploads)
        temporary = Path(name)
        try:
            digest, size = hashlib.sha256(), 0
            with os.fdopen(descriptor, "wb") as output:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > limit:
                        raise ApiProblem(
                            "PAYLOAD_TOO_LARGE", "The export exceeds the upload limit."
                        )
                    digest.update(chunk)
                    output.write(chunk)
            if size == 0:
                raise ApiProblem("VALIDATION_FAILED", "The upload is empty.")
            upload_sha256 = digest.hexdigest()
            key = document_sha256(
                {"upload_sha256": upload_sha256, "params": params, "importer": IMPORTER_VERSION}
            )
            import_id = "imp-" + secrets.token_hex(12)
            # Reuse and creation share the deletion guard: a subject being deleted can
            # neither gain an import nor hand back one that is about to disappear.
            with self._writing(params.subject_id):
                for record in self.metadata.imports_with_key(key):
                    if _reusable_import(record):
                        return record.status, False
                directory = private_directory(self.workspace.import_directory(import_id))
                try:
                    os.replace(
                        temporary, directory / ("upload" + UPLOAD_SUFFIX[params.source_format])
                    )
                    status = self._insert_import(key, upload_sha256, import_id, params)
                except BaseException:
                    remove_tree(directory)  # no record names it, so it must not outlive us
                    raise
        finally:
            temporary.unlink(missing_ok=True)
        self.runner.submit("import", import_id)
        return status, True

    def _insert_import(
        self, key: str, upload_sha256: str, import_id: str, params: UploadParams
    ) -> ImportStatus:
        now = now_utc()
        status = ImportStatus(
            schema_version=SCHEMA_VERSION,
            import_id=import_id,
            subject_id=params.subject_id,
            data_mode=params.data_mode,
            source_format=params.source_format,
            declared_tz_name=params.tz_name,
            state="pending",
            created_at_utc=now,
            updated_at_utc=now,
            counts=None,
            record_issues=[],
            failure=None,
        )
        self.metadata.insert_import(key, upload_sha256, status)
        return status

    def get_import(self, import_id: str) -> ImportStatus:
        record = self.metadata.get_import(import_id)
        if record is None:
            raise ApiProblem("NOT_FOUND", "No such import.")
        return record.status

    def _upload_path(self, record: ImportRecord) -> Path:
        directory = self.workspace.import_directory(record.import_id)
        return directory / ("upload" + UPLOAD_SUFFIX[record.status.source_format])

    def run_import(self, import_id: str) -> None:
        record = self.metadata.get_import(import_id)
        if record is None or record.status.state != "pending":
            return
        status = record.status
        self.metadata.update_import(_updated(status, state="running", updated_at_utc=now_utc()))
        upload = self._upload_path(record)
        config = ImportConfig(
            dataset_id=_dataset_id(status.data_mode),
            subject_id=status.subject_id,
            declared_tz_name=status.declared_tz_name,
            data_mode=status.data_mode,
        )
        database = self.workspace.import_directory(import_id) / "snapshot.sqlite3"
        try:
            audit = import_export(upload, config, database, limits=self.settings.import_limits)
        except ImportProblem as exc:
            self._fail_import(status, exc.failure)
            return
        except Exception as exc:
            log.error("import %s failed (%s)", import_id, type(exc).__name__)
            database.unlink(missing_ok=True)
            self._fail_import(
                status,
                ImportFailure(
                    error_code="INTERNAL_ERROR",
                    message="The import failed unexpectedly.",
                    action="Try the upload again; if it fails again, report the import id.",
                ),
            )
            return
        finally:
            upload.unlink(missing_ok=True)  # the private snapshot keeps the raw records
        snapshot = DatasetSnapshotRef(
            dataset_id=config.dataset_id,
            dataset_version=IMPORTER_VERSION,
            snapshot_sha256=document_sha256(
                {"xml_sha256": audit.xml_sha256, "config": config, "importer": IMPORTER_VERSION}
            ),
        )
        summary = {  # aggregate counts and spans only
            "metric_counts": audit.metric_counts,
            "metric_spans_utc": audit.metric_spans_utc,
            "missing_metrics": audit.missing_metrics,
            "source_kind_counts": audit.source_kind_counts,
            "xml_bytes": audit.xml_bytes,
        }
        self.metadata.update_import(
            _updated(
                status,
                state="succeeded",
                updated_at_utc=now_utc(),
                counts=audit.counts,
                record_issues=list(audit.issues),
            ),
            snapshot=snapshot,
            summary_json=document_bytes(summary).decode(),
        )

    def _fail_import(self, status: ImportStatus, failure: ImportFailure) -> None:
        self.metadata.update_import(
            _updated(
                status,
                state="failed",
                updated_at_utc=now_utc(),
                counts=None,
                record_issues=[],
                failure=failure,
            )
        )

    def recover(self) -> None:
        """After a restart: interrupted imports fail cleanly; queued work runs again."""
        for record in self.metadata.imports_in_states("running"):
            remove_tree(self.workspace.import_directory(record.import_id))
            self._fail_import(
                record.status,
                ImportFailure(
                    error_code="INTERNAL_ERROR",
                    message="The import was interrupted before it finished.",
                    action="Upload the export again.",
                ),
            )
        for record in self.metadata.imports_in_states("pending"):
            if self._upload_path(record).is_file():
                self.runner.submit("import", record.import_id)
            else:
                self._fail_import(
                    record.status,
                    ImportFailure(
                        error_code="INTERNAL_ERROR",
                        message="The uploaded file is no longer available.",
                        action="Upload the export again.",
                    ),
                )
        for job in self.metadata.reports_in_states("queued", "running"):
            if job.state == "running":
                self.metadata.update_report(_updated(job, state="queued"))
            self.runner.submit("report", job.report_id)

    # Coverage ---------------------------------------------------------------------------

    def coverage(self, subject_id: str, params: CoverageParams) -> Coverage:
        self._require_known(subject_id)
        subject = self.catalog.subject(subject_id, self.metadata, self.workspace)

        def support(observed, sufficient):
            return reports.task_support(self.catalog, subject, observed, sufficient)

        if subject is None:  # only failed, pending or no imports: an empty history
            records = self.metadata.subject_imports(subject_id)
            latest = records[-1].status if records else None
            return build_coverage(
                subject_id=subject_id,
                data_mode=latest.data_mode if latest else reports.fallback_data_mode(subject_id),
                snapshot=None,
                tz_name=latest.declared_tz_name if latest else "UTC",
                presence=(),
                task_support=support,
                generated_at=now_utc(),
            )
        return build_coverage(
            subject_id=subject_id,
            data_mode=subject.data_mode,
            snapshot=subject.snapshot,
            tz_name=subject.tz_name,
            presence=subject.presence(params.as_of),
            task_support=support,
            generated_at=now_utc(),
        )

    # Reports ----------------------------------------------------------------------------

    def submit_report(self, request: ReportRequest) -> tuple[ReportJob, bool]:
        body = request.root
        if body.as_of > now_utc() + FUTURE_SKEW:
            raise ApiProblem(
                "VALIDATION_FAILED",
                "as_of cannot be in the future.",
                issues=[FieldIssue(path="body.as_of", message="must not be in the future")],
            )
        self._require_known(body.subject_id)
        subject = self.catalog.subject(body.subject_id, self.metadata, self.workspace)
        artifact = reports.select_artifact(request, self.catalog, subject)
        digest = None
        if body.task in ("illness_onset", "recovery"):
            entries = reports.self_report_entries(self.metadata, body.subject_id)
            digest = reports.self_report_digest(entries, body.as_of)
        key = reports.report_key(request, subject, artifact, self.settings.git_sha, digest)
        for job in self.metadata.reports_with_key(key):
            if _reusable_report(job):
                return job, False
        now = now_utc()
        job = ReportJob(
            schema_version=SCHEMA_VERSION,
            report_id="rep-" + secrets.token_hex(12),
            state="queued",
            submitted_at_utc=now,
            updated_at_utc=now,
            request=request,
            result=None,
        )
        with self._writing(body.subject_id):
            self.metadata.insert_report(key, job)
        self.runner.submit("report", job.report_id)
        return job, True

    def get_report(self, report_id: str) -> ReportJob:
        job = self.metadata.get_report(report_id)
        if job is None:
            raise ApiProblem("NOT_FOUND", "No such report.")
        return job

    def run_report(self, report_id: str) -> None:
        job = self.metadata.get_report(report_id)
        if job is None or job.state == "completed":
            return
        self.metadata.update_report(_updated(job, state="running", updated_at_utc=now_utc()))
        try:
            result = run_report(self.context, report_id, job.request)
        except Exception as exc:
            log.error("report %s failed (%s)", report_id, type(exc).__name__)
            data_mode = reports.fallback_data_mode(job.request.root.subject_id)
            result = reports._Base(report_id, job.request, data_mode, self.settings.git_sha).error(
                "INTERNAL_ERROR", "The report could not be produced."
            )
        self.metadata.update_report(
            ReportJob(
                schema_version=SCHEMA_VERSION,
                report_id=report_id,
                state="completed",
                submitted_at_utc=job.submitted_at_utc,
                updated_at_utc=now_utc(),
                request=job.request,
                result=result,
            )
        )

    # Self-reports -----------------------------------------------------------------------

    def add_self_reports(
        self, subject_id: str, request: SelfReportRequest
    ) -> tuple[SelfReportRequest, bool]:
        """Append entries; an identical resubmission is a no-op, a changed one a conflict."""
        stored = {row.entry_id: row for row in self.metadata.self_reports(subject_id)}
        onsets = {r.entry_id for r in stored.values() if r.kind == "symptom_onset"}
        onsets |= {e.entry_id for e in request.entries if isinstance(e, SymptomOnsetEntry)}
        issues, rows = [], []
        for index, entry in enumerate(request.entries):
            document = entry.model_dump_json()
            previous = stored.get(entry.entry_id)
            if previous is not None and previous.entry_json != document:
                issues.append(
                    FieldIssue(
                        path=f"body.entries.{index}.entry_id",
                        message="an entry with this id was already recorded differently",
                    )
                )
            if isinstance(entry, SymptomResolutionEntry) and entry.onset_entry_id not in onsets:
                raise ApiProblem(
                    "VALIDATION_FAILED",
                    "A resolution must refer to a recorded symptom onset.",
                    issues=[
                        FieldIssue(
                            path=f"body.entries.{index}.onset_entry_id",
                            message="no symptom_onset entry with this id",
                        )
                    ],
                )
            if previous is None:
                rows.append(SelfReportRow(entry.entry_id, entry.kind, document))
        if issues:
            raise ApiProblem(
                "CONFLICT", "Recorded entries are immutable; use a new entry_id.", issues=issues
            )
        if rows:
            with self._writing(subject_id):
                self.metadata.insert_self_reports(subject_id, rows)
        return request, bool(rows)

    def self_report_history(self, subject_id: str) -> SelfReportHistory:
        self._require_known(subject_id)
        return SelfReportHistory(
            schema_version=SCHEMA_VERSION,
            subject_id=subject_id,
            entries=reports.self_report_entries(self.metadata, subject_id),
        )

    # Scenarios --------------------------------------------------------------------------

    def scenario(self, request: ScenarioRequest) -> ReportResult:
        subject = self.catalog.subject(request.subject_id, self.metadata, self.workspace)
        data_mode: DataMode = (
            subject.data_mode if subject else reports.fallback_data_mode(request.subject_id)
        )
        return scenario_result(request, data_mode, self.settings.git_sha)

    # Deletion ---------------------------------------------------------------------------

    def delete_subject(self, subject_id: str, confirm: str | None) -> None:
        """Delete the subject's imports, private snapshots, reports and self-reports.

        Served dataset snapshots are immutable shared research data and are not altered;
        only the API's records about a dataset subject are removed.
        """
        if confirm != subject_id:
            raise ApiProblem(
                "VALIDATION_FAILED",
                "Confirm deletion by repeating the subject id.",
                issues=[FieldIssue(path="confirm", message="must equal the subject id")],
            )
        self._require_known(subject_id)
        with self._subjects:
            if subject_id in self._deleting:
                raise ApiProblem("CONFLICT", "This subject is already being deleted.")
            imports = self.metadata.subject_imports(subject_id)
            busy = any(r.status.state in ("pending", "running") for r in imports) or any(
                j.state != "completed" for j in self.metadata.subject_reports(subject_id)
            )
            if busy:
                raise ApiProblem(
                    "CONFLICT", "Jobs for this subject are still running; delete after they finish."
                )
            self._deleting.add(subject_id)
        try:
            # Private files go first and the records last: if a removal fails, the records
            # still name every import, so the same deletion can simply be retried.
            try:
                for record in imports:
                    remove_tree(self.workspace.import_directory(record.import_id))
            except OSError as exc:
                log.error("delete: private files not removed (%s)", type(exc).__name__)
                raise ApiProblem(
                    "INTERNAL_ERROR",
                    "Some private files could not be removed, so no records were deleted. "
                    "Retry the deletion.",
                ) from exc
            self.metadata.delete_subject(subject_id)
        finally:
            with self._subjects:
                self._deleting.discard(subject_id)

    # Health -----------------------------------------------------------------------------

    def health(self) -> HealthStatus:
        healthy = not self.catalog.problems and self.metadata.check()
        return HealthStatus(
            schema_version=SCHEMA_VERSION,
            status="ok" if healthy else "degraded",
            git_sha=self.settings.git_sha,
            artifacts=[a.ref for a in self.catalog.artifacts],
        )


def _updated[T: ImportStatus | ReportJob](document: T, **changes) -> T:
    """A changed copy, revalidated so every contract invariant still holds."""
    return type(document).model_validate_json(document.model_copy(update=changes).model_dump_json())


def _reusable_import(record: ImportRecord) -> bool:
    failure = record.status.failure
    return failure is None or failure.error_code != "INTERNAL_ERROR"


def _reusable_report(job: ReportJob) -> bool:
    result = job.result.root if job.result is not None else None
    return not (isinstance(result, ErrorResult) and result.error_code in TRANSIENT_REPORT_ERRORS)
