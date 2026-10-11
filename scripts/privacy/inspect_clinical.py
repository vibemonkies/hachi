#!/usr/bin/env python3
"""Read-only permitted source/snapshot inspection; emit aggregate identities and modes.

Never changes permissions, reads a source row into output, or deletes private data.
Actual clock/label interpretation is governed by the snapshot's outcome definitions.
"""

import argparse
import hashlib
import json
import stat
from pathlib import Path

from hachi.data.clinical.snapshot import dataset_snapshot_ref, verify


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    args = parser.parse_args()
    try:
        verified = verify(args.snapshot, full=True)
        ref = dataset_snapshot_ref(args.snapshot)
        archive_sha = digest(args.archive)
        files = list(args.snapshot.iterdir())
        result = {
            "ok": verified["ok"]
            and archive_sha == args.archive_sha256
            and ref.snapshot_sha256 == args.snapshot_sha256,
            "archive_sha256_matches": archive_sha == args.archive_sha256,
            "snapshot_sha256_matches": ref.snapshot_sha256 == args.snapshot_sha256,
            "verified_files": verified["checked"]["files"],
            "validated_outcome_counts": verified["checked"]["validated_outcomes"],
            "archive_mode": oct(stat.S_IMODE(args.archive.stat().st_mode)),
            "snapshot_directory_mode": oct(stat.S_IMODE(args.snapshot.stat().st_mode)),
            "snapshot_files_writable": sum(bool(p.stat().st_mode & 0o222) for p in files),
            "snapshot_files_world_readable": sum(bool(p.stat().st_mode & 0o004) for p in files),
            "source_modified": False,
            "deletion_attempted": False,
        }
    except Exception as exc:
        result = {"ok": False, "error_type": type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
