"""#12 on the frozen PMData protocol: label-free export of every GX10 input.

The harness runs over the active outer fold's three inner validation manifests and,
per amendment 1, four grouped meta manifests inside each inner fold's training
participants. Recording predictors capture each model input; no label is passed.
Outputs are opaque requests (no subject ids or cutoffs) plus fine-tune series built
only from each inner fold's TrainingPrefix.
"""

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hachi.contracts.manifests import SplitManifest
from hachi.contracts.tables import Aggregate
from hachi.data.pmdata import iter_aggregates
from hachi.evaluation import (
    EvaluationConfig,
    HourlyFeatureView,
    NestedFold,
    NestedFoldPlan,
    PredictorFactory,
    TrainingPrefix,
    evaluate_forecast,
)
from hachi.evaluation.context import ContextIndex, ContextPolicy, context_index
from hachi.evaluation.features import HourlyFeaturePolicy
from hachi.evaluation.pmdata_run import PMDataProtocol, fold_split, load_inputs
from hachi.evaluation.serialization import document_bytes, document_sha256

from ..chronos.adapter import (
    AdapterLog,
    Builder,
    ContextRequest,
    build_request,
    extended_builder,
    recording_factory,
)
from ..chronos.inference import canonical_bytes, file_sha256, request_id
from ..chronos.pmdata import ChronosPMDataConfig, check_binding, chronos_evaluation
from ..ensemble.selection import SelectionRule
from .meta import MetaPlan, meta_splits
from .ridge import RidgeConfig
from .windows import finetune_series, training_windows

REPO = Path(__file__).resolve().parents[4]
CONTEXT_HOURS = 720
# Zero-shot variants: (context hours, past-only covariates). The first is #10's model.
VARIANTS: dict[str, tuple[int, tuple[str, ...]]] = {
    "chronos-2-zero-shot": (48, ()),
    "chronos-2-zero-shot-ctx168": (168, ()),
    "chronos-2-zero-shot-ctx720": (720, ()),
    "chronos-2-zero-shot-steps": (48, ("steps",)),
}


@dataclass(frozen=True)
class Experiment:
    protocol: PMDataProtocol
    chronos: ChronosPMDataConfig
    rule: SelectionRule
    adaptation: dict[str, Any]
    meta_plan: MetaPlan
    steps_policy: HourlyFeaturePolicy

    @property
    def context_policy(self) -> ContextPolicy:
        return ContextPolicy(
            hours=CONTEXT_HOURS, channels=[self.protocol.feature_policy, self.steps_policy]
        )

    def ridge(self, kind: str) -> RidgeConfig:
        head = self.adaptation["ridge_head"]
        return RidgeConfig(
            kind=kind,
            metric=self.protocol.evaluation.metric,
            context_hours=head["context_hours"],
            horizon=self.protocol.horizon_hours,
            stride_hours=head["window_stride_hours"],
            min_context_values=self.protocol.min_history_hours,
            holdout_hours=168,
            alphas=head["alphas"],
        )


def load_experiment(root: Path = REPO) -> Experiment:
    protocol = PMDataProtocol.model_validate_json(
        (root / "configs/evaluation/pmdata-hourly-validation.json").read_bytes()
    )
    chronos = ChronosPMDataConfig.model_validate_json(
        (root / "configs/models/chronos/pmdata-hourly-hr.json").read_bytes()
    )
    rule = SelectionRule.model_validate_json(
        (root / "configs/experiments/pmdata-hourly-selection.json").read_bytes()
    )
    adaptation = json.loads(
        (root / "configs/experiments/pmdata-hourly-adaptation.json").read_text()
    )
    check_binding(protocol, chronos)
    for value, expected in (
        (rule.protocol_sha256, document_sha256(protocol)),
        (adaptation["protocol_sha256"], document_sha256(protocol)),
        (adaptation["selection_rule_sha256"], document_sha256(rule)),
    ):
        if value != expected:
            raise ValueError("experiment configs are not bound to the frozen protocol and rule")
    meta = adaptation["amendment_1"]["meta_plan"]
    steps = adaptation["history_accessor"]["steps_policy"]
    return Experiment(
        protocol,
        chronos,
        rule,
        adaptation,
        MetaPlan(
            meta_folds=meta["meta_folds"],
            seed=meta["seed"],
            window_start_utc=datetime.fromisoformat(meta["window_start_utc"]),
            window_end_utc=datetime.fromisoformat(meta["window_end_utc"]),
        ),
        HourlyFeaturePolicy(
            metric=steps["metric"],
            aggregation=steps["aggregation"],
            min_coverage=steps["min_coverage"],
            min_observed_count=steps["min_observed_count"],
            availability_rule=protocol.feature_policy.availability_rule,
        ),
    )


