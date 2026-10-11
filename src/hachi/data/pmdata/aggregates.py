"""Hourly (UTC) and daily (local midnight to midnight) bins over canonical observations.

Every bin of a participant's span exists for every metric, so missing data is explicit: a bin
without observations is null with "no_observations", never zero. Coverage is the fraction of
the bin with usable data:
- heart rate: minutes holding at least one sample;
- steps, distance, vendor resting HR: the observations' own intervals;
- sleep states: time inside any sleep log, so an hour fully in bed with no deep sleep is
  covered but still has no deep-sleep observation.

`available_at_utc` is pipeline metadata beside the canonical Aggregate columns: the latest
availability of anything the bin depends on, and never before the bin ends. For any cutoff at
or after it, recomputing the bin from the observations available by that cutoff gives the
stored row. Before it, recompute from observations; the stored value may use later data.
"""

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from hachi.contracts.base import local_day_bounds
from hachi.contracts.metrics import METRICS, Aggregation, Metric
from hachi.contracts.tables import Observation

from .clock import HOUR, MINUTE, from_us, local_date, to_us
from .config import RESOLUTIONS, PipelineConfig

SLEEP_METRICS = frozenset(m for m in RESOLUTIONS if m.startswith("sleep_"))


@dataclass(frozen=True)
class Obs:
    start: int
    end: int
    value: float
    available: int
    source_id: str
    record_id: str


@dataclass(frozen=True)
class Bin:
    start: int
    end: int
    local_date: date | None


@dataclass(frozen=True)
class BinValue:
    bin: Bin
    value: float | None
    null_reason: str | None
    observed_count: int
    coverage: float
    source_ids: tuple[str, ...]
    available: int


def hour_bins(first: int, last: int) -> list[Bin]:
    start = first - first % HOUR
    stop = last if last % HOUR == 0 else last - last % HOUR + HOUR
    return [Bin(t, t + HOUR, None) for t in range(start, max(stop, start + HOUR), HOUR)]


def day_bins(first: int, last: int, zone: str) -> list[Bin]:
    day, final = local_date(first, ZoneInfo(zone)), local_date(max(first, last - 1), ZoneInfo(zone))
    bins = []
    while day <= final:
        start, end = local_day_bounds(day, zone)
        bins.append(Bin(to_us(start), to_us(end), day))
        day += timedelta(days=1)
    return bins


def coverage_spans(metric: Metric, own: Sequence[Obs], in_bed: Sequence[Obs]) -> list[Obs]:
    if metric in SLEEP_METRICS:
        return sorted(in_bed, key=lambda o: (o.start, o.record_id))
    if metric == "heart_rate":
        minutes: dict[int, int] = {}
        for o in own:
            minute = o.start - o.start % MINUTE
            minutes[minute] = max(minutes.get(minute, o.available), o.available)
        return [Obs(m, m + MINUTE, 0.0, a, "", "") for m, a in sorted(minutes.items())]
    return list(own)


