"""Which local days each participant has wearable records on, streamed from a Stanford archive.

Labels are only useful where wearable data sits around them, so the label snapshot records each
participant-day's record counts per stream. Members are streamed straight from the zip (never
extracted) with pyarrow's CSV reader, reading only the timestamp column; zipfile checks every
member's CRC as it reaches the end. Output is counts, never values.
"""

import re
import zipfile
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

MAX_MEMBERS = 20_000
MAX_MEMBER_BYTES = 8 << 30
BLOCK_BYTES = 1 << 24

PHASE1 = re.compile(
    r"^COVID-19-Wearables/(?P<subject>[A-Z0-9]{7})(?:_(?P<device>\d))?_"
    r"(?P<stream>hr|steps|sleep)(?P<longterm>_longterm)?\.csv$"
)
PHASE2 = re.compile(
    r"^COVID-19-Phase2-Wearables/(?P<subject>P\d{6})/Orig_(?P<device>Fitbit|NonFitbit)_"
    r"(?P<stream>HR|ST)\.csv$"
)
STREAMS = {
    "hr": "heart_rate",
    "steps": "steps",
    "sleep": "sleep",
    "HR": "heart_rate",
    "ST": "steps",
}


class WearableArchiveError(ValueError):
    pass


@dataclass(frozen=True)
class Member:
    name: str
    subject_id: str
    stream: str  # heart_rate | steps | sleep
    source: str  # device or download variant
    timestamp_column: str
    size: int


@dataclass
class Coverage:
    """Record counts per (subject, local day, stream), plus per-member bookkeeping."""

    days: Counter = field(default_factory=Counter)  # (subject, date, stream) -> records
    members: dict[str, dict] = field(default_factory=dict)
    ignored: Counter = field(default_factory=Counter)
    # Steps summed by hour of day over the whole archive: the clock check. Local wall time
    # puts the trough at night; US data on UTC would put it mid-morning.
    steps_by_hour: Counter = field(default_factory=Counter)


def _phase1(info: zipfile.ZipInfo) -> Member | None:
    m = PHASE1.match(info.filename)
    if m is None:
        return None
    variant = "longterm" if m["longterm"] else "standard"
    source = f"device{m['device']}-{variant}" if m["device"] else variant
    return Member(
        info.filename, m["subject"], STREAMS[m["stream"]], source, "datetime", info.file_size
    )


def _phase2(info: zipfile.ZipInfo) -> Member | None:
    m = PHASE2.match(info.filename)
    if m is None:
        return None
    column = "start_datetime" if m["device"] == "NonFitbit" and m["stream"] == "ST" else "datetime"
    return Member(
        info.filename, m["subject"], STREAMS[m["stream"]], m["device"], column, info.file_size
    )


LAYOUTS: dict[str, Callable[[zipfile.ZipInfo], Member | None]] = {
    "phase1": _phase1,
    "phase2": _phase2,
}


def _ignorable(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    return name.startswith("__MACOSX/") or base == ".DS_Store" or name.endswith("/")


def list_members(archive: Path, layout: str) -> tuple[list[Member], Counter]:
    classify = LAYOUTS[layout]
    members, ignored = [], Counter()
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) > MAX_MEMBERS:
            raise WearableArchiveError("too many archive members")
        names = [i.filename for i in infos]
        if len(names) != len(set(names)):
            raise WearableArchiveError("duplicate member names")
        for info in infos:
            name = info.filename
            if name.startswith(("/", "\\")) or "\\" in name or ".." in name.split("/"):
                raise WearableArchiveError(f"unsafe member path {name!r}")
            if _ignorable(name):
                ignored["macos_metadata_or_directory"] += 1
                continue
            if info.flag_bits & 0x1 or info.compress_type not in (
                zipfile.ZIP_STORED,
                zipfile.ZIP_DEFLATED,
            ):
                raise WearableArchiveError(f"encrypted or unsupported member {name!r}")
            if info.file_size > MAX_MEMBER_BYTES:
                raise WearableArchiveError(f"{name!r} is too large")
            member = classify(info)
            if member is None:
                raise WearableArchiveError(f"unexpected member {name!r}")
            members.append(member)
    return sorted(members, key=lambda m: m.name), ignored


# Some phase 2 members hold the text of a failed BigQuery export instead of a CSV.
EXPORT_ERRORS = ("BigQuery error in query operation", "Error in query string")


def _first_line(z: zipfile.ZipFile, name: str) -> str | None:
    with z.open(name) as handle:
        for _ in range(4):
            line = handle.readline(1 << 16)
            if not line:
                return None
            if line.strip():
                return line.decode("utf-8", "replace").strip()
    return None


def _scan(args: tuple[Path, Member]) -> tuple[Member, dict[str, int], dict]:
    archive, member = args
    counts: Counter = Counter()
    by_hour: Counter = Counter()
    rows = bad = 0
    columns = [member.timestamp_column] + (["steps"] if member.stream == "steps" else [])
    with zipfile.ZipFile(archive) as z:
        first = _first_line(z, member.name)
        if first is None:
            return member, {}, {"rows": 0, "bad_timestamps": 0, "state": "empty"}
        if first.startswith(EXPORT_ERRORS):
            return member, {}, {"rows": 0, "bad_timestamps": 0, "state": "export_error"}
        if not set(columns) <= set(first.replace('"', "").split(",")):
            raise WearableArchiveError(f"{member.name}: unexpected header")
        with z.open(member.name) as handle:
            reader = pacsv.open_csv(
                handle,
                read_options=pacsv.ReadOptions(block_size=BLOCK_BYTES),
                convert_options=pacsv.ConvertOptions(
                    include_columns=columns,
                    column_types={member.timestamp_column: pa.string(), "steps": pa.float64()},
                ),
            )
            for batch in reader:
                column = batch.column(member.timestamp_column)
                rows += len(column)
                days = pc.utf8_slice_codeunits(column, 0, 10)
                valid = pc.fill_null(pc.match_substring_regex(days, r"^\d{4}-\d{2}-\d{2}$"), False)
                bad += len(column) - pc.sum(pc.cast(valid, pa.int64())).as_py()
                for item in pc.value_counts(pc.filter(days, valid)).to_pylist():
                    counts[item["values"]] += item["counts"]
                if member.stream == "steps":
                    hours = pc.utf8_slice_codeunits(pc.filter(column, valid), 11, 13)
                    table = pa.table({"h": hours, "s": pc.filter(batch.column("steps"), valid)})
                    for item in table.group_by("h").aggregate([("s", "sum")]).to_pylist():
                        by_hour[item["h"]] += item["s_sum"] or 0
            handle.read()  # reach EOF so zipfile verifies the CRC
    stats = {"rows": rows, "bad_timestamps": bad, "state": "read", "steps_by_hour": by_hour}
    return member, dict(counts), stats


def scan(archive: Path, layout: str, workers: int = 6) -> Coverage:
    members, ignored = list_members(archive, layout)
    coverage = Coverage(ignored=ignored)
    jobs = [(archive, m) for m in sorted(members, key=lambda m: -m.size)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for member, counts, stats in pool.map(_scan, jobs):
            for day, n in counts.items():
                try:
                    parsed = date.fromisoformat(day)
                except ValueError:
                    stats["bad_timestamps"] += n
                    continue
                coverage.days[(member.subject_id, parsed, member.stream)] += n
            coverage.steps_by_hour.update(stats.pop("steps_by_hour", {}))
            coverage.members[member.name] = {
                "subject_id": member.subject_id,
                "stream": member.stream,
                "source": member.source,
                "bytes": member.size,
                **stats,
            }
    return coverage
