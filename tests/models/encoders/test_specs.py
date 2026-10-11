import pytest

np = pytest.importorskip("numpy", reason="encoder inputs require the optional baselines extra")

from hachi.models.encoders.specs import (  # noqa: E402
    WBM_CHANNELS,
    meanpool_features,
    moment_input,
    wbm_input,
    wbm_values,
)
from hachi.models.encoders.windows import WindowConfig, build_windows  # noqa: E402

from .helpers import week  # noqa: E402

WINDOWS = build_windows(
    week("s1"), WindowConfig(as_of_delay_hours=16, local_timezone="Europe/Oslo")
)
MEANS = np.arange(19, dtype=np.float32)
STDS = np.full(19, 2.0, dtype=np.float32)


def openmhc_process_example(values, mask, means, stds):
    # OpenMHC downstream_evaluation/models/wbm/model.py::_process_example at a2d6783 (oracle).
    present = 1.0 - mask
    norm = (values - means) / stds
    norm = norm * present
    return np.concatenate([norm, mask], axis=1)


def test_wbm_channels_units_and_unsupported_channels():
    values = wbm_values(WINDOWS)
    assert values.shape == (len(WINDOWS), 168, 19) and len(WBM_CHANNELS) == 19
    native = WINDOWS.values
    assert np.allclose(values[..., 5], native[..., 0] / 60.0, equal_nan=True)  # beats per second
    assert np.array_equal(values[..., 3], native[..., 1], equal_nan=True)
    assert np.array_equal(values[..., 4], native[..., 2], equal_nan=True)
    for unsupported in (0, 1, 2, 6, *range(9, 19)):
        assert np.isnan(values[..., unsupported]).all()


def test_wbm_input_matches_openmhc_preprocessing_and_variants_change_only_their_channels():
    values = wbm_values(WINDOWS)
    x = wbm_input(values, MEANS, STDS)
    for i in range(len(WINDOWS)):
        mask = np.isnan(values[i]).astype(np.float32)
        expected = openmhc_process_example(np.nan_to_num(values[i]), mask, MEANS, STDS)
        assert np.allclose(x[i], expected)
    hr = wbm_values(WINDOWS, "hr_only")
    assert np.isnan(np.delete(hr, 5, axis=2)).all()
    assert np.isnan(wbm_values(WINDOWS, "no_sleep")[..., 7:9]).all()
    records = wbm_values(WINDOWS, "sleep_records_only")[..., 7]
    assert set(np.unique(records[~np.isnan(records)])) == {1.0}
    zero = wbm_values(WINDOWS, "workouts_zero")[..., 9:19]
    assert np.nanmax(zero) == 0.0 and not np.isnan(zero).all()


def test_meanpool_and_moment_layouts():
    assert meanpool_features(wbm_values(WINDOWS)).shape == (len(WINDOWS), 76)
    x, mask = moment_input(WINDOWS)
    assert x.shape == mask.shape == (len(WINDOWS), 5, 512)
    assert not mask[:, :, :344].any() and not x[:, :, :344].any()
    assert np.array_equal(
        mask[:, :, 344:].astype(bool), np.isfinite(WINDOWS.values).transpose(0, 2, 1)
    )
