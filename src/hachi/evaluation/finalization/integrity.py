"""Read immutable private bundles without executing their model code."""

import hashlib
import os
import stat
import subprocess
from functools import cache
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


@cache
def _git_blob(repo: Path, git_sha: str, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{git_sha}:{relative}"], cwd=repo, capture_output=True, check=False
    )
    if result.returncode:
        raise EvidenceRefused("producing source commit is unavailable")
    return result.stdout


def read_producing_file(repo: Path, git_sha: str, relative: str) -> bytes:
    """Read a pinned historical document, with the same path/size boundary as inputs."""
    path = TypeAdapter(RelativePath).validate_python(relative)
    raw = _git_blob(repo, git_sha, path)
    if len(raw) > MAX_JSON_BYTES:
        raise EvidenceRefused("producing document exceeds its format limit")
    return raw


def verify_sources(
    raw: bytes,
    repo: Path,
    git_sha: str,
    prefix: str,
    *,
    required_files: frozenset[str] | None = None,
) -> None:
    """Compare historical source receipts with their producing commit, not current main."""
    sources = SOURCES.validate_json(raw)
    if not sources:
        raise EvidenceRefused("source receipt is empty")
    paths = {f"src/hachi/{n}" if "/" in n else f"{prefix}/{n}" for n in sources}
    tracked = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", git_sha, prefix],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    required = (
        required_files
        if required_files is not None
        else {
            p
            for p in tracked.stdout.splitlines()
            if str(Path(p).parent) == prefix and Path(p).suffix == ".py"
        }
    )
    if tracked.returncode or not required or not required <= paths:
        raise EvidenceRefused("source receipt omits producing implementation files")
    for name, expected in sources.items():
        relative = f"src/hachi/{name}" if "/" in name else f"{prefix}/{name}"
        if digest(_git_blob(repo, git_sha, relative)) != expected:
            raise EvidenceRefused("source receipt differs from the producing commit")


def require_separate_output(output: Path, roots: list[Path]) -> None:
    if any(output.resolve().is_relative_to(root.resolve()) for root in roots):
        raise EvidenceRefused("output must be outside immutable input bundles")


def write_private(output: Path, payloads: dict[str, bytes]) -> dict[str, str]:
    """Exclusive output creation; never rewrite an existing packet or upstream bundle."""
    hashes = {name: digest(raw) for name, raw in payloads.items()}
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, raw in {**payloads, "sha256.json": document_bytes(hashes)}.items():
        fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
    return hashes
