"""A small synthetic archive in PMData's layout, with the edge cases the pipeline must handle.

Every value is generated here; nothing is copied from the real dataset.
"""

import csv
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from hachi.data.pmdata.archive import sha256_file
from hachi.data.pmdata.config import Admission, load_config


def _minutes(start: datetime, count: int) -> list[datetime]:
    return [start + timedelta(minutes=i) for i in range(count)]


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _local(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000")


def _sleep_log(log_id, start, segments, *, kind="stages", main=True, short=(), avg=30):
    """segments: [(level, seconds)] contiguous from start (local wall time)."""
    data, t = [], start
    for level, seconds in segments:
        data.append({"dateTime": _local(t), "level": level, "seconds": seconds})
        t += timedelta(seconds=seconds)
    end = t
    totals: dict[str, int] = {}
    for level, seconds in segments:
        totals[level] = totals.get(level, 0) + seconds
    short_rows = []
    for offset, seconds in short:
        moment = start + timedelta(seconds=offset)
        short_rows.append({"dateTime": _local(moment), "level": "wake", "seconds": seconds})
        # Fitbit's summary counts short wakes as wake, taken out of the surrounding stage.
        covering = next(
            (
                lv
                for (lv, s), row in zip(segments, data, strict=True)
                if datetime.fromisoformat(row["dateTime"])
                <= moment
                < datetime.fromisoformat(row["dateTime"]) + timedelta(seconds=s)
            )
        )
        totals[covering] -= seconds
        totals["wake"] = totals.get("wake", 0) + seconds
    levels = (
        ("deep", "light", "rem", "wake") if kind == "stages" else ("asleep", "restless", "awake")
    )
    summary = {
        lv: {"count": 1, "minutes": totals.get(lv, 0) // 60}
        | ({"thirtyDayAvgMinutes": avg} if kind == "stages" else {})
        for lv in levels
    }
    duration = int((end - start).total_seconds())
    asleep = sum(totals.get(lv, 0) for lv in ("deep", "light", "rem", "asleep")) // 60
    log = {
        "logId": log_id,
        "dateOfSleep": end.strftime("%Y-%m-%d"),
        "startTime": _local(start).replace("T", " ")[:19],
        "endTime": _local(end),
        "duration": duration * 1000,
        "minutesToFallAsleep": 0,
        "minutesAsleep": asleep,
        "minutesAwake": duration // 60 - asleep,
        "minutesAfterWakeup": 0,
        "timeInBed": duration // 60,
        "efficiency": 90,
        "type": kind,
        "infoCode": 0,
        "levels": {"summary": summary, "data": data}
        | ({"shortData": short_rows} if kind == "stages" else {}),
        "mainSleep": main,
    }
    return log


def _csv(header: list[str], rows: list[list]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode()


def build_members() -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    j = lambda rows: json.dumps(rows).encode()  # noqa: E731

    # p01: 2020-03-27 18:00 UTC to 2020-03-30 12:00 UTC, across the Oslo DST change.
    t0 = datetime(2020, 3, 27, 18, 0)
    minutes = _minutes(t0, 66 * 60)
    asleep_utc = [  # the kept sleep logs below, in UTC
        (datetime(2020, 3, 27, 22, 0), datetime(2020, 3, 28, 1, 10)),
        (datetime(2020, 3, 29, 20, 0), datetime(2020, 3, 29, 21, 45)),
    ]
    awake = lambda m: not any(a <= m < b for a, b in asleep_utc)  # noqa: E731
    hr = [
        {
            "dateTime": _stamp(m + timedelta(seconds=s)),
            "value": {"bpm": (72 if awake(m) else 52) + s // 30, "confidence": 2},
        }
        for m in minutes
        if m.hour != 13  # 13:00-14:00 UTC: watch off
        for s in (0, 30)
    ]
    hr.append(dict(hr[10]))  # identical duplicate
    hr.append({"dateTime": hr[20]["dateTime"], "value": {"bpm": 150, "confidence": 1}})  # conflict
    hr.append({"dateTime": "2020-03-28 13:30:05", "value": {"bpm": 400, "confidence": 0}})
    members["p01/fitbit/heart_rate.json"] = j(hr)

    steps = []
    for m in minutes:
        if m.hour == 13 or (m.hour == 3 and m.minute % 2):  # absent rows stay unknown
            continue
        steps.append({"dateTime": _stamp(m), "value": str(12 if awake(m) and m.minute < 20 else 0)})
    steps.append(dict(steps[5]))
    steps.append({"dateTime": steps[7]["dateTime"], "value": "99"})
    members["p01/fitbit/steps.json"] = j(steps)
    members["p01/fitbit/distance.json"] = j(
        [{"dateTime": r["dateTime"], "value": str(int(r["value"]) * 70)} for r in steps[:-2]]
    )
    members["p01/fitbit/calories.json"] = j(
        [{"dateTime": _stamp(m), "value": "1.2"} for m in minutes]
    )
    members["p01/fitbit/resting_heart_rate.json"] = j(
        [
            {
                "dateTime": f"{d} 00:00:00",
                "value": {
                    # Fitbit's "no estimate" row: null date, zero value and error.
                    "date": date.fromisoformat(d).strftime("%m/%d/%y") if v else None,
                    "value": v,
                    "error": 6.5 if v else 0.0,
                },
            }
            for d, v in (("2020-03-27", 0.0), ("2020-03-28", 51.5), ("2020-03-29", 52.25))
        ]
    )

    stages = [("light", 1800), ("deep", 3600), ("rem", 1800), ("light", 3600), ("wake", 600)]
    good = _sleep_log(1001, datetime(2020, 3, 27, 23, 0), stages, short=[(600, 60), (5460, 90)])
    members["p01/fitbit/sleep.json"] = j(
        [
            good,
            _sleep_log(
                1001, datetime(2020, 3, 27, 23, 0), stages, short=[(600, 60), (5460, 90)], avg=31
            ),
            # DST night: 01:00 to 05:00 local wall time crosses the 02:00 spring-forward.
            _sleep_log(1002, datetime(2020, 3, 29, 1, 0), [("light", 7200), ("deep", 7200)]),
            # Classic log on the following evening (CEST, UTC+2).
            _sleep_log(
                1003,
                datetime(2020, 3, 29, 22, 0),
                [("asleep", 3600), ("restless", 600), ("awake", 300), ("asleep", 1800)],
                kind="classic",
            ),
            # Two overlapping naps: both quarantined.
            _sleep_log(
                1004, datetime(2020, 3, 28, 15, 0), [("asleep", 1800)], kind="classic", main=False
            ),
            _sleep_log(
                1005, datetime(2020, 3, 28, 15, 20), [("asleep", 1800)], kind="classic", main=False
            ),
            # Conflicting duplicate id: dropped.
            _sleep_log(
                1006, datetime(2020, 3, 28, 12, 0), [("asleep", 1200)], kind="classic", main=False
            ),
            _sleep_log(
                1006, datetime(2020, 3, 28, 12, 0), [("asleep", 1500)], kind="classic", main=False
            ),
        ]
    )
    members["p01/fitbit/sleep_score.csv"] = _csv(
        ["timestamp", "sleep_log_entry_id", "overall_score"], [["2020-03-28T07:00:00Z", 1001, 80]]
    )
    members["p01/fitbit/exercise.json"] = j([{"logId": 1, "activityName": "Walk"}])
    members["p01/pmsys/wellness.csv"] = _csv(
        [
            "effective_time_frame",
            "fatigue",
            "mood",
            "readiness",
            "sleep_duration_h",
            "sleep_quality",
            "soreness",
            "soreness_area",
            "stress",
        ],
        [
            ["2020-03-28T07:10:00.000Z", 2, 3, 6, 7, 3, 3, "[]", 3],
            ["2020-03-28T09:30:00.500Z", 4, 4, 8, 7.5, 4, 3, "[1]", 4],  # same local day: wins
            ["2020-03-30T06:00:00.000Z", 0, 3, 5, 6, 3, 3, "[]", 3],  # fatigue 0: out of scale
        ],
    )
    members["p01/pmsys/srpe.csv"] = _csv(
        ["end_date_time", "perceived_exertion"], [["2020-03-28T18:00:00Z", 6]]
    )
    members["p01/googledocs/reporting.csv"] = _csv(["date", "weight"], [["28/03/2020", 70]])
    members["p01/food-images/photo.jpg"] = b"\xff\xd8 synthetic"

    # p02: steps and wellness only; no heart rate or resting HR file.
    t1 = datetime(2020, 1, 10, 0, 0)
    members["p02/fitbit/steps.json"] = j(
        [{"dateTime": _stamp(m), "value": str(m.minute % 7)} for m in _minutes(t1, 48 * 60)]
    )
    members["p02/fitbit/sleep.json"] = j([])
    members["p02/pmsys/wellness.csv"] = _csv(
        [
            "effective_time_frame",
            "fatigue",
            "mood",
            "readiness",
            "sleep_duration_h",
            "sleep_quality",
            "soreness",
            "soreness_area",
            "stress",
        ],
        [["2020-01-10T08:00:00.000Z", 3, 3, 5, 8, 3, 3, "[]", 3]],
    )
    members["participant-overview.xlsx"] = b"synthetic placeholder"
    return members


def write_archive(path: Path, members: dict[str, bytes]) -> Admission:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as handle:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(2020, 4, 24, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            handle.writestr(info, members[name])
    return Admission(
        dataset_id="pmdata",
        dataset_version="synthetic-1",
        archive_name=path.name,
        archive_bytes=path.stat().st_size,
        archive_sha256=sha256_file(path),
    )


@dataclass(frozen=True)
class Built:
    archive: Path
    admission: Admission
    snapshot: Path
    report: dict


@pytest.fixture(scope="session")
def synthetic_archive(tmp_path_factory) -> tuple[Path, Admission]:
    path = tmp_path_factory.mktemp("archive") / "pmdata.zip"
    return path, write_archive(path, build_members())


@pytest.fixture(scope="session")
def built(synthetic_archive, tmp_path_factory) -> Built:
    from hachi.data.pmdata.snapshot import GitState, build

    archive, admission = synthetic_archive
    root = tmp_path_factory.mktemp("derived")
    result = build(archive, root, load_config(), admission, GitState("0" * 40, False))
    return Built(archive, admission, result.path, result.report)
