"""Full Chronos-2 fine-tuning on the GX10, then forecasts from the fine-tuned weights.

Runs in the pinned GX10 runtime beside inference.py (stdlib at import; torch, Chronos
and transformers only inside `run`). Inputs come from the CPU harness: training series
built only from one inner fold's TrainingPrefix, ending before a temporal holdout;
holdout series whose final 24 h lie inside it (early stopping only); and that fold's
causal validation requests. Nothing here sees a validation label.

    scripts/gx10/gpu-run --owner justin06lee --run-id issue12-... -- \\
        "$runtime_py" -I src/hachi/models/chronos/finetune.py --model infra/gx10/model.json \\
        --train train.jsonl --holdout holdout.jsonl --requests requests.jsonl --learning-rate 1e-5
"""

import argparse
import json
import math
import os
import resource
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Sibling module from this directory; `-I` keeps the directory itself off sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from inference import (
    canonical_bytes,
    environment,
    file_sha256,
    forecast_rows,
    load_pipeline,
    pipeline_forecaster,
    read_requests,
    single_latency,
    write_new,
    write_run,
)

SERIES_FORMAT = "chronos-training-series-1"


def read_series(path: Path) -> list[dict[str, Any]]:
    """Opaque training series: target values (null = missing) and optional past covariates."""
    rows = []
    with path.open() as stream:
        for line in stream:
            row = json.loads(line)
            if set(row) - {"format", "series_id", "target", "past_covariates"}:
                raise ValueError("unexpected training series fields")
            if row.get("format") != SERIES_FORMAT:
                raise ValueError("unrecognized training series format")
            target = row["target"]
            if not any(isinstance(v, float) and math.isfinite(v) for v in target):
                raise ValueError("a training series needs observed values")
            for values in row.get("past_covariates", {}).values():
                if len(values) != len(target):
                    raise ValueError("covariates must align with their target")
            rows.append(row)
    if not rows:
        raise ValueError("no training series")
    return rows


def fit_inputs(rows: Sequence[dict[str, Any]]) -> list[Any]:
    import torch

    def tensor(values):
        return torch.tensor([math.nan if v is None else v for v in values], dtype=torch.float32)

    return [
        {
            "target": tensor(r["target"]),
            "past_covariates": {k: tensor(v) for k, v in r["past_covariates"].items()},
        }
        if r.get("past_covariates")
        else tensor(r["target"])
        for r in rows
    ]


