"""Recompute sampled snapshot values straight from the raw archive, by a separate route.

This shares no parsing, clock or binning code with the pipeline: members are loaded whole
with `json`, times go through `datetime`/`zoneinfo` directly, and sleep is painted onto 30 s
ticks instead of carving intervals. Only the documented rules are repeated (UTC intraday
timestamps, local sleep logs, contract bounds, dropping conflicting duplicates and quarantined
logs).
"""

import hashlib
import itertools
import json
import zipfile
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow.compute as pc
import pyarrow.parquet as pq

from .archive import open_archive
from .config import Admission
from .snapshot import load_manifest

SUBJECTS = 4
BINS_PER_CHECK = 40
TICK = timedelta(seconds=30)
LEVELS = {
    ("stages", "deep"): "sleep_asleep_deep",
    ("stages", "light"): "sleep_asleep_core",
    ("stages", "rem"): "sleep_asleep_rem",
    ("stages", "wake"): "sleep_awake",
    ("classic", "asleep"): "sleep_asleep_unspecified",
    ("classic", "awake"): "sleep_awake",
}


def _rank(seed: str, key: str) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()


def _load(handle: zipfile.ZipFile, name: str) -> Any:
    if name not in handle.NameToInfo:
        return []  # a missing member contributes nothing, as in the pipeline
    with handle.open(name) as f:
        return json.loads(f.read())


