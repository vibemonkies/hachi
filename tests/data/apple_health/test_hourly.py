"""Generated native inputs prove causal transport semantics, not Apple accuracy."""

from datetime import UTC, datetime, timedelta

import pytest

from hachi.data.apple_health.hourly import (
    AVAILABILITY_RULE,
    apple_hourly_features,
    iter_hourly_bins,
)
from hachi.evaluation.features import HourlyFeaturePolicy

from .test_importer import record, run

START = datetime(2026, 10, 10, 7, tzinfo=UTC)
HOUR = timedelta(hours=1)


def native(minute=0, *, end=None, created=None, steps=False, **changes):
    stamp = START + timedelta(minutes=minute)
    return record(
        **{
            "startDate": stamp.isoformat(),
            "endDate": (end or stamp).isoformat(),
            "creationDate": (created or stamp).isoformat(),
            "type": "HKQuantityTypeIdentifierStepCount"
            if steps
            else "HKQuantityTypeIdentifierHeartRate",
            "unit": "count" if steps else "count/min",
            **changes,
        }
    )


def policy(**changes):
    return HourlyFeaturePolicy(
        **{
            "metric": "heart_rate",
            "aggregation": "mean",
            "min_coverage": 0.5,
            "min_observed_count": 30,
            "availability_rule": AVAILABILITY_RULE,
            **changes,
        }
    )


def bins(path, *, as_of=START + HOUR, start=START, metric="heart_rate", aggregation="mean"):
    return list(
        iter_hourly_bins(path, metric=metric, aggregation=aggregation, as_of=as_of, start=start)
    )


def test_dense_hr_native_mean_units_sources_and_density(tmp_path, config):
    records = [native(m, value=str(60 + m)) for m in range(30)]
    _, _, path = run(tmp_path, config, records)
    (item,) = bins(path)
    assert item.aggregate.value == 74.5
    assert item.aggregate.unit == "bpm"
    assert item.aggregate.observed_count == 30
    assert item.aggregate.coverage == 0.5
    assert len(item.aggregate.source_ids) == 1
    assert item.audit.sample_minutes == 30
    assert item.audit.interval_seconds == 0
    assert item.audit.source_counts == ((item.aggregate.source_ids[0], 30),)
    assert item.available_at_utc == START + HOUR
    view = apple_hourly_features(path, policy(), START + HOUR)
    assert view.counts["included"] == 1
    assert view.features[0].availability_rule == AVAILABILITY_RULE


def test_sample_count_does_not_fabricate_continuous_hr_support(tmp_path, config):
    records = [native(m / 100, value="70") for m in range(60)]
    _, _, path = run(tmp_path, config, records)
    (item,) = bins(path)
    assert item.aggregate.observed_count == 60
    assert item.aggregate.coverage == 1 / 60
    assert item.audit.sample_minutes == 1
    view = apple_hourly_features(path, policy(), START + HOUR)
    assert not view.features and view.counts["low_coverage"] == 1


def test_model_count_gate_preserved_even_when_coverage_passes(tmp_path, config):
    _, _, path = run(tmp_path, config, [native(m) for m in range(30)])
    view = apple_hourly_features(path, policy(min_observed_count=31), START + HOUR)
    assert not view.features and view.counts["low_count"] == 1


def test_late_batch_updates_do_not_change_previously_known_hour(tmp_path, config):
    phone = [native(m, sourceName="Synthetic iPhone", device="", value="65") for m in range(30)]
    late = [native(m, value="90", created=START + 2 * HOUR) for m in range(30)]
    _, _, first = run(tmp_path / "first", config, phone)
    _, _, later = run(tmp_path / "later", config, [*reversed(late), *reversed(phone)])
    early = apple_hourly_features(first, policy(), START + HOUR, START)
    for cutoff in (START + HOUR, START + 3 * HOUR):
        updated = apple_hourly_features(later, policy(), cutoff, START)
        assert updated.features == early.features
        assert updated.features[0].record_id == early.features[0].record_id
        assert updated.features[0].available_at_utc == START + HOUR


def test_creation_and_event_end_are_both_sealed_not_query_cutoff(tmp_path, config):
    records = [
        native(10, value="62"),
        native(20, value="95", created=START + HOUR + timedelta(microseconds=1)),
        native(30, value="99", end=START + HOUR + timedelta(microseconds=1)),
        native(40, value="64", created=START + HOUR),
    ]
    _, _, path = run(tmp_path, config, records)
    assert bins(path, as_of=START + HOUR - timedelta(microseconds=1)) == []
    a = bins(path)[0]
    b = bins(path, as_of=START + 2 * HOUR)[0]
    assert a == b
    assert a.aggregate.value == 63
    assert a.aggregate.observed_count == 2


