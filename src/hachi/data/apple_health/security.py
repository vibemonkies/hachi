"""Bounded input and archive access; no extraction or external XML resources."""

import stat
import struct
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from hachi.contracts.api import ImportErrorCode, ImportFailure


class ImportProblem(ValueError):
    def __init__(self, code: ImportErrorCode, message: str, action: str) -> None:
        self.failure = ImportFailure(error_code=code, message=message, action=action)
        super().__init__(message)


@dataclass(frozen=True)
class ImportLimits:
    upload_bytes: int = 256 * 1024 * 1024
    xml_bytes: int = 1024 * 1024 * 1024
    archive_entries: int = 1024
    central_directory_bytes: int = 4 * 1024 * 1024
    expansion_ratio: float = 1000.0
    records: int = 2_000_000
    token_bytes: int = 64 * 1024
    record_bytes: int = 128 * 1024
    depth: int = 32
    xml_names: int = 256

    def __post_init__(self) -> None:
        if any(
            value <= 0
            for value in (
                self.upload_bytes,
                self.xml_bytes,
                self.archive_entries,
                self.central_directory_bytes,
                self.records,
                self.token_bytes,
                self.record_bytes,
                self.depth,
                self.xml_names,
                self.expansion_ratio,
            )
        ):
            raise ValueError("import limits must be positive")


def too_large() -> ImportProblem:
    return ImportProblem(
        "FILE_TOO_LARGE",
        "The export exceeds the configured import limit.",
        "Use a smaller export or have the storage owner review the configured limits.",
    )


def unsafe_archive() -> ImportProblem:
    return ImportProblem(
        "ARCHIVE_UNSAFE",
        "The ZIP is unsafe, ambiguous, damaged, or unsupported.",
        "Provide an unencrypted single-disk ZIP containing one export.xml, or the XML itself.",
    )


def _check_directory(stream: BinaryIO, limits: ImportLimits) -> None:
    # Bound zipfile's central-directory allocation BEFORE constructing ZipFile.
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(max(0, size - 65557))
    tail = stream.read(65557)
    offset = tail.rfind(b"PK\x05\x06")
    if offset < 0 or len(tail) - offset < 22:
        raise unsafe_archive()
    fields = struct.unpack_from("<4s4H2LH", tail, offset)
    # Match zipfile's choice of the final signature. Do not validate an earlier
    # EOCD while ZipFile later interprets attacker-controlled comment bytes.
    if offset + 22 + fields[7] != len(tail):
        raise unsafe_archive()
    _, disk, directory_disk, disk_entries, entries, directory_size, directory_offset, _ = fields
    if (
        disk
        or directory_disk
        or disk_entries != entries
        or entries == 65535
        or entries > limits.archive_entries
        or directory_size > limits.central_directory_bytes
        or directory_size == 0xFFFFFFFF
        or directory_offset == 0xFFFFFFFF
        or directory_offset + directory_size > size - 22
    ):
        raise unsafe_archive()
    stream.seek(0)


def _xml_member(archive: zipfile.ZipFile, limits: ImportLimits) -> zipfile.ZipInfo:
    infos = archive.infolist()
    if len(infos) > limits.archive_entries:
        raise unsafe_archive()
    total = 0
    matches = []
    for info in infos:
        path = PurePosixPath(info.filename)
        mode = info.external_attr >> 16
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in info.filename
            or "\x00" in info.orig_filename
            or ":" in info.filename
            or "\x00" in info.filename
            or stat.S_ISLNK(mode)
            or info.flag_bits & 1
            or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
        ):
            raise unsafe_archive()
        total += info.file_size
        if total > limits.xml_bytes:
            raise too_large()
        if info.file_size / max(1, info.compress_size) > limits.expansion_ratio:
            raise unsafe_archive()
        if not info.is_dir() and path.name == "export.xml":
            matches.append(info)
    if len(matches) != 1:
        raise unsafe_archive()
    return matches[0]


@contextmanager
def export_stream(path: Path, limits: ImportLimits) -> Iterator[BinaryIO]:
    if path.stat().st_size > limits.upload_bytes:
        raise too_large()
    if path.suffix.lower() not in {".xml", ".zip"}:
        raise ImportProblem(
            "UNSUPPORTED_FORMAT",
            "Only Apple Health XML or ZIP exports are accepted.",
            "Provide export.xml or the Apple Health export ZIP.",
        )
    with path.open("rb") as source:
        if path.suffix.lower() == ".xml":
            yield source
            return
        _check_directory(source, limits)
        try:
            with zipfile.ZipFile(source) as archive:
                member = _xml_member(archive, limits)
                with archive.open(member) as xml:
                    yield xml
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
            raise unsafe_archive() from exc
