"""Run a pinned upstream comparator on generated CSVs in new isolated directories."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

REVISION = "99b3bd7937e72d42c2670c7a259d9f9f8728dc06"
SOURCE_SHA256 = "198487887166afa2c7f884d832c2c837d41f2973b684da0303ec5aa8ad54a999"
SHIM = """import sys, runpy, matplotlib
matplotlib.use('Agg')
import matplotlib.style as style
style.library['seaborn-dark-palette'] = style.library['seaborn-v0_8-dark-palette']
source=sys.argv[1]
sys.argv=sys.argv[1:]
runpy.run_path(source,run_name='__main__')
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = args.upstream.resolve()
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        parser.error("upstream source must match the pinned reviewed revision")
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    base = date(2026, 10, 1)
    cases = {
        "complete": {**dict.fromkeys(range(7), 60), 7: 70, 8: 70},
        "gap_full": {**dict.fromkeys(range(7), 60), 7: 70, 9: 70, 10: 60},
        "gap_prefix": {**dict.fromkeys(range(7), 60), 7: 70},
    }
    outputs = {}
    for name, days in cases.items():
        path = root / name
        path.mkdir(mode=0o700)
        csv = "Datetime,Heartrate,unused,Steps\n" + "".join(
            f"{base + timedelta(days=day)} {hour:02}:00:00,{value},0,0\n"
            for day, value in sorted(days.items())
            for hour in range(7)
        )
        (path / "generated.csv").write_text(csv)
        environment = {
            **os.environ,
            "MPLCONFIGDIR": str(path / "plot-cache"),
            "XDG_CACHE_HOME": str(path / "cache"),
        }
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                SHIM,
                str(source),
                "--device=Fitbit",
                "--restinghr=generated.csv",
            ],
            cwd=path,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        (path / "output.log").write_text(result.stdout + result.stderr)
        signals = json.loads((path / "NS-signals.json").read_text())["nightsignal"]
        outputs[name] = {point["date"].split()[0]: int(point["val"]) for point in signals}
    gap = str(base + timedelta(days=8))
    assert outputs["complete"][gap] == 2
    assert outputs["gap_full"][gap] == 2 and gap not in outputs["gap_prefix"]
    import matplotlib
    import numpy
    import pandas

    receipt = {
        "data_mode": "synthetic",
        "upstream_revision": REVISION,
        "upstream_source_sha256": SOURCE_SHA256,
        "model_id": "upstream-nightsignal-99b3bd7-plotcompat",
        "scope": "Fitbit input path; generated records only; no real cohort or alert burden",
        "compatibility": (
            "current locked numpy/pandas/matplotlib; palette alias and Agg only; "
            "upstream source unchanged"
        ),
        "python": sys.version.split()[0],
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
        "matplotlib": matplotlib.__version__,
        "plot_shim_sha256": hashlib.sha256(SHIM.encode()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "complete_two_elevated_nights_red": True,
        "future_adjacent_night_creates_earlier_imputed_red": True,
        "counts": {
            name: {
                "nights": len(points),
                "red": sum(value == 2 for value in points.values()),
                "yellow": sum(value == 1 for value in points.values()),
            }
            for name, points in outputs.items()
        },
    }
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    (root / "synthetic-summary.json").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