def aggregate(
    metric: Metric,
    aggregation: Aggregation,
    bins: Sequence[Bin],
    observations: Sequence[Obs],
    spans: Sequence[Obs],
    min_coverage: float,
) -> list[BinValue]:
    """Bin one metric. Observations and spans must be sorted by (start, record_id)."""
    kind = METRICS[metric].kind
    ends = [b.end for b in bins]
    n = len(bins)
    count, total = [0] * n, [0.0] * n
    low, high = [float("inf")] * n, [float("-inf")] * n
    available = [b.end for b in bins]
    sources: list[set[str]] = [set() for _ in range(n)]

    def add(i: int, o: Obs) -> None:
        b = bins[i]
        if kind == "amount" and (o.start < b.start or o.end > b.end):
            raise ValueError(f"{o.record_id}: an amount never straddles bins here")
        count[i] += 1
        if kind == "duration":
            overlap = min(o.end, b.end) - max(o.start, b.start)
            total[i] += o.value * overlap / (o.end - o.start)
        else:
            total[i] += o.value
            low[i] = min(low[i], o.value)
            high[i] = max(high[i], o.value)
        available[i] = max(available[i], o.available)
        sources[i].add(o.source_id)

    for o in observations:
        i = bisect_right(ends, o.start)  # first bin ending after the observation starts
        if o.start == o.end:
            if i < n and bins[i].start <= o.start:
                add(i, o)
            continue
        while i < n and bins[i].start < o.end:
            add(i, o)
            i += 1

    covered = [0] * n
    covered_until = [b.start for b in bins]
    for s in spans:
        i = bisect_right(ends, s.start)
        while i < n and bins[i].start < s.end:
            b = bins[i]
            begin = max(s.start, covered_until[i])
            finish = min(s.end, b.end)
            if finish > begin:
                covered[i] += finish - begin
                covered_until[i] = finish
            if count[i]:
                available[i] = max(available[i], s.available)
            i += 1

    out = []
    for i, b in enumerate(bins):
        if count[i] == 0:
            out.append(BinValue(b, None, "no_observations", 0, 0.0, (), b.end))
            continue
        coverage = min(1.0, covered[i] / (b.end - b.start))
        if coverage < min_coverage:
            value, reason = None, "insufficient_coverage"
        elif kind != "level" or aggregation == "sum":
            value, reason = total[i], None
        elif aggregation == "mean":
            value, reason = total[i] / count[i], None
        elif aggregation == "min":
            value, reason = low[i], None
        elif aggregation == "max":
            value, reason = high[i], None
        else:
            raise ValueError(f"{metric} cannot be aggregated with {aggregation}")
        out.append(
            BinValue(b, value, reason, count[i], coverage, tuple(sorted(sources[i])), available[i])
        )
    return out


def subject_grids(by_metric: dict[Metric, list[Obs]], zone: str) -> dict[str, list[Bin]]:
    """Hour and day bins spanning everything one participant recorded."""
    every = [o for obs in by_metric.values() for o in obs]
    if not every:
        return {"hour": [], "day": []}
    first = min(o.start for o in every)
    last = max(o.end if o.end > o.start else o.start + 1 for o in every)
    return {"hour": hour_bins(first, last), "day": day_bins(first, last, zone)}


def subject_aggregates(
    subject: str,
    by_metric: dict[Metric, list[Obs]],
    config: PipelineConfig,
    grids: dict[str, list[Bin]] | None = None,
) -> dict[Literal["hour", "day"], list[dict]]:
    """Aggregate rows (canonical columns plus available_at_utc) for one participant."""
    grids = grids or subject_grids(by_metric, config.local_timezone)
    in_bed = by_metric.get("sleep_in_bed", [])
    out: dict[Literal["hour", "day"], list[dict]] = {"hour": [], "day": []}
    for metric in sorted(RESOLUTIONS):
        own = by_metric.get(metric, [])
        spans = coverage_spans(metric, own, in_bed)
        for resolution in RESOLUTIONS[metric]:
            threshold = getattr(config.min_coverage[metric], resolution)
            for aggregation in config.aggregations_for(metric):
                for v in aggregate(metric, aggregation, grids[resolution], own, spans, threshold):
                    out[resolution].append(
                        {
                            "dataset_id": config.dataset_id,
                            "subject_id": subject,
                            "metric": metric,
                            "unit": METRICS[metric].unit,
                            "resolution": resolution,
                            "interval_start_utc": from_us(v.bin.start),
                            "interval_end_utc": from_us(v.bin.end),
                            "local_date": v.bin.local_date,
                            "tz_name": config.local_timezone if resolution == "day" else None,
                            "aggregation": aggregation,
                            "value": v.value,
                            "null_reason": v.null_reason,
                            "observed_count": v.observed_count,
                            "coverage": v.coverage,
                            "source_ids": list(v.source_ids),
                            "pipeline_version": config.pipeline_version,
                            "available_at_utc": from_us(v.available),
                        }
                    )
    return out


def group_observations(observations: Iterable[Observation]) -> dict[Metric, list[Obs]]:
    """Canonical observations as sorted aggregation inputs (used to recompute as of a cutoff)."""
    grouped: dict[Metric, list[Obs]] = defaultdict(list)
    for o in observations:
        grouped[o.metric].append(
            Obs(
                to_us(o.start_utc),
                to_us(o.end_utc),
                o.value,
                to_us(o.available_at_utc),
                o.source_id,
                o.record_id,
            )
        )
    return {m: sorted(obs, key=lambda o: (o.start, o.record_id)) for m, obs in grouped.items()}
