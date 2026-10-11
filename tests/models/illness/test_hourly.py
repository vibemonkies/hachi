"""Native context construction must be causal and preserve unknown coverage."""

import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hachi.models.illness.hourly import (
    NativePoint,
    causal_hours,
    load_context_protocol,
    read_native_context,
)

PROTOCOL = load_context_protocol(Path("configs/experiments/illness/clinical-contexts.toml"))
START = datetime(2020, 1, 1, tzinfo=UTC)


def point(minute, value=60.0, metric="heart_rate", delay=0):
    at = START + timedelta(minutes=minute)
    return NativePoint(
        at=at, available_at=at + timedelta(minutes=delay), metric=metric, value=value
    )


def test_hr_minute_weighting_missing_quality_and_future_invariance():
    protocol = PROTOCOL.model_copy(update={"context_hours": 1, "min_observed_hr_hours": 1})
    rows = [point(m, 60 if m < 15 else 80) for m in range(30)]
    # Dense sampling must not weight one minute more than another minute.
    rows += [
        NativePoint(
            at=START + timedelta(seconds=s),
            available_at=START + timedelta(seconds=s),
            metric="heart_rate",
            value=60.0,
        )
        for s in range(1, 60)
    ]
    cutoff = START + timedelta(hours=1)
    hour = causal_hours(rows, cutoff, protocol)[0]
    assert hour.hr_bpm == 70 and hour.recorded_hr_minutes == 30
    assert hour.steps_total is None and hour.complete_step_minutes == 0
    perturbed = [*rows, point(61, 200), point(29, 300, delay=120)]
    assert causal_hours(perturbed, cutoff, protocol) == (hour,)
    assert causal_hours([point(m) for m in range(29)], cutoff, protocol)[0].hr_bpm is None
    # An HR value exactly at cutoff belongs to the next incomplete hour.
    assert causal_hours([*rows, point(60, 200)], cutoff, protocol) == (hour,)


def test_duplicate_conflicts_and_backdated_availability():
    protocol = PROTOCOL.model_copy(update={"context_hours": 2, "min_observed_hr_hours": 1})
    rows = [point(m) for m in range(30)]
    cutoff = START + timedelta(hours=2)
    identical = causal_hours([*rows, point(0)], cutoff, protocol)[0]
    assert identical.hr_bpm == 60 and identical.recorded_hr_minutes == 30
    conflict = causal_hours([*rows, point(0, 70)], cutoff, protocol)[0]
    assert conflict.hr_bpm is None and conflict.recorded_hr_minutes == 29
    late = [point(m, delay=90) for m in range(30)]
    hour = causal_hours(late, cutoff, protocol)[0]
    assert hour.hr_bpm == 60
    assert hour.available_at == START + timedelta(minutes=119)
    earlier_protocol = protocol.model_copy(update={"context_hours": 1})
    assert causal_hours(late, START + timedelta(hours=1), earlier_protocol)[0].hr_bpm is None


def test_both_step_edges_require_complete_ready_equal_totals():
    protocol = PROTOCOL.model_copy(update={"context_hours": 2, "min_observed_hr_hours": 1})
    rows = [point(m, 0, "steps", 1) for m in range(121)]
    hours = causal_hours(rows, START + timedelta(hours=2), protocol)
    assert hours[0].steps_total == 0 and hours[0].complete_step_minutes == 60
    assert hours[1].steps_total is None and hours[1].complete_step_minutes == 59
    rows[0] = point(0, 1, "steps", 1)
    assert causal_hours(rows, START + timedelta(hours=2), protocol)[0].steps_total is None
    assert causal_hours([], START + timedelta(hours=2), protocol)[0].steps_total is None


def test_native_stream_is_bounded_without_requiring_steps(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import hachi.models.illness.hourly as hourly

    member = SimpleNamespace(
        subject_id="synthetic", source="standard", stream="heart_rate", name="synthetic.csv"
    )
    monkeypatch.setattr(hourly, "phase1_members", lambda _: [member])
    archive = tmp_path / "native.zip"
    content = (
        "user,datetime,heartrate\n"
        "synthetic,2020-01-01T00:00:00,60\n"
        "synthetic,2020-01-01T01:01:00,200\n"
        "other,2020-01-01T00:00:00,60\n"
        "synthetic,2020-01-01T00:01:00Z,60\n"
        "synthetic,2020-01-01T00:02:00,nan\n"
        "synthetic,2020-01-01T00:03:00,301\n"
    )
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(member.name, content)
    protocol = PROTOCOL.model_copy(update={"context_hours": 1, "min_observed_hr_hours": 1})
    native = read_native_context(archive, "synthetic", [START + timedelta(hours=1)], protocol)
    assert native.points == (point(0),)
    assert native.counts["heart_rate:source_rows"] == 6
    assert native.counts["heart_rate:quarantined_subject"] == 1
    assert native.counts["heart_rate:quarantined_value_time"] == 3
    assert native.counts["heart_rate:outside_requested_windows"] == 1
    assert len(native.source_sha256) == 64
    monkeypatch.setattr(hourly, "phase1_members", lambda _: [member, member])
    with pytest.raises(ValueError, match="duplicate standard"):
        read_native_context(archive, "synthetic", [START + timedelta(hours=1)], protocol)


def test_context_clock_rejects_unaligned_and_naive_cutoffs():
    with pytest.raises(ValueError, match="aligned"):
        causal_hours([], START + timedelta(minutes=1), PROTOCOL)
    with pytest.raises(ValueError, match="aligned"):
        causal_hours([], START.replace(tzinfo=None), PROTOCOL)
