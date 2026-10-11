"""#12 scoring: every candidate on identical origins, meta learners, ensembles, selection.

All model predictions come from `evaluate_forecast` over the inner validation and
amendment-1 meta manifests. Meta tables (inside each inner fold's training
participants) alone fit stacking weights and point-model residual intervals. Every
final candidate is then replayed through the harness, paired with the incumbent by
`compare_forecasts`, and judged by the predeclared selection rule.
"""

import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Any

from hachi.evaluation import (
    EvaluationConfig,
    EvaluationResult,
    compare_forecasts,
    evaluate_forecast,
)
from hachi.evaluation.metrics import Estimate, bootstrap_participant_mean, combine_metric_reports
from hachi.evaluation.serialization import document_bytes, document_sha256

from ..chronos.adapter import AdapterLog, replay_factory
from ..chronos.evaluation import Forecasts, load_forecasts
from ..chronos.inference import EMBEDDING_FORMAT, REQUEST_FORMAT, file_sha256
from ..chronos.pmdata import baseline_factory
from ..ensemble import stacking
from ..ensemble.selection import Challenge, SelectionLog, select
from .pmdata import VARIANTS, Inputs, manifest_key
from .ridge import ridge_factory

COMPARATORS = (
    "train-population-mean-v1",
    "hourly-last-valid-v1",
    "utc-seasonal-naive-v1",
    "causal-hourly-tree-v1",
)
RIDGES = {
    "handcrafted-ridge-personal": "handcrafted-personal",
    "handcrafted-ridge-population": "handcrafted-population",
    "chronos-2-embedding-ridge": "embedding",
}
FINETUNED = "chronos-2-finetuned"
ENSEMBLES = ("ensemble-equal-weight", "ensemble-stacked")


