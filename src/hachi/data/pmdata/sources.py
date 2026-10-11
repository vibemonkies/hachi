"""Fitbit members of one participant become canonical observation rows.

Rules, all counted in the audit rather than applied silently:
- Exact duplicates (same instant, same value) are kept once. Conflicting duplicates are all
  dropped: neither value is known to be right.
- Missing minutes stay missing. Nothing is filled, and a zero is only ever a recorded zero.
- Vendor resting HR of 0 is Fitbit's "no estimate", not a heart rate.
- Sleep logs are local wall time. A log spanning a DST change, overlapping another log, or
  disagreeing with its own duplicate is quarantined whole. Fitbit's short wakes (shortData)
  are overlaid on the stage timeline so stage totals reconcile with Fitbit's own summary.
"""

import itertools
from array import array
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from zoneinfo import ZoneInfo

from hachi.contracts.base import local_day_bounds
from hachi.contracts.metrics import METRICS, Metric

from . import parse
from .archive import Archive
from .clock import MINUTE, SECOND, intraday_us, local_us, to_us
from .config import PipelineConfig

STAGE_METRICS: dict[str, dict[str, Metric | None]] = {
    "stages": {
        "wake": "sleep_awake",
        "light": "sleep_asleep_core",
        "deep": "sleep_asleep_deep",
        "rem": "sleep_asleep_rem",
        "unknown": None,
    },
    "classic": {
        # Fitbit counts restless minutes as neither asleep nor plainly awake; no canonical
        # metric holds them, so they are excluded and counted.
        "asleep": "sleep_asleep_unspecified",
        "awake": "sleep_awake",
        "restless": None,
    },
}
SUMMARY_TOLERANCE_SECONDS = 60

type Counts = Counter[tuple[str, str]]


@dataclass
class Rows:
    """Observation columns for one participant; constant columns are added when written."""

    metric: list[str] = field(default_factory=list)
    record_id: list[str] = field(default_factory=list)
    value: array = field(default_factory=lambda: array("d"))
    start: array = field(default_factory=lambda: array("q"))
    end: array = field(default_factory=lambda: array("q"))
    available: array = field(default_factory=lambda: array("q"))
    rule: list[str] = field(default_factory=list)

    def add(self, metric, record_id, value, start, end, available, rule) -> None:
        self.metric.append(metric)
        self.record_id.append(record_id)
        self.value.append(value)
        self.start.append(start)
        self.end.append(end)
        self.available.append(available)
        self.rule.append(rule)

    def __len__(self) -> int:
        return len(self.record_id)


@dataclass(frozen=True)
class KeptSleepLog:
    log_id: int
    sleep_type: str
    main_sleep: bool
    start_naive: object
    start: int
    end: int
    segments: tuple[tuple[int, int, str], ...]  # (start_us, end_us, level) after overlay


@dataclass
class Participant:
    subject: str
    rows: Rows
    sleep_logs: list[KeptSleepLog]
    steps_by_minute: dict[int, float]
    heart_rate_by_minute: dict[int, float]  # mean bpm per UTC minute, for the clock audit


def rules(config: PipelineConfig) -> dict[str, str]:
    lag = config.availability
    return {
        "intraday": f"pmdata-fitbit-intraday-end-plus-{lag.intraday_lag_seconds}s",
        "daily": f"pmdata-fitbit-daily-local-day-end-plus-{lag.daily_summary_lag_seconds}s",
        "sleep": f"pmdata-fitbit-sleep-log-end-plus-{lag.sleep_lag_seconds}s",
    }


def _within_bounds(metric: Metric, value: float) -> bool:
    spec = METRICS[metric]
    if spec.minimum is not None and value < spec.minimum:
        return False
    return spec.maximum is None or value <= spec.maximum


def _deduplicate(
    pairs: Iterable[tuple[int, float]], kind: str, counts: Counts
) -> list[tuple[int, float]]:
    by_time: dict[int, list[float]] = defaultdict(list)
    for moment, value in pairs:
        by_time[moment].append(value)
    kept = []
    for moment in sorted(by_time):
        values = by_time[moment]
        if len(set(values)) > 1:
            counts[(kind, "duplicate_conflicting_dropped")] += len(values)
            continue
        counts[(kind, "duplicate_identical_dropped")] += len(values) - 1
        kept.append((moment, values[0]))
    return kept


