"""Publication scans refuse generated examples of credentials, IDs and unscanned files."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "hachi_privacy_scan", Path(__file__).parents[2] / "scripts/privacy/scan.py"
)
assert SPEC is not None and SPEC.loader is not None
SCANNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCANNER)


def test_scanner_detects_credentials_and_exact_roster_ids_without_echo(tmp_path):
    source = tmp_path / "asset.txt"
    generated_token = "ghp_" + "S" * 36
    source.write_text(generated_token + " synthetic-private-person ")
    result = SCANNER.scan([source], {"synthetic-private-person"})
    assert not result["ok"]
    assert result["findings"] == {"credential_pattern": 1, "participant_identifier": 1}
    assert generated_token not in str(result) and "synthetic-private-person" not in str(result)
    source.write_text("prefixsynthetic-private-personsuffix")
    assert SCANNER.scan([source], {"synthetic-private-person"})["ok"]


@pytest.mark.parametrize("kind", ["symlink", "oversize", "database"])
def test_scanner_refuses_private_or_unscanned_assets(tmp_path, kind):
    source = tmp_path / "asset.txt"
    if kind == "symlink":
        source.symlink_to(tmp_path / "not-published")
    elif kind == "oversize":
        with source.open("wb") as output:
            output.truncate(SCANNER.MAX_FILE_BYTES + 1)
    else:
        source = tmp_path / "personal.sqlite3"
        source.write_bytes(b"generated private database")
    result = SCANNER.scan([source], set())
    assert not result["ok"] and result["files_scanned"] == 1