def load_embeddings(requests_path: Path, run_dir: Path) -> tuple[dict, str]:
    evidence = json.loads((run_dir / "inference.json").read_text())
    if evidence.get("format") != EMBEDDING_FORMAT or evidence.get("request_format") != (
        REQUEST_FORMAT
    ):
        raise ValueError("unrecognized embedding run format")
    if evidence["requests_sha256"] != file_sha256(requests_path):
        raise ValueError("GX10 embeddings answered a different request file")
    digest = file_sha256(run_dir / "embeddings.jsonl")
    if evidence["embeddings_sha256"] != digest:
        raise ValueError("embeddings file does not match its recorded checksum")
    with requests_path.open() as stream:
        wanted = {json.loads(line)["request_id"] for line in stream}
    found = {}
    with (run_dir / "embeddings.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            found[row["request_id"]] = (row["embedding"], row["loc"], row["scale"])
    if found.keys() != wanted:
        raise ValueError("embeddings do not cover exactly the exported requests")
    return found, digest


def _deciles(log: AdapterLog, levels: Sequence[float]) -> dict:
    index = [min(range(len(levels)), key=lambda i: abs(levels[i] - q)) for q in stacking.DECILES]
    return {key: [[row[i] for i in index] for row in rows] for key, rows in log.quantiles.items()}


@dataclass
class Candidate:
    """One model's harness results: per inner fold (main) and per meta manifest (meta)."""

    name: str
    family: str  # comparator | ridge | chronos | finetuned | ensemble
    main: dict[int, EvaluationResult] = field(default_factory=dict)
    main_table: dict[int, stacking.Table] = field(default_factory=dict)
    meta_table: dict[int, stacking.Table] = field(default_factory=dict)
    final: dict[int, stacking.Table] = field(default_factory=dict)
    official: dict[int, EvaluationResult] = field(default_factory=dict)
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def gpu(self) -> bool:
        return self.family in {"chronos", "finetuned"} or self.name == "chronos-2-embedding-ridge"


@dataclass
class Scoring:
    inputs: Inputs
    forecasts: Forecasts
    embeddings: Mapping
    embeddings_sha256: str
    candidates: dict[str, Candidate] = field(default_factory=dict)
    finetune: dict[str, Any] = field(default_factory=dict)

    @property
    def truth(self) -> dict:
        return stacking.labels(self.inputs.labels, self.inputs.evaluation)

    def config(self, name: str) -> EvaluationConfig:
        family = self.candidates[name].family
        cpu = family in {"comparator", "ridge"} and name != "chronos-2-embedding-ridge"
        # External (#11) heads sit on pretrained encoders: overlap is unknown as for Chronos.
        return self.inputs.evaluation if cpu else self.inputs.chronos_evaluation


def _factory(scoring: Scoring, name: str, log: AdapterLog | None):
    inputs = scoring.inputs
    protocol = inputs.experiment.protocol
    if name in COMPARATORS:
        methods = dict(
            zip(
                COMPARATORS,
                ("train_population_mean", "last_valid", "seasonal_naive", "tree"),
                strict=True,
            )
        )
        configs = {c.method: c for c in protocol.baselines} | {"tree": protocol.tree}
        return baseline_factory(protocol, configs[methods[name]], [])
    if name in RIDGES:
        return ridge_factory(
            inputs.experiment.ridge(RIDGES[name]), scoring.embeddings, scoring.embeddings_sha256
        )
    if name in VARIANTS:
        assert log is not None
        return replay_factory(
            inputs.experiment.chronos.chronos,
            scoring.forecasts.quantiles,
            scoring.forecasts.levels,
            log,
            inputs.builder(name),
        )
    raise KeyError(name)


def run_models(scoring: Scoring) -> None:
    """Base models on every main and meta manifest, tables kept per inner fold."""
    inputs = scoring.inputs
    names = [*COMPARATORS, *RIDGES, *VARIANTS]
    for name in names:
        family = "comparator" if name in COMPARATORS else "ridge" if name in RIDGES else "chronos"
        candidate = scoring.candidates.setdefault(name, Candidate(name, family))
        for role, fold, manifest in inputs.manifests():
            log = AdapterLog() if family == "chronos" else None
            result = evaluate_forecast(
                manifest,
                inputs.view.features,
                inputs.labels,
                _factory(scoring, name, log),
                scoring.config(name),
            )
            deciles = _deciles(log, scoring.forecasts.levels) if log is not None else None
            table = stacking.table(result, deciles)
            if role == "main":
                candidate.main[fold] = result
                candidate.main_table[fold] = table
                if log is not None:
                    candidate.notes.setdefault("adapter_counts", {})[fold] = dict(log.counts)
            else:
                merged = candidate.meta_table.setdefault(fold, {})
                if set(merged) & set(table):
                    raise ValueError("meta manifests of one inner fold must not overlap")
                merged.update(table)


def add_finetuned(
    scoring: Scoring, runs: Mapping[str, Mapping[int, tuple[Forecasts, dict]]]
) -> None:
    """Fine-tuned forecasts per learning rate and fold; the rate is chosen on validation MAE."""
    inputs = scoring.inputs
    by_rate: dict[str, dict[int, tuple[EvaluationResult, stacking.Table, dict]]] = {}
    for rate, folds in runs.items():
        for fold, (forecasts, receipt) in folds.items():
            hours = receipt["hyperparameters"]["context_length"]
            variant = next(v for v, (h, c) in VARIANTS.items() if h == hours and not c)
            log = AdapterLog()
            result = evaluate_forecast(
                inputs.splits[fold],
                inputs.view.features,
                inputs.labels,
                replay_factory(
                    inputs.experiment.chronos.chronos,
                    forecasts.quantiles,
                    forecasts.levels,
                    log,
                    inputs.builder(variant),
                ),
                inputs.chronos_evaluation,
            )
            table = stacking.table(result, _deciles(log, forecasts.levels))
            by_rate.setdefault(rate, {})[fold] = (result, table, receipt)
    pooled = {
        rate: combine_metric_reports(
            [r.metrics for r, _, _ in folds.values()], seed=inputs.experiment.protocol.folds.seed
        ).mae
        for rate, folds in by_rate.items()
    }
    chosen = min(pooled, key=lambda r: pooled[r].value if pooled[r] else float("inf"))
    candidate = Candidate(FINETUNED, "finetuned")
    for fold, (result, table, receipt) in by_rate[chosen].items():
        candidate.main[fold] = result
        candidate.main_table[fold] = table
        candidate.notes.setdefault("receipts", {})[fold] = receipt
    candidate.notes["learning_rate_selection"] = {
        "rule": "lowest pooled inner-validation MAE (predeclared)",
        "pooled_mae": {r: (asdict(e) if e else None) for r, e in pooled.items()},
        "chosen": chosen,
    }
    scoring.candidates[FINETUNED] = candidate


def calibrate_and_combine(scoring: Scoring) -> dict[str, Any]:
    """Residual intervals from meta tables; stacked and equal-weight ensembles."""
    inputs = scoring.inputs
    adaptation = inputs.experiment.adaptation
    metric = inputs.evaluation.metric
    truth = scoring.truth
    rule = inputs.experiment.rule
    support: dict[str, Any] = {}
    for candidate in scoring.candidates.values():
        if candidate.family in {"comparator", "ridge"}:
            for fold, table in candidate.main_table.items():
                offsets = stacking.residual_offsets(
                    candidate.meta_table[fold], truth, rule.interval_lower, rule.interval_upper
                )
                candidate.final[fold] = stacking.with_interval(table, offsets, metric)
                candidate.notes.setdefault("residual_offsets", {})[fold] = offsets
        elif candidate.family in {"chronos", "finetuned"}:
            candidate.final = dict(candidate.main_table)
    members = adaptation["ensembles"]["members"]
    equal = Candidate("ensemble-equal-weight", "ensemble")
    stacked = Candidate("ensemble-stacked", "ensemble")
    for fold in range(len(inputs.splits)):
        keys = stacking.keys_of(scoring.candidates[COMPARATORS[0]].main[fold])
        meta = {m: scoring.candidates[m].meta_table[fold] for m in members}
        weights = stacking.fit_stack(meta, truth, members)
        main = {m: scoring.candidates[m].main_table[fold] for m in members}
        stacked.final[fold] = stacking.combine(main, keys, weights, metric)
        equal.final[fold] = stacking.combine(main, keys, None, metric)
        meta_keys = set().union(*(set(t) for t in meta.values()))
        support[f"inner-{fold}"] = {
            "meta_points": len(meta_keys),
            "meta_labelled": sum((k[0], k[2]) in truth for k in meta_keys),
            "complete_labelled_fit_points": weights.fitted_points,
            "member_meta_abstentions": {
                m: sum(1 for k in meta_keys if t.get(k) is None) for m, t in meta.items()
            },
            "weights": {
                str(q): dict(zip(weights.members, w, strict=True))
                for q, w in weights.weights.items()
            },
        }
    scoring.candidates[equal.name] = equal
    scoring.candidates[stacked.name] = stacked
    return support


def run_official(scoring: Scoring) -> None:
    """Replay every final table through the harness: identical origins for all."""
    inputs = scoring.inputs
    for candidate in scoring.candidates.values():
        for fold, split in enumerate(inputs.splits):
            candidate.official[fold] = evaluate_forecast(
                split,
                inputs.view.features,
                inputs.labels,
                stacking.replay_factory(candidate.final[fold], candidate.name),
                scoring.config(candidate.name),
            )
    for fold in range(len(inputs.splits)):
        plans = {document_sha256(c.official[fold].plan) for c in scoring.candidates.values()}
        if len(plans) != 1:
            raise RuntimeError("candidates were not scored on identical origin plans")


def _boot(values: Sequence[float], scoring: Scoring) -> Estimate | None:
    config = scoring.inputs.evaluation
    return bootstrap_participant_mean(
        values,
        samples=config.bootstrap_samples,
        confidence=config.confidence,
        seed=scoring.inputs.experiment.protocol.folds.seed,
    )


def abstention_share(candidate: Candidate) -> float:
    abstained = sum(r.counts["abstained_points"] for r in candidate.official.values())
    scored = sum(r.counts["scored_points"] for r in candidate.official.values())
    return abstained / (abstained + scored) if abstained + scored else 1.0


def coverage(candidate: Candidate, seed: int) -> Estimate | None:
    return combine_metric_reports(
        [r.metrics for r in candidate.official.values()], seed=seed
    ).interval_coverage


def challenge(
    scoring: Scoring, name: str, incumbent: str, costs: Mapping[str, Mapping[str, Any]]
) -> tuple[Challenge, list]:
    inputs = scoring.inputs
    cand, inc = scoring.candidates[name], scoring.candidates[incumbent]
    truth = scoring.truth
    differences, results = [], []
    losses: dict[str, list[tuple[float, float]]] = defaultdict(list)
    paired = 0
    for fold, split in enumerate(inputs.splits):
        result = compare_forecasts(
            split,
            inputs.view.features,
            inputs.labels,
            stacking.replay_factory(inc.final[fold], inc.name),
            stacking.replay_factory(cand.final[fold], cand.name),
            baseline_config=scoring.config(incumbent),
            candidate_config=scoring.config(name),
        )
        results.append(result)
        differences.extend(result.summary.difference.subjects)
        paired += result.summary.counts["paired_points"]
        for key, point in cand.final[fold].items():
            other = inc.final[fold].get(key)
            label = truth.get((key[0], key[2]))
            if point is None or other is None or label is None:
                continue
            losses[key[0]].append(
                (stacking.mean_pinball(other, label), stacking.mean_pinball(point, label))
            )
    decile = [fmean(c for _, c in rows) - fmean(b for b, _ in rows) for rows in losses.values()]
    evidence = Challenge(
        candidate=name,
        incumbent=incumbent,
        paired_points=paired,
        paired_mae=_boot([d.mae for d in differences], scoring),
        paired_decile_loss=_boot(decile, scoring),
        coverage=coverage(cand, inputs.experiment.protocol.folds.seed),
        abstention_share=abstention_share(cand),
        incumbent_abstention_share=abstention_share(inc),
        latency_p95_seconds=costs.get(name, {}).get("latency_p95_seconds"),
        peak_memory_bytes=costs.get(name, {}).get("peak_memory_bytes"),
    )
    return evidence, results


def run_selection(
    scoring: Scoring, costs: Mapping[str, Mapping[str, Any]]
) -> tuple[SelectionLog, dict[tuple[str, str], list]]:
    rule = scoring.inputs.experiment.rule
    packets: dict[tuple[str, str], list] = {}

    def judge(name: str, incumbent: str) -> Challenge:
        evidence, results = challenge(scoring, name, incumbent, costs)
        packets[(incumbent, name)] = results
        return evidence

    available = [n for n, c in scoring.candidates.items() if c.family != "external"]
    log = select(rule, document_sha256(rule), available, judge)
    return log, packets


ABLATIONS = (
    ("channel: past steps", "chronos-2-zero-shot", "chronos-2-zero-shot-steps"),
    ("context: 168 h", "chronos-2-zero-shot", "chronos-2-zero-shot-ctx168"),
    ("context: 720 h", "chronos-2-zero-shot", "chronos-2-zero-shot-ctx720"),
    (
        "representation: Chronos embedding vs handcrafted",
        "handcrafted-ridge-personal",
        "chronos-2-embedding-ridge",
    ),
    (
        "personalization: personal history vs population only",
        "handcrafted-ridge-population",
        "handcrafted-ridge-personal",
    ),
    ("adaptation: fine-tuned vs zero-shot (same context)", "chronos-2-zero-shot", FINETUNED),
    ("combination: stacked vs equal weight", "ensemble-equal-weight", "ensemble-stacked"),
    ("combination: stacked vs Chronos-2 zero-shot", "chronos-2-zero-shot", "ensemble-stacked"),
)


def measure_cpu(
    name: str, snapshot: Path, export_dir: Path, embed_dir: Path | None
) -> dict[str, Any]:
    """Fit and predict one inner fold in a fresh process: wall latency and actual peak RSS."""
    import platform
    import resource
    from time import perf_counter

    from hachi.evaluation.pmdata_run import fold_split, load_inputs

    from .pmdata import load_experiment

    experiment = load_experiment()
    protocol = experiment.protocol
    plan, view, labels = load_inputs(snapshot, protocol)
    fold = next(f for f in plan.folds if f.outer_fold == protocol.active_outer_fold)
    embeddings, digest = (
        load_embeddings(export_dir / "embed-requests.jsonl", embed_dir)
        if name == "chronos-2-embedding-ridge" and embed_dir is not None
        else ({}, None)
    )
    if name in COMPARATORS:
        methods = dict(
            zip(
                COMPARATORS,
                ("train_population_mean", "last_valid", "seasonal_naive", "tree"),
                strict=True,
            )
        )
        configs = {c.method: c for c in protocol.baselines} | {"tree": protocol.tree}
        factory = baseline_factory(protocol, configs[methods[name]], [])
    else:
        factory = ridge_factory(experiment.ridge(RIDGES[name]), embeddings, digest)
    fit_seconds: list[float] = []
    predict_seconds: list[float] = []

    def timed(training):
        started = perf_counter()
        predictor = factory(training)
        fit_seconds.append(perf_counter() - started)

        def predict(request):
            begun = perf_counter()
            output = predictor(request)
            predict_seconds.append(perf_counter() - begun)
            return output

        return predict

    evaluate_forecast(fold_split(protocol, fold), view.features, labels, timed, protocol.evaluation)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = rss if platform.system() == "Darwin" else rss * 1024
    ordered = sorted(predict_seconds)
    return {
        "where": f"{platform.system()} {platform.machine()} CPU, fresh process, inner fold 0",
        "fit_seconds": fit_seconds[0],
        "predict_calls": len(ordered),
        "latency_p50_seconds": ordered[len(ordered) // 2],
        "latency_p95_seconds": ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))],
        "peak_rss_bytes": rss_bytes,
        "peak_memory_bytes": rss_bytes,
        "note": "process RSS includes loading the snapshot features this model serves from",
    }


