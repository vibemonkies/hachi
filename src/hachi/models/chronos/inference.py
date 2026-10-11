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
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType
from typing import Any, NamedTuple

REQUEST_FORMAT = "chronos-context-1"
PREDICTION_FORMAT = "chronos-quantiles-1"
EMBEDDING_FORMAT = "chronos-embeddings-1"
# Model card limits for amazon/chronos-2 (config.json: context_length, max_output_patches * 16).
MODEL_CONTEXT_LIMIT = 8192
MODEL_HORIZON_LIMIT = 1024


class Request(NamedTuple):
    request_id: str
    context: list[float | None]
    prediction_length: int
    # Past-only covariates aligned with the context; never values after the cutoff.
    past_covariates: Mapping[str, list[float | None]] = MappingProxyType({})


type Forecaster = Callable[[list[Request], int], list[list[list[float]]]]
type Embedder = Callable[[list[Request]], list[tuple[list[float], float, float]]]


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def request_id(
    context: Sequence[float | None],
    prediction_length: int,
    past_covariates: Mapping[str, Sequence[float | None]] | None = None,
) -> str:
    """Content identity of one causal context; identical windows share one forecast.

    Univariate requests hash exactly as before covariates existed.
    """
    document: dict[str, Any] = {
        "format": REQUEST_FORMAT,
        "context": list(context),
        "prediction_length": prediction_length,
    }
    if past_covariates:
        document["past_covariates"] = {k: list(v) for k, v in past_covariates.items()}
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _check_series(values: Any, length: int | None, label: str) -> int:
    if not isinstance(values, list) or not 0 < len(values) <= MODEL_CONTEXT_LIMIT:
        raise ValueError(f"{label} must be a nonempty list within the model's context limit")
    if length is not None and len(values) != length:
        raise ValueError(f"{label} must align with the context")
    observed = 0
    for value in values:
        if value is None:
            continue
        if not isinstance(value, float) or not math.isfinite(value):
            raise ValueError(f"{label} values must be finite floats or null")
        observed += 1
    return observed


def check_request(row: dict[str, Any]) -> Request:
    keys = {"request_id", "context", "prediction_length"}
    if not keys <= set(row) <= keys | {"past_covariates"}:
        raise ValueError(
            "request rows hold exactly request_id, context, prediction_length "
            "and optional past_covariates"
        )
    context, length = row["context"], row["prediction_length"]
    if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
        raise ValueError("prediction_length must be a positive integer")
    if length > MODEL_HORIZON_LIMIT:
        raise ValueError("prediction_length exceeds the model's output limit")
    if not _check_series(context, None, "context"):
        raise ValueError("a context needs at least one observed value")
    covariates = row.get("past_covariates", {})
    if not isinstance(covariates, dict) or ("past_covariates" in row and not covariates):
        raise ValueError("past_covariates must be a nonempty mapping when present")
    for name, values in covariates.items():
        if not isinstance(name, str) or not name:
            raise ValueError("covariate names must be nonempty strings")
        _check_series(values, len(context), f"covariate {name}")
    if row["request_id"] != request_id(context, length, covariates):
        raise ValueError("request id does not match its content")
    return Request(row["request_id"], context, length, covariates)


def read_requests(path: Path) -> list[Request]:
    seen: set[str] = set()
    requests = []
    with path.open() as stream:
        for line in stream:
            parsed = check_request(json.loads(line))
            if parsed.request_id in seen:
                raise ValueError("duplicate request id; the exporter writes each context once")
            seen.add(parsed.request_id)
            requests.append(parsed)
    if not requests:
        raise ValueError("no requests")
    return requests


