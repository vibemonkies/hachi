from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from hachi.contracts.tables import Observation
from hachi.models.baselines import (
    NightlyFeaturePolicy,
    NightlyRequest,
    RobustConfig,
    nightly_deviation,
    nightly_rest,
)
from hachi.models.baselines.robust import DeviationAbstention

BASE = datetime(2026, 10, 10, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
END = BASE + timedelta(hours=7)


def request(**changes):
    return NightlyRequest.model_validate(
        {
            "dataset_id": "synthetic",
            "subject_id": "generated",
            "local_date": BASE.date(),
            "tz_name": "UTC",
            "cutoff": END,
            **changes,
        }
    )


def policy(**changes):
    return NightlyFeaturePolicy(min_hr_samples_per_minute=1, min_rest_minutes=1, **changes)


def row(metric, minute, value, *, seconds=0, delay=timedelta(0), **changes):
    start = BASE + minute * MINUTE + timedelta(seconds=seconds)
    end = start + MINUTE if metric == "steps" else start
    return Observation.model_validate(
        {
            "dataset_id": "synthetic",
            "subject_id": "generated",
            "record_id": f"generated-{metric}-{minute}-{seconds}-{value}".replace(".", "_"),
            "source_kind": "research_device",
            "source_id": "generated-device",
            "device_model": None,
            "metric": metric,
            "value": float(value),
            "unit": "count" if metric == "steps" else "bpm",
            "start_utc": start,
            "end_utc": end,
            "available_at_utc": end + delay,
            "availability": "assumed",
            "availability_rule": "generated-end-1",
            "tz_name": "UTC",
            "utc_offset_minutes": 0,
            "tz_provenance": "dataset_documentation",
            **changes,
        }
    )


def test_empty_and_silent_step_minutes_are_missing_not_rest():
    empty = nightly_rest([], request(), policy())
    assert empty.status == "insufficient_rest_minutes"
    assert empty.night.rhr_bpm is None and empty.night.observed_zero_step_minutes == 0
    assert empty.night.available_at_utc == END
    assert empty.counts["unobserved_step_minutes"] == 420
    silent = nightly_rest([row("heart_rate", 0, 60)], request(), policy())
    assert silent.night.rhr_bpm is None
    result = nightly_deviation(silent.night, [], RobustConfig(), cutoff=END)
    assert isinstance(result, DeviationAbstention) and result.reason == "missing_rest_measurement"


def test_median_of_minute_medians_equal_weights_minutes_and_reports_denominators():
    data = [row("heart_rate", 0, v, seconds=i * 5) for i, v in enumerate([50, 60, 70])]
    data += [row("heart_rate", 1, 90), row("heart_rate", 2, 110), row("heart_rate", 3, 250)]
    data += [row("steps", i, 0 if i != 3 else 2) for i in range(5)]
    result = nightly_rest(data, request(), policy())
    assert result.status == "observed" and result.night.rhr_bpm == 90.0
    assert result.night.observed_zero_step_minutes == 3.0
    assert result.counts["observed_zero_step_minutes"] == 4
    assert result.counts["zero_step_without_hr_minutes"] == 1
    assert result.counts["observed_step_minutes"] == 5
    assert result.counts["unobserved_step_minutes"] == 415
    categories = [
        "other_metric",
        "outside_window",
        "unavailable",
        "unsupported_hr_interval",
        "accepted_hr_points",
        "accepted_step_minutes",
    ]
    assert sum(result.counts[k] for k in categories) == result.counts["input_records"]


def test_native_hr_density_and_rest_minutes_are_explicit_inclusion_policy():
    data = [
        row("steps", 0, 0),
        row("steps", 1, 0),
        row("heart_rate", 0, 60),
        row("heart_rate", 0, 80, seconds=5),
        row("heart_rate", 1, 250),
    ]
    config = NightlyFeaturePolicy(min_hr_samples_per_minute=2, min_rest_minutes=2)
    result = nightly_rest(data, request(), config)
    assert result.night.rhr_bpm is None and result.counts["rest_minutes"] == 1
    assert result.counts["low_hr_sample_minutes"] == 1
    selected = nightly_rest(data, request(), config.model_copy(update={"min_rest_minutes": 1}))
    assert selected.night.rhr_bpm == 70.0


def test_withheld_future_values_cannot_change_earlier_night_or_causal_hash():
    known = [row("steps", 0, 0), row("heart_rate", 0, 60)]
    baseline = nightly_rest(known, request(), policy())
    late = row("heart_rate", 0, 250, seconds=5, delay=timedelta(days=1))
    future = row("heart_rate", 500, 300)
    changed = nightly_rest([*known, late, future], request(), policy())
    assert changed.night == baseline.night
    assert changed.causal_input_sha256 == baseline.causal_input_sha256
    assert changed.counts["unavailable"] == 2
    later = nightly_rest([*known, late], request(cutoff=END + timedelta(days=1)), policy())
    assert later.night.rhr_bpm == 155.0
    assert later.night.available_at_utc == late.available_at_utc


def test_incomplete_night_cannot_be_an_observed_rest_value():
    result = nightly_rest(
        [row("steps", 0, 0), row("heart_rate", 0, 60)],
        request(cutoff=BASE + timedelta(hours=3)),
        policy(),
    )
    assert result.status == "night_incomplete" and result.night.rhr_bpm is None
    assert result.night.available_at_utc == END


@pytest.mark.parametrize(
    "local_date,expected_minutes", [(date(2026, 11, 1), 480), (date(2026, 3, 8), 360)]
)
def test_local_night_minute_denominators_follow_dst(local_date, expected_minutes):
    result = nightly_rest(
        [],
        request(
            local_date=local_date,
            tz_name="America/Los_Angeles",
            cutoff=datetime(2026, 11, 2, tzinfo=UTC),
        ),
        policy(),
    )
    assert result.counts["night_minutes"] == expected_minutes
    assert result.counts["unobserved_step_minutes"] == expected_minutes


@pytest.mark.parametrize(
    "changes",
    [
        {"end_utc": BASE + 2 * MINUTE},
        {"start_utc": BASE + timedelta(seconds=5)},
        {"start_utc": BASE - MINUTE, "end_utc": BASE + MINUTE},
    ],
)
def test_unsupported_step_spans_cannot_silently_claim_a_quiet_minute(changes):
    bad = row("steps", 0, 0, **changes)
    with pytest.raises(ValueError, match="aligned one-minute"):
        nightly_rest([bad], request(), policy())


def test_vendor_rhr_and_hr_spans_are_audited_but_not_used():
    data = [
        row("steps", 0, 0),
        row("resting_heart_rate_vendor", 0, 60),
        row("heart_rate", 0, 80, end_utc=BASE + MINUTE),
    ]
    result = nightly_rest(data, request(), policy())
    assert result.night.rhr_bpm is None
    assert result.counts["other_metric"] == 1 and result.counts["unsupported_hr_interval"] == 1


def test_duplicate_events_wrong_roster_and_non_utc_cutoff_are_refused():
    record = row("steps", 0, 0)
    duplicate = Observation.model_validate({**record.model_dump(), "record_id": "duplicate"})
    with pytest.raises(ValueError, match="duplicate native"):
        nightly_rest([record, duplicate], request(), policy())
    with pytest.raises(ValueError, match="dataset and participant"):
        nightly_rest([record], request(subject_id="other"), policy())
    with pytest.raises(ValidationError):
        request(cutoff=END.replace(tzinfo=None))
