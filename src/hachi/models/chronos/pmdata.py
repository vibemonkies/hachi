"""Chronos-2 zero-shot on the frozen PMData validation protocol: export, infer, score.

1. `export` (CPU, no labels loaded into the harness): record every causal context the
   #7 harness hands a predictor across the active outer fold's inner validation folds.
2. GX10: `inference.py` under `scripts/gx10/gpu-run` answers exactly those requests.
3. `score` (CPU): replay the forecasts by content hash, pair Chronos with each #9
   comparator refit on identical origins, and write private packets plus a summary
   without participant identifiers.

Only validation origins are scheduled; the protocol's outer test fold stays sealed.
"""

import hashlib
import json
import os
import platform
import subprocess
import tracemalloc
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Literal

from hachi.contracts.base import Contract, Sha256, Text
from hachi.contracts.manifests import ModelRef, RunManifest, SplitManifest
from hachi.contracts.tables import Aggregate
from hachi.evaluation import (
    ComparisonResult,
    EvaluationConfig,
    ForecastInput,
    HourlyFeatureView,
    NestedFold,
    NestedFoldPlan,
    PredictorFactory,
    TrainingPrefix,
    compare_forecasts,
    evaluate_forecast,
    write_comparison_packet,
)
from hachi.evaluation.metrics import (
    Estimate,
    MetricReport,
    bootstrap_participant_mean,
    combine_metric_reports,
)
from hachi.evaluation.pmdata_run import PMDataProtocol, fold_split, load_inputs
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.baselines import BaselineConfig, TreeConfig, fit_baseline, fit_tree
from hachi.models.baselines.artifacts import ForecastArtifact
from hachi.models.baselines.tree import FEATURES

from .adapter import AdapterLog, ChronosConfig, replay_factory
from .evaluation import (
    QuantileReport,
    SubjectQuantiles,
    export_requests,
    load_forecasts,
    paired_quantile_report,
    summarize_quantiles,
    write_requests,
)
from .inference import file_sha256

CHRONOS_MODEL_ID = "chronos-2-zero-shot"
REPO = Path(__file__).resolve().parents[4]


class ChronosPMDataConfig(Contract):
    """Binds the model settings to one frozen protocol document by hash."""

    protocol_sha256: Sha256
    chronos: ChronosConfig
    pretrained_cohort_overlap: Literal["none", "known", "unknown"]
    overlap_note: Text


@dataclass(frozen=True)
class Inputs:
    protocol: PMDataProtocol
    config: ChronosPMDataConfig
    evaluation: EvaluationConfig
    plan: NestedFoldPlan
    folds: tuple[NestedFold, ...]
    splits: tuple[SplitManifest, ...]
    view: HourlyFeatureView
    labels: tuple[Aggregate, ...]


def chronos_evaluation(protocol: PMDataProtocol, config: ChronosPMDataConfig) -> EvaluationConfig:
    """The protocol's scoring rules; only the pretrained-overlap disclosure differs."""
    return EvaluationConfig.model_validate(
        {
            **protocol.evaluation.model_dump(),
            "pretrained_cohort_overlap": config.pretrained_cohort_overlap,
            "overlap_note": config.overlap_note,
        }
    )


def check_binding(protocol: PMDataProtocol, config: ChronosPMDataConfig) -> None:
    if document_sha256(protocol) != config.protocol_sha256:
        raise ValueError("Chronos config is bound to a different protocol document")
    chronos = config.chronos
    if (chronos.metric, chronos.aggregation) != (
        protocol.evaluation.metric,
        protocol.evaluation.aggregation,
    ):
        raise ValueError("Chronos must forecast the protocol's metric and aggregation")
    if chronos.context_hours != protocol.lookback_hours:
        raise ValueError("Chronos context must be exactly the protocol lookback")