def _utc(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def _minute_series(handle, name: str, scale: float) -> dict[datetime, float]:
    values: dict[datetime, set[float]] = defaultdict(set)
    for row in _load(handle, name):
        values[_utc(row["dateTime"])].add(float(row["value"]) * scale)
    return {t: next(iter(v)) for t, v in values.items() if len(v) == 1}


def _heart_rate(handle, name: str) -> dict[datetime, int]:
    values: dict[datetime, set[int]] = defaultdict(set)
    for row in _load(handle, name):
        values[_utc(row["dateTime"])].add(row["value"]["bpm"])
    # Contract bounds for heart rate: 1-300 bpm.
    return {t: next(iter(v)) for t, v in values.items() if len(v) == 1 and 1 <= min(v) <= 300}


def _sleep_ticks(handle, name: str, zone: ZoneInfo) -> dict[str, dict[datetime, int]]:
    """Seconds per (metric, UTC 30 s tick start) from the logs the pipeline keeps."""
    logs: dict[int, list[dict]] = defaultdict(list)
    for log in _load(handle, name):
        logs[log["logId"]].append(log)
    kept = []
    for versions in logs.values():
        for v in versions:
            for stats in v["levels"]["summary"].values():
                stats.pop("thirtyDayAvgMinutes", None)
        if len({json.dumps(v, sort_keys=True) for v in versions}) > 1:
            continue
        log = versions[0]
        start = datetime.fromisoformat(log["startTime"].replace("T", " "))
        end = datetime.fromisoformat(log["endTime"].replace("T", " "))
        if start.replace(tzinfo=zone).utcoffset() != end.replace(tzinfo=zone).utcoffset():
            continue
        offset = start.replace(tzinfo=zone).utcoffset()
        kept.append((start - offset, end - offset, log))
    kept.sort(key=lambda k: k[0])
    clash = set()
    for (_a0, a1, a), (b0, _, b) in itertools.pairwise(kept):
        if b0 < a1:
            clash |= {a["logId"], b["logId"]}
    seconds: dict[str, dict[datetime, int]] = defaultdict(dict)
    for start, end, log in kept:
        if log["logId"] in clash:
            continue
        local0 = datetime.fromisoformat(log["startTime"].replace("T", " "))
        paint: dict[datetime, str] = {}
        for layer in ("data", "shortData"):
            for seg in log["levels"].get(layer, []):
                t = start + (datetime.fromisoformat(seg["dateTime"].replace("T", " ")) - local0)
                for k in range(seg["seconds"] // 30):
                    paint[t + k * TICK] = seg["level"]
        for t, level in paint.items():
            metric = LEVELS.get((log["type"], level))
            if metric:
                seconds[metric][t.replace(tzinfo=UTC)] = 30
        # In-bed time is Fitbit's duration, spread evenly over the log's wall-clock span.
        weight = 30 * (log["duration"] / 1000) / (end - start).total_seconds()
        t = start
        while t < end:
            seconds["sleep_in_bed"][t.replace(tzinfo=UTC)] = weight
            t += TICK
    return seconds


def reconcile(snapshot: Path, archive_path: Path, admission: Admission) -> dict[str, Any]:
    manifest = load_manifest(snapshot)
    seed = manifest["dataset_snapshot"]["snapshot_sha256"]
    zone_name = manifest["config"]["content"]["local_timezone"]
    zone = ZoneInfo(zone_name)
    subjects = sorted(manifest["subjects"], key=lambda s: _rank(seed, s))[:SUBJECTS]
    hourly = pq.read_table(snapshot / "aggregates_hourly.parquet")
    daily = pq.read_table(snapshot / "aggregates_daily.parquet")
    tally: Counter = Counter()
    mismatches: list[dict[str, Any]] = []

    def check(label: str, stored: float | None, expected: float | None) -> None:
        tally[(label, "checked")] += 1
        if stored is None or expected is None:
            ok = stored is None and expected is None
        else:
            ok = abs(stored - expected) <= 1e-6 * max(1.0, abs(expected))
        if not ok:
            mismatches.append({"check": label, "stored": stored, "expected": expected})

    def ordered(series: dict) -> tuple[list, list]:
        keys = sorted(series)
        return keys, [series[k] for k in keys]

    def window(series: tuple[list, list], a: datetime, b: datetime) -> list:
        keys, values = series
        return values[bisect_left(keys, a) : bisect_left(keys, b)]

    def sample(table, subject, metric, aggregation):
        rows = table.filter(
            (pc.field("subject_id") == subject)
            & (pc.field("metric") == metric)
            & (pc.field("aggregation") == aggregation)
            & pc.field("value").is_valid()
        ).to_pylist()
        rows.sort(key=lambda r: _rank(seed, f"{metric}{r['interval_start_utc']}"))
        return rows[:BINS_PER_CHECK]

    with open_archive(archive_path, admission) as verified:
        path = verified.path
    with zipfile.ZipFile(path) as handle:
        names = set(handle.namelist())
        for subject in subjects:
            steps = ordered(_minute_series(handle, f"{subject}/fitbit/steps.json", 1.0))
            for resolution, table in (("hour", hourly), ("day", daily)):
                for row in sample(table, subject, "steps", "sum"):
                    a, b = row["interval_start_utc"], row["interval_end_utc"]
                    inside = window(steps, a, b)
                    check(f"{resolution}:steps:sum", row["value"], sum(inside))
                    check(f"{resolution}:steps:count", row["observed_count"], len(inside))
            del steps
            if f"{subject}/fitbit/resting_heart_rate.json" in names:
                rhr = {}
                for item in _load(handle, f"{subject}/fitbit/resting_heart_rate.json"):
                    if item["value"]["value"] > 0:
                        rhr.setdefault(date.fromisoformat(item["dateTime"][:10]), set()).add(
                            item["value"]["value"]
                        )
                for row in sample(daily, subject, "resting_heart_rate_vendor", "mean"):
                    values = rhr.get(row["local_date"], set())
                    check(
                        "day:resting_heart_rate_vendor:mean",
                        row["value"],
                        next(iter(values)) if len(values) == 1 else None,
                    )
            ticks = {
                m: ordered(v)
                for m, v in _sleep_ticks(handle, f"{subject}/fitbit/sleep.json", zone).items()
            }
            for metric in ("sleep_asleep_deep", "sleep_in_bed", "sleep_awake"):
                for resolution, table in (("hour", hourly), ("day", daily)):
                    for row in sample(table, subject, metric, "sum"):
                        a, b = row["interval_start_utc"], row["interval_end_utc"]
                        total = sum(window(ticks.get(metric, ([], [])), a, b))
                        check(f"{resolution}:{metric}:sum", row["value"], total)
            del ticks
            heart = ordered(_heart_rate(handle, f"{subject}/fitbit/heart_rate.json"))
            for resolution, table in (("hour", hourly), ("day", daily)):
                for aggregation in ("mean", "max"):
                    for row in sample(table, subject, "heart_rate", aggregation):
                        a, b = row["interval_start_utc"], row["interval_end_utc"]
                        inside = window(heart, a, b)
                        expected = (
                            sum(inside) / len(inside) if aggregation == "mean" else max(inside)
                        )
                        check(f"{resolution}:heart_rate:{aggregation}", row["value"], expected)
            del heart
    checks = sorted({label for label, _ in tally})
    return {
        "snapshot_id": manifest["snapshot_id"],
        "subjects_sampled": len(subjects),
        "checks": {label: tally[(label, "checked")] for label in checks},
        "mismatches": len(mismatches),
        "mismatch_examples": mismatches[:10],
        "ok": not mismatches and bool(tally),
    }
