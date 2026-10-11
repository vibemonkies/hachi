"""How much the served forecasters degrade on Apple-like (thinned) heart-rate history.

  python -m hachi.models.density.run export --snapshot DIR --output PRIVATE_DIR
  # GX10: hachi.models.chronos inference.py on PRIVATE_DIR/{full,thin}/requests.jsonl (gpu-run)
  python -m hachi.models.density.run score --snapshot DIR --export PRIVATE_DIR \
      --gx10-full RUN --gx10-thin RUN --output PRIVATE_DIR/score
  python -m hachi.models.density.run fit --snapshot DIR --variant FILE --output PRIVATE_DIR/fit

Each model (the four #9 comparators and Chronos-2 zero-shot) is evaluated twice on the same
sealed splits and the same full-density targets: once with the frozen protocol's full-density
history, once with the predeclared variant's thinned history. Predictions are paired per
participant, cutoff and target hour; abstentions on either side leave the pairing and are
counted. Only the active outer fold's inner validation folds are scored; its test stays sealed.

`fit --variant FILE` freezes the CPU comparators at a variant's gates for serving: the committed
#9 runner fits, saves and replay-checks each model on that variant's thinned history, with
full-density labels, and labels every packet's run_id with the thinning's pipeline suffix.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from hachi.evaluation import evaluate_forecast, hourly_features
from hachi.evaluation.forecast import EvaluationResult, target_quality_eligible
from hachi.evaluation.metrics import ScoredPoint, bootstrap_participant_mean, forecast_metrics
from hachi.evaluation.pmdata_run import ReplacementHistory
from hachi.evaluation.pmdata_run import run as run_protocol
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.chronos import AdapterLog, load_forecasts, replay_factory
from hachi.models.chronos.pmdata import (
    CHRONOS_MODEL_ID,
    ChronosPMDataConfig,
    Inputs,
    baseline_factory,
    export,
    prepare,
)

from .config import REPO, load_variant
from .thinning import thinned_bins

VARIANT = REPO / "configs/evaluation/pmdata-hourly-validation-apple-density.json"
CHRONOS_FULL = REPO / "configs/models/chronos/pmdata-hourly-hr.json"
CHRONOS_THIN = REPO / "configs/models/chronos/pmdata-hourly-hr-apple-density.json"
MODEL_IDS = (
    "hourly-last-valid-v1",
    "utc-seasonal-naive-v1",
    "train-population-mean-v1",
    "causal-hourly-tree-v1",
    CHRONOS_MODEL_ID,
)


def _write(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value if isinstance(value, bytes) else document_bytes(value))


def build_inputs(
    snapshot: Path, variant_path: Path = VARIANT, chronos_thin: Path = CHRONOS_THIN
) -> tuple[Inputs, Inputs, dict[str, Any]]:
    """Full-density inputs (the frozen protocol) and thinned-history inputs (the variant)."""
    variant, base = load_variant(variant_path)
    full = prepare(
        snapshot, base, ChronosPMDataConfig.model_validate_json(CHRONOS_FULL.read_bytes())
    )
    thin_config = ChronosPMDataConfig.model_validate_json(chronos_thin.read_bytes())
    bins, thin_counts = thinned_bins(snapshot, variant.thinning)
    view = hourly_features(bins, variant.protocol.feature_policy)
    probe = prepare(snapshot, variant.protocol, thin_config)  # same splits, binding checked
    if probe.splits != full.splits or document_sha256(probe.plan) != document_sha256(full.plan):
        raise ValueError("the variant must use the frozen protocol's splits")
    # History is thinned; labels stay the full-density aggregates.
    thin = replace(probe, view=view, labels=full.labels)
    audit = {
        "variant_sha256": document_sha256(variant),
        "variant_protocol_sha256": document_sha256(variant.protocol),
        "base_protocol_sha256": document_sha256(base),
        "thinning": variant.thinning.model_dump(),
        "thinning_counts": thin_counts,
        "full_feature_counts": full.view.counts,
        "thin_feature_counts": view.counts,
    }
    return full, thin, audit


def evaluate_all(inputs: Inputs, forecasts) -> dict[str, list[EvaluationResult]]:
    """Every model on every inner fold, with this input's history and the shared labels."""
    out: dict[str, list[EvaluationResult]] = defaultdict(list)
    protocol = inputs.protocol
    for split in inputs.splits:
        for model_config in [*protocol.baselines, protocol.tree]:
            fitted: list = []
            result = evaluate_forecast(
                split,
                inputs.view.features,
                inputs.labels,
                baseline_factory(protocol, model_config, fitted),
                protocol.evaluation,
            )
            out[fitted[0].model_id].append(result)
        log = AdapterLog()
        result = evaluate_forecast(
            split,
            inputs.view.features,
            inputs.labels,
            replay_factory(inputs.config.chronos, forecasts.quantiles, forecasts.levels, log),
            inputs.evaluation,
        )
        out[CHRONOS_MODEL_ID].append(result)
    return out


