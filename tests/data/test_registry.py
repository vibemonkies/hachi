"""The dataset registry is complete, internally consistent and honest about access."""

import hashlib
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from hachi.data.registry import REGISTRY_DIR, DatasetSource, load_registry, sha256sums, verify

# Every source named in docs/RESEARCH.md's catalog has an entry.
CATALOG = {
    "pmdata",
    "covidentify",
    "stanford-wearable-infection",
    "cmu-common-cold-project",
    "openmhc",
    "nhanes-paxmin-h",
    "wesad",
    "ppg-dalia",
    "sleep-edfx",
    "dreamt",
    "globem",
    "all-of-us",
    "uk-biobank",
    "mipact",
    "personal-apple-export",
}


def raw(dataset_id: str) -> dict:
    with (REGISTRY_DIR / f"{dataset_id}.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_registry_loads_and_covers_the_catalog() -> None:
    assert set(load_registry()) >= CATALOG


def test_research_catalog_links_every_registry_entry() -> None:
    research = (REGISTRY_DIR.parents[1] / "docs" / "RESEARCH.md").read_text()
    for dataset_id in load_registry():
        assert f"configs/datasets/{dataset_id}.toml" in research, dataset_id


def test_first_usable_cohorts_are_held_with_checksums() -> None:
    sources = load_registry()
    for dataset_id in ("pmdata", "cmu-common-cold-project"):
        assert sources[dataset_id].status in {"downloaded", "validated"}
        assert sources[dataset_id].files


def test_individually_licensed_data_cannot_be_allowed_on_the_shared_account() -> None:
    doc = raw("cmu-common-cold-project")
    doc["terms"]["shared_gx10_account"] = "allowed"
    with pytest.raises(ValidationError, match="shared GX10 account"):
        DatasetSource.model_validate(doc)


def test_a_catalog_entry_is_not_proof_of_access() -> None:
    doc = raw("covidentify")
    doc["files"] = [{"name": "x.zip", "bytes": 1, "sha256": "0" * 64}]
    with pytest.raises(ValidationError, match="only downloaded or validated"):
        DatasetSource.model_validate(doc)


def test_held_sources_need_an_owner_who_accepted_the_terms() -> None:
    doc = raw("cmu-common-cold-project")
    doc["approved_users"] = []
    with pytest.raises(ValidationError, match="accepted the terms"):
        DatasetSource.model_validate(doc)


def test_verify_detects_matching_missing_and_altered_archives(tmp_path: Path) -> None:
    source = load_registry()["cmu-common-cold-project"]
    first, second = source.files[0], source.files[1]
    payload = b"synthetic archive bytes"
    forged = first.model_copy(
        update={"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    )
    (tmp_path / forged.name).write_bytes(payload)
    (tmp_path / second.name).write_bytes(b"x" * second.bytes)
    patched = source.model_copy(update={"files": [forged, second]})
    states = {name: state for _, name, state in verify(tmp_path, {"cmu": patched})}
    assert states == {forged.name: "ok", second.name: "MISMATCH"}
    missing = verify(tmp_path / "absent", {"cmu": patched})
    assert {state for *_, state in missing} == {"missing"}


def test_verify_finds_archives_in_the_versioned_gx10_layout(tmp_path: Path) -> None:
    source = load_registry()["cmu-common-cold-project"]
    payload = b"versioned layout"
    archive = source.files[0].model_copy(
        update={"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    )
    folder = tmp_path / source.dataset_id / str(source.version)
    folder.mkdir(parents=True)
    (folder / archive.name).write_bytes(payload)
    patched = source.model_copy(update={"files": [archive]})
    assert verify(tmp_path, {"cmu": patched}) == [(source.dataset_id, archive.name, "ok")]


def test_sha256sums_match_the_coreutils_format() -> None:
    source = load_registry()["cmu-common-cold-project"]
    lines = sha256sums(source).splitlines()
    assert len(lines) == len(source.files)
    assert lines[0] == f"{source.files[0].sha256}  {source.files[0].name}"
