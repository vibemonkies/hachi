"""Convert a pip --dry-run --ignore-installed --report into an ARM64 wheel lock."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("report", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
report = json.loads(args.report.read_text())
assert report["environment"]["platform_machine"] == "aarch64"
assert report["environment"]["python_version"] == "3.12"
locked = []
for item in report["install"]:
    info = item["download_info"]
    url = info["url"]
    assert urlparse(url).path.endswith(".whl"), url
    assert urlparse(url).hostname in ("files.pythonhosted.org", "download-r2.pytorch.org", "pypi.nvidia.com")
    locked.append({"name": item["metadata"]["name"], "version": item["metadata"]["version"],
                   "url": url, "sha256": info["archive_info"]["hashes"]["sha256"]})
locked.sort(key=lambda item: item["name"].lower())
args.destination.mkdir(parents=True, exist_ok=True)
(args.destination / "wheels.json").write_text(json.dumps(locked, indent=2) + "\n")
(args.destination / "requirements.lock").write_text(
    "# CPython 3.12 / Linux aarch64 / bundled CUDA 12.9. Generated from runtime.in.\n"
    + "".join(f'{item["name"]}=={item["version"]} --hash=sha256:{item["sha256"]}\n' for item in locked)
)
