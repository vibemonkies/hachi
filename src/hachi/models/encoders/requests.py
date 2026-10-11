"""Frozen WBM/MOMENT features for another lane's context requests (#13 Stanford onset).

The requesting lane exports one JSON line per context: 168 hourly values per channel on the
cohort's own (floating) clock, starting at local 00:00, with no subject id, cutoff or date.
Each record names itself by ``request_sha256`` = ``document_sha256`` of the record without that
field. This module turns requests into the exact #11 encoder inputs and writes the returned
features keyed by that hash; the requester joins them to its folds through its private map.

  python -m hachi.models.encoders.requests inputs --requests contexts.jsonl --wbm-config JSON \
      --output inputs.npz
  python -m hachi.models.encoders.requests features --inputs inputs.npz --wbm wbm.npz \
      --moment moment.npz --output frozen-features.parquet [--join-map map.parquet]

Both encoders are frozen and never fitted on the requesting cohort, so every feature is
out-of-fold by construction; any projection or head belongs to the requester's training folds.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from hachi.evaluation.serialization import document_sha256

from .config import REPO
from .specs import WBM_HOURS, meanpool_features, moment_input, wbm_input, wbm_values
from .windows import CHANNELS, WeekWindows

UNITS = {"heart_rate": "bpm", "steps": "count"}
LIMITS = {"heart_rate": (20.0, 300.0), "steps": (0.0, 20000.0)}
WBM_VARIANTS = {"wbm_hr": "hr_only", "wbm_hr_steps": "full"}


def read_requests(path: Path) -> tuple[list[str], np.ndarray, str]:
    """Validated requests as native-channel arrays (NaN = unknown) and their policy hash."""
    hashes: list[str] = []
    rows: list[np.ndarray] = []
    policies: set[str] = set()
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        claimed = record.pop("request_sha256")
        if document_sha256(record) != claimed:
            raise ValueError(f"line {number}: request_sha256 does not match its content")
        if record.get("hours") != WBM_HOURS or record.get("first_hour_local") != 0:
            raise ValueError(f"line {number}: need 168 hours starting at local 00:00")
        channels = record["channels"]
        if "heart_rate" not in channels or set(channels) - set(UNITS):
            raise ValueError(f"line {number}: channels must be heart_rate and optional steps")
        for name in channels:
            if record["units"].get(name) != UNITS[name]:
                raise ValueError(f"line {number}: {name} must be in {UNITS[name]}")
        native = np.full((WBM_HOURS, len(CHANNELS)), np.nan, dtype=np.float32)
        for name, values in channels.items():
            if len(values) != WBM_HOURS:
                raise ValueError(f"line {number}: {name} needs 168 values")
            low, high = LIMITS[name]
            for hour, value in enumerate(values):
                if value is None:
                    continue
                if not (isinstance(value, int | float) and math.isfinite(value)):
                    raise ValueError(f"line {number}: {name} values must be numbers or null")
                if not low <= value <= high:
                    raise ValueError(f"line {number}: {name} value outside {low}-{high}")
                native[hour, CHANNELS.index(name)] = value
        if claimed in hashes:
            raise ValueError(f"line {number}: duplicate request")
        hashes.append(claimed)
        rows.append(native)
        policies.add(record["context_policy_sha256"])
    if len(policies) != 1:
        raise ValueError("one export must use one context policy")
    values = np.stack(rows) if rows else np.zeros((0, WBM_HOURS, len(CHANNELS)), np.float32)
    return hashes, values, policies.pop()


def _windows(values: np.ndarray) -> WeekWindows:
    n = len(values)
    worn = np.isfinite(values[:, :, CHANNELS.index("heart_rate")]) | np.isfinite(
        values[:, :, CHANNELS.index("steps")]
    )
    return WeekWindows(("request",) * n, (None,) * n, (None,) * n, values, worn)  # type: ignore[arg-type]


def model_inputs(values: np.ndarray, means: np.ndarray, stds: np.ndarray) -> dict[str, np.ndarray]:
    """#11's exact layouts. Distance, sleep, iPhone, energy and workout channels stay missing."""
    windows = _windows(values)
    # Steps variants exist only when the export carries steps (its primary is HR-only).
    channels = ("heart_rate", "steps") if np.isfinite(values[:, :, 1]).any() else ("heart_rate",)
    arrays: dict[str, np.ndarray] = {}
    for name, variant in WBM_VARIANTS.items():
        if variant == "full" and "steps" not in channels:
            continue
        raw = wbm_values(windows, variant)
        arrays[name] = wbm_input(raw, means, stds)
        arrays[name.replace("wbm", "meanpool")] = meanpool_features(raw)
    arrays["moment_x"], arrays["moment_mask"] = moment_input(windows, channels)
    arrays["moment_channels"] = np.asarray(channels)
    return arrays