def _heart_rate(archive, subject, config, rows, counts, rule, by_minute) -> None:
    kind = "fitbit/heart_rate.json"
    member = archive.member(subject, kind)
    if member is None:
        counts[(kind, "participants_missing_file")] += 1
        return
    pairs = []
    with archive.open(member) as stream:
        for sample in parse.iter_heart_rate(stream):
            counts[(kind, "rows")] += 1
            counts[(kind, f"confidence_{sample.confidence}")] += 1
            pairs.append((intraday_us(sample.timestamp), float(sample.bpm)))
    lag = config.availability.intraday_lag_seconds * SECOND
    sums: dict[int, list[float]] = defaultdict(lambda: [0.0, 0])
    for moment, bpm in _deduplicate(pairs, kind, counts):
        if not _within_bounds("heart_rate", bpm):
            counts[(kind, "rejected_out_of_bounds")] += 1
            continue
        counts[(kind, "accepted")] += 1
        rows.add(
            "heart_rate",
            f"{subject}-hr-{moment // SECOND}",
            bpm,
            moment,
            moment,
            moment + lag,
            rule,
        )
        cell = sums[moment - moment % MINUTE]
        cell[0] += bpm
        cell[1] += 1
    by_minute.update({m: s / n for m, (s, n) in sums.items()})


def _per_minute(archive, subject, config, rows, counts, rule, kind, metric, scale, code):
    member = archive.member(subject, kind)
    if member is None:
        counts[(kind, "participants_missing_file")] += 1
        return {}
    pairs = []
    with archive.open(member) as stream:
        for item in parse.iter_intraday(stream):
            counts[(kind, "rows")] += 1
            moment = intraday_us(item.timestamp)
            if moment % MINUTE:
                counts[(kind, "rejected_off_minute")] += 1
                continue
            pairs.append((moment, item.value))
    lag = config.availability.intraday_lag_seconds * SECOND
    kept = {}
    for moment, raw in _deduplicate(pairs, kind, counts):
        value = raw * scale
        if not _within_bounds(metric, value):
            counts[(kind, "rejected_out_of_bounds")] += 1
            continue
        counts[(kind, "accepted")] += 1
        if raw == 0:
            counts[(kind, "accepted_recorded_zero")] += 1
        end = moment + MINUTE
        rows.add(
            metric, f"{subject}-{code}-{moment // SECOND}", value, moment, end, end + lag, rule
        )
        kept[moment] = value
    return kept


def _resting_heart_rate(archive, subject, config, rows, counts, rule) -> None:
    kind = "fitbit/resting_heart_rate.json"
    member = archive.member(subject, kind)
    if member is None:
        counts[(kind, "participants_missing_file")] += 1
        return
    by_day: dict[date, list[float]] = defaultdict(list)
    with archive.open(member) as stream:
        for item in parse.iter_resting_heart_rate(stream):
            counts[(kind, "rows")] += 1
            if item.value <= 0:
                counts[(kind, "excluded_zero_means_no_estimate")] += 1
                continue
            by_day[item.day].append(item.value)
    lag = config.availability.daily_summary_lag_seconds * SECOND
    for day in sorted(by_day):
        values = by_day[day]
        if len(set(values)) > 1:
            counts[(kind, "duplicate_conflicting_dropped")] += len(values)
            continue
        counts[(kind, "duplicate_identical_dropped")] += len(values) - 1
        if not _within_bounds("resting_heart_rate_vendor", values[0]):
            counts[(kind, "rejected_out_of_bounds")] += 1
            continue
        start, end = (to_us(t) for t in local_day_bounds(day, config.local_timezone))
        counts[(kind, "accepted")] += 1
        rows.add(
            "resting_heart_rate_vendor",
            f"{subject}-rhr-{day:%Y%m%d}",
            values[0],
            start,
            end,
            end + lag,
            rule,
        )


def _overlay(log: parse.SleepLog, start_us: int) -> list[tuple[int, int, str]]:
    """Stage timeline in UTC with short wakes carved out of the long segments."""

    def at(segment: parse.SleepSegment) -> tuple[int, int]:
        # The log does not cross a DST change, so wall-clock offsets are elapsed time.
        begin = start_us + int((segment.start - log.start).total_seconds() * SECOND)
        return begin, begin + segment.seconds * SECOND

    pieces = [(*at(s), s.level) for s in log.data]
    for short in log.short_data:
        if short.level != "wake":
            raise parse.ParseError("shortData holds only wake periods")
        a, b = at(short)
        carved = []
        for begin, end, level in pieces:
            if end <= a or begin >= b:
                carved.append((begin, end, level))
                continue
            if begin < a:
                carved.append((begin, a, level))
            if end > b:
                carved.append((b, end, level))
        carved.append((a, b, "wake"))
        pieces = sorted(carved)
    return [p for p in pieces if p[1] > p[0]]