def gpu_costs(zeroshot_dir: Path, embed_dir: Path) -> dict[str, dict[str, Any]]:
    zeroshot = json.loads((zeroshot_dir / "inference.json").read_text())
    embed = json.loads((embed_dir / "inference.json").read_text())
    z_memory = max(
        zeroshot["memory"]["peak_process_rss_kib"] * 1024,
        zeroshot["memory"]["peak_cuda_allocated_bytes_batched"],
    )
    chronos = {
        "where": f"GX10 {zeroshot['environment']['gpu']}, gpu-run",
        "latency_p95_seconds": zeroshot["timing"]["single_request_seconds_p95"],
        "latency_p50_seconds": zeroshot["timing"]["single_request_seconds_p50"],
        "peak_rss_bytes": zeroshot["memory"]["peak_process_rss_kib"] * 1024,
        "peak_cuda_allocated_bytes": zeroshot["memory"]["peak_cuda_allocated_bytes_batched"],
        "peak_memory_bytes": z_memory,
        "note": "single-request latency sampled over the first 32 requests across variants",
    }
    costs = {variant: dict(chronos) for variant in VARIANTS}
    costs["embedding"] = {
        "latency_p95_seconds": embed["timing"]["single_request_seconds_p95"],
        "peak_rss_bytes": embed["memory"]["peak_process_rss_kib"] * 1024,
        "peak_cuda_allocated_bytes": embed["memory"]["peak_cuda_allocated_bytes"],
        "peak_memory_bytes": max(
            embed["memory"]["peak_process_rss_kib"] * 1024,
            embed["memory"]["peak_cuda_allocated_bytes"],
        ),
    }
    return costs


