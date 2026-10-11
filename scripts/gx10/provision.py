"""Create one owner's checkout and hash-verified environment without touching existing installs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from supervise import OWNERS


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("owner", choices=OWNERS)
    parser.add_argument("--source", required=True, help="Git bundle, local repo, or authenticated Git URL")
    parser.add_argument("--branch", default="main", help="named source branch; bundles may not contain HEAD")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "aarch64" or sys.version_info[:2] != (3, 12):
        parser.error("this lock requires CPython 3.12 on Linux aarch64")
    os.umask(0o077)
    source = Path(__file__).resolve().parents[2]
    lock = source / "infra/gx10/requirements.lock"
    lock_id = digest(lock)
    root = Path(os.environ["HACHI_HOME"]).resolve()
    owner = root / "workspaces" / args.owner
    owner.mkdir(parents=True, exist_ok=True)
    checkout = owner / "hachi"
    if not checkout.exists():
        subprocess.run(["git", "clone", "--branch", args.branch, "--", args.source, str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "remote", "set-url", "origin",
                        "https://github.com/vibemonkies/hachi.git"], check=True)
    elif not (checkout / ".git").exists():
        parser.error(f"existing path is not a checkout; untouched: {checkout}")
    else:
        origin = subprocess.check_output(["git", "-C", str(checkout), "remote", "get-url", "origin"], text=True).strip()
        if origin not in ("https://github.com/vibemonkies/hachi.git", "git@github.com:vibemonkies/hachi.git"):
            parser.error(f"existing checkout has an unexpected origin; untouched: {checkout}")
    # Never pull, switch, reset, or copy over an existing contributor checkout.
    for directory in (owner / "cache", owner / "state", root / "runs" / args.owner):
        directory.mkdir(parents=True, exist_ok=True)
    database = owner / "state/metadata.sqlite3"
    if not database.exists():
        # Placeholder only. Backend owns migrations and the actual schema.
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA user_version = 0")

    wheels = root / "infra/wheels" / lock_id
    wheels.mkdir(parents=True, exist_ok=True)
    for item in json.loads((source / "infra/gx10/wheels.json").read_text()):
        target = wheels / unquote(Path(urlparse(item["url"]).path).name)
        if target.exists() and digest(target) == item["sha256"]:
            continue
        temporary = target.with_suffix(".partial")
        print(f'Downloading {item["name"]}=={item["version"]}', flush=True)
        try:
            # PyTorch's CDN rejects Python urllib's default user agent (403).
            request = Request(item["url"], headers={"User-Agent": "hachi-gx10/1.0"})
            with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            if digest(temporary) != item["sha256"]:
                raise RuntimeError(f"wheel checksum failed: {target.name}")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    environment = owner / "envs" / lock_id[:16]
    stamp = environment / ".hachi-lock-sha256"
    if environment.exists():
        if not stamp.exists() or stamp.read_text().strip() != lock_id:
            parser.error(f"existing unrecognized environment is untouched: {environment}")
    else:
        environment.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
            subprocess.run([
                str(environment / "bin/python"), "-m", "pip", "--isolated", "install",
                "--disable-pip-version-check", "--no-cache-dir", "--no-index", "--no-deps",
                "--find-links", str(wheels), "--require-hashes", "-r", str(lock),
            ], check=True)
            subprocess.run([str(environment / "bin/python"), "-m", "pip", "--isolated", "check"], check=True)
            stamp.write_text(lock_id + "\n")
        except BaseException:
            # Only the new environment created by this invocation is removable.
            shutil.rmtree(environment)
            raise
    subprocess.run([str(environment / "bin/python"), "-m", "pip", "--isolated", "check"], check=True)
    # Print the identity; do not alter shell startup or global PATH.
    print(json.dumps({"owner": args.owner, "checkout": str(checkout),
                      "python": str(environment / "bin/python"), "lock_sha256": lock_id,
                      "database": str(database)}, indent=2))


if __name__ == "__main__":
    main()
