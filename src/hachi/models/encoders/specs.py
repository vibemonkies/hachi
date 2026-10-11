"""Exact input layouts for the frozen encoders, from native PMData week windows.

WBM (OpenMHC ``openmhc-wbm-dp``): 168 local hours x 19 MyHeartCounts channels, hourly sums for
accumulations, hourly mean heart rate in beats per second, hourly max for binary states. The
model input is ``[(value - mean) / std * present | missing]`` (38 features, ``1 = missing``),
exactly as OpenMHC's ``_process_example`` builds it. PMData has no iPhone, active-energy or
workout source, so those channels are always missing unless an ablation says otherwise.

MOMENT: each native channel is its own univariate series, left-padded to 512 steps with
``input_mask = 0`` for padding and for unknown hours (``1 = observed``).
"""

from typing import Literal

import numpy as np

from .windows import CHANNELS, WeekWindows

WBM_CHANNELS = (
    "hk_iphone:HKQuantityTypeIdentifierStepCount",
    "hk_iphone:HKQuantityTypeIdentifierDistanceWalkingRunning",
    "hk_iphone:HKQuantityTypeIdentifierFlightsClimbed",
    "hk_watch:HKQuantityTypeIdentifierStepCount",
    "hk_watch:HKQuantityTypeIdentifierDistanceWalkingRunning",
    "hk_watch:HKQuantityTypeIdentifierHeartRate",
    "hk_watch:HKQuantityTypeIdentifierActiveEnergyBurned",
    "sleep:asleep",
    "sleep:inbed",
    "workout:HKWorkoutActivityTypeWalking",
    "workout:HKWorkoutActivityTypeCycling",
    "workout:HKWorkoutActivityTypeRunning",
    "workout:HKWorkoutActivityTypeOther",
    "workout:HKWorkoutActivityTypeMixedMetabolicCardioTraining",
    "workout:HKWorkoutActivityTypeTraditionalStrengthTraining",
    "workout:HKWorkoutActivityTypeElliptical",
    "workout:HKWorkoutActivityTypeHighIntensityIntervalTraining",
    "workout:HKWorkoutActivityTypeFunctionalStrengthTraining",
    "workout:HKWorkoutActivityTypeYoga",
)
WBM_HOURS = 168
WORKOUT_SLICE = slice(9, 19)

# WBM channel <- native PMData channel (a Fitbit Versa 2 on the wrist stands in for the watch).
WBM_SOURCES = {
    3: "steps",
    4: "walking_running_distance",
    5: "heart_rate",
    7: "sleep_asleep",
    8: "sleep_in_bed",
}
BPM_PER_HZ = 60.0

type WbmVariant = Literal["full", "hr_only", "no_sleep", "sleep_records_only", "workouts_zero"]
WBM_VARIANTS: tuple[WbmVariant, ...] = (
    "full",
    "hr_only",
    "no_sleep",
    "sleep_records_only",
    "workouts_zero",
)


def wbm_values(windows: WeekWindows, variant: WbmVariant = "full") -> np.ndarray:
    """Raw hourly values in WBM channel order and units, NaN where missing."""
    if windows.values.shape[1] != WBM_HOURS:
        raise ValueError("WBM consumes exactly 168 hourly steps (seven local days)")
    native = {name: windows.values[:, :, i] for i, name in enumerate(CHANNELS)}
    out = np.full((len(windows), WBM_HOURS, len(WBM_CHANNELS)), np.nan, dtype=np.float32)
    for channel, source in WBM_SOURCES.items():
        out[:, :, channel] = native[source]
    out[:, :, 5] /= BPM_PER_HZ  # OpenMHC stores heart rate in count/s (its stats: mean 1.24)
    if variant == "hr_only":
        keep = np.zeros(len(WBM_CHANNELS), dtype=bool)
        keep[5] = True
        out[:, :, ~keep] = np.nan
    elif variant == "no_sleep":
        out[:, :, 7:9] = np.nan
    elif variant == "sleep_records_only":
        # Alternative mask semantics: only recorded sleep is observed; "not asleep" is unknown.
        sleep = out[:, :, 7:9]
        sleep[sleep == 0] = np.nan
    elif variant == "workouts_zero":
        out[:, :, WORKOUT_SLICE] = np.where(windows.worn[:, :, None], 0.0, np.nan)
    elif variant != "full":
        raise ValueError(f"unknown WBM input variant {variant!r}")
    return out


def wbm_input(values: np.ndarray, means: np.ndarray, stds: np.ndarray) -> np.ndarray:
    """OpenMHC's checkpoint input: z-scored values zeroed where missing, then the missing flags."""
    if values.shape[1:] != (WBM_HOURS, len(WBM_CHANNELS)):
        raise ValueError("expected (n, 168, 19) WBM values")
    missing = np.isnan(values).astype(np.float32)
    present = 1.0 - missing
    norm = (np.nan_to_num(values, nan=0.0) - means.astype(np.float32)) / stds.astype(np.float32)
    return np.concatenate([norm * present, missing], axis=2).astype(np.float32)


def meanpool_features(values: np.ndarray) -> np.ndarray:
    """OpenMHC's README MeanPool encoder on the same input: per-feature mean and std of
    ``nan_to_num([values | missing])`` over the week (76 features)."""
    missing = np.isnan(values).astype(np.float32)
    x = np.concatenate([np.nan_to_num(values, nan=0.0), missing], axis=2)
    return np.concatenate([x.mean(axis=1), x.std(axis=1)], axis=1).astype(np.float32)


MOMENT_SEQ_LEN = 512
MOMENT_PATCH_LEN = 8


def moment_input(
    windows: WeekWindows, channels: tuple[str, ...] = CHANNELS
) -> tuple[np.ndarray, np.ndarray]:
    """Left-padded univariate series ``(n, c, 512)`` and observed masks ``(n, c, 512)``."""
    hours = windows.values.shape[1]
    if hours > MOMENT_SEQ_LEN or hours % MOMENT_PATCH_LEN:
        raise ValueError("window must fit 512 steps and whole 8-step patches")
    index = [CHANNELS.index(c) for c in channels]
    series = np.transpose(windows.values[:, :, index], (0, 2, 1))
    x = np.zeros((len(windows), len(index), MOMENT_SEQ_LEN), dtype=np.float32)
    mask = np.zeros_like(x)
    x[:, :, -hours:] = np.nan_to_num(series, nan=0.0)
    mask[:, :, -hours:] = np.isfinite(series)
    return x, mask
