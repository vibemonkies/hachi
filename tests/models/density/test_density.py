import json
from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pytest

pytest.importorskip("numpy", reason="thinning requires the optional baselines extra")

from hachi.models.density.config import REPO, load_variant
from hachi.models.density.thinning import (
    AppleMinuteThinning,
    ThinningRule,
    hourly_from_samples,
    thin_samples,
)

RULE = ThinningRule(slot_seconds=300, pipeline_suffix="thin300s")
T0 = datetime(2020, 1, 1, tzinfo=UTC)
VARIANT = REPO / "configs/evaluation/pmdata-hourly-validation-apple-density.json"
AMENDED = REPO / "configs/evaluation/pmdata-hourly-validation-apple-minute-density.json"


def samples(rows):
    return pa.table(
        {
            "subject_id": [r[0] for r in rows],
            "record_id": [r[1] for r in rows],
            "source_id": ["generated"] * len(rows),
            "value": [r[3] for r in rows],
            "start_utc": pa.array(
                [T0 + timedelta(seconds=r[2]) for r in rows], pa.timestamp("us", "UTC")
            ),
            "available_at_utc": pa.array(
                [T0 + timedelta(seconds=r[2]) for r in rows], pa.timestamp("us", "UTC")
            ),
        }
    )


def test_thinning_keeps_the_earliest_sample_per_subject_and_utc_slot():
    table = samples(
        [
            ("b", "r9", 10, 70.0),
            ("a", "r2", 5, 61.0),
            ("a", "r1", 5, 60.0),  # same start: lower record_id wins
            ("a", "r3", 299, 99.0),  # same slot, later
            ("a", "r4", 300, 62.0),  # next slot
            ("b", "r8", 20, 71.0),
        ]
    )
    kept = thin_samples(table, RULE).to_pylist()
    assert [(r["subject_id"], r["record_id"]) for r in kept] == [
        ("a", "r1"),
        ("a", "r4"),
        ("b", "r9"),
    ]


def test_hourly_rebinning_counts_kept_samples_and_latest_availability():
    rows = [("a", f"r{i:02d}", i * 300 + 7, 60.0 + i) for i in range(12)] + [
        ("a", "late", 3600 + 5, 90.0)
    ]
    hourly = hourly_from_samples(thin_samples(samples(rows), RULE))
    first = hourly[("a", int(T0.timestamp() * 1_000_000))]
    assert first[0] == 12 and first[1] == pytest.approx(sum(60.0 + i for i in range(12)))
    assert first[2] == int((T0 + timedelta(seconds=11 * 300 + 7)).timestamp() * 1_000_000)
    assert hourly[("a", int((T0 + timedelta(hours=1)).timestamp() * 1_000_000))][0] == 1


def test_variant_changes_only_the_model_input_density_gates(tmp_path):
    variant, base = load_variant(VARIANT)
    assert variant.protocol.evaluation == base.evaluation  # target gates untouched
    assert variant.protocol.feature_policy.min_coverage == base.feature_policy.min_coverage
    assert (
        variant.protocol.feature_policy.min_observed_count
        == 6
        < base.feature_policy.min_observed_count
    )
    raw = json.loads(VARIANT.read_text())
    raw["protocol"]["lookback_hours"] = 72
    raw["protocol"]["tree"]["lookback_hours"] = 72
    changed = tmp_path / "variant.json"
    changed.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="more than the density gates"):
        load_variant(changed)
    raw = json.loads(VARIANT.read_text())
    raw["protocol"]["tree"]["min_samples_per_hour"] = 5
    changed.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="declared gate"):
        load_variant(changed)


def test_hourly_rebinning_counts_distinct_sampled_minutes_like_the_apple_helper():
    rule = AppleMinuteThinning(
        slot_seconds=300, pipeline_suffix="x", coverage="distinct_sampled_minutes_per_60"
    )
    rows = [("a", f"r{i:02d}", i * 300 + 7, 60.0) for i in range(6)]
    hourly = hourly_from_samples(thin_samples(samples(rows), rule))
    count, _, _, _, minutes = hourly[("a", int(T0.timestamp() * 1_000_000))]
    assert count == minutes == 6  # one kept sample per slot is one distinct minute


def test_amendment_moves_only_the_minute_coverage_gate_and_pins_the_amended_variant(tmp_path):
    variant, base = load_variant(AMENDED)
    assert isinstance(variant.thinning, AppleMinuteThinning)
    assert variant.protocol.feature_policy.min_coverage == 0.1
    assert variant.protocol.feature_policy.min_observed_count == 6
    assert variant.protocol.evaluation == base.evaluation
    raw = json.loads(AMENDED.read_text())
    raw["amendment"]["amends_sha256"] = "0" * 64
    changed = tmp_path / "amended.json"
    changed.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="amended variant changed"):
        load_variant(changed)
    raw = json.loads(VARIANT.read_text())
    raw["protocol"]["feature_policy"]["min_coverage"] = 0.1  # slot variants may not move coverage
    changed.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="more than the density gates"):
        load_variant(changed)
