"""Archive resource limits and privacy-safe CLI behavior on generated exports."""

import json
import subprocess
import sys
import zipfile

import pytest

from hachi.data.apple_health import ImportLimits, ImportProblem, import_export

from .test_importer import record, xml


@pytest.mark.parametrize(
    "case",
    [
        "ambiguous",
        "symlink",
        "ratio",
        "directory",
        "entries",
        "corrupt",
        "comment",
    ],
)
def test_unsafe_archives_are_refused(tmp_path, config, case):
    path = tmp_path / "export.zip"
    limits = ImportLimits()
    if case == "corrupt":
        path.write_bytes(b"not a ZIP")
    else:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if case == "symlink":
                member = zipfile.ZipInfo("export.xml")
                member.create_system = 3
                member.external_attr = 0o120777 << 16
                archive.writestr(member, b"another.xml")
            else:
                archive.writestr("export.xml", xml([record()]))
            if case in {"ambiguous", "entries"}:
                archive.writestr("other/export.xml", xml([record()]))
            if case == "comment":
                archive.comment = b"PK\x05\x06" + b"x" * 30
        if case == "ratio":
            limits = ImportLimits(expansion_ratio=1)
        elif case == "directory":
            limits = ImportLimits(central_directory_bytes=10)
        elif case == "entries":
            limits = ImportLimits(archive_entries=1)
    with pytest.raises(ImportProblem) as error:
        import_export(path, config, tmp_path / "private" / "import.sqlite3", limits=limits)
    assert error.value.failure.error_code == "ARCHIVE_UNSAFE"
    assert error.value.failure.action


def test_cli_reports_aggregate_audit_without_private_source_names(tmp_path):
    source = tmp_path / "export.xml"
    source.write_bytes(xml([record(sourceName="Synthetic private source")]))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hachi.data.apple_health",
            str(source),
            "--database",
            str(tmp_path / "private" / "import.sqlite3"),
            "--dataset-id",
            "synthetic-apple",
            "--subject-id",
            "synthetic-001",
            "--timezone",
            "UTC",
            "--data-mode",
            "synthetic",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    audit = json.loads(result.stdout)
    assert audit["data_mode"] == "synthetic"
    assert audit["counts"]["records_accepted"] == 1
    assert audit["metric_spans_utc"]["heart_rate"] == [
        "2026-10-10T07:00:00+00:00",
        "2026-10-10T07:00:00+00:00",
    ]
    assert "Synthetic private source" not in result.stdout
    assert "Private" not in result.stdout