def pair(full: EvaluationResult, thin: EvaluationResult, labels, config) -> dict[str, Any]:
    """Same target hours, both models predicting, label eligible under the shared rule."""
    eligible = {
        (t.subject_id, t.interval_start_utc): t.value
        for t in labels
        if t.metric == config.metric
        and t.resolution == "hour"
        and t.aggregation == config.aggregation
        and t.value is not None
        and target_quality_eligible(t, config)
    }

    def estimates(result: EvaluationResult) -> dict[tuple, Any]:
        return {
            (p.origin.subject_id, p.origin.cutoff, w.start_utc): e
            for p in result.predictions
            for w, e in zip(p.origin.targets, p.estimates, strict=True)
        }

    a, b = estimates(full), estimates(thin)
    counts: Counter[str] = Counter()
    points_full: list[ScoredPoint] = []
    points_thin: list[ScoredPoint] = []
    for key in sorted(a.keys() | b.keys()):
        truth = eligible.get((key[0], key[2]))
        if truth is None:
            counts["unlabelled_or_ineligible"] += 1
            continue
        x, y = a.get(key), b.get(key)
        if x is None and y is None:
            counts["both_abstained"] += 1
        elif y is None:
            counts["full_only"] += 1
        elif x is None:
            counts["thin_only"] += 1
        else:
            counts["paired"] += 1
            points_full.append(ScoredPoint(key[0], truth, x.median, x.lower, x.upper))
            points_thin.append(ScoredPoint(key[0], truth, y.median, y.lower, y.upper))
    return {"counts": counts, "full": points_full, "thin": points_thin}


def _estimate(value) -> dict[str, Any] | None:
    return asdict(value) if value is not None else None