def prepare(snapshot: Path, protocol: PMDataProtocol, config: ChronosPMDataConfig) -> Inputs:
    """The shared protocol inputs and sealed splits (pmdata_run), bound to this config."""
    check_binding(protocol, config)
    plan, view, labels = load_inputs(snapshot, protocol)
    folds = tuple(f for f in plan.folds if f.outer_fold == protocol.active_outer_fold)
    return Inputs(
        protocol,
        config,
        chronos_evaluation(protocol, config),
        plan,
        folds,
        tuple(fold_split(protocol, f) for f in folds),
        view,
        labels,
    )


def _write_private(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(document_bytes(value))


def _git() -> dict[str, Any]:
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True))
    return {"git_sha": sha, "git_dirty": dirty}


def _fold_name(fold: NestedFold) -> str:
    return f"outer-{fold.outer_fold}-inner-{fold.inner_fold}"


def export(inputs: Inputs, output: Path) -> dict[str, Any]:
    """Write the label-free request file and the identities scoring must reproduce."""
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    requests = {}
    folds = []
    for fold, split in zip(inputs.folds, inputs.splits, strict=True):
        sink, log, result = export_requests(
            split, inputs.view.features, inputs.config.chronos, inputs.evaluation
        )
        requests.update(sink)
        folds.append(
            {
                "fold": _fold_name(fold),
                "split_sha256": document_sha256(split),
                "validation_participants": len(split.validation_subjects),
                "distinct_requests": len(sink),
                "adapter_counts": dict(sorted(log.counts.items())),
                "harness_counts": {
                    k: result.counts[k]
                    for k in (
                        "planned_origins",
                        "predicted_origins",
                        "expected_points",
                        "insufficient_history_points",
                    )
                },
            }
        )
    manifest = {
        "format": "chronos-pmdata-export-1",
        **_git(),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "dataset_snapshot": inputs.protocol.expected_snapshot.model_dump(),
        "protocol_sha256": document_sha256(inputs.protocol),
        "config_sha256": document_sha256(inputs.config),
        "nested_plan_sha256": document_sha256(inputs.plan),
        "outer_test_sealed": True,
        "labels_passed_to_harness": False,
        "feature_counts": inputs.view.counts,
        "folds": folds,
        "requests": len(requests),
        "requests_sha256": write_requests(output / "requests.jsonl", requests),
    }
    _write_private(output / "export.json", manifest)
    return manifest


@dataclass
class Cost:
    """CPU cost of one model's fit and predictions, from the scoring pass (time) and a
    separate traced pass (memory), so tracing overhead never inflates the timings."""

    fit_seconds: list[float] = field(default_factory=list)
    predict_seconds: list[float] = field(default_factory=list)
    fit_peak_bytes: int = 0
    predict_peak_bytes: int = 0


def _measured[T](call: Callable[[], T], trace: bool) -> tuple[T, float, int]:
    base = 0
    if trace:
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
    started = perf_counter()
    value = call()
    elapsed = perf_counter() - started
    peak = tracemalloc.get_traced_memory()[1] - base if trace else 0
    return value, elapsed, peak


def instrumented(factory: PredictorFactory, cost: Cost, *, trace: bool) -> PredictorFactory:
    def fit(training: TrainingPrefix):
        predictor, elapsed, peak = _measured(lambda: factory(training), trace)
        if trace:
            cost.fit_peak_bytes = max(cost.fit_peak_bytes, peak)
        else:
            cost.fit_seconds.append(elapsed)

        def predict(request: ForecastInput):
            output, elapsed, peak = _measured(lambda: predictor(request), trace)
            if trace:
                cost.predict_peak_bytes = max(cost.predict_peak_bytes, peak)
            else:
                cost.predict_seconds.append(elapsed)
            return output

        return predict

    return fit