def finetune_cost(receipt: Mapping[str, Any]) -> dict[str, Any]:
    memory = receipt["memory"]
    return {
        "where": "GX10 gpu-run, fine-tuned checkpoint",
        "latency_p95_seconds": receipt["timing"].get("single_request_seconds_p95"),
        "latency_p50_seconds": receipt["timing"].get("single_request_seconds_p50"),
        "peak_rss_bytes": memory["peak_process_rss_kib"] * 1024,
        "peak_cuda_allocated_bytes": memory["peak_cuda_allocated_bytes_inference"],
        "peak_memory_bytes": max(
            memory["peak_process_rss_kib"] * 1024, memory["peak_cuda_allocated_bytes_inference"]
        ),
        "training": {
            "fit_seconds": receipt["timing"]["fit_seconds"],
            "peak_cuda_allocated_bytes": memory["peak_cuda_allocated_bytes_training"],
        },
    }


def ensemble_cost(members: Sequence[str], costs: Mapping[str, Mapping[str, Any]]) -> dict:
    latency = [costs[m].get("latency_p95_seconds") for m in members]
    memory = [costs[m].get("peak_memory_bytes") for m in members]
    return {
        "where": "sum of member p95 latencies; largest member memory (amendment 1)",
        "latency_p95_seconds": sum(latency) if None not in latency else None,
        "peak_memory_bytes": max(memory) if None not in memory else None,
    }