def _sleep(archive, subject, config, rows, counts, rule) -> list[KeptSleepLog]:
    kind = "fitbit/sleep.json"
    member = archive.member(subject, kind)
    if member is None:
        counts[(kind, "participants_missing_file")] += 1
        return []
    zone = ZoneInfo(config.local_timezone)
    by_id: dict[int, list[parse.SleepLog]] = defaultdict(list)
    with archive.open(member) as stream:
        for log in parse.iter_sleep(stream):
            counts[(kind, "rows")] += 1
            by_id[log.log_id].append(log)
    candidates = []
    for log_id in sorted(by_id):
        logs = by_id[log_id]
        if len({log.fingerprint for log in logs}) > 1:
            counts[(kind, "duplicate_conflicting_dropped")] += len(logs)
            continue
        counts[(kind, "duplicate_identical_dropped")] += len(logs) - 1
        log = logs[0]
        start, end = local_us(log.start, zone), local_us(log.end, zone)
        if (
            start is None
            or end is None
            or (end - start) != int((log.end - log.start).total_seconds() * SECOND)
        ):
            counts[(kind, "quarantined_dst_transition")] += 1
            continue
        if end <= start or log.duration_ms * 1000 > end - start + SECOND:
            counts[(kind, "rejected_duration_exceeds_interval")] += 1
            continue
        try:
            pieces = _overlay(log, start)
        except parse.ParseError:
            counts[(kind, "rejected_malformed_levels")] += 1
            continue
        if not pieces or pieces[0][0] < start or pieces[-1][1] > end:
            counts[(kind, "rejected_segments_outside_log")] += 1
            continue
        if any(a[1] > b[0] for a, b in itertools.pairwise(pieces)):
            counts[(kind, "rejected_overlapping_segments")] += 1
            continue
        if any(level not in STAGE_METRICS[log.sleep_type] for *_, level in pieces):
            raise parse.ParseError(f"unknown {log.sleep_type} sleep level")
        candidates.append((log, start, end, pieces))
    # Distinct logs that overlap in time would double-count; neither is preferred.
    candidates.sort(key=lambda c: (c[1], c[0].log_id))
    overlapping = set()
    for (a, _a_start, a_end, _), (b, b_start, _, _) in itertools.pairwise(candidates):
        if b_start < a_end:
            overlapping |= {a.log_id, b.log_id}
    kept = []
    lag = config.availability.sleep_lag_seconds * SECOND
    for log, start, end, pieces in candidates:
        if log.log_id in overlapping:
            counts[(kind, "quarantined_overlapping_logs")] += 1
            continue
        counts[(kind, "accepted")] += 1
        counts[(kind, f"accepted_{log.sleep_type}_{'main' if log.main_sleep else 'other'}")] += 1
        totals = Counter()
        for begin, finish, level in pieces:
            totals[level] += (finish - begin) // SECOND
        reconciled = all(
            abs(totals[level] - seconds) <= SUMMARY_TOLERANCE_SECONDS
            for level, seconds in log.summary_seconds.items()
            if level in STAGE_METRICS[log.sleep_type]
        )
        counts[(kind, "summary_reconciled" if reconciled else "summary_mismatch")] += 1
        available = end + lag
        prefix = f"{subject}-sleep-{log.log_id}"
        rows.add(
            "sleep_in_bed", f"{prefix}-inbed", log.duration_ms / 1000, start, end, available, rule
        )
        for index, (begin, finish, level) in enumerate(pieces):
            metric = STAGE_METRICS[log.sleep_type][level]
            if metric is None:
                counts[(kind, f"segments_excluded_{log.sleep_type}_{level}")] += 1
                continue
            seconds = (finish - begin) / SECOND
            rows.add(metric, f"{prefix}-{index:03d}", seconds, begin, finish, available, rule)
        kept.append(
            KeptSleepLog(
                log.log_id, log.sleep_type, log.main_sleep, log.start, start, end, tuple(pieces)
            )
        )
    return kept


def count_only(archive: Archive, subject: str, counts: Counts) -> None:
    """Parse reconciled-but-not-ingested members so their row counts can be checked."""
    for member in archive.members:
        if member.subject == subject and member.role == "counted":
            with archive.open(member) as stream:
                counts[(member.kind, "rows")] += parse.count_rows(member.kind, stream)
            counts[(member.kind, "excluded_rows")] = counts[(member.kind, "rows")]


def participant(archive: Archive, subject: str, config: PipelineConfig, counts: Counts):
    rows = Rows()
    rule = rules(config)
    by_minute: dict[int, float] = {}
    _heart_rate(archive, subject, config, rows, counts, rule["intraday"], by_minute)
    steps = _per_minute(
        archive,
        subject,
        config,
        rows,
        counts,
        rule["intraday"],
        "fitbit/steps.json",
        "steps",
        1.0,
        "steps",
    )
    _per_minute(
        archive,
        subject,
        config,
        rows,
        counts,
        rule["intraday"],
        "fitbit/distance.json",
        "walking_running_distance",
        0.01,
        "distance",  # cm -> m
    )
    _resting_heart_rate(archive, subject, config, rows, counts, rule["daily"])
    logs = _sleep(archive, subject, config, rows, counts, rule["sleep"])
    count_only(archive, subject, counts)
    return Participant(subject, rows, logs, steps, by_minute)
