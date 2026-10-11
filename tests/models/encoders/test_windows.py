from datetime import UTC, datetime

import pytest

np = pytest.importorskip("numpy", reason="encoder inputs require the optional baselines extra")

from hachi.models.encoders.windows import CHANNELS, WindowConfig, build_windows  # noqa: E402

from .helpers import HOUR, MIDNIGHT, hourly, week  # noqa: E402

CONFIG = WindowConfig(as_of_delay_hours=16, local_timezone="Europe/Oslo")
HR, STEPS, DIST, ASLEEP, IN_BED = (CHANNELS.index(c) for c in CHANNELS)


def only(windows, end):
    (index,) = [i for i, e in enumerate(windows.window_end_utc) if e == end]
    return windows.values[index], windows.worn[index], windows.as_of_utc[index]


def test_window_covers_seven_local_days_in_local_hour_order():
    windows = build_windows(week("s1"), CONFIG)
    values, worn, as_of = only(windows, MIDNIGHT)
    assert values.shape == (168, len(CHANNELS)) and worn.all()
    assert as_of == MIDNIGHT + 16 * HOUR
    # Row 0 is 00:00 local on the first day, 23:00 UTC the evening before.
    assert values[0, HR] == 60.0 and values[1, HR] == 61.0
    assert values[1, STEPS] == 10.0 and values[1, DIST] == 7.0
    # 03:00 local is asleep and in bed; 12:00 local is worn and observed awake.
    assert values[3, ASLEEP] == 1.0 and values[3, IN_BED] == 1.0
    assert values[12, ASLEEP] == 0.0 and values[12, IN_BED] == 0.0


def test_unworn_hours_and_unfinished_sleep_logs_are_unknown_not_zero():
    bins = [b for b in week("s1") if b.aggregate.interval_start_utc != MIDNIGHT - 30 * HOUR]
    late = MIDNIGHT - 2 * HOUR  # 22:00 local on the last day, logged as sleep but final very late
    bins += [hourly("s1", "sleep_in_bed", late, 1800.0, available=MIDNIGHT + 20 * HOUR)]
    values, worn, _ = only(build_windows(bins, CONFIG), MIDNIGHT)
    unworn = 168 - 30
    assert not worn[unworn] and np.isnan(values[unworn]).all()
    assert np.isnan(values[166, IN_BED])  # pending at as-of: unknown
    assert values[166, ASLEEP] == 0.0  # no asleep record for that hour, and it was worn


def test_window_is_identical_when_recomputed_from_data_truncated_at_its_as_of():
    full = build_windows(week("s1", days=12), CONFIG)
    for end, as_of in zip(full.window_end_utc, full.as_of_utc, strict=True):
        cut = [
            b
            for b in week("s1", days=12)
            if b.available_at_utc <= as_of and b.aggregate.interval_end_utc <= as_of
        ]
        truncated = build_windows(cut, CONFIG)
        if end not in truncated.window_end_utc:
            continue
        a = only(full, end)[0]
        b = only(truncated, end)[0]
        assert np.array_equal(a, b, equal_nan=True)


def test_dst_gap_hour_is_missing_and_windows_need_known_hours():
    end = datetime(2020, 3, 29, 22, tzinfo=UTC)  # 2020-03-30 00:00 CEST
    windows = build_windows(week("s1", end=end), CONFIG)
    values, _, _ = only(windows, end)
    gap = 6 * 24 + 2  # 02:00 local on 29 March does not exist
    assert np.isnan(values[gap]).all()
    sparse = [hourly("s2", "heart_rate", MIDNIGHT - h * HOUR, 60.0) for h in range(1, 10)]
    assert len(build_windows(sparse, CONFIG)) == 0
