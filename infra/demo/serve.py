#!/usr/bin/env python3
"""Launch a private demo with explicit per-worker roots, snapshots, and artifact pins."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from hachi.api.settings import Settings
from hachi.storage import private_directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-root",
        type=Path,
        required=True,
        help="new private directory for this worker; never a source-data root",
    )
    parser.add_argument("--owner", default="ezzy1630")
    parser.add_argument("--port", type=int, default=8719)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--snapshot", action="append", default=[])
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--artifact", action="append", default=[], help="ID@sha256 pin")
    args = parser.parse_args()
    root = args.state_root.expanduser().absolute()
    repo = Path(__file__).resolve().parents[2]
    if root.exists() or root.is_symlink() or root.is_relative_to(repo):
        parser.error("state-root must be new and outside the checkout")
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    env = {k: v for k, v in os.environ.items() if not k.startswith("HACHI_")}
    env.update(
        {
            "HACHI_OWNER": args.owner,
            "HACHI_WORKSPACES": str(root / "workspaces"),
            "HACHI_DB_PATH": str(root / "workspaces" / args.owner / "state" / "metadata.sqlite3"),
            "HACHI_RUN_DIR": str(root / "run"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "HF_HOME": str(root / "cache" / "models"),
            "HACHI_ARTIFACT_ROOT": str(args.artifact_root.expanduser().absolute()),
            "HACHI_SERVE_ARTIFACTS": ",".join(args.artifact),
            "HACHI_DATASET_SNAPSHOTS": ",".join(args.snapshot),
            "HACHI_GIT_SHA": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip(),
        }
    )
    if args.data_root:
        env["HACHI_DATA_ROOT"] = str(args.data_root.expanduser().absolute())
    # Validate configuration before creating private runtime state.
    settings = Settings.from_environment(environ=env)
    private_directory(root)
    for path in (settings.workspace.root, settings.workspace.state, root / "run", root / "cache"):
        private_directory(path)
    os.umask(0o077)
    os.execve(
        sys.executable,
        [
            sys.executable,
            "-I",
            "-m",
            "hachi.api",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ],
        env,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
