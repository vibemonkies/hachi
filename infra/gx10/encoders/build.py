"""Build the #11 encoder wheels (causal-conv1d, mamba-ssm, momentfm) from pinned, verified sources.

Runs on the GX10 with the system CPython 3.12, CPU only (no GPU lock needed). Everything it
creates lives under the owner's workspace; the machine CUDA 13.0 toolkit, existing environments
and the shared runtime lock are never read for building or changed. Every download is checked
against a SHA-256 (CUDA redist, sdists, wheels) or an exact Git commit before use.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
OWNERS = ("ezzy1630", "justin06lee", "CoffeeCoder1015")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(url, target, sha256):
    if target.exists() and digest(target) == sha256:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    print(f"Downloading {url}", flush=True)
    try:
        request = Request(url, headers={"User-Agent": "hachi-gx10/1.0"})
        with urlopen(request, timeout=120) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
        if digest(partial) != sha256:
            raise RuntimeError(f"checksum failed: {target.name}")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def safe_extract(archive, destination):
    """Extract a tar archive refusing absolute paths, parent traversal and links outside it."""
    with tarfile.open(archive) as tar:
        tar.extractall(destination, filter="data")


def ensure_toolchain(sources, workspace):
    cuda = sources["cuda_toolkit"]
    identity = hashlib.sha256(json.dumps(cuda["components"], sort_keys=True).encode()).hexdigest()
    prefix = workspace / "toolchains" / f"cuda-{cuda['release']}-{cuda['platform']}"
    stamp = prefix / ".hachi-components-sha256"
    if stamp.exists() and stamp.read_text().strip() == identity:
        return prefix, identity
    if prefix.exists():
        raise SystemExit(f"existing unrecognized toolchain is untouched: {prefix}")
    downloads = workspace / "toolchains" / "downloads"
    staging = prefix.with_name(prefix.name + ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        for component in cuda["components"]:
            archive = fetch(
                cuda["base_url"] + component["path"],
                downloads / Path(component["path"]).name,
                component["sha256"],
            )
            unpacked = staging / ".unpack"
            safe_extract(archive, unpacked)
            (top,) = list(unpacked.iterdir())
            shutil.copytree(top, staging, dirs_exist_ok=True, symlinks=True)
            shutil.rmtree(unpacked)
        (staging / "lib64").symlink_to("lib")
        stamp_tmp = staging / ".hachi-components-sha256"
        stamp_tmp.write_text(identity + "\n")
        staging.replace(prefix)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return prefix, identity


def ensure_wheels(root, lock_dir):
    lock_id = digest(lock_dir / "requirements.lock")
    wheels = root / "infra/wheels" / lock_id
    for item in json.loads((lock_dir / "wheels.json").read_text()):
        fetch(item["url"], wheels / unquote(Path(urlparse(item["url"]).path).name), item["sha256"])
    return wheels, lock_id


def ensure_builder(workspace, runtime, build):
    (runtime_wheels, runtime_id), (build_wheels, build_id) = runtime, build
    builder_id = hashlib.sha256(f"{runtime_id}:{build_id}".encode()).hexdigest()[:16]
    venv = workspace / "build-venvs" / builder_id
    stamp = venv / ".hachi-builder"
    if stamp.exists():
        return venv
    if venv.exists():
        raise SystemExit(f"existing unrecognized builder is untouched: {venv}")
    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        subprocess.run(
            [
                str(venv / "bin/python"),
                "-m",
                "pip",
                "--isolated",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "--no-index",
                "--no-deps",
                "--find-links",
                str(runtime_wheels),
                "--find-links",
                str(build_wheels),
                "--require-hashes",
                "-r",
                str(HERE / "requirements.lock"),
                "-r",
                str(HERE / "build/requirements.lock"),
            ],
            check=True,
        )
        stamp.write_text(f"{runtime_id}\n{build_id}\n")
    except BaseException:
        shutil.rmtree(venv, ignore_errors=True)
        raise
    return venv


def build_wheel(builder, source, output, env, log):
    started = time.monotonic()
    with log.open("w") as stream:
        result = subprocess.run(
            [
                str(builder / "bin/python"),
                "-m",
                "pip",
                "--isolated",
                "wheel",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "--no-index",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(output),
                "--verbose",
                str(source),
            ],
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
    seconds = round(time.monotonic() - started, 1)
    if result.returncode:
        raise SystemExit(f"build failed after {seconds}s (exit {result.returncode}); see {log}")
    return seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True, choices=OWNERS)
    parser.add_argument("--variant", required=True, help="gencode variant name from sources.json")
    parser.add_argument("--only", action="append", help="build only these package names")
    parser.add_argument("--max-jobs", type=int, default=16)
    args = parser.parse_args()
    if (
        platform.system() != "Linux"
        or platform.machine() != "aarch64"
        or sys.version_info[:2] != (3, 12)
    ):
        parser.error("this build requires CPython 3.12 on Linux aarch64")
    os.umask(0o077)
    sources = json.loads((HERE / "sources.json").read_text())
    flags = sources["gencode_variants"].get(args.variant)
    if flags is None:
        parser.error(f"unknown variant; choose from {sorted(sources['gencode_variants'])}")
    root = Path(os.environ.get("HACHI_HOME", Path.home() / "hachi")).resolve()
    workspace = root / "workspaces" / args.owner
    if not workspace.is_dir():
        parser.error(f"owner workspace is not provisioned: {workspace}")

    prefix, toolchain_id = ensure_toolchain(sources, workspace)
    runtime = ensure_wheels(root, HERE)
    build = ensure_wheels(root, HERE / "build")
    builder = ensure_builder(workspace, runtime, build)
    nvcc = subprocess.check_output([str(prefix / "bin/nvcc"), "--version"], text=True)
    arches = subprocess.check_output(
        [str(prefix / "bin/nvcc"), "--list-gpu-arch"], text=True
    ).split()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = workspace / "built-wheels" / f"{args.variant}-{stamp}"
    output.mkdir(parents=True)
    work = output / "work"
    work.mkdir()
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHONPATH", "PYTHONHOME", "PIP_CONFIG_FILE")
    }
    env.update(
        {
            "CUDA_HOME": str(prefix),
            "PATH": f"{prefix / 'bin'}:{builder / 'bin'}:/usr/bin:/bin",
            "MAX_JOBS": str(args.max_jobs),
            "TMPDIR": str(work),
        }
    )
    env.pop("NVCC_APPEND_FLAGS", None)
    if flags:
        env["NVCC_APPEND_FLAGS"] = flags
    wanted = set(args.only or [])
    records = []
    for item in sources["sdists"]:
        if wanted and item["name"] not in wanted:
            continue
        sdist = fetch(
            item["url"],
            workspace / "toolchains/downloads" / Path(urlparse(item["url"]).path).name,
            item["sha256"],
        )
        before = set(output.glob("*.whl"))
        seconds = build_wheel(
            builder,
            sdist,
            output,
            {**env, item["force_build_env"]: "TRUE"},
            output / f"{item['name']}.log",
        )
        (wheel,) = set(output.glob("*.whl")) - before
        records.append(
            {
                "name": item["name"],
                "version": item["version"],
                "filename": wheel.name,
                "sha256": digest(wheel),
                "source": {"url": item["url"], "sha256": item["sha256"]},
                "build_seconds": seconds,
            }
        )
    for item in sources["git"]:
        if wanted and item["name"] not in wanted:
            continue
        checkout = work / item["name"]
        subprocess.run(
            ["git", "clone", "--quiet", "--no-checkout", item["repository"], str(checkout)],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(checkout), "checkout", "--quiet", "--detach", item["commit"]],
            check=True,
        )
        head = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
        ).strip()
        if head != item["commit"]:
            raise SystemExit(f"{item['name']} checkout is {head}, expected {item['commit']}")
        before = set(output.glob("*.whl"))
        seconds = build_wheel(builder, checkout, output, env, output / f"{item['name']}.log")
        (wheel,) = set(output.glob("*.whl")) - before
        records.append(
            {
                "name": item["name"],
                "version": item["version"],
                "filename": wheel.name,
                "sha256": digest(wheel),
                "source": {"repository": item["repository"], "commit": item["commit"]},
                "build_seconds": seconds,
            }
        )
    shutil.rmtree(work)
    receipt = {
        "built_at_utc": stamp,
        "variant": args.variant,
        "nvcc_append_flags": flags,
        "toolchain": {
            "release": sources["cuda_toolkit"]["release"],
            "components_sha256": toolchain_id,
            "nvcc_version": nvcc.strip().splitlines()[-1],
            "gpu_arches": arches,
        },
        "runtime_lock_sha256": runtime[1],
        "build_lock_sha256": build[1],
        "host": {
            "machine": platform.machine(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
        "wheels": records,
    }
    (output / "built-wheels.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (output / "built.lock").write_text(
        f"# Wheels built by build.py ({args.variant}); hashes are of these exact local builds.\n"
        + "".join(f"{r['name']}=={r['version']} --hash=sha256:{r['sha256']}\n" for r in records)
    )
    print(json.dumps({"output": str(output), **receipt}, indent=2))


if __name__ == "__main__":
    main()
