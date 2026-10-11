"""Generate a labelled synthetic replay with staggered target windows, never real data."""

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from hachi.contracts.api import ReportJob
from hachi.storage import private_directory

REPO = Path(__file__).resolve().parents[2]


def gapped_target_job() -> ReportJob:
    """Both series are contiguous as required, but their target windows have gaps.

    HR covers hours 1-4 after cutoff; steps covers hours 10-12. The common UTC
    scale must retain the missing initial hour and the separation between windows.
    No unsupported per-point abstention or noncontiguous series is invented.
    """
    job = json.loads((REPO / "contracts/fixtures/ReportJob/completed.json").read_bytes())
    result = job["result"]
    cutoff = datetime.fromisoformat(result["as_of"].replace("Z", "+00:00"))
    for series, hours in zip(result["forecast"]["series"], ((1, 2, 3), (10, 11)), strict=True):
        points = series["points"][: len(hours)]
        for point, hour in zip(points, hours, strict=True):
            start = cutoff + timedelta(hours=hour)
            point.update(
                interval_start_utc=start.isoformat(),
                interval_end_utc=(start + timedelta(hours=1)).isoformat(),
                lower=None,
                upper=None,
            )
        series.update(points=points, interval_calibration="none", nominal_coverage=None)
    result["warnings"] = []
    return ReportJob.model_validate_json(json.dumps(job))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.destination.resolve().is_relative_to(REPO):
        parser.error("Synthetic rehearsal responses still belong outside Git")
    os.umask(0o077)
    private_directory(args.destination.parent)
    with args.destination.open("x") as stream:
        stream.write(gapped_target_job().model_dump_json(indent=2))
    print(json.dumps({"generated": True, "data_mode": "synthetic", "target_points": 5}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