def batches[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _schema(item: Request) -> tuple[int, tuple[str, ...]]:
    return item.prediction_length, tuple(sorted(item.past_covariates))


def forecast_rows(
    requests: Sequence[Request],
    forecaster: Forecaster,
    *,
    batch_size: int,
    levels: Sequence[float],
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[list[dict[str, Any]], list[dict[str, float | int]], int]:
    """Forecast in fixed request order; a batch shares one horizon and covariate schema.

    Raw quantiles are stored unchanged. Steps whose quantiles cross are counted here;
    the CPU adapter rearranges them, so the stored forecast stays the model's output.
    """
    groups: dict[tuple[int, tuple[str, ...]], list[Request]] = {}
    for item in requests:
        groups.setdefault(_schema(item), []).append(item)
    rows: list[dict[str, Any]] = []
    timings: list[dict[str, float | int]] = []
    crossed = 0
    for (length, _), group in sorted(groups.items()):
        for batch in batches(group, batch_size):
            started = clock()
            output = forecaster(list(batch), length)
            elapsed = clock() - started
            if len(output) != len(batch):
                raise ValueError("forecaster returned the wrong number of series")
            for item, quantiles in zip(batch, output, strict=True):
                if len(quantiles) != length or any(len(step) != len(levels) for step in quantiles):
                    raise ValueError("forecast shape must be prediction_length x quantile levels")
                for step in quantiles:
                    if not all(math.isfinite(v) for v in step):
                        raise ValueError("forecast contains a non-finite quantile")
                    crossed += any(b < a for a, b in pairwise(step))
                rows.append({"request_id": item.request_id, "quantiles": quantiles})
            timings.append({"series": len(batch), "prediction_length": length, "seconds": elapsed})
    return rows, timings, crossed


def embed_rows(
    requests: Sequence[Request], embedder: Embedder, *, batch_size: int
) -> list[dict[str, Any]]:
    """One pooled encoder embedding per univariate context, with its location and scale."""
    if any(item.past_covariates for item in requests):
        raise ValueError("embeddings are defined for univariate contexts only")
    rows: list[dict[str, Any]] = []
    width = None
    for batch in batches(list(requests), batch_size):
        output = embedder(list(batch))
        if len(output) != len(batch):
            raise ValueError("embedder returned the wrong number of series")
        for item, (vector, loc, scale) in zip(batch, output, strict=True):
            width = len(vector) if width is None else width
            if len(vector) != width or not all(math.isfinite(v) for v in (*vector, loc, scale)):
                raise ValueError("embeddings must be finite and of one width")
            rows.append(
                {"request_id": item.request_id, "embedding": vector, "loc": loc, "scale": scale}
            )
    return rows


def write_new(path: Path, lines: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        for line in lines:
            digest.update(line)
            stream.write(line)
    return digest.hexdigest()


def single_latency(call: Callable[[Request], Any], items: Sequence[Request], samples: int) -> dict:
    """Warm once, then time `samples` single-request calls (the serving path's latency)."""
    if not items:
        return {"single_request_samples": 0}
    call(items[0])
    seconds = []
    for item in items[:samples]:
        started = time.perf_counter()
        call(item)
        seconds.append(time.perf_counter() - started)
    return {
        "single_request_samples": len(seconds),
        "single_request_seconds_p50": _percentile(seconds, 0.5) if seconds else None,
        "single_request_seconds_p95": _percentile(seconds, 0.95) if seconds else None,
    }


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def write_run(
    output: Path,
    requests_path: Path,
    requests: Sequence[Request],
    rows: Sequence[dict[str, Any]],
    levels: Sequence[float],
    crossed: int,
    details: dict[str, Any],
    *,
    kind: str = "forecast",
) -> dict[str, Any]:
    """Write forecasts (or embeddings) and the identity the CPU side verifies before use."""
    filename = {"forecast": "predictions.jsonl", "embed": "embeddings.jsonl"}[kind]
    evidence = {
        "format": PREDICTION_FORMAT if kind == "forecast" else EMBEDDING_FORMAT,
        "request_format": REQUEST_FORMAT,
        "data": "causal context windows only; no subject ids, cutoffs or targets",
        "requests_sha256": file_sha256(requests_path),
        f"{filename.split('.')[0]}_sha256": write_new(
            output / filename, (canonical_bytes(r) for r in rows)
        ),
        "requests": len(requests),
        "context_lengths": sorted({len(r.context) for r in requests}),
        "prediction_lengths": sorted({r.prediction_length for r in requests}),
        "past_covariates": sorted({k for r in requests for k in r.past_covariates}),
        "quantile_levels": list(levels),
        "crossed_quantile_steps": crossed,
        **details,
    }
    write_new(output / "inference.json", [json.dumps(evidence, indent=2).encode() + b"\n"])
    return evidence


def load_pipeline(spec: dict[str, Any], checkpoint: Path | None, checkpoint_sha256: str | None):
    """The pinned public checkpoint, or a local fine-tuned one verified by its weight hash."""
    import torch
    from huggingface_hub import snapshot_download

    from chronos import Chronos2Pipeline

    if checkpoint is None:
        # The owner cache already holds the pinned revision; never resolve a newer one here.
        directory = Path(
            snapshot_download(
                spec["model_id"],
                revision=spec["revision"],
                allow_patterns=["config.json", "model.safetensors"],
                local_files_only=True,
            )
        )
        expected = spec["weights_sha256"]
    else:
        if checkpoint_sha256 is None:
            raise SystemExit("a local checkpoint needs its expected weight sha256")
        directory, expected = checkpoint, checkpoint_sha256
    weights = file_sha256(directory / "model.safetensors")
    if weights != expected:
        raise SystemExit("checkpoint checksum does not match the expected weights")
    pipeline = Chronos2Pipeline.from_pretrained(
        str(directory), device_map="cuda", torch_dtype=torch.float32
    )
    pipeline.model.eval()
    return pipeline, weights


def environment() -> dict[str, Any]:
    import torch

    return {
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
    }


def model_inputs(items: Sequence[Request]) -> list[Any]:
    """Chronos-2 inputs: a tensor per univariate context, a dict when covariates exist."""
    import torch

    def tensor(values: Sequence[float | None]):
        return torch.tensor([math.nan if v is None else v for v in values], dtype=torch.float32)

    return [
        {
            "target": tensor(item.context),
            "past_covariates": {k: tensor(v) for k, v in item.past_covariates.items()},
        }
        if item.past_covariates
        else tensor(item.context)
        for item in items
    ]


def pipeline_forecaster(pipeline, batch_size: int) -> Forecaster:
    import torch

    def forecaster(items: list[Request], length: int) -> list[list[list[float]]]:
        with torch.no_grad():
            predictions = pipeline.predict(
                model_inputs(items),
                prediction_length=length,
                batch_size=batch_size,
                cross_learning=False,
                limit_prediction_length=True,
            )
        torch.cuda.synchronize()
        # Each prediction is (target variates=1, quantiles, horizon); store horizon x quantiles.
        return [p[0].T.tolist() for p in predictions]

    return forecaster


def run(args: argparse.Namespace) -> dict[str, Any]:
    import torch

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
    pipeline, weights = load_pipeline(spec, args.checkpoint, args.checkpoint_sha256)
    load_seconds = time.monotonic() - load_start
    levels = [float(q) for q in pipeline.quantiles]
    model = {
        "base": spec,
        "weights_sha256": weights,
        "checkpoint": None if args.checkpoint is None else args.checkpoint.name,
    }
    if args.mode == "embed":

        def embedder(items: list[Request]) -> list[tuple[list[float], float, float]]:
            with torch.no_grad():
                embeddings, loc_scale = pipeline.embed(
                    model_inputs(items), batch_size=args.batch_size
                )
            return [
                (
                    e[0].mean(dim=0).float().tolist(),
                    float(ls[0].flatten()[0]),
                    float(ls[1].flatten()[0]),
                )
                for e, ls in zip(embeddings, loc_scale, strict=True)
            ]

        latency = single_latency(lambda item: embedder([item]), requests, args.latency_samples)
        torch.cuda.reset_peak_memory_stats()
        embed_start = time.monotonic()
        rows = embed_rows(requests, embedder, batch_size=args.batch_size)
        details = {
            "owner": os.environ.get("HACHI_OWNER"),
            "model": model["base"],
            "weights_sha256": weights,
            "checkpoint": model["checkpoint"],
            "embedding": "mean over all encoder tokens of the first variate",
            "timing": {
                "model_load_seconds": load_seconds,
                "embed_seconds": time.monotonic() - embed_start,
                **latency,
            },
            "memory": {
                "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
                "peak_process_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            },
            "environment": environment(),
        }
        return write_run(output, args.requests, requests, rows, levels, 0, details, kind="embed")

    forecaster = pipeline_forecaster(pipeline, args.batch_size)
    # Warm kernels on the first request, then time single-request and batched paths.
    forecaster([requests[0]], requests[0].prediction_length)
    single: list[float] = []
    for item in requests[: args.latency_samples]:
        single_start = time.perf_counter()
        forecaster([item], item.prediction_length)
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
        "checkpoint": model["checkpoint"],
        "inference": {
            "device_map": "cuda",
            "torch_dtype": "float32",
            "batch_size": args.batch_size,
            "cross_learning": False,
            "missing_values": "NaN in context (Chronos-2 masks them)",
            "covariates": "past-only when present; never future covariates",
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
        "environment": environment(),
    }
    return write_run(output, args.requests, requests, rows, levels, crossed, details)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requests", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path, help="infra/gx10/model.json")
    parser.add_argument("--checkpoint", type=Path, help="local fine-tuned checkpoint directory")
    parser.add_argument("--checkpoint-sha256", help="expected model.safetensors sha256")
    parser.add_argument("--mode", choices=("forecast", "embed"), default="forecast")
    parser.add_argument("--output", type=Path, help="defaults to $HACHI_RUN_DIR")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--latency-samples", type=int, default=32)
    evidence = run(parser.parse_args(argv))
    print(json.dumps({k: evidence.get(k) for k in ("requests", "timing", "memory")}, indent=2))


if __name__ == "__main__":
    main()
