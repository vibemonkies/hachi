"""Coverage: which metrics a subject has, over what span, with what gaps, at an optional as-of."""

from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

from hachi.contracts.api import Coverage, MetricCoverage, TaskSupport
from hachi.contracts.base import SCHEMA_VERSION, DataMode, DatasetSnapshotRef
from hachi.contracts.metrics import METRICS, Metric

from .sources import Presence

HOUR = timedelta(hours=1)
# Below this many distinct observed hours a history is "insufficient": the baselines' minimum
# history (#9: 24 hours) cannot be met at any cutoff.
MIN_HISTORY_HOURS = 24
# A single record never marks more than this many hours present (bounds pathological spans).
MAX_SPAN_HOURS = 24 * 31


def _hour_index(moment: datetime) -> int:
    return int(moment.timestamp() // 3600)


def _touched_hours(start: datetime, end: datetime, cap: int | None = MAX_SPAN_HOURS) -> range:
    first = _hour_index(start)
    last = _hour_index(end - timedelta(microseconds=1)) if end > start else first
    if cap is not None:
        last = min(last, first + cap - 1)
    return range(first, last + 1)


def build_coverage(
    *,
    subject_id: str,
    data_mode: DataMode,
    snapshot: DatasetSnapshotRef | None,
    tz_name: str,
    presence: Iterable[Presence],
    task_support: Callable[[set[Metric], bool], list[TaskSupport]],
    generated_at: datetime,
) -> Coverage:
    first: dict[str, datetime] = {}
    last: dict[str, datetime] = {}
    hours: dict[str, set[int]] = defaultdict(set)
    kinds: dict[str, set[str]] = defaultdict(set)
    for p in presence:
        first[p.metric] = min(first.get(p.metric, p.start_utc), p.start_utc)
        last[p.metric] = max(last.get(p.metric, p.end_utc), p.end_utc)
        hours[p.metric].update(_touched_hours(p.start_utc, p.end_utc))
        kinds[p.metric].add(p.source_kind)
    if not first:
        return Coverage(
            schema_version=SCHEMA_VERSION,
            subject_id=subject_id,
            data_mode=data_mode,
            generated_at_utc=generated_at,
            dataset_snapshot=snapshot,
            history="empty",
            span_start_utc=None,
            span_end_utc=None,
            metrics=[],
            task_support=task_support(set(), False),
        )
    span_start, span_end = min(first.values()), max(last.values())
    span_hours = len(_touched_hours(span_start, span_end, cap=None))
    zone = ZoneInfo(tz_name)
    metrics = []
    for metric in sorted(first, key=list(METRICS).index):
        observed = sorted(hours[metric])
        gaps = [b - a - 1 for a, b in pairwise(observed)]
        days = {datetime.fromtimestamp(h * 3600, UTC).astimezone(zone).date() for h in observed}
        metrics.append(
            MetricCoverage(
                metric=metric,
                unit=METRICS[metric].unit,
                first_utc=first[metric],
                last_utc=last[metric],
                days_with_data=len(days),
                coverage=min(1.0, len(observed) / span_hours),
                longest_gap_hours=float(max(gaps, default=0)),
                source_kinds=sorted(kinds[metric]),
            )
        )
    sufficient = len(set().union(*hours.values())) >= MIN_HISTORY_HOURS
    return Coverage(
        schema_version=SCHEMA_VERSION,
        subject_id=subject_id,
        data_mode=data_mode,
        generated_at_utc=generated_at,
        dataset_snapshot=snapshot,
        history="sufficient" if sufficient else "insufficient",
        span_start_utc=span_start,
        span_end_utc=span_end,
        metrics=metrics,
        task_support=task_support(set(first), sufficient),
    )
