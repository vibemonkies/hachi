"""Capture sanitized host identity without reading credentials or process arguments."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()


def command(*parts):
    result = subprocess.run(parts, text=True, capture_output=True)
    return {"exit_code": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def config_hash(path):
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


usage = shutil.disk_usage(Path.home())
evidence = {
    "captured_at": datetime.now(timezone.utc).isoformat(),
    "hostname": platform.node(), "architecture": platform.machine(), "kernel": platform.release(),
    "os_release": Path("/etc/os-release").read_text(), "system_python": sys.version,
    "gpu": command("nvidia-smi", "--query-gpu=uuid,name,driver_version", "--format=csv,noheader"),
    "installed_toolkit": command(shutil.which("nvcc") or "/usr/local/cuda/bin/nvcc", "--version"),
    "memory": command("free", "-b"),
    "disk": {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free},
    "compute_processes": command("nvidia-smi", "--query-compute-apps=pid,process_name", "--format=csv,noheader"),
    "existing_venv_config_sha256": config_hash(Path.home() / "venv/pyvenv.cfg"),
    "existing_environment_policy": "~/venv and ~/unsloth remain untouched; no system or service changes",
}
args.output.write_text(json.dumps(evidence, indent=2) + "\n")
print(json.dumps(evidence, indent=2))
