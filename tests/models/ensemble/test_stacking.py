"""Generated predictions only; these are software checks, not real-cohort evidence."""

import random
from datetime import UTC, datetime, timedelta

import pytest

from hachi.contracts.manifests import TimeWindow
from hachi.evaluation import ForecastEstimate, ForecastInput, TrainingPrefix
from hachi.models.ensemble.stacking import (
    DECILES,
    Point,
    combine,
    fit_stack,
    mean_pinball,
    replay_factory,
    residual_offsets,
    with_interval,
)

T0 = datetime(2019, 12, 25, tzinfo=UTC)
HOUR = timedelta(hours=1)


def keys(n=120):
    return [(f"s{i % 4}", T0, T0 + i * HOUR) for i in range(n)]


def test_lp_recovers_the_member_that_carries_the_signal():
    pytest.importorskip("numpy", reason="LP stacking requires the optional baselines extra")
    pytest.importorskip("scipy", reason="LP stacking requires the optional baselines extra")
    rng = random.Random(3)
    truth, good, bad = {}, {}, {}
    for key in keys():
        y = 60 + rng.gauss(0, 5)
        truth[(key[0], key[2])] = y
        good[key] = Point(y + rng.gauss(0, 0.5), None, None, None)
        bad[key] = Point(60 + rng.gauss(0, 8), None, None, None)
    weights = fit_stack({"good": good, "bad": bad}, truth, ["good", "bad"])
    assert weights.fitted_points == 120
    assert all(abs(sum(w) - 1) < 1e-9 and min(w) >= 0 for w in weights.weights.values())
    assert weights.weights[0.5][0] > 0.9


def test_combine_renormalizes_absent_members_and_rearranges_deciles():
    key = ("s0", T0, T0)
    wide = Point(60.0, None, None, tuple(55.0 + i for i in range(9)))
    point = Point(70.0, None, None, None)
    equal = combine({"a": {key: wide}, "b": {key: point}}, [key], None, "heart_rate")[key]
    assert equal.deciles == tuple(sorted((55.0 + i + 70.0) / 2 for i in range(9)))
    alone = combine({"a": {key: wide}, "b": {key: None}}, [key], None, "heart_rate")[key]
    assert alone.median == 59.0 and alone.lower == 55.0 and alone.upper == 63.0
    assert combine({"a": {key: None}}, [key], None, "heart_rate")[key] is None


def test_residual_intervals_come_from_meta_points_and_contain_the_median():
    meta = {(f"s{i}", T0, T0 + i * HOUR): Point(60.0, None, None, None) for i in range(40)}
    truth = {(f"s{i}", T0 + i * HOUR): 60.0 + (i - 10) / 4 for i in range(40)}
    low, high = residual_offsets(meta, truth, 0.1, 0.9)
    assert low <= 0 <= high
    shifted = with_interval(
        {("v", T0, T0): Point(298.0, None, None, None)}, (low, high + 5), "heart_rate"
    )[("v", T0, T0)]
    assert shifted.lower <= 298.0 <= shifted.upper == 300.0
    with pytest.raises(ValueError, match="too few"):
        residual_offsets(dict(list(meta.items())[:5]), truth, 0.1, 0.9)


def test_point_pinball_is_half_the_absolute_error_and_deciles_are_used_when_present():
    assert mean_pinball(Point(60.0, None, None, None), 64.0) == pytest.approx(2.0)
    spread = Point(60.0, None, None, tuple(60.0 + (q - 0.5) * 10 for q in DECILES))
    assert mean_pinball(spread, 60.0) < mean_pinball(Point(60.0, None, None, None), 64.0)


def test_replay_factory_serves_the_table_and_refuses_unknown_origins():
    key = ("s0", T0, T0)
    predict = replay_factory({key: Point(60.0, 58.0, 62.0, None)}, "demo")(
        TrainingPrefix(T0, (), ())
    )
    window = TimeWindow(start_utc=T0, end_utc=T0 + HOUR)
    assert predict(ForecastInput("s0", T0, (window,), ())) == (
        ForecastEstimate(median=60.0, lower=58.0, upper=62.0),
    )
    with pytest.raises(ValueError, match="no prediction"):
        predict(ForecastInput("s1", T0, (window,), ()))