def _estimate(value: Estimate | None) -> dict[str, Any] | None:
    return asdict(value) if value is not None else None


def _feature_order(scoring: Scoring, name: str) -> list[str]:
    from hachi.models.baselines.tree import FEATURES

    from .ridge import CALENDAR, HANDCRAFTED

    metric = scoring.inputs.evaluation.metric
    return {
        "causal-hourly-tree-v1": list(FEATURES),
        "handcrafted-ridge-personal": [*HANDCRAFTED, *CALENDAR],
        "handcrafted-ridge-population": list(CALENDAR),
        "chronos-2-embedding-ridge": ["chronos_2_embedding_mean_768", "loc", "scale", *CALENDAR],
        "chronos-2-zero-shot-steps": [metric, "steps"],
    }.get(name, [metric])


def _run_manifest(scoring: Scoring, name: str, fold: int, git: dict, environment: str):
    from datetime import UTC, datetime

    from hachi.contracts.manifests import ModelRef, RunManifest

    inputs = scoring.inputs
    pin = inputs.experiment.chronos.chronos.model
    candidate = scoring.candidates[name]
    pretrained = candidate.gpu or candidate.family == "ensemble"
    return RunManifest(
        schema_version="0.1",
        run_id=f"outer{inputs.folds[fold].outer_fold}-inner{fold}-{name}",
        created_at_utc=datetime.now(UTC),
        **git,
        config_sha256=document_sha256(scoring.config(name)),
        dataset_snapshot=inputs.experiment.protocol.expected_snapshot,
        split_manifest_sha256=document_sha256(inputs.splits[fold]),
        task="physiology_forecast",
        feature_order=_feature_order(scoring, name),
        model=ModelRef(
            model_id=name,
            checkpoint_source=pin.model_id if pretrained else None,
            checkpoint_revision=pin.revision if pretrained else None,
            license=pin.license if pretrained else None,
        ),
        environment_sha256=pin.runtime_lock_sha256 if candidate.gpu else environment,
        seed=inputs.experiment.protocol.folds.seed,
        artifact=None,
        metrics_paths=["evaluation.json"],
    )