def run(args: argparse.Namespace) -> dict[str, Any]:
    import torch
    from transformers import TrainerCallback, set_seed

    started = time.monotonic()
    output = Path(os.environ.get("HACHI_RUN_DIR", "")) if args.output is None else args.output
    if not output.is_dir():
        raise SystemExit("output must be an existing run directory (HACHI_RUN_DIR under gpu-run)")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable; run under scripts/gx10/gpu-run on the GX10")
    spec = json.loads(args.model.read_text())
    train, holdout = read_series(args.train), read_series(args.holdout)
    requests = read_requests(args.requests)
    set_seed(args.seed)
    torch.cuda.reset_peak_memory_stats()
    base, base_weights = load_pipeline(spec, None, None)

    history: list[dict[str, Any]] = []

    class Recorder(TrainerCallback):
        def on_log(self, _args, state, _control, logs=None, **_kwargs):
            history.append({"step": state.global_step, **(logs or {})})

    fit_start = time.monotonic()
    tuned = base.fit(
        fit_inputs(train),
        prediction_length=args.prediction_length,
        validation_inputs=fit_inputs(holdout),
        finetune_mode="full",
        context_length=args.context_length,
        learning_rate=args.learning_rate,
        num_steps=args.max_steps,
        batch_size=args.batch_size,
        output_dir=output / "trainer",
        min_past=args.min_past,
        finetuned_ckpt_name="finetuned",
        callbacks=[Recorder()],
        remove_printer_callback=True,
        # fp32 only: #1 certified fp32 training on the GB10, not BF16/TF32.
        bf16=False,
        tf32=False,
        seed=args.seed,
        data_seed=args.seed,
        eval_steps=args.eval_every,
        save_steps=args.eval_every,
        logging_steps=args.eval_every,
        optim=args.optim,
    )
    fit_seconds = time.monotonic() - fit_start
    peak_training = torch.cuda.max_memory_allocated()
    checkpoint = output / "trainer" / "finetuned"
    weights = file_sha256(checkpoint / "model.safetensors")
    evals = [h for h in history if "eval_loss" in h]
    best = min(evals, key=lambda h: h["eval_loss"]) if evals else None

    # Forecast from the saved checkpoint, reloaded and verified, not the in-memory copy.
    del tuned
    torch.cuda.empty_cache()
    pipeline, reloaded = load_pipeline(spec, checkpoint, weights)
    levels = [float(q) for q in pipeline.quantiles]
    torch.cuda.reset_peak_memory_stats()
    forecaster = pipeline_forecaster(pipeline, args.inference_batch_size)
    latency = single_latency(
        lambda item: forecaster([item], item.prediction_length), requests, args.latency_samples
    )
    infer_start = time.monotonic()
    rows, _, crossed = forecast_rows(
        requests, forecaster, batch_size=args.inference_batch_size, levels=levels
    )
    infer_seconds = time.monotonic() - infer_start
    training = {
        "format": "chronos-finetune-1",
        "base_model": spec,
        "base_weights_sha256": base_weights,
        "finetuned_weights_sha256": weights,
        "reloaded_weights_sha256": reloaded,
        "train_sha256": file_sha256(args.train),
        "holdout_sha256": file_sha256(args.holdout),
        "train_series": len(train),
        "holdout_series": len(holdout),
        "hyperparameters": {
            "finetune_mode": "full",
            "dtype": "float32",
            "learning_rate": args.learning_rate,
            "max_steps": args.max_steps,
            "eval_every_steps": args.eval_every,
            "batch_size": args.batch_size,
            "context_length": args.context_length,
            "prediction_length": args.prediction_length,
            "min_past": args.min_past,
            "optimizer": args.optim,
            "lr_scheduler": "linear",
            "warmup": 0,
            "seed": args.seed,
            "early_stopping": "load_best_model_at_end on holdout eval_loss",
        },
        "best": best,
        "log_history": history,
        "timing": {
            "fit_seconds": fit_seconds,
            **latency,
            "batched_inference_seconds": infer_seconds,
        },
        "memory": {
            "peak_cuda_allocated_bytes_training": peak_training,
            "peak_cuda_allocated_bytes_inference": torch.cuda.max_memory_allocated(),
            "peak_process_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "total_seconds": time.monotonic() - started,
        "environment": environment(),
    }
    write_new(output / "finetune.json", [canonical_bytes(training)])
    details = {
        "owner": os.environ.get("HACHI_OWNER"),
        "model": spec,
        "weights_sha256": reloaded,
        "checkpoint": "trainer/finetuned",
        "finetune_sha256": file_sha256(output / "finetune.json"),
        "timing": training["timing"],
        "memory": training["memory"],
        "environment": training["environment"],
    }
    return write_run(output, args.requests, requests, rows, levels, crossed, details)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, type=Path, help="infra/gx10/model.json")
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--holdout", required=True, type=Path)
    parser.add_argument("--requests", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="defaults to $HACHI_RUN_DIR")
    parser.add_argument("--learning-rate", required=True, type=float)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument("--eval-every", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--inference-batch-size", type=int, default=256)
    parser.add_argument("--context-length", type=int, default=48)
    parser.add_argument("--prediction-length", type=int, default=24)
    parser.add_argument("--min-past", type=int, default=24)
    parser.add_argument("--optim", default="adamw_torch_fused")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--latency-samples", type=int, default=16)
    evidence = run(parser.parse_args(argv))
    print(json.dumps({k: evidence.get(k) for k in ("requests", "timing", "memory")}, indent=2))


if __name__ == "__main__":
    main()