@dataclass(frozen=True)
class Inputs:
    experiment: Experiment
    plan: NestedFoldPlan
    folds: tuple[NestedFold, ...]
    splits: tuple[SplitManifest, ...]
    meta: tuple[tuple[SplitManifest, ...], ...]  # per inner fold
    view: HourlyFeatureView
    labels: tuple[Aggregate, ...]
    index: ContextIndex

    @property
    def evaluation(self) -> EvaluationConfig:
        return self.experiment.protocol.evaluation

    @property
    def chronos_evaluation(self) -> EvaluationConfig:
        return chronos_evaluation(self.experiment.protocol, self.experiment.chronos)

    def manifests(self) -> list[tuple[str, int, SplitManifest]]:
        """(role, inner fold, manifest) for every main and meta manifest."""
        rows = [("main", i, s) for i, s in enumerate(self.splits)]
        rows += [("meta", i, m) for i, group in enumerate(self.meta) for m in group]
        return rows

    def builder(self, variant: str) -> Builder:
        config = self.experiment.chronos.chronos
        hours, covariates = VARIANTS[variant]
        if hours == self.experiment.protocol.lookback_hours and not covariates:
            return lambda request: build_request(request, config)
        return extended_builder(
            config,
            self.index,
            context_hours=hours,
            harness_lookback_hours=self.experiment.protocol.lookback_hours,
            covariates=covariates,
        )


def prepare(snapshot: Path, experiment: Experiment) -> Inputs:
    protocol = experiment.protocol
    plan, view, labels = load_inputs(snapshot, protocol)
    folds = tuple(f for f in plan.folds if f.outer_fold == protocol.active_outer_fold)
    bins = tuple(
        iter_aggregates(
            snapshot,
            "hour",
            metrics=[protocol.evaluation.metric, experiment.steps_policy.metric],
        )
    )
    return Inputs(
        experiment,
        plan,
        folds,
        tuple(fold_split(protocol, f) for f in folds),
        tuple(meta_splits(protocol, f, experiment.meta_plan) for f in folds),
        view,
        labels,
        context_index(bins, experiment.context_policy),
    )


def _write_private(path: Path, data: bytes) -> str:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    return file_sha256(path)


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> str:
    return _write_private(path, b"".join(canonical_bytes(r) for r in rows))


def git_state() -> dict[str, Any]:
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True))
    return {"git_sha": sha, "git_dirty": dirty}


def _capture(factory: PredictorFactory, sink: dict[str, TrainingPrefix], key: str):
    def fit(training: TrainingPrefix):
        sink[key] = training
        return factory(training)

    return fit


def manifest_key(role: str, manifest: SplitManifest) -> str:
    return f"{role}:{manifest.manifest_id}"


