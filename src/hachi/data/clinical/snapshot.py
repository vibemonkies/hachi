"""Build, publish, read and verify immutable outcome-label snapshots (#8).

A snapshot directory holds Parquet tables, a manifest, the audit and SHA256SUMS. Its name ends
with the first 12 hex digits of its snapshot hash, which covers the admitted source files, the
outcome definitions, the dataset settings, every table and the audit. The same code, settings
and sources give a byte-identical directory.
"""

import hashlib
import json
import os
import platform
import stat
import subprocess
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pydantic

from hachi.contracts.base import SCHEMA_VERSION, DatasetSnapshotRef
from hachi.contracts.tables import StatusUnknown, SymptomEpisode, TestResult

from . import audit, tables
from .config import Admission, AdmittedFile, Definitions, Loaded
from .labels import DayRange, SubjectInput, SubjectLabels, label_subject

PARQUET_OPTIONS = {"compression": "zstd", "compression_level": 9, "write_statistics": True}


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


@dataclass(frozen=True)
class LabelSet:
    """Everything a dataset adapter hands the snapshot writer."""

    dataset_id: str
    subjects: list[SubjectInput]
    subject_info: dict[str, dict[str, str]]
    source_counts: Counter
    hr_days: dict[str, set[date]]
    any_days: dict[str, set[date]]
    wearable_rows: list[dict]
    unlabeled_note: str | None
    clock: str
    extra_audit: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_admitted(path: Path, admitted: AdmittedFile) -> None:
    """Refuse a source file whose name, size or SHA-256 differs from the registry."""
    if path.name != admitted.name:
        raise SnapshotError(f"expected {admitted.name}, got {path.name}")
    if path.stat().st_size != admitted.bytes:
        raise SnapshotError(f"{path.name}: size differs from the admitted file")
    if sha256_file(path) != admitted.sha256:
        raise SnapshotError(f"{path.name}: SHA-256 differs from the admitted file")


def _canonical(document: Any) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), default=str).encode()


def _write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True, default=str) + "\n")


def snapshot_hash(manifest: dict[str, Any]) -> str:
    """Hash of everything the snapshot's contents depend on, excluding how it was built."""
    basis = {
        "schema_version": manifest["schema_version"],
        "dataset_id": manifest["dataset_snapshot"]["dataset_id"],
        "dataset_version": manifest["dataset_snapshot"]["dataset_version"],
        "pipeline_version": manifest["pipeline_version"],
        "definitions_sha256": manifest["definitions"]["sha256"],
        "settings_sha256": manifest["settings"]["sha256"],
        "sources": {k: v["sha256"] for k, v in manifest["sources"].items()},
        "tables": {k: v["sha256"] for k, v in manifest["tables"].items()},
        "audit_sha256": manifest["audit_sha256"],
    }
    return hashlib.sha256(_canonical(basis)).hexdigest()


def build(
    label_set: Callable[[], LabelSet],
    *,
    admission: Admission,
    sources_read: Sequence[str],
    definitions: Loaded[Definitions],
    settings: Loaded[Any],
    pipeline_version: str,
    output_root: Path,
    git: GitState,
) -> BuildResult:
    """Build a snapshot into a fresh directory under output_root; never overwrite one."""
    output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".building-", dir=output_root))
    try:
        return _build_into(
            staging,
            label_set(),
            admission,
            sources_read,
            definitions,
            settings,
            pipeline_version,
            output_root,
            git,
        )
    except BaseException:
        _remove_tree(staging)
        raise


def label_all(subjects: Sequence[SubjectInput], defs: Definitions) -> list[SubjectLabels]:
    return [label_subject(s, defs) for s in sorted(subjects, key=lambda s: s.subject_id)]