def summarize(
    pairs: dict[str, list[dict[str, Any]]],
    results: dict[str, dict[str, list[EvaluationResult]]],
    config,
    seed: int,
) -> dict[str, Any]:
    models = {}
    for model, fold_pairs in pairs.items():
        full_points = [p for f in fold_pairs for p in f["full"]]
        thin_points = [p for f in fold_pairs for p in f["thin"]]
        report = {}
        for name, points in (("full", full_points), ("thin", thin_points)):
            metrics = forecast_metrics(
                points,
                metric=config.metric,
                unit="bpm",
                bootstrap_samples=config.bootstrap_samples,
                confidence=config.confidence,
                seed=seed,
            )
            report[name] = metrics
        by_subject_full = {s.subject_id: s for s in report["full"].subjects}
        differences = defaultdict(list)
        for s in report["thin"].subjects:
            f = by_subject_full[s.subject_id]
            differences["mae"].append(s.mae - f.mae)
            differences["rmse"].append(s.rmse - f.rmse)
            differences["median_pinball_loss"].append(s.median_pinball_loss - f.median_pinball_loss)
            if s.interval_coverage is not None and f.interval_coverage is not None:
                differences["interval_coverage"].append(s.interval_coverage - f.interval_coverage)
        own = {}
        for density in ("full", "thin"):
            rows = results[density][model]
            own[density] = {
                "scored_points": sum(r.counts["scored_points"] for r in rows),
                "abstained_points": sum(r.counts["abstained_points"] for r in rows),
                "insufficient_history_points": sum(
                    r.counts["insufficient_history_points"] for r in rows
                ),
                "predicted_origins": sum(r.counts["predicted_origins"] for r in rows),
            }
        counts = Counter()
        for f in fold_pairs:
            counts.update(f["counts"])
        models[model] = {
            "coverage": {**own, "pairing": dict(sorted(counts.items()))},
            "paired_full": {
                k: _estimate(getattr(report["full"], k))
                for k in ("mae", "rmse", "median_pinball_loss", "interval_coverage")
            },
            "paired_thin": {
                k: _estimate(getattr(report["thin"], k))
                for k in ("mae", "rmse", "median_pinball_loss", "interval_coverage")
            },
            "thin_minus_full": {
                k: _estimate(
                    bootstrap_participant_mean(
                        v, samples=config.bootstrap_samples, confidence=config.confidence, seed=seed
                    )
                )
                for k, v in differences.items()
            },
            "participants_worse_better": [
                sum(d > 0 for d in differences["mae"]),
                sum(d < 0 for d in differences["mae"]),
            ],
            "per_fold_thin_minus_full_mae": [
                round(_fold_delta(f), 3) if f["thin"] else None for f in fold_pairs
            ],
        }
    return models


def _fold_delta(fold: dict[str, Any]) -> float:
    def mae(points):
        by = defaultdict(list)
        for p in points:
            by[p.subject_id].append(abs(p.median - p.truth))
        return {s: sum(v) / len(v) for s, v in by.items()}

    a, b = mae(fold["full"]), mae(fold["thin"])
    return sum(b[s] - a[s] for s in a) / len(a)


def _git() -> dict[str, Any]:
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True))
    return {"git_sha": sha, "git_dirty": dirty}


def run_export(snapshot: Path, output: Path, variant: Path, chronos: Path) -> dict[str, Any]:
    full, thin, audit = build_inputs(snapshot, variant, chronos)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {
        **_git(),
        **audit,
        "full": export(full, output / "full"),
        "thin": export(thin, output / "thin"),
    }
    _write(output / "export.json", manifest)
    return manifest


