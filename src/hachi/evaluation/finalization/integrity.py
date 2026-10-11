"""Read immutable private bundles without executing their model code."""

import hashlib
import os
import stat
import subprocess
from pathlib import Path

from pydantic import TypeAdapter

from hachi.contracts.base import RelativePath, Sha256
from hachi.evaluation.serialization import document_bytes

INDEX = TypeAdapter(dict[RelativePath, Sha256])
SOURCES = TypeAdapter(dict[RelativePath, Sha256])
MAX_JSON_BYTES = 128 * 1024 * 1024


class EvidenceRefused(ValueError):
    """Messages deliberately omit private paths, values and participant identities."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_file(root: Path, relative: str) -> bytes:
    relative = TypeAdapter(RelativePath).validate_python(relative)
    path = root
    if root.is_symlink() or not root.is_dir():
        raise EvidenceRefused("evidence root must be a real directory")
    for part in relative.split("/"):
        path = path / part
        if path.is_symlink():
            raise EvidenceRefused("evidence cannot contain symlinks")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON_BYTES:
        raise EvidenceRefused("evidence file must be regular and within the size limit")
    return path.read_bytes()


def verify_index(root: Path, expected: str) -> dict[str, str]:
    """Pin the index externally, then verify every byte and reject unindexed files."""
    raw = read_file(root, "sha256.json")
    if digest(raw) != expected:
        raise EvidenceRefused("bundle index does not match its expected checksum")
    index = INDEX.validate_json(raw)
    if not index or "sha256.json" in index:
        raise EvidenceRefused("bundle index must be nonempty and cannot index itself")
    present = set()
    for directory, directories, files in os.walk(root, followlinks=False):
        base = Path(directory)
        if any((base / name).is_symlink() for name in directories):
            raise EvidenceRefused("evidence cannot contain symlink directories")
        present.update((base / name).relative_to(root).as_posix() for name in files)
    if present != {*index, "sha256.json"}:
        raise EvidenceRefused("bundle contains missing or unindexed files")
    for name, expected_digest in index.items():
        if digest(read_file(root, name)) != expected_digest:
            raise EvidenceRefused("bundle content checksum mismatch")
    return index


def verify_sources(raw: bytes, repo: Path, git_sha: str, prefix: str) -> None:
    """Compare historical source receipts with their producing commit, not current main."""
    sources = SOURCES.validate_json(raw)
    if not sources:
        raise EvidenceRefused("source receipt is empty")
    for name, expected in sources.items():
        relative = f"src/hachi/{name}" if "/" in name else f"{prefix}/{name}"
        result = subprocess.run(
            ["git", "show", f"{git_sha}:{relative}"],
            cwd=repo,
            capture_output=True,
            check=False,
        )
        if result.returncode or digest(result.stdout) != expected:
            raise EvidenceRefused("source receipt differs from the producing commit")


def write_private(output: Path, payloads: dict[str, bytes]) -> dict[str, str]:
    """Exclusive output creation; never rewrite an existing packet or upstream bundle."""
    hashes = {name: digest(raw) for name, raw in payloads.items()}
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, raw in {**payloads, "sha256.json": document_bytes(hashes)}.items():
        fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
    return hashes