def baseline_factory(
    protocol: PMDataProtocol, model_config: BaselineConfig | TreeConfig, fitted: list
) -> PredictorFactory:
    """The protocol runner's comparator factory (pmdata_run.run), unchanged."""

    def factory(training: TrainingPrefix):
        if len({r.subject_id for r in training.observations}) < protocol.folds.min_train_subjects:
            raise ValueError("insufficient causally available training participants")
        model: ForecastArtifact = (
            fit_tree(training, model_config)
            if isinstance(model_config, TreeConfig)
            else fit_baseline(training, model_config)
        )
        fitted.append(model)
        return model.predict

    return factory


def _estimates(report: MetricReport) -> dict[str, Any]:
    return {
        name: asdict(value) if value is not None else None
        for name in (
            "mae",
            "rmse",
            "median_pinball_loss",
            "interval_coverage",
            "mean_interval_width",
        )
        if (value := getattr(report, name)) is not None
    }


def _boot(values: Sequence[float], config: EvaluationConfig, seed: int) -> Estimate | None:
    return bootstrap_participant_mean(
        values, samples=config.bootstrap_samples, confidence=config.confidence, seed=seed
    )


def _distribution(values: Sequence[float]) -> dict[str, Any] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "participants": len(ordered),
        "candidate_better": sum(v < 0 for v in ordered),
        "candidate_worse": sum(v > 0 for v in ordered),
        "min": ordered[0],
        "median": median(ordered),
        "max": ordered[-1],
    }


def _seconds(values: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"calls": 0}
    return {
        "calls": len(ordered),
        "total": sum(ordered),
        "p50": ordered[len(ordered) // 2],
        "p95": ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))],
        "max": ordered[-1],
    }


