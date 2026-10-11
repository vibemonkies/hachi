#!/usr/bin/env python3
"""Scan the current tracked tree and explicit demo assets; print counts, never matches.

Optional --clinical-snapshot reads the permitted private roster in memory to detect
exact participant identifiers. This is a bounded current-tree scan, not a history audit.
"""

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

SECRET_PATTERNS = (
    rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})",
    rb"AKIA[A-Z0-9]{16}",
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    rb"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}",
)
PRIVATE_SUFFIXES = {
    ".parquet",
    ".arrow",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".h5",
    ".hdf5",
    ".pt",
    ".pth",
    ".ckpt",
    ".safetensors",
    ".pem",
    ".key",
    ".zip",
}
MAX_FILE_BYTES = 8 * 1024 * 1024


def scan(paths: list[Path], participant_ids: set[str]) -> dict:
    counts = Counter()
    patterns = [re.compile(p) for p in SECRET_PATTERNS]
    participants = [
        re.compile(rb"(?<![A-Za-z0-9_-])" + re.escape(p.encode()) + rb"(?![A-Za-z0-9_-])")
        for p in participant_ids
    ]
    for path in paths:
        if path.is_symlink() or not path.is_file():
            counts["unreadable_or_symlink"] += 1
            continue
        if path.suffix.lower() in PRIVATE_SUFFIXES or path.name.lower() in {
            "export.xml",
            ".env",
            "covid-19-wearables.zip",
        }:
            counts["private_data_or_key_file"] += 1
        if path.stat().st_size > MAX_FILE_BYTES:
            counts["unscanned_oversize"] += 1
            continue
        data = path.read_bytes()
        if any(p.search(data) for p in patterns):
            counts["credential_pattern"] += 1
        if any(p.search(data) for p in participants):
            counts["participant_identifier"] += 1
        # Real HealthData raw XML must never be a presentation asset. Test source code
        # constructs XML in memory; contract fixtures are generated canonical JSON.
        if b"<HealthData" in data and b"<Record " in data and path.suffix.lower() == ".xml":
            counts["raw_health_export"] += 1
    return {
        "ok": not counts,
        "files_scanned": len(paths),
        "findings": dict(counts),
        "participant_roster_checked": bool(participant_ids),
        "scope": "current tracked files plus explicit assets; no Git history",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, nargs="*", default=[])
    parser.add_argument("--clinical-snapshot", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\0")
    paths = [root / p.decode() for p in tracked if p]
    for asset in args.assets:
        if asset.is_symlink() or not asset.exists():
            paths.append(asset)
        elif asset.is_dir():
            paths.extend(p for p in asset.rglob("*") if p.is_file() or p.is_symlink())
        else:
            paths.append(asset)
    ids = set()
    if args.clinical_snapshot:
        from hachi.data.clinical.snapshot import read_table, verify

        verified = verify(args.clinical_snapshot, full=True)
        if not verified["ok"]:
            print(json.dumps({"ok": False, "error": "private roster verification failed"}))
            return 1
        ids = set(read_table(args.clinical_snapshot, "subjects")["subject_id"].to_pylist())
    result = scan(list(dict.fromkeys(paths)), ids)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