def export(inputs: Inputs, output: Path) -> dict[str, Any]:
    """Every GX10 input for the zero-shot variants, embeddings and fine-tuning; no labels."""
    experiment = inputs.experiment
    chronos = experiment.chronos.chronos
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    forecasts: dict[str, ContextRequest] = {}
    per_variant: dict[tuple[str, str], dict[str, ContextRequest]] = {}
    prefixes: dict[str, TrainingPrefix] = {}
    counts: dict[str, dict[str, int]] = {}
    for role, _, manifest in inputs.manifests():
        key = manifest_key(role, manifest)
        for variant in VARIANTS:
            sink: dict[str, ContextRequest] = {}
            log = AdapterLog()
            factory: Callable = recording_factory(chronos, sink, log, inputs.builder(variant))
            if variant == "chronos-2-zero-shot":
                factory = _capture(factory, prefixes, key)
            evaluate_forecast(
                manifest, inputs.view.features, (), factory, inputs.chronos_evaluation
            )
            per_variant[(key, variant)] = sink
            forecasts.update(sink)
            counts[f"{key}|{variant}"] = dict(sorted(log.counts.items()))
    # Embeddings: every 48 h validation context plus every ridge training window context.
    embeds: dict[str, dict[str, Any]] = {}
    for (_, variant), sink in per_variant.items():
        if variant == "chronos-2-zero-shot":
            embeds.update({rid: r.row() for rid, r in sink.items()})
    ridge = experiment.ridge("embedding")
    windows = 0
    for prefix in prefixes.values():
        for window in training_windows(
            prefix,
            ridge.metric,
            context_hours=ridge.context_hours,
            horizon=ridge.horizon,
            stride_hours=ridge.stride_hours,
            min_context_values=ridge.min_context_values,
        ):
            rid = request_id(list(window.context), ridge.horizon)
            embeds.setdefault(
                rid,
                {
                    "request_id": rid,
                    "context": list(window.context),
                    "prediction_length": ridge.horizon,
                },
            )
            windows += 1
    files = {
        "forecast-requests.jsonl": _write_rows(
            output / "forecast-requests.jsonl", [forecasts[k].row() for k in sorted(forecasts)]
        ),
        "embed-requests.jsonl": _write_rows(
            output / "embed-requests.jsonl", [embeds[k] for k in sorted(embeds)]
        ),
    }
    # Fine-tune inputs per inner fold, from that fold's TrainingPrefix only.
    tune = experiment.adaptation["chronos_finetune"]
    finetune = {}
    for index, split in enumerate(inputs.splits):
        folder = output / "finetune" / f"inner-{index}"
        folder.mkdir(mode=0o700, parents=True)
        prefix = prefixes[manifest_key("main", split)]
        train, holdout = finetune_series(
            prefix,
            inputs.evaluation.metric,
            holdout_hours=168,
            horizon=tune["prediction_length"],
            min_target_values=12,
            min_past_values=experiment.protocol.min_history_hours,
        )
        entry = {
            "train.jsonl": _write_rows(folder / "train.jsonl", train),
            "holdout.jsonl": _write_rows(folder / "holdout.jsonl", holdout),
            "train_series": len(train),
            "holdout_series": len(holdout),
            "fit_as_of": prefix.fit_as_of.isoformat(),
        }
        for variant, (hours, covariates) in VARIANTS.items():
            if covariates:
                continue
            sink = per_variant[(manifest_key("main", split), variant)]
            entry[f"requests-{hours}.jsonl"] = _write_rows(
                folder / f"requests-{hours}.jsonl", [sink[k].row() for k in sorted(sink)]
            )
        finetune[f"inner-{index}"] = entry
    manifest = {
        "format": "issue12-pmdata-export-1",
        **git_state(),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "dataset_snapshot": experiment.protocol.expected_snapshot.model_dump(),
        "protocol_sha256": document_sha256(experiment.protocol),
        "selection_rule_sha256": document_sha256(experiment.rule),
        "adaptation_sha256": file_sha256(
            REPO / "configs/experiments/pmdata-hourly-adaptation.json"
        ),
        "chronos_config_sha256": document_sha256(experiment.chronos),
        "context_policy_sha256": document_sha256(experiment.context_policy),
        "context_counts": inputs.index.counts,
        "nested_plan_sha256": document_sha256(inputs.plan),
        "splits": {manifest_key(r, m): document_sha256(m) for r, _, m in inputs.manifests()},
        "outer_test_sealed": True,
        "labels_passed_to_harness": False,
        "variants": {
            k: {"context_hours": h, "past_covariates": list(c)} for k, (h, c) in VARIANTS.items()
        },
        "requests": {
            "forecast": len(forecasts),
            "embed": len(embeds),
            "embed_training_windows": windows,
        },
        "recording_counts": counts,
        "files": files,
        "finetune": finetune,
        "training_prefix_sha256": {k: document_sha256(v) for k, v in sorted(prefixes.items())},
    }
    _write_private(output / "export.json", document_bytes(manifest))
    return {
        **{k: manifest[k] for k in ("git_sha", "git_dirty", "requests", "files")},
        "finetune": {
            k: {n: v[n] for n in ("train_series", "holdout_series")} for k, v in finetune.items()
        },
    }