def _build_into(
    staging: Path,
    label_set: LabelSet,
    admission: Admission,
    sources_read: Sequence[str],
    definitions: Loaded[Definitions],
    settings: Loaded[Any],
    pipeline_version: str,
    output_root: Path,
    git: GitState,
) -> BuildResult:
    defs = definitions.value
    dataset_id = label_set.dataset_id
    if dataset_id != admission.dataset_id:
        raise SnapshotError("label set and admission name different datasets")
    results = label_all(label_set.subjects, defs)
    horizons = defs.onset.horizons_hours
    outcome, episodes, recovery, windows, subjects, status = [], [], [], [], [], []
    for labels in results:
        s = labels.subject_id
        info = label_set.subject_info.get(s)
        hr, anyd = label_set.hr_days.get(s, set()), label_set.any_days.get(s, set())
        outcome += tables.outcome_rows(dataset_id, labels, defs, label_set.unlabeled_note)
        episodes += tables.episode_rows(dataset_id, labels, info or {}, hr, anyd)
        recovery += tables.recovery_rows(dataset_id, labels, defs)
        windows += tables.window_rows(dataset_id, labels, horizons, anyd)
        subjects.append(tables.subject_row(dataset_id, labels, info, anyd))
        status += tables.status_rows(dataset_id, labels, defs)
    surveys = [
        {"subject_id": s.subject_id, "local_date": d, "state": state}
        for s in sorted(label_set.subjects, key=lambda s: s.subject_id)
        for d, state in sorted(s.surveys.items())
    ]
    written = {
        "subjects.parquet": tables.table(subjects, tables.SUBJECT_SCHEMA),
        "status_intervals.parquet": tables.table(status, tables.STATUS_SCHEMA),
        "outcomes.parquet": tables.table(outcome, tables.OUTCOME_SCHEMA),
        "episodes.parquet": tables.table(episodes, tables.EPISODE_SCHEMA),
        "recovery.parquet": tables.table(recovery, tables.RECOVERY_SCHEMA),
        "onset_windows.parquet": tables.table(windows, tables.window_schema(horizons)),
        "surveys.parquet": tables.table(surveys, tables.SURVEY_SCHEMA),
        "wearable_days.parquet": tables.table(label_set.wearable_rows, tables.WEARABLE_SCHEMA),
    }
    for name, t in written.items():
        pq.write_table(t, staging / name, **PARQUET_OPTIONS)

    audit_doc = audit.build_audit(
        dataset_id, results, label_set, written, defs, endpoint_ids=_endpoint_ids(defs)
    )
    _write_json(staging / "audit.json", audit_doc)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": pipeline_version,
        "dataset_snapshot": {
            "dataset_id": dataset_id,
            "dataset_version": admission.dataset_version,
            "snapshot_sha256": "",
        },
        "definitions": {
            "path": "configs/outcomes/definitions.toml",
            "definitions_version": defs.definitions_version,
            "sha256": definitions.sha256,
            "document": defs.model_dump(mode="json"),
        },
        "settings": {
            "path": f"configs/outcomes/{settings.path.name}",
            "sha256": settings.sha256,
            "document": settings.value.model_dump(mode="json"),
        },
        "sources": {
            name: admission.files[name].model_dump(mode="json") for name in sorted(sources_read)
        },
        "clock": label_set.clock,
        "availability_rules": {
            tables.SURVEY_AVAILABILITY_RULE: "A survey answer is assumed available at the end "
            "of the local day it describes; the sources record no entry time.",
            tables.LABEL_AVAILABILITY_RULE: "Episode and test labels (observed_at_utc) are "
            "assumed known only at the end of the participant's follow-up: the sources record "
            "neither when a label was reported nor which reports were retrospective.",
        },
        "canonical_recovery_endpoint": tables.endpoint_definition(defs, tables.CANONICAL_ENDPOINT),
        "tables": {
            name: {
                "sha256": sha256_file(staging / name),
                "rows": pq.read_metadata(staging / name).num_rows,
                "columns": t.schema.names,
            }
            for name, t in written.items()
        },
        "audit_sha256": sha256_file(staging / "audit.json"),
        "subjects": len(results),
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
    snapshot_id = f"{pipeline_version}-{dataset_id}-{admission.dataset_version}-{digest[:12]}"
    manifest["snapshot_id"] = snapshot_id
    _write_json(staging / "manifest.json", manifest)
    report = audit.report(snapshot_id, manifest, audit_doc)

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


def _endpoint_ids(defs: Definitions) -> dict[str, str]:
    return {
        e: tables.endpoint_definition(defs, e)
        for e in ("sustained_symptom_free", "self_reported_recovery")
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


def subject_span(days: Sequence[date]) -> DayRange:
    return DayRange(min(days), max(days))


# Reading ---------------------------------------------------------------------------------


def load_manifest(snapshot: Path) -> dict[str, Any]:
    return json.loads((snapshot / "manifest.json").read_text())


def dataset_snapshot_ref(snapshot: Path) -> DatasetSnapshotRef:
    return DatasetSnapshotRef.model_validate(load_manifest(snapshot)["dataset_snapshot"])


def read_outcomes(
    snapshot: Path, subjects: Sequence[str] | None = None
) -> list[SymptomEpisode | TestResult | StatusUnknown]:
    """Canonical outcome rows, validated against the shared contracts."""
    expression = ds.field("subject_id").isin(list(subjects)) if subjects is not None else None
    t = ds.dataset(snapshot / "outcomes.parquet").to_table(filter=expression)
    return [tables.outcome_from_row(r) for r in t.to_pylist()]


def read_table(snapshot: Path, name: str, subjects: Sequence[str] | None = None) -> pa.Table:
    """One of the snapshot's tables ('episodes', 'recovery', 'onset_windows', ...)."""
    path = snapshot / f"{name}.parquet"
    if not path.is_file():
        raise SnapshotError(f"{snapshot.name} has no table {name!r}")
    expression = ds.field("subject_id").isin(list(subjects)) if subjects is not None else None
    return ds.dataset(path).to_table(filter=expression)


def labels_known_by(
    snapshot: Path, cutoff: datetime, subjects: Sequence[str] | None = None
) -> list[SymptomEpisode | TestResult]:
    """Outcome labels recorded by a cutoff (on the dataset clock); unknown status never is."""
    from hachi.contracts.causality import label_known_by

    rows = read_outcomes(snapshot, subjects)
    return [r for r in rows if label_known_by(r, cutoff)]  # type: ignore[misc]


# Verifying -------------------------------------------------------------------------------


def verify(snapshot: Path, *, full: bool = False) -> dict[str, Any]:
    """Check checksums, manifest identity and counts; `full` re-validates every outcome row."""
    problems: list[str] = []
    listed = {}
    for line in (snapshot / "SHA256SUMS").read_text().splitlines():
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
    if full and not problems:
        rows = read_outcomes(snapshot)
        kinds = Counter(type(r).__name__ for r in rows)
        episodes = {r.episode_id for r in rows if isinstance(r, SymptomEpisode)}
        if len(episodes) != kinds["SymptomEpisode"]:
            problems.append("duplicate episode ids")
        for r in rows:
            if isinstance(r, TestResult) and r.episode_id and r.episode_id not in episodes:
                problems.append(f"test {r.test_id} links to a missing episode")
        checked["validated_outcomes"] = dict(kinds)
    return {
        "snapshot_id": manifest["snapshot_id"],
        "ok": not problems,
        "problems": problems,
        "checked": checked,
    }