def run_score(
    inputs: Inputs,
    *,
    snapshot: Path,
    export_dir: Path,
    zeroshot_dir: Path,
    embed_dir: Path,
    finetune_runs: Mapping[str, Mapping[int, Path]],
    output: Path,
    measure: Callable[[str, Path, Path, Path], dict[str, Any]] | None = None,
    external_11: Path | None = None,
) -> dict[str, Any]:
    import hashlib
    import subprocess
    import sys

    def in_fresh_process(name: str, snapshot: Path, export_dir: Path, embed_dir: Path) -> dict:
        measured = subprocess.run(
            [
                sys.executable,
                "-I",
                "-m",
                "hachi.models.training",
                "cost",
                "--candidate",
                name,
                "--snapshot",
                str(snapshot),
                "--export",
                str(export_dir),
                "--embed",
                str(embed_dir),
            ],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO,
        )
        return json.loads(measured.stdout)

    measure = measure or in_fresh_process

    from hachi.evaluation import write_comparison_packet, write_packet

    from .pmdata import REPO, _write_private, git_state

    exported = json.loads((export_dir / "export.json").read_text())
    experiment = inputs.experiment
    for key, value in (
        ("protocol_sha256", document_sha256(experiment.protocol)),
        ("selection_rule_sha256", document_sha256(experiment.rule)),
        ("context_policy_sha256", document_sha256(experiment.context_policy)),
        ("nested_plan_sha256", document_sha256(inputs.plan)),
    ):
        if exported[key] != value:
            raise ValueError(f"export was made with a different {key}")
    if exported["splits"] != {
        manifest_key(r, m): document_sha256(m) for r, _, m in inputs.manifests()
    }:
        raise ValueError("export was made against different main or meta manifests")
    forecasts = load_forecasts(export_dir / "forecast-requests.jsonl", zeroshot_dir)
    pin = experiment.chronos.chronos.model
    if forecasts.evidence["weights_sha256"] != pin.weights_sha256:
        raise ValueError("zero-shot run used a different checkpoint than the pinned one")
    embeddings, embed_sha = load_embeddings(export_dir / "embed-requests.jsonl", embed_dir)
    scoring = Scoring(inputs, forecasts, embeddings, embed_sha)
    run_models(scoring)
    costs: dict[str, dict[str, Any]] = gpu_costs(zeroshot_dir, embed_dir)
    if finetune_runs:
        loaded: dict[str, dict[int, tuple[Forecasts, dict]]] = {}
        for rate, folds in finetune_runs.items():
            for fold, run_dir in folds.items():
                receipt = json.loads((run_dir / "finetune.json").read_text())
                hours = receipt["hyperparameters"]["context_length"]
                entry = exported["finetune"][f"inner-{fold}"]
                if (
                    receipt["train_sha256"] != entry["train.jsonl"]
                    or receipt["holdout_sha256"] != entry["holdout.jsonl"]
                ):
                    raise ValueError("fine-tune run used different training or holdout series")
                if receipt["base_weights_sha256"] != pin.weights_sha256:
                    raise ValueError("fine-tune started from a different checkpoint")
                ft = load_forecasts(
                    export_dir / "finetune" / f"inner-{fold}" / f"requests-{hours}.jsonl", run_dir
                )
                if ft.evidence["weights_sha256"] != receipt["finetuned_weights_sha256"]:
                    raise ValueError("fine-tuned forecasts came from other weights")
                receipt["finetune_json_sha256"] = file_sha256(run_dir / "finetune.json")
                loaded.setdefault(rate, {})[fold] = (ft, receipt)
        add_finetuned(scoring, loaded)
        chosen = scoring.candidates[FINETUNED].notes["receipts"]
        costs[FINETUNED] = finetune_cost(chosen[0])
    support = calibrate_and_combine(scoring)
    external = add_external_11(scoring, external_11) if external_11 is not None else None
    run_official(scoring)
    # CPU costs in fresh processes, so each RSS is that model's own serving process.
    for name in (*COMPARATORS, *RIDGES):
        costs[name] = measure(name, snapshot, export_dir, embed_dir)
    embed_ridge = costs["chronos-2-embedding-ridge"]
    costs["chronos-2-embedding-ridge"] = {
        **embed_ridge,
        "where": "Chronos-2 embedding on the GX10, then the ridge head on CPU",
        "latency_p95_seconds": embed_ridge["latency_p95_seconds"]
        + costs["embedding"]["latency_p95_seconds"],
        "peak_memory_bytes": max(
            embed_ridge["peak_memory_bytes"], costs["embedding"]["peak_memory_bytes"]
        ),
    }
    members = experiment.adaptation["ensembles"]["members"]
    for name in ENSEMBLES:
        costs[name] = ensemble_cost(members, costs)

    log, chain = run_selection(scoring, costs)
    ablations = []
    best_context = None
    if FINETUNED in scoring.candidates:
        hours = scoring.candidates[FINETUNED].notes["receipts"][0]["hyperparameters"][
            "context_length"
        ]
        best_context = next(v for v, (h, c) in VARIANTS.items() if h == hours and not c)
    extra = (
        [
            (
                "representation: frozen WBM on #11's head",
                "issue11-ridge-handcrafted",
                "issue11-ridge-handcrafted-wbm",
            ),
            (
                "representation: frozen MOMENT on #11's head",
                "issue11-ridge-handcrafted",
                "issue11-ridge-handcrafted-moment",
            ),
            (
                "representation: #11 handcrafted ridge vs #12 handcrafted ridge",
                "handcrafted-ridge-personal",
                "issue11-ridge-handcrafted",
            ),
        ]
        if external is not None
        else []
    )
    for label, base, cand in [*ABLATIONS, *extra]:
        if cand == FINETUNED:
            if best_context is None:
                continue
            base = best_context
        evidence, _ = challenge(scoring, cand, base, costs)
        ablations.append({"ablation": label, "evidence": asdict(evidence)})

    git = git_state()
    environment = hashlib.sha256((REPO / "uv.lock").read_bytes()).hexdigest()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    packets = {}
    for name, candidate in scoring.candidates.items():
        for fold, result in candidate.official.items():
            run = _run_manifest(scoring, name, fold, git, environment)
            packets[f"{name}/inner-{fold}"] = write_packet(
                output / "candidates" / name / f"inner-{fold}", inputs.splits[fold], run, result
            )["evaluation.json"]
    links: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    for (incumbent, name), results in chain.items():
        for fold, result in enumerate(results):
            hashes = write_comparison_packet(
                output / "chain" / f"{incumbent}__vs__{name}" / f"inner-{fold}",
                inputs.splits[fold],
                _run_manifest(scoring, incumbent, fold, git, environment),
                _run_manifest(scoring, name, fold, git, environment).model_copy(
                    update={"run_id": f"outer0-inner{fold}-{name}-challenger"}
                ),
                result,
            )
            links.setdefault((incumbent, name), {})[f"inner-{fold}"] = {
                "path": f"chain/{incumbent}__vs__{name}/inner-{fold}",
                "comparison.json": hashes["comparison.json"],
                "sha256.json": hashlib.sha256(document_bytes(hashes)).hexdigest(),
            }
    pooled = {}
    for name, candidate in scoring.candidates.items():
        report = combine_metric_reports(
            [r.metrics for r in candidate.official.values()], seed=experiment.protocol.folds.seed
        )
        counts: dict[str, int] = defaultdict(int)
        for result in candidate.official.values():
            for key in (
                "expected_points",
                "scored_points",
                "abstained_points",
                "missing_labels",
                "insufficient_history_points",
                "predicted_origins",
            ):
                counts[key] += result.counts[key]
        pooled[name] = {
            "family": candidate.family,
            "mae": _estimate(report.mae),
            "rmse": _estimate(report.rmse),
            "interval_coverage": _estimate(report.interval_coverage),
            "mean_interval_width": _estimate(report.mean_interval_width),
            "abstention_share": abstention_share(candidate),
            "counts": dict(counts),
        }
    summary = {
        "format": "issue12-pmdata-score-1",
        **git,
        "environment_sha256": environment,
        "export_git_sha": exported["git_sha"],
        "protocol_sha256": exported["protocol_sha256"],
        "selection_rule_sha256": exported["selection_rule_sha256"],
        "adaptation_sha256": exported["adaptation_sha256"],
        "context_policy_sha256": exported["context_policy_sha256"],
        "dataset_snapshot": exported["dataset_snapshot"],
        "outer_test_sealed": True,
        "validation_participants": len({s for f in inputs.folds for s in f.validation_subjects}),
        "inner_folds": len(inputs.folds),
        "requests": exported["requests"],
        "zero_shot_predictions_sha256": forecasts.evidence["predictions_sha256"],
        "embeddings_sha256": embed_sha,
        "candidates": pooled,
        "selection": {
            "selected": log.selected,
            "rule_sha256": log.rule_sha256,
            "steps": [
                {
                    "candidate": s.candidate,
                    "incumbent": s.incumbent,
                    "status": s.status,
                    "gates": s.gates,
                    "evidence": asdict(s.challenge) if s.challenge else None,
                    "packets": links.get((s.incumbent, s.candidate), {}),
                }
                for s in log.steps
            ],
        },
        "ablations": ablations,
        "external_11": external,
        "ensemble_support": support,
        "residual_offsets": {
            n: {str(k): list(v) for k, v in c.notes.get("residual_offsets", {}).items()}
            for n, c in scoring.candidates.items()
            if c.notes.get("residual_offsets")
        },
        "finetune": None
        if FINETUNED not in scoring.candidates
        else {
            "learning_rate_selection": scoring.candidates[FINETUNED].notes[
                "learning_rate_selection"
            ],
            "receipts": {
                str(k): {
                    n: r[n]
                    for n in (
                        "hyperparameters",
                        "best",
                        "finetuned_weights_sha256",
                        "finetune_json_sha256",
                        "train_series",
                        "holdout_series",
                    )
                }
                for k, r in scoring.candidates[FINETUNED].notes["receipts"].items()
            },
        },
        "costs": costs,
        "packets_evaluation_sha256": packets,
    }
    _write_private(
        output / "aggregate-summary.json",
        (json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n").encode(),
    )
    if "subject_id" in json.dumps(summary, default=str):
        raise RuntimeError("summary must not carry participant identifiers")
    return summary


EXTERNAL_11 = {
    "ridge-handcrafted": "issue11-ridge-handcrafted",
    "ridge-handcrafted-wbm": "issue11-ridge-handcrafted-wbm",
    "ridge-handcrafted-moment": "issue11-ridge-handcrafted-moment",
    "ridge-wbm": "issue11-ridge-wbm",
    "ridge-moment": "issue11-ridge-moment",
}


def add_external_11(scoring: Scoring, parquet: Path) -> dict[str, Any]:
    """#11's out-of-fold medians as reported comparators (amendment 2), plus a tree cross-check.

    They are point forecasts without meta-fold predictions, so the predeclared interval
    method cannot apply and they are never selection candidates.
    """
    import pyarrow.parquet as pq

    inputs = scoring.inputs
    table = pq.read_table(parquet).to_pylist()
    outer = inputs.experiment.protocol.active_outer_fold
    by_model: dict[str, dict[int, stacking.Table]] = defaultdict(lambda: defaultdict(dict))
    for row in table:
        if row["outer_fold"] != outer:
            continue
        key = (row["subject_id"], row["cutoff_utc"], row["target_start_utc"])
        median = row["median"]
        by_model[row["model"]][row["inner_fold"]][key] = (
            None if median is None else stacking.Point(median, None, None, None)
        )
    mismatches = 0
    compared = 0
    mine = scoring.candidates["causal-hourly-tree-v1"].main_table
    for fold, theirs in by_model["causal-hourly-tree-v1"].items():
        for key, point in theirs.items():
            compared += 1
            other = mine[fold].get(key)
            same = (point is None and other is None) or (
                point is not None and other is not None and point.median == other.median
            )
            mismatches += not same
    for source, name in EXTERNAL_11.items():
        candidate = Candidate(name, "external")
        candidate.final = {fold: dict(t) for fold, t in by_model[source].items()}
        scoring.candidates[name] = candidate
    return {
        "source": "issue11-run-20261011T120409Z/oof-predictions.parquet",
        "sha256": file_sha256(parquet),
        "models": dict(EXTERNAL_11),
        "tree_cross_check": {"points": compared, "mismatches": mismatches},
        "role": "reported comparators only (amendment 2): published before insertion and "
        "without meta-fold predictions, so never selection candidates",
    }
