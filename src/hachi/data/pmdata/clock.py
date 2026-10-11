"""Which clock each PMData timestamp is on, as integer UTC microseconds.

Fitbit intraday series (heart rate, steps, distance, calories) are written in UTC without an
offset. Sleep logs are local wall time. PMSys wellness carries a real `Z`. The build audit
re-measures the intraday/sleep alignment rather than trusting this module.
"""

from datetime import UTC, date, datetime, timedelta
from functools import cache
from zoneinfo import ZoneInfo

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
SECOND = 1_000_000
MINUTE = 60 * SECOND
HOUR = 60 * MINUTE
DAY = 24 * HOUR


def to_us(moment: datetime) -> int:
    if moment.utcoffset() is None:
        raise ValueError("an aware datetime is required")
    delta = moment - EPOCH
    return (delta.days * 86_400 + delta.seconds) * SECOND + delta.microseconds


def from_us(value: int) -> datetime:
    return EPOCH + timedelta(microseconds=value)


@cache
def _day_us(day: str) -> int:
    return to_us(datetime.fromisoformat(day).replace(tzinfo=UTC))


def intraday_us(stamp: str) -> int:
    """'YYYY-MM-DD HH:MM:SS' read as UTC (format already checked by the parser)."""
    return (
        _day_us(stamp[:10])
        + (int(stamp[11:13]) * 3600 + int(stamp[14:16]) * 60 + int(stamp[17:19])) * SECOND
    )


def local_us(naive: datetime, zone: ZoneInfo) -> int | None:
    """A local wall time as UTC, or None when DST makes it nonexistent or ambiguous."""
    early = naive.replace(tzinfo=zone, fold=0)
    late = naive.replace(tzinfo=zone, fold=1)
    if early.utcoffset() != late.utcoffset():
        return None
    if early.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
        return None
    return to_us(early)


def local_day_us(day: date, zone: ZoneInfo) -> tuple[int, int]:
    """UTC bounds of one local calendar day (23 or 25 hours across DST)."""
    start = datetime.combine(day, datetime.min.time(), zone)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), zone)
    return to_us(start), to_us(end)


def local_date(value_us: int, zone: ZoneInfo) -> date:
    return from_us(value_us).astimezone(zone).date()