def feature_table(
    hashes: np.ndarray, arrays: dict[str, np.ndarray], metadata: dict[str, str]
) -> pa.Table:
    rows = []
    for model, matrix in sorted(arrays.items()):
        for request, vector in zip(hashes, matrix, strict=True):
            rows.append(
                {
                    "request_sha256": str(request),
                    "model": model,
                    "dim": int(vector.shape[0]),
                    "finite": bool(np.isfinite(vector).all()),
                    "vector": vector.astype(np.float32).tolist(),
                }
            )
    table = pa.Table.from_pylist(rows)
    return table.replace_schema_metadata({k.encode(): v.encode() for k, v in metadata.items()})


def join_features(features: pa.Table, join_map: pa.Table) -> pa.Table:
    """Attach the requester's private fold keys; unmatched requests are dropped, never guessed.

    Arrow's hash join cannot carry list columns, so this joins through a dictionary.
    """
    keys = {r["request_sha256"]: r for r in join_map.to_pylist()}
    if len(keys) != join_map.num_rows:
        raise ValueError("join map repeats a request")
    rows = [
        {**keys[r["request_sha256"]], **r}
        for r in features.to_pylist()
        if r["request_sha256"] in keys
    ]
    return pa.Table.from_pylist(rows).replace_schema_metadata(features.schema.metadata)


def _checkpoint(model: str) -> str:
    pin = json.loads((REPO / f"configs/models/encoders/{model}.json").read_text())["checkpoint"]
    return f"{pin['repository']}@{pin['revision']}"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("inputs")
    build.add_argument("--requests", required=True, type=Path)
    build.add_argument("--wbm-config", required=True, type=Path)
    build.add_argument("--output", required=True, type=Path)
    out = sub.add_parser("features")
    out.add_argument("--inputs", required=True, type=Path)
    out.add_argument("--wbm", required=True, type=Path)
    out.add_argument("--moment", required=True, type=Path)
    out.add_argument("--join-map", type=Path)
    out.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "inputs":
            hashes, values, policy = read_requests(args.requests)
            config = json.loads(args.wbm_config.read_text())["input"]["normalization"]
            arrays = model_inputs(
                values,
                np.asarray(config["means"], dtype=np.float32),
                np.asarray(config["stds"], dtype=np.float32),
            )
            np.savez(args.output, request_sha256=np.asarray(hashes), **arrays)
            print(
                json.dumps(
                    {
                        "requests": len(hashes),
                        "requests_sha256": _sha(args.requests),
                        "context_policy_sha256": policy,
                        "inputs_sha256": _sha(args.output),
                        "observed_fraction": {
                            c: float(np.isfinite(values[:, :, CHANNELS.index(c)]).mean())
                            for c in UNITS
                        },
                    },
                    indent=2,
                )
            )
            return 0
        with np.load(args.inputs, allow_pickle=False) as data:
            hashes = data["request_sha256"]
            channels = [str(c) for c in data["moment_channels"]]
            arrays = {k: data[k] for k in data.files if k.startswith("meanpool_")}
        for path in (args.wbm, args.moment):
            with np.load(path, allow_pickle=False) as data:
                if not np.array_equal(data["request_sha256"], hashes):
                    raise ValueError(f"{path.name} rows do not match the inputs")
                for name in data.files:
                    if name in WBM_VARIANTS:
                        arrays[name] = data[name]
                if "moment" in data.files:
                    width = data["moment"].shape[1] // len(channels)
                    for i, channel in enumerate(channels):
                        name = {"heart_rate": "moment_hr", "steps": "moment_steps"}[channel]
                        arrays[name] = data["moment"][:, i * width : (i + 1) * width]
        metadata = {
            "inputs_sha256": _sha(args.inputs),
            "wbm_sha256": _sha(args.wbm),
            "moment_sha256": _sha(args.moment),
            "wbm_checkpoint": _checkpoint("wbm"),
            "moment_checkpoint": _checkpoint("moment"),
            "encoders": "frozen; never fitted on the requesting cohort",
        }
        table = feature_table(hashes, arrays, metadata)
        pq.write_table(table, args.output)
        summary = {"rows": table.num_rows, "output_sha256": _sha(args.output)}
        if args.join_map is not None:
            joined = join_features(table, pq.read_table(args.join_map))
            target = args.output.with_name("oof-features.parquet")
            pq.write_table(joined, target)
            summary.update({"joined_rows": joined.num_rows, "oof_sha256": _sha(target)})
        summary["finite"] = bool(all(table.column("finite").to_pylist()))
        print(json.dumps(summary, indent=2))
        return 0
    except Exception as error:
        # Request content is participant-level; keep diagnostics free of values.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
