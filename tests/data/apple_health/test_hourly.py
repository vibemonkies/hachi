"""Generated native inputs prove causal transport semantics, not Apple accuracy."""

import hashlib
import random
from datetime import UTC, datetime, timedelta
from statistics import fmean

import pytest

from hachi.data.apple_health import hourly, iter_observations
from hachi.data.apple_health.hourly import (
    AVAILABILITY_RULE,
    _iter_hourly_bins,
    apple_hourly_features,
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
    return [
        item
        for item, _ in _iter_hourly_bins(
            path, metric=metric, aggregation=aggregation, as_of=as_of, start=start
        )
    ]


def test_dense_hr_native_mean_units_sources_and_density(tmp_path, config):
    records = [native(m, value=str(60 + m)) for m in range(30)]
    _, _, path = run(tmp_path, config, records)
    (item,) = bins(path)
    assert item.aggregate.value == 74.5
    assert item.aggregate.unit == "bpm"
    assert item.aggregate.observed_count == 30
    assert item.aggregate.coverage == 0.5
    assert len(item.aggregate.source_ids) == 1
    assert item.sample_minutes == 30
    assert item.interval_seconds == 0
    assert item.source_counts == ((item.aggregate.source_ids[0], 30),)
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
    assert item.sample_minutes == 1
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
    assert first.aggregate.observed_count == 2 and first.interval_seconds == 3600
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
    assert item.interval_seconds == 0
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
    assert not hasattr(hourly, "iter_hourly_bins")
    assert not hasattr(hourly, "AppleFeatureBin")
    assert hourly.__all__ == [
        "AVAILABILITY_RULE",
        "AppleHourlyView",
        "HourAudit",
        "apple_hourly_features",
    ]


def test_late_audit_counts_only_known_candidates_and_preserves_feature_identity(tmp_path, config):
    phone = [native(m, sourceName="Synthetic iPhone", device="", value="65") for m in range(30)]
    seal = START + HOUR
    cutoff = seal + timedelta(minutes=10)
    late = native(10, value="90", created=cutoff)
    future_created = native(11, value="92", created=cutoff + timedelta(microseconds=1))
    future_end = native(12, value="94", created=cutoff, end=cutoff + timedelta(microseconds=1))
    _, _, original = run(tmp_path / "original", config, phone)
    _, _, amended = run(
        tmp_path / "amended", config, [*phone, late, late, future_created, future_end]
    )
    before = apple_hourly_features(original, policy(), seal, START)
    early = apple_hourly_features(amended, policy(), seal, START)
    visible = apple_hourly_features(amended, policy(), cutoff, START)
    later = apple_hourly_features(amended, policy(), cutoff + timedelta(microseconds=1), START)
    assert before.features == early.features == visible.features == later.features
    assert (
        before.audits == early.audits
    )  # sentinel additions are wholly invisible at the old cutoff
    assert early.audits[0].excluded_created_after_seal == 0
    assert visible.audits[0].excluded_created_after_seal == 1  # exact duplicate counted once
    assert visible.audits[0].known_candidates == 31
    assert later.audits[0].excluded_created_after_seal == 3
    assert later.audits[0].audit_as_of_utc == cutoff + timedelta(microseconds=1)
    assert visible.features[0].record_id == before.features[0].record_id
    assert visible.features[0].available_at_utc == seal


def test_audit_reasons_are_exclusive_and_precedence_is_at_closure(tmp_path, config):
    rows = [
        native(10, sourceName="Synthetic iPhone", device="", value="60"),
        native(10, value="80"),
        native(20, created=START + HOUR + timedelta(minutes=1)),
        native(30, end=START + HOUR + timedelta(minutes=10)),
        native(40, end=START + HOUR + timedelta(minutes=10), created=START + 2 * HOUR),
    ]
    _, _, path = run(tmp_path, config, rows)
    audit = apple_hourly_features(path, policy(), START + 2 * HOUR, START).audits[0]
    assert audit.known_candidates == 5
    assert audit.included_records == 1
    assert audit.excluded_created_after_seal == 2  # late crossing candidate attributed here only
    assert audit.excluded_cross_hour == 1
    assert audit.excluded_by_precedence == 1
    assert audit.known_candidates == (
        audit.included_records
        + audit.excluded_created_after_seal
        + audit.excluded_cross_hour
        + audit.excluded_by_precedence
    )


def test_all_late_native_history_has_a_missing_bin_and_visible_audit(tmp_path, config):
    _, _, path = run(tmp_path, config, [native(10, created=START + HOUR + timedelta(minutes=5))])
    view = apple_hourly_features(path, policy(), START + HOUR + timedelta(minutes=5), START)
    assert not view.features
    assert view.counts["missing"] == 1
    assert view.audits[0].excluded_created_after_seal == 1
    assert view.audits[0].included_records == 0


def test_crossing_winner_suppresses_contained_loser_and_audits_its_start_hour(tmp_path, config):
    rows = [
        native(-10, end=START + timedelta(minutes=10), steps=True, value="100"),
        native(
            0,
            end=START + timedelta(minutes=5),
            steps=True,
            value="10",
            sourceName="Synthetic iPhone",
            device="",
        ),
    ]
    _, _, path = run(tmp_path, config, rows)
    view = apple_hourly_features(
        path,
        policy(metric="steps", aggregation="sum", min_observed_count=1),
        START + HOUR,
        START - HOUR,
    )
    assert not view.features
    earlier, current = view.audits
    assert earlier.excluded_cross_hour == 1 and earlier.known_candidates == 1
    assert current.excluded_by_precedence == 1 and current.known_candidates == 1
    assert current.included_records == 0


def test_public_audited_view_keeps_recorded_zero_duration_and_snapshot_read_only(tmp_path, config):
    _, _, path = run(tmp_path, config, [native(0, steps=True, end=START + HOUR, value="0")])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    view = apple_hourly_features(
        path,
        policy(metric="steps", aggregation="sum", min_observed_count=1),
        START + 2 * HOUR,
        START,
    )
    assert len(view.features) == 1 and view.features[0].value == 0
    assert view.audits[0].interval_seconds == 3600
    assert view.audits[1].known_candidates == 0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_generated_replay_matches_importer_oracle_with_hostile_intervals(tmp_path, config):
    rng = random.Random(42)
    records = []
    for _ in range(160):
        minute = rng.randrange(240)
        event = START + timedelta(minutes=minute)
        steps = rng.choice([True, False])
        records.append(
            native(
                minute,
                steps=steps,
                value=str(rng.randrange(0, 200) if steps else rng.randrange(40, 120)),
                end=event + timedelta(minutes=rng.choice([0, 5, 65])),
                created=event + timedelta(minutes=rng.choice([0, 20, 140])),
                sourceName=rng.choice(["Synthetic Apple Watch", "Synthetic iPhone"]),
                device="",
            )
        )
    _, _, path = run(tmp_path, config, records)
    for metric, aggregation in (("heart_rate", "mean"), ("steps", "sum")):
        replay = bins(path, metric=metric, aggregation=aggregation, as_of=START + 6 * HOUR)
        for item in replay:
            row = item.aggregate
            selected = [
                o
                for o in iter_observations(path, as_of=row.interval_end_utc)
                if o.metric == metric
                and row.interval_start_utc <= o.start_utc < row.interval_end_utc
                and o.end_utc <= row.interval_end_utc
            ]
            assert row.observed_count == len(selected)
            expected = (
                (
                    fmean(o.value for o in selected)
                    if metric == "heart_rate"
                    else sum(o.value for o in selected)
                )
                if selected
                else None
            )
            assert row.value == expected
            assert row.source_ids == sorted({o.source_id for o in selected})
