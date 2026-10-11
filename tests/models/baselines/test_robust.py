from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from hachi.contracts.requests import ConfounderEntry
from hachi.models.baselines.robust import (
    DeviationAbstention,
    DeviationScore,
    NightlyRest,
    RobustConfig,
    nightly_deviation,
)

BASE = datetime(2026, 10, 10, tzinfo=UTC)
DAY = timedelta(days=1)
HOUR = timedelta(hours=1)


def night(day, value=60.0, *, delay=0, minutes=60.0):
    start = BASE + day * DAY
    end = start + 7 * HOUR
    return NightlyRest(
        subject_id="generated",
        local_date=start.date(),
        tz_name="UTC",
        start_utc=start,
        end_utc=end,
        available_at_utc=end + delay * DAY,
        rhr_bpm=value,
        observed_zero_step_minutes=minutes,
    )


def test_median_mad_excludes_current_night_and_uses_explicit_scale_floor():
    target = night(0, 70.0)
    history = [night(d) for d in range(-7, 0)]
    result = nightly_deviation(target, [*history, target], RobustConfig(), cutoff=target.end_utc)
    assert isinstance(result, DeviationScore)
    assert result.baseline_median_bpm == 60.0
    assert result.scale_bpm == 1.0 and result.robust_z == 10.0 and result.alert
    assert result.model_id == "causal-nightly-mad-v1"
    assert "illness_probability" not in result.model_dump()


def test_future_and_backdated_nights_cannot_inform_an_earlier_score():
    target = night(0, 70.0)
    history = [night(d) for d in range(-7, 0)]
    extra = [night(-8, 250.0, delay=10), night(1, 250.0)]
    initial = nightly_deviation(target, history, RobustConfig(), cutoff=target.end_utc)
    changed = nightly_deviation(target, history + extra, RobustConfig(), cutoff=target.end_utc)
    assert changed == initial
    unavailable = nightly_deviation(
        night(0, 70.0, delay=1), history, RobustConfig(), cutoff=target.end_utc
    )
    assert isinstance(unavailable, DeviationAbstention)
    assert unavailable.reason == "night_unavailable"


def test_missing_steps_and_cold_start_abstain_without_imputing_a_night():
    target = night(0)
    result = nightly_deviation(
        target,
        [night(d) for d in range(-6, 0)] + [night(-7, None, minutes=0.0)],
        RobustConfig(),
        cutoff=target.end_utc,
    )
    assert isinstance(result, DeviationAbstention) and result.reason == "cold_start"
    assert result.baseline_nights == 6 and result.excluded_missing_nights == 1
    missing = nightly_deviation(
        night(0, 60.0, minutes=0.0), [], RobustConfig(), cutoff=target.end_utc
    )
    assert isinstance(missing, DeviationAbstention)
    assert missing.reason == "missing_rest_measurement"


def test_only_confounders_recorded_by_cutoff_are_reported_or_excluded():
    target = night(0, 70.0)
    history = [night(d) for d in range(-8, 0)]
    prior = ConfounderEntry(
        kind="confounder",
        entry_id="prior",
        factor="alcohol",
        occurred_earliest_utc=history[0].start_utc,
        occurred_latest_utc=history[0].end_utc,
        entered_at_utc=history[0].end_utc,
    )
    current = ConfounderEntry(
        kind="confounder",
        entry_id="current",
        factor="sleep_loss",
        occurred_earliest_utc=target.start_utc,
        occurred_latest_utc=target.end_utc,
        entered_at_utc=target.end_utc,
    )
    late = ConfounderEntry.model_validate(
        {**current.model_dump(), "entered_at_utc": target.end_utc + DAY, "factor": "travel"}
    )
    result = nightly_deviation(
        target, history, RobustConfig(), cutoff=target.end_utc, confounders=[prior, current, late]
    )
    assert isinstance(result, DeviationScore)
    assert result.baseline_nights == 7 and result.excluded_confounder_nights == 1
    assert result.known_confounders == ("sleep_loss",)


def test_upward_and_two_sided_scores_keep_signed_deviation():
    target = night(0, 50.0)
    history = [night(d) for d in range(-7, 0)]
    up = nightly_deviation(target, history, RobustConfig(direction="up"), cutoff=target.end_utc)
    two = nightly_deviation(target, history, RobustConfig(), cutoff=target.end_utc)
    assert isinstance(up, DeviationScore) and isinstance(two, DeviationScore)
    assert up.robust_z == two.robust_z == -10.0
    assert up.score == 0.0 and not up.alert and two.score == 10.0 and two.alert


def test_boundary_refuses_bad_coverage_mixed_subjects_and_duplicate_intervals():
    target = night(0)
    with pytest.raises(ValidationError, match="quiet minutes"):
        night(-1, minutes=500.0)
    with pytest.raises(ValueError, match="non-overlapping"):
        nightly_deviation(target, [night(-1), night(-1)], RobustConfig(), cutoff=target.end_utc)
    other = NightlyRest.model_validate({**night(-1).model_dump(), "subject_id": "other"})
    with pytest.raises(ValueError, match="participant"):
        nightly_deviation(target, [other], RobustConfig(), cutoff=target.end_utc)


def test_local_night_boundaries_follow_dst_and_refuse_fragmented_nights():
    from datetime import date

    shifted = NightlyRest(
        subject_id="generated",
        local_date=date(2026, 11, 1),
        tz_name="America/Los_Angeles",
        start_utc=datetime(2026, 11, 1, 7, tzinfo=UTC),
        end_utc=datetime(2026, 11, 1, 15, tzinfo=UTC),
        available_at_utc=datetime(2026, 11, 1, 15, tzinfo=UTC),
        rhr_bpm=60.0,
        observed_zero_step_minutes=480.0,
    )
    assert (shifted.end_utc - shifted.start_utc).total_seconds() == 8 * 3600
    with pytest.raises(ValidationError, match="complete local"):
        NightlyRest.model_validate({**night(-1).model_dump(), "end_utc": BASE - DAY + 4 * HOUR})
