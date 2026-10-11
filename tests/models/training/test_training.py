"""Generated hourly bins only; these are software checks, not real-cohort evidence."""

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hachi.contracts.manifests import TimeWindow
from hachi.contracts.tables import Aggregate
from hachi.evaluation import ForecastInput, HourlyFeature, NestedFold, TrainingPrefix
from hachi.evaluation.pmdata_run import PMDataProtocol
from hachi.models.training import (
    MetaPlan,
    RidgeArtifact,
    RidgeConfig,
    finetune_series,
    fit_ridge,
    meta_groups,
    meta_splits,
    training_windows,
)

ROOT = Path(__file__).resolve().parents[3]
FIT = datetime(2020, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


def feature(subject, hour, value, delay=0):
    start = FIT + hour * HOUR
    row = Aggregate(
        dataset_id="generated",
        subject_id=subject,
        metric="heart_rate",
        unit="bpm",
        resolution="hour",
        interval_start_utc=start,
        interval_end_utc=start + HOUR,
        local_date=None,
        tz_name="UTC",
        aggregation="mean",
        value=value,
        null_reason=None,
        observed_count=60,
        coverage=1.0,
        source_ids=["generated"],
        pipeline_version="g1",
    )
    return HourlyFeature(
        aggregate=row,
        available_at_utc=row.interval_end_utc + delay * HOUR,
        availability_rule="generated",
    )


def level(i, hour):
    return 60.0 + 2 * i + 6 * math.sin(2 * math.pi * (hour % 24) / 24)


def prefix(subjects=4, hours=24 * 20):
    rows = [
        feature(f"g-{i}", h, level(i, h))
        for i in range(subjects)
        for h in range(-hours, 0)
        if (h + i) % 9
    ]
    return TrainingPrefix(FIT, tuple(f"g-{i}" for i in range(subjects)), tuple(rows))


def protocol() -> PMDataProtocol:
    path = ROOT / "configs/evaluation/pmdata-hourly-validation.json"
    return PMDataProtocol.model_validate_json(path.read_bytes())


PLAN = MetaPlan(
    meta_folds=4, seed=42, window_start_utc=datetime(2019, 12, 25, tzinfo=UTC), window_end_utc=FIT
)


def test_meta_groups_are_order_independent_and_disjoint():
    subjects = [f"p{i:02d}" for i in range(8)]
    groups = meta_groups(subjects, PLAN, "meta:0:0")
    assert groups == meta_groups(list(reversed(subjects)), PLAN, "meta:0:0")
    assert sorted(s for g in groups for s in g) == sorted(subjects)
    assert all(len(g) == 2 for g in groups)
    assert groups != meta_groups(subjects, PLAN, "meta:0:1")


def test_meta_manifests_seal_validation_and_outer_test():
    fold = NestedFold(
        0,
        1,
        tuple(f"t{i}" for i in range(8)),
        ("v0", "v1", "v2", "v3"),
        ("x0", "x1", "x2", "x3"),
        (),
    )
    manifests = meta_splits(protocol(), fold, PLAN)
    assert len(manifests) == 4
    for m in manifests:
        assert set(m.test_subjects) == {"v0", "v1", "v2", "v3", "x0", "x1", "x2", "x3"}
        assert not set(m.train_subjects) & set(m.validation_subjects)
        assert m.evaluation_window.end_utc <= protocol().evaluation_window.start_utc
        assert m.test_opened_at_utc is None
    late = PLAN.model_copy(update={"window_end_utc": FIT + HOUR})
    with pytest.raises(ValueError, match="first held-out cutoff"):
        meta_splits(protocol(), fold, late)


def test_windows_use_only_what_each_cutoff_could_see():
    # A bin starting 30 h before the fit cutoff that only arrives 9 h before it.
    late = feature("g-0", -30, 199.0, delay=20)
    rows = (*(r for r in prefix(1).observations if r.start_utc != late.start_utc), late)
    windows = training_windows(
        TrainingPrefix(FIT, ("g-0",), rows),
        "heart_rate",
        context_hours=48,
        horizon=24,
        stride_hours=6,
        min_context_values=24,
    )
    assert windows and all(w.cutoff + 24 * HOUR <= FIT for w in windows)
    assert all(w.cutoff.hour % 6 == 0 for w in windows)
    # Every window cutoff precedes its arrival, so no context holds it; labels may.
    assert not any(199.0 in w.context for w in windows)
    assert any(199.0 in w.targets for w in windows)
    with pytest.raises(ValueError, match="unavailable at its fit cutoff"):
        training_windows(
            TrainingPrefix(FIT, ("g-0",), (feature("g-0", -2, 60.0, delay=5),)),
            "heart_rate",
            context_hours=48,
            horizon=24,
            stride_hours=6,
            min_context_values=24,
        )


def test_finetune_series_end_before_and_inside_the_holdout():
    train, holdout = finetune_series(
        prefix(),
        "heart_rate",
        holdout_hours=168,
        horizon=24,
        min_target_values=12,
        min_past_values=24,
    )
    assert len(train) == 4 and len(holdout) == 4 * 7
    spans = {len(r["target"]) for r in train}
    assert spans <= {24 * 20 - 168, 24 * 20 - 169}  # each series starts at its first bin
    assert {len(r["target"]) - min(spans) for r in holdout} >= {24 * (d + 1) for d in range(7)}
    assert all(set(r) == {"format", "series_id", "target"} for r in train + holdout)


@pytest.mark.parametrize("kind", ["handcrafted-personal", "handcrafted-population"])
def test_ridge_fits_selects_alpha_and_replays_from_its_artifact(kind):
    config = RidgeConfig(kind=kind, metric="heart_rate", alphas=[0.1, 10.0, 1000.0])
    artifact = fit_ridge(prefix(), config)
    assert artifact.alpha in config.alphas and any(
        v is not None for v in artifact.holdout_mae.values()
    )
    reloaded = RidgeArtifact.model_validate_json(artifact.model_dump_json())
    history = tuple(feature("g-1", h, level(1, h)) for h in range(-48, 0))
    request = ForecastInput(
        "g-1",
        FIT,
        tuple(
            TimeWindow(start_utc=FIT + h * HOUR, end_utc=FIT + (h + 1) * HOUR) for h in range(24)
        ),
        history,
    )
    estimates = reloaded.predict_with(request)
    assert estimates == artifact.predict_with(request)
    errors = [abs(e.median - level(1, h)) for h, e in enumerate(estimates)]
    if kind == "handcrafted-personal":
        assert max(errors) < 3.0  # learns the generated daily cycle around the personal level
    with pytest.raises(ValueError, match="precedes"):
        artifact.predict_with(ForecastInput("g-1", FIT - HOUR, request.targets, ()))
