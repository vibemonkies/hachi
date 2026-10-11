"""Build the model-ready encoder inputs for the GX10 and their sanitized input audit.

  python -m hachi.models.encoders.inputs --snapshot DIR --experiment JSON --wbm-config JSON \
      --output PRIVATE_DIR

Writes ``inputs.npz`` (participant-level, private: keep it in approved storage) and
``input-audit.json`` (aggregate counts and distribution summaries only).
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

from hachi.data.pmdata import dataset_snapshot_ref
from hachi.evaluation.pmdata_run import PMDataProtocol

from .config import EncoderExperiment
from .specs import (
    WBM_CHANNELS,
    WBM_VARIANTS,
    meanpool_features,
    moment_input,
    wbm_input,
    wbm_values,
)
from .windows import CHANNELS, WeekWindows, build_windows, load_bins, snapshot_timezone


def model_inputs(
    windows: WeekWindows, means: np.ndarray, stds: np.ndarray
) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {
        "subject_ids": np.asarray(windows.subject_ids),
        "window_end_utc": np.asarray([t.isoformat() for t in windows.window_end_utc]),
        "as_of_utc": np.asarray([t.isoformat() for t in windows.as_of_utc]),
    }
    for variant in WBM_VARIANTS:
        arrays[f"wbm_{variant}"] = wbm_input(wbm_values(windows, variant), means, stds)
    arrays["meanpool"] = meanpool_features(wbm_values(windows, "full"))
    arrays["moment_x"], arrays["moment_mask"] = moment_input(windows)
    return arrays


def input_audit(windows: WeekWindows, means: np.ndarray, stds: np.ndarray) -> dict[str, object]:
    """Aggregates only: window counts, missingness and how far PMData sits from WBM's scale."""
    values = wbm_values(windows, "full")
    observed = ~np.isnan(values)
    z = (values - means) / stds
    shift = {}
    for channel in sorted({3, 4, 5}):
        column = z[:, :, channel][observed[:, :, channel]]
        shift[WBM_CHANNELS[channel]] = {
            "observed_hours": int(column.size),
            "z_mean": float(column.mean()) if column.size else None,
            "z_std": float(column.std()) if column.size else None,
        }
    per_subject = {}
    for subject in windows.subject_ids:
        per_subject[subject] = per_subject.get(subject, 0) + 1
    return {
        "windows": len(windows),
        "subjects": len(per_subject),
        "windows_per_subject": {
            "min": min(per_subject.values(), default=0),
            "max": max(per_subject.values(), default=0),
        },
        "first_window_end_utc": min(windows.window_end_utc).isoformat() if len(windows) else None,
        "last_window_end_utc": max(windows.window_end_utc).isoformat() if len(windows) else None,
        "native_observed_fraction": {
            name: float(np.isfinite(windows.values[:, :, i]).mean())
            for i, name in enumerate(CHANNELS)
        },
        "wbm_channel_observed_fraction": {
            name: float(observed[:, :, i].mean()) for i, name in enumerate(WBM_CHANNELS)
        },
        "wbm_device_shift_z": shift,
        "wbm_device_shift_note": (
            "z uses the checkpoint's MyHeartCounts normalization; an unshifted cohort would sit "
            "near mean 0 and std 1 on observed hours."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--experiment", required=True, type=Path)
    parser.add_argument("--wbm-config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        experiment = EncoderExperiment.model_validate_json(args.experiment.read_bytes())
        protocol = PMDataProtocol.model_validate_json(experiment.protocol.resolve().read_bytes())
        if dataset_snapshot_ref(args.snapshot) != protocol.expected_snapshot:
            raise ValueError("snapshot is not the protocol's admitted snapshot")
        if snapshot_timezone(args.snapshot) != experiment.window.local_timezone:
            raise ValueError("snapshot local timezone differs from the experiment window")
        wbm = json.loads(args.wbm_config.read_text())
        means = np.asarray(wbm["input"]["normalization"]["means"], dtype=np.float32)
        stds = np.asarray(wbm["input"]["normalization"]["stds"], dtype=np.float32)
        windows = build_windows(load_bins(args.snapshot), experiment.window)
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        path = args.output / "inputs.npz"
        np.savez(path, **model_inputs(windows, means, stds))
        audit = {
            "dataset_snapshot": protocol.expected_snapshot.model_dump(),
            "window": experiment.window.model_dump(),
            "inputs_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            **input_audit(windows, means, stds),
        }
        descriptor = os.open(
            args.output / "input-audit.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(audit, indent=2) + "\n")
        print(json.dumps(audit, indent=2))
        return 0
    except Exception as error:
        # Row validation errors could quote participant values; keep diagnostics private.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