def score(inputs: Inputs, export_dir: Path, gx10_dir: Path, output: Path) -> dict[str, Any]:
    """Pair Chronos with each comparator per inner fold, then pool the disjoint folds."""
    protocol, config = inputs.protocol, inputs.config
    pin = config.chronos.model
    exported = json.loads((export_dir / "export.json").read_text())
    for key, value in (
        ("protocol_sha256", document_sha256(protocol)),
        ("config_sha256", document_sha256(config)),
        ("nested_plan_sha256", document_sha256(inputs.plan)),
    ):
        if exported[key] != value:
            raise ValueError(f"export was made with a different {key}")
    if [f["split_sha256"] for f in exported["folds"]] != [
        document_sha256(s) for s in inputs.splits
    ]:
        raise ValueError("export was made against different split manifests")
    forecasts = load_forecasts(export_dir / "requests.jsonl", gx10_dir)
    evidence = forecasts.evidence
    if (
        evidence["model"]["model_id"] != pin.model_id
        or evidence["model"]["revision"] != pin.revision
        or evidence["weights_sha256"] != pin.weights_sha256
    ):
        raise ValueError("GX10 run used a different checkpoint than the pinned one")
    git = _git()
    environment = hashlib.sha256((REPO / "uv.lock").read_bytes()).hexdigest()
    now = datetime.now(UTC)
    seed = protocol.folds.seed
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    _write_private(output / "inference.json", evidence)

    comparators = [*protocol.baselines, protocol.tree]
    reports: dict[str, list[MetricReport]] = defaultdict(list)
    differences: dict[str, list] = defaultdict(list)
    quantiles: dict[str, list[SubjectQuantiles]] = defaultdict(list)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    costs: dict[str, Cost] = defaultdict(Cost)
    adapter = Counter()
    folds = []
    for fold, split in zip(inputs.folds, inputs.splits, strict=True):
        fold_root = output / _fold_name(fold)
        fold_root.mkdir(mode=0o700)
        candidate_hashes = set()
        fold_summary: dict[str, Any] = {
            "fold": _fold_name(fold),
            "split_sha256": document_sha256(split),
            "comparisons": {},
        }
        for model_config in comparators:
            fitted: list[ForecastArtifact] = []
            probe: list[ForecastArtifact] = []
            log = AdapterLog()
            cost_key = "tree" if isinstance(model_config, TreeConfig) else model_config.method
            result: ComparisonResult = compare_forecasts(
                split,
                inputs.view.features,
                inputs.labels,
                instrumented(
                    baseline_factory(protocol, model_config, fitted), costs[cost_key], trace=False
                ),
                replay_factory(config.chronos, forecasts.quantiles, forecasts.levels, log),
                baseline_config=protocol.evaluation,
                candidate_config=inputs.evaluation,
            )
            model_id = fitted[0].model_id
            # Memory is traced in a separate pass so tracing overhead stays out of timings.
            tracemalloc.start()
            try:
                evaluate_forecast(
                    split,
                    inputs.view.features,
                    inputs.labels,
                    instrumented(
                        baseline_factory(protocol, model_config, probe),
                        costs[cost_key],
                        trace=True,
                    ),
                    protocol.evaluation,
                )
            finally:
                tracemalloc.stop()
            quantile = paired_quantile_report(
                result, inputs.labels, log, forecasts.levels, protocol.evaluation, seed
            )
            candidate_hashes.add(document_sha256(result.candidate))
            runs = [
                RunManifest(
                    schema_version="0.1",
                    run_id=f"outer{fold.outer_fold}-inner{fold.inner_fold}-{model_id}",
                    created_at_utc=now,
                    **git,
                    config_sha256=document_sha256(protocol.evaluation),
                    dataset_snapshot=protocol.expected_snapshot,
                    split_manifest_sha256=document_sha256(split),
                    task="physiology_forecast",
                    feature_order=list(FEATURES)
                    if isinstance(model_config, TreeConfig)
                    else [protocol.evaluation.metric],
                    model=ModelRef(
                        model_id=model_id,
                        checkpoint_source=None,
                        checkpoint_revision=None,
                        license=None,
                    ),
                    environment_sha256=environment,
                    seed=seed,
                    artifact=None,
                    metrics_paths=["evaluation.json"],
                ),
                RunManifest(
                    schema_version="0.1",
                    run_id=f"outer{fold.outer_fold}-inner{fold.inner_fold}-{CHRONOS_MODEL_ID}",
                    created_at_utc=now,
                    **git,
                    config_sha256=document_sha256(inputs.evaluation),
                    dataset_snapshot=protocol.expected_snapshot,
                    split_manifest_sha256=document_sha256(split),
                    task="physiology_forecast",
                    feature_order=[protocol.evaluation.metric],
                    model=ModelRef(
                        model_id=CHRONOS_MODEL_ID,
                        checkpoint_source=pin.model_id,
                        checkpoint_revision=pin.revision,
                        license=pin.license,
                    ),
                    environment_sha256=pin.runtime_lock_sha256,
                    seed=seed,
                    artifact=None,
                    metrics_paths=["evaluation.json"],
                ),
            ]
            packet = write_comparison_packet(
                fold_root / f"vs-{model_id}", split, runs[0], runs[1], result
            )
            _write_private(fold_root / f"quantiles-vs-{model_id}.json", quantile)
            reports[model_id].append(result.baseline.metrics)
            if model_config is comparators[0]:
                reports[CHRONOS_MODEL_ID].append(result.candidate.metrics)
                counts[CHRONOS_MODEL_ID].update(result.candidate.counts)
                adapter.update(log.counts)
            counts[model_id].update(result.baseline.counts)
            counts[f"paired-vs-{model_id}"].update(result.summary.counts)
            differences[model_id].extend(result.summary.difference.subjects)
            quantiles[model_id].extend(quantile.subjects)
            fold_summary["comparisons"][model_id] = {
                "baseline_evaluation_sha256": document_sha256(result.baseline),
                "candidate_evaluation_sha256": document_sha256(result.candidate),
                "packet_comparison_sha256": packet["comparison.json"],
                "paired_counts": result.summary.counts,
                "difference": {
                    name: asdict(value) if value is not None else None
                    for name in ("mae", "rmse", "median_pinball_loss")
                    if (value := getattr(result.summary.difference, name)) is not None
                },
            }
        if len(candidate_hashes) != 1:
            raise RuntimeError("Chronos replay was not identical across comparisons")
        folds.append(fold_summary)

    pooled_models = {
        name: _estimates(combine_metric_reports(rows, seed=seed))
        for name, rows in sorted(reports.items())
    }
    paired = {}
    for model_id, rows in sorted(differences.items()):
        pooled_quantiles: QuantileReport = summarize_quantiles(
            quantiles[model_id], protocol.evaluation, seed
        )
        paired[model_id] = {
            "definition": "Chronos minus comparator; pooled disjoint inner validation folds; "
            "bootstrap over participants",
            "counts": dict(sorted(counts[f"paired-vs-{model_id}"].items())),
            "mae": asdict(e)
            if (e := _boot([d.mae for d in rows], protocol.evaluation, seed))
            else None,
            "rmse": asdict(e)
            if (e := _boot([d.rmse for d in rows], protocol.evaluation, seed))
            else None,
            "mae_by_participant": _distribution([d.mae for d in rows]),
            "decile_quantile_loss": {
                "definition": pooled_quantiles.definition,
                "paired_points": pooled_quantiles.paired_points,
                "participants": pooled_quantiles.participants,
                "comparator": asdict(pooled_quantiles.baseline)
                if pooled_quantiles.baseline
                else None,
                "chronos": asdict(pooled_quantiles.candidate)
                if pooled_quantiles.candidate
                else None,
                "difference": asdict(pooled_quantiles.difference)
                if pooled_quantiles.difference
                else None,
            },
        }
    calibration = summarize_quantiles(
        quantiles[next(iter(sorted(quantiles)))], protocol.evaluation, seed
    ).calibration
    summary: dict[str, Any] = {
        "data_mode": "real",
        **git,
        "environment_sha256": environment,
        "python": platform.python_version(),
        "dataset_snapshot": protocol.expected_snapshot.model_dump(),
        "protocol_sha256": document_sha256(protocol),
        "config_sha256": document_sha256(config),
        "nested_plan_sha256": document_sha256(inputs.plan),
        "active_outer_fold": protocol.active_outer_fold,
        "outer_test_sealed": True,
        "outer_test_participants": len(inputs.folds[0].test_subjects),
        "validation_participants": len({s for f in inputs.folds for s in f.validation_subjects}),
        "inner_folds": len(inputs.folds),
        "feature_counts": inputs.view.counts,
        "requests": exported["requests"],
        "requests_sha256": exported["requests_sha256"],
        "predictions_sha256": evidence["predictions_sha256"],
        "model": {
            **pin.model_dump(),
            "quantile_levels": list(forecasts.levels),
            "interval": [config.chronos.interval_lower, config.chronos.interval_upper],
            "context_hours": config.chronos.context_hours,
            "covariates": config.chronos.covariates,
            "pretrained_cohort_overlap": config.pretrained_cohort_overlap,
        },
        "adapter_counts": dict(sorted(adapter.items())),
        "crossed_quantile_steps_raw": evidence["crossed_quantile_steps"],
        "models": {
            name: {"metrics": metrics, "counts": dict(sorted(counts[name].items()))}
            for name, metrics in pooled_models.items()
        },
        "paired_vs_comparators": paired,
        "chronos_calibration": {
            name: asdict(value) if value is not None else None
            for name, value in calibration.items()
        },
        "cost": {
            "chronos_gx10": {
                **evidence["timing"],
                **evidence["memory"],
                "gpu": evidence["environment"]["gpu"],
            },
            "comparators_cpu": {
                name: {
                    "fit_seconds": _seconds(cost.fit_seconds),
                    "predict_seconds_per_origin": _seconds(cost.predict_seconds),
                    "fit_peak_traced_bytes": cost.fit_peak_bytes,
                    "predict_peak_traced_bytes": cost.predict_peak_bytes,
                }
                for name, cost in sorted(costs.items())
            },
            "cpu": platform.platform(),
            "note": "Comparators run on the Mac CPU, Chronos on the GX10 GPU: hardware "
            "differs. Traced bytes are Python/NumPy allocations during fit or one call.",
        },
        "folds": folds,
    }
    _write_private(output / "aggregate-summary.json", summary)
    _write_private(
        output / "sha256.json",
        {
            str(p.relative_to(output)): file_sha256(p)
            for p in sorted(output.rglob("*"))
            if p.is_file()
        },
    )
    return summary


