"""Read-only access to the admitted PMData archive: verified, streamed, never extracted."""

import hashlib
import io
import re
import stat
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Literal

from .config import Admission

# Every file a participant folder may hold, by role. Canonical members feed the snapshot;
# counted members are parsed only to reconcile row counts with the paper; the rest is never
# opened. Anything else refuses the archive rather than being silently skipped.
CANONICAL = frozenset(
    {
        "fitbit/heart_rate.json",
        "fitbit/steps.json",
        "fitbit/distance.json",
        "fitbit/resting_heart_rate.json",
        "fitbit/sleep.json",
        "pmsys/wellness.csv",
    }
)
COUNTED = frozenset(
    {
        "fitbit/calories.json",
        "fitbit/exercise.json",
        "fitbit/lightly_active_minutes.json",
        "fitbit/moderately_active_minutes.json",
        "fitbit/very_active_minutes.json",
        "fitbit/sedentary_minutes.json",
        "fitbit/time_in_heart_rate_zones.json",
        "fitbit/sleep_score.csv",
        "pmsys/srpe.csv",
        "pmsys/injury.csv",
        "googledocs/reporting.csv",
    }
)
PARTICIPANT = re.compile(r"^(p\d{2})/(.+)$")
IMAGE = re.compile(r"^food-images/[^/]+\.(jpe?g|png)$", re.IGNORECASE)
NOT_READ = {"participant-overview.xlsx": "demographics"}

# Bounds on what one member may expand to; the largest admitted member is ~260 MB.
MAX_MEMBER_BYTES = 1 << 30
MAX_MEMBERS = 4096

type Role = Literal["canonical", "counted", "not_read"]


class ArchiveError(ValueError):
    """The archive is not the admitted one, or holds something unexpected."""


@dataclass(frozen=True)
class Member:
    name: str
    subject: str | None
    kind: str  # e.g. "fitbit/steps.json", "food-images", "participant-overview.xlsx"
    role: Role
    size: int


@dataclass
class MemberDigest:
    """SHA-256 of a member's decompressed bytes, filled in while it is streamed."""

    name: str
    sha256: str = ""
    size: int = 0


@dataclass
class Archive:
    path: Path
    admission: Admission
    members: list[Member]
    digests: dict[str, MemberDigest] = field(default_factory=dict)
    _zip: zipfile.ZipFile | None = None

    def subjects(self) -> list[str]:
        return sorted({m.subject for m in self.members if m.subject is not None})

    def member(self, subject: str, kind: str) -> Member | None:
        name = f"{subject}/{kind}"
        return next((m for m in self.members if m.name == name), None)

    @contextmanager
    def open(self, member: Member) -> Iterator[BinaryIO]:
        """Stream one member, hashing it and enforcing its declared size."""
        if member.role == "not_read":
            raise ArchiveError(f"{member.name} is not read by this pipeline")
        assert self._zip is not None
        digest = hashlib.sha256()
        with self._zip.open(member.name) as raw:
            reader = _HashingReader(raw, digest, member.size)
            yield io.BufferedReader(reader, buffer_size=1 << 20)
            reader.drain()
        self.digests[member.name] = MemberDigest(member.name, digest.hexdigest(), reader.count)


class _HashingReader(io.RawIOBase):
    """Counts and hashes every byte read, refusing to read past the declared size."""

    def __init__(self, raw: BinaryIO, digest, limit: int) -> None:
        super().__init__()
        self._raw, self._digest, self._limit, self.count = raw, digest, limit, 0

    def readable(self) -> bool:
        return True

    def _take(self, size: int) -> bytes:
        block = self._raw.read(size)
        self.count += len(block)
        if self.count > self._limit:
            raise ArchiveError("a member expanded beyond its declared size")
        self._digest.update(block)
        return block

    def readinto(self, buffer) -> int:
        block = self._take(len(buffer))
        buffer[: len(block)] = block
        return len(block)

    def drain(self) -> None:
        """Hash whatever the parser left unread, so the digest always covers the member."""
        while self._take(1 << 20):
            pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _classify(info: zipfile.ZipInfo) -> Member | None:
    name = info.filename
    if name.startswith(("/", "\\")) or "\\" in name or ".." in name.split("/") or ":" in name:
        raise ArchiveError(f"unsafe member path {name!r}")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise ArchiveError(f"symbolic link member {name!r}")
    if info.flag_bits & 0x1:
        raise ArchiveError(f"encrypted member {name!r}")
    if info.is_dir():
        return None
    if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise ArchiveError(f"unsupported compression in {name!r}")
    if info.file_size > MAX_MEMBER_BYTES:
        raise ArchiveError(f"{name!r} is larger than {MAX_MEMBER_BYTES} bytes")
    if name in NOT_READ:
        return Member(name, None, name, "not_read", info.file_size)
    match = PARTICIPANT.match(name)
    if match is None:
        raise ArchiveError(f"unexpected member {name!r}")
    subject, rest = match.groups()
    if rest in CANONICAL:
        return Member(name, subject, rest, "canonical", info.file_size)
    if rest in COUNTED:
        return Member(name, subject, rest, "counted", info.file_size)
    if IMAGE.match(rest):
        return Member(name, subject, "food-images", "not_read", info.file_size)
    raise ArchiveError(f"unexpected member {name!r}")


@contextmanager
def open_archive(path: Path, admission: Admission) -> Iterator[Archive]:
    """Open the admitted archive after checking its size and SHA-256 against the registry."""
    if path.name != admission.archive_name:
        raise ArchiveError(f"expected {admission.archive_name}, got {path.name}")
    if path.stat().st_size != admission.archive_bytes:
        raise ArchiveError("archive size differs from the admitted archive")
    if sha256_file(path) != admission.archive_sha256:
        raise ArchiveError("archive SHA-256 differs from the admitted archive")
    with zipfile.ZipFile(path) as handle:
        infos = handle.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ArchiveError("too many archive members")
        names = [i.filename for i in infos]
        if len(names) != len(set(names)):
            raise ArchiveError("duplicate member names")
        members = [m for m in (_classify(i) for i in infos) if m is not None]
        archive = Archive(path, admission, sorted(members, key=lambda m: m.name), _zip=handle)
        try:
            yield archive
        finally:
            archive._zip = None
