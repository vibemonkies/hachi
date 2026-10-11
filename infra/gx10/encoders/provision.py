"""Create the #11 encoder environment from the locked wheels plus the recorded local builds.

  python3 infra/gx10/encoders/provision.py --owner justin06lee --built DIR

DIR is a build.py output whose built.lock equals the committed infra/gx10/encoders/built.lock.
The environment is new (envs/<sha256(requirements.lock + built.lock)[:16]>), installed with
--no-index --no-deps --require-hashes and checked with pip check. Existing environments,
including the shared runtime env, are never modified or removed.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from build import HERE, OWNERS, digest, ensure_wheels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True, choices=OWNERS)
    parser.add_argument("--built", required=True, type=Path)
    args = parser.parse_args()
    if platform.machine() != "aarch64" or sys.version_info[:2] != (3, 12):
        parser.error("this lock requires CPython 3.12 on Linux aarch64")
    os.umask(0o077)
    root = Path(os.environ.get("HACHI_HOME", Path.home() / "hachi")).resolve()
    workspace = root / "workspaces" / args.owner
    lock = HERE / "requirements.lock"
    built_lock = HERE / "built.lock"
    built = args.built.resolve()
    if (built / "built.lock").read_bytes() != built_lock.read_bytes():
        parser.error("the build output's built.lock differs from the committed one")
    receipt = json.loads((built / "built-wheels.json").read_text())
    for wheel in receipt["wheels"]:
        if digest(built / wheel["filename"]) != wheel["sha256"]:
            parser.error(f"{wheel['filename']} does not match its recorded SHA-256")
    runtime_wheels, _ = ensure_wheels(root, HERE)
    identity = hashlib.sha256(lock.read_bytes() + built_lock.read_bytes()).hexdigest()
    environment = workspace / "envs" / identity[:16]
    stamp = environment / ".hachi-lock-sha256"
    if environment.exists():
        if not stamp.exists() or stamp.read_text().strip() != identity:
            parser.error(f"existing unrecognized environment is untouched: {environment}")
    else:
        try:
            subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
            subprocess.run(
                [
                    str(environment / "bin/python"), "-m", "pip", "--isolated", "install",
                    "--disable-pip-version-check", "--no-cache-dir", "--no-index", "--no-deps",
                    "--find-links", str(runtime_wheels), "--find-links", str(built),
                    "--require-hashes", "-r", str(lock), "-r", str(built_lock),
                ],
                check=True,
            )  # fmt: skip
            subprocess.run(
                [str(environment / "bin/python"), "-m", "pip", "--isolated", "check"], check=True
            )
            stamp.write_text(identity + "\n")
        except BaseException:
            # Only the environment created by this invocation is removable.
            shutil.rmtree(environment, ignore_errors=True)
            raise
    subprocess.run(
        [str(environment / "bin/python"), "-m", "pip", "--isolated", "check"], check=True
    )
    frozen = subprocess.check_output(
        [str(environment / "bin/python"), "-m", "pip", "--isolated", "freeze", "--all"], text=True
    )
    print(json.dumps({
        "owner": args.owner,
        "python": str(environment / "bin/python"),
        "environment_sha256": identity,
        "requirements_lock_sha256": digest(lock),
        "built_lock_sha256": digest(built_lock),
        "built_from": str(built),
        "installed": sorted(frozen.split()),
    }, indent=2))  # fmt: skip


if __name__ == "__main__":
    main()