def zero_shot_receipt(
    inputs: Inputs,
    export_dir: Path,
    gx10_dir: Path,
    output: Path,
    *,
    fold_index: int,
    expected_evaluation_sha256: str,
) -> dict[str, Any]:
    """A served zero-shot artifact bound to a re-scored #10 packet with an identical result.

    The fold's Chronos evaluation is rebuilt from the saved GX10 forecasts and must hash
    to the value #10 recorded, so the packet the artifact names is that evaluation.
    """
    from hachi.evaluation import evaluate_forecast, write_packet

    from .artifacts import ChronosArtifact, artifact_id_for, load_artifact, save_artifact

    protocol, config = inputs.protocol, inputs.config
    forecasts = load_forecasts(export_dir / "requests.jsonl", gx10_dir)
    pin = config.chronos.model
    if forecasts.evidence["weights_sha256"] != pin.weights_sha256:
        raise ValueError("GX10 run used a different checkpoint than the pinned one")
    artifact = ChronosArtifact(
        model_id=CHRONOS_MODEL_ID,
        chronos=config.chronos,
        protocol_sha256=document_sha256(protocol),
        harness_lookback_hours=protocol.lookback_hours,
    )
    artifact_id = artifact_id_for(artifact)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    reference = save_artifact(output / "model", artifact, artifact_id=artifact_id)
    reloaded = load_artifact(output / "model", reference)
    if reloaded != artifact:
        raise RuntimeError("reloaded artifact differs from the saved one")
    split = inputs.splits[fold_index]
    result = evaluate_forecast(
        split,
        inputs.view.features,
        inputs.labels,
        replay_factory(reloaded.chronos, forecasts.quantiles, forecasts.levels, AdapterLog()),
        inputs.evaluation,
    )
    if document_sha256(result) != expected_evaluation_sha256:
        raise ValueError("re-scored evaluation differs from the recorded #10 evaluation")
    fold = inputs.folds[fold_index]
    run = RunManifest(
        schema_version="0.1",
        run_id=f"outer{fold.outer_fold}-inner{fold.inner_fold}-{CHRONOS_MODEL_ID}",
        created_at_utc=datetime.now(UTC),
        **_git(),
        config_sha256=document_sha256(inputs.evaluation),
        dataset_snapshot=protocol.expected_snapshot,
        split_manifest_sha256=document_sha256(split),
        task="physiology_forecast",
        feature_order=[protocol.evaluation.metric],
        model=ModelRef(
            model_id=CHRONOS_MODEL_ID,
            checkpoint_source=pin.model_id,
            checkpoint_revision=pin.revision,
            license=pin.license,
        ),
        environment_sha256=pin.runtime_lock_sha256,
        seed=protocol.folds.seed,
        artifact=reference,
        metrics_paths=["evaluation.json"],
    )
    hashes = write_packet(output / "packet", split, run, result)
    receipt = {
        "artifact": reference.model_dump(),
        "pin": f"{reference.artifact_id}@{reference.artifact_sha256}",
        "fold": _fold_name(fold),
        "evaluation_sha256": document_sha256(result),
        "matches_recorded_10_evaluation": True,
        "packet_sha256": hashes,
        "model_files": sorted(p.name for p in (output / "model").iterdir()),
        "weights_sha256": reloaded.weights_sha256,
        "runtime_lock_sha256": pin.runtime_lock_sha256,
        "config_sha256": document_sha256(config),
    }
    _write_private(output / "receipt.json", receipt)
    return receipt
