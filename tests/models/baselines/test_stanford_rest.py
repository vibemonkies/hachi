from datetime import UTC, date, datetime, timedelta

import pytest

from hachi.models.baselines.nightly import NightlyRequest
from hachi.models.baselines.stanford.rest import (
    HeartRatePoint,
    StanfordRestPolicy,
    StepPoint,
    stanford_nightly_rest,
)

START = datetime(2020, 1, 1, tzinfo=UTC)


def request(hours=8):
    return NightlyRequest(
        dataset_id="stanford-covid19-wearables",
        subject_id="generated-person",
        local_date=date(2020, 1, 1),
        tz_name="UTC",
        cutoff=START + timedelta(hours=hours),
    )


def policy(edge="both", minimum=1):
    return StanfordRestPolicy(
        clock="floating_local_shifted",
        step_timestamp=edge,
        min_hr_samples_per_minute=1,
        min_rest_minutes=minimum,
    )


def hr(minute, bpm=60):
    return HeartRatePoint(at=START + timedelta(minutes=minute, seconds=15), bpm=float(bpm))


def step(minute, value=0):
    return StepPoint(at=START + timedelta(minutes=minute), steps=float(value))


def test_edge_assumptions_require_different_recorded_zero_support():
    # Only the shared minute is quiet under either timestamp interpretation.
    source = [step(0), step(1), step(2, 10)]
    points = [hr(0, 60), hr(1, 100)]
    both = stanford_nightly_rest(points, source, request(), policy())
    start = stanford_nightly_rest(points, source, request(), policy("start"))
    end = stanford_nightly_rest(points, source, request(), policy("end"))
    assert both.night.rhr_bpm == 60 and both.night.observed_zero_step_minutes == 1
    assert start.night.rhr_bpm == 80 and start.night.observed_zero_step_minutes == 2
    assert end.night.rhr_bpm == 60 and end.night.observed_zero_step_minutes == 1
    assert both.counts["step_edge_disagreement_minutes"] == 1


def test_absent_steps_and_conflicting_records_stay_unknown():
    points = [hr(0), hr(1)]
    missing = stanford_nightly_rest(points, [], request(), policy())
    conflict = stanford_nightly_rest(points, [step(0), step(0, 3), step(1)], request(), policy())
    assert missing.night.rhr_bpm is None
    assert conflict.night.rhr_bpm is None
    assert conflict.counts["conflicting_step_instants"] == 1
    same = stanford_nightly_rest(points, [step(0), step(0), step(1)], request(), policy())
    assert same.night.observed_zero_step_minutes == 1


def test_hr_duplicates_conflicts_and_equal_minute_weight():
    points = [hr(0, 60), hr(0, 60), hr(1, 100)]
    steps = [step(0), step(1), step(2)]
    r = stanford_nightly_rest(points, steps, request(), policy())
    assert r.night.rhr_bpm == 80
    bad = stanford_nightly_rest([*points, hr(0, 200)], steps, request(), policy())
    assert bad.night.rhr_bpm == 100 and bad.counts["conflicting_hr_instants"] == 1


def test_future_points_cannot_change_earlier_night_or_input_receipt():
    points = [hr(0)]
    steps = [step(0), step(1)]
    earlier = stanford_nightly_rest(points, steps, request(), policy())
    future_hr = HeartRatePoint(at=START + timedelta(hours=9), bpm=299.0)
    future_steps = StepPoint(at=START + timedelta(hours=9), steps=999.0)
    later = stanford_nightly_rest([*points, future_hr], [*steps, future_steps], request(), policy())
    assert earlier.night == later.night
    assert earlier.causal_input_sha256 == later.causal_input_sha256
    incomplete = stanford_nightly_rest(points, steps, request(6), policy())
    assert incomplete.status == "night_incomplete" and incomplete.night.rhr_bpm is None


def test_boundary_step_readiness_and_clock_are_explicit():
    points = [hr(419)]
    steps = [step(419), step(420)]
    at_end = stanford_nightly_rest(points, steps, request(7), policy())
    assert at_end.night.rhr_bpm is None and at_end.counts["steps_unavailable"] == 1
    later = stanford_nightly_rest(points, steps, request(8), policy())
    assert later.night.rhr_bpm == 60
    assert later.night.available_at_utc == START + timedelta(hours=7, minutes=1)
    with pytest.raises(ValueError, match="floating UTC"):
        stanford_nightly_rest(
            points, steps, request().model_copy(update={"tz_name": "Europe/Oslo"}), policy()
        )
