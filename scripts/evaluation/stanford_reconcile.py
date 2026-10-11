#!/usr/bin/env python3
"""Independent native-CSV median/quiet-coverage checks; print aggregate results only."""

import argparse
import csv
import io
import json
import math
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median


def check(archive, packet):
    checked = 0
    with zipfile.ZipFile(archive) as z:
        for directory in sorted((packet / "participants").iterdir()):
            primary = json.loads((directory / "both.json").read_bytes())["controls"]
            # Exercise both a measurable and an unavailable night when each is present.
            selected = {}
            for row in primary:
                selected.setdefault(row["feature"]["night"]["rhr_bpm"] is None, row)
            days = {row["feature"]["night"]["local_date"] for row in selected.values()}
            streams = {}
            for suffix, value_column in (("hr", "heartrate"), ("steps", "steps")):
                points = defaultdict(set)
                name = f"COVID-19-Wearables/{directory.name}_{suffix}.csv"
                with z.open(name) as stream:
                    for row in csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig")):
                        if row["user"] != directory.name:
                            continue
                        try:
                            at = datetime.fromisoformat(row["datetime"])
                            value = float(row[value_column])
                        except (ValueError, TypeError):
                            continue
                        if at.tzinfo is not None or at.date().isoformat() not in days:
                            continue
                        if not math.isfinite(value):
                            continue
                        if suffix == "hr" and not 1 <= value <= 300:
                            continue
                        if suffix == "steps" and (value < 0 or at.second or at.microsecond):
                            continue
                        points[at].add(value)
                streams[suffix] = {
                    at: next(iter(values)) for at, values in points.items() if len(values) == 1
                }
            for edge in ("both", "start", "end"):
                rows = json.loads((directory / f"{edge}.json").read_bytes())["controls"]
                for row in rows:
                    feature = row["feature"]
                    day = feature["night"]["local_date"]
                    if day not in days:
                        continue
                    start = datetime.fromisoformat(day)
                    finish = start + timedelta(hours=7)
                    hr_minutes = defaultdict(list)
                    for at, value in streams["hr"].items():
                        if start <= at < finish:
                            hr_minutes[at.replace(second=0, microsecond=0)].append(value)
                    quiet_values = []
                    for at, values in hr_minutes.items():
                        keys = (
                            (at, at + timedelta(minutes=1))
                            if edge == "both"
                            else (at,)
                            if edge == "start"
                            else (at + timedelta(minutes=1),)
                        )
                        if len(values) >= feature["policy"]["min_hr_samples_per_minute"] and all(
                            streams["steps"].get(key) == 0 for key in keys
                        ):
                            quiet_values.append(median(values))
                    expected = (
                        median(quiet_values)
                        if len(quiet_values) >= feature["policy"]["min_rest_minutes"]
                        else None
                    )
                    if (
                        expected != feature["night"]["rhr_bpm"]
                        or len(quiet_values) != feature["night"]["observed_zero_step_minutes"]
                    ):
                        raise ValueError("native rest reconciliation differs")
                    checked += 2
    return {"native_reconciliation_checks": checked, "mismatches": 0}


if __name__ == "__main__":
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.archive, args.packet)))
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
