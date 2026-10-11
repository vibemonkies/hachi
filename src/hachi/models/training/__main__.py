"""CLI for #12 on PMData: export GX10 inputs, choose the fine-tune context, score and select."""

import argparse
import json
import sys
import traceback
from pathlib import Path

from hachi.evaluation import evaluate_forecast
from hachi.evaluation.metrics import combine_metric_reports
from hachi.evaluation.serialization import document_bytes

from ..chronos.adapter import AdapterLog, replay_factory
from ..chronos.evaluation import load_forecasts
from .pmdata import VARIANTS, export, load_experiment, prepare
from .score import measure_cpu, run_score


def choose_context(snapshot: Path, export_dir: Path, zeroshot_dir: Path) -> dict:
    """Predeclared: the univariate zero-shot context with the lowest pooled validation MAE."""
    inputs = prepare(snapshot, load_experiment())
    forecasts = load_forecasts(export_dir / "forecast-requests.jsonl", zeroshot_dir)
    pooled = {}
    for variant, (hours, covariates) in VARIANTS.items():
        if covariates:
            continue
        reports = []
        for split in inputs.splits:
            factory = replay_factory(
                inputs.experiment.chronos.chronos,
                forecasts.quantiles,
                forecasts.levels,
                AdapterLog(),
                inputs.builder(variant),
            )
            result = evaluate_forecast(
                split, inputs.view.features, inputs.labels, factory, inputs.chronos_evaluation
            )
            reports.append(result.metrics)
        pooled[hours] = combine_metric_reports(
            reports, seed=inputs.experiment.protocol.folds.seed
        ).mae.value
    chosen = min(pooled, key=pooled.get)
    return {
        "rule": "lowest pooled inner-validation MAE of the univariate zero-shot contexts",
        "pooled_mae": pooled,
        "context_hours": chosen,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("export", "choose-context", "score", "cost"):
        command = commands.add_parser(name)
        command.add_argument("--snapshot", required=True, type=Path)
        if name == "export":
            command.add_argument("--output", required=True, type=Path)
        if name in ("choose-context", "score", "cost"):
            command.add_argument("--export", required=True, type=Path)
        if name in ("choose-context", "score"):
            command.add_argument("--zeroshot", required=True, type=Path)
        if name in ("score", "cost"):
            command.add_argument("--embed", required=True, type=Path)
        if name == "score":
            command.add_argument(
                "--finetune", action="append", default=[], help="RATE:FOLD:RUN_DIR, repeatable"
            )
            command.add_argument("--output", required=True, type=Path)
        if name == "cost":
            command.add_argument("--candidate", required=True)
    args = parser.parse_args()
    output = getattr(args, "output", None)
    try:
        if args.command == "export":
            result = export(prepare(args.snapshot, load_experiment()), args.output)
        elif args.command == "choose-context":
            result = choose_context(args.snapshot, args.export, args.zeroshot)
        elif args.command == "cost":
            result = measure_cpu(args.candidate, args.snapshot, args.export, args.embed)
        else:
            runs: dict[str, dict[int, Path]] = {}
            for item in args.finetune:
                rate, fold, path = item.split(":", 2)
                runs.setdefault(rate, {})[int(fold)] = Path(path)
            result = run_score(
                prepare(args.snapshot, load_experiment()),
                snapshot=args.snapshot,
                export_dir=args.export,
                zeroshot_dir=args.zeroshot,
                embed_dir=args.embed,
                finetune_runs=runs,
                output=args.output,
            )
            result = {k: result[k] for k in ("selection", "candidates")}
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    except Exception as error:
        # Row validation errors can quote participant values; keep diagnostics private.
        if output is not None and output.is_dir():
            (output / "failure.json").write_bytes(
                document_bytes({"traceback": traceback.format_exc()})
            )
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "detail": str(error)[:200]
                    if isinstance(error, ValueError | RuntimeError | KeyError)
                    else None,
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