def test_exact_duplicates_and_source_precedence_are_importer_owned(tmp_path, config):
    rows = [
        native(10, sourceName="Synthetic iPhone", device="", value="60"),
        native(10, value="80"),
    ]
    _, _, a = run(tmp_path / "a", config, [*rows, rows[1]])
    _, _, b = run(tmp_path / "b", config, list(reversed(rows)))
    assert bins(a) == bins(b)
    assert bins(a)[0].aggregate.value == 80
    assert bins(a)[0].aggregate.observed_count == 1


def test_steps_sum_recorded_interval_support_not_missing_zero(tmp_path, config):
    records = [
        native(0, end=START + timedelta(minutes=30), steps=True, value="300"),
        native(30, end=START + HOUR, steps=True, value="0"),
    ]
    _, _, path = run(tmp_path, config, records)
    first, missing = bins(path, metric="steps", aggregation="sum", as_of=START + 2 * HOUR)
    assert first.aggregate.value == 300 and first.aggregate.coverage == 1
    assert first.aggregate.observed_count == 2 and first.audit.interval_seconds == 3600
    assert first.aggregate.unit == "count"
    assert missing.aggregate.value is None
    assert missing.aggregate.null_reason == "no_observations"
    assert missing.aggregate.coverage == 0


def test_cross_hour_amounts_excluded_whole_and_point_steps_have_zero_support(tmp_path, config):
    rows = [
        native(-10, end=START + timedelta(minutes=10), steps=True, value="100"),
        native(30, steps=True, value="10"),
    ]
    _, _, path = run(tmp_path, config, rows)
    (item,) = bins(path, metric="steps", aggregation="sum")
    assert item.aggregate.value == 10
    assert item.aggregate.coverage == 0
    assert item.audit.excluded_cross_hour == 1
    assert item.audit.interval_seconds == 0
    view = apple_hourly_features(
        path, policy(metric="steps", aggregation="sum", min_observed_count=1), START + HOUR, START
    )
    assert not view.features and view.counts["low_coverage"] == 1


def test_overlapping_steps_not_prorated_or_double_counted(tmp_path, config):
    rows = [
        native(
            0, end=START + HOUR, steps=True, value="100", sourceName="Synthetic iPhone", device=""
        ),
        native(10, end=START + timedelta(minutes=20), steps=True, value="20"),
    ]
    _, _, path = run(tmp_path, config, rows)
    (item,) = bins(path, metric="steps", aggregation="sum")
    assert item.aggregate.value == 20
    assert item.aggregate.observed_count == 1
    assert item.aggregate.coverage == 1 / 6


def test_vendor_rhr_not_native_hr_and_missing_metric_remains_empty(tmp_path, config):
    rows = [native(type="HKQuantityTypeIdentifierRestingHeartRate")]
    _, _, path = run(tmp_path, config, rows)
    assert bins(path) == []
    assert bins(path, metric="steps", aggregation="sum") == []


def test_utc_bins_offsets_and_start_filter(tmp_path, config):
    row = native(60)
    for field in ("startDate", "endDate", "creationDate"):
        row[field] = "2026-10-10T01:00:00-07:00"
    _, _, path = run(tmp_path, config, [native(0), row])
    a, b = bins(path, as_of=START + 2 * HOUR)
    assert a.aggregate.interval_start_utc == START
    assert b.aggregate.interval_start_utc == START + HOUR
    assert bins(path, as_of=START + 2 * HOUR, start=START + timedelta(seconds=1)) == [b]


@pytest.mark.parametrize(
    "aggregation,expected", [("min", 60), ("max", 80), ("mean", 70), ("median", 70)]
)
def test_hr_level_aggregations(tmp_path, config, aggregation, expected):
    _, _, path = run(tmp_path, config, [native(0, value="60"), native(1, value="80")])
    assert bins(path, aggregation=aggregation)[0].aggregate.value == expected


def test_reject_foreign_rule_and_unsupported_native_metrics(tmp_path, config):
    _, _, path = run(tmp_path, config, [native()])
    with pytest.raises(ValueError, match="source-specific"):
        apple_hourly_features(
            path, policy(availability_rule="pmdata-aggregate-final-at-latest-input"), START + HOUR
        )
    with pytest.raises(ValueError, match="only native"):
        apple_hourly_features(path, policy(metric="resting_heart_rate_vendor"), START + HOUR)
    with pytest.raises(ValueError, match="aggregation"):
        bins(path, aggregation="sum")
    with pytest.raises(ValueError, match="aware"):
        bins(path, as_of=datetime(2026, 10, 10))
