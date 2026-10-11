"""Exclusive durable receipt appends in a private directory, pinned by the caller."""

import fcntl
import hashlib
import os
import stat
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from hachi.contracts.base import Sha256
from hachi.evaluation.serialization import document_bytes, document_sha256

from .policy import ProspectiveRefused, require_transition
from .specification import FollowUp, Prediction, Protocol, Receipt, ReceiptBody, Registration

MAX_RECEIPT_BYTES = 16 * 1024 * 1024
MAX_RECEIPTS = 10000


def _now() -> datetime:
    return datetime.now(UTC)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _private_path(root: Path) -> None:
    for path in (root, *root.absolute().parents):
        if path.is_symlink():
            raise ProspectiveRefused("journal path cannot contain symlinks")
        if (path / ".git").exists():
            raise ProspectiveRefused("private journal must stay outside Git checkouts")


@contextmanager
def _directory(root: Path, *, exclusive: bool):
    _private_path(root)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise ProspectiveRefused("journal requires private directory permissions")
        # The directory inode is the local lock; no shared root lock or database.
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield fd
    finally:
        os.close(fd)


def _read(fd: int, name: str) -> bytes:
    entry_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(entry_fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > MAX_RECEIPT_BYTES
        ):
            raise ProspectiveRefused("receipt must be a private single-link regular file")
        return stream.read(MAX_RECEIPT_BYTES + 1)


def _chain(fd: int, expected_head: str | None) -> list[Receipt]:
    names = sorted(os.listdir(fd))
    if names != [f"{i:08d}.json" for i in range(len(names))] or len(names) > MAX_RECEIPTS:
        raise ProspectiveRefused("journal has missing, reordered or unexpected files")
    receipts: list[Receipt] = []
    try:
        for name in names:
            raw = _read(fd, name)
            receipt = Receipt.model_validate_json(raw)
            if raw != document_bytes(receipt):
                raise ProspectiveRefused("receipt serialization is not canonical")
            require_transition(receipts, receipt)
            receipts.append(receipt)
        if expected_head is not None:
            TypeAdapter(Sha256).validate_python(expected_head)
        if (receipts[-1].sha256 if receipts else None) != expected_head:
            raise ProspectiveRefused("journal differs from externally retained head pin")
    except (OSError, ValidationError) as exc:
        raise ProspectiveRefused("journal cannot be verified") from exc
    return receipts


def _append(
    fd: int, receipts: list[Receipt], payload: Registration | Prediction | FollowUp
) -> Receipt:
    if len(receipts) >= MAX_RECEIPTS:
        raise ProspectiveRefused("journal receipt capacity reached")
    body = ReceiptBody(
        sequence=len(receipts),
        previous_sha256=receipts[-1].sha256 if receipts else None,
        logged_at_utc=_now(),
        payload=payload,
    )
    receipt = Receipt(body=body, sha256=document_sha256(body))
    raw = document_bytes(receipt)
    try:
        # Canonical contracts freeze attributes, but their nested lists remain mutable.
        # Validate the bytes actually saved, and detach caller-owned containers.
        receipt = Receipt.model_validate_json(raw)
    except ValidationError:
        raise ProspectiveRefused("receipt payload violates canonical contracts") from None
    require_transition(receipts, receipt)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ProspectiveRefused("receipt exceeds private journal size limit")
    entry_fd = os.open(
        f"{len(receipts):08d}.json",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=fd,
    )
    with os.fdopen(entry_fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.fsync(fd)
    return receipt


class Journal:
    """No clock override, mutable head pointer, edit, deletion, or real-mode authorization."""

    def __init__(self, root: Path):
        self.root = root

    @classmethod
    def create(cls, root: Path, protocol: Protocol, *, analysis_plan: bytes) -> Receipt:
        _private_path(root)
        if protocol.data_mode != "synthetic":
            raise ProspectiveRefused("real studies are outside preparation authorization")
        if _digest(analysis_plan) != protocol.analysis_plan_sha256:
            raise ProspectiveRefused("analysis plan differs from frozen protocol")
        root.mkdir(mode=0o700, exist_ok=False)
        with _directory(root, exclusive=True) as fd:
            return _append(fd, _chain(fd, None), Registration(protocol=protocol))

    def verify(self, expected_head: str) -> list[Receipt]:
        with _directory(self.root, exclusive=False) as fd:
            return _chain(fd, expected_head)

    def predict(
        self, prediction: Prediction, *, expected_head: str, input_document: bytes
    ) -> Receipt:
        if _digest(input_document) != prediction.input_sha256:
            raise ProspectiveRefused("input document differs from prediction input hash")
        with _directory(self.root, exclusive=True) as fd:
            return _append(fd, _chain(fd, expected_head), prediction)

    def follow_up(
        self, follow_up: FollowUp, *, expected_head: str, outcome_document: bytes
    ) -> Receipt:
        if outcome_document != document_bytes(follow_up.aggregates):
            raise ProspectiveRefused("outcome document differs from captured canonical aggregates")
        if _digest(outcome_document) != follow_up.outcome_document_sha256:
            raise ProspectiveRefused("outcome document differs from follow-up hash")
        with _directory(self.root, exclusive=True) as fd:
            return _append(fd, _chain(fd, expected_head), follow_up)
