"""Chronos-2 inference on the GX10: stdlib at import, torch and Chronos only inside `run`.

The pinned GX10 runtime (infra/gx10/requirements.lock) holds torch and Chronos but not
Hachi's data stack, so this file must never import `hachi`. It reads causal context
requests exported by the CPU harness, verifies every request id and the pinned checkpoint,
and writes quantile forecasts keyed by request id. Requests carry no subject id, cutoff or
target, so nothing here can see a label.

Run under the queue with an isolated interpreter, so this directory is not on sys.path:

    scripts/gx10/gpu-run --owner justin06lee --run-id issue10-... -- \\
        "$runtime_py" -I src/hachi/models/chronos/inference.py \\
        --requests requests.jsonl --model infra/gx10/model.json
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import resource
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

REQUEST_FORMAT = "chronos-context-1"
PREDICTION_FORMAT = "chronos-quantiles-1"
# Model card limits for amazon/chronos-2 (config.json: context_length, max_output_patches * 16).
MODEL_CONTEXT_LIMIT = 8192
MODEL_HORIZON_LIMIT = 1024

type Forecaster = Callable[[list[list[float | None]], int], list[list[list[float]]]]


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def request_id(context: Sequence[float | None], prediction_length: int) -> str:
    """Content identity of one causal context; identical windows share one forecast."""
    document = {
        "format": REQUEST_FORMAT,
        "context": list(context),
        "prediction_length": prediction_length,
    }
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_request(row: dict[str, Any]) -> tuple[str, list[float | None], int]:
    if set(row) != {"request_id", "context", "prediction_length"}:
        raise ValueError("request rows hold exactly request_id, context and prediction_length")
    context, length = row["context"], row["prediction_length"]
    if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
        raise ValueError("prediction_length must be a positive integer")
    if length > MODEL_HORIZON_LIMIT:
        raise ValueError("prediction_length exceeds the model's output limit")
    if not isinstance(context, list) or not 0 < len(context) <= MODEL_CONTEXT_LIMIT:
        raise ValueError("context must be a nonempty list within the model's context limit")
    observed = 0
    for value in context:
        if value is None:
            continue
        if not isinstance(value, float) or not math.isfinite(value):
            raise ValueError("context values must be finite floats or null")
        observed += 1
    if not observed:
        raise ValueError("a context needs at least one observed value")
    if row["request_id"] != request_id(context, length):
        raise ValueError("request id does not match its content")
    return row["request_id"], context, length


def read_requests(path: Path) -> list[tuple[str, list[float | None], int]]:
    seen: set[str] = set()
    requests = []
    with path.open() as stream:
        for line in stream:
            parsed = check_request(json.loads(line))
            if parsed[0] in seen:
                raise ValueError("duplicate request id; the exporter writes each context once")
            seen.add(parsed[0])
            requests.append(parsed)
    if not requests:
        raise ValueError("no requests")
    return requests


def batches[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def forecast_rows(
    requests: Sequence[tuple[str, list[float | None], int]],
    forecaster: Forecaster,
    *,
    batch_size: int,
    levels: Sequence[float],
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[list[dict[str, Any]], list[dict[str, float | int]], int]:
    """Forecast in fixed request order; group by horizon so a batch shares one length.

    Raw quantiles are stored unchanged. Steps whose quantiles cross are counted here;
    the CPU adapter rearranges them, so the stored forecast stays the model's output.
    """
    by_length: dict[int, list[tuple[str, list[float | None], int]]] = {}
    for item in requests:
        by_length.setdefault(item[2], []).append(item)
    rows: list[dict[str, Any]] = []
    timings: list[dict[str, float | int]] = []
    crossed = 0
    for length, group in sorted(by_length.items()):
        for batch in batches(group, batch_size):
            started = clock()
            output = forecaster([context for _, context, _ in batch], length)
            elapsed = clock() - started
            if len(output) != len(batch):
                raise ValueError("forecaster returned the wrong number of series")
            for (rid, _, _), quantiles in zip(batch, output, strict=True):
                if len(quantiles) != length or any(len(step) != len(levels) for step in quantiles):
                    raise ValueError("forecast shape must be prediction_length x quantile levels")
                for step in quantiles:
                    if not all(math.isfinite(v) for v in step):
                        raise ValueError("forecast contains a non-finite quantile")
                    crossed += any(b < a for a, b in pairwise(step))
                rows.append({"request_id": rid, "quantiles": quantiles})
            timings.append({"series": len(batch), "prediction_length": length, "seconds": elapsed})
    return rows, timings, crossed


def write_new(path: Path, lines: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        for line in lines:
            digest.update(line)
            stream.write(line)
    return digest.hexdigest()


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def write_run(
    output: Path,
    requests_path: Path,
    requests: Sequence[tuple[str, list[float | None], int]],
    rows: Sequence[dict[str, Any]],
    levels: Sequence[float],
    crossed: int,
    details: dict[str, Any],
) -> dict[str, Any]:
    """Write forecasts and the identity the CPU harness verifies before scoring them."""
    evidence = {
        "format": PREDICTION_FORMAT,
        "request_format": REQUEST_FORMAT,
        "data": "causal context windows only; no subject ids, cutoffs or targets",
        "requests_sha256": file_sha256(requests_path),
        "predictions_sha256": write_new(
            output / "predictions.jsonl", (canonical_bytes(r) for r in rows)
        ),
        "requests": len(requests),
        "context_lengths": sorted({len(c) for _, c, _ in requests}),
        "prediction_lengths": sorted({n for _, _, n in requests}),
        "quantile_levels": list(levels),
        "crossed_quantile_steps": crossed,
        **details,
    }
    write_new(output / "inference.json", [json.dumps(evidence, indent=2).encode() + b"\n"])
    return evidence


def run(args: argparse.Namespace) -> dict[str, Any]:
    import torch
    from huggingface_hub import snapshot_download

    from chronos import Chronos2Pipeline

    started = time.monotonic()
    output = Path(os.environ.get("HACHI_RUN_DIR", "")) if args.output is None else args.output
    if not output.is_dir():
        raise SystemExit("output must be an existing run directory (HACHI_RUN_DIR under gpu-run)")
    spec = json.loads(args.model.read_text())
    requests = read_requests(args.requests)
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable; run under scripts/gx10/gpu-run on the GX10")
    torch.manual_seed(0)
    torch.cuda.reset_peak_memory_stats()

    load_start = time.monotonic()
    # The owner cache already holds the pinned revision; never resolve a newer one here.
    snapshot = Path(
        snapshot_download(
            spec["model_id"],
            revision=spec["revision"],
            allow_patterns=["config.json", "model.safetensors"],
            local_files_only=True,
        )
    )
    weights = file_sha256(snapshot / "model.safetensors")
    if weights != spec["weights_sha256"]:
        raise SystemExit("checkpoint checksum does not match the pinned weights")
    pipeline = Chronos2Pipeline.from_pretrained(
        str(snapshot), device_map="cuda", torch_dtype=torch.float32
    )
    pipeline.model.eval()
    load_seconds = time.monotonic() - load_start
    levels = [float(q) for q in pipeline.quantiles]

    def forecaster(contexts: list[list[float | None]], length: int) -> list[list[list[float]]]:
        tensors = [
            torch.tensor([math.nan if v is None else v for v in c], dtype=torch.float32)
            for c in contexts
        ]
        with torch.no_grad():
            predictions = pipeline.predict(
                tensors,
                prediction_length=length,
                batch_size=args.batch_size,
                cross_learning=False,
                limit_prediction_length=True,
            )
        torch.cuda.synchronize()
        # Each prediction is (variates=1, quantiles, horizon); store horizon x quantiles.
        return [p[0].T.tolist() for p in predictions]

    # Warm kernels on the first request, then time single-request and batched paths.
    forecaster([requests[0][1]], requests[0][2])
    single: list[float] = []
    for _, context, length in requests[: args.latency_samples]:
        single_start = time.perf_counter()
        forecaster([context], length)
        single.append(time.perf_counter() - single_start)
    single_peak = torch.cuda.max_memory_allocated()
    torch.cuda.reset_peak_memory_stats()
    infer_start = time.monotonic()
    rows, timings, crossed = forecast_rows(
        requests, forecaster, batch_size=args.batch_size, levels=levels
    )
    infer_seconds = time.monotonic() - infer_start
    batch_seconds = [t["seconds"] for t in timings]
    details = {
        "owner": os.environ.get("HACHI_OWNER"),
        "model": spec,
        "weights_sha256": weights,
        "inference": {
            "device_map": "cuda",
            "torch_dtype": "float32",
            "batch_size": args.batch_size,
            "cross_learning": False,
            "missing_values": "NaN in context (Chronos-2 masks them)",
            "covariates": "none",
        },
        "timing": {
            "model_load_seconds": load_seconds,
            "batched_inference_seconds": infer_seconds,
            "batched_seconds_per_series": infer_seconds / len(requests),
            "batches": len(timings),
            "batch_seconds_p50": _percentile(batch_seconds, 0.5),
            "batch_seconds_max": max(batch_seconds),
            "single_request_samples": len(single),
            "single_request_seconds_p50": _percentile(single, 0.5) if single else None,
            "single_request_seconds_p95": _percentile(single, 0.95) if single else None,
            "total_seconds": time.monotonic() - started,
        },
        "memory": {
            "peak_cuda_allocated_bytes_single_request": single_peak,
            "peak_cuda_allocated_bytes_batched": torch.cuda.max_memory_allocated(),
            "peak_cuda_reserved_bytes_batched": torch.cuda.max_memory_reserved(),
            "peak_process_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "note": "GB10 memory is unified; allocator peaks do not cover all device memory",
        },
        "environment": {
            "python": sys.version,
            "python_executable": sys.executable,
            "architecture": platform.machine(),
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
            "capability": list(torch.cuda.get_device_capability(0)),
            "gpu_identity": subprocess.check_output(
                ["nvidia-smi", "--query-gpu=uuid,name,driver_version", "--format=csv,noheader"],
                text=True,
            ).strip(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("chronos-forecasting", "transformers", "accelerate", "numpy")
            },
            "script_sha256": file_sha256(Path(__file__).resolve()),
            "source_commit": subprocess.run(
                ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            ).stdout.strip()
            or None,
        },
    }
    return write_run(output, args.requests, requests, rows, levels, crossed, details)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requests", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path, help="infra/gx10/model.json")
    parser.add_argument("--output", type=Path, help="defaults to $HACHI_RUN_DIR")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--latency-samples", type=int, default=32)
    evidence = run(parser.parse_args(argv))
    print(json.dumps({k: evidence[k] for k in ("requests", "timing", "memory")}, indent=2))


if __name__ == "__main__":
    main()