def run_score(
    snapshot: Path,
    export_dir: Path,
    gx10_full: Path,
    gx10_thin: Path,
    output: Path,
    variant: Path,
    chronos: Path,
):
    full, thin, audit = build_inputs(snapshot, variant, chronos)
    exported = json.loads((export_dir / "export.json").read_bytes())
    for key in ("variant_sha256", "variant_protocol_sha256", "base_protocol_sha256"):
        if exported[key] != audit[key]:
            raise ValueError(f"export was made with a different {key}")
    forecasts = {
        "full": load_forecasts(export_dir / "full/requests.jsonl", gx10_full),
        "thin": load_forecasts(export_dir / "thin/requests.jsonl", gx10_thin),
    }
    for f in forecasts.values():
        pin = full.config.chronos.model
        if f.evidence["weights_sha256"] != pin.weights_sha256:
            raise ValueError("GX10 run used a different checkpoint than the pinned one")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        results = {
            "full": evaluate_all(full, forecasts["full"]),
            "thin": evaluate_all(thin, forecasts["thin"]),
        }
        pairs: dict[str, list[dict[str, Any]]] = {}
        rows = []
        for model in MODEL_IDS:
            pairs[model] = []
            for fold, a, b in zip(
                full.folds, results["full"][model], results["thin"][model], strict=True
            ):
                if a.split_manifest_sha256 != b.split_manifest_sha256:
                    raise ValueError("full and thin runs used different splits")
                paired = pair(a, b, full.labels, full.protocol.evaluation)
                pairs[model].append(paired)
                name = f"outer-{fold.outer_fold}-inner-{fold.inner_fold}"
                root = output / name
                root.mkdir(mode=0o700, exist_ok=True)
                _write(root / f"{model}-full.json", a)
                _write(root / f"{model}-thin.json", b)
                for side, points in (("full", paired["full"]), ("thin", paired["thin"])):
                    rows += [
                        {"fold": name, "model": model, "history": side, "subject_id": p.subject_id,
                         "truth": p.truth, "median": p.median}
                        for p in points
                    ]  # fmt: skip
        sink = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist(rows), sink)
        _write(output / "paired-points.parquet", sink.getvalue().to_pybytes())
        summary = {
            **_git(),
            "created_at_utc": datetime.now(UTC).isoformat(),
            **audit,
            "dataset_snapshot": full.protocol.expected_snapshot.model_dump(),
            "nested_plan_sha256": document_sha256(full.plan),
            "split_sha256": [document_sha256(s) for s in full.splits],
            "outer_test_sealed": True,
            "validation_participants": len({s for x in full.splits for s in x.validation_subjects}),
            "full_requests_sha256": exported["full"]["requests_sha256"],
            "thin_requests_sha256": exported["thin"]["requests_sha256"],
            "full_evaluation_sha256": {
                m: [document_sha256(r) for r in results["full"][m]] for m in MODEL_IDS
            },
            "models": summarize(pairs, results, full.protocol.evaluation, full.protocol.folds.seed),
            "definition": (
                "thin minus full per participant on paired targets; "
                "positive = worse with Apple-like history"
            ),
        }
        _write(output / "summary.json", summary)
        hashes = {
            str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.rglob("*"))
            if p.is_file()
        }
        _write(output / "sha256.json", hashes)
        return summary
    except Exception:
        _write(output / "failure.json", {"traceback": traceback.format_exc()})
        raise


def run_fit(snapshot: Path, output: Path, variant_path: Path) -> dict[str, Any]:
    """Every CPU comparator frozen on a variant's thinned history, with its own packet."""
    variant, base = load_variant(variant_path)
    bins, counts = thinned_bins(snapshot, variant.thinning)
    history = ReplacementHistory(
        label=variant.thinning.pipeline_suffix,
        bins=bins,
        audit={
            "variant_file_sha256": hashlib.sha256(variant_path.read_bytes()).hexdigest(),
            "variant_sha256": document_sha256(variant),
            "variant_protocol_sha256": document_sha256(variant.protocol),
            "base_protocol_sha256": document_sha256(base),
            "thinning": variant.thinning.model_dump(),
            "thinning_counts": counts,
        },
    )
    return run_protocol(snapshot, output, variant.protocol, history=history)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("export")
    e.add_argument("--snapshot", required=True, type=Path)
    e.add_argument("--output", required=True, type=Path)
    s = sub.add_parser("score")
    s.add_argument("--snapshot", required=True, type=Path)
    s.add_argument("--export", required=True, type=Path)
    s.add_argument("--gx10-full", required=True, type=Path)
    s.add_argument("--gx10-thin", required=True, type=Path)
    s.add_argument("--output", required=True, type=Path)
    for command in (e, s):
        command.add_argument("--variant", type=Path, default=VARIANT)
        command.add_argument("--chronos-thin", type=Path, default=CHRONOS_THIN)
    f = sub.add_parser("fit")
    f.add_argument("--snapshot", required=True, type=Path)
    f.add_argument("--output", required=True, type=Path)
    f.add_argument("--variant", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "export":
            result = run_export(args.snapshot, args.output, args.variant, args.chronos_thin)
        elif args.command == "fit":
            result = run_fit(args.snapshot, args.output, args.variant)
        else:
            result = run_score(
                args.snapshot,
                args.export,
                args.gx10_full,
                args.gx10_thin,
                args.output,
                args.variant,
                args.chronos_thin,
            )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
