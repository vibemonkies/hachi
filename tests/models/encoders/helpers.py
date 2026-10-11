"""Tiny generated PMData-shaped hourly bins; never a real participant row."""

from datetime import UTC, datetime, timedelta

from hachi.contracts.manifests import TimeWindow
from hachi.contracts.tables import Aggregate, Observation
from hachi.data.pmdata import FeatureBin
from hachi.evaluation import ForecastInput

HOUR = timedelta(hours=1)
# 2020-01-08 00:00 Europe/Oslo (UTC+1 in winter).
MIDNIGHT = datetime(2020, 1, 7, 23, tzinfo=UTC)
UNITS = {
    "heart_rate": "bpm",
    "steps": "count",
    "walking_running_distance": "m",
}


def hourly(
    subject: str,
    metric: str,
    start: datetime,
    value: float | None,
    *,
    available: datetime | None = None,
    aggregation: str | None = None,
) -> FeatureBin:
    aggregation = aggregation or ("mean" if metric == "heart_rate" else "sum")
    row = Aggregate(
        dataset_id="synthetic",
        subject_id=subject,
        metric=metric,
        unit=UNITS.get(metric, "s"),
        resolution="hour",
        interval_start_utc=start,
        interval_end_utc=start + HOUR,
        local_date=None,
        tz_name=None,
        aggregation=aggregation,
        value=value,
        null_reason=None if value is not None else "no_observations",
        observed_count=0 if value is None else 60,
        coverage=0.0 if value is None else 1.0,
        source_ids=[] if value is None else ["generated"],
        pipeline_version="synthetic-1",
    )
    return FeatureBin(row, available or start + HOUR)


def week(
    subject: str, end: datetime = MIDNIGHT, days: int = 8, hr: float = 60.0
) -> list[FeatureBin]:
    """Hourly heart rate and steps; a 23:00-07:00 local sleep log each night, final at 07:00."""
    bins = []
    start = end - days * 24 * HOUR
    for h in range(days * 24):
        t = start + h * HOUR
        bins.append(hourly(subject, "heart_rate", t, hr + (h % 24)))
        bins.append(hourly(subject, "steps", t, float(10 * (h % 24))))
        bins.append(hourly(subject, "walking_running_distance", t, float(7 * (h % 24))))
        local_hour = (t.hour + 1) % 24
        if local_hour >= 23 or local_hour < 7:
            wake = t + ((7 - local_hour) % 24) * HOUR
            bins.append(hourly(subject, "sleep_in_bed", t, 3600.0, available=wake))
            bins.append(hourly(subject, "sleep_asleep_core", t, 3000.0, available=wake))
    return bins


BASE = datetime(2026, 10, 10, tzinfo=UTC)


def row(subject: str, hour: int, value: float) -> Observation:
    start = BASE + hour * HOUR
    return Observation(
        dataset_id="synthetic",
        subject_id=subject,
        record_id=f"{subject}-{hour}-{value}".replace(".", "_"),
        source_kind="research_device",
        source_id="generated",
        device_model=None,
        metric="heart_rate",
        unit="bpm",
        value=value,
        start_utc=start,
        end_utc=start + timedelta(minutes=15),
        available_at_utc=start + timedelta(minutes=15),
        availability="observed",
        availability_rule=None,
        tz_name="UTC",
        utc_offset_minutes=0,
        tz_provenance="dataset_documentation",
    )


def request(history=(), *, subject="held-out", cutoff=BASE, horizon=2) -> ForecastInput:
    return ForecastInput(
        subject,
        cutoff,
        tuple(
            TimeWindow(start_utc=cutoff + h * HOUR, end_utc=cutoff + (h + 1) * HOUR)
            for h in range(horizon)
        ),
        tuple(history),
    )
