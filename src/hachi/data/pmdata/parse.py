"""Strict, streaming parsers for the PMData member formats.

Each parser yields typed rows or raises ParseError; nothing is guessed. Timestamps stay as the
source wrote them here: which clock they are on is decided in `clock`.
"""

import codecs
import csv
import io
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, BinaryIO

CHUNK_CHARS = 1 << 20
MAX_ELEMENT_CHARS = 1 << 22

NAIVE_SECOND = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
NAIVE_MILLI = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d{3})?$")
UTC_MILLI = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
INTEGER = re.compile(r"^-?\d+$")
DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")


class ParseError(ValueError):
    pass


def iter_json_array(stream: BinaryIO) -> Iterator[Any]:
    """Yield the elements of one top-level JSON array of objects without loading it whole."""
    decoder = json.JSONDecoder()
    text = codecs.getincrementaldecoder("utf-8")(errors="strict")
    buffer, pos, eof = "", 0, False

    def fill() -> bool:
        nonlocal buffer, pos, eof
        if eof:
            return False
        block = stream.read(CHUNK_CHARS)
        if not block:
            eof = True
            buffer = buffer[pos:] + text.decode(b"", final=True)
        else:
            buffer = buffer[pos:] + text.decode(block)
        pos = 0
        return True

    def skip_space() -> str:
        nonlocal pos
        while True:
            while pos < len(buffer) and buffer[pos] in " \t\r\n":
                pos += 1
            if pos < len(buffer):
                return buffer[pos]
            if not fill():
                return ""

    if skip_space() != "[":
        raise ParseError("expected a JSON array")
    pos += 1
    first = True
    while True:
        token = skip_space()
        if token == "]" and first:
            pos += 1
            break
        if not first:
            if token == "]":
                pos += 1
                break
            if token != ",":
                raise ParseError("expected ',' or ']' between array elements")
            pos += 1
            skip_space()
        while True:
            try:
                element, end = decoder.raw_decode(buffer, pos)
                break
            except json.JSONDecodeError as error:
                if len(buffer) - pos > MAX_ELEMENT_CHARS or not fill():
                    raise ParseError("malformed or oversized array element") from error
        if not isinstance(element, dict):
            raise ParseError("array elements must be objects")
        pos = end
        first = False
        yield element
    if skip_space() != "":
        raise ParseError("trailing content after the array")


def _keys(row: dict, expected: set[str]) -> None:
    if set(row) != expected:
        raise ParseError(f"unexpected fields {sorted(set(row) ^ expected)}")


def naive_second(value: Any) -> str:
    if not isinstance(value, str) or not NAIVE_SECOND.match(value):
        raise ParseError("timestamp must look like 'YYYY-MM-DD HH:MM:SS'")
    return value


@dataclass(frozen=True)
class IntradayValue:
    timestamp: str  # 'YYYY-MM-DD HH:MM:SS' as written
    value: float


@dataclass(frozen=True)
class HeartRateSample:
    timestamp: str
    bpm: int
    confidence: int


def iter_intraday(stream: BinaryIO) -> Iterator[IntradayValue]:
    """steps/distance/calories and the per-day minute summaries: {dateTime, value: "<number>"}."""
    for row in iter_json_array(stream):
        _keys(row, {"dateTime", "value"})
        value = row["value"]
        if not isinstance(value, str) or not DECIMAL.match(value):
            raise ParseError("intraday value must be a decimal string")
        yield IntradayValue(naive_second(row["dateTime"]), float(value))


def iter_heart_rate(stream: BinaryIO) -> Iterator[HeartRateSample]:
    for row in iter_json_array(stream):
        _keys(row, {"dateTime", "value"})
        value = row["value"]
        if not isinstance(value, dict) or set(value) != {"bpm", "confidence"}:
            raise ParseError("heart rate value must hold bpm and confidence")
        bpm, confidence = value["bpm"], value["confidence"]
        if type(bpm) is not int or type(confidence) is not int:
            raise ParseError("bpm and confidence must be integers")
        yield HeartRateSample(naive_second(row["dateTime"]), bpm, confidence)


@dataclass(frozen=True)
class DailyRestingHeartRate:
    day: date
    value: float
    error: float | None


def iter_resting_heart_rate(stream: BinaryIO) -> Iterator[DailyRestingHeartRate]:
    for row in iter_json_array(stream):
        _keys(row, {"dateTime", "value"})
        stamp = naive_second(row["dateTime"])
        if not stamp.endswith(" 00:00:00"):
            raise ParseError("daily resting HR must be stamped at midnight")
        day = date.fromisoformat(stamp[:10])
        value = row["value"]
        if not isinstance(value, dict) or set(value) != {"date", "value", "error"}:
            raise ParseError("resting HR value must hold date, value and error")
        if value["date"] != day.strftime("%m/%d/%y"):
            raise ParseError("resting HR date disagrees with its dateTime")
        number, error = value["value"], value["error"]
        if not isinstance(number, int | float) or isinstance(number, bool):
            raise ParseError("resting HR must be numeric")
        if error is not None and (not isinstance(error, int | float) or isinstance(error, bool)):
            raise ParseError("resting HR error must be numeric")
        yield DailyRestingHeartRate(day, float(number), None if error is None else float(error))


@dataclass(frozen=True)
class SleepSegment:
    start: datetime  # naive local wall time as written
    level: str
    seconds: int


