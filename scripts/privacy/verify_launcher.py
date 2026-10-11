#!/usr/bin/env python3
"""Prove the private launcher clears inherited roots and creates only isolated state."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 8719))
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    with tempfile.TemporaryDirectory(prefix="hachi-19-launch-") as directory:
        parent = Path(directory)
        root = parent / "demo"
        inherited = parent / "must-not-exist.sqlite3"
        env = dict(
            os.environ,
            HACHI_OWNER="wrong-owner",
            HACHI_DB_PATH=str(inherited),
            HACHI_GIT_SHA="wrong-sha",
            HACHI_SERVE_ARTIFACTS="bad-pin",
        )
        with (parent / "startup.log").open("wb") as output:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(repo / "infra/demo/serve.py"),
                    "--state-root",
                    str(root),
                    "--owner",
                    "privacy-launch",
                    "--port",
                    "8719",
                    "--artifact-root",
                    str(parent / "models"),
                ],
                env=env,
                cwd=repo,
                stdout=output,
                stderr=output,
                umask=0o077,
            )
            result = {"ok": False, "git_sha": sha}
            try:
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(
                            "http://127.0.0.1:8719/healthz", timeout=0.2
                        ) as r:
                            health = json.load(r)
                        break
                    except OSError:
                        if process.poll() is not None:
                            raise RuntimeError("launcher exited") from None
                        time.sleep(0.05)
                else:
                    raise RuntimeError("launcher not ready")
                database = root / "workspaces/privacy-launch/state/metadata.sqlite3"
                result.update(
                    {
                        "health_matches_commit": health["git_sha"] == sha,
                        "model_refs": health["artifacts"],
                        "isolated_database_created": database.is_file(),
                        "inherited_database_untouched": not inherited.exists(),
                        "root_private": root.stat().st_mode & 0o777 == 0o700,
                        "state_private": database.parent.stat().st_mode & 0o777 == 0o700,
                    }
                )
                result["ok"] = (
                    all(
                        result[k]
                        for k in (
                            "health_matches_commit",
                            "isolated_database_created",
                            "inherited_database_untouched",
                            "root_private",
                            "state_private",
                        )
                    )
                    and not health["artifacts"]
                )
            except Exception as exc:
                result["error_type"] = type(exc).__name__
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