@dataclass(frozen=True)
class SleepLog:
    log_id: int
    sleep_type: str  # "stages" or "classic"
    main_sleep: bool
    start: datetime  # naive local
    end: datetime  # naive local
    duration_ms: int
    minutes_asleep: int
    summary_seconds: dict[str, int]
    data: tuple[SleepSegment, ...]
    short_data: tuple[SleepSegment, ...]
    fingerprint: str  # content identity excluding Fitbit's rolling thirty-day averages


def _naive_local(value: Any) -> datetime:
    if not isinstance(value, str) or not NAIVE_MILLI.match(value):
        raise ParseError("sleep timestamp must be a local wall time without offset")
    return datetime.fromisoformat(value.replace("T", " "))


def _segments(rows: Any) -> tuple[SleepSegment, ...]:
    if not isinstance(rows, list):
        raise ParseError("sleep levels must be lists")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise ParseError("sleep segment must be an object")
        _keys(row, {"dateTime", "level", "seconds"})
        seconds = row["seconds"]
        if type(seconds) is not int or seconds <= 0 or not isinstance(row["level"], str):
            raise ParseError("sleep segment needs a level and positive whole seconds")
        out.append(SleepSegment(_naive_local(row["dateTime"]), row["level"], seconds))
    return tuple(out)


def _without_rolling_averages(row: dict) -> dict:
    summary = {
        level: {k: v for k, v in stats.items() if k != "thirtyDayAvgMinutes"}
        for level, stats in row["levels"]["summary"].items()
    }
    return {**row, "levels": {**row["levels"], "summary": summary}}


def iter_sleep(stream: BinaryIO) -> Iterator[SleepLog]:
    required = {
        "logId",
        "dateOfSleep",
        "startTime",
        "endTime",
        "duration",
        "minutesToFallAsleep",
        "minutesAsleep",
        "minutesAwake",
        "minutesAfterWakeup",
        "timeInBed",
        "efficiency",
        "type",
        "infoCode",
        "levels",
        "mainSleep",
    }
    for row in iter_json_array(stream):
        _keys(row, required)
        if row["type"] not in {"stages", "classic"}:
            raise ParseError("sleep type must be stages or classic")
        levels = row["levels"]
        if not isinstance(levels, dict) or not {"data", "summary"} <= set(levels):
            raise ParseError("sleep levels need data and summary")
        if set(levels) - {"data", "summary", "shortData"}:
            raise ParseError("unexpected sleep level fields")
        summary = levels["summary"]
        if not isinstance(summary, dict):
            raise ParseError("sleep summary must be an object")
        summary_seconds = {}
        for level, stats in summary.items():
            if not isinstance(stats, dict) or type(stats.get("minutes")) is not int:
                raise ParseError("sleep summary minutes must be integers")
            summary_seconds[level] = stats["minutes"] * 60
        for key in ("logId", "duration", "minutesAsleep"):
            if type(row[key]) is not int:
                raise ParseError(f"sleep {key} must be an integer")
        if type(row["mainSleep"]) is not bool:
            raise ParseError("mainSleep must be a boolean")
        fingerprint = json.dumps(_without_rolling_averages(row), sort_keys=True)
        yield SleepLog(
            log_id=row["logId"],
            sleep_type=row["type"],
            main_sleep=row["mainSleep"],
            start=_naive_local(row["startTime"]),
            end=_naive_local(row["endTime"]),
            duration_ms=row["duration"],
            minutes_asleep=row["minutesAsleep"],
            summary_seconds=summary_seconds,
            data=_segments(levels["data"]),
            short_data=_segments(levels.get("shortData", [])),
            fingerprint=fingerprint,
        )


def iter_csv(stream: BinaryIO) -> Iterator[dict[str, str]]:
    text = io.TextIOWrapper(stream, encoding="utf-8", newline="")
    try:
        for row in csv.DictReader(text, strict=True):
            if None in row or any(v is None for v in row.values()):
                raise ParseError("CSV row has the wrong number of fields")
            yield row
    finally:
        text.detach()  # leave the member stream open for the archive to finish hashing


@dataclass(frozen=True)
class WellnessReport:
    reported_at: datetime  # aware UTC
    items: dict[str, str]  # raw item strings, validated in `wellness`


WELLNESS_COLUMNS = (
    "effective_time_frame",
    "fatigue",
    "mood",
    "readiness",
    "sleep_duration_h",
    "sleep_quality",
    "soreness",
    "soreness_area",
    "stress",
)


def iter_wellness(stream: BinaryIO) -> Iterator[WellnessReport]:
    for row in iter_csv(stream):
        if tuple(row) != WELLNESS_COLUMNS:
            raise ParseError("unexpected wellness columns")
        stamp = row["effective_time_frame"]
        if not UTC_MILLI.match(stamp):
            raise ParseError("wellness time must be UTC with a Z suffix")
        reported_at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        items = {k: v for k, v in row.items() if k != "effective_time_frame"}
        yield WellnessReport(reported_at, items)


def count_rows(kind: str, stream: BinaryIO) -> int:
    """Rows in a member that is reconciled but not ingested."""
    if kind.endswith(".csv"):
        return sum(1 for _ in iter_csv(stream))
    return sum(1 for _ in iter_json_array(stream))
